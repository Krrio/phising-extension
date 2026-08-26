from __future__ import annotations

import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"
sys.path.insert(0, str(BENCHMARKS_DIR))

from phishing_bench.contracts import (  # noqa: E402
    ContractError,
    QUALITY_PILOT_PROFILE,
    build_chat_request,
    load_and_validate_campaign,
    validate_runtime_config,
)
from phishing_bench.io_utils import read_json  # noqa: E402
from phishing_bench.runner import readiness_report  # noqa: E402


CONFIG_PATH = (
    BENCHMARKS_DIR
    / "campaigns"
    / "BUDGET_30H_OPENAI_PILOT_030_001"
    / "runtime_config.json"
)


class QualityCampaignContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = read_json(CONFIG_PATH)

    def test_frozen_quality_campaign_is_complete_and_label_free(self) -> None:
        config, assets = load_and_validate_campaign(CONFIG_PATH, REPO_ROOT)
        report = readiness_report(CONFIG_PATH, REPO_ROOT, check_local_tls=False)

        self.assertEqual(config["evaluation_profile"], QUALITY_PILOT_PROFILE)
        self.assertEqual(config["expected_sample_count"], 30)
        self.assertEqual(len(assets["dataset"]), 30)
        self.assertEqual(report["record_count"], 30)
        self.assertEqual(report["evaluation_profile"], QUALITY_PILOT_PROFILE)
        self.assertEqual(report["budget"], {
            "max_attempts": 60,
            "max_cost_usd": 0.25,
            "max_wall_seconds": 7200,
        })
        self.assertLessEqual(
            report["required_cost_cap_with_margin_usd"],
            report["budget"]["max_cost_usd"],
        )
        self.assertEqual(
            assets["dataset_manifest"]["dataset_id"], "OPENAI_PILOT_030_V1"
        )
        self.assertNotIn("class_counts", assets["dataset_manifest"])

        serialized_requests = []
        for record in assets["dataset"]:
            body = build_chat_request(
                config, record, assets["prompt"], assets["response_schema"]
            )
            serialized_requests.append(json.dumps(body, ensure_ascii=False).casefold())
        joined = "\n".join(serialized_requests)
        for forbidden in (
            "class_label",
            "acceptable_actions",
            "label_confidence",
            "analysis_cluster_id",
            "justification",
            "security_probe",
        ):
            self.assertNotIn(forbidden, joined)

    def test_quality_runtime_rejects_any_frozen_limit_drift(self) -> None:
        mutations = (
            ("expected_sample_count_bool", lambda c: c.__setitem__("expected_sample_count", True)),
            ("expected_sample_count_29", lambda c: c.__setitem__("expected_sample_count", 29)),
            ("retry_bool", lambda c: c.__setitem__("max_retries_per_sample", True)),
            ("retry_zero", lambda c: c.__setitem__("max_retries_per_sample", 0)),
            ("timeout", lambda c: c.__setitem__("request_timeout_seconds", 44)),
            ("attempts", lambda c: c["budget"].__setitem__("max_attempts", 59)),
            ("attempts_bool", lambda c: c["budget"].__setitem__("max_attempts", True)),
            ("cost", lambda c: c["budget"].__setitem__("max_cost_usd", 0.250001)),
            ("cost_bool", lambda c: c["budget"].__setitem__("max_cost_usd", True)),
            ("wall", lambda c: c["budget"].__setitem__("max_wall_seconds", 7199)),
            ("wall_float", lambda c: c["budget"].__setitem__("max_wall_seconds", 7200.0)),
            ("unknown_profile", lambda c: c.__setitem__("evaluation_profile", "unknown")),
        )
        for name, mutate in mutations:
            with self.subTest(name=name):
                changed = deepcopy(self.config)
                mutate(changed)
                with self.assertRaises(ContractError):
                    validate_runtime_config(changed, REPO_ROOT)

    def test_quality_requires_exactly_30_records_before_request_building(self) -> None:
        _, assets = load_and_validate_campaign(CONFIG_PATH, REPO_ROOT)
        with patch(
            "phishing_bench.contracts.read_jsonl",
            return_value=deepcopy(assets["dataset"][:-1]),
        ), patch("phishing_bench.contracts.build_chat_request") as build_request:
            with self.assertRaisesRegex(ContractError, "exactly 30"):
                load_and_validate_campaign(CONFIG_PATH, REPO_ROOT)
        build_request.assert_not_called()

    def test_quality_rejects_localhost_even_though_legacy_smoke_allows_it(self) -> None:
        _, assets = load_and_validate_campaign(CONFIG_PATH, REPO_ROOT)
        changed_dataset = deepcopy(assets["dataset"])
        changed_dataset[0]["untrusted_analysis"]["content"] += " https://mail.localhost/path"
        with patch(
            "phishing_bench.contracts.read_jsonl", return_value=changed_dataset
        ):
            with self.assertRaisesRegex(ContractError, "excludes .localhost"):
                load_and_validate_campaign(CONFIG_PATH, REPO_ROOT)

    def test_asset_hash_drift_and_insufficient_reservation_are_rejected(self) -> None:
        changed = deepcopy(self.config)
        changed["expected_asset_sha256"]["dataset_manifest"] = "0" * 64
        with self.assertRaisesRegex(ContractError, "asset hash mismatch"):
            validate_runtime_config(changed, REPO_ROOT)

        with patch(
            "phishing_bench.runner.conservative_attempt_reservation",
            return_value=0.004,
        ):
            with self.assertRaisesRegex(ContractError, "required campaign reservation"):
                readiness_report(CONFIG_PATH, REPO_ROOT, check_local_tls=False)


if __name__ == "__main__":
    unittest.main()
