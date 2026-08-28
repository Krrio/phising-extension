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

from phishing_bench.contracts import (  # noqa: E402
    ContractError,
    GPT54_NANO_QUALITY_PILOT_PROFILE,
    GPT54_NANO_REQUEST_PROFILE,
    GPT54_NANO_SMOKE_PROFILE,
    build_chat_request,
    load_and_validate_campaign,
    validate_outgoing_request,
    validate_runtime_config,
)
from phishing_bench.comparison import compare_runs  # noqa: E402
from phishing_bench.io_utils import read_json, read_jsonl  # noqa: E402
from phishing_bench.openai_direct import ProviderResponse  # noqa: E402
from phishing_bench.runner import readiness_report, run_campaign  # noqa: E402
from phishing_bench.scoring import score_run  # noqa: E402


SMOKE_CONFIG_PATH = (
    BENCHMARKS_DIR
    / "campaigns"
    / "BUDGET_30H_OPENAI_GPT54_NANO_SMOKE_001"
    / "runtime_config.json"
)
PILOT_CONFIG_PATH = (
    BENCHMARKS_DIR
    / "campaigns"
    / "BUDGET_30H_OPENAI_GPT54_NANO_PILOT_030_001"
    / "runtime_config.json"
)
BASE_SMOKE_CONFIG_PATH = (
    BENCHMARKS_DIR
    / "campaigns"
    / "BUDGET_30H_OPENAI_SMOKE_001"
    / "runtime_config.json"
)
BASE_PILOT_CONFIG_PATH = (
    BENCHMARKS_DIR
    / "campaigns"
    / "BUDGET_30H_OPENAI_PILOT_030_001"
    / "runtime_config.json"
)
PILOT_LABELS_PATH = (
    BENCHMARKS_DIR / "secure_scoring" / "openai_pilot_030_v1" / "labels.jsonl"
)
FAKE_KEY = "sk-test_GPT54_NANO_FAKE_123456"


def _output(malicious: bool) -> dict[str, Any]:
    return {
        "trustScore": 10 if malicious else 95,
        "verdict": "phishing" if malicious else "safe",
        "confidence": 0.95,
        "reasoning": "Syntetyczne uzasadnienie testowe GPT-5.4 nano.",
        "categories": ["impersonation"] if malicious else [],
        "policyAssessment": None,
    }


class FakeGPT54Transport:
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
            response_id=f"chatcmpl-gpt54-fake-{len(self.calls)}",
            requested_model=body["model"],
            resolved_model=body["model"],
            content=content,
            finish_reason="stop",
            refusal=None,
            tool_calls_present=False,
            usage={
                "input_tokens": 100,
                "cached_input_tokens": 0,
                "output_tokens": 20,
                "reasoning_tokens": 0,
                "total_tokens": 120,
            },
            safe_headers={"x-request-id": f"req-gpt54-{len(self.calls)}"},
            elapsed_ms=10.0,
            raw_response_sha256_material=content.encode("utf-8"),
        )


class GPT54NanoCampaignTests(unittest.TestCase):
    def test_campaigns_freeze_a_paired_model_delta_and_current_request_contract(self) -> None:
        smoke, smoke_assets = load_and_validate_campaign(SMOKE_CONFIG_PATH, REPO_ROOT)
        pilot, pilot_assets = load_and_validate_campaign(PILOT_CONFIG_PATH, REPO_ROOT)
        base_smoke = read_json(BASE_SMOKE_CONFIG_PATH)
        base_pilot = read_json(BASE_PILOT_CONFIG_PATH)

        self.assertEqual(smoke["evaluation_profile"], GPT54_NANO_SMOKE_PROFILE)
        self.assertEqual(
            pilot["evaluation_profile"], GPT54_NANO_QUALITY_PILOT_PROFILE
        )
        self.assertEqual(smoke["requested_model"], "gpt-5.4-nano-2026-03-17")
        self.assertEqual(smoke["request_profile"], GPT54_NANO_REQUEST_PROFILE)
        self.assertEqual(smoke["reasoning_effort"], "none")
        self.assertEqual(len(smoke_assets["dataset"]), 5)
        self.assertEqual(len(pilot_assets["dataset"]), 30)

        for candidate, baseline in (
            (smoke, base_smoke),
            (pilot, base_pilot),
        ):
            for key in ("dataset", "prompt", "response_schema", "decision_policy"):
                self.assertEqual(
                    candidate["expected_asset_sha256"][key],
                    baseline["expected_asset_sha256"][key],
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
                "temperature",
                "reasoning_effort",
                "max_completion_tokens",
                "store",
                "messages",
                "response_format",
            },
        )
        self.assertEqual(body["temperature"], 0)
        self.assertEqual(body["reasoning_effort"], "none")
        self.assertEqual(body["max_completion_tokens"], 500)
        self.assertEqual([item["role"] for item in body["messages"]], ["developer", "user"])
        self.assertFalse(body["store"])
        self.assertNotIn("max_tokens", body)
        self.assertNotIn("tools", body)

        smoke_report = readiness_report(SMOKE_CONFIG_PATH, REPO_ROOT)
        pilot_report = readiness_report(PILOT_CONFIG_PATH, REPO_ROOT)
        self.assertEqual(
            smoke_report["request_contract"],
            {
                "request_profile": GPT54_NANO_REQUEST_PROFILE,
                "instruction_role": "developer",
                "token_limit_field": "max_completion_tokens",
                "reasoning_effort": "none",
                "temperature": 0,
            },
        )
        self.assertLessEqual(
            smoke_report["required_cost_cap_with_margin_usd"], 0.05
        )
        self.assertLessEqual(
            pilot_report["required_cost_cap_with_margin_usd"], 0.25
        )

    def test_config_and_outgoing_payload_drift_fail_closed(self) -> None:
        config, assets = load_and_validate_campaign(SMOKE_CONFIG_PATH, REPO_ROOT)
        mutations = (
            ("model_alias", lambda c: c.__setitem__("requested_model", "gpt-5.4-nano")),
            (
                "wrong_snapshot",
                lambda c: c.__setitem__("requested_model", "gpt-5.4-mini-2026-03-17"),
            ),
            ("reasoning", lambda c: c.__setitem__("reasoning_effort", "low")),
            ("request_profile", lambda c: c.__setitem__("request_profile", "changed")),
            ("temperature", lambda c: c.__setitem__("temperature", 1)),
            (
                "pricing",
                lambda c: c["pricing_usd_per_million_tokens"].__setitem__("output", 1.24),
            ),
            (
                "pricing_date",
                lambda c: c["pricing_usd_per_million_tokens"].__setitem__(
                    "source_checked_at", "2026-08-27"
                ),
            ),
        )
        for name, mutate in mutations:
            with self.subTest(name=name):
                changed = deepcopy(config)
                mutate(changed)
                with self.assertRaises(ContractError):
                    validate_runtime_config(changed, REPO_ROOT)

        body = build_chat_request(
            config, assets["dataset"][0], assets["prompt"], assets["response_schema"]
        )
        for name, mutate_body in (
            ("legacy_token_limit", lambda b: b.__setitem__("max_tokens", b.pop("max_completion_tokens"))),
            ("system_role", lambda b: b["messages"][0].__setitem__("role", "system")),
            ("reasoning_low", lambda b: b.__setitem__("reasoning_effort", "low")),
            ("tools", lambda b: b.__setitem__("tools", [])),
        ):
            with self.subTest(payload=name):
                changed_body = deepcopy(body)
                mutate_body(changed_body)
                with self.assertRaises(ContractError):
                    validate_outgoing_request(config, changed_body)

    def test_fake_pilot_runs_scores_and_accounts_for_gpt54_pricing(self) -> None:
        config, assets = load_and_validate_campaign(PILOT_CONFIG_PATH, REPO_ROOT)
        labels_by_id = {
            row["sample_id"]: row for row in read_jsonl(PILOT_LABELS_PATH)
        }
        plans = [
            _output(labels_by_id[record["sample_id"]]["class_label"] == "malicious")
            for record in assets["dataset"]
        ]
        transport = FakeGPT54Transport(plans)

        with tempfile.TemporaryDirectory() as temporary:
            output_root = Path(temporary) / "runs"
            run_dir = run_campaign(
                config_path=PILOT_CONFIG_PATH,
                repo_root=REPO_ROOT,
                output_root=output_root,
                api_key=FAKE_KEY,
                transport=transport,
                sleep=lambda _: None,
            )
            score_dir = score_run(
                run_dir=run_dir,
                labels_path=PILOT_LABELS_PATH,
                output_dir=None,
                repo_root=REPO_ROOT,
            )
            metrics = read_json(score_dir / "metrics.json")
            results = read_jsonl(run_dir / "results.jsonl")

            _, base_assets = load_and_validate_campaign(
                BASE_PILOT_CONFIG_PATH, REPO_ROOT
            )
            baseline_transport = FakeGPT54Transport(
                [
                    _output(
                        labels_by_id[record["sample_id"]]["class_label"]
                        == "malicious"
                    )
                    for record in base_assets["dataset"]
                ]
            )
            baseline_run = run_campaign(
                config_path=BASE_PILOT_CONFIG_PATH,
                repo_root=REPO_ROOT,
                output_root=output_root,
                api_key=FAKE_KEY,
                transport=baseline_transport,
                sleep=lambda _: None,
            )
            score_run(
                run_dir=baseline_run,
                labels_path=PILOT_LABELS_PATH,
                output_dir=None,
                repo_root=REPO_ROOT,
            )
            comparison_dir = compare_runs(
                named_run_dirs=[
                    ("baseline", baseline_run),
                    ("gpt54_nano", run_dir),
                ],
                labels_path=PILOT_LABELS_PATH,
                output_dir=Path(temporary) / "comparison",
                repo_root=REPO_ROOT,
            )
            comparison = read_json(comparison_dir / "comparison.json")

        self.assertEqual(len(transport.calls), 30)
        self.assertEqual(len(results), 30)
        self.assertTrue(all(row["status"] == "success" for row in results))
        self.assertEqual(metrics["campaign_status"], "PILOT_READY_FOR_SELECTION")
        self.assertEqual(
            metrics["confusion_matrix"],
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
        self.assertEqual(metrics["cost"]["observed_usd"], 0.00135)
        self.assertEqual(
            comparison["compatibility"]["comparison_type"],
            "model_or_provider_delta",
        )
        self.assertTrue(comparison["compatibility"]["same_prompt"])
        self.assertTrue(comparison["compatibility"]["same_adapter"])
        self.assertFalse(comparison["compatibility"]["same_request_profile"])
        self.assertEqual(
            comparison["compatibility"]["request_profiles"],
            ["chat_completions_legacy_v1", GPT54_NANO_REQUEST_PROFILE],
        )
        for call in transport.calls:
            self.assertEqual(call["body"]["model"], "gpt-5.4-nano-2026-03-17")
            self.assertEqual(call["body"]["reasoning_effort"], "none")
            self.assertNotIn("tools", call["body"])


if __name__ == "__main__":
    unittest.main()
