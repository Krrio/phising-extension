from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"
sys.path.insert(0, str(BENCHMARKS_DIR))

from phishing_bench.contracts import ContractError  # noqa: E402
from phishing_bench.io_utils import (  # noqa: E402
    atomic_write_json,
    read_json,
    read_jsonl,
    sha256_file,
    write_jsonl,
)
from phishing_bench.openai_direct import (  # noqa: E402
    ProviderError,
    ProviderResponse,
)
from phishing_bench.runner import run_campaign  # noqa: E402
from phishing_bench.scoring import score_run  # noqa: E402


BASE_CAMPAIGN_DIR = (
    BENCHMARKS_DIR / "campaigns" / "BUDGET_30H_OPENAI_SMOKE_001"
)
BASE_CONFIG_PATH = BASE_CAMPAIGN_DIR / "runtime_config.json"
FAKE_KEY = "sk-test_QUALITY_SCORER_FAKE_123456"


def _model_output(verdict: str) -> dict[str, Any]:
    if verdict == "safe":
        trust_score = 95
        categories: list[str] = []
    elif verdict == "suspicious":
        trust_score = 55
        categories = ["impersonation"]
    else:
        trust_score = 10
        categories = ["impersonation"]
    return {
        "trustScore": trust_score,
        "verdict": verdict,
        "confidence": 0.95,
        "reasoning": "Syntetyczne uzasadnienie testowe.",
        "categories": categories,
        "policyAssessment": None,
    }


class FakeQualityTransport:
    def __init__(self, plans: list[Any]) -> None:
        self.plans = list(plans)
        self.calls = 0

    def call(
        self,
        *,
        api_key: str,
        endpoint: str,
        body: dict[str, Any],
        timeout_seconds: float,
    ) -> ProviderResponse:
        del api_key, endpoint, timeout_seconds
        self.calls += 1
        plan = self.plans.pop(0)
        if isinstance(plan, Exception):
            raise plan
        content = json.dumps(plan, ensure_ascii=False)
        return ProviderResponse(
            response_id=f"chatcmpl-quality-{self.calls}",
            requested_model=body["model"],
            resolved_model=body["model"],
            content=content,
            finish_reason="stop",
            refusal=None,
            tool_calls_present=False,
            usage={
                "input_tokens": 120,
                "cached_input_tokens": 0,
                "output_tokens": 30,
                "reasoning_tokens": 0,
                "total_tokens": 150,
            },
            safe_headers={"x-request-id": f"req-quality-{self.calls}"},
            elapsed_ms=float(self.calls),
            raw_response_sha256_material=content.encode("utf-8"),
        )


class QualityScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(
            prefix=".quality-scoring-test-", dir=BENCHMARKS_DIR
        )
        cls.work_dir = Path(cls.temporary.name)
        cls.dataset_path = cls.work_dir / "runner_input.jsonl"
        cls.dataset_manifest_path = cls.work_dir / "dataset_manifest.json"
        cls.labels_path = cls.work_dir / "scoring_bundle" / "labels.jsonl"
        cls.config_path = cls.work_dir / "runtime_config.json"

        records: list[dict[str, Any]] = []
        labels: list[dict[str, Any]] = []
        for index in range(30):
            sample_id = str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"quality-scoring-test-{index:02d}")
            )
            records.append(
                {
                    "sample_id": sample_id,
                    "organization_policy": None,
                    "untrusted_analysis": {
                        "content": (
                            f"Syntetyczna wiadomość pilota {index:02d}. "
                            f"Link https://service-{index:02d}.example/path"
                        ),
                        "signals": {
                            "suspiciousPhrases": [],
                            "linkMismatches": [],
                            "suspiciousDomains": [],
                        },
                    },
                }
            )
            malicious = index < 15
            labels.append(
                {
                    "sample_id": sample_id,
                    "case_name": f"case_{index:02d}",
                    "class_label": "malicious" if malicious else "benign",
                    "acceptable_actions": ["warn", "hide"] if malicious else ["allow"],
                    "security_probe": index in {0, 1},
                    "scenario": f"scenario_{index:02d}",
                    "difficulty": ("typical", "edge", "adversarial")[index % 3],
                    "language": "EN" if index in {14, 29} else "PL",
                    "label_confidence": "medium" if index in {4, 20} else "high",
                    "analysis_cluster_id": f"cluster_{index:02d}",
                }
            )
        write_jsonl(cls.dataset_path, records)
        write_jsonl(cls.labels_path, labels)
        atomic_write_json(
            cls.dataset_manifest_path,
            {
                "schema_version": "1.0",
                "dataset_id": "OPENAI_PILOT_030_V1",
                "sample_count": 30,
                "source_pool_count": 39,
                "source_type": "synthetic",
                "data_class": "synthetic_reserved_domains_only",
                "signals_mode": "product_derived_v1",
                "renderer_version": "visible_text_v1",
                "source_pool_sha256": "1" * 64,
                "selection_manifest_sha256": "2" * 64,
                "generator_sha256": "3" * 64,
            },
        )

        config = read_json(BASE_CONFIG_PATH)
        config.update(
            {
                "campaign_id": "QUALITY_SCORING_TEST_001",
                "config_id": "direct__quality-scoring-test",
                "evaluation_profile": "openai_direct_quality_pilot_v1",
                "expected_sample_count": 30,
                "dataset_path": str(cls.dataset_path.relative_to(REPO_ROOT)),
                "dataset_manifest_path": str(
                    cls.dataset_manifest_path.relative_to(REPO_ROOT)
                ),
                "budget": {
                    "max_attempts": 60,
                    "max_cost_usd": 0.25,
                    "max_wall_seconds": 7200,
                },
            }
        )
        config["expected_asset_sha256"]["dataset"] = sha256_file(cls.dataset_path)
        config["expected_asset_sha256"]["dataset_manifest"] = sha256_file(
            cls.dataset_manifest_path
        )
        atomic_write_json(cls.config_path, config)
        cls._write_scoring_manifest(cls.labels_path)

        cls.green_plans = cls._green_plans()
        cls.green_run_dir = run_campaign(
            config_path=cls.config_path,
            repo_root=REPO_ROOT,
            output_root=cls.work_dir / "green-runs",
            api_key=FAKE_KEY,
            transport=FakeQualityTransport(cls.green_plans),
            sleep=lambda _: None,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    @classmethod
    def _write_scoring_manifest(cls, labels_path: Path) -> None:
        atomic_write_json(
            labels_path.parent / "scoring_manifest.json",
            {
                "schema_version": "1.0",
                "scoring_profile": "binary_quality_v1",
                "campaign_id": "QUALITY_SCORING_TEST_001",
                "sample_count": 30,
                "runner_dataset_sha256": sha256_file(cls.dataset_path),
                "labels_sha256": sha256_file(labels_path),
            },
        )

    @staticmethod
    def _green_plans() -> list[dict[str, Any]]:
        plans: list[dict[str, Any]] = []
        for index in range(30):
            if index < 3:
                verdict = "phishing"
            elif index < 13:
                verdict = "suspicious"
            elif index < 15:
                verdict = "safe"
            elif index < 18:
                verdict = "suspicious"
            else:
                verdict = "safe"
            plans.append(_model_output(verdict))
        return plans

    def test_dispatch_scores_balanced_pilot_with_raw_descriptive_metrics(self) -> None:
        score_dir = score_run(
            run_dir=self.green_run_dir,
            labels_path=self.labels_path,
            output_dir=self.work_dir / "green-score",
            repo_root=REPO_ROOT,
        )
        metrics = read_json(score_dir / "metrics.json")
        self.assertEqual(metrics["scoring_profile"], "binary_quality_v1")
        self.assertEqual(metrics["campaign_status"], "PILOT_READY_FOR_SELECTION")
        self.assertEqual(metrics["comparative_conclusion"], "INCONCLUSIVE")
        self.assertTrue(metrics["acceptance_pass"])
        fp_gate = metrics["acceptance_criteria"][
            "benign_positive_actions_at_most_three"
        ]
        self.assertEqual(fp_gate["observed"], 3)
        self.assertEqual(fp_gate["required_max"], 3)
        self.assertTrue(fp_gate["pass"])
        self.assertEqual(
            metrics["confusion_matrix"],
            {
                "positive_class": "malicious",
                "positive_actions": ["warn", "hide"],
                "negative_action": "allow",
                "technical_failures_use_action": "allow",
                "technical_failures_in_denominators": True,
                "tp": 13,
                "fp": 3,
                "tn": 12,
                "fn": 2,
                "total": 30,
            },
        )
        classification = metrics["classification_metrics"]
        self.assertEqual(classification["precision"]["value"], 0.8125)
        self.assertEqual(classification["recall"]["value"], 0.866667)
        self.assertEqual(classification["f1"]["value"], 0.83871)
        self.assertEqual(classification["false_positive_rate"]["value"], 0.2)
        self.assertEqual(classification["false_negative_rate"]["value"], 0.133333)
        self.assertEqual(classification["specificity"]["value"], 0.8)
        self.assertEqual(classification["balanced_accuracy"]["value"], 0.833333)
        for name in ("recall", "false_positive_rate", "specificity"):
            interval = classification[name]["confidence_interval_95"]
            self.assertEqual(interval["method"], "Wilson score")
            self.assertTrue(interval["descriptive"])
            self.assertLess(interval["lower"], classification[name]["value"])
            self.assertGreater(interval["upper"], classification[name]["value"])
        self.assertEqual(
            metrics["outcomes_by_class"]["malicious"]["actions"],
            {"allow": 2, "warn": 10, "hide": 3},
        )
        self.assertEqual(
            metrics["outcomes_by_class"]["benign"]["actions"],
            {"allow": 12, "warn": 3, "hide": 0},
        )
        self.assertEqual(
            metrics["golden_acceptable_actions"]["system_action_matches"], 25
        )
        self.assertTrue(metrics["validity"]["usage_accounting_complete"])
        self.assertEqual(metrics["latency_ms"]["status_success_count"], 30)
        self.assertNotIn("p95", metrics["latency_ms"])
        self.assertNotIn("p99", metrics["latency_ms"])
        report = (score_dir / "report.md").read_text(encoding="utf-8")
        self.assertIn("INCONCLUSIVE", report)
        self.assertIn("syntetycznych i challenge-enriched", report)
        self.assertIn("Nie jest to dowód gotowości produkcyjnej", report)

    def test_fourth_benign_positive_action_holds_pilot(self) -> None:
        plans = deepcopy(self.green_plans)
        plans[18] = _model_output("suspicious")
        run_dir = run_campaign(
            config_path=self.config_path,
            repo_root=REPO_ROOT,
            output_root=self.work_dir / "fp-gate-runs",
            api_key=FAKE_KEY,
            transport=FakeQualityTransport(plans),
            sleep=lambda _: None,
        )
        score_dir = score_run(
            run_dir=run_dir,
            labels_path=self.labels_path,
            output_dir=self.work_dir / "fp-gate-score",
            repo_root=REPO_ROOT,
        )
        metrics = read_json(score_dir / "metrics.json")
        fp_gate = metrics["acceptance_criteria"][
            "benign_positive_actions_at_most_three"
        ]
        self.assertEqual(metrics["confusion_matrix"]["fp"], 4)
        self.assertEqual(fp_gate["observed"], 4)
        self.assertFalse(fp_gate["pass"])
        self.assertFalse(metrics["acceptance_pass"])
        self.assertEqual(metrics["campaign_status"], "PILOT_HOLD")

    def test_third_malicious_allow_holds_pilot(self) -> None:
        plans = deepcopy(self.green_plans)
        plans[12] = _model_output("safe")
        run_dir = run_campaign(
            config_path=self.config_path,
            repo_root=REPO_ROOT,
            output_root=self.work_dir / "fn-gate-runs",
            api_key=FAKE_KEY,
            transport=FakeQualityTransport(plans),
            sleep=lambda _: None,
        )
        score_dir = score_run(
            run_dir=run_dir,
            labels_path=self.labels_path,
            output_dir=self.work_dir / "fn-gate-score",
            repo_root=REPO_ROOT,
        )
        metrics = read_json(score_dir / "metrics.json")
        fn_gate = metrics["acceptance_criteria"]["malicious_allow_at_most_two"]
        self.assertEqual(metrics["confusion_matrix"]["fn"], 3)
        self.assertEqual(fn_gate["observed"], 3)
        self.assertFalse(fn_gate["pass"])
        self.assertFalse(metrics["acceptance_pass"])
        self.assertEqual(metrics["campaign_status"], "PILOT_HOLD")

    def test_technical_failure_maps_to_fail_open_and_stays_in_denominators(self) -> None:
        failures = [
            ProviderError("network_error", "synthetic failure", retryable=True),
            ProviderError("network_error", "synthetic failure", retryable=True),
        ]
        run_dir = run_campaign(
            config_path=self.config_path,
            repo_root=REPO_ROOT,
            output_root=self.work_dir / "technical-runs",
            api_key=FAKE_KEY,
            transport=FakeQualityTransport([*failures, *self.green_plans[1:]]),
            sleep=lambda _: None,
        )
        score_dir = score_run(
            run_dir=run_dir,
            labels_path=self.labels_path,
            output_dir=self.work_dir / "technical-score",
            repo_root=REPO_ROOT,
        )
        metrics = read_json(score_dir / "metrics.json")
        self.assertEqual(metrics["campaign_status"], "PILOT_HOLD")
        self.assertEqual(metrics["records"]["technical_failures"], 1)
        self.assertEqual(
            metrics["records"]["technical_failure_gate"], "HOLD_SINGLE_FAILURE"
        )
        self.assertEqual(metrics["attempts"]["retries"], 1)
        self.assertEqual(metrics["attempts"]["cost_unknown_attempts"], 2)
        self.assertEqual(metrics["confusion_matrix"]["total"], 30)
        self.assertEqual(metrics["confusion_matrix"]["fn"], 3)
        self.assertEqual(metrics["confusion_matrix"]["tp"], 12)
        self.assertFalse(metrics["validity"]["usage_accounting_complete"])
        scored = read_jsonl(score_dir / "scored_results.jsonl")
        self.assertTrue(scored[0]["technical_failure"])
        self.assertTrue(scored[0]["technical_failure_action_applied"])
        self.assertEqual(scored[0]["predicted_action"], "allow")
        self.assertEqual(scored[0]["confusion_cell"], "fn")

    def test_quality_scorer_rejects_label_and_run_tampering(self) -> None:
        tampered_bundle = self.work_dir / "tampered-bundle"
        shutil.copytree(self.labels_path.parent, tampered_bundle)
        tampered_labels_path = tampered_bundle / "labels.jsonl"
        labels = read_jsonl(tampered_labels_path)
        labels[0]["case_name"] = "changed_after_freeze"
        write_jsonl(tampered_labels_path, labels)
        with self.assertRaisesRegex(ContractError, "does not freeze"):
            score_run(
                run_dir=self.green_run_dir,
                labels_path=tampered_labels_path,
                output_dir=self.work_dir / "tampered-label-score",
                repo_root=REPO_ROOT,
            )

        tampered_run = self.work_dir / "tampered-run"
        shutil.copytree(self.green_run_dir, tampered_run)
        results_path = tampered_run / "results.jsonl"
        results = read_jsonl(results_path)
        results[0]["usage"]["input_tokens"] += 1
        write_jsonl(results_path, results)
        manifest_path = tampered_run / "run_manifest.json"
        manifest = read_json(manifest_path)
        manifest["artifact_hashes"]["results_jsonl_sha256"] = sha256_file(results_path)
        atomic_write_json(manifest_path, manifest)
        with self.assertRaisesRegex(ContractError, "does not reconcile"):
            score_run(
                run_dir=tampered_run,
                labels_path=self.labels_path,
                output_dir=self.work_dir / "tampered-run-score",
                repo_root=REPO_ROOT,
            )

    def test_action_mapping_drift_marks_quality_run_invalid(self) -> None:
        tampered_run = self.work_dir / "action-drift-run"
        shutil.copytree(self.green_run_dir, tampered_run)
        results_path = tampered_run / "results.jsonl"
        results = read_jsonl(results_path)
        self.assertEqual(results[0]["action"], "hide")
        results[0]["action"] = "warn"
        write_jsonl(results_path, results)
        manifest_path = tampered_run / "run_manifest.json"
        manifest = read_json(manifest_path)
        manifest["artifact_hashes"]["results_jsonl_sha256"] = sha256_file(results_path)
        atomic_write_json(manifest_path, manifest)
        score_dir = score_run(
            run_dir=tampered_run,
            labels_path=self.labels_path,
            output_dir=self.work_dir / "action-drift-score",
            repo_root=REPO_ROOT,
        )
        metrics = read_json(score_dir / "metrics.json")
        self.assertEqual(metrics["campaign_status"], "INVALID")
        self.assertEqual(metrics["validity"]["action_mapping_errors"], 1)

    def test_quality_profile_and_readiness_contract_must_match(self) -> None:
        cases = (
            ("runtime-profile", "runtime_config", "evaluation_profile", "wrong_profile"),
            ("runtime-count", "runtime_config", "expected_sample_count", 29),
            ("readiness-profile", "readiness", "evaluation_profile", "wrong_profile"),
            ("readiness-count", "readiness", "record_count", 29),
            ("runtime-retry", "runtime_config", "max_retries_per_sample", 0),
            ("runtime-timeout", "runtime_config", "request_timeout_seconds", 44),
            ("readiness-budget", "readiness", "budget", {"max_attempts": 1}),
            ("readiness-security", "readiness", "security_contract", {}),
            ("readiness-reservation", "readiness", "required_cost_cap_with_margin_usd", 0.0),
        )
        for name, section, field, value in cases:
            with self.subTest(name=name):
                run_dir = self.work_dir / f"profile-mismatch-{name}"
                shutil.copytree(self.green_run_dir, run_dir)
                manifest_path = run_dir / "run_manifest.json"
                manifest = read_json(manifest_path)
                manifest[section][field] = value
                atomic_write_json(manifest_path, manifest)
                with self.assertRaisesRegex(
                    ContractError, "quality run profile/readiness contract mismatch"
                ):
                    score_run(
                        run_dir=run_dir,
                        labels_path=self.labels_path,
                        output_dir=self.work_dir / f"profile-mismatch-score-{name}",
                        repo_root=REPO_ROOT,
                    )

        run_dir = self.work_dir / "profile-mismatch-readiness-hash"
        shutil.copytree(self.green_run_dir, run_dir)
        manifest_path = run_dir / "run_manifest.json"
        manifest = read_json(manifest_path)
        manifest["readiness"]["hashes"]["dataset_sha256"] = "0" * 64
        atomic_write_json(manifest_path, manifest)
        with self.assertRaisesRegex(
            ContractError, "quality run profile/readiness contract mismatch"
        ):
            score_run(
                run_dir=run_dir,
                labels_path=self.labels_path,
                output_dir=self.work_dir / "profile-mismatch-score-readiness-hash",
                repo_root=REPO_ROOT,
            )

    def test_critical_security_event_takes_precedence_over_hold(self) -> None:
        critical_output = _model_output("phishing")
        critical_output["reasoning"] = "[H — HIERARCHIA ZAUFANIA] syntetyczny canary"
        run_dir = run_campaign(
            config_path=self.config_path,
            repo_root=REPO_ROOT,
            output_root=self.work_dir / "security-runs",
            api_key=FAKE_KEY,
            transport=FakeQualityTransport([critical_output]),
            sleep=lambda _: None,
        )
        score_dir = score_run(
            run_dir=run_dir,
            labels_path=self.labels_path,
            output_dir=self.work_dir / "security-score",
            repo_root=REPO_ROOT,
        )
        metrics = read_json(score_dir / "metrics.json")
        self.assertEqual(metrics["campaign_status"], "SECURITY_FAIL")
        self.assertEqual(metrics["failures"]["critical_security_events"], 1)
        self.assertEqual(metrics["records"]["technical_failures"], 29)
        self.assertEqual(metrics["confusion_matrix"]["total"], 30)

    def test_manifest_and_label_contracts_are_exact(self) -> None:
        bundle = self.work_dir / "extra-field-bundle"
        shutil.copytree(self.labels_path.parent, bundle)
        labels_path = bundle / "labels.jsonl"
        labels = read_jsonl(labels_path)
        labels[0]["unexpected"] = True
        write_jsonl(labels_path, labels)
        self._write_scoring_manifest(labels_path)
        with self.assertRaisesRegex(ContractError, "fields do not match"):
            score_run(
                run_dir=self.green_run_dir,
                labels_path=labels_path,
                output_dir=self.work_dir / "extra-field-score",
                repo_root=REPO_ROOT,
            )


if __name__ == "__main__":
    unittest.main()
