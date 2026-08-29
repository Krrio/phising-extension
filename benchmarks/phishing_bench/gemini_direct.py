from __future__ import annotations

import hashlib
import json
import socket
import ssl
import time
import urllib.error
import urllib.request
from typing import Any

from .contracts import (
    GEMINI_INTERACTIONS_API_REVISION,
    GEMINI_INTERACTIONS_ENDPOINT,
    ContractError,
)
from .io_utils import sanitize_text
from .openai_direct import ProviderError, ProviderResponse, validated_tls_context


MAX_PROVIDER_RESPONSE_BYTES = 2 * 1024 * 1024
SAFE_RESPONSE_HEADERS = {
    "x-goog-request-id",
    "request-id",
    "retry-after",
}
INTERACTION_STATUSES = {
    "in_progress",
    "requires_action",
    "completed",
    "failed",
    "cancelled",
    "incomplete",
}
KNOWN_TOP_LEVEL_RESPONSE_KEYS = {
    "background",
    "categories",
    "confidence",
    "created",
    "data",
    "error",
    "id",
    "interaction",
    "model",
    "object",
    "outputs",
    "policyAssessment",
    "reasoning",
    "response",
    "result",
    "status",
    "steps",
    "trustScore",
    "updated",
    "usage",
    "verdict",
}


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def _safe_headers(headers: Any) -> dict[str, str]:
    if headers is None:
        return {}
    return {
        str(key).lower(): str(value)[:200]
        for key, value in headers.items()
        if str(key).lower() in SAFE_RESPONSE_HEADERS
    }


def _read_limited(handle: Any) -> bytes:
    payload = handle.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
    if len(payload) > MAX_PROVIDER_RESPONSE_BYTES:
        raise ProviderError(
            "response_too_large",
            "Gemini provider response exceeded 2 MiB",
            retryable=False,
        )
    return payload


def _safe_top_level_shape(data: dict[str, Any]) -> str:
    """Describe only protocol structure, never provider/model values."""

    string_keys = sorted(key for key in data if isinstance(key, str))
    known = sorted(set(string_keys) & KNOWN_TOP_LEVEL_RESPONSE_KEYS)
    keyset_material = json.dumps(
        string_keys,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(keyset_material).hexdigest()[:16]
    known_summary = ",".join(known) if known else "none"
    return (
        f"top_level_key_count={len(string_keys)}; "
        f"known_keys={known_summary}; keyset_sha256_prefix={digest}"
    )


def _retry_after(headers: Any) -> float | None:
    if headers is None:
        return None
    value = headers.get("Retry-After")
    if value is None:
        value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return min(max(float(value), 0.0), 900.0)
    except (TypeError, ValueError):
        return None


def _required_token_count(usage: dict[str, Any], key: str) -> int:
    value = usage.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProviderError(
            "missing_usage",
            f"Gemini usage.{key} is missing or invalid",
            retryable=False,
        )
    return value


def _optional_token_count(usage: dict[str, Any], key: str) -> int:
    value = usage.get(key, 0)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProviderError(
            "missing_usage",
            f"Gemini usage.{key} is invalid",
            retryable=False,
        )
    return value


def _mapped_usage(data: dict[str, Any]) -> dict[str, int]:
    usage_raw = data.get("usage")
    if not isinstance(usage_raw, dict):
        raise ProviderError(
            "missing_usage",
            "Gemini success response did not contain usage",
            retryable=False,
        )

    input_tokens = _required_token_count(usage_raw, "total_input_tokens")
    cached_input_tokens = _optional_token_count(usage_raw, "total_cached_tokens")
    visible_output_tokens = _required_token_count(usage_raw, "total_output_tokens")
    thought_tokens = _optional_token_count(usage_raw, "total_thought_tokens")
    total_tokens = _required_token_count(usage_raw, "total_tokens")
    billed_output_tokens = visible_output_tokens + thought_tokens

    if (
        input_tokens <= 0
        or cached_input_tokens > input_tokens
        or total_tokens < input_tokens + billed_output_tokens
    ):
        raise ProviderError(
            "missing_usage",
            "Gemini usage token counts are internally inconsistent",
            retryable=False,
        )

    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        # Gemini bills visible output and thinking at the output-token rate.
        "output_tokens": billed_output_tokens,
        "reasoning_tokens": thought_tokens,
        "total_tokens": total_tokens,
    }


def _is_tool_step(step_type: str) -> bool:
    return (
        step_type in {"function_call", "function_result"}
        or step_type.startswith("tool_")
        or step_type.endswith("_call")
        or step_type.endswith("_result")
    )


def _parse_steps(data: dict[str, Any], status: str) -> tuple[str, bool]:
    steps = data.get("steps")
    if not isinstance(steps, list):
        raise ProviderError(
            "invalid_provider_response",
            "Gemini response steps are missing or invalid",
            retryable=False,
        )

    tool_calls_present = False
    last_model_output: dict[str, Any] | None = None
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get("type"), str):
            raise ProviderError(
                "invalid_provider_response",
                "Gemini response contains an invalid step",
                retryable=False,
            )
        step_type = step["type"]
        tool_calls_present = tool_calls_present or _is_tool_step(step_type)
        if step_type == "model_output":
            last_model_output = step

    content = ""
    if last_model_output is not None:
        blocks = last_model_output.get("content")
        if not isinstance(blocks, list):
            raise ProviderError(
                "invalid_provider_response",
                "Gemini model_output content is missing or invalid",
                retryable=False,
            )
        text_parts: list[str] = []
        for block in blocks:
            if not isinstance(block, dict) or not isinstance(block.get("type"), str):
                raise ProviderError(
                    "invalid_provider_response",
                    "Gemini model_output contains an invalid content block",
                    retryable=False,
                )
            if block["type"] == "text":
                text = block.get("text")
                if not isinstance(text, str):
                    raise ProviderError(
                        "invalid_provider_response",
                        "Gemini model_output text block has no text",
                        retryable=False,
                    )
                text_parts.append(text)
        content = "".join(text_parts)

    if status == "completed" and not content and not tool_calls_present:
        raise ProviderError(
            "invalid_provider_response",
            "Gemini completed response contained no model_output text",
            retryable=False,
        )
    return content, tool_calls_present


class GeminiInteractionsTransport:
    """Single-attempt transport for the pinned Gemini Interactions v1 endpoint."""

    def __init__(self) -> None:
        # Ignore environment proxy variables so egress remains direct and auditable.
        tls_context = validated_tls_context()
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=tls_context),
            _RejectRedirects(),
        )

    def call(
        self,
        *,
        api_key: str,
        endpoint: str,
        body: dict[str, Any],
        timeout_seconds: float,
    ) -> ProviderResponse:
        if endpoint != GEMINI_INTERACTIONS_ENDPOINT:
            raise ContractError("transport rejected non-allowlisted Gemini endpoint")
        requested_model = body.get("model")
        if not isinstance(requested_model, str) or not requested_model:
            raise ContractError("Gemini request body.model must be a non-empty string")

        encoded_body = json.dumps(
            body,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=encoded_body,
            method="POST",
            headers={
                "x-goog-api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Api-Revision": GEMINI_INTERACTIONS_API_REVISION,
                "User-Agent": "phishing-extension-benchmark/0.1",
            },
        )
        started = time.monotonic()
        response_status: int | None = None
        try:
            with self._opener.open(request, timeout=timeout_seconds) as response:
                raw = _read_limited(response)
                headers = _safe_headers(response.headers)
                status_value = getattr(response, "status", None)
                if isinstance(status_value, int) and not isinstance(status_value, bool):
                    response_status = status_value
        except urllib.error.HTTPError as exc:
            # Consume a bounded body for connection hygiene, but never parse, echo, or log it.
            _read_limited(exc)
            status_code = int(exc.code)
            retryable = status_code in {408, 429} or 500 <= status_code <= 599
            kind = (
                "timeout"
                if status_code == 408
                else "rate_limit"
                if status_code == 429
                else "provider_http_error"
            )
            raise ProviderError(
                kind,
                f"Gemini returned HTTP {status_code}",
                status_code=status_code,
                retryable=retryable,
                retry_after_seconds=_retry_after(exc.headers),
                response_headers=_safe_headers(exc.headers),
            ) from None
        except (TimeoutError, socket.timeout) as exc:
            raise ProviderError(
                "timeout",
                "Gemini request timed out",
                retryable=True,
            ) from exc
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise ProviderError(
                    "timeout",
                    "Gemini request timed out",
                    retryable=True,
                ) from exc
            if isinstance(reason, ssl.SSLCertVerificationError):
                verify_code = getattr(reason, "verify_code", None)
                code_suffix = (
                    f" (verify_code={verify_code})"
                    if verify_code is not None
                    else ""
                )
                raise ProviderError(
                    "tls_certificate_error",
                    "TLS certificate verification failed"
                    + code_suffix
                    + "; repair the Python CA trust store; never disable verification",
                    retryable=False,
                ) from exc
            raise ProviderError(
                "network_error",
                sanitize_text("Gemini network request failed", (api_key,)),
                retryable=True,
            ) from exc

        elapsed_ms = (time.monotonic() - started) * 1000
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderError(
                "invalid_provider_json",
                "Gemini returned invalid JSON",
                status_code=response_status,
                retryable=False,
                response_headers=headers,
            ) from exc
        if not isinstance(data, dict):
            raise ProviderError(
                "invalid_provider_response",
                "Gemini response is not an object",
                status_code=response_status,
                retryable=False,
                response_headers=headers,
            )

        response_id = data.get("id")
        resolved_model = data.get("model")
        status = data.get("status")
        if not isinstance(response_id, str) or not response_id:
            raise ProviderError(
                "invalid_provider_response",
                "Gemini response id is missing or invalid; "
                + _safe_top_level_shape(data),
                status_code=response_status,
                retryable=False,
                response_headers=headers,
            )
        if not isinstance(resolved_model, str) or not resolved_model:
            raise ProviderError(
                "invalid_provider_response",
                "Gemini response model is missing or invalid; "
                + _safe_top_level_shape(data),
                status_code=response_status,
                retryable=False,
                response_headers=headers,
            )
        if not isinstance(status, str) or status not in INTERACTION_STATUSES:
            raise ProviderError(
                "invalid_provider_response",
                "Gemini response status is missing or invalid; "
                + _safe_top_level_shape(data),
                status_code=response_status,
                retryable=False,
                response_headers=headers,
            )

        try:
            content, tool_calls_present = _parse_steps(data, status)
            usage = _mapped_usage(data)
        except ProviderError as exc:
            raise ProviderError(
                exc.kind,
                str(exc) + "; " + _safe_top_level_shape(data),
                status_code=response_status,
                retryable=False,
                response_headers=headers,
            ) from exc
        finish_reason = {
            "completed": "stop",
            "incomplete": "incomplete",
        }.get(status, status)
        return ProviderResponse(
            response_id=response_id,
            requested_model=requested_model,
            resolved_model=resolved_model,
            content=content,
            finish_reason=finish_reason,
            refusal=None,
            tool_calls_present=tool_calls_present,
            usage=usage,
            safe_headers=headers,
            elapsed_ms=elapsed_ms,
            raw_response_sha256_material=raw,
        )
