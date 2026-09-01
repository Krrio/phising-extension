from __future__ import annotations

import io
import json
import ssl
import sys
import tempfile
import unittest
import urllib.request
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"
sys.path.insert(0, str(BENCHMARKS_DIR))

from phishing_bench.contracts import (  # noqa: E402
    GEMINI37_NATIVE_QUALITY_PILOT_PROFILE,
    GEMINI37_NATIVE_SMOKE_PROFILE,
    GEMINI_GENERATE_CONTENT_ENDPOINTS,
    GEMINI_GENERATE_CONTENT_LOW_REQUEST_PROFILE,
    ContractError,
    build_chat_request,
    campaign_live_block_reason,
    load_and_validate_campaign,
    validate_outgoing_request,
    validate_runtime_config,
)
from phishing_bench.gemini_direct import GeminiGenerateContentTransport  # noqa: E402
from phishing_bench.io_utils import read_json, read_jsonl  # noqa: E402
from phishing_bench.openai_direct import ProviderError, ProviderResponse  # noqa: E402
from phishing_bench.runner import readiness_report, run_campaign  # noqa: E402
from phishing_bench.scoring import score_run  # noqa: E402


SMOKE_ID = "BUDGET_30H_GOOGLE_NATIVE_GEMINI37_FLASH_SMOKE_001"
PILOT_ID = "BUDGET_30H_GOOGLE_NATIVE_GEMINI37_FLASH_PILOT_030_001"
SMOKE_CONFIG = BENCHMARKS_DIR / "campaigns" / SMOKE_ID / "runtime_config.json"
PILOT_CONFIG = BENCHMARKS_DIR / "campaigns" / PILOT_ID / "runtime_config.json"
CREW_SMOKE_CONFIG = (
    BENCHMARKS_DIR
    / "campaigns"
    / "BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_SMOKE_001"
    / "runtime_config.json"
)
SMOKE_LABELS = (
    BENCHMARKS_DIR / "secure_scoring" / "openai_smoke_v1" / "labels.jsonl"
)
SMOKE_MANIFEST = (
    BENCHMARKS_DIR
    / "secure_scoring"
    / "openai_smoke_v1"
    / "scoring_manifest.json"
)
PILOT_MANIFEST = (
    BENCHMARKS_DIR
    / "secure_scoring"
    / "openai_pilot_030_v1"
    / "scoring_manifest.json"
)
MODEL = "gemini-3.7-flash"
ENDPOINT = GEMINI_GENERATE_CONTENT_ENDPOINTS[MODEL]
FAKE_KEY = "synthetic-gemini-native-key-never-live"


def _output(malicious: bool) -> dict[str, Any]:
    return {
        "trustScore": 10 if malicious else 95,
        "verdict": "phishing" if malicious else "safe",
        "confidence": 0.95,
        "reasoning": "Syntetyczne uzasadnienie testowe Gemini native.",
        "categories": ["impersonation"] if malicious else [],
        "policyAssessment": None,
    }


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


def _native_response() -> dict[str, Any]:
    return {
        "responseId": "native-response-synthetic",
        "modelVersion": MODEL,
        "candidates": [
            {
                "index": 0,
                "finishReason": "STOP",
                "content": {
                    "role": "model",
                    "parts": [
                        {"thought": True, "text": "hidden synthetic thought"},
                        {"text": json.dumps(_output(False), ensure_ascii=False)},
                    ],
                },
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 100,
            "cachedContentTokenCount": 10,
            "candidatesTokenCount": 20,
            "thoughtsTokenCount": 5,
            "totalTokenCount": 125,
        },
    }


def _transport() -> GeminiGenerateContentTransport:
    with patch(
        "phishing_bench.gemini_direct.validated_tls_context",
        return_value=ssl.create_default_context(),
    ):
        return GeminiGenerateContentTransport()


class FakeNativeTransport:
    def __init__(
        self,
        plans: list[dict[str, Any]] | None = None,
        error: ProviderError | None = None,
    ) -> None:
        self.plans = list(plans or [])
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def call(
        self,
        *,
        api_key: str,
        endpoint: str,
        body: dict[str, Any],
        timeout_seconds: float,
    ) -> ProviderResponse:
        del api_key
        self.calls.append(
            {"endpoint": endpoint, "body": body, "timeout": timeout_seconds}
        )
        if self.error is not None:
            raise self.error
        content = json.dumps(self.plans.pop(0), ensure_ascii=False)
        return ProviderResponse(
            response_id=f"native-fake-{len(self.calls)}",
            requested_model=MODEL,
            resolved_model=MODEL,
            content=content,
            finish_reason="stop",
            refusal=None,
            tool_calls_present=False,
            usage={
                "input_tokens": 100,
                "cached_input_tokens": 10,
                "output_tokens": 25,
                "reasoning_tokens": 5,
                "total_tokens": 125,
            },
            safe_headers={"x-goog-request-id": f"native-{len(self.calls)}"},
            elapsed_ms=10.0,
            raw_response_sha256_material=content.encode("utf-8"),
        )


class GeminiNativeDirectContractTests(unittest.TestCase):
    def test_smoke_and_pilot_freeze_matching_direct_assets(self) -> None:
        smoke, smoke_assets = load_and_validate_campaign(SMOKE_CONFIG, REPO_ROOT)
        pilot, pilot_assets = load_and_validate_campaign(PILOT_CONFIG, REPO_ROOT)
        crew, crew_assets = load_and_validate_campaign(CREW_SMOKE_CONFIG, REPO_ROOT)

        self.assertEqual(smoke["evaluation_profile"], GEMINI37_NATIVE_SMOKE_PROFILE)
        self.assertEqual(
            pilot["evaluation_profile"], GEMINI37_NATIVE_QUALITY_PILOT_PROFILE
        )
        self.assertEqual(smoke["adapter"], "gemini_generate_content")
        self.assertEqual(smoke["endpoint"], ENDPOINT)
        self.assertEqual(smoke["requested_model"], MODEL)
        self.assertEqual(
            smoke["request_profile"], GEMINI_GENERATE_CONTENT_LOW_REQUEST_PROFILE
        )
        self.assertEqual(smoke["expected_sample_count"], 5)
        self.assertEqual(pilot["expected_sample_count"], 30)
        self.assertEqual(smoke["max_retries_per_sample"], 0)
        self.assertEqual(pilot["max_retries_per_sample"], 0)
        self.assertEqual(smoke["request_timeout_seconds"], 120)
        self.assertEqual(pilot["request_timeout_seconds"], 120)
        self.assertEqual(smoke_assets["dataset"], crew_assets["dataset"])
        self.assertEqual(
            smoke_assets["response_schema"], crew_assets["response_schema"]
        )
        self.assertEqual(
            smoke_assets["decision_policy"], crew_assets["decision_policy"]
        )
        self.assertEqual(len(pilot_assets["dataset"]), 30)

        self.assertIsNone(campaign_live_block_reason(smoke))
        self.assertIn("prerequisite", campaign_live_block_reason(pilot) or "")
        self.assertIn(
            SMOKE_ID, read_json(SMOKE_MANIFEST)["compatible_campaign_ids"]
        )
        self.assertIn(
            PILOT_ID, read_json(PILOT_MANIFEST)["compatible_campaign_ids"]
        )

    def test_readiness_exposes_native_contract_and_blocks_only_pilot(self) -> None:
        smoke_report = readiness_report(SMOKE_CONFIG, REPO_ROOT)
        pilot_report = readiness_report(PILOT_CONFIG, REPO_ROOT)

        self.assertEqual(
            smoke_report["status"], "READY_FOR_MANUAL_LIVE_CONFIRMATION"
        )
        self.assertEqual(pilot_report["status"], "LIVE_BLOCKED")
        self.assertEqual(
            smoke_report["request_contract"],
            {
                "request_profile": GEMINI_GENERATE_CONTENT_LOW_REQUEST_PROFILE,
                "provider_api": "native_generate_content_v1",
                "instruction_role": "systemInstruction",
                "token_limit_field": "generationConfig.maxOutputTokens",
                "thinking_level": "low",
                "seed": 0,
                "temperature": None,
                "response_id_policy": "required",
            },
        )
        self.assertEqual(smoke_report["security_contract"]["store"], False)
        self.assertEqual(smoke_report["security_contract"]["tools"], "absent")
        self.assertEqual(
            smoke_report["security_contract"]["provider_api"],
            "native_generate_content_v1",
        )
        self.assertLessEqual(
            smoke_report["required_cost_cap_with_margin_usd"], 0.05
        )

    def test_request_envelope_is_exact_and_drift_fails_closed(self) -> None:
        config, assets = load_and_validate_campaign(SMOKE_CONFIG, REPO_ROOT)
        body = build_chat_request(
            config,
            assets["dataset"][0],
            assets["prompt"],
            assets["response_schema"],
        )

        self.assertEqual(
            set(body), {"systemInstruction", "contents", "generationConfig", "store"}
        )
        self.assertFalse(body["store"])
        self.assertEqual(
            body["generationConfig"]["thinkingConfig"],
            {"thinkingLevel": "LOW", "includeThoughts": False},
        )
        self.assertEqual(body["generationConfig"]["seed"], 0)
        self.assertEqual(
            body["generationConfig"]["responseMimeType"], "application/json"
        )
        self.assertNotIn("model", body)
        self.assertNotIn("tools", body)
        self.assertNotIn("temperature", body["generationConfig"])

        body_mutations = (
            ("store", lambda value: value.__setitem__("store", True)),
            ("tools", lambda value: value.__setitem__("tools", [])),
            (
                "thinking",
                lambda value: value["generationConfig"]["thinkingConfig"].__setitem__(
                    "thinkingLevel", "MEDIUM"
                ),
            ),
            (
                "thoughts",
                lambda value: value["generationConfig"]["thinkingConfig"].__setitem__(
                    "includeThoughts", True
                ),
            ),
            (
                "temperature",
                lambda value: value["generationConfig"].__setitem__(
                    "temperature", 0
                ),
            ),
            (
                "schema",
                lambda value: value["generationConfig"].__setitem__(
                    "responseJsonSchema",
                    {"type": "object", "additionalProperties": True},
                ),
            ),
        )
        for name, mutate in body_mutations:
            with self.subTest(payload=name):
                changed = deepcopy(body)
                mutate(changed)
                with self.assertRaises(ContractError):
                    validate_outgoing_request(config, changed)

        config_mutations = (
            ("adapter", lambda value: value.__setitem__("adapter", "gemini_interactions")),
            (
                "endpoint",
                lambda value: value.__setitem__(
                    "endpoint", "https://example.invalid/v1/models/x:generateContent"
                ),
            ),
            ("model", lambda value: value.__setitem__("requested_model", MODEL + "-preview")),
            ("thinking", lambda value: value.__setitem__("thinking_level", "medium")),
            ("seed", lambda value: value.__setitem__("seed", 1)),
            ("retry", lambda value: value.__setitem__("max_retries_per_sample", 1)),
        )
        for name, mutate in config_mutations:
            with self.subTest(config=name):
                changed = deepcopy(config)
                mutate(changed)
                with self.assertRaises(ContractError):
                    validate_runtime_config(changed, REPO_ROOT)

    def test_transport_maps_native_response_usage_headers_and_auth(self) -> None:
        config, assets = load_and_validate_campaign(SMOKE_CONFIG, REPO_ROOT)
        body = build_chat_request(
            config,
            assets["dataset"][0],
            assets["prompt"],
            assets["response_schema"],
        )
        transport = _transport()
        captured: dict[str, Any] = {}

        def open_request(request: urllib.request.Request, timeout: float) -> _Response:
            captured["request"] = request
            captured["timeout"] = timeout
            return _Response(
                _native_response(),
                {
                    "X-Goog-Request-Id": "native-request",
                    "Set-Cookie": "must-not-be-recorded",
                },
            )

        transport._opener.open = open_request  # type: ignore[method-assign]
        response = transport.call(
            api_key=FAKE_KEY,
            endpoint=ENDPOINT,
            body=body,
            timeout_seconds=12,
        )

        self.assertEqual(response.response_id, "native-response-synthetic")
        self.assertEqual(response.requested_model, MODEL)
        self.assertEqual(response.resolved_model, MODEL)
        self.assertEqual(json.loads(response.content), _output(False))
        self.assertEqual(response.finish_reason, "stop")
        self.assertFalse(response.tool_calls_present)
        self.assertEqual(
            response.usage,
            {
                "input_tokens": 100,
                "cached_input_tokens": 10,
                "output_tokens": 25,
                "reasoning_tokens": 5,
                "total_tokens": 125,
            },
        )
        self.assertEqual(
            response.safe_headers, {"x-goog-request-id": "native-request"}
        )
        request = captured["request"]
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["x-goog-api-key"], FAKE_KEY)
        self.assertNotIn("authorization", headers)
        self.assertNotIn(FAKE_KEY, request.full_url)
        self.assertNotIn(FAKE_KEY.encode("utf-8"), request.data)
        self.assertEqual(captured["timeout"], 12)

    def test_transport_rejects_endpoint_and_capability_drift(self) -> None:
        transport = _transport()
        with self.assertRaisesRegex(ContractError, "non-allowlisted"):
            transport.call(
                api_key=FAKE_KEY,
                endpoint="https://example.invalid/v1/models/x:generateContent",
                body={"store": False},
                timeout_seconds=1,
            )
        with self.assertRaisesRegex(ContractError, "store=false"):
            transport.call(
                api_key=FAKE_KEY,
                endpoint=ENDPOINT,
                body={"store": True},
                timeout_seconds=1,
            )

    def test_native_transient_failure_stops_campaign_after_one_attempt(self) -> None:
        transport = FakeNativeTransport(
            error=ProviderError(
                "timeout",
                "synthetic native timeout",
                retryable=True,
            )
        )
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = run_campaign(
                config_path=SMOKE_CONFIG,
                repo_root=REPO_ROOT,
                output_root=Path(temporary) / "runs",
                api_key=FAKE_KEY,
                transport=transport,
                sleep=lambda _: None,
            )
            results = read_jsonl(run_dir / "results.jsonl")
            ledger = read_json(run_dir / "budget_ledger.json")

        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(results[0]["status"], "timeout")
        self.assertEqual(results[0]["outbound_attempts"], 1)
        self.assertTrue(
            all(result["status"] == "campaign_stopped" for result in results[1:])
        )
        self.assertEqual(ledger["attempts_started"], 1)
        self.assertIn("verify billing", ledger["stop_reason"])

    def test_fake_native_smoke_runs_and_scores_all_five_records(self) -> None:
        _, assets = load_and_validate_campaign(SMOKE_CONFIG, REPO_ROOT)
        labels = {row["sample_id"]: row for row in read_jsonl(SMOKE_LABELS)}
        plans = [
            _output(labels[row["sample_id"]]["class_label"] == "malicious")
            for row in assets["dataset"]
        ]
        transport = FakeNativeTransport(plans=plans)

        with tempfile.TemporaryDirectory() as temporary:
            run_dir = run_campaign(
                config_path=SMOKE_CONFIG,
                repo_root=REPO_ROOT,
                output_root=Path(temporary) / "runs",
                api_key=FAKE_KEY,
                transport=transport,
                sleep=lambda _: None,
            )
            score_dir = score_run(
                run_dir=run_dir,
                labels_path=SMOKE_LABELS,
                output_dir=None,
                repo_root=REPO_ROOT,
            )
            metrics = read_json(score_dir / "metrics.json")
            results = read_jsonl(run_dir / "results.jsonl")

        self.assertEqual(len(transport.calls), 5)
        self.assertTrue(all(result["status"] == "success" for result in results))
        self.assertEqual(metrics["campaign_status"], "READINESS_PASS")
        self.assertEqual(metrics["security"]["critical_events"], 0)
        self.assertEqual(metrics["security"]["provider_metadata_omissions"], 0)


if __name__ == "__main__":
    unittest.main()
