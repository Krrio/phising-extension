from __future__ import annotations

import json
import sys
import tempfile
import unittest
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"
sys.path.insert(0, str(BENCHMARKS_DIR))

from phishing_bench.contracts import (  # noqa: E402
    ContractError,
    GEMINI31_FLASH_LITE_QUALITY_PILOT_PROFILE,
    GEMINI31_FLASH_LITE_SMOKE_PROFILE,
    GEMINI37_FLASH_QUALITY_PILOT_PROFILE,
    GEMINI37_FLASH_SMOKE_PROFILE,
    GEMINI_INTERACTIONS_LOW_REQUEST_PROFILE,
    GEMINI_INTERACTIONS_REQUEST_PROFILE,
    assert_pricing_current_for_run,
    build_chat_request,
    load_and_validate_campaign,
    validate_outgoing_request,
    validate_runtime_config,
)
from phishing_bench.io_utils import read_json, read_jsonl  # noqa: E402
from phishing_bench.openai_direct import ProviderResponse  # noqa: E402
from phishing_bench.runner import readiness_report, run_campaign  # noqa: E402
from phishing_bench.scoring import score_run  # noqa: E402


CAMPAIGN_ROOT = BENCHMARKS_DIR / "campaigns"
CONFIGS = {
    "31_smoke": CAMPAIGN_ROOT
    / "BUDGET_30H_GOOGLE_GEMINI31_FLASH_LITE_SMOKE_001"
    / "runtime_config.json",
    "31_pilot": CAMPAIGN_ROOT
    / "BUDGET_30H_GOOGLE_GEMINI31_FLASH_LITE_PILOT_030_001"
    / "runtime_config.json",
    "37_smoke": CAMPAIGN_ROOT
    / "BUDGET_30H_GOOGLE_GEMINI37_FLASH_SMOKE_001"
    / "runtime_config.json",
    "37_smoke_timeout120": CAMPAIGN_ROOT
    / "BUDGET_30H_GOOGLE_GEMINI37_FLASH_SMOKE_002"
    / "runtime_config.json",
    "37_pilot": CAMPAIGN_ROOT
    / "BUDGET_30H_GOOGLE_GEMINI37_FLASH_PILOT_030_001"
    / "runtime_config.json",
}
GEMINI35_SMOKE = (
    CAMPAIGN_ROOT
    / "BUDGET_30H_GOOGLE_GEMINI35_FLASH_LITE_SMOKE_003"
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
SMOKE_LABELS = (
    BENCHMARKS_DIR / "secure_scoring" / "openai_smoke_v1" / "labels.jsonl"
)
FAKE_KEY = "gemini-challenger_FAKE_SECRET_123456"


def _output(malicious: bool) -> dict[str, Any]:
    return {
        "trustScore": 10 if malicious else 95,
        "verdict": "phishing" if malicious else "safe",
        "confidence": 0.95,
        "reasoning": "Syntetyczne uzasadnienie testowe.",
        "categories": ["impersonation"] if malicious else [],
        "policyAssessment": None,
    }


class FakeTransport:
    def __init__(self, outputs: list[dict[str, Any]]) -> None:
        self.outputs = list(outputs)
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
        content = json.dumps(self.outputs.pop(0), ensure_ascii=False)
        return ProviderResponse(
            response_id=f"fake-{len(self.calls)}",
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
            safe_headers={"x-request-id": f"req-{len(self.calls)}"},
            elapsed_ms=5.0,
            raw_response_sha256_material=content.encode("utf-8"),
        )


class GeminiChallengerCampaignTests(unittest.TestCase):
    def test_profiles_payloads_prices_and_scoring_compatibility_are_frozen(self) -> None:
        expected = {
            "31_smoke": (
                GEMINI31_FLASH_LITE_SMOKE_PROFILE,
                "gemini-3.1-flash-lite",
                "minimal",
                GEMINI_INTERACTIONS_REQUEST_PROFILE,
                5,
                0.05,
                (0.25, 0.025, 1.50),
                45,
                1,
                10,
            ),
            "31_pilot": (
                GEMINI31_FLASH_LITE_QUALITY_PILOT_PROFILE,
                "gemini-3.1-flash-lite",
                "minimal",
                GEMINI_INTERACTIONS_REQUEST_PROFILE,
                30,
                0.25,
                (0.25, 0.025, 1.50),
                45,
                1,
                60,
            ),
            "37_smoke": (
                GEMINI37_FLASH_SMOKE_PROFILE,
                "gemini-3.7-flash",
                "low",
                GEMINI_INTERACTIONS_LOW_REQUEST_PROFILE,
                5,
                0.10,
                (0.75, 0.075, 3.75),
                45,
                1,
                10,
            ),
            "37_smoke_timeout120": (
                GEMINI37_FLASH_SMOKE_PROFILE,
                "gemini-3.7-flash",
                "low",
                GEMINI_INTERACTIONS_LOW_REQUEST_PROFILE,
                5,
                0.05,
                (0.75, 0.075, 3.75),
                120,
                0,
                5,
            ),
            "37_pilot": (
                GEMINI37_FLASH_QUALITY_PILOT_PROFILE,
                "gemini-3.7-flash",
                "low",
                GEMINI_INTERACTIONS_LOW_REQUEST_PROFILE,
                30,
                0.65,
                (0.75, 0.075, 3.75),
                45,
                1,
                60,
            ),
        }
        smoke_ids = set(read_json(SMOKE_MANIFEST)["compatible_campaign_ids"])
        pilot_ids = set(read_json(PILOT_MANIFEST)["compatible_campaign_ids"])

        for name, path in CONFIGS.items():
            with self.subTest(name=name):
                config, assets = load_and_validate_campaign(path, REPO_ROOT)
                (
                    profile,
                    model,
                    thinking,
                    request_profile,
                    count,
                    cap,
                    prices,
                    timeout,
                    retries,
                    attempts,
                ) = expected[name]
                self.assertEqual(config["evaluation_profile"], profile)
                self.assertEqual(config["requested_model"], model)
                self.assertEqual(config["thinking_level"], thinking)
                self.assertEqual(config["request_profile"], request_profile)
                self.assertEqual(config["expected_sample_count"], count)
                self.assertEqual(len(assets["dataset"]), count)
                self.assertEqual(config["budget"]["max_cost_usd"], cap)
                self.assertEqual(config["request_timeout_seconds"], timeout)
                self.assertEqual(config["max_retries_per_sample"], retries)
                self.assertEqual(config["budget"]["max_attempts"], attempts)
                pricing = config["pricing_usd_per_million_tokens"]
                self.assertEqual(
                    (pricing["input"], pricing["cached_input"], pricing["output"]),
                    prices,
                )
                body = build_chat_request(
                    config,
                    assets["dataset"][0],
                    assets["prompt"],
                    assets["response_schema"],
                )
                self.assertEqual(body["generation_config"]["thinking_level"], thinking)
                self.assertEqual(body["generation_config"]["seed"], 0)
                self.assertFalse(body["store"])
                self.assertFalse(body["background"])
                self.assertFalse(body["stream"])
                self.assertNotIn("temperature", body)
                self.assertNotIn("tools", body)
                report = readiness_report(path, REPO_ROOT)
                self.assertLessEqual(
                    report["required_cost_cap_with_margin_usd"], cap
                )
                compatible = pilot_ids if count == 30 else smoke_ids
                self.assertIn(config["campaign_id"], compatible)

        gemini35 = read_json(GEMINI35_SMOKE)
        self.assertEqual(
            read_json(CONFIGS["31_smoke"])["request_profile"],
            gemini35["request_profile"],
        )
        self.assertNotEqual(
            read_json(CONFIGS["37_smoke"])["request_profile"],
            gemini35["request_profile"],
        )

    def test_gemini37_timeout_diagnostic_is_a_new_no_retry_campaign(self) -> None:
        path = CONFIGS["37_smoke_timeout120"]
        config, _ = load_and_validate_campaign(path, REPO_ROOT)
        report = readiness_report(path, REPO_ROOT)

        self.assertEqual(
            config["campaign_id"],
            "BUDGET_30H_GOOGLE_GEMINI37_FLASH_SMOKE_002",
        )
        self.assertEqual(config["request_timeout_seconds"], 120)
        self.assertEqual(config["max_retries_per_sample"], 0)
        self.assertEqual(config["budget"]["max_attempts"], 5)
        self.assertEqual(config["budget"]["max_cost_usd"], 0.05)
        self.assertLessEqual(report["required_cost_cap_with_margin_usd"], 0.05)

        for key, value in (
            ("request_timeout_seconds", 45),
            ("max_retries_per_sample", 1),
            ("config_id", "changed"),
        ):
            changed = deepcopy(config)
            changed[key] = value
            with self.assertRaises(ContractError):
                validate_runtime_config(changed, REPO_ROOT)

    def test_gemini37_timeout_diagnostic_makes_five_mocked_calls_without_retry(self) -> None:
        path = CONFIGS["37_smoke_timeout120"]
        config, assets = load_and_validate_campaign(path, REPO_ROOT)
        labels = {row["sample_id"]: row for row in read_jsonl(SMOKE_LABELS)}
        transport = FakeTransport(
            [
                _output(labels[row["sample_id"]]["class_label"] == "malicious")
                for row in assets["dataset"]
            ]
        )

        with tempfile.TemporaryDirectory() as temporary:
            run_dir = run_campaign(
                config_path=path,
                repo_root=REPO_ROOT,
                output_root=Path(temporary) / "runs",
                api_key=FAKE_KEY,
                transport=transport,
                sleep=lambda _: None,
            )
            scoring = score_run(
                run_dir=run_dir,
                labels_path=SMOKE_LABELS,
                output_dir=None,
                repo_root=REPO_ROOT,
            )
            metrics = read_json(scoring / "metrics.json")

        self.assertEqual(len(transport.calls), 5)
        self.assertTrue(all(call["timeout"] == 120 for call in transport.calls))
        self.assertEqual(metrics["attempts"]["outbound"], 5)
        self.assertEqual(metrics["attempts"]["retries"], 0)
        self.assertEqual(metrics["campaign_status"], "READINESS_PASS")

    def test_config_payload_and_promotional_price_drift_fail_closed(self) -> None:
        config, assets = load_and_validate_campaign(CONFIGS["37_smoke"], REPO_ROOT)
        mutations = (
            lambda value: value.__setitem__("requested_model", "gemini-3.7-flash-latest"),
            lambda value: value.__setitem__("thinking_level", "minimal"),
            lambda value: value.__setitem__("request_profile", "changed"),
            lambda value: value.__setitem__("pricing_valid_through", "2027-01-01"),
            lambda value: value["pricing_usd_per_million_tokens"].__setitem__(
                "output", 7.50
            ),
            lambda value: value["budget"].__setitem__("max_cost_usd", 0.11),
        )
        for mutate in mutations:
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
        for mutate in (
            lambda value: value["generation_config"].__setitem__(
                "thinking_level", "minimal"
            ),
            lambda value: value.__setitem__("store", True),
            lambda value: value.__setitem__("tools", []),
        ):
            changed = deepcopy(body)
            mutate(changed)
            with self.assertRaises(ContractError):
                validate_outgoing_request(config, changed)

        assert_pricing_current_for_run(config, today=date(2026, 12, 31))
        with self.assertRaisesRegex(ContractError, "pricing expired"):
            assert_pricing_current_for_run(config, today=date(2027, 1, 1))
        # Static validation remains available for historical manifests/scoring.
        validate_runtime_config(config, REPO_ROOT)

    def test_both_pilots_run_and_score_with_frozen_cost_accounting(self) -> None:
        labels_by_id = {row["sample_id"]: row for row in read_jsonl(PILOT_LABELS)}
        expected_costs = {"31_pilot": 0.001515, "37_pilot": 0.004095}

        for name in ("31_pilot", "37_pilot"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                config, assets = load_and_validate_campaign(CONFIGS[name], REPO_ROOT)
                outputs = [
                    _output(
                        labels_by_id[row["sample_id"]]["class_label"] == "malicious"
                    )
                    for row in assets["dataset"]
                ]
                transport = FakeTransport(outputs)
                run_dir = run_campaign(
                    config_path=CONFIGS[name],
                    repo_root=REPO_ROOT,
                    output_root=Path(temporary) / "runs",
                    api_key=FAKE_KEY,
                    transport=transport,
                    sleep=lambda _: None,
                )
                scoring = score_run(
                    run_dir=run_dir,
                    labels_path=PILOT_LABELS,
                    output_dir=None,
                    repo_root=REPO_ROOT,
                )
                metrics = read_json(scoring / "metrics.json")
                results = read_jsonl(run_dir / "results.jsonl")

                self.assertEqual(len(transport.calls), 30)
                self.assertTrue(all(row["status"] == "success" for row in results))
                self.assertTrue(
                    all(row["resolved_model"] == config["requested_model"] for row in results)
                )
                self.assertEqual(
                    metrics["campaign_status"], "PILOT_READY_FOR_SELECTION"
                )
                self.assertEqual(
                    metrics["cost"]["observed_usd"], expected_costs[name]
                )


if __name__ == "__main__":
    unittest.main()
