from __future__ import annotations

import io
import json
import os
import ssl
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "benchmarks"))

from phishing_bench.contracts import (
    GEMINI_INTERACTIONS_API_REVISION,
    GEMINI_INTERACTIONS_ENDPOINT,
    ContractError,
)
from phishing_bench.gemini_direct import GeminiInteractionsTransport
from phishing_bench.openai_direct import ProviderError


FAKE_KEY = "synthetic-gemini-key-never-live"
MODEL = "gemini-3.5-flash-lite"


class _Response(io.BytesIO):
    def __init__(
        self,
        value: dict[str, Any],
        headers: dict[str, str] | None = None,
        status: int = 200,
    ) -> None:
        super().__init__(json.dumps(value).encode("utf-8"))
        self.headers = headers or {}
        self.status = status

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def _interaction(
    *,
    status: str = "completed",
    steps: list[dict[str, Any]] | None = None,
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if steps is None:
        steps = [
            {
                "type": "model_output",
                "content": [
                    {"type": "text", "text": '{"verdict":"safe"}'},
                ],
            }
        ]
    if usage is None:
        usage = {
            "total_input_tokens": 18,
            "total_cached_tokens": 2,
            "total_output_tokens": 7,
            "total_thought_tokens": 3,
            "total_tokens": 28,
        }
    return {
        "id": "int_synthetic",
        "model": MODEL,
        "status": status,
        "steps": steps,
        "usage": usage,
    }


def _transport() -> GeminiInteractionsTransport:
    with patch(
        "phishing_bench.gemini_direct.validated_tls_context",
        return_value=ssl.create_default_context(),
    ):
        return GeminiInteractionsTransport()


class GeminiTransportTests(unittest.TestCase):
    def test_completed_response_maps_text_usage_headers_and_auth(self) -> None:
        transport = _transport()
        captured: dict[str, Any] = {}

        def open_request(request: urllib.request.Request, timeout: float) -> _Response:
            captured["request"] = request
            captured["timeout"] = timeout
            return _Response(
                _interaction(),
                {
                    "X-Goog-Request-Id": "goog-request",
                    "Request-Id": "generic-request",
                    "Retry-After": "1.5",
                    "Set-Cookie": "not-safe",
                },
            )

        transport._opener.open = open_request  # type: ignore[method-assign]
        response = transport.call(
            api_key=FAKE_KEY,
            endpoint=GEMINI_INTERACTIONS_ENDPOINT,
            body={"model": MODEL, "input": "synthetic"},
            timeout_seconds=12,
        )

        self.assertEqual(response.response_id, "int_synthetic")
        self.assertEqual(response.requested_model, MODEL)
        self.assertEqual(response.resolved_model, MODEL)
        self.assertEqual(response.content, '{"verdict":"safe"}')
        self.assertEqual(response.finish_reason, "stop")
        self.assertFalse(response.tool_calls_present)
        self.assertEqual(
            response.usage,
            {
                "input_tokens": 18,
                "cached_input_tokens": 2,
                "output_tokens": 10,
                "reasoning_tokens": 3,
                "total_tokens": 28,
            },
        )
        self.assertEqual(
            response.safe_headers,
            {
                "x-goog-request-id": "goog-request",
                "request-id": "generic-request",
                "retry-after": "1.5",
            },
        )

        request = captured["request"]
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["x-goog-api-key"], FAKE_KEY)
        self.assertEqual(headers["api-revision"], GEMINI_INTERACTIONS_API_REVISION)
        self.assertNotIn("authorization", headers)
        self.assertNotIn(FAKE_KEY, request.full_url)
        self.assertNotIn(FAKE_KEY.encode("utf-8"), request.data)
        self.assertEqual(captured["timeout"], 12)

    def test_last_model_output_is_used_and_incomplete_is_preserved(self) -> None:
        transport = _transport()
        transport._opener.open = lambda *args, **kwargs: _Response(  # type: ignore[method-assign]
            _interaction(
                status="incomplete",
                steps=[
                    {
                        "type": "model_output",
                        "content": [{"type": "text", "text": "old"}],
                    },
                    {"type": "thought", "summary": []},
                    {
                        "type": "model_output",
                        "content": [
                            {"type": "text", "text": "new"},
                            {"type": "text", "text": " output"},
                        ],
                    },
                ],
            )
        )
        response = transport.call(
            api_key=FAKE_KEY,
            endpoint=GEMINI_INTERACTIONS_ENDPOINT,
            body={"model": MODEL},
            timeout_seconds=1,
        )
        self.assertEqual(response.content, "new output")
        self.assertEqual(response.finish_reason, "incomplete")

    def test_function_and_server_tool_steps_are_detected(self) -> None:
        for step_type in ("function_call", "tool_call", "google_search_call"):
            with self.subTest(step_type=step_type):
                transport = _transport()
                transport._opener.open = lambda *args, **kwargs: _Response(  # type: ignore[method-assign]
                    _interaction(
                        status="requires_action",
                        steps=[{"type": step_type}],
                    )
                )
                response = transport.call(
                    api_key=FAKE_KEY,
                    endpoint=GEMINI_INTERACTIONS_ENDPOINT,
                    body={"model": MODEL},
                    timeout_seconds=1,
                )
                self.assertTrue(response.tool_calls_present)
                self.assertEqual(response.content, "")
                self.assertEqual(response.finish_reason, "requires_action")

    def test_missing_or_inconsistent_usage_fails_closed(self) -> None:
        invalid_usage_values = (
            None,
            {
                "total_input_tokens": 18,
                "total_cached_tokens": 19,
                "total_output_tokens": 7,
                "total_thought_tokens": 3,
                "total_tokens": 28,
            },
            {
                "total_input_tokens": 18,
                "total_cached_tokens": 2,
                "total_output_tokens": 7,
                "total_thought_tokens": 3,
                "total_tokens": 20,
            },
        )
        for usage in invalid_usage_values:
            with self.subTest(usage=usage):
                value = _interaction()
                value["usage"] = usage
                transport = _transport()
                transport._opener.open = lambda *args, **kwargs: _Response(value)  # type: ignore[method-assign]
                with self.assertRaises(ProviderError) as captured:
                    transport.call(
                        api_key=FAKE_KEY,
                        endpoint=GEMINI_INTERACTIONS_ENDPOINT,
                        body={"model": MODEL},
                        timeout_seconds=1,
                    )
                self.assertEqual(captured.exception.kind, "missing_usage")
                self.assertFalse(captured.exception.retryable)
                self.assertEqual(captured.exception.status_code, 200)
                self.assertIn(
                    "known_keys=id,model,status,steps,usage",
                    str(captured.exception),
                )

    def test_missing_id_reports_only_a_safe_structural_fingerprint(self) -> None:
        secret_value = "provider-value-that-must-never-be-logged"
        transport = _transport()
        transport._opener.open = lambda *args, **kwargs: _Response(  # type: ignore[method-assign]
            {
                "response": {"private": secret_value},
                "verdict": secret_value,
                "opaque_provider_key": secret_value,
            },
            {"X-Goog-Request-Id": "safe-diagnostic-request-id"},
        )

        with self.assertRaises(ProviderError) as captured:
            transport.call(
                api_key=FAKE_KEY,
                endpoint=GEMINI_INTERACTIONS_ENDPOINT,
                body={"model": MODEL},
                timeout_seconds=1,
            )

        provider_error = captured.exception
        message = str(provider_error)
        self.assertEqual(provider_error.kind, "invalid_provider_response")
        self.assertEqual(provider_error.status_code, 200)
        self.assertEqual(
            provider_error.response_headers,
            {"x-goog-request-id": "safe-diagnostic-request-id"},
        )
        self.assertFalse(provider_error.retryable)
        self.assertIn("top_level_key_count=3", message)
        self.assertIn("known_keys=response,verdict", message)
        self.assertRegex(message, r"keyset_sha256_prefix=[0-9a-f]{16}")
        self.assertNotIn("opaque_provider_key", message)
        self.assertNotIn(secret_value, message)

    def test_omitted_zero_cache_and_thought_counts_are_normalized(self) -> None:
        transport = _transport()
        transport._opener.open = lambda *args, **kwargs: _Response(  # type: ignore[method-assign]
            _interaction(
                usage={
                    "total_input_tokens": 18,
                    "total_output_tokens": 7,
                    "total_tokens": 25,
                }
            )
        )
        response = transport.call(
            api_key=FAKE_KEY,
            endpoint=GEMINI_INTERACTIONS_ENDPOINT,
            body={"model": MODEL},
            timeout_seconds=1,
        )
        self.assertEqual(
            response.usage,
            {
                "input_tokens": 18,
                "cached_input_tokens": 0,
                "output_tokens": 7,
                "reasoning_tokens": 0,
                "total_tokens": 25,
            },
        )

    def test_http_error_is_generic_redacted_and_retry_policy_is_exact(self) -> None:
        cases = ((408, True), (429, True), (500, True), (599, True), (400, False))
        for status_code, retryable in cases:
            with self.subTest(status_code=status_code):
                transport = _transport()
                error = urllib.error.HTTPError(
                    GEMINI_INTERACTIONS_ENDPOINT,
                    status_code,
                    "synthetic",
                    {"Retry-After": "2", "X-Goog-Request-Id": "request"},
                    io.BytesIO(
                        json.dumps(
                            {"error": {"message": "private body " + FAKE_KEY}}
                        ).encode("utf-8")
                    ),
                )
                transport._opener.open = lambda *args, **kwargs: (_ for _ in ()).throw(error)  # type: ignore[method-assign]
                with self.assertRaises(ProviderError) as captured:
                    transport.call(
                        api_key=FAKE_KEY,
                        endpoint=GEMINI_INTERACTIONS_ENDPOINT,
                        body={"model": MODEL},
                        timeout_seconds=1,
                    )
                provider_error = captured.exception
                self.assertEqual(provider_error.status_code, status_code)
                self.assertEqual(provider_error.retryable, retryable)
                self.assertNotIn(FAKE_KEY, str(provider_error))
                self.assertNotIn("private body", str(provider_error))
                self.assertEqual(provider_error.retry_after_seconds, 2)
                self.assertEqual(
                    provider_error.response_headers["x-goog-request-id"],
                    "request",
                )

    def test_endpoint_is_allowlisted_and_environment_proxy_is_disabled(self) -> None:
        with patch.dict(
            os.environ,
            {"HTTPS_PROXY": "http://proxy.attacker.invalid:8080"},
        ), patch(
            "phishing_bench.gemini_direct.validated_tls_context",
            return_value=ssl.create_default_context(),
        ):
            transport = GeminiInteractionsTransport()
        proxy_handlers = [
            handler
            for handler in transport._opener.handlers
            if isinstance(handler, urllib.request.ProxyHandler)
        ]
        self.assertEqual(proxy_handlers, [])
        with self.assertRaisesRegex(ContractError, "non-allowlisted"):
            transport.call(
                api_key=FAKE_KEY,
                endpoint="https://example.invalid/v1/interactions",
                body={"model": MODEL},
                timeout_seconds=1,
            )


if __name__ == "__main__":
    unittest.main()
