"""Pure analysis helpers shared by the dashboard and its tests."""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Iterable, Mapping, Sequence


MODEL_LABELS = {
    "gpt-5.4-nano-2026-03-17": "GPT-5.4 Nano",
    "gpt-5.4-mini-2026-03-17": "GPT-5.4 Mini",
    "gemini-3.1-flash-lite": "Gemini 3.1 Flash-Lite",
    "gemini-3.7-flash": "Gemini 3.7 Flash",
}


def as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    return None


def model_label(row: Mapping[str, Any]) -> str:
    requested = str(row.get("requested_model") or "Unknown model")
    return MODEL_LABELS.get(requested, requested)


def architecture_label(row: Mapping[str, Any]) -> str:
    architecture = str(row.get("architecture") or "").lower()
    adapter = str(row.get("adapter") or "").lower()
    return "CrewAI" if architecture == "crew" or "crewai" in adapter else "Direct"


def variant_label(row: Mapping[str, Any]) -> str:
    return f"{model_label(row)} · {architecture_label(row)}"


def recompute_binary_metrics(
    case_rows: Iterable[Mapping[str, Any]],
) -> dict[str, float | int | None]:
    counts = Counter(
        str(row.get("confusion_cell") or "").lower()
        for row in case_rows
        if str(row.get("confusion_cell") or "").lower() in {"tp", "fp", "tn", "fn"}
    )
    tp, fp, tn, fn = (counts[name] for name in ("tp", "fp", "tn", "fn"))

    def ratio(numerator: int, denominator: int) -> float | None:
        return numerator / denominator if denominator else None

    precision = ratio(tp, tp + fp)
    recall = ratio(tp, tp + fn)
    specificity = ratio(tn, tn + fp)
    fpr = ratio(fp, fp + tn)
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None
        and recall is not None
        and precision + recall > 0
        else None
    )
    return {
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "specificity": specificity,
        "false_positive_rate": fpr,
        "f1": f1,
        "evaluated_count": tp + fp + tn + fn,
    }


def comparison_scope(
    direct: Mapping[str, Any], crew: Mapping[str, Any]
) -> str:
    direct_cap = as_int(direct.get("max_output_tokens"))
    crew_cap = as_int(crew.get("max_output_tokens"))
    if direct_cap != crew_cap:
        return "token_cap_adjusted_system_bundle_delta"
    if str(direct.get("request_profile")) != str(crew.get("request_profile")):
        return "cross_api_system_bundle_delta"
    return "system_bundle_delta"


def _ratio(right: float | None, left: float | None) -> float | None:
    if right is None or left in (None, 0):
        return None
    return right / left


def _find_pairwise(
    pairwise_rows: Sequence[Mapping[str, Any]],
    left_variant: str,
    right_variant: str,
) -> Mapping[str, Any] | None:
    target = {left_variant, right_variant}
    for row in pairwise_rows:
        if {str(row.get("left_variant")), str(row.get("right_variant"))} == target:
            return row
    return None


def direct_crewai_comparisons(
    run_rows: Sequence[Mapping[str, Any]],
    pairwise_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return one consistently oriented Direct -> CrewAI row per model."""

    grouped: dict[str, dict[str, Mapping[str, Any]]] = {}
    for row in run_rows:
        requested_model = str(row.get("requested_model"))
        architecture = architecture_label(row)
        model_group = grouped.setdefault(requested_model, {})
        if architecture in model_group:
            raise ValueError(
                f"Niejednoznaczna para {requested_model}: więcej niż jeden "
                f"wariant {architecture}"
            )
        model_group[architecture] = row

    result: list[dict[str, Any]] = []
    for requested_model, architectures in grouped.items():
        direct = architectures.get("Direct")
        crew = architectures.get("CrewAI")
        if direct is None or crew is None:
            continue
        direct_id = str(direct.get("variant_id"))
        crew_id = str(crew.get("variant_id"))
        pair = _find_pairwise(pairwise_rows, direct_id, crew_id)
        direct_f1 = as_float(direct.get("f1"))
        crew_f1 = as_float(crew.get("f1"))
        direct_fpr = as_float(direct.get("false_positive_rate"))
        crew_fpr = as_float(crew.get("false_positive_rate"))
        direct_cost = as_float(direct.get("observed_cost_usd_per_message"))
        crew_cost = as_float(crew.get("observed_cost_usd_per_message"))
        direct_latency = as_float(direct.get("latency_median_ms"))
        crew_latency = as_float(crew.get("latency_median_ms"))
        result.append(
            {
                "requested_model": requested_model,
                "model": model_label(direct),
                "direct_variant": direct_id,
                "crewai_variant": crew_id,
                "direct_f1": direct_f1,
                "crewai_f1": crew_f1,
                "delta_f1": (
                    crew_f1 - direct_f1
                    if crew_f1 is not None and direct_f1 is not None
                    else None
                ),
                "direct_fpr": direct_fpr,
                "crewai_fpr": crew_fpr,
                "delta_fpr": (
                    crew_fpr - direct_fpr
                    if crew_fpr is not None and direct_fpr is not None
                    else None
                ),
                "cost_ratio": _ratio(crew_cost, direct_cost),
                "latency_ratio": _ratio(crew_latency, direct_latency),
                "exact_action_agreement_rate": (
                    as_float(pair.get("exact_action_agreement_rate")) if pair else None
                ),
                "binary_prediction_agreement_rate": (
                    as_float(pair.get("binary_prediction_agreement_rate"))
                    if pair
                    else None
                ),
                "scope": comparison_scope(direct, crew),
            }
        )
    return result


def case_outcome(row: Mapping[str, Any]) -> str:
    if as_bool(row.get("technical_failure")):
        return "TECH"
    cell = str(row.get("confusion_cell") or "").upper()
    return cell if cell in {"TP", "FP", "TN", "FN"} else "OTHER"
