"""Load and validate an offline benchmark comparison export.

This module intentionally uses only the Python standard library.  The main
benchmark test environment can therefore validate dashboard inputs without
installing Streamlit, Plotly, pandas, or Matplotlib.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


MAX_ARTIFACT_BYTES = 100 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

ARTIFACT_HASH_KEYS = {
    "runs.csv": "runs_csv_sha256",
    "cases.csv": "cases_csv_sha256",
    "pairwise.csv": "pairwise_csv_sha256",
    "report.md": "report_md_sha256",
}
REQUIRED_FILES = (*ARTIFACT_HASH_KEYS, "comparison.json")

REQUIRED_RUN_COLUMNS = frozenset(
    {
        "variant_id",
        "run_id",
        "campaign_id",
        "provider",
        "adapter",
        "architecture",
        "requested_model",
        "request_profile",
        "max_output_tokens",
        "resolved_models",
        "sample_count",
        "malicious_count",
        "benign_count",
        "success_count",
        "tp",
        "fp",
        "tn",
        "fn",
        "precision",
        "recall",
        "f1",
        "false_positive_rate",
        "specificity",
        "schema_valid_count",
        "technical_failures",
        "critical_security_events",
        "golden_action_match_rate",
        "outbound_calls",
        "retries",
        "cost_unknown_attempts",
        "input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "total_tokens",
        "observed_cost_usd",
        "ledger_reserved_or_observed_cost_usd",
        "observed_cost_usd_per_message",
        "latency_min_ms",
        "latency_median_ms",
        "latency_iqr_ms",
        "latency_max_ms",
        "campaign_status",
        "comparative_conclusion",
        "git_commit",
        "git_dirty",
    }
)
REQUIRED_CASE_COLUMNS = frozenset(
    {
        "variant_id",
        "run_id",
        "sample_id",
        "case_name",
        "class_label",
        "scenario",
        "difficulty",
        "security_probe",
        "acceptable_actions_json",
        "status",
        "verdict",
        "predicted_action",
        "confusion_cell",
        "binary_correct",
        "golden_action_match",
        "technical_failure",
        "action_mapping_valid",
        "security_probe_allow",
        "trust_score",
        "confidence",
        "latency_ms",
        "outbound_attempts",
        "observed_cost_usd",
        "cost_known",
    }
)
REQUIRED_PAIRWISE_COLUMNS = frozenset(
    {
        "left_variant",
        "right_variant",
        "sample_count",
        "exact_action_agreement_count",
        "exact_action_agreement_rate",
        "binary_prediction_agreement_rate",
        "both_correct",
        "left_only_correct",
        "right_only_correct",
        "both_wrong",
        "delta_precision_right_minus_left",
        "delta_recall_right_minus_left",
        "delta_f1_right_minus_left",
        "delta_fpr_right_minus_left",
        "cost_ratio_right_over_left",
        "median_latency_ratio_right_over_left",
        "provider_calls_ratio_right_over_left",
    }
)

ALLOWED_RUN_COLUMNS = REQUIRED_RUN_COLUMNS | frozenset(
    {
        "accuracy",
        "balanced_accuracy",
        "cached_input_tokens",
        "config_id",
        "evaluation_profile",
        "evaluation_track",
        "false_negative_rate",
        "golden_action_matches",
        "not_attempted",
        "planned_workflows",
        "provider_failures",
        "reasoning_effort",
        "run_elapsed_seconds",
        "security_probe_allow",
        "started_workflows",
        "workflows",
    }
)
ALLOWED_CASE_COLUMNS = REQUIRED_CASE_COLUMNS | frozenset(
    {
        "adapter",
        "analysis_cluster_id",
        "cached_input_tokens",
        "campaign_id",
        "categories_json",
        "config_id",
        "detected_risk",
        "input_tokens",
        "label_confidence",
        "language",
        "llm_call_count",
        "max_output_tokens",
        "output_tokens",
        "predicted_positive",
        "provider",
        "provider_latency_ms",
        "reasoning_effort",
        "reasoning_tokens",
        "request_profile",
        "requested_model",
        "resolved_model",
        "total_tokens",
    }
)
ALLOWED_PAIRWISE_COLUMNS = REQUIRED_PAIRWISE_COLUMNS | frozenset(
    {
        "binary_prediction_agreement_count",
        "discordant_total",
        "mcnemar_exact_p_descriptive",
        "verdict_agreement_count",
        "verdict_agreement_rate",
    }
)

ALLOWED_METADATA_KEYS = frozenset(
    {
        "cases",
        "comparative_conclusion",
        "comparison_status",
        "compatibility",
        "csv_formula_escaping",
        "disclaimer",
        "eligible_for_ranking",
        "export_artifacts",
        "generated_at",
        "pairwise",
        "record_type",
        "runs",
        "schema_version",
        "source_artifacts",
        "trusted_labels",
    }
)
ALLOWED_COMPATIBILITY_KEYS = frozenset(
    {
        "baseline_variant",
        "comparison_type",
        "frozen_invariants",
        "max_output_tokens",
        "paired",
        "reasoning_efforts",
        "request_profiles",
        "same_adapter",
        "same_architecture",
        "same_max_output_tokens",
        "same_model",
        "same_prompt",
        "same_provider",
        "same_request_profile",
        "token_cap_adjustments",
    }
)
ALLOWED_FROZEN_INVARIANT_KEYS = frozenset(
    {
        "dataset_manifest_sha256",
        "dataset_sha256",
        "decision_policy_sha256",
        "labels_sha256",
        "negative_action",
        "positive_actions",
        "positive_class",
        "response_schema_sha256",
        "sample_count",
        "scoring_profile",
        "stage",
        "technical_failure_action",
        "technical_failures_in_denominators",
    }
)
ALLOWED_TOKEN_ADJUSTMENT_KEYS = frozenset(
    {
        "comparison_type",
        "crewai_max_output_tokens",
        "direct_max_output_tokens",
        "variant_id",
    }
)
ALLOWED_SOURCE_ARTIFACT_KEYS = frozenset(
    {
        "attempts_sha256",
        "budget_ledger_sha256",
        "metrics_sha256",
        "results_sha256",
        "run_dir",
        "run_id",
        "run_manifest_sha256",
        "scored_results_sha256",
    }
)

RUN_INTEGER_COLUMNS = frozenset(
    {
        "max_output_tokens",
        "sample_count",
        "malicious_count",
        "benign_count",
        "success_count",
        "tp",
        "fp",
        "tn",
        "fn",
        "schema_valid_count",
        "technical_failures",
        "critical_security_events",
        "security_probe_allow",
        "golden_action_matches",
        "outbound_calls",
        "retries",
        "cost_unknown_attempts",
        "workflows",
        "planned_workflows",
        "started_workflows",
        "not_attempted",
        "provider_failures",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "total_tokens",
    }
)
RUN_RATE_COLUMNS = frozenset(
    {
        "accuracy",
        "precision",
        "recall",
        "f1",
        "false_positive_rate",
        "false_negative_rate",
        "specificity",
        "balanced_accuracy",
        "golden_action_match_rate",
    }
)
RUN_NONNEGATIVE_FLOAT_COLUMNS = frozenset(
    {
        "observed_cost_usd",
        "ledger_reserved_or_observed_cost_usd",
        "observed_cost_usd_per_message",
        "latency_min_ms",
        "latency_median_ms",
        "latency_iqr_ms",
        "latency_max_ms",
        "run_elapsed_seconds",
    }
)
CASE_BOOLEAN_COLUMNS = frozenset(
    {
        "security_probe",
        "predicted_positive",
        "binary_correct",
        "golden_action_match",
        "technical_failure",
        "action_mapping_valid",
        "security_probe_allow",
        "detected_risk",
        "cost_known",
    }
)
NULLABLE_CASE_BOOLEAN_COLUMNS = frozenset(
    {"detected_risk", "golden_action_match"}
)
CASE_INTEGER_COLUMNS = frozenset(
    {
        "max_output_tokens",
        "outbound_attempts",
        "llm_call_count",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "total_tokens",
    }
)
CASE_NONNEGATIVE_FLOAT_COLUMNS = frozenset(
    {"trust_score", "confidence", "latency_ms", "provider_latency_ms", "observed_cost_usd"}
)

# The comparison exporter intentionally omits these fields.  Rejecting them
# prevents a future export from silently exposing message bodies or model
# reasoning in a browser UI.
DISALLOWED_COLUMNS = frozenset(
    {
        "body",
        "body_text",
        "email_body",
        "email_text",
        "message_body",
        "message_text",
        "prompt",
        "raw_email",
        "raw_message",
        "reasoning",
        "reasoning_text",
        "response_text",
        "subject",
    }
)


class DashboardDataError(ValueError):
    """Raised when a comparison directory is missing, unsafe, or inconsistent."""


@dataclass(frozen=True)
class ArtifactVerification:
    file_name: str
    expected_sha256: str
    actual_sha256: str

    @property
    def matches(self) -> bool:
        return self.expected_sha256 == self.actual_sha256


@dataclass(frozen=True)
class ComparisonBundle:
    directory: Path
    runs: tuple[dict[str, str], ...]
    cases: tuple[dict[str, str], ...]
    pairwise: tuple[dict[str, str], ...]
    metadata: dict[str, Any]
    report_markdown: str
    verifications: tuple[ArtifactVerification, ...]

    @property
    def variant_ids(self) -> tuple[str, ...]:
        return tuple(row["variant_id"] for row in self.runs)

    @property
    def all_artifacts_verified(self) -> bool:
        return bool(self.verifications) and all(
            verification.matches for verification in self.verifications
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_verified_artifact(bundle: ComparisonBundle, file_name: str) -> bytes:
    """Read one artifact and reject changes made after the bundle was loaded."""

    if file_name not in REQUIRED_FILES:
        raise DashboardDataError(f"Plik nie należy do eksportu: {file_name}")
    path = _safe_artifact(bundle.directory, file_name)
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise DashboardDataError(f"Nie można odczytać {file_name}") from exc

    if file_name in ARTIFACT_HASH_KEYS:
        hash_key = ARTIFACT_HASH_KEYS[file_name]
        expected = bundle.metadata["export_artifacts"][hash_key]
        actual = hashlib.sha256(payload).hexdigest()
        if actual != expected:
            raise DashboardDataError(
                f"{file_name} zmienił się po walidacji; pobieranie zablokowane"
            )
    else:
        try:
            current_metadata = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DashboardDataError(
                "comparison.json zmienił się po walidacji; pobieranie zablokowane"
            ) from exc
        if current_metadata != bundle.metadata:
            raise DashboardDataError(
                "comparison.json zmienił się po walidacji; pobieranie zablokowane"
            )
    return payload


def _safe_artifact(base: Path, file_name: str) -> Path:
    candidate = base / file_name
    if candidate.is_symlink():
        raise DashboardDataError(
            f"Artefakt dashboardu nie może być symlinkiem: {file_name}"
        )
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise DashboardDataError(f"Brak wymaganego pliku: {file_name}") from exc
    if resolved.parent != base or not resolved.is_file():
        raise DashboardDataError(f"Nieprawidłowa ścieżka artefaktu: {file_name}")
    if resolved.stat().st_size > MAX_ARTIFACT_BYTES:
        raise DashboardDataError(
            f"Artefakt przekracza limit {MAX_ARTIFACT_BYTES} bajtów: {file_name}"
        )
    return resolved


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DashboardDataError(f"Nie można odczytać JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise DashboardDataError(f"Korzeń {path.name} musi być obiektem JSON")
    return value


def _read_csv_rows(
    path: Path,
    required_columns: frozenset[str],
    allowed_columns: frozenset[str],
) -> tuple[dict[str, str], ...]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames
            if not fieldnames:
                raise DashboardDataError(f"Brak nagłówka CSV: {path.name}")
            if any(not name for name in fieldnames):
                raise DashboardDataError(f"Pusty nagłówek kolumny w {path.name}")
            duplicates = sorted(
                name for name, count in Counter(fieldnames).items() if count > 1
            )
            if duplicates:
                raise DashboardDataError(
                    f"Powielone kolumny w {path.name}: {', '.join(duplicates)}"
                )
            columns = frozenset(fieldnames)
            missing = sorted(required_columns - columns)
            if missing:
                raise DashboardDataError(
                    f"Brak wymaganych kolumn w {path.name}: {', '.join(missing)}"
                )
            disallowed = sorted(columns & DISALLOWED_COLUMNS)
            if disallowed:
                raise DashboardDataError(
                    f"{path.name} zawiera niedozwolone surowe pola: "
                    f"{', '.join(disallowed)}"
                )
            unknown = sorted(columns - allowed_columns)
            if unknown:
                raise DashboardDataError(
                    f"{path.name} zawiera niedozwolone kolumny spoza schematu: "
                    f"{', '.join(unknown)}"
                )
            parsed_rows: list[dict[str, str]] = []
            for line_number, row in enumerate(reader, start=2):
                if None in row:
                    raise DashboardDataError(
                        f"{path.name}:{line_number} ma nadmiarowe komórki"
                    )
                if any(value is None for value in row.values()):
                    raise DashboardDataError(
                        f"{path.name}:{line_number} ma brakujące komórki"
                    )
                parsed_rows.append(dict(row))
            rows = tuple(parsed_rows)
    except DashboardDataError:
        raise
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise DashboardDataError(f"Nie można odczytać CSV: {path.name}") from exc
    if not rows:
        raise DashboardDataError(f"Plik CSV jest pusty: {path.name}")
    return rows


def _nonnegative_int(value: str, *, field: str, context: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise DashboardDataError(
            f"{context}: {field} musi być liczbą całkowitą"
        ) from exc
    if parsed < 0:
        raise DashboardDataError(f"{context}: {field} nie może być ujemne")
    return parsed


def _finite_float(
    value: str,
    *,
    field: str,
    context: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise DashboardDataError(f"{context}: {field} musi być liczbą") from exc
    if not math.isfinite(parsed):
        raise DashboardDataError(f"{context}: {field} musi być liczbą skończoną")
    if minimum is not None and parsed < minimum:
        raise DashboardDataError(f"{context}: {field} jest mniejsze niż {minimum}")
    if maximum is not None and parsed > maximum:
        raise DashboardDataError(f"{context}: {field} jest większe niż {maximum}")
    return parsed


def _strict_bool(
    value: str, *, field: str, context: str, allow_blank: bool = False
) -> bool | None:
    if allow_blank and value == "":
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    raise DashboardDataError(f"{context}: {field} musi mieć wartość true albo false")


def _json_scalar_to_csv(
    value: Any, *, context: str, escape_formulas: bool
) -> str:
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        if escape_formulas and value.lstrip().startswith(("=", "+", "-", "@")):
            return "'" + value
        return value
    if isinstance(value, (int, float)):
        return str(value)
    raise DashboardDataError(f"{context}: wartość JSON nie jest skalarem")


def _validate_csv_json_rows(
    section: str,
    csv_rows: tuple[dict[str, str], ...],
    json_rows: list[Any],
    *,
    escape_formulas: bool,
) -> None:
    if len(csv_rows) != len(json_rows):
        raise DashboardDataError(
            f"Liczba rekordów {section}.csv nie zgadza się z comparison.json"
        )
    for index, (csv_row, json_row) in enumerate(
        zip(csv_rows, json_rows, strict=True), start=1
    ):
        context = f"comparison.json/{section}[{index - 1}]"
        if not isinstance(json_row, dict):
            raise DashboardDataError(f"{context} musi być obiektem")
        if set(json_row) != set(csv_row):
            raise DashboardDataError(
                f"{section}.csv i {context} mają inne kolumny"
            )
        for column, csv_value in csv_row.items():
            json_value = _json_scalar_to_csv(
                json_row[column],
                context=f"{context}/{column}",
                escape_formulas=escape_formulas,
            )
            if csv_value != json_value:
                raise DashboardDataError(
                    f"{section}.csv i {context} różnią się w polu {column}"
                )


def _divide(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def _assert_rounded_value(
    value: str,
    expected: float | None,
    *,
    field: str,
    context: str,
    abs_tolerance: float = 1e-6,
) -> None:
    if expected is None:
        if value != "":
            raise DashboardDataError(f"{context}: {field} powinno być puste")
        return
    actual = _finite_float(value, field=field, context=context)
    if not math.isclose(
        actual, expected, rel_tol=1e-6, abs_tol=abs_tolerance
    ):
        raise DashboardDataError(
            f"{context}: {field}={actual} nie zgadza się z przeliczeniem {expected}"
        )


def _verify_artifacts(
    paths: Mapping[str, Path], metadata: Mapping[str, Any]
) -> tuple[ArtifactVerification, ...]:
    export_hashes = metadata.get("export_artifacts")
    if not isinstance(export_hashes, dict):
        raise DashboardDataError(
            "comparison.json nie zawiera obiektu export_artifacts"
        )
    expected_hash_keys = set(ARTIFACT_HASH_KEYS.values())
    if set(export_hashes) != expected_hash_keys:
        raise DashboardDataError(
            "export_artifacts ma inny zestaw pól niż schema_version=1.0"
        )
    verifications: list[ArtifactVerification] = []
    for file_name, hash_key in ARTIFACT_HASH_KEYS.items():
        expected = export_hashes.get(hash_key)
        if not isinstance(expected, str) or not SHA256_RE.fullmatch(expected):
            raise DashboardDataError(
                f"Brak poprawnego SHA-256 {hash_key} w comparison.json"
            )
        actual = sha256_file(paths[file_name])
        verification = ArtifactVerification(file_name, expected, actual)
        if not verification.matches:
            raise DashboardDataError(
                f"Niezgodny SHA-256 dla {file_name}; nie pokazuję zmienionych danych"
            )
        verifications.append(verification)
    return tuple(verifications)


def _validate_metadata(metadata: Mapping[str, Any]) -> None:
    unknown_keys = sorted(set(metadata) - ALLOWED_METADATA_KEYS)
    if unknown_keys:
        raise DashboardDataError(
            "comparison.json zawiera pola spoza schematu: "
            + ", ".join(unknown_keys)
        )
    if metadata.get("record_type") != "BenchmarkComparison":
        raise DashboardDataError(
            "comparison.json nie jest eksportem BenchmarkComparison"
        )
    if metadata.get("schema_version") != "1.0":
        raise DashboardDataError("Dashboard obsługuje schema_version=1.0")
    if not isinstance(metadata.get("runs"), list):
        raise DashboardDataError("comparison.json nie zawiera listy runs")
    if not isinstance(metadata.get("cases"), list):
        raise DashboardDataError("comparison.json nie zawiera listy cases")
    if not isinstance(metadata.get("pairwise"), list):
        raise DashboardDataError("comparison.json nie zawiera listy pairwise")
    compatibility = metadata.get("compatibility")
    if compatibility is not None:
        if not isinstance(compatibility, dict):
            raise DashboardDataError("compatibility musi być obiektem JSON")
        unknown_compatibility = sorted(
            set(compatibility) - ALLOWED_COMPATIBILITY_KEYS
        )
        if unknown_compatibility:
            raise DashboardDataError(
                "compatibility zawiera pola spoza schematu: "
                + ", ".join(unknown_compatibility)
            )
        frozen = compatibility.get("frozen_invariants")
        if frozen is not None:
            if not isinstance(frozen, dict):
                raise DashboardDataError("frozen_invariants musi być obiektem")
            unknown_frozen = sorted(
                set(frozen) - ALLOWED_FROZEN_INVARIANT_KEYS
            )
            if unknown_frozen:
                raise DashboardDataError(
                    "frozen_invariants zawiera pola spoza schematu: "
                    + ", ".join(unknown_frozen)
                )
        adjustments = compatibility.get("token_cap_adjustments", [])
        if not isinstance(adjustments, list):
            raise DashboardDataError("token_cap_adjustments musi być listą")
        for index, adjustment in enumerate(adjustments):
            if not isinstance(adjustment, dict):
                raise DashboardDataError(
                    f"token_cap_adjustments[{index}] musi być obiektem"
                )
            unknown_adjustment = sorted(
                set(adjustment) - ALLOWED_TOKEN_ADJUSTMENT_KEYS
            )
            if unknown_adjustment:
                raise DashboardDataError(
                    f"token_cap_adjustments[{index}] ma pola spoza schematu: "
                    + ", ".join(unknown_adjustment)
                )
    formula_escaping = metadata.get("csv_formula_escaping")
    if formula_escaping is not None and formula_escaping != (
        "apostrophe_prefix_after_leading_whitespace"
    ):
        raise DashboardDataError("Nieznana polityka csv_formula_escaping")
    trusted_labels = metadata.get("trusted_labels")
    if trusted_labels is not None:
        if not isinstance(trusted_labels, dict):
            raise DashboardDataError("trusted_labels musi być obiektem")
        unknown_trusted = sorted(set(trusted_labels) - {"path", "sha256"})
        if unknown_trusted:
            raise DashboardDataError(
                "trusted_labels zawiera pola spoza schematu: "
                + ", ".join(unknown_trusted)
            )


def _validate_relations(
    runs: tuple[dict[str, str], ...],
    cases: tuple[dict[str, str], ...],
    pairwise: tuple[dict[str, str], ...],
    metadata: Mapping[str, Any],
) -> None:
    variant_ids = [row.get("variant_id", "") for row in runs]
    if any(not variant_id for variant_id in variant_ids):
        raise DashboardDataError("runs.csv zawiera pusty variant_id")
    if len(variant_ids) != len(set(variant_ids)):
        raise DashboardDataError("runs.csv zawiera powielony variant_id")
    variant_set = set(variant_ids)

    run_by_variant = {row["variant_id"]: row for row in runs}
    case_keys: set[tuple[str, str]] = set()
    cases_by_variant: Counter[str] = Counter()
    classes_by_variant: Counter[tuple[str, str]] = Counter()
    cells_by_variant: Counter[tuple[str, str]] = Counter()
    successes_by_variant: Counter[str] = Counter()
    technical_by_variant: Counter[str] = Counter()
    outbound_by_variant: Counter[str] = Counter()
    cost_by_variant: Counter[str] = Counter()
    cost_values_by_variant: Counter[str] = Counter()
    token_sums_by_variant: dict[str, Counter[str]] = {
        variant_id: Counter() for variant_id in variant_ids
    }
    samples_by_variant: dict[str, set[str]] = {
        variant_id: set() for variant_id in variant_ids
    }
    correct_by_variant: dict[str, dict[str, bool]] = {
        variant_id: {} for variant_id in variant_ids
    }
    action_by_variant: dict[str, dict[str, str]] = {
        variant_id: {} for variant_id in variant_ids
    }
    positive_by_variant: dict[str, dict[str, bool]] = {
        variant_id: {} for variant_id in variant_ids
    }
    identity_by_variant: dict[str, dict[str, tuple[str, str, str, str]]] = {
        variant_id: {} for variant_id in variant_ids
    }
    case_names_by_variant: dict[str, set[str]] = {
        variant_id: set() for variant_id in variant_ids
    }
    for row in cases:
        variant_id = row.get("variant_id", "")
        sample_id = row.get("sample_id", "")
        if variant_id not in variant_set:
            raise DashboardDataError(
                f"cases.csv odwołuje się do nieznanego wariantu: {variant_id}"
            )
        if not sample_id:
            raise DashboardDataError("cases.csv zawiera pusty sample_id")
        key = (variant_id, sample_id)
        if key in case_keys:
            raise DashboardDataError(
                f"Powielony wynik wariantu i próbki w cases.csv: {key}"
            )
        case_keys.add(key)
        cases_by_variant[variant_id] += 1
        samples_by_variant[variant_id].add(sample_id)
        context = f"cases.csv/{variant_id}/{sample_id}"
        if row.get("run_id") != run_by_variant[variant_id].get("run_id"):
            raise DashboardDataError(f"{context}: run_id nie zgadza się z runs.csv")
        class_label = row.get("class_label", "")
        if class_label not in {"malicious", "benign"}:
            raise DashboardDataError(f"{context}: nieznany class_label={class_label}")
        confusion_cell = row.get("confusion_cell", "").lower()
        if confusion_cell not in {"tp", "fp", "tn", "fn"}:
            raise DashboardDataError(
                f"{context}: nieznany confusion_cell={confusion_cell}"
            )
        classes_by_variant[(variant_id, class_label)] += 1
        cells_by_variant[(variant_id, confusion_cell)] += 1
        case_name = row.get("case_name", "")
        if not case_name:
            raise DashboardDataError(f"{context}: pusty case_name")
        if case_name in case_names_by_variant[variant_id]:
            raise DashboardDataError(
                f"{context}: powielony case_name={case_name} w wariancie"
            )
        case_names_by_variant[variant_id].add(case_name)
        identity_by_variant[variant_id][sample_id] = (
            case_name,
            class_label,
            row.get("scenario", ""),
            row.get("difficulty", ""),
        )
        if class_label == "malicious" and confusion_cell not in {"tp", "fn"}:
            raise DashboardDataError(
                f"{context}: malicious wymaga confusion_cell TP albo FN"
            )
        if class_label == "benign" and confusion_cell not in {"fp", "tn"}:
            raise DashboardDataError(
                f"{context}: benign wymaga confusion_cell FP albo TN"
            )
        if row.get("status") == "success":
            successes_by_variant[variant_id] += 1
        technical = _strict_bool(
            row["technical_failure"],
            field="technical_failure",
            context=context,
        )
        if technical:
            technical_by_variant[variant_id] += 1
        for field in CASE_BOOLEAN_COLUMNS:
            if field not in row:
                continue
            _strict_bool(
                row[field],
                field=field,
                context=context,
                allow_blank=field in NULLABLE_CASE_BOOLEAN_COLUMNS,
            )
        parsed_case_integers: dict[str, int] = {}
        for field in CASE_INTEGER_COLUMNS:
            if field in row and row[field] != "":
                parsed_case_integers[field] = _nonnegative_int(
                    row[field], field=field, context=context
                )
        parsed_case_floats: dict[str, float] = {}
        for field in CASE_NONNEGATIVE_FLOAT_COLUMNS:
            if field in row and row[field] != "":
                maximum = 100 if field == "trust_score" else None
                if field == "confidence":
                    maximum = 1
                parsed_case_floats[field] = _finite_float(
                    row[field],
                    field=field,
                    context=context,
                    minimum=0,
                    maximum=maximum,
                )
        outbound_by_variant[variant_id] += parsed_case_integers[
            "outbound_attempts"
        ]
        if "observed_cost_usd" in parsed_case_floats:
            cost_by_variant[variant_id] += parsed_case_floats[
                "observed_cost_usd"
            ]
            cost_values_by_variant[variant_id] += 1
        for field in (
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "total_tokens",
        ):
            if field in parsed_case_integers:
                token_sums_by_variant[variant_id][field] += parsed_case_integers[
                    field
                ]
        correct = _strict_bool(
            row["binary_correct"], field="binary_correct", context=context
        )
        if bool(correct) != (confusion_cell in {"tp", "tn"}):
            raise DashboardDataError(
                f"{context}: binary_correct nie zgadza się z confusion_cell"
            )
        correct_by_variant[variant_id][sample_id] = bool(correct)
        action = row.get("predicted_action", "")
        if action not in {"allow", "warn", "hide"}:
            raise DashboardDataError(f"{context}: nieznana akcja {action}")
        predicted_positive = action in {"warn", "hide"}
        if predicted_positive != (confusion_cell in {"tp", "fp"}):
            raise DashboardDataError(
                f"{context}: predicted_action nie zgadza się z confusion_cell"
            )
        if "predicted_positive" in row and row["predicted_positive"] != "":
            stored_positive = _strict_bool(
                row["predicted_positive"],
                field="predicted_positive",
                context=context,
            )
            if bool(stored_positive) != predicted_positive:
                raise DashboardDataError(
                    f"{context}: predicted_positive nie zgadza się z akcją"
                )
        action_by_variant[variant_id][sample_id] = action
        positive_by_variant[variant_id][sample_id] = predicted_positive

    if set(cases_by_variant) != variant_set:
        missing = sorted(variant_set - set(cases_by_variant))
        raise DashboardDataError(
            f"Brak przypadków dla wariantów: {', '.join(missing)}"
        )
    reference_variant = variant_ids[0]
    reference_samples = samples_by_variant[reference_variant]
    for variant_id in variant_ids[1:]:
        if samples_by_variant[variant_id] != reference_samples:
            raise DashboardDataError(
                f"{variant_id} ma inny zestaw sample_id niż {reference_variant}"
            )
        if identity_by_variant[variant_id] != identity_by_variant[reference_variant]:
            raise DashboardDataError(
                f"{variant_id} ma inne metadane przypadków niż {reference_variant}"
            )
    for variant_id, run in run_by_variant.items():
        context = f"runs.csv/{variant_id}"
        integers = {
            field: _nonnegative_int(run[field], field=field, context=context)
            for field in RUN_INTEGER_COLUMNS
            if field in run
        }
        for field in RUN_RATE_COLUMNS:
            if field in run and run[field] != "":
                _finite_float(
                    run[field],
                    field=field,
                    context=context,
                    minimum=0,
                    maximum=1,
                )
        for field in RUN_NONNEGATIVE_FLOAT_COLUMNS:
            if field in run and run[field] != "":
                _finite_float(
                    run[field], field=field, context=context, minimum=0
                )
        _strict_bool(run["git_dirty"], field="git_dirty", context=context)
        expected = integers["sample_count"]
        actual = cases_by_variant[variant_id]
        if expected != actual:
            raise DashboardDataError(
                f"{variant_id}: sample_count={expected}, ale cases.csv ma {actual} rekordów"
            )
        if integers["malicious_count"] + integers["benign_count"] != expected:
            raise DashboardDataError(
                f"{context}: malicious_count + benign_count != sample_count"
            )
        if sum(integers[cell] for cell in ("tp", "fp", "tn", "fn")) != expected:
            raise DashboardDataError(f"{context}: TP+FP+TN+FN != sample_count")
        expected_values = {
            "malicious_count": classes_by_variant[(variant_id, "malicious")],
            "benign_count": classes_by_variant[(variant_id, "benign")],
            "success_count": successes_by_variant[variant_id],
            "technical_failures": technical_by_variant[variant_id],
            "tp": cells_by_variant[(variant_id, "tp")],
            "fp": cells_by_variant[(variant_id, "fp")],
            "tn": cells_by_variant[(variant_id, "tn")],
            "fn": cells_by_variant[(variant_id, "fn")],
        }
        for field, case_value in expected_values.items():
            if integers[field] != case_value:
                raise DashboardDataError(
                    f"{context}: {field}={integers[field]}, "
                    f"ale cases.csv daje {case_value}"
                )
        tp, fp, tn, fn = (
            integers[field] for field in ("tp", "fp", "tn", "fn")
        )
        recall = _divide(tp, tp + fn)
        specificity = _divide(tn, tn + fp)
        precision = _divide(tp, tp + fp)
        expected_metrics = {
            "accuracy": _divide(tp + tn, expected),
            "precision": precision,
            "recall": recall,
            "f1": (
                2 * precision * recall / (precision + recall)
                if precision is not None
                and recall is not None
                and precision + recall
                else None
            ),
            "false_positive_rate": _divide(fp, fp + tn),
            "false_negative_rate": _divide(fn, fn + tp),
            "specificity": specificity,
            "balanced_accuracy": (
                (recall + specificity) / 2
                if recall is not None and specificity is not None
                else None
            ),
        }
        for field, metric_value in expected_metrics.items():
            if field in run:
                _assert_rounded_value(
                    run[field], metric_value, field=field, context=context
                )
        if "golden_action_matches" in integers:
            _assert_rounded_value(
                run["golden_action_match_rate"],
                _divide(integers["golden_action_matches"], expected),
                field="golden_action_match_rate",
                context=context,
            )
        if integers["outbound_calls"] != outbound_by_variant[variant_id]:
            raise DashboardDataError(
                f"{context}: outbound_calls nie zgadza się z cases.csv"
            )
        if cost_values_by_variant[variant_id] == expected:
            _assert_rounded_value(
                run["observed_cost_usd"],
                float(cost_by_variant[variant_id]),
                field="observed_cost_usd",
                context=context,
                abs_tolerance=1e-10,
            )
        expected_cost_per_message = (
            _divide(float(run["observed_cost_usd"]), expected)
            if run["observed_cost_usd"] != ""
            else None
        )
        _assert_rounded_value(
            run["observed_cost_usd_per_message"],
            expected_cost_per_message,
            field="observed_cost_usd_per_message",
            context=context,
            abs_tolerance=1e-9,
        )
        for field, case_total in token_sums_by_variant[variant_id].items():
            if field in integers and integers[field] != case_total:
                raise DashboardDataError(
                    f"{context}: {field} nie zgadza się z cases.csv"
                )

    pair_keys: set[frozenset[str]] = set()
    for row in pairwise:
        left = row.get("left_variant", "")
        right = row.get("right_variant", "")
        if left not in variant_set or right not in variant_set:
            raise DashboardDataError(
                f"pairwise.csv odwołuje się do nieznanej pary: {left}, {right}"
            )
        if left == right:
            raise DashboardDataError("pairwise.csv zawiera porównanie wariantu z nim samym")
        key = frozenset((left, right))
        if key in pair_keys:
            raise DashboardDataError(
                f"pairwise.csv zawiera powieloną parę: {left}, {right}"
            )
        pair_keys.add(key)
        context = f"pairwise.csv/{left}/{right}"
        sample_count = _nonnegative_int(
            row["sample_count"], field="sample_count", context=context
        )
        if sample_count != len(reference_samples):
            raise DashboardDataError(
                f"{context}: sample_count nie zgadza się z cases.csv"
            )
        count_fields = (
            "exact_action_agreement_count",
            "both_correct",
            "left_only_correct",
            "right_only_correct",
            "both_wrong",
        )
        parsed_counts = {
            field: _nonnegative_int(row[field], field=field, context=context)
            for field in count_fields
        }
        if sum(parsed_counts[field] for field in count_fields[1:]) != sample_count:
            raise DashboardDataError(
                f"{context}: macierz poprawności nie sumuje się do sample_count"
            )
        rate_fields = (
            "exact_action_agreement_rate",
            "binary_prediction_agreement_rate",
        )
        for field in rate_fields:
            if row[field] != "":
                _finite_float(
                    row[field],
                    field=field,
                    context=context,
                    minimum=0,
                    maximum=1,
                )
        for field in (
            "delta_precision_right_minus_left",
            "delta_recall_right_minus_left",
            "delta_f1_right_minus_left",
            "delta_fpr_right_minus_left",
        ):
            if row[field] != "":
                _finite_float(
                    row[field],
                    field=field,
                    context=context,
                    minimum=-1,
                    maximum=1,
                )
        for field in (
            "cost_ratio_right_over_left",
            "median_latency_ratio_right_over_left",
            "provider_calls_ratio_right_over_left",
        ):
            if row[field] != "":
                _finite_float(
                    row[field], field=field, context=context, minimum=0
                )

        samples = sorted(reference_samples)
        actual_counts = Counter()
        exact_actions = 0
        binary_agreements = 0
        for sample_id in samples:
            left_correct = correct_by_variant[left][sample_id]
            right_correct = correct_by_variant[right][sample_id]
            if left_correct and right_correct:
                actual_counts["both_correct"] += 1
            elif left_correct:
                actual_counts["left_only_correct"] += 1
            elif right_correct:
                actual_counts["right_only_correct"] += 1
            else:
                actual_counts["both_wrong"] += 1
            exact_actions += int(
                action_by_variant[left][sample_id]
                == action_by_variant[right][sample_id]
            )
            binary_agreements += int(
                positive_by_variant[left][sample_id]
                == positive_by_variant[right][sample_id]
            )
        for field in count_fields[1:]:
            if parsed_counts[field] != actual_counts[field]:
                raise DashboardDataError(
                    f"{context}: {field} nie zgadza się z cases.csv"
                )
        if parsed_counts["exact_action_agreement_count"] != exact_actions:
            raise DashboardDataError(
                f"{context}: exact_action_agreement_count nie zgadza się z cases.csv"
            )
        if "binary_prediction_agreement_count" in row:
            binary_count = _nonnegative_int(
                row["binary_prediction_agreement_count"],
                field="binary_prediction_agreement_count",
                context=context,
            )
            if binary_count != binary_agreements:
                raise DashboardDataError(
                    f"{context}: binary agreement nie zgadza się z cases.csv"
                )
        _assert_rounded_value(
            row["exact_action_agreement_rate"],
            _divide(exact_actions, sample_count),
            field="exact_action_agreement_rate",
            context=context,
        )
        _assert_rounded_value(
            row["binary_prediction_agreement_rate"],
            _divide(binary_agreements, sample_count),
            field="binary_prediction_agreement_rate",
            context=context,
        )

        left_run = run_by_variant[left]
        right_run = run_by_variant[right]
        for field, metric in (
            ("delta_precision_right_minus_left", "precision"),
            ("delta_recall_right_minus_left", "recall"),
            ("delta_f1_right_minus_left", "f1"),
            ("delta_fpr_right_minus_left", "false_positive_rate"),
        ):
            left_raw = left_run[metric]
            right_raw = right_run[metric]
            expected_delta = (
                float(right_raw) - float(left_raw)
                if left_raw != "" and right_raw != ""
                else None
            )
            _assert_rounded_value(
                row[field],
                expected_delta,
                field=field,
                context=context,
            )
        for field, metric in (
            ("cost_ratio_right_over_left", "observed_cost_usd_per_message"),
            ("median_latency_ratio_right_over_left", "latency_median_ms"),
            ("provider_calls_ratio_right_over_left", "outbound_calls"),
        ):
            left_raw = left_run[metric]
            right_raw = right_run[metric]
            expected_ratio = (
                _divide(float(right_raw), float(left_raw))
                if left_raw != "" and right_raw != ""
                else None
            )
            _assert_rounded_value(
                row[field], expected_ratio, field=field, context=context
            )

    expected_pair_count = len(variant_set) * (len(variant_set) - 1) // 2
    if len(pairwise) != expected_pair_count:
        raise DashboardDataError(
            f"pairwise.csv ma {len(pairwise)} par; oczekiwano {expected_pair_count}"
        )

    json_runs = metadata["runs"]
    json_cases = metadata["cases"]
    json_pairwise = metadata["pairwise"]
    escape_formulas = metadata.get("csv_formula_escaping") == (
        "apostrophe_prefix_after_leading_whitespace"
    )
    _validate_csv_json_rows(
        "runs", runs, json_runs, escape_formulas=escape_formulas
    )
    _validate_csv_json_rows(
        "cases", cases, json_cases, escape_formulas=escape_formulas
    )
    _validate_csv_json_rows(
        "pairwise", pairwise, json_pairwise, escape_formulas=escape_formulas
    )

    sources = metadata.get("source_artifacts")
    if not isinstance(sources, dict) or set(sources) != variant_set:
        raise DashboardDataError(
            "source_artifacts nie pokrywa wszystkich wariantów porównania"
        )
    for variant_id, source in sources.items():
        if not isinstance(source, dict):
            raise DashboardDataError(
                f"source_artifacts/{variant_id} musi być obiektem"
            )
        unknown_source_keys = sorted(
            set(source) - ALLOWED_SOURCE_ARTIFACT_KEYS
        )
        if unknown_source_keys:
            raise DashboardDataError(
                f"source_artifacts/{variant_id} ma pola spoza schematu: "
                + ", ".join(unknown_source_keys)
            )


def load_comparison_bundle(directory: str | Path) -> ComparisonBundle:
    """Load a comparison directory after strict, read-only validation."""

    raw_directory = Path(directory).expanduser()
    try:
        base = raw_directory.resolve(strict=True)
    except FileNotFoundError as exc:
        raise DashboardDataError(
            f"Katalog porównania nie istnieje: {raw_directory}"
        ) from exc
    if not base.is_dir():
        raise DashboardDataError(f"Ścieżka nie jest katalogiem: {base}")

    paths = {file_name: _safe_artifact(base, file_name) for file_name in REQUIRED_FILES}
    metadata = _read_json_object(paths["comparison.json"])
    _validate_metadata(metadata)
    verifications = _verify_artifacts(paths, metadata)
    runs = _read_csv_rows(
        paths["runs.csv"], REQUIRED_RUN_COLUMNS, ALLOWED_RUN_COLUMNS
    )
    cases = _read_csv_rows(
        paths["cases.csv"], REQUIRED_CASE_COLUMNS, ALLOWED_CASE_COLUMNS
    )
    pairwise = _read_csv_rows(
        paths["pairwise.csv"],
        REQUIRED_PAIRWISE_COLUMNS,
        ALLOWED_PAIRWISE_COLUMNS,
    )
    try:
        report = paths["report.md"].read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise DashboardDataError("Nie można odczytać report.md") from exc
    _validate_relations(runs, cases, pairwise, metadata)

    return ComparisonBundle(
        directory=base,
        runs=runs,
        cases=cases,
        pairwise=pairwise,
        metadata=metadata,
        report_markdown=report,
        verifications=verifications,
    )
