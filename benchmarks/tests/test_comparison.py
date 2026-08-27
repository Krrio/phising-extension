from __future__ import annotations

import csv
import json
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"
sys.path.insert(0, str(BENCHMARKS_DIR))

from phishing_bench.comparison import (  # noqa: E402
    _csv_payload,
    _safe_csv_cell,
    compare_runs,
    parse_named_run,
)
from phishing_bench.contracts import ContractError  # noqa: E402
from phishing_bench.io_utils import (  # noqa: E402
    atomic_write_json,
    read_json,
    read_jsonl,
    sha256_file,
    write_jsonl,
)
from phishing_bench.openai_direct import ProviderResponse  # noqa: E402
from phishing_bench.runner import run_campaign  # noqa: E402
from phishing_bench.scoring import score_run  # noqa: E402


CONFIG_PATH = (
    BENCHMARKS_DIR
    / "campaigns"
    / "BUDGET_30H_OPENAI_PILOT_030_001"
    / "runtime_config.json"
)
LABELS_PATH = (
    BENCHMARKS_DIR
    / "secure_scoring"
    / "openai_pilot_030_v1"
    / "labels.jsonl"
)
FAKE_KEY = "sk-test_COMPARISON_FAKE_SECRET_123456"


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
        "reasoning": "Syntetyczne uzasadnienie testu porównania.",
        "categories": categories,
        "policyAssessment": None,
    }


class FakeComparisonTransport:
    def __init__(self, plans: list[dict[str, Any]]) -> None:
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
        content = json.dumps(self.plans.pop(0), ensure_ascii=False)
        return ProviderResponse(
            response_id=f"chatcmpl-comparison-{self.calls}",
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
            safe_headers={"x-request-id": f"req-comparison-{self.calls}"},
            elapsed_ms=float(self.calls),
            raw_response_sha256_material=content.encode("utf-8"),
        )


def _paired_plans(
    labels: list[dict[str, Any]],
    *,
    malicious_hide: int,
    benign_positive: int,
) -> list[dict[str, Any]]:
    malicious_seen = 0
    benign_seen = 0
    plans: list[dict[str, Any]] = []
    for label in labels:
        if label["class_label"] == "malicious":
            verdict = "phishing" if malicious_seen < malicious_hide else "suspicious"
            malicious_seen += 1
        else:
            verdict = "suspicious" if benign_seen < benign_positive else "safe"
            benign_seen += 1
        plans.append(_model_output(verdict))
    return plans


class ComparisonExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(
            prefix=".comparison-test-", dir=BENCHMARKS_DIR
        )
        cls.work_dir = Path(cls.temporary.name)
        cls.labels = read_jsonl(LABELS_PATH)

        # These two deterministic plans reproduce the paired shape observed in
        # the real Direct vs CrewAI pilot without making an outbound request:
        # left TP/FP/TN/FN=15/3/12/0, right=15/7/8/0. Two malicious cases move
        # warn->hide and four benign cases move allow->warn.
        left_transport = FakeComparisonTransport(
            _paired_plans(cls.labels, malicious_hide=8, benign_positive=3)
        )
        right_transport = FakeComparisonTransport(
            _paired_plans(cls.labels, malicious_hide=10, benign_positive=7)
        )
        cls.left_run = run_campaign(
            config_path=CONFIG_PATH,
            repo_root=REPO_ROOT,
            output_root=cls.work_dir / "left-runs",
            api_key=FAKE_KEY,
            transport=left_transport,
            sleep=lambda _: None,
        )
        cls.right_run = run_campaign(
            config_path=CONFIG_PATH,
            repo_root=REPO_ROOT,
            output_root=cls.work_dir / "right-runs",
            api_key=FAKE_KEY,
            transport=right_transport,
            sleep=lambda _: None,
        )
        cls.left_score = score_run(
            run_dir=cls.left_run,
            labels_path=LABELS_PATH,
            output_dir=None,
            repo_root=REPO_ROOT,
        )
        cls.right_score = score_run(
            run_dir=cls.right_run,
            labels_path=LABELS_PATH,
            output_dir=None,
            repo_root=REPO_ROOT,
        )
        if left_transport.calls != 30 or right_transport.calls != 30:
            raise AssertionError("comparison fixtures must execute exactly 30 fake calls")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def setUp(self) -> None:
        self.case_temporary = tempfile.TemporaryDirectory(
            prefix="case-", dir=self.work_dir
        )
        self.case_dir = Path(self.case_temporary.name)

    def tearDown(self) -> None:
        self.case_temporary.cleanup()

    def _compare(
        self,
        right_run: Path | None = None,
        *,
        output_name: str = "comparison",
    ) -> Path:
        return compare_runs(
            named_run_dirs=[
                ("direct", self.left_run),
                ("candidate", right_run or self.right_run),
            ],
            labels_path=LABELS_PATH,
            output_dir=self.case_dir / output_name,
            repo_root=REPO_ROOT,
        )

    def _copy_run(self, source: Path, name: str) -> Path:
        destination = self.case_dir / name
        shutil.copytree(source, destination)
        return destination

    @staticmethod
    def _source_hashes(run_dir: Path) -> dict[str, str]:
        return {
            str(path.relative_to(run_dir)): sha256_file(path)
            for path in sorted(run_dir.rglob("*"))
            if path.is_file()
        }

    def test_happy_path_exports_private_tidy_artifacts_without_touching_sources(self) -> None:
        before = {
            "left": self._source_hashes(self.left_run),
            "right": self._source_hashes(self.right_run),
        }
        output_dir = self._compare()

        self.assertEqual(
            {path.name for path in output_dir.iterdir()},
            {"runs.csv", "cases.csv", "pairwise.csv", "comparison.json", "report.md"},
        )
        self.assertEqual(stat.S_IMODE(output_dir.stat().st_mode), 0o700)
        for path in output_dir.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

        with (output_dir / "runs.csv").open(newline="", encoding="utf-8") as handle:
            run_rows = list(csv.DictReader(handle))
        with (output_dir / "cases.csv").open(newline="", encoding="utf-8") as handle:
            case_rows = list(csv.DictReader(handle))
        with (output_dir / "pairwise.csv").open(newline="", encoding="utf-8") as handle:
            pair_rows = list(csv.DictReader(handle))
        self.assertEqual(len(run_rows), 2)
        self.assertEqual(len(case_rows), 60)
        self.assertEqual(len(pair_rows), 1)
        self.assertEqual({row["variant_id"] for row in case_rows}, {"direct", "candidate"})

        comparison = read_json(output_dir / "comparison.json")
        self.assertEqual(comparison["record_type"], "BenchmarkComparison")
        self.assertEqual(comparison["comparative_conclusion"], "INCONCLUSIVE")
        self.assertEqual(comparison["compatibility"]["baseline_variant"], "direct")
        self.assertTrue(comparison["compatibility"]["paired"])
        self.assertEqual(len(comparison["runs"]), 2)
        self.assertEqual(len(comparison["cases"]), 60)
        self.assertEqual(len(comparison["pairwise"]), 1)
        self.assertEqual(comparison["trusted_labels"]["sha256"], sha256_file(LABELS_PATH))
        all_export_text = "".join(
            path.read_text(encoding="utf-8") for path in output_dir.iterdir()
        )
        self.assertNotIn(FAKE_KEY, all_export_text)
        self.assertNotIn("Syntetyczne uzasadnienie testu porównania.", all_export_text)

        self.assertEqual(before["left"], self._source_hashes(self.left_run))
        self.assertEqual(before["right"], self._source_hashes(self.right_run))

    def test_pairwise_math_matches_known_direct_vs_crew_shape(self) -> None:
        comparison = read_json(self._compare() / "comparison.json")
        runs = {row["variant_id"]: row for row in comparison["runs"]}
        self.assertEqual(
            {key: runs["direct"][key] for key in ("tp", "fp", "tn", "fn")},
            {"tp": 15, "fp": 3, "tn": 12, "fn": 0},
        )
        self.assertEqual(
            {key: runs["candidate"][key] for key in ("tp", "fp", "tn", "fn")},
            {"tp": 15, "fp": 7, "tn": 8, "fn": 0},
        )

        pair = comparison["pairwise"][0]
        self.assertEqual(pair["left_variant"], "direct")
        self.assertEqual(pair["right_variant"], "candidate")
        self.assertEqual(pair["sample_count"], 30)
        self.assertEqual(pair["both_correct"], 23)
        self.assertEqual(pair["left_only_correct"], 4)
        self.assertEqual(pair["right_only_correct"], 0)
        self.assertEqual(pair["both_wrong"], 3)
        self.assertEqual(pair["discordant_total"], 4)
        self.assertEqual(pair["mcnemar_exact_p_descriptive"], 0.125)
        self.assertEqual(pair["binary_prediction_agreement_count"], 26)
        self.assertEqual(pair["binary_prediction_agreement_rate"], 0.866667)
        self.assertEqual(pair["exact_action_agreement_count"], 24)
        self.assertEqual(pair["exact_action_agreement_rate"], 0.8)
        self.assertEqual(pair["delta_f1_right_minus_left"], -0.09828)
        self.assertEqual(pair["delta_fpr_right_minus_left"], 0.266667)

    def test_metrics_and_scored_result_tampering_are_rejected(self) -> None:
        cases: list[tuple[str, Any, str]] = []

        def change_f1(run_dir: Path) -> None:
            path = run_dir / "scoring" / "metrics.json"
            metrics = read_json(path)
            metrics["classification_metrics"]["f1"]["value"] = 0.123456
            atomic_write_json(path, metrics)

        cases.append(("changed-f1", change_f1, "classification metric f1 differs"))

        def remove_precision(run_dir: Path) -> None:
            path = run_dir / "scoring" / "metrics.json"
            metrics = read_json(path)
            del metrics["classification_metrics"]["precision"]
            atomic_write_json(path, metrics)

        cases.append(("missing-precision", remove_precision, "precision is missing"))

        def change_action(run_dir: Path) -> None:
            path = run_dir / "scoring" / "scored_results.jsonl"
            records = read_jsonl(path)
            records[0]["predicted_action"] = "warn"
            write_jsonl(path, records)

        cases.append(("changed-action", change_action, "scored prediction does not reconcile"))

        def change_label(run_dir: Path) -> None:
            path = run_dir / "scoring" / "scored_results.jsonl"
            records = read_jsonl(path)
            records[0]["case_name"] = "changed_after_scoring"
            write_jsonl(path, records)

        cases.append(("changed-label", change_label, "scored labels differ"))

        for name, mutate, error in cases:
            with self.subTest(name=name):
                run_dir = self._copy_run(self.right_run, name)
                mutate(run_dir)
                output_dir = self.case_dir / f"out-{name}"
                with self.assertRaisesRegex(ContractError, error):
                    compare_runs(
                        named_run_dirs=[("direct", self.left_run), ("candidate", run_dir)],
                        labels_path=LABELS_PATH,
                        output_dir=output_dir,
                        repo_root=REPO_ROOT,
                    )
                self.assertFalse(output_dir.exists())

    def test_frozen_compatibility_mismatches_are_rejected(self) -> None:
        cases: list[tuple[str, Any, str]] = []

        def change_response_schema(run_dir: Path) -> None:
            path = run_dir / "run_manifest.json"
            manifest = read_json(path)
            manifest["readiness"]["hashes"]["response_schema_sha256"] = "0" * 64
            atomic_write_json(path, manifest)

        cases.append(
            ("response-schema", change_response_schema, "response_schema_sha256")
        )

        def change_dataset_manifest(run_dir: Path) -> None:
            path = run_dir / "run_manifest.json"
            manifest = read_json(path)
            manifest["readiness"]["hashes"]["dataset_manifest_sha256"] = "0" * 64
            atomic_write_json(path, manifest)

        cases.append(
            ("dataset-manifest", change_dataset_manifest, "dataset_manifest_sha256")
        )

        def change_decision_policy(run_dir: Path) -> None:
            path = run_dir / "scoring" / "metrics.json"
            metrics = read_json(path)
            metrics["hashes"]["decision_policy_sha256"] = "0" * 64
            atomic_write_json(path, metrics)

        cases.append(
            ("decision-policy", change_decision_policy, "decision_policy_sha256")
        )

        def change_input_projection(run_dir: Path) -> None:
            results_path = run_dir / "results.jsonl"
            results = read_jsonl(results_path)
            results[0]["hashes"]["input_sha256"] = "0" * 64
            write_jsonl(results_path, results)
            results_hash = sha256_file(results_path)

            manifest_path = run_dir / "run_manifest.json"
            manifest = read_json(manifest_path)
            manifest["artifact_hashes"]["results_jsonl_sha256"] = results_hash
            atomic_write_json(manifest_path, manifest)

            metrics_path = run_dir / "scoring" / "metrics.json"
            metrics = read_json(metrics_path)
            metrics["hashes"]["results_sha256"] = results_hash
            atomic_write_json(metrics_path, metrics)

        cases.append(
            (
                "sample-input",
                change_input_projection,
                "sample_input_hash_projection",
            )
        )

        for name, mutate, mismatch in cases:
            with self.subTest(name=name):
                run_dir = self._copy_run(self.right_run, f"compat-{name}")
                mutate(run_dir)
                with self.assertRaisesRegex(ContractError, mismatch):
                    self._compare(run_dir, output_name=f"out-compat-{name}")

    def test_dataset_and_trusted_label_bundle_mismatches_fail_closed(self) -> None:
        changed_dataset = self._copy_run(self.right_run, "changed-dataset")
        manifest_path = changed_dataset / "run_manifest.json"
        manifest = read_json(manifest_path)
        manifest["readiness"]["hashes"]["dataset_sha256"] = "0" * 64
        atomic_write_json(manifest_path, manifest)
        with self.assertRaisesRegex(ContractError, "does not freeze"):
            self._compare(changed_dataset, output_name="out-dataset")

        bundle_dir = self.case_dir / "changed-bundle"
        shutil.copytree(LABELS_PATH.parent, bundle_dir)
        changed_labels_path = bundle_dir / "labels.jsonl"
        labels = read_jsonl(changed_labels_path)
        labels[0]["case_name"] = "changed_case"
        write_jsonl(changed_labels_path, labels)
        scoring_manifest_path = bundle_dir / "scoring_manifest.json"
        scoring_manifest = read_json(scoring_manifest_path)
        scoring_manifest["labels_sha256"] = sha256_file(changed_labels_path)
        atomic_write_json(scoring_manifest_path, scoring_manifest)
        output_dir = self.case_dir / "out-labels"
        with self.assertRaisesRegex(ContractError, "scored labels differ"):
            compare_runs(
                named_run_dirs=[("direct", self.left_run), ("candidate", self.right_run)],
                labels_path=changed_labels_path,
                output_dir=output_dir,
                repo_root=REPO_ROOT,
            )
        self.assertFalse(output_dir.exists())

    def test_duplicate_names_paths_run_ids_and_overlapping_output_are_rejected(self) -> None:
        with self.assertRaisesRegex(ContractError, "between 2 and 20"):
            compare_runs(
                named_run_dirs=[("direct", self.left_run)],
                labels_path=LABELS_PATH,
                output_dir=self.case_dir / "one-run",
                repo_root=REPO_ROOT,
            )
        with self.assertRaisesRegex(ContractError, "names must be unique"):
            compare_runs(
                named_run_dirs=[("same", self.left_run), ("same", self.right_run)],
                labels_path=LABELS_PATH,
                output_dir=self.case_dir / "duplicate-name",
                repo_root=REPO_ROOT,
            )
        with self.assertRaisesRegex(ContractError, "same run directory"):
            compare_runs(
                named_run_dirs=[("left", self.left_run), ("right", self.left_run)],
                labels_path=LABELS_PATH,
                output_dir=self.case_dir / "duplicate-path",
                repo_root=REPO_ROOT,
            )
        with self.assertRaisesRegex(ContractError, "invalid characters"):
            compare_runs(
                named_run_dirs=[("=formula", self.left_run), ("right", self.right_run)],
                labels_path=LABELS_PATH,
                output_dir=self.case_dir / "invalid-name",
                repo_root=REPO_ROOT,
            )

        copied_run = self._copy_run(self.right_run, "same-run-id")
        with self.assertRaisesRegex(ContractError, "distinct run_id"):
            compare_runs(
                named_run_dirs=[("original", self.right_run), ("copy", copied_run)],
                labels_path=LABELS_PATH,
                output_dir=self.case_dir / "duplicate-run-id",
                repo_root=REPO_ROOT,
            )

        with self.assertRaisesRegex(ContractError, "cannot overlap"):
            compare_runs(
                named_run_dirs=[("left", self.left_run), ("right", self.right_run)],
                labels_path=LABELS_PATH,
                output_dir=self.left_run / "comparison-output",
                repo_root=REPO_ROOT,
            )

    def test_parse_named_run_and_csv_formula_guard(self) -> None:
        variant, path = parse_named_run("Direct_1=./benchmark-runs/example")
        self.assertEqual(variant, "Direct_1")
        self.assertTrue(path.is_absolute())
        for invalid in ("missing-separator", "=./run", "bad name=./run", "@bad=./run"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    parse_named_run(invalid)

        dangerous = (
            "=HYPERLINK(\"https://attacker.invalid\")",
            "+cmd|' /C calc'!A0",
            "-1+1",
            "@SUM(1,1)",
            "\t=1+1",
            "\r@SUM(1,1)",
            " \n=1+1",
        )
        for value in dangerous:
            with self.subTest(value=value):
                self.assertEqual(_safe_csv_cell(value), "'" + value)

        rows = [
            {"name": dangerous[0], "detail": "comma,quote\"and\r\nnewline"},
            {"name": "żółć", "detail": "plain"},
        ]
        payload = _csv_payload(rows)
        parsed = list(csv.DictReader(payload.splitlines(keepends=True)))
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["name"], "'" + dangerous[0])
        self.assertEqual(parsed[0]["detail"], rows[0]["detail"])
        self.assertEqual(parsed[1], rows[1])


if __name__ == "__main__":
    unittest.main()
