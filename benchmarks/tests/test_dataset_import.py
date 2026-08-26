from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"
if str(BENCHMARKS_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARKS_DIR))

from phishing_bench.contracts import validate_dataset  # noqa: E402
from phishing_bench.io_utils import read_jsonl  # noqa: E402


IMPORTER = BENCHMARKS_DIR / "tools" / "import_openai_pilot_pool.ts"
SOURCE = BENCHMARKS_DIR / "datasets" / "openai_pilot_pool_v1" / "source.md"
VITE_NODE = REPO_ROOT / "node_modules" / ".bin" / "vite-node"

MALICIOUS_CASE_IDS = [
    "case_001",
    "case_003",
    "case_007",
    "case_009",
    "case_011",
    "case_013",
    "case_015",
    "case_017",
    "case_019",
    "case_023",
    "case_025",
    "case_027",
    "case_029",
    "case_033",
    "case_035",
]
BENIGN_CASE_IDS = [
    "case_002",
    "case_004",
    "case_006",
    "case_012",
    "case_016",
    "case_020",
    "case_022",
    "case_026",
    "case_028",
    "case_030",
    "case_032",
    "case_034",
    "case_036",
    "case_037",
    "case_038",
]
ORDERED_CASE_IDS = sorted(MALICIOUS_CASE_IDS + BENIGN_CASE_IDS)
ALLOW_OR_WARN_CASE_IDS = {
    "case_004",
    "case_020",
    "case_022",
    "case_030",
    "case_032",
    "case_037",
    "case_038",
}
GENERATED_FILES = (
    Path("fixtures/openai_pilot_030_v1/runner_input.jsonl"),
    Path("fixtures/openai_pilot_030_v1/dataset_manifest.json"),
    Path("secure_scoring/openai_pilot_030_v1/labels.jsonl"),
    Path("secure_scoring/openai_pilot_030_v1/metadata.jsonl"),
    Path("secure_scoring/openai_pilot_030_v1/selection_manifest.json"),
    Path("secure_scoring/openai_pilot_030_v1/provenance_manifest.json"),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class DatasetImportTest(unittest.TestCase):
    maxDiff = None

    def run_import(
        self,
        output_root: Path,
        *,
        source: Path = SOURCE,
        check: bool = False,
        expect_success: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            str(VITE_NODE),
            str(IMPORTER),
            "--source",
            str(source),
            "--output-root",
            str(output_root),
        ]
        if check:
            command.append("--check")
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        if expect_success and completed.returncode != 0:
            self.fail(f"import failed: stdout={completed.stdout!r} stderr={completed.stderr!r}")
        if not expect_success and completed.returncode == 0:
            self.fail("malformed source unexpectedly imported successfully")
        return completed

    def test_canonical_source_declares_39_and_marks_annotations_non_runtime(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        self.assertTrue(source.startswith("# Zestaw ewaluacyjny — phishing detection (39 przypadków)\n"))
        self.assertIn("Wersja: `EVAL_OPENAI_PILOT_POOL_039_V1`", source)
        self.assertIn("SIGNALS_MODE: `product_derived_v1`", source)
        self.assertEqual(source.count("\n### case_"), 39)
        self.assertEqual(source.count("\nANNOTATOR_SIGNALS:\n"), 39)
        self.assertNotIn("\nSIGNALS:\n", source)

    def test_import_is_deterministic_and_matches_runner_and_label_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first"
            second = root / "second"
            self.run_import(first)
            self.run_import(second)

            for relative_path in GENERATED_FILES:
                self.assertEqual(
                    (first / relative_path).read_bytes(),
                    (second / relative_path).read_bytes(),
                    relative_path,
                )

            runner_path = first / GENERATED_FILES[0]
            runner_records = read_jsonl(runner_path)
            validate_dataset(runner_records)
            self.assertEqual(len(runner_records), 30)
            self.assertEqual(len({record["sample_id"] for record in runner_records}), 30)

            labels = load_jsonl(first / "secure_scoring/openai_pilot_030_v1/labels.jsonl")
            metadata = load_jsonl(first / "secure_scoring/openai_pilot_030_v1/metadata.jsonl")
            self.assertEqual([label["case_name"] for label in labels], ORDERED_CASE_IDS)
            self.assertEqual([record["case_id"] for record in metadata], ORDERED_CASE_IDS)
            self.assertEqual(
                Counter(label["class_label"] for label in labels),
                Counter({"malicious": 15, "benign": 15}),
            )
            self.assertEqual(len({label["analysis_cluster_id"] for label in labels}), 30)
            expected_label_keys = {
                "sample_id",
                "case_name",
                "class_label",
                "acceptable_actions",
                "security_probe",
                "scenario",
                "difficulty",
                "language",
                "label_confidence",
                "analysis_cluster_id",
            }
            self.assertTrue(all(set(label) == expected_label_keys for label in labels))
            for label in labels:
                case_id = str(label["case_name"])
                if label["class_label"] == "malicious":
                    self.assertEqual(label["acceptable_actions"], ["warn", "hide"])
                elif case_id in ALLOW_OR_WARN_CASE_IDS:
                    self.assertEqual(label["acceptable_actions"], ["allow", "warn"])
                else:
                    self.assertEqual(label["acceptable_actions"], ["allow"])

            self.assertEqual(runner_records[0]["sample_id"], "d0967168-9f0c-54a8-8cbc-507dedf82389")
            self.assertEqual(
                [record["sample_id"] for record in runner_records],
                [label["sample_id"] for label in labels],
            )

            public_manifest_path = first / "fixtures/openai_pilot_030_v1/dataset_manifest.json"
            public_manifest = json.loads(public_manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(
                set(public_manifest),
                {
                    "schema_version",
                    "dataset_id",
                    "sample_count",
                    "source_pool_count",
                    "source_type",
                    "data_class",
                    "signals_mode",
                    "renderer_version",
                    "source_pool_sha256",
                    "selection_manifest_sha256",
                    "generator_sha256",
                },
            )
            self.assertEqual(public_manifest["schema_version"], "1.0")
            self.assertEqual(public_manifest["dataset_id"], "OPENAI_PILOT_030_V1")
            self.assertEqual(public_manifest["sample_count"], 30)
            self.assertEqual(public_manifest["source_pool_count"], 39)
            self.assertEqual(public_manifest["source_type"], "synthetic")
            self.assertEqual(public_manifest["data_class"], "synthetic_reserved_domains_only")
            self.assertEqual(public_manifest["signals_mode"], "product_derived_v1")
            self.assertEqual(public_manifest["renderer_version"], "visible_text_v1")
            self.assertEqual(public_manifest["source_pool_sha256"], sha256(SOURCE))
            self.assertEqual(public_manifest["generator_sha256"], sha256(IMPORTER))
            selection_path = first / "secure_scoring/openai_pilot_030_v1/selection_manifest.json"
            self.assertEqual(public_manifest["selection_manifest_sha256"], sha256(selection_path))
            serialized_manifest = json.dumps(public_manifest, sort_keys=True).casefold()
            for forbidden in ("class_count", "case_id", "malicious", "benign", "label"):
                self.assertNotIn(forbidden, serialized_manifest)

            selection = json.loads(selection_path.read_text(encoding="utf-8"))
            self.assertEqual(selection["malicious_case_ids"], MALICIOUS_CASE_IDS)
            self.assertEqual(selection["benign_case_ids"], BENIGN_CASE_IDS)
            self.assertEqual(selection["ordered_case_ids"], ORDERED_CASE_IDS)

            provenance = json.loads(
                (first / "secure_scoring/openai_pilot_030_v1/provenance_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(provenance["canonical_source_sha256"], sha256(SOURCE))
            self.assertEqual(provenance["importer_sha256"], sha256(IMPORTER))
            self.assertEqual(provenance["outputs_sha256"]["runner_input_jsonl"], sha256(runner_path))

    def test_renderer_exposes_link_text_but_not_hidden_href(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.run_import(root)
            runner = load_jsonl(root / "fixtures/openai_pilot_030_v1/runner_input.jsonl")
            metadata = load_jsonl(root / "secure_scoring/openai_pilot_030_v1/metadata.jsonl")
            sample_by_case = {str(record["case_id"]): str(record["sample_id"]) for record in metadata}
            runner_by_id = {str(record["sample_id"]): record for record in runner}

            tracking = runner_by_id[sample_by_case["case_037"]]["untrusted_analysis"]
            self.assertIsInstance(tracking, dict)
            tracking_content = tracking["content"]
            tracking_signals = tracking["signals"]
            self.assertIn("Link: produkt.test/blog", tracking_content)
            self.assertNotIn("https://klik.mailing-serwis.invalid/r/podsumowanie", tracking_content)
            self.assertEqual(
                tracking_signals["linkMismatches"],
                [
                    {
                        "text": "produkt.test/blog",
                        "href": "https://klik.mailing-serwis.invalid/r/podsumowanie",
                    }
                ],
            )

            matching = runner_by_id[sample_by_case["case_006"]]["untrusted_analysis"]
            self.assertIn("Link: sklep.test/zamowienia", matching["content"])
            self.assertNotIn("https://sklep.test/zamowienia", matching["content"])
            self.assertEqual(matching["signals"]["linkMismatches"], [])

            first_case = runner_by_id[sample_by_case["case_001"]]["untrusted_analysis"]
            self.assertEqual(first_case["signals"]["suspiciousPhrases"], [])
            first_metadata = next(record for record in metadata if record["case_id"] == "case_001")
            self.assertIn("zaloguj się natychmiast", first_metadata["annotator_signals_raw"])
            self.assertIs(first_metadata["annotator_signals_used_for_runner"], False)

    def test_annotator_signal_changes_do_not_change_runner_or_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            modified_source = root / "source.md"
            source_text = SOURCE.read_text(encoding="utf-8")
            modified = source_text.replace(
                '"zaloguj się natychmiast"',
                '"ręczna notatka zmieniona"',
                1,
            )
            self.assertNotEqual(modified, source_text)
            modified_source.write_text(modified, encoding="utf-8")
            original_output = root / "original"
            modified_output = root / "modified"
            self.run_import(original_output)
            self.run_import(modified_output, source=modified_source)
            self.assertEqual(
                (original_output / GENERATED_FILES[0]).read_bytes(),
                (modified_output / GENERATED_FILES[0]).read_bytes(),
            )
            self.assertEqual(
                (original_output / "secure_scoring/openai_pilot_030_v1/labels.jsonl").read_bytes(),
                (modified_output / "secure_scoring/openai_pilot_030_v1/labels.jsonl").read_bytes(),
            )
            self.assertNotEqual(
                (original_output / "secure_scoring/openai_pilot_030_v1/metadata.jsonl").read_bytes(),
                (modified_output / "secure_scoring/openai_pilot_030_v1/metadata.jsonl").read_bytes(),
            )

    def test_importer_fails_fast_on_contract_drift_and_check_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "output"
            self.run_import(output)
            checked = self.run_import(output, check=True)
            self.assertIn("CHECK_OK", checked.stdout)
            runner_path = output / GENERATED_FILES[0]
            runner_path.write_text(runner_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            drift = self.run_import(output, check=True, expect_success=False)
            self.assertIn("generated artifact drift", drift.stderr)

            for name, replacement in (
                ("wrong_version", ("EVAL_OPENAI_PILOT_POOL_039_V1", "EVAL_WRONG")),
                ("wrong_mode", ("product_derived_v1", "source_frozen_v1")),
                ("missing_field", ("LABEL_CONFIDENCE: high\n", "")),
            ):
                with self.subTest(name=name):
                    malformed = root / f"{name}.md"
                    shutil.copyfile(SOURCE, malformed)
                    before, after = replacement
                    source_text = malformed.read_text(encoding="utf-8")
                    self.assertIn(before, source_text)
                    malformed.write_text(source_text.replace(before, after, 1), encoding="utf-8")
                    failed = self.run_import(root / f"out-{name}", source=malformed, expect_success=False)
                    self.assertIn("IMPORT_ERROR", failed.stderr)


if __name__ == "__main__":
    unittest.main()
