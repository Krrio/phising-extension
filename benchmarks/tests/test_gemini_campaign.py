from __future__ import annotations

import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"
sys.path.insert(0, str(BENCHMARKS_DIR))

from phishing_bench.comparison import compare_runs  # noqa: E402
from phishing_bench.contracts import (  # noqa: E402
    ContractError,
    GEMINI35_FLASH_LITE_QUALITY_PILOT_PROFILE,
    GEMINI35_FLASH_LITE_SMOKE_PROFILE,
    GEMINI_INTERACTIONS_REQUEST_PROFILE,
    build_chat_request,
    load_and_validate_campaign,
    validate_outgoing_request,
    validate_runtime_config,
)
from phishing_bench.io_utils import read_json, read_jsonl  # noqa: E402
from phishing_bench.openai_direct import ProviderResponse  # noqa: E402
from phishing_bench.runner import readiness_report, run_campaign  # noqa: E402
from phishing_bench.scoring import score_run  # noqa: E402


SMOKE_CONFIG_PATH = (
    BENCHMARKS_DIR
    / "campaigns"
    / "BUDGET_30H_GOOGLE_GEMINI35_FLASH_LITE_SMOKE_001"
    / "runtime_config.json"
)
PILOT_CONFIG_PATH = (
    BENCHMARKS_DIR
    / "campaigns"
    / "BUDGET_30H_GOOGLE_GEMINI35_FLASH_LITE_PILOT_030_001"
    / "runtime_config.json"
)
MINI_SMOKE_CONFIG_PATH = (
    BENCHMARKS_DIR
    / "campaigns"
    / "BUDGET_30H_OPENAI_GPT54_MINI_SMOKE_001"
    / "runtime_config.json"
)
MINI_PILOT_CONFIG_PATH = (
    BENCHMARKS_DIR
    / "campaigns"
    / "BUDGET_30H_OPENAI_GPT54_MINI_PILOT_030_001"
    / "runtime_config.json"
)
SMOKE_SCORING_MANIFEST_PATH = (
    BENCHMARKS_DIR / "secure_scoring" / "openai_smoke_v1" / "scoring_manifest.json"
)
PILOT_LABELS_PATH = (
    BENCHMARKS_DIR / "secure_scoring" / "openai_pilot_030_v1" / "labels.jsonl"
)
PILOT_SCORING_MANIFEST_PATH = (
    BENCHMARKS_DIR
    / "secure_scoring"
    / "openai_pilot_030_v1"
    / "scoring_manifest.json"
)
FAKE_KEY = "gemini-test_FAKE_SECRET_123456"


def _output(malicious: bool) -> dict[str, Any]:
    return {
        "trustScore": 10 if malicious else 95,
        "verdict": "phishing" if malicious else "safe",
        "confidence": 0.95,
        "reasoning": "Syntetyczne uzasadnienie testowe Gemini.",
        "categories": ["impersonation"] if malicious else [],
        "policyAssessment": None,
    }


class FakeGeminiCompatibleTransport:
    """Provider-neutral fake proving that the runner consumes ProviderResponse."""

    def __init__(self, plans: list[dict[str, Any]]) -> None:
        self.plans = list(plans)
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
        content = json.dumps(self.plans.pop(0), ensure_ascii=False)
        return ProviderResponse(
            response_id=f"interaction-gemini-fake-{len(self.calls)}",
            requested_model=body["model"],
            resolved_model=body["model"],
            content=content,
            finish_reason="stop",
            refusal=None,
            tool_calls_present=False,
            usage={
                "input_tokens": 100,
                "cached_input_tokens": 20,
                "output_tokens": 20,
                "reasoning_tokens": 5,
                "total_tokens": 120,
            },
            safe_headers={"x-request-id": f"req-gemini-{len(self.calls)}"},
            elapsed_ms=10.0,
            raw_response_sha256_material=content.encode("utf-8"),
        )


class GeminiCampaignTests(unittest.TestCase):
    def test_campaigns_freeze_shared_assets_and_exact_interactions_payload(self) -> None:
        smoke, smoke_assets = load_and_validate_campaign(SMOKE_CONFIG_PATH, REPO_ROOT)
        pilot, pilot_assets = load_and_validate_campaign(PILOT_CONFIG_PATH, REPO_ROOT)
        mini_smoke = read_json(MINI_SMOKE_CONFIG_PATH)
        mini_pilot = read_json(MINI_PILOT_CONFIG_PATH)

        self.assertEqual(smoke["evaluation_profile"], GEMINI35_FLASH_LITE_SMOKE_PROFILE)
        self.assertEqual(
            pilot["evaluation_profile"],
            GEMINI35_FLASH_LITE_QUALITY_PILOT_PROFILE,
        )
        self.assertEqual(smoke["provider"], "google")
        self.assertEqual(smoke["adapter"], "gemini_interactions")
        self.assertEqual(smoke["requested_model"], "gemini-3.5-flash-lite")
        self.assertEqual(smoke["request_profile"], GEMINI_INTERACTIONS_REQUEST_PROFILE)
        self.assertEqual(smoke["api_key_env"], "GEMINI_API_KEY")
        self.assertIsNone(smoke["temperature"])
        self.assertEqual(smoke["thinking_level"], "minimal")
        self.assertEqual(smoke["seed"], 0)
        self.assertEqual(
            smoke["budget"],
            {"max_attempts": 10, "max_cost_usd": 0.10, "max_wall_seconds": 900},
        )
        self.assertEqual(
            pilot["budget"],
            {"max_attempts": 60, "max_cost_usd": 0.30, "max_wall_seconds": 7200},
        )
        self.assertEqual(
            smoke["pricing_usd_per_million_tokens"],
            {
                "input": 0.30,
                "cached_input": 0.03,
                "output": 2.50,
                "source_checked_at": "2026-08-29",
                "source": "https://ai.google.dev/gemini-api/docs/pricing",
            },
        )
        self.assertEqual(len(smoke_assets["dataset"]), 5)
        self.assertEqual(len(pilot_assets["dataset"]), 30)

        for candidate, baseline in ((smoke, mini_smoke), (pilot, mini_pilot)):
            for key in (
                "dataset_path",
                "prompt_path",
                "response_schema_path",
                "decision_policy_path",
            ):
                self.assertEqual(candidate[key], baseline[key])
            self.assertEqual(
                candidate["expected_asset_sha256"],
                baseline["expected_asset_sha256"],
            )

        body = build_chat_request(
            smoke,
            smoke_assets["dataset"][0],
            smoke_assets["prompt"],
            smoke_assets["response_schema"],
        )
        self.assertEqual(
            set(body),
            {
                "model",
                "input",
                "system_instruction",
                "response_format",
                "stream",
                "store",
                "background",
                "generation_config",
            },
        )
        self.assertEqual(body["model"], "gemini-3.5-flash-lite")
        self.assertEqual(body["system_instruction"], smoke_assets["prompt"])
        self.assertEqual(len(body["input"]), 1)
        self.assertEqual(body["input"][0]["type"], "user_input")
        self.assertEqual(len(body["input"][0]["content"]), 1)
        self.assertEqual(body["input"][0]["content"][0]["type"], "text")
        self.assertTrue(body["input"][0]["content"][0]["text"].strip())
        self.assertEqual(
            body["response_format"],
            {
                "type": "text",
                "mime_type": "application/json",
                "schema": smoke_assets["response_schema"]["json_schema"]["schema"],
            },
        )
        self.assertEqual(
            body["generation_config"],
            {
                "max_output_tokens": 500,
                "seed": 0,
                "thinking_level": "minimal",
                "thinking_summaries": "none",
            },
        )
        self.assertFalse(body["store"])
        self.assertFalse(body["background"])
        self.assertFalse(body["stream"])
        self.assertNotIn("temperature", body)
        self.assertNotIn("temperature", body["generation_config"])
        self.assertNotIn("tools", body)
        self.assertNotIn("previous_interaction_id", body)

        smoke_report = readiness_report(SMOKE_CONFIG_PATH, REPO_ROOT)
        pilot_report = readiness_report(PILOT_CONFIG_PATH, REPO_ROOT)
        self.assertEqual(smoke_report["status"], "READY_FOR_MANUAL_LIVE_CONFIRMATION")
        self.assertEqual(smoke_report["record_count"], 5)
        self.assertEqual(pilot_report["record_count"], 30)
        self.assertEqual(
            smoke_report["request_contract"],
            {
                "request_profile": GEMINI_INTERACTIONS_REQUEST_PROFILE,
                "instruction_role": "system_instruction",
                "token_limit_field": "generation_config.max_output_tokens",
                "thinking_level": "minimal",
                "seed": 0,
                "temperature": None,
            },
        )
        self.assertEqual(
            smoke_report["security_contract"],
            {
                "store": False,
                "stream": False,
                "background": False,
                "tools": "absent",
                "conversation": "absent",
                "previous_interaction_id": "absent",
                "provider_egress": "generativelanguage.googleapis.com_only",
                "runtime_config_exposes_scoring_path": False,
                "input_data_class": "synthetic_reserved_domains_only",
            },
        )
        self.assertLessEqual(
            smoke_report["required_cost_cap_with_margin_usd"],
            smoke["budget"]["max_cost_usd"],
        )
        self.assertLessEqual(
            pilot_report["required_cost_cap_with_margin_usd"],
            pilot["budget"]["max_cost_usd"],
        )
        self.assertIn(
            smoke["campaign_id"],
            read_json(SMOKE_SCORING_MANIFEST_PATH)["compatible_campaign_ids"],
        )
        self.assertIn(
            pilot["campaign_id"],
            read_json(PILOT_SCORING_MANIFEST_PATH)["compatible_campaign_ids"],
        )

    def test_config_and_outgoing_payload_drift_fail_closed(self) -> None:
        config, assets = load_and_validate_campaign(SMOKE_CONFIG_PATH, REPO_ROOT)
        mutations = (
            (
                "latest_model",
                lambda value: value.__setitem__(
                    "requested_model", "gemini-3.5-flash-lite-latest"
                ),
            ),
            (
                "preview_model",
                lambda value: value.__setitem__(
                    "requested_model", "gemini-3.5-flash-lite-preview"
                ),
            ),
            (
                "different_model",
                lambda value: value.__setitem__("requested_model", "gemini-3.5-flash"),
            ),
            ("provider", lambda value: value.__setitem__("provider", "openai")),
            (
                "adapter",
                lambda value: value.__setitem__("adapter", "chat_completions"),
            ),
            (
                "key_environment",
                lambda value: value.__setitem__("api_key_env", "OPENAI_API_KEY"),
            ),
            (
                "endpoint_version",
                lambda value: value.__setitem__(
                    "endpoint",
                    "https://generativelanguage.googleapis.com/v1beta/interactions",
                ),
            ),
            (
                "endpoint_host",
                lambda value: value.__setitem__(
                    "endpoint", "https://example.invalid/v1/interactions"
                ),
            ),
            (
                "pricing",
                lambda value: value["pricing_usd_per_million_tokens"].__setitem__(
                    "input", 0.31
                ),
            ),
            (
                "pricing_date",
                lambda value: value["pricing_usd_per_million_tokens"].__setitem__(
                    "source_checked_at", "2026-08-28"
                ),
            ),
            (
                "thinking",
                lambda value: value.__setitem__("thinking_level", "low"),
            ),
            (
                "request_profile",
                lambda value: value.__setitem__("request_profile", "changed"),
            ),
            ("seed", lambda value: value.__setitem__("seed", 1)),
            ("temperature", lambda value: value.__setitem__("temperature", 0)),
        )
        for name, mutate in mutations:
            with self.subTest(config=name):
                changed = deepcopy(config)
                mutate(changed)
                with self.assertRaises(ContractError):
                    validate_runtime_config(changed, REPO_ROOT)

        body = build_chat_request(
            config,
            assets["dataset"][0],
            assets["prompt"],
            assets["response_schema"],
        )
        body_mutations = (
            ("model", lambda value: value.__setitem__("model", "gemini-3.5-flash")),
            ("store", lambda value: value.__setitem__("store", True)),
            ("background", lambda value: value.__setitem__("background", True)),
            ("stream", lambda value: value.__setitem__("stream", True)),
            ("tools", lambda value: value.__setitem__("tools", [])),
            (
                "previous_interaction",
                lambda value: value.__setitem__("previous_interaction_id", "previous"),
            ),
            (
                "thinking",
                lambda value: value["generation_config"].__setitem__(
                    "thinking_level", "low"
                ),
            ),
            (
                "thinking_summaries",
                lambda value: value["generation_config"].__setitem__(
                    "thinking_summaries", "auto"
                ),
            ),
            (
                "temperature",
                lambda value: value["generation_config"].__setitem__(
                    "temperature", 0
                ),
            ),
            (
                "schema",
                lambda value: value["response_format"].__setitem__(
                    "schema", {"type": "object", "additionalProperties": True}
                ),
            ),
        )
        for name, mutate in body_mutations:
            with self.subTest(payload=name):
                changed = deepcopy(body)
                mutate(changed)
                with self.assertRaises(ContractError):
                    validate_outgoing_request(config, changed)

    def test_fake_pilot_scores_cost_and_cross_provider_comparison(self) -> None:
        config, assets = load_and_validate_campaign(PILOT_CONFIG_PATH, REPO_ROOT)
        labels_by_id = {
            row["sample_id"]: row for row in read_jsonl(PILOT_LABELS_PATH)
        }

        def plans_for(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [
                _output(
                    labels_by_id[record["sample_id"]]["class_label"] == "malicious"
                )
                for record in records
            ]

        gemini_transport = FakeGeminiCompatibleTransport(
            plans_for(assets["dataset"])
        )
        with tempfile.TemporaryDirectory() as temporary:
            output_root = Path(temporary) / "runs"
            gemini_run = run_campaign(
                config_path=PILOT_CONFIG_PATH,
                repo_root=REPO_ROOT,
                output_root=output_root,
                api_key=FAKE_KEY,
                transport=gemini_transport,
                sleep=lambda _: None,
            )
            gemini_score_dir = score_run(
                run_dir=gemini_run,
                labels_path=PILOT_LABELS_PATH,
                output_dir=None,
                repo_root=REPO_ROOT,
            )
            gemini_metrics = read_json(gemini_score_dir / "metrics.json")
            gemini_results = read_jsonl(gemini_run / "results.jsonl")

            _, mini_assets = load_and_validate_campaign(
                MINI_PILOT_CONFIG_PATH, REPO_ROOT
            )
            mini_transport = FakeGeminiCompatibleTransport(
                plans_for(mini_assets["dataset"])
            )
            mini_run = run_campaign(
                config_path=MINI_PILOT_CONFIG_PATH,
                repo_root=REPO_ROOT,
                output_root=output_root,
                api_key=FAKE_KEY,
                transport=mini_transport,
                sleep=lambda _: None,
            )
            score_run(
                run_dir=mini_run,
                labels_path=PILOT_LABELS_PATH,
                output_dir=None,
                repo_root=REPO_ROOT,
            )
            comparison_dir = compare_runs(
                named_run_dirs=[("gpt54_mini", mini_run), ("gemini", gemini_run)],
                labels_path=PILOT_LABELS_PATH,
                output_dir=Path(temporary) / "comparison",
                repo_root=REPO_ROOT,
            )
            comparison = read_json(comparison_dir / "comparison.json")

        self.assertEqual(len(gemini_transport.calls), 30)
        self.assertEqual(len(gemini_results), 30)
        self.assertTrue(all(row["status"] == "success" for row in gemini_results))
        self.assertTrue(
            all(
                row["resolved_model"] == "gemini-3.5-flash-lite"
                for row in gemini_results
            )
        )
        self.assertEqual(gemini_metrics["campaign_status"], "PILOT_READY_FOR_SELECTION")
        self.assertEqual(
            gemini_metrics["confusion_matrix"],
            {
                "positive_class": "malicious",
                "positive_actions": ["warn", "hide"],
                "negative_action": "allow",
                "technical_failures_use_action": "allow",
                "technical_failures_in_denominators": True,
                "tp": 15,
                "fp": 0,
                "tn": 15,
                "fn": 0,
                "total": 30,
            },
        )
        self.assertEqual(
            gemini_metrics["usage"],
            {
                "input_tokens": 3000,
                "cached_input_tokens": 600,
                "output_tokens": 600,
                "reasoning_tokens": 150,
                "total_tokens": 3600,
            },
        )
        self.assertEqual(gemini_metrics["cost"]["observed_usd"], 0.002238)
        for call in gemini_transport.calls:
            self.assertEqual(
                call["endpoint"],
                "https://generativelanguage.googleapis.com/v1/interactions",
            )
            self.assertEqual(call["body"]["model"], "gemini-3.5-flash-lite")
            self.assertNotIn("temperature", call["body"])
            self.assertNotIn("tools", call["body"])
            self.assertFalse(call["body"]["store"])

        compatibility = comparison["compatibility"]
        self.assertEqual(
            compatibility["comparison_type"], "model_or_provider_delta"
        )
        self.assertTrue(compatibility["same_architecture"])
        self.assertTrue(compatibility["same_prompt"])
        self.assertFalse(compatibility["same_adapter"])
        self.assertFalse(compatibility["same_model"])
        self.assertFalse(compatibility["same_provider"])
        self.assertFalse(compatibility["same_request_profile"])
        self.assertEqual(comparison["comparative_conclusion"], "INCONCLUSIVE")


if __name__ == "__main__":
    unittest.main()
