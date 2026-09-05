from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"
sys.path.insert(0, str(BENCHMARKS_DIR))

from phishing_bench.comparison import (  # noqa: E402
    LoadedRun,
    _compatibility,
    _render_report,
)
from phishing_bench.scoring import (  # noqa: E402
    TOKEN_CAP_ADJUSTED_COMPARISON_TYPE,
    _comparison_scope_type,
    _token_cap_adjusted_bundle_note,
    _token_cap_adjustment,
)


def _runtime_config(*, crew: bool) -> dict[str, Any]:
    config: dict[str, Any] = {
        "adapter": "crewai_sequential_offline" if crew else "gemini_generate_content",
        "provider": "google",
        "requested_model": "gemini-3.7-flash",
        "request_profile": (
            "crewai_google_generate_content_v1"
            if crew
            else "gemini_native_generate_content_v1"
        ),
        "max_output_tokens": 1000 if crew else 500,
        "reasoning_effort": None,
    }
    if crew:
        config["system_bundle_delta"] = {
            "comparison_name": "system_bundle_delta",
            "same_provider_api": True,
            "same_max_output_tokens": False,
            "direct_max_output_tokens": 500,
            "crewai_max_output_tokens": 1000,
        }
    return config


def _loaded_run(variant_id: str, *, crew: bool) -> LoadedRun:
    common_hashes = {
        "dataset_sha256": "dataset",
        "dataset_manifest_sha256": "dataset-manifest",
        "response_schema_sha256": "schema",
        "prompt_sha256": "crew-prompt" if crew else "direct-prompt",
    }
    return LoadedRun(
        variant_id=variant_id,
        run_dir=Path(f"/{variant_id}"),
        manifest={
            "runtime_config": _runtime_config(crew=crew),
            "readiness": {"hashes": common_hashes},
        },
        metrics={
            "stage": "ENGINEERING_PILOT",
            "scoring_profile": "binary_quality_v1",
            "hashes": {
                "labels_sha256": "labels",
                "decision_policy_sha256": "policy",
            },
            "confusion_matrix": {
                "positive_actions": ["warn", "hide"],
                "positive_class": "malicious",
                "negative_action": "allow",
                "technical_failures_use_action": "allow",
                "technical_failures_in_denominators": True,
            },
        },
        results=[{"sample_id": "sample", "hashes": {"input_sha256": "input"}}],
        scored=[{"sample_id": "sample"}],
        labels=[{"sample_id": "sample"}],
    )


class TokenCapReportingTests(unittest.TestCase):
    def test_scoring_helpers_name_and_explain_the_adjusted_bundle(self) -> None:
        config = _runtime_config(crew=True)

        self.assertEqual(
            _token_cap_adjustment(config),
            {
                "comparison_type": TOKEN_CAP_ADJUSTED_COMPARISON_TYPE,
                "direct_max_output_tokens": 500,
                "crewai_max_output_tokens": 1000,
            },
        )
        self.assertEqual(
            _comparison_scope_type(config), TOKEN_CAP_ADJUSTED_COMPARISON_TYPE
        )
        note = _token_cap_adjusted_bundle_note(config)
        self.assertIn("token-cap-adjusted system bundle", note)
        self.assertIn("500 dla Direct", note)
        self.assertIn("1000 dla CrewAI", note)
        self.assertIn("Nie jest to porównanie apples-to-apples", note)
        self.assertIn("ani czysta delta frameworka", note)

    def test_malformed_or_equal_cap_disclosure_is_not_reported_as_adjusted(self) -> None:
        for direct_cap, crew_cap in ((500, 500), (None, 1000), (500, True)):
            with self.subTest(direct_cap=direct_cap, crew_cap=crew_cap):
                config = _runtime_config(crew=True)
                config["system_bundle_delta"]["direct_max_output_tokens"] = direct_cap
                config["system_bundle_delta"]["crewai_max_output_tokens"] = crew_cap
                self.assertIsNone(_token_cap_adjustment(config))

    def test_comparison_exports_adjusted_type_caps_and_non_apples_caveat(self) -> None:
        compatibility = _compatibility(
            [
                _loaded_run("direct", crew=False),
                _loaded_run("crew", crew=True),
            ]
        )

        self.assertEqual(
            compatibility["comparison_type"],
            TOKEN_CAP_ADJUSTED_COMPARISON_TYPE,
        )
        self.assertFalse(compatibility["same_architecture"])
        self.assertTrue(compatibility["same_model"])
        self.assertTrue(compatibility["same_provider"])
        self.assertFalse(compatibility["same_max_output_tokens"])
        self.assertEqual(compatibility["max_output_tokens"], [500, 1000])
        self.assertEqual(
            compatibility["token_cap_adjustments"],
            [
                {
                    "variant_id": "crew",
                    "comparison_type": TOKEN_CAP_ADJUSTED_COMPARISON_TYPE,
                    "direct_max_output_tokens": 500,
                    "crewai_max_output_tokens": 1000,
                }
            ],
        )

        run_row = {
            "variant_id": "direct",
            "adapter": "gemini_generate_content",
            "requested_model": "gemini-3.7-flash",
            "success_count": 30,
            "technical_failures": 0,
            "tp": 15,
            "fp": 1,
            "tn": 14,
            "fn": 0,
            "precision": 0.9375,
            "recall": 1.0,
            "f1": 0.967742,
            "false_positive_rate": 0.066667,
            "observed_cost_usd": 0.01,
            "latency_median_ms": 1000,
            "campaign_status": "PILOT_HOLD",
        }
        report = _render_report(
            run_rows=[run_row],
            pairwise_rows=[],
            compatibility=compatibility,
        )
        self.assertIn(TOKEN_CAP_ADJUSTED_COMPARISON_TYPE, report)
        self.assertIn("token-cap-adjusted system bundle", report)
        self.assertIn("dla ramienia `crew`", report)
        self.assertIn("Direct=500", report)
        self.assertIn("CrewAI=1000", report)
        self.assertIn("nie jest apples-to-apples", report)
        self.assertIn("ani czystą deltą frameworka", report)

    def test_multi_model_report_still_warns_about_an_adjusted_arm(self) -> None:
        compatibility = _compatibility(
            [
                _loaded_run("direct", crew=False),
                _loaded_run("crew", crew=True),
            ]
        )
        compatibility["comparison_type"] = "system_bundle_delta"

        report = _render_report(
            run_rows=[],
            pairwise_rows=[],
            compatibility=compatibility,
        )

        self.assertIn("token-cap-adjusted system bundle", report)
        self.assertIn("dla ramienia `crew`", report)
        self.assertIn("Direct=500", report)
        self.assertIn("CrewAI=1000", report)

    def test_same_architecture_different_caps_are_not_called_replication(self) -> None:
        lower_cap = _loaded_run("crew-v2", crew=True)
        lower_config = lower_cap.manifest["runtime_config"]
        lower_config["max_output_tokens"] = 500
        lower_config["system_bundle_delta"].pop("same_max_output_tokens")
        lower_config["system_bundle_delta"].pop("direct_max_output_tokens")
        lower_config["system_bundle_delta"].pop("crewai_max_output_tokens")

        compatibility = _compatibility(
            [lower_cap, _loaded_run("crew-v3", crew=True)]
        )

        self.assertFalse(compatibility["same_max_output_tokens"])
        self.assertEqual(
            compatibility["comparison_type"], TOKEN_CAP_ADJUSTED_COMPARISON_TYPE
        )


if __name__ == "__main__":
    unittest.main()
