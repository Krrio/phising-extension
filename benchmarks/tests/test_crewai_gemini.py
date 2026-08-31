from __future__ import annotations

import importlib.util
import json
import os
import socket
import sys
import tempfile
import unittest
from copy import deepcopy
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from unittest.mock import Mock


REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"
sys.path.insert(0, str(BENCHMARKS_DIR))

from phishing_bench.contracts import (  # noqa: E402
    CREWAI_GEMINI35_FLASH_LITE_QUALITY_PILOT_PROFILE,
    CREWAI_GEMINI35_FLASH_LITE_SMOKE_PROFILE,
    ContractError,
    load_and_validate_campaign,
    validate_runtime_config,
)
from phishing_bench.crewai_offline import (  # noqa: E402
    GOOGLE_AMBIENT_ENV_KEYS,
    PROXY_ENV_KEYS,
    CrewCallObservation,
    CrewWorkflowExecution,
    _import_benchmark_factory,
    _isolated_provider_environment,
    _normalize_finish_reason,
    _normalize_usage,
    _provider_only_network_guard,
    build_frozen_domain_evidence,
    crewai_readiness_report,
    crewai_runtime_preflight,
    run_crewai_campaign,
)
from phishing_bench.io_utils import read_json, read_jsonl, sha256_text  # noqa: E402
from phishing_bench.openai_direct import validated_tls_context  # noqa: E402
from phishing_bench.scoring import score_run  # noqa: E402


CAMPAIGN_ROOT = BENCHMARKS_DIR / "campaigns"
SMOKE_CONFIG = (
    CAMPAIGN_ROOT
    / "BUDGET_30H_CREWAI_GOOGLE_GEMINI35_FLASH_LITE_OFFLINE_SMOKE_001"
    / "runtime_config.json"
)
PILOT_CONFIG = (
    CAMPAIGN_ROOT
    / "BUDGET_30H_CREWAI_GOOGLE_GEMINI35_FLASH_LITE_OFFLINE_PILOT_030_001"
    / "runtime_config.json"
)
DIRECT_PILOT_CONFIG = (
    CAMPAIGN_ROOT
    / "BUDGET_30H_GOOGLE_GEMINI35_FLASH_LITE_PILOT_030_002"
    / "runtime_config.json"
)
SMOKE_MANIFEST = (
    BENCHMARKS_DIR / "secure_scoring" / "openai_smoke_v1" / "scoring_manifest.json"
)
PILOT_MANIFEST = (
    BENCHMARKS_DIR
    / "secure_scoring"
    / "openai_pilot_030_v1"
    / "scoring_manifest.json"
)
PILOT_LABELS = (
    BENCHMARKS_DIR / "secure_scoring" / "openai_pilot_030_v1" / "labels.jsonl"
)
HAS_CREWAI = importlib.util.find_spec("crewai") is not None
FAKE_KEY = "gemini-crewai_FAKE_SECRET_123456"


class CrewAIGeminiContractTests(unittest.TestCase):
    def test_campaigns_are_paired_but_disclose_cross_api_bundle_delta(self) -> None:
        smoke, smoke_assets = load_and_validate_campaign(SMOKE_CONFIG, REPO_ROOT)
        pilot, pilot_assets = load_and_validate_campaign(PILOT_CONFIG, REPO_ROOT)
        direct, direct_assets = load_and_validate_campaign(
            DIRECT_PILOT_CONFIG, REPO_ROOT
        )

        self.assertEqual(
            smoke["evaluation_profile"], CREWAI_GEMINI35_FLASH_LITE_SMOKE_PROFILE
        )
        self.assertEqual(
            pilot["evaluation_profile"],
            CREWAI_GEMINI35_FLASH_LITE_QUALITY_PILOT_PROFILE,
        )
        self.assertEqual(pilot["requested_model"], direct["requested_model"])
        self.assertEqual(pilot_assets["dataset"], direct_assets["dataset"])
        self.assertEqual(len(smoke_assets["dataset"]), 5)
        self.assertEqual(len(pilot_assets["dataset"]), 30)
        self.assertEqual(pilot["provider"], "google")
        self.assertEqual(pilot["thinking_level"], "minimal")
        self.assertIsNone(pilot["temperature"])
        self.assertEqual(
            smoke["endpoint"],
            "https://generativelanguage.googleapis.com/v1/models/"
            "gemini-3.5-flash-lite:generateContent",
        )
        self.assertEqual(smoke["budget"]["max_cost_usd"], 0.10)
        self.assertEqual(pilot["budget"]["max_cost_usd"], 0.50)
        self.assertEqual(
            pilot["security"]["provider_state_mode"],
            "explicit_store_false_request_override",
        )
        self.assertEqual(
            pilot["security"]["store_enforcement"],
            "http_options_extra_body_root",
        )
        disclosure = pilot["system_bundle_delta"]
        self.assertEqual(
            disclosure["comparison_name"], "cross_api_system_bundle_delta"
        )
        self.assertFalse(disclosure["same_provider_api"])
        self.assertFalse(disclosure["same_wire_response_schema"])
        self.assertTrue(disclosure["same_response_schema_semantics"])
        self.assertIn(
            smoke["campaign_id"],
            read_json(SMOKE_MANIFEST)["compatible_campaign_ids"],
        )
        self.assertIn(
            pilot["campaign_id"],
            read_json(PILOT_MANIFEST)["compatible_campaign_ids"],
        )

    def test_native_usage_and_finish_reason_are_normalized_without_double_count(self) -> None:
        self.assertEqual(_normalize_finish_reason("STOP"), "stop")
        self.assertEqual(_normalize_finish_reason("MAX_TOKENS"), "max_tokens")
        self.assertIsNone(_normalize_finish_reason(None))
        self.assertEqual(
            _normalize_usage(
                {
                    "prompt_token_count": 100,
                    "completion_tokens": 20,
                    "cached_prompt_tokens": 10,
                    "reasoning_tokens": 5,
                    "total_tokens": 120,
                }
            ),
            {
                "input_tokens": 100,
                "cached_input_tokens": 10,
                "output_tokens": 20,
                "reasoning_tokens": 5,
                "total_tokens": 120,
            },
        )

    def test_crewai_gemini_generation_limit_drift_fails_closed(self) -> None:
        config, _ = load_and_validate_campaign(SMOKE_CONFIG, REPO_ROOT)
        changed = deepcopy(config)
        changed["max_output_tokens"] = 501
        with self.assertRaisesRegex(ContractError, "max_output_tokens=500"):
            validate_runtime_config(changed, REPO_ROOT)

    def test_google_network_guard_blocks_every_other_hostname_before_dns(self) -> None:
        with self.assertRaisesRegex(PermissionError, "network guard blocked hostname"):
            with _provider_only_network_guard("google"):
                socket.getaddrinfo("api.openai.com", 443)


@unittest.skipUnless(HAS_CREWAI, "requires the pinned backend CrewAI environment")
class CrewAIGeminiRuntimeTests(unittest.TestCase):
    def test_preflight_audits_native_v1_store_tls_retry_and_environment(self) -> None:
        config, assets = load_and_validate_campaign(SMOKE_CONFIG, REPO_ROOT)
        touched = set(PROXY_ENV_KEYS) | set(GOOGLE_AMBIENT_ENV_KEYS)
        saved = {key: os.environ[key] for key in touched if key in os.environ}
        for key in touched:
            os.environ[key] = "ambient-value-that-must-not-be-used"
        try:
            report = crewai_runtime_preflight(config, assets)
            for key in touched:
                self.assertEqual(os.environ.get(key), "ambient-value-that-must-not-be-used")
        finally:
            for key in touched:
                os.environ.pop(key, None)
            os.environ.update(saved)

        self.assertEqual(report["installed_crewai_version"], "1.15.8")
        self.assertEqual(report["installed_google_genai_version"], "1.65.0")
        self.assertEqual(report["provider_calls_made"], 0)
        self.assertEqual(report["telemetry"]["ambient_google_variables_present"], [])
        self.assertEqual(report["telemetry"]["proxy_variables_present"], [])
        agents = report["effective_profile"]["agents"]
        self.assertEqual([row["provider"] for row in agents], ["gemini"] * 3)
        self.assertEqual([row["api_version"] for row in agents], ["v1"] * 3)
        self.assertTrue(all(row["wire_store_false_verified"] for row in agents))
        self.assertTrue(all(row["provider_max_attempts"] == 1 for row in agents))
        self.assertTrue(all(row["trust_env"] is False for row in agents))
        self.assertTrue(all(row["follow_redirects"] is False for row in agents))
        self.assertTrue(all(row["async_transport"] == "httpx" for row in agents))
        self.assertTrue(all(row["wire_tools"] == "absent" for row in agents))
        self.assertEqual(
            [row["response_format"] for row in agents],
            ["text", "text", "strict_json_schema"],
        )
        self.assertIsNone(agents[0]["response_schema_sha256"])
        self.assertIsNone(agents[1]["response_schema_sha256"])
        self.assertRegex(agents[2]["response_schema_sha256"], r"^[0-9a-f]{64}$")

        readiness = crewai_readiness_report(SMOKE_CONFIG, REPO_ROOT)
        self.assertEqual(readiness["status"], "READY_FOR_MANUAL_LIVE_CONFIRMATION")
        self.assertLessEqual(
            readiness["required_cost_cap_with_margin_usd"],
            config["budget"]["max_cost_usd"],
        )
        self.assertEqual(
            readiness["security_contract"]["store_enforcement"],
            "http_options_extra_body_root",
        )
        self.assertFalse(readiness["security_contract"]["vertexai"])

    def test_real_crewai_kickoff_makes_exactly_three_mocked_provider_calls_and_cleans_up(self) -> None:
        config, assets = load_and_validate_campaign(SMOKE_CONFIG, REPO_ROOT)
        record = assets["dataset"][0]
        evidence, _ = build_frozen_domain_evidence(
            record, assets["frozen_domain_evidence"]
        )
        final_output = json.dumps(
            {
                "trustScore": 10,
                "verdict": "phishing",
                "confidence": 0.99,
                "reasoning": "Syntetyczne wyłudzenie danych.",
                "categories": ["credential_request", "suspicious_link"],
                "policyAssessment": None,
            },
            ensure_ascii=False,
        )
        responses = (
            "Lokalne dowody domenowe wskazują ryzyko.",
            "Treść żąda danych logowania.",
            final_output,
        )
        with _isolated_provider_environment("google"):
            build_crew, audit_crew = _import_benchmark_factory("google")
            bundle = build_crew(
                api_key=FAKE_KEY,
                requested_model=config["requested_model"],
                temperature=config["temperature"],
                max_output_tokens=config["max_output_tokens"],
                request_timeout_seconds=config["request_timeout_seconds"],
                max_llm_calls=3,
                response_schema=assets["response_schema"],
                profile=assets["crew_profile"],
                provider="google",
                thinking_level="minimal",
                tls_context=validated_tls_context(),
            )
            audit = audit_crew(bundle)

        self.assertTrue(
            all(row["wire_store_false_verified"] for row in audit["agents"])
        )
        delegates = [agent.llm.delegate for agent in bundle.crew.agents]
        clients = [delegate._client for delegate in delegates]  # noqa: SLF001
        provider_mocks: list[Mock] = []
        try:
            with ExitStack() as stack:
                for delegate, response in zip(delegates, responses, strict=True):
                    provider_call = Mock(return_value=response)
                    provider_mocks.append(provider_call)
                    stack.enter_context(
                        unittest.mock.patch.object(delegate, "call", provider_call)
                    )
                output = bundle.crew.kickoff(
                    inputs={
                        "benchmark_system_prompt": assets["prompt"],
                        "record_payload": json.dumps(record, ensure_ascii=False),
                        "frozen_domain_evidence": json.dumps(
                            evidence, ensure_ascii=False
                        ),
                    }
                )
        finally:
            bundle.close()

        self.assertEqual(bundle.call_budget.used, 3)
        self.assertEqual(
            bundle.call_budget.roles,
            ("domain_analyst", "content_analyst", "orchestrator"),
        )
        self.assertEqual([mock.call_count for mock in provider_mocks], [1, 1, 1])
        self.assertEqual(json.loads(output.raw), json.loads(final_output))
        self.assertTrue(all(delegate._client is None for delegate in delegates))  # noqa: SLF001
        self.assertTrue(all(delegate.api_key is None for delegate in delegates))
        self.assertTrue(all(client is not None for client in clients))

    def test_fake_pilot_writes_90_calls_and_scores_as_cross_api_bundle(self) -> None:
        config, assets = load_and_validate_campaign(PILOT_CONFIG, REPO_ROOT)
        labels = {row["sample_id"]: row for row in read_jsonl(PILOT_LABELS)}

        def executor(**kwargs: Any) -> CrewWorkflowExecution:
            record = kwargs["record"]
            malicious = labels[record["sample_id"]]["class_label"] == "malicious"
            output = {
                "trustScore": 10 if malicious else 95,
                "verdict": "phishing" if malicious else "safe",
                "confidence": 0.95,
                "reasoning": "Syntetyczne uzasadnienie CrewAI Gemini.",
                "categories": ["impersonation"] if malicious else [],
                "policyAssessment": None,
            }
            calls = tuple(
                CrewCallObservation(
                    call_id=f"{record['sample_id']}-{index}",
                    role=role,
                    task_name=task,
                    request_sha256=sha256_text(f"request-{record['sample_id']}-{index}"),
                    response_sha256=sha256_text(f"response-{record['sample_id']}-{index}"),
                    model=config["requested_model"],
                    usage={
                        "input_tokens": 100,
                        "cached_input_tokens": 20,
                        "output_tokens": 20,
                        "reasoning_tokens": 5,
                        "total_tokens": 120,
                    },
                    latency_ms=5.0,
                    finish_reason="stop",
                    response_id=f"fake-{record['sample_id']}-{index}",
                    status="success",
                    error=None,
                )
                for index, (role, task) in enumerate(
                    zip(
                        ("domain_analyst", "content_analyst", "orchestrator"),
                        ("domain_analysis", "content_analysis", "synthesis"),
                        strict=True,
                    ),
                    start=1,
                )
            )
            return CrewWorkflowExecution(
                raw_output=json.dumps(output, ensure_ascii=False),
                calls=calls,
                runtime_audit={},
            )

        with tempfile.TemporaryDirectory() as temporary:
            run_dir = run_crewai_campaign(
                config_path=PILOT_CONFIG,
                repo_root=REPO_ROOT,
                output_root=Path(temporary) / "runs",
                api_key=FAKE_KEY,
                workflow_executor=executor,
            )
            scoring = score_run(
                run_dir=run_dir,
                labels_path=PILOT_LABELS,
                output_dir=None,
                repo_root=REPO_ROOT,
            )
            metrics = read_json(scoring / "metrics.json")
            report = (scoring / "report.md").read_text(encoding="utf-8")
            calls = read_jsonl(run_dir / "calls.jsonl")
            results = read_jsonl(run_dir / "results.jsonl")

        self.assertEqual(len(results), 30)
        self.assertEqual(len(calls), 90)
        self.assertTrue(all(row["status"] == "success" for row in results))
        self.assertEqual(metrics["attempts"]["outbound"], 90)
        self.assertEqual(metrics["cost"]["observed_usd"], 0.006714)
        self.assertEqual(
            metrics["comparison_scope"]["comparison_name"],
            "cross_api_system_bundle_delta",
        )
        self.assertEqual(metrics["campaign_status"], "PILOT_READY_FOR_SELECTION")
        self.assertIn("cross_api_system_bundle_delta", report)


if __name__ == "__main__":
    unittest.main()
