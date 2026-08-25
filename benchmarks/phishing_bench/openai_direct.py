from __future__ import annotations

import json
import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .contracts import OPENAI_CHAT_COMPLETIONS_ENDPOINT, ContractError
from .io_utils import sanitize_text


MAX_PROVIDER_RESPONSE_BYTES = 2 * 1024 * 1024
SAFE_RESPONSE_HEADERS = {
    "x-request-id",
    "openai-processing-ms",
    "x-ratelimit-limit-requests",
    "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-requests",
    "x-ratelimit-remaining-tokens",
    "x-ratelimit-reset-requests",
    "x-ratelimit-reset-tokens",
}


class ProviderError(RuntimeError):
    def __init__(
        self,
        kind: str,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        retry_after_seconds: float | None = None,
        response_headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.response_headers = response_headers or {}


@dataclass(frozen=True)
class ProviderResponse:
    response_id: str | None
    requested_model: str
    resolved_model: str | None
    content: str
    finish_reason: str | None
    refusal: str | None
    tool_calls_present: bool
    usage: dict[str, int]
    safe_headers: dict[str, str]
    elapsed_ms: float
    raw_response_sha256_material: bytes


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def _safe_headers(headers: Any) -> dict[str, str]:
    return {
        key.lower(): str(value)[:200]
        for key, value in headers.items()
        if key.lower() in SAFE_RESPONSE_HEADERS
    }


def _read_limited(handle: Any) -> bytes:
    payload = handle.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
    if len(payload) > MAX_PROVIDER_RESPONSE_BYTES:
        raise ProviderError("response_too_large", "provider response exceeded 2 MiB")
    return payload


def _retry_after(headers: Any) -> float | None:
    value = headers.get("Retry-After") if headers else None
    if value is None:
        return None
    try:
        return min(max(float(value), 0.0), 900.0)
    except (TypeError, ValueError):
        return None


def _provider_error_summary(raw: bytes, status: int) -> str:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return f"OpenAI returned HTTP {status}"
    error = value.get("error") if isinstance(value, dict) else None
    if not isinstance(error, dict):
        return f"OpenAI returned HTTP {status}"
    safe_parts = [
        str(error[key])[:100]
        for key in ("type", "code")
        if isinstance(error.get(key), (str, int))
    ]
    suffix = f" ({'/'.join(safe_parts)})" if safe_parts else ""
    return f"OpenAI returned HTTP {status}{suffix}"


def validated_tls_context() -> ssl.SSLContext:
    """Build a verified client context and fail before egress if no CA is loaded."""
    context = ssl.create_default_context()
    ca_count = int(context.cert_store_stats().get("x509_ca", 0))
    if (
        ca_count <= 0
        or not context.check_hostname
        or context.verify_mode != ssl.CERT_REQUIRED
    ):
        raise ContractError(
            "Python TLS trust store has no trusted CA certificates or verification is disabled; "
            "install/configure an approved CA bundle and rerun validate; never disable TLS verification"
        )
    return context


def tls_trust_summary() -> dict[str, Any]:
    context = validated_tls_context()
    stats = context.cert_store_stats()
    return {
        "ca_certificates": int(stats.get("x509_ca", 0)),
        "certificate_verification": "CERT_REQUIRED",
        "hostname_verification": True,
        "environment_proxy_enabled": False,
    }


class OpenAIChatTransport:
    """Single-attempt transport. Retry policy lives in the auditable runner."""

    def __init__(self) -> None:
        # Environment proxies are deliberately disabled for the pinned direct-egress smoke.
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
        if endpoint != OPENAI_CHAT_COMPLETIONS_ENDPOINT:
            raise ContractError("transport rejected non-allowlisted endpoint")
        encoded_body = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=encoded_body,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "phishing-extension-benchmark/0.1",
            },
        )
        started = time.monotonic()
        try:
            with self._opener.open(request, timeout=timeout_seconds) as response:
                raw = _read_limited(response)
                headers = _safe_headers(response.headers)
        except urllib.error.HTTPError as exc:
            raw_error = _read_limited(exc)
            status = int(exc.code)
            retryable = status == 429 or 500 <= status <= 599
            kind = "rate_limit" if status == 429 else "provider_http_error"
            raise ProviderError(
                kind,
                _provider_error_summary(raw_error, status),
                status_code=status,
                retryable=retryable,
                retry_after_seconds=_retry_after(exc.headers),
                response_headers=_safe_headers(exc.headers),
            ) from None
        except (TimeoutError, socket.timeout) as exc:
            raise ProviderError("timeout", "OpenAI request timed out", retryable=True) from exc
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise ProviderError("timeout", "OpenAI request timed out", retryable=True) from exc
            if isinstance(reason, ssl.SSLCertVerificationError):
                verify_code = getattr(reason, "verify_code", None)
                code_suffix = f" (verify_code={verify_code})" if verify_code is not None else ""
                raise ProviderError(
                    "tls_certificate_error",
                    "TLS certificate verification failed"
                    + code_suffix
                    + "; repair the Python CA trust store; never disable verification",
                    retryable=False,
                ) from exc
            raise ProviderError(
                "network_error",
                sanitize_text(str(reason), (api_key,)),
                retryable=True,
            ) from exc
        elapsed_ms = (time.monotonic() - started) * 1000
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderError("invalid_provider_json", f"OpenAI returned invalid JSON: {exc.msg}", retryable=True) from exc
        if not isinstance(data, dict):
            raise ProviderError("invalid_provider_response", "OpenAI response is not an object", retryable=True)
        choices = data.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise ProviderError("invalid_provider_response", "OpenAI response must contain exactly one choice", retryable=True)
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict):
            raise ProviderError("invalid_provider_response", "OpenAI choice has no message", retryable=True)
        content = message.get("content")
        refusal = message.get("refusal")
        tool_calls_present = bool(message.get("tool_calls") or message.get("function_call"))
        if refusal:
            raise ProviderError("refusal", "OpenAI model returned a refusal", retryable=False)
        if not isinstance(content, str):
            if tool_calls_present:
                content = ""
            else:
                raise ProviderError("invalid_provider_response", "OpenAI message content is not text", retryable=True)
        usage_raw = data.get("usage")
        if not isinstance(usage_raw, dict):
            raise ProviderError(
                "missing_usage",
                "OpenAI success response did not contain usage",
                retryable=True,
            )
        prompt_details = (
            usage_raw.get("prompt_tokens_details")
            if isinstance(usage_raw.get("prompt_tokens_details"), dict)
            else {}
        )
        completion_details = (
            usage_raw.get("completion_tokens_details")
            if isinstance(usage_raw.get("completion_tokens_details"), dict)
            else {}
        )

        def optional_token_count(container: dict[str, Any], key: str) -> int:
            value = container.get(key, 0)
            return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

        def required_token_count(key: str) -> int:
            value = usage_raw.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ProviderError(
                    "missing_usage",
                    f"OpenAI usage.{key} is missing or invalid",
                    retryable=True,
                )
            return value

        usage = {
            "input_tokens": required_token_count("prompt_tokens"),
            "cached_input_tokens": optional_token_count(prompt_details, "cached_tokens"),
            "output_tokens": required_token_count("completion_tokens"),
            "reasoning_tokens": optional_token_count(completion_details, "reasoning_tokens"),
            "total_tokens": required_token_count("total_tokens"),
        }
        if (
            usage["input_tokens"] <= 0
            or usage["output_tokens"] <= 0
            or usage["cached_input_tokens"] > usage["input_tokens"]
            or usage["total_tokens"] < usage["input_tokens"] + usage["output_tokens"]
        ):
            raise ProviderError(
                "missing_usage",
                "OpenAI usage token counts are internally inconsistent",
                retryable=True,
            )
        return ProviderResponse(
            response_id=data.get("id") if isinstance(data.get("id"), str) else None,
            requested_model=str(body["model"]),
            resolved_model=data.get("model") if isinstance(data.get("model"), str) else None,
            content=content,
            finish_reason=choice.get("finish_reason") if isinstance(choice.get("finish_reason"), str) else None,
            refusal=None,
            tool_calls_present=tool_calls_present,
            usage=usage,
            safe_headers=headers,
            elapsed_ms=elapsed_ms,
            raw_response_sha256_material=raw,
        )
