from __future__ import annotations

import csv
import importlib.util
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"

import sys

sys.path.insert(0, str(BENCHMARKS_DIR))

from phishing_bench.contracts import (  # noqa: E402
    ContractError,
    load_and_validate_campaign,
)
from phishing_bench.comparison import (  # noqa: E402
    LoadedRun,
    _run_row,
    _validate_metrics_against_records,
)
from phishing_bench.crewai_offline import (  # noqa: E402
    CrewCallObservation,
    CrewWorkflowExecution,
    run_crewai_campaign,
)
from phishing_bench.io_utils import (  # noqa: E402
    atomic_write_json,
    read_json,
    read_jsonl,
    sha256_file,
    sha256_text,
    write_jsonl,
)
from phishing_bench.quality_scoring import score_quality_run  # noqa: E402
from phishing_bench.scoring import (  # noqa: E402
    _execution_observability,
    score_run,
)


SMOKE_CONFIG = (
    BENCHMARKS_DIR
    / "campaigns"
    / "BUDGET_30H_CREWAI_GOOGLE_GEMINI35_FLASH_LITE_OFFLINE_SMOKE_002"
    / "runtime_config.json"
)
SMOKE_LABELS = (
    BENCHMARKS_DIR / "secure_scoring" / "openai_smoke_v1" / "labels.jsonl"
)
HAS_CREWAI = importlib.util.find_spec("crewai") is not None
FAKE_KEY = "gemini-crewai_FAKE_observability_123456"


class ExecutionObservabilityTests(unittest.TestCase):
    def test_attempt_events_distinguish_started_stopped_and_provider_failures(self) -> None:
        results = [
            {
                "sample_id": "sample-1",
                "attempt_ids": ["attempt-1"],
                "status": "timeout",
            },
            *[
                {
                    "sample_id": f"sample-{index}",
                    "attempt_ids": [],
                    "status": "campaign_stopped",
                }
                for index in range(2, 6)
            ],
        ]
        attempt_events = [
            {
                "event": "started",
                "sample_id": "sample-1",
                "attempt_id": "attempt-1",
            },
            {
                "event": "finished",
                "sample_id": "sample-1",
                "attempt_id": "attempt-1",
                "status": "timeout",
            },
        ]

        self.assertEqual(
            _execution_observability(
                results,
                expected_workflows=5,
                attempt_events=attempt_events,
            ),
            {
                "planned_workflows": 5,
                "started_workflows": 1,
                "not_attempted": 4,
                "provider_failures": 1,
            },
        )

    def test_quality_metrics_and_comparison_validate_fail_fast_observability(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "run"
            run_dir.mkdir()
            labels_path = root / "labels.jsonl"
            policy_path = root / "decision_policy.json"
            output_dir = root / "scoring"
            run_id = "QUALITY_OBSERVABILITY_TEST__001"
            campaign_id = "QUALITY_OBSERVABILITY_TEST"

            labels = []
            results = []
            for index in range(30):
                sample_id = f"sample-{index:02d}"
                malicious = index < 15
                labels.append(
                    {
                        "sample_id": sample_id,
                        "case_name": f"case_{index:02d}",
                        "class_label": "malicious" if malicious else "benign",
                        "acceptable_actions": (
                            ["warn", "hide"] if malicious else ["allow"]
                        ),
                        "security_probe": False,
                        "scenario": f"scenario_{index:02d}",
                        "difficulty": ("typical", "edge", "adversarial")[
                            index % 3
                        ],
                        "language": "pl",
                        "label_confidence": "high",
                        "analysis_cluster_id": f"cluster_{index:02d}",
                    }
                )
                started = index == 0
                results.append(
                    {
                        "sample_id": sample_id,
                        "status": "timeout" if started else "campaign_stopped",
                        "action": "allow",
                        "verdict": None,
                        "response_schema_valid": False,
                        "attempt_ids": ["attempt-1"] if started else [],
                        "outbound_attempts": 1 if started else 0,
                        "cost_unknown_attempts": 1 if started else 0,
                        "observed_cost_usd": 0.0,
                        "latency_ms": 120_000.0 if started else 0.0,
                        "usage": {
                            "input_tokens": 0,
                            "cached_input_tokens": 0,
                            "output_tokens": 0,
                            "reasoning_tokens": 0,
                            "total_tokens": 0,
                        },
                        "security_events": [],
                    }
                )

            manifest = {
                "run_id": run_id,
                "campaign_id": campaign_id,
                "stage": "ENGINEERING_PILOT",
                "status": "completed_with_failures",
                "runtime_config": {
                    "adapter": "crewai_sequential_offline",
                    "provider": "google",
                    "evaluation_profile": "test_quality_profile",
                    "config_id": "quality-observability-v1",
                    "requested_model": "gemini-test",
                    "request_profile": "native-test-v1",
                    "system_bundle_delta": {
                        "comparison_name": "test_bundle_delta"
                    },
                },
                "summary": {"elapsed_seconds": 120.0},
                "git": {"commit": "0" * 40, "dirty": False},
            }
            policy = {
                "schema_version": "1.0",
                "safe_action": "allow",
                "hide_when": {
                    "verdict": "phishing",
                    "trust_score_lt": 40,
                    "confidence_gte": 0.8,
                },
                "non_safe_fallback_action": "warn",
                "technical_failure_action": "allow",
            }
            attempt_events = [
                {
                    "event": "started",
                    "sample_id": "sample-00",
                    "attempt_id": "attempt-1",
                },
                {
                    "event": "finished",
                    "sample_id": "sample-00",
                    "attempt_id": "attempt-1",
                    "status": "timeout",
                },
            ]
            ledger = {"reserved_or_observed_cost_usd": 0.0110688}
            atomic_write_json(run_dir / "run_manifest.json", manifest)
            atomic_write_json(run_dir / "budget_ledger.json", ledger)
            atomic_write_json(policy_path, policy)
            write_jsonl(run_dir / "results.jsonl", results)
            write_jsonl(run_dir / "attempts.jsonl", attempt_events)
            write_jsonl(labels_path, labels)
            labels_hash = sha256_file(labels_path)

            with (
                patch(
                    "phishing_bench.quality_scoring._validate_quality_run_profile"
                ),
                patch(
                    "phishing_bench.quality_scoring._validate_run_integrity"
                ),
                patch(
                    "phishing_bench.quality_scoring._load_policy",
                    return_value=(policy, policy_path),
                ),
                patch(
                    "phishing_bench.quality_scoring._validate_scoring_bundle",
                    return_value={"labels_sha256": labels_hash},
                ),
            ):
                score_quality_run(
                    run_dir=run_dir,
                    labels_path=labels_path,
                    output_dir=output_dir,
                    repo_root=REPO_ROOT,
                )

            metrics = read_json(output_dir / "metrics.json")
            scored = read_jsonl(output_dir / "scored_results.jsonl")
            self.assertEqual(metrics["records"]["technical_failures"], 30)
            self.assertEqual(metrics["confusion_matrix"]["total"], 30)
            self.assertEqual(metrics["attempts"]["started_workflows"], 1)
            self.assertEqual(metrics["attempts"]["not_attempted"], 29)
            self.assertEqual(metrics["attempts"]["provider_failures"], 1)
            self.assertEqual(
                metrics["cost"]["ledger_reserved_or_observed_usd"],
                ledger["reserved_or_observed_cost_usd"],
            )

            _validate_metrics_against_records(
                manifest=manifest,
                metrics=metrics,
                results=results,
                scored=scored,
                labels=labels,
                labels_sha256=labels_hash,
                run_dir=run_dir,
            )
            run_row = _run_row(
                LoadedRun(
                    variant_id="quality_observability",
                    run_dir=run_dir,
                    manifest=manifest,
                    metrics=metrics,
                    results=results,
                    scored=scored,
                    labels=labels,
                )
            )
            self.assertEqual(run_row["started_workflows"], 1)
            self.assertEqual(run_row["not_attempted"], 29)
            self.assertEqual(run_row["provider_failures"], 1)
            self.assertEqual(
                run_row["ledger_reserved_or_observed_cost_usd"], 0.0110688
            )

            tampered = deepcopy(metrics)
            tampered["attempts"]["started_workflows"] = 2
            with self.assertRaisesRegex(
                ContractError, "started_workflows differs"
            ):
                _validate_metrics_against_records(
                    manifest=manifest,
                    metrics=tampered,
                    results=results,
                    scored=scored,
                    labels=labels,
                    labels_sha256=labels_hash,
                    run_dir=run_dir,
                )

    def test_runner_error_before_first_call_still_counts_as_started_workflow(self) -> None:
        results = [
            {
                "sample_id": "sample-1",
                "attempt_ids": [],
                "status": "runner_error",
            },
            {
                "sample_id": "sample-2",
                "attempt_ids": [],
                "status": "campaign_stopped",
            },
        ]

        self.assertEqual(
            _execution_observability(
                results,
                expected_workflows=2,
                attempt_events=[],
            ),
            {
                "planned_workflows": 2,
                "started_workflows": 1,
                "not_attempted": 1,
                "provider_failures": 0,
            },
        )


@unittest.skipUnless(HAS_CREWAI, "requires the pinned backend CrewAI environment")
class CrewAIFailFastObservabilityTests(unittest.TestCase):
    def test_smoke_scoring_reports_work_started_without_hiding_terminal_failures(
        self,
    ) -> None:
        config, _ = load_and_validate_campaign(SMOKE_CONFIG, REPO_ROOT)
        executor_calls = 0

        def executor(**kwargs: object) -> CrewWorkflowExecution:
            nonlocal executor_calls
            record = kwargs["record"]
            assert isinstance(record, dict)
            executor_calls += 1
            if executor_calls > 1:
                self.fail("fail-fast must stop before a second workflow")
            return CrewWorkflowExecution(
                raw_output=None,
                calls=(
                    CrewCallObservation(
                        call_id="failed-call-1",
                        role="domain_analyst",
                        task_name="domain_analysis",
                        request_sha256=sha256_text(
                            f"failed-request-{record['sample_id']}"
                        ),
                        response_sha256=None,
                        model=config["requested_model"],
                        usage=None,
                        latency_ms=120_000.0,
                        finish_reason=None,
                        response_id=None,
                        status="failed",
                        error="Deadline expired before operation could complete.",
                        error_kind="timeout",
                        status_code=504,
                        provider_status="DEADLINE_EXCEEDED",
                    ),
                ),
                runtime_audit={"fake": True},
                error="Deadline expired before operation could complete.",
            )

        with tempfile.TemporaryDirectory() as temporary:
            run_dir = run_crewai_campaign(
                config_path=SMOKE_CONFIG,
                repo_root=REPO_ROOT,
                output_root=Path(temporary) / "runs",
                api_key=FAKE_KEY,
                workflow_executor=executor,
            )
            scoring_dir = score_run(
                run_dir=run_dir,
                labels_path=SMOKE_LABELS,
                output_dir=None,
                repo_root=REPO_ROOT,
            )
            metrics = read_json(scoring_dir / "metrics.json")
            ledger = read_json(run_dir / "budget_ledger.json")
            results = read_jsonl(run_dir / "results.jsonl")
            report = (scoring_dir / "report.md").read_text(encoding="utf-8")
            with (scoring_dir / "metrics.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                csv_metrics = {
                    row["metric"]: row["value"] for row in csv.DictReader(handle)
                }

        self.assertEqual(executor_calls, 1)
        self.assertEqual(
            [result["status"] for result in results],
            ["timeout"] + ["campaign_stopped"] * 4,
        )
        self.assertEqual(metrics["records"]["technical_failures"], 5)
        self.assertEqual(
            metrics["attempts"],
            {
                "outbound": 1,
                "retries": 0,
                "cost_unknown_attempts": 1,
                "semantics": "llm_calls",
                "workflows": 1,
                "planned_workflows": 5,
                "started_workflows": 1,
                "not_attempted": 4,
                "provider_failures": 1,
            },
        )
        self.assertEqual(
            metrics["cost"]["ledger_reserved_or_observed_usd"],
            ledger["reserved_or_observed_cost_usd"],
        )
        self.assertEqual(csv_metrics["started_workflows"], "1")
        self.assertEqual(csv_metrics["not_attempted"], "4")
        self.assertEqual(csv_metrics["provider_failures"], "1")
        self.assertIn("rozpoczęte workflows: 1", report)
        self.assertIn("nieuruchomione: 4", report)
        self.assertIn("błędy providera: 1", report)
        self.assertIn("błędy techniczne: 5", report)
        self.assertIn("konserwatywnie zarezerwowany w ledgerze", report)


if __name__ == "__main__":
    unittest.main()
