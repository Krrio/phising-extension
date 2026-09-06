from __future__ import annotations

import csv
import importlib.util
import json
import py_compile
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"
sys.path.insert(0, str(BENCHMARKS_DIR))

from dashboard.analytics import (  # noqa: E402
    case_outcome,
    direct_crewai_comparisons,
    recompute_binary_metrics,
)
from dashboard.data_loader import (  # noqa: E402
    REQUIRED_CASE_COLUMNS,
    REQUIRED_PAIRWISE_COLUMNS,
    REQUIRED_RUN_COLUMNS,
    DashboardDataError,
    load_comparison_bundle,
    read_verified_artifact,
    sha256_file,
)


CHART_DEPS_AVAILABLE = all(
    importlib.util.find_spec(package) is not None for package in ("pandas", "plotly")
)
if CHART_DEPS_AVAILABLE:
    import pandas as pd  # noqa: E402

    from dashboard.charts import cost_quality_scatter, metric_bar  # noqa: E402


def _blank_row(columns: frozenset[str]) -> dict[str, str]:
    return {column: "" for column in sorted(columns)}


class DashboardFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.runs = [
            self._run("model_direct", "direct", "direct-api", 500, 0, 1),
            self._run("model_crewai", "crew", "crew-api", 1000, 1, 0),
        ]
        self.cases = [
            self._case("model_direct", "sample-mal", "case_001", "tp", False),
            self._case("model_direct", "sample-ben", "case_002", "tn", False),
            self._case("model_crewai", "sample-mal", "case_001", "tp", False),
            self._case("model_crewai", "sample-ben", "case_002", "fp", False),
        ]
        self.pairwise = [self._pair()]
        self.report = "# Test report\n\nDESCRIPTIVE_ONLY / INCONCLUSIVE\n"
        self.metadata: dict = {}
        self.write()

    @staticmethod
    def _run(
        variant_id: str,
        architecture: str,
        request_profile: str,
        max_tokens: int,
        fp: int,
        tn: int,
    ) -> dict[str, str]:
        row = _blank_row(REQUIRED_RUN_COLUMNS)
        row.update(
            {
                "variant_id": variant_id,
                "run_id": f"run-{variant_id}",
                "campaign_id": f"campaign-{variant_id}",
                "provider": "google",
                "adapter": (
                    "gemini_generate_content"
                    if architecture == "direct"
                    else "crewai_sequential_offline"
                ),
                "architecture": architecture,
                "requested_model": "gemini-3.7-flash",
                "request_profile": request_profile,
                "max_output_tokens": str(max_tokens),
                "sample_count": "2",
                "malicious_count": "1",
                "benign_count": "1",
                "success_count": "2",
                "tp": "1",
                "fp": str(fp),
                "tn": str(tn),
                "fn": "0",
                "precision": "0.5" if fp else "1.0",
                "recall": "1.0",
                "f1": "0.666667" if fp else "1.0",
                "false_positive_rate": "1.0" if fp else "0.0",
                "specificity": "0.0" if fp else "1.0",
                "schema_valid_count": "2",
                "technical_failures": "0",
                "critical_security_events": "0",
                "golden_action_match_rate": "1.0",
                "outbound_calls": "2" if architecture == "direct" else "6",
                "retries": "0",
                "cost_unknown_attempts": "0",
                "input_tokens": "100",
                "output_tokens": "20",
                "reasoning_tokens": "0",
                "total_tokens": "120",
                "observed_cost_usd": "0.02" if architecture == "direct" else "0.08",
                "ledger_reserved_or_observed_cost_usd": "0.10",
                "observed_cost_usd_per_message": (
                    "0.01" if architecture == "direct" else "0.04"
                ),
                "latency_median_ms": "1000" if architecture == "direct" else "3000",
                "latency_iqr_ms": "100",
                "campaign_status": "PILOT_HOLD",
                "comparative_conclusion": "INCONCLUSIVE",
                "git_commit": "a" * 40,
                "git_dirty": "false",
            }
        )
        return row

    @staticmethod
    def _case(
        variant_id: str,
        sample_id: str,
        case_name: str,
        confusion_cell: str,
        technical_failure: bool,
    ) -> dict[str, str]:
        is_crewai = variant_id.endswith("_crewai")
        row = _blank_row(REQUIRED_CASE_COLUMNS)
        row.update(
            {
                "variant_id": variant_id,
                "run_id": f"run-{variant_id}",
                "sample_id": sample_id,
                "case_name": case_name,
                "class_label": "malicious" if confusion_cell == "tp" else "benign",
                "scenario": case_name,
                "difficulty": "typical",
                "security_probe": "false",
                "acceptable_actions_json": '["allow"]',
                "status": "success",
                "verdict": "phishing" if confusion_cell in {"tp", "fp"} else "safe",
                "predicted_action": "warn" if confusion_cell in {"tp", "fp"} else "allow",
                "confusion_cell": confusion_cell,
                "binary_correct": "true" if confusion_cell in {"tp", "tn"} else "false",
                "golden_action_match": "true",
                "technical_failure": str(technical_failure).lower(),
                "action_mapping_valid": "true",
                "security_probe_allow": "false",
                "latency_ms": "1000",
                "outbound_attempts": "3" if is_crewai else "1",
                "observed_cost_usd": "0.04" if is_crewai else "0.01",
                "cost_known": "true",
            }
        )
        return row

    @staticmethod
    def _pair() -> dict[str, str]:
        row = _blank_row(REQUIRED_PAIRWISE_COLUMNS)
        row.update(
            {
                "left_variant": "model_crewai",
                "right_variant": "model_direct",
                "sample_count": "2",
                "exact_action_agreement_count": "1",
                "exact_action_agreement_rate": "0.5",
                "binary_prediction_agreement_rate": "0.5",
                "both_correct": "1",
                "left_only_correct": "0",
                "right_only_correct": "1",
                "both_wrong": "0",
                "delta_precision_right_minus_left": "0.5",
                "delta_recall_right_minus_left": "0",
                "delta_f1_right_minus_left": "0.333333",
                "delta_fpr_right_minus_left": "-1",
                "cost_ratio_right_over_left": "0.25",
                "median_latency_ratio_right_over_left": "0.333333",
                "provider_calls_ratio_right_over_left": "0.333333",
            }
        )
        return row

    @staticmethod
    def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def write(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._write_csv(self.root / "runs.csv", self.runs)
        self._write_csv(self.root / "cases.csv", self.cases)
        self._write_csv(self.root / "pairwise.csv", self.pairwise)
        (self.root / "report.md").write_text(self.report, encoding="utf-8")
        self.metadata = {
            "record_type": "BenchmarkComparison",
            "schema_version": "1.0",
            "comparison_status": "DESCRIPTIVE_ONLY",
            "comparative_conclusion": "INCONCLUSIVE",
            "eligible_for_ranking": False,
            "runs": self.runs,
            "cases": self.cases,
            "pairwise": self.pairwise,
            "source_artifacts": {
                row["variant_id"]: {"run_id": row["run_id"]} for row in self.runs
            },
            "export_artifacts": {
                "runs_csv_sha256": sha256_file(self.root / "runs.csv"),
                "cases_csv_sha256": sha256_file(self.root / "cases.csv"),
                "pairwise_csv_sha256": sha256_file(self.root / "pairwise.csv"),
                "report_md_sha256": sha256_file(self.root / "report.md"),
            },
        }
        (self.root / "comparison.json").write_text(
            json.dumps(self.metadata, sort_keys=True), encoding="utf-8"
        )


class DashboardLoaderTests(unittest.TestCase):
    def test_valid_bundle_is_loaded_and_verified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = DashboardFixture(Path(temporary) / "comparison")
            bundle = load_comparison_bundle(fixture.root)

            self.assertEqual(bundle.variant_ids, ("model_direct", "model_crewai"))
            self.assertEqual(len(bundle.cases), 4)
            self.assertEqual(len(bundle.pairwise), 1)
            self.assertTrue(bundle.all_artifacts_verified)
            self.assertEqual(len(bundle.verifications), 4)

    def test_modified_csv_is_rejected_by_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = DashboardFixture(Path(temporary) / "comparison")
            with (fixture.root / "runs.csv").open("a", encoding="utf-8") as handle:
                handle.write("tampered\n")

            with self.assertRaisesRegex(DashboardDataError, "Niezgodny SHA-256"):
                load_comparison_bundle(fixture.root)

    def test_download_is_blocked_if_file_changes_after_loading(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = DashboardFixture(Path(temporary) / "comparison")
            bundle = load_comparison_bundle(fixture.root)
            with (fixture.root / "runs.csv").open("a", encoding="utf-8") as handle:
                handle.write("tampered\n")

            with self.assertRaisesRegex(DashboardDataError, "pobieranie zablokowane"):
                read_verified_artifact(bundle, "runs.csv")

    def test_missing_required_column_is_rejected_after_valid_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = DashboardFixture(Path(temporary) / "comparison")
            for row in fixture.runs:
                row.pop("f1")
            fixture.write()

            with self.assertRaisesRegex(DashboardDataError, "Brak wymaganych kolumn"):
                load_comparison_bundle(fixture.root)

    def test_raw_message_column_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = DashboardFixture(Path(temporary) / "comparison")
            for row in fixture.cases:
                row["subject"] = "must not reach dashboard"
            fixture.write()

            with self.assertRaisesRegex(DashboardDataError, "niedozwolone surowe pola"):
                load_comparison_bundle(fixture.root)

    def test_case_count_must_match_run_sample_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = DashboardFixture(Path(temporary) / "comparison")
            fixture.cases.pop()
            fixture.write()

            with self.assertRaisesRegex(
                DashboardDataError, "sample_count=2|inny zestaw sample_id"
            ):
                load_comparison_bundle(fixture.root)

    def test_run_metric_must_match_case_confusion_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = DashboardFixture(Path(temporary) / "comparison")
            fixture.runs[0]["f1"] = "0.25"
            fixture.write()

            with self.assertRaisesRegex(DashboardDataError, "f1=.*przeliczeniem"):
                load_comparison_bundle(fixture.root)

    def test_case_metadata_must_be_frozen_across_variants(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = DashboardFixture(Path(temporary) / "comparison")
            fixture.cases[-1]["difficulty"] = "adversarial"
            fixture.write()

            with self.assertRaisesRegex(DashboardDataError, "inne metadane"):
                load_comparison_bundle(fixture.root)

    def test_unknown_case_column_is_rejected_case_independently(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = DashboardFixture(Path(temporary) / "comparison")
            for row in fixture.cases:
                row["Body"] = "must not reach dashboard"
            fixture.write()

            with self.assertRaisesRegex(DashboardDataError, "spoza schematu"):
                load_comparison_bundle(fixture.root)

    def test_symlinked_artifact_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = DashboardFixture(Path(temporary) / "comparison")
            report = fixture.root / "report.md"
            external = Path(temporary) / "external.md"
            external.write_text(fixture.report, encoding="utf-8")
            report.unlink()
            report.symlink_to(external)

            with self.assertRaisesRegex(DashboardDataError, "symlinkiem"):
                load_comparison_bundle(fixture.root)

    def test_real_full_export_when_available(self) -> None:
        directory = (
            REPO_ROOT
            / "benchmark-runs"
            / "comparisons"
            / "FULL_EIGHT_ARM_PILOT_030_001"
        )
        if not directory.exists():
            self.skipTest("local ignored benchmark export is not available")

        bundle = load_comparison_bundle(directory)

        self.assertEqual(len(bundle.runs), 8)
        self.assertEqual(len(bundle.cases), 240)
        self.assertEqual(len(bundle.pairwise), 28)
        self.assertTrue(bundle.all_artifacts_verified)


class DashboardAnalyticsTests(unittest.TestCase):
    def test_metrics_are_recomputed_from_confusion_cells(self) -> None:
        metrics = recompute_binary_metrics(
            [
                {"confusion_cell": "tp"},
                {"confusion_cell": "tp"},
                {"confusion_cell": "fp"},
                {"confusion_cell": "tn"},
                {"confusion_cell": "fn"},
            ]
        )

        self.assertEqual(
            {key: metrics[key] for key in ("tp", "fp", "tn", "fn")},
            {"tp": 2, "fp": 1, "tn": 1, "fn": 1},
        )
        self.assertAlmostEqual(metrics["precision"] or 0, 2 / 3)
        self.assertAlmostEqual(metrics["recall"] or 0, 2 / 3)
        self.assertAlmostEqual(metrics["f1"] or 0, 2 / 3)
        self.assertAlmostEqual(metrics["false_positive_rate"] or 0, 0.5)

    def test_direct_crewai_rows_are_oriented_independently_of_pair_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = DashboardFixture(Path(temporary) / "comparison")
            rows = direct_crewai_comparisons(fixture.runs, fixture.pairwise)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["direct_variant"], "model_direct")
        self.assertEqual(row["crewai_variant"], "model_crewai")
        self.assertAlmostEqual(row["delta_f1"], -0.333333)
        self.assertAlmostEqual(row["delta_fpr"], 1.0)
        self.assertAlmostEqual(row["cost_ratio"], 4.0)
        self.assertAlmostEqual(row["latency_ratio"], 3.0)
        self.assertEqual(row["exact_action_agreement_rate"], 0.5)
        self.assertEqual(row["scope"], "token_cap_adjusted_system_bundle_delta")

    def test_ambiguous_model_architecture_pair_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = DashboardFixture(Path(temporary) / "comparison")
            duplicate = dict(fixture.runs[0])
            duplicate["variant_id"] = "model_direct_replication"

            with self.assertRaisesRegex(ValueError, "Niejednoznaczna para"):
                direct_crewai_comparisons(
                    [*fixture.runs, duplicate], fixture.pairwise
                )

    def test_technical_outcome_has_priority_over_confusion_cell(self) -> None:
        self.assertEqual(
            case_outcome({"technical_failure": "true", "confusion_cell": "tn"}),
            "TECH",
        )

    def test_dashboard_sources_compile_without_optional_imports(self) -> None:
        for name in (
            "app.py",
            "charts.py",
            "data_loader.py",
            "analytics.py",
            "frames.py",
            "export_static.py",
        ):
            with self.subTest(name=name):
                py_compile.compile(
                    str(BENCHMARKS_DIR / "dashboard" / name), doraise=True
                )


@unittest.skipUnless(
    CHART_DEPS_AVAILABLE,
    "optional dashboard chart dependencies are not installed",
)
class DashboardChartLayoutTests(unittest.TestCase):
    @staticmethod
    def _runs_frame():
        return pd.DataFrame(
            [
                {
                    "variant_id": "direct",
                    "variant_label": "Model · Direct",
                    "model_label": "Model",
                    "provider": "openai",
                    "architecture_label": "Direct",
                    "campaign_status": "PILOT_HOLD",
                    "success_count": 29,
                    "technical_failures": 1,
                    "f1": 1.0,
                    "false_positive_rate": 0.2,
                    "observed_cost_usd_per_message": 0.001,
                    "latency_median_ms": 1000.0,
                },
                {
                    "variant_id": "crewai",
                    "variant_label": "Model · CrewAI",
                    "model_label": "Model",
                    "provider": "openai",
                    "architecture_label": "CrewAI",
                    "campaign_status": "PILOT_HOLD",
                    "success_count": 30,
                    "technical_failures": 0,
                    "f1": 0.9,
                    "false_positive_rate": 0.1,
                    "observed_cost_usd_per_message": 0.003,
                    "latency_median_ms": 3000.0,
                },
            ]
        )

    def test_metric_bar_uses_dynamic_scale_and_fixed_failure_rail(self) -> None:
        figure = metric_bar(
            self._runs_frame(),
            "false_positive_rate",
            "FPR",
            percent=True,
        )

        self.assertAlmostEqual(figure.layout.xaxis.range[1], 0.22)
        self.assertEqual(figure.layout.legend.orientation, "h")
        self.assertIsNone(figure.layout.yaxis.title.text)
        self.assertEqual(len(figure.layout.annotations), 1)
        self.assertEqual(figure.layout.annotations[0].xref, "paper")
        self.assertGreater(figure.layout.annotations[0].x, 1)

    def test_scatter_keeps_semantic_axis_and_non_horizontal_legend(self) -> None:
        figure = cost_quality_scatter(self._runs_frame())

        self.assertEqual(figure.layout.yaxis.title.text, "F1")
        self.assertTrue(figure.layout.yaxis.showgrid)
        self.assertNotEqual(figure.layout.legend.orientation, "h")


if __name__ == "__main__":
    unittest.main()
