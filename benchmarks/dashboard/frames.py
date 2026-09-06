"""Convert validated comparison rows to typed pandas DataFrames."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

try:
    from .analytics import architecture_label, as_bool, model_label, variant_label
    from .data_loader import ComparisonBundle
except ImportError:  # Streamlit executes app.py as a script.
    from analytics import architecture_label, as_bool, model_label, variant_label
    from data_loader import ComparisonBundle

if TYPE_CHECKING:
    from collections.abc import Iterable


RUN_NUMERIC_COLUMNS = {
    "sample_count",
    "malicious_count",
    "benign_count",
    "success_count",
    "tp",
    "fp",
    "tn",
    "fn",
    "accuracy",
    "precision",
    "recall",
    "f1",
    "false_positive_rate",
    "false_negative_rate",
    "specificity",
    "balanced_accuracy",
    "schema_valid_count",
    "technical_failures",
    "critical_security_events",
    "security_probe_allow",
    "golden_action_matches",
    "golden_action_match_rate",
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
    "observed_cost_usd",
    "ledger_reserved_or_observed_cost_usd",
    "observed_cost_usd_per_message",
    "latency_min_ms",
    "latency_median_ms",
    "latency_iqr_ms",
    "latency_max_ms",
    "run_elapsed_seconds",
    "max_output_tokens",
}
CASE_NUMERIC_COLUMNS = {
    "trust_score",
    "confidence",
    "latency_ms",
    "provider_latency_ms",
    "outbound_attempts",
    "llm_call_count",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "total_tokens",
    "observed_cost_usd",
    "max_output_tokens",
}
CASE_BOOLEAN_COLUMNS = {
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
PAIRWISE_NUMERIC_COLUMNS = {
    "sample_count",
    "exact_action_agreement_count",
    "exact_action_agreement_rate",
    "verdict_agreement_count",
    "verdict_agreement_rate",
    "binary_prediction_agreement_count",
    "binary_prediction_agreement_rate",
    "both_correct",
    "left_only_correct",
    "right_only_correct",
    "both_wrong",
    "discordant_total",
    "mcnemar_exact_p_descriptive",
    "delta_precision_right_minus_left",
    "delta_recall_right_minus_left",
    "delta_f1_right_minus_left",
    "delta_fpr_right_minus_left",
    "cost_ratio_right_over_left",
    "median_latency_ratio_right_over_left",
    "provider_calls_ratio_right_over_left",
}


def _coerce_numeric(frame: pd.DataFrame, columns: "Iterable[str]") -> None:
    for column in columns:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")


def comparison_frames(
    bundle: ComparisonBundle,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    runs = pd.DataFrame(bundle.runs)
    cases = pd.DataFrame(bundle.cases)
    pairwise = pd.DataFrame(bundle.pairwise)

    _coerce_numeric(runs, RUN_NUMERIC_COLUMNS)
    _coerce_numeric(cases, CASE_NUMERIC_COLUMNS)
    _coerce_numeric(pairwise, PAIRWISE_NUMERIC_COLUMNS)
    for column in CASE_BOOLEAN_COLUMNS:
        if column in cases.columns:
            cases[column] = cases[column].map(as_bool).astype("boolean")
    if "git_dirty" in runs.columns:
        runs["git_dirty"] = runs["git_dirty"].map(as_bool).astype("boolean")

    runs["model_label"] = [model_label(row) for row in bundle.runs]
    runs["architecture_label"] = [
        architecture_label(row) for row in bundle.runs
    ]
    base_labels = [variant_label(row) for row in bundle.runs]
    duplicate_labels = {
        label for label in base_labels if base_labels.count(label) > 1
    }
    runs["variant_label"] = [
        f"{label} · {row['variant_id']}" if label in duplicate_labels else label
        for label, row in zip(base_labels, bundle.runs, strict=True)
    ]
    label_by_variant = dict(zip(runs["variant_id"], runs["variant_label"], strict=True))
    model_by_variant = dict(zip(runs["variant_id"], runs["model_label"], strict=True))
    architecture_by_variant = dict(
        zip(runs["variant_id"], runs["architecture_label"], strict=True)
    )
    cases["variant_label"] = cases["variant_id"].map(label_by_variant)
    cases["model_label"] = cases["variant_id"].map(model_by_variant)
    cases["architecture_label"] = cases["variant_id"].map(
        architecture_by_variant
    )

    return runs, cases, pairwise
