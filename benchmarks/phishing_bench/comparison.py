from __future__ import annotations

import csv
import io
import json
import math
import re
import statistics
from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any

from .contracts import ContractError
from .io_utils import (
    atomic_write_json,
    atomic_write_text,
    canonical_json,
    ensure_private_directory,
    read_json,
    read_jsonl,
    sha256_file,
    sha256_text,
    utc_now,
)
from .quality_scoring import (
    NON_TECHNICAL_STATUSES,
    POSITIVE_ACTIONS,
    QUALITY_LABEL_KEYS,
    QUALITY_SCORING_PROFILE,
    _validate_scoring_bundle,
    _validate_quality_labels,
)
from .scoring import (
    TOKEN_CAP_ADJUSTED_COMPARISON_TYPE,
    _execution_observability,
    _load_results,
    _token_cap_adjustment,
    _validate_run_integrity,
)


VARIANT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SCORING_RECORD_KEYS = {
    "status",
    "verdict",
    "recorded_action",
    "predicted_action",
    "predicted_positive",
    "confusion_cell",
    "technical_failure",
    "technical_failure_action_applied",
    "golden_action_match",
    "action_mapping_valid",
    "security_probe_allow",
}
COMPARISON_DISCLAIMER = (
    "Porównanie ma charakter opisowy: n=30, dane syntetyczne i "
    "challenge-enriched. Nie dowodzi przewagi modelu, frameworka ani gotowości "
    "produkcyjnej. Cross-provider Direct obejmuje model oraz natywny protokół "
    "providera; różne prompty lub architektury oznaczają porównanie całych "
    "system bundles, a nie izolowanego wpływu jednego komponentu."
)


@dataclass(frozen=True)
class LoadedRun:
    variant_id: str
    run_dir: Path
    manifest: dict[str, Any]
    metrics: dict[str, Any]
    results: list[dict[str, Any]]
    scored: list[dict[str, Any]]
    labels: list[dict[str, Any]]


def parse_named_run(value: str) -> tuple[str, Path]:
    variant_id, separator, raw_path = value.partition("=")
    variant_id = variant_id.strip()
    raw_path = raw_path.strip()
    if not separator or not VARIANT_ID_PATTERN.fullmatch(variant_id) or not raw_path:
        raise argparse_error(
            "--run wymaga formatu NAZWA=/pełna/lub/względna/ścieżka; "
            "NAZWA może zawierać litery, cyfry, kropkę, _ i -"
        )
    return variant_id, Path(raw_path).expanduser().resolve()


def argparse_error(message: str) -> ValueError:
    """Small indirection so argparse can render a concise custom-type error."""

    return ValueError(message)


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{name} must be an object")
    return value


def _require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{name} must be a non-empty string")
    return value


def _ratio(numerator: int | float, denominator: int | float) -> float | None:
    if not denominator:
        return None
    return round(float(numerator) / float(denominator), 6)


def _metric_value(metrics: dict[str, Any], name: str) -> float | None:
    classification = metrics.get("classification_metrics")
    if not isinstance(classification, dict):
        raise ContractError("classification_metrics must be an object")
    metric = classification.get(name)
    if not isinstance(metric, dict):
        raise ContractError(f"classification metric {name} is missing")
    value = metric.get("value")
    if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
        raise ContractError(f"classification metric {name} has an invalid value")
    return float(value) if value is not None else None


def _canonical_labels(scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if any(
        not isinstance(record, dict)
        or set(record) != QUALITY_LABEL_KEYS | SCORING_RECORD_KEYS
        for record in scored
    ):
        raise ContractError("scored result fields do not match binary_quality_v1")
    labels = [{key: record[key] for key in QUALITY_LABEL_KEYS} for record in scored]
    _validate_quality_labels(labels)
    return labels


def _validate_metrics_against_records(
    *,
    manifest: dict[str, Any],
    metrics: dict[str, Any],
    results: list[dict[str, Any]],
    scored: list[dict[str, Any]],
    labels: list[dict[str, Any]],
    labels_sha256: str,
    run_dir: Path,
) -> None:
    run_id = _require_string(manifest.get("run_id"), "manifest run_id")
    campaign_id = _require_string(manifest.get("campaign_id"), "manifest campaign_id")
    if metrics.get("schema_version") != "1.0":
        raise ContractError("comparison supports metrics schema_version 1.0 only")
    if metrics.get("scoring_profile") != QUALITY_SCORING_PROFILE:
        raise ContractError("comparison requires binary_quality_v1 scoring")
    if metrics.get("run_id") != run_id or metrics.get("campaign_id") != campaign_id:
        raise ContractError("scoring identity differs from the frozen run manifest")
    if metrics.get("stage") != manifest.get("stage"):
        raise ContractError("scoring stage differs from the frozen run manifest")
    if metrics.get("comparative_conclusion") != "INCONCLUSIVE":
        raise ContractError("pilot scoring must keep comparative_conclusion INCONCLUSIVE")

    metrics_hashes = _require_mapping(metrics.get("hashes"), "metrics hashes")
    results_hash = sha256_file(run_dir / "results.jsonl")
    if metrics_hashes.get("results_sha256") != results_hash:
        raise ContractError("scoring results hash differs from the closed run artifact")
    if (
        metrics_hashes.get("labels_sha256") != labels_sha256
        or metrics_hashes.get("scoring_manifest_labels_sha256") != labels_sha256
    ):
        raise ContractError("scored label projection does not match the frozen labels hash")

    results_by_id = {record.get("sample_id"): record for record in results}
    if len(results_by_id) != len(results):
        raise ContractError("raw ResultRecords contain duplicate sample_id values")

    confusion: Counter[str] = Counter()
    technical_total = 0
    golden_matches = 0
    for record, label in zip(scored, labels, strict=True):
        raw = results_by_id.get(label["sample_id"])
        if raw is None:
            expected_status = "missing_result"
            expected_recorded_action = None
            expected_verdict = None
            expected_technical = True
        else:
            expected_status = raw.get("status")
            expected_recorded_action = raw.get("action")
            expected_verdict = raw.get("verdict")
            expected_technical = expected_status not in NON_TECHNICAL_STATUSES
        if (
            record.get("status") != expected_status
            or record.get("recorded_action") != expected_recorded_action
            or record.get("verdict") != expected_verdict
            or record.get("technical_failure") is not expected_technical
        ):
            raise ContractError("scored result does not reconcile with its raw ResultRecord")

        technical_action = metrics.get("confusion_matrix", {}).get(
            "technical_failures_use_action"
        )
        expected_action = technical_action if expected_technical else expected_recorded_action
        expected_positive = expected_action in POSITIVE_ACTIONS
        expected_cell = (
            "tp"
            if label["class_label"] == "malicious" and expected_positive
            else "fn"
            if label["class_label"] == "malicious"
            else "fp"
            if expected_positive
            else "tn"
        )
        expected_golden = expected_action in label["acceptable_actions"]
        expected_probe_allow = bool(label["security_probe"] and expected_action == "allow")
        if (
            record.get("predicted_action") != expected_action
            or record.get("predicted_positive") is not expected_positive
            or record.get("confusion_cell") != expected_cell
            or record.get("golden_action_match") is not expected_golden
            or record.get("security_probe_allow") is not expected_probe_allow
        ):
            raise ContractError("scored prediction does not reconcile with raw action and label")
        confusion[expected_cell] += 1
        technical_total += int(expected_technical)
        golden_matches += int(expected_golden)

    matrix = _require_mapping(metrics.get("confusion_matrix"), "confusion matrix")
    expected_matrix = {key: confusion[key] for key in ("tp", "fp", "tn", "fn")}
    if any(matrix.get(key) != value for key, value in expected_matrix.items()):
        raise ContractError("confusion matrix differs from scored per-case outcomes")
    if matrix.get("total") != len(scored):
        raise ContractError("confusion matrix total differs from scored records")
    positive_actions = matrix.get("positive_actions")
    if not isinstance(positive_actions, list) or set(positive_actions) != POSITIVE_ACTIONS:
        raise ContractError("positive action semantics differ from binary_quality_v1")

    tp, fp, tn, fn = (confusion[key] for key in ("tp", "fp", "tn", "fn"))
    expected_metrics = {
        "precision": _ratio(tp, tp + fp),
        "recall": _ratio(tp, tp + fn),
        "f1": _ratio(2 * tp, 2 * tp + fp + fn),
        "false_positive_rate": _ratio(fp, fp + tn),
        "false_negative_rate": _ratio(fn, fn + tp),
        "specificity": _ratio(tn, tn + fp),
    }
    recall_raw = tp / (tp + fn) if tp + fn else None
    specificity_raw = tn / (tn + fp) if tn + fp else None
    expected_metrics["balanced_accuracy"] = (
        round((recall_raw + specificity_raw) / 2, 6)
        if recall_raw is not None and specificity_raw is not None
        else None
    )
    for name, expected in expected_metrics.items():
        if _metric_value(metrics, name) != expected:
            raise ContractError(f"classification metric {name} differs from per-case outcomes")

    records_metrics = _require_mapping(metrics.get("records"), "record metrics")
    if (
        records_metrics.get("expected") != len(scored)
        or records_metrics.get("received") != len(results)
        or records_metrics.get("missing") != len(scored) - len(results)
        or records_metrics.get("technical_failures") != technical_total
    ):
        raise ContractError("record counters differ from scored/raw records")
    golden = _require_mapping(
        metrics.get("golden_acceptable_actions"), "golden action metrics"
    )
    if golden.get("system_action_matches") != golden_matches:
        raise ContractError("golden action counter differs from scored records")

    usage_totals = {
        key: sum(int(result.get("usage", {}).get(key, 0)) for result in results)
        for key in (
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "total_tokens",
        )
    }
    if metrics.get("usage") != usage_totals:
        raise ContractError("usage totals differ from raw ResultRecords")
    observed_cost = round(
        sum(float(result.get("observed_cost_usd", 0)) for result in results), 10
    )
    cost_metrics = _require_mapping(metrics.get("cost"), "cost metrics")
    if cost_metrics.get("observed_usd") != observed_cost:
        raise ContractError("observed cost differs from raw ResultRecords")
    outbound = sum(int(result.get("outbound_attempts", 0)) for result in results)
    attempt_metrics = _require_mapping(metrics.get("attempts"), "attempt metrics")
    if attempt_metrics.get("outbound") != outbound:
        raise ContractError("outbound attempt total differs from raw ResultRecords")
    observability = _execution_observability(
        results,
        expected_workflows=len(scored),
        attempt_events=read_jsonl(run_dir / "attempts.jsonl"),
    )
    for key, expected in observability.items():
        if key in attempt_metrics and attempt_metrics[key] != expected:
            raise ContractError(
                f"{key} differs from raw ResultRecords and planned samples"
            )
    if (
        "workflows" in attempt_metrics
        and "started_workflows" in attempt_metrics
        and attempt_metrics["workflows"] != observability["started_workflows"]
    ):
        raise ContractError("workflow total differs from started workflow count")
    ledger = _require_mapping(
        read_json(run_dir / "budget_ledger.json"), "budget ledger"
    )
    ledger_reservation = ledger.get("reserved_or_observed_cost_usd")
    if (
        "ledger_reserved_or_observed_usd" in cost_metrics
        and cost_metrics["ledger_reserved_or_observed_usd"] != ledger_reservation
    ):
        raise ContractError("ledger cost reservation differs from scored metrics")

    successful_latencies = [
        float(result["latency_ms"])
        for result in results
        if result.get("status") == "success"
        and isinstance(result.get("latency_ms"), (int, float))
        and not isinstance(result.get("latency_ms"), bool)
    ]
    expected_median = (
        round(statistics.median(successful_latencies), 3)
        if successful_latencies
        else None
    )
    latency = _require_mapping(metrics.get("latency_ms"), "latency metrics")
    if (
        latency.get("status_success_count") != len(successful_latencies)
        or latency.get("median") != expected_median
    ):
        raise ContractError("latency summary differs from raw ResultRecords")


def _load_run(
    variant_id: str,
    run_dir: Path,
    labels: list[dict[str, Any]],
    labels_path: Path,
) -> LoadedRun:
    run_dir = run_dir.resolve()
    manifest = _require_mapping(
        read_json(run_dir / "run_manifest.json"), "run manifest"
    )
    if manifest.get("status") not in {
        "completed",
        "completed_with_failures",
    } or not isinstance(manifest.get("finished_at"), str):
        raise ContractError(
            "comparison requires a completed or completed-with-failures run manifest"
        )
    results = _load_results(run_dir)
    _validate_run_integrity(manifest, results, run_dir)
    _validate_scoring_bundle(
        labels=labels,
        labels_path=labels_path,
        manifest=manifest,
    )
    scoring_dir = run_dir / "scoring"
    metrics = _require_mapping(read_json(scoring_dir / "metrics.json"), "metrics")
    try:
        scored = read_jsonl(scoring_dir / "scored_results.jsonl")
    except ValueError as exc:
        raise ContractError(str(exc)) from exc
    projected_labels = _canonical_labels(scored)
    projected_by_id = {label["sample_id"]: label for label in projected_labels}
    scored_by_id = {record["sample_id"]: record for record in scored}
    expected_ids = {label["sample_id"] for label in labels}
    if (
        len(projected_by_id) != len(projected_labels)
        or len(scored_by_id) != len(scored)
        or set(projected_by_id) != expected_ids
        or any(projected_by_id[label["sample_id"]] != label for label in labels)
    ):
        raise ContractError("scored labels differ from the trusted scoring bundle")
    scored = [scored_by_id[label["sample_id"]] for label in labels]
    result_ids = {result.get("sample_id") for result in results}
    if len(result_ids) != len(results) or result_ids != expected_ids:
        raise ContractError("comparison requires one terminal ResultRecord per label")
    _validate_metrics_against_records(
        manifest=manifest,
        metrics=metrics,
        results=results,
        scored=scored,
        labels=labels,
        labels_sha256=sha256_file(labels_path),
        run_dir=run_dir,
    )
    return LoadedRun(
        variant_id=variant_id,
        run_dir=run_dir,
        manifest=manifest,
        metrics=metrics,
        results=results,
        scored=scored,
        labels=labels,
    )


def _compatibility(runs: list[LoadedRun]) -> dict[str, Any]:
    baseline = runs[0]

    def frozen(run: LoadedRun) -> dict[str, Any]:
        readiness_hashes = run.manifest.get("readiness", {}).get("hashes", {})
        matrix = run.metrics.get("confusion_matrix", {})
        return {
            "stage": run.metrics.get("stage"),
            "scoring_profile": run.metrics.get("scoring_profile"),
            "dataset_sha256": readiness_hashes.get("dataset_sha256"),
            "dataset_manifest_sha256": readiness_hashes.get(
                "dataset_manifest_sha256"
            ),
            "labels_sha256": run.metrics.get("hashes", {}).get("labels_sha256"),
            "decision_policy_sha256": run.metrics.get("hashes", {}).get(
                "decision_policy_sha256"
            ),
            "response_schema_sha256": readiness_hashes.get(
                "response_schema_sha256"
            ),
            "positive_actions": sorted(matrix.get("positive_actions", [])),
            "positive_class": matrix.get("positive_class"),
            "negative_action": matrix.get("negative_action"),
            "technical_failure_action": matrix.get(
                "technical_failures_use_action"
            ),
            "technical_failures_in_denominators": matrix.get(
                "technical_failures_in_denominators"
            ),
            "sample_count": len(run.scored),
            "sample_label_projection": canonical_json(run.labels),
            "sample_input_hash_projection": canonical_json(
                {
                    result["sample_id"]: result.get("hashes", {}).get(
                        "input_sha256"
                    )
                    for result in run.results
                }
            ),
        }

    baseline_frozen = frozen(baseline)
    for run in runs[1:]:
        candidate = frozen(run)
        mismatches = [
            key for key in baseline_frozen if candidate.get(key) != baseline_frozen[key]
        ]
        if mismatches:
            raise ContractError(
                f"variant {run.variant_id} is not paired-comparable with "
                f"{baseline.variant_id}: {', '.join(mismatches)}"
            )

    runtime_configs = [run.manifest.get("runtime_config", {}) for run in runs]
    prompts = [
        run.manifest.get("readiness", {}).get("hashes", {}).get("prompt_sha256")
        for run in runs
    ]
    adapters = [config.get("adapter") for config in runtime_configs]
    architectures = [
        "crew"
        if config.get("adapter") == "crewai_sequential_offline"
        else "direct"
        for config in runtime_configs
    ]
    models = [config.get("requested_model") for config in runtime_configs]
    providers = [config.get("provider") for config in runtime_configs]
    request_profiles = [
        config.get("request_profile")
        or (
            "crewai_sequential_offline_v1"
            if config.get("adapter") == "crewai_sequential_offline"
            else "chat_completions_legacy_v1"
        )
        for config in runtime_configs
    ]
    reasoning_efforts = [config.get("reasoning_effort") for config in runtime_configs]
    max_output_tokens = [config.get("max_output_tokens") for config in runtime_configs]
    prompt_same = len(set(prompts)) == 1
    adapter_same = len(set(adapters)) == 1
    architecture_same = len(set(architectures)) == 1
    model_same = len(set(models)) == 1
    provider_same = len(set(providers)) == 1
    disclosed_cross_api_delta = any(
        isinstance(config.get("system_bundle_delta"), dict)
        and config["system_bundle_delta"].get("comparison_name")
        == "cross_api_system_bundle_delta"
        for config in runtime_configs
    )
    token_cap_adjustments = [
        {"variant_id": run.variant_id, **adjustment}
        for run, config in zip(runs, runtime_configs, strict=True)
        if (adjustment := _token_cap_adjustment(config)) is not None
    ]
    same_max_output_tokens = len(set(max_output_tokens)) == 1
    comparison_type = (
        "model_or_provider_delta"
        if prompt_same
        and architecture_same
        and same_max_output_tokens
        and (
            not provider_same
            or (adapter_same and not model_same)
        )
        else "replication"
        if (
            prompt_same
            and adapter_same
            and model_same
            and provider_same
            and same_max_output_tokens
        )
        else TOKEN_CAP_ADJUSTED_COMPARISON_TYPE
        if token_cap_adjustments
        and model_same
        and provider_same
        and not same_max_output_tokens
        else "cross_api_system_bundle_delta"
        if disclosed_cross_api_delta
        and model_same
        and provider_same
        and not architecture_same
        else "system_bundle_delta"
    )
    public_frozen = dict(baseline_frozen)
    public_frozen.pop("sample_label_projection")
    public_frozen.pop("sample_input_hash_projection")
    return {
        "paired": True,
        "baseline_variant": baseline.variant_id,
        "comparison_type": comparison_type,
        "same_prompt": prompt_same,
        "same_adapter": adapter_same,
        "same_architecture": architecture_same,
        "same_model": model_same,
        "same_provider": provider_same,
        "same_request_profile": len(set(request_profiles)) == 1,
        "request_profiles": request_profiles,
        "reasoning_efforts": reasoning_efforts,
        "same_max_output_tokens": same_max_output_tokens,
        "max_output_tokens": max_output_tokens,
        "token_cap_adjustments": token_cap_adjustments,
        "frozen_invariants": public_frozen,
    }


def _resolved_models(results: list[dict[str, Any]]) -> str:
    values = sorted(
        {
            str(result["resolved_model"])
            for result in results
            if isinstance(result.get("resolved_model"), str)
            and result["resolved_model"]
        }
    )
    return ",".join(values)


def _run_row(run: LoadedRun) -> dict[str, Any]:
    metrics = run.metrics
    manifest = run.manifest
    config = _require_mapping(manifest.get("runtime_config"), "runtime_config")
    matrix = _require_mapping(metrics.get("confusion_matrix"), "confusion matrix")
    dataset = _require_mapping(metrics.get("dataset"), "dataset metrics")
    attempts = _require_mapping(metrics.get("attempts"), "attempt metrics")
    usage = _require_mapping(metrics.get("usage"), "usage metrics")
    cost = _require_mapping(metrics.get("cost"), "cost metrics")
    latency = _require_mapping(metrics.get("latency_ms"), "latency metrics")
    failures = _require_mapping(metrics.get("failures"), "failure metrics")
    records = _require_mapping(metrics.get("records"), "record metrics")
    golden = _require_mapping(
        metrics.get("golden_acceptable_actions"), "golden action metrics"
    )
    git = manifest.get("git", {})
    summary = manifest.get("summary", {})
    schema_valid_count = sum(
        int(result.get("response_schema_valid") is True) for result in run.results
    )
    observability = _execution_observability(
        run.results,
        expected_workflows=len(run.scored),
        attempt_events=read_jsonl(run.run_dir / "attempts.jsonl"),
    )
    ledger = read_json(run.run_dir / "budget_ledger.json")
    return {
        "variant_id": run.variant_id,
        "run_id": manifest["run_id"],
        "campaign_id": manifest["campaign_id"],
        "provider": config.get("provider"),
        "adapter": config.get("adapter"),
        "architecture": "crew"
        if config.get("adapter") == "crewai_sequential_offline"
        else "direct",
        "evaluation_profile": config.get("evaluation_profile"),
        "evaluation_track": metrics.get("evaluation_track")
        or config.get("evaluation_profile"),
        "config_id": config.get("config_id"),
        "requested_model": config.get("requested_model"),
        "request_profile": config.get("request_profile")
        or (
            "crewai_sequential_offline_v1"
            if config.get("adapter") == "crewai_sequential_offline"
            else "chat_completions_legacy_v1"
        ),
        "reasoning_effort": config.get("reasoning_effort"),
        "max_output_tokens": config.get("max_output_tokens"),
        "resolved_models": _resolved_models(run.results),
        "sample_count": dataset.get("sample_count"),
        "malicious_count": dataset.get("class_counts", {}).get("malicious"),
        "benign_count": dataset.get("class_counts", {}).get("benign"),
        "success_count": records.get("status_counts", {}).get("success", 0),
        "tp": matrix.get("tp"),
        "fp": matrix.get("fp"),
        "tn": matrix.get("tn"),
        "fn": matrix.get("fn"),
        "accuracy": _ratio(
            int(matrix.get("tp", 0)) + int(matrix.get("tn", 0)),
            int(matrix.get("total", 0)),
        ),
        "precision": _metric_value(metrics, "precision"),
        "recall": _metric_value(metrics, "recall"),
        "f1": _metric_value(metrics, "f1"),
        "false_positive_rate": _metric_value(metrics, "false_positive_rate"),
        "false_negative_rate": _metric_value(metrics, "false_negative_rate"),
        "specificity": _metric_value(metrics, "specificity"),
        "balanced_accuracy": _metric_value(metrics, "balanced_accuracy"),
        "schema_valid_count": schema_valid_count,
        "technical_failures": failures.get("technical_total"),
        "critical_security_events": failures.get("critical_security_events"),
        "security_probe_allow": failures.get("security_probe_allow"),
        "golden_action_matches": golden.get("system_action_matches"),
        "golden_action_match_rate": _ratio(
            int(golden.get("system_action_matches", 0)),
            int(matrix.get("total", 0)),
        ),
        "outbound_calls": attempts.get("outbound"),
        "retries": attempts.get("retries"),
        "cost_unknown_attempts": attempts.get("cost_unknown_attempts"),
        "workflows": attempts.get(
            "started_workflows", observability["started_workflows"]
        ),
        "planned_workflows": attempts.get(
            "planned_workflows", observability["planned_workflows"]
        ),
        "started_workflows": attempts.get(
            "started_workflows", observability["started_workflows"]
        ),
        "not_attempted": attempts.get(
            "not_attempted", observability["not_attempted"]
        ),
        "provider_failures": attempts.get(
            "provider_failures", observability["provider_failures"]
        ),
        "input_tokens": usage.get("input_tokens"),
        "cached_input_tokens": usage.get("cached_input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "reasoning_tokens": usage.get("reasoning_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "observed_cost_usd": cost.get("observed_usd"),
        "ledger_reserved_or_observed_cost_usd": cost.get(
            "ledger_reserved_or_observed_usd",
            ledger.get("reserved_or_observed_cost_usd"),
        ),
        "observed_cost_usd_per_message": cost.get("observed_usd_per_message"),
        "latency_min_ms": latency.get("min"),
        "latency_median_ms": latency.get("median"),
        "latency_iqr_ms": latency.get("iqr"),
        "latency_max_ms": latency.get("max"),
        "run_elapsed_seconds": summary.get("elapsed_seconds"),
        "campaign_status": metrics.get("campaign_status"),
        "comparative_conclusion": metrics.get("comparative_conclusion"),
        "git_commit": git.get("commit"),
        "git_dirty": git.get("dirty"),
    }


def _case_rows(run: LoadedRun) -> list[dict[str, Any]]:
    config = run.manifest["runtime_config"]
    raw_by_id = {result["sample_id"]: result for result in run.results}
    rows: list[dict[str, Any]] = []
    for scored in run.scored:
        raw = raw_by_id.get(scored["sample_id"], {})
        usage = raw.get("usage", {})
        rows.append(
            {
                "variant_id": run.variant_id,
                "run_id": run.manifest["run_id"],
                "campaign_id": run.manifest["campaign_id"],
                "provider": config.get("provider"),
                "adapter": config.get("adapter"),
                "requested_model": config.get("requested_model"),
                "request_profile": config.get("request_profile")
                or (
                    "crewai_sequential_offline_v1"
                    if config.get("adapter") == "crewai_sequential_offline"
                    else "chat_completions_legacy_v1"
                ),
                "reasoning_effort": config.get("reasoning_effort"),
                "max_output_tokens": config.get("max_output_tokens"),
                "resolved_model": raw.get("resolved_model"),
                "config_id": config.get("config_id"),
                "sample_id": scored.get("sample_id"),
                "case_name": scored.get("case_name"),
                "class_label": scored.get("class_label"),
                "scenario": scored.get("scenario"),
                "difficulty": scored.get("difficulty"),
                "language": scored.get("language"),
                "label_confidence": scored.get("label_confidence"),
                "analysis_cluster_id": scored.get("analysis_cluster_id"),
                "security_probe": scored.get("security_probe"),
                "acceptable_actions_json": json.dumps(
                    scored.get("acceptable_actions", []),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "status": scored.get("status"),
                "verdict": scored.get("verdict"),
                "predicted_action": scored.get("predicted_action"),
                "predicted_positive": scored.get("predicted_positive"),
                "confusion_cell": scored.get("confusion_cell"),
                "binary_correct": scored.get("confusion_cell") in {"tp", "tn"},
                "golden_action_match": scored.get("golden_action_match"),
                "technical_failure": scored.get("technical_failure"),
                "action_mapping_valid": scored.get("action_mapping_valid"),
                "security_probe_allow": scored.get("security_probe_allow"),
                "trust_score": raw.get("trust_score"),
                "confidence": raw.get("confidence"),
                "detected_risk": raw.get("detected_risk"),
                "categories_json": json.dumps(
                    raw.get("categories", []),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "latency_ms": raw.get("latency_ms"),
                "provider_latency_ms": raw.get("provider_latency_ms"),
                "outbound_attempts": raw.get("outbound_attempts", 0),
                "llm_call_count": raw.get("llm_call_count")
                or raw.get("outbound_attempts", 0),
                "input_tokens": usage.get("input_tokens", 0),
                "cached_input_tokens": usage.get("cached_input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "reasoning_tokens": usage.get("reasoning_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
                "observed_cost_usd": raw.get("observed_cost_usd", 0),
                "cost_known": int(raw.get("cost_unknown_attempts", 0)) == 0,
            }
        )
    return rows


def _mcnemar_exact(left_only: int, right_only: int) -> float:
    discordant = left_only + right_only
    if discordant == 0:
        return 1.0
    lower = min(left_only, right_only)
    probability = sum(math.comb(discordant, k) for k in range(lower + 1)) / (
        2**discordant
    )
    return round(min(1.0, 2 * probability), 6)


def _divide(right: float | int | None, left: float | int | None) -> float | None:
    if right is None or left in (None, 0):
        return None
    return round(float(right) / float(left), 6)


def _delta(right: float | int | None, left: float | int | None) -> float | None:
    if right is None or left is None:
        return None
    return round(float(right) - float(left), 6)


def _pairwise_rows(
    runs: list[LoadedRun], run_rows: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for left, right in combinations(runs, 2):
        left_by_id = {record["sample_id"]: record for record in left.scored}
        right_by_id = {record["sample_id"]: record for record in right.scored}
        sample_ids = [record["sample_id"] for record in left.scored]
        action_agreement = 0
        verdict_agreement = 0
        binary_agreement = 0
        both_correct = 0
        left_only_correct = 0
        right_only_correct = 0
        both_wrong = 0
        for sample_id in sample_ids:
            left_case = left_by_id[sample_id]
            right_case = right_by_id[sample_id]
            action_agreement += int(
                left_case["predicted_action"] == right_case["predicted_action"]
            )
            verdict_agreement += int(left_case["verdict"] == right_case["verdict"])
            binary_agreement += int(
                left_case["predicted_positive"] == right_case["predicted_positive"]
            )
            left_correct = left_case["confusion_cell"] in {"tp", "tn"}
            right_correct = right_case["confusion_cell"] in {"tp", "tn"}
            if left_correct and right_correct:
                both_correct += 1
            elif left_correct:
                left_only_correct += 1
            elif right_correct:
                right_only_correct += 1
            else:
                both_wrong += 1
        count = len(sample_ids)
        left_summary = run_rows[left.variant_id]
        right_summary = run_rows[right.variant_id]
        rows.append(
            {
                "left_variant": left.variant_id,
                "right_variant": right.variant_id,
                "sample_count": count,
                "exact_action_agreement_count": action_agreement,
                "exact_action_agreement_rate": _ratio(action_agreement, count),
                "verdict_agreement_count": verdict_agreement,
                "verdict_agreement_rate": _ratio(verdict_agreement, count),
                "binary_prediction_agreement_count": binary_agreement,
                "binary_prediction_agreement_rate": _ratio(binary_agreement, count),
                "both_correct": both_correct,
                "left_only_correct": left_only_correct,
                "right_only_correct": right_only_correct,
                "both_wrong": both_wrong,
                "discordant_total": left_only_correct + right_only_correct,
                "mcnemar_exact_p_descriptive": _mcnemar_exact(
                    left_only_correct, right_only_correct
                ),
                "delta_precision_right_minus_left": _delta(
                    right_summary["precision"], left_summary["precision"]
                ),
                "delta_recall_right_minus_left": _delta(
                    right_summary["recall"], left_summary["recall"]
                ),
                "delta_f1_right_minus_left": _delta(
                    right_summary["f1"], left_summary["f1"]
                ),
                "delta_fpr_right_minus_left": _delta(
                    right_summary["false_positive_rate"],
                    left_summary["false_positive_rate"],
                ),
                "cost_ratio_right_over_left": _divide(
                    right_summary["observed_cost_usd"],
                    left_summary["observed_cost_usd"],
                ),
                "median_latency_ratio_right_over_left": _divide(
                    right_summary["latency_median_ms"],
                    left_summary["latency_median_ms"],
                ),
                "provider_calls_ratio_right_over_left": _divide(
                    right_summary["outbound_calls"],
                    left_summary["outbound_calls"],
                ),
            }
        )
    return rows


def _safe_csv_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if not isinstance(value, str):
        return value
    if value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _csv_payload(rows: list[dict[str, Any]]) -> str:
    if not rows:
        raise ContractError("cannot export an empty CSV")
    columns = list(rows[0])
    if any(list(row) != columns for row in rows):
        raise ContractError("CSV rows have inconsistent columns")
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _safe_csv_cell(value) for key, value in row.items()})
    return stream.getvalue()


def _md(value: Any) -> str:
    if value is None:
        return "—"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _render_report(
    *,
    run_rows: list[dict[str, Any]],
    pairwise_rows: list[dict[str, Any]],
    compatibility: dict[str, Any],
) -> str:
    table_lines = [
        "| Wariant | Adapter | Model | Sukcesy | Błędy techniczne | TP | FP | TN | FN | Precision | Recall | F1 | FPR | Koszt USD | Mediana ms | Status |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in run_rows:
        table_lines.append(
            "| "
            + " | ".join(
                _md(row[key])
                for key in (
                    "variant_id",
                    "adapter",
                    "requested_model",
                    "success_count",
                    "technical_failures",
                    "tp",
                    "fp",
                    "tn",
                    "fn",
                    "precision",
                    "recall",
                    "f1",
                    "false_positive_rate",
                    "observed_cost_usd",
                    "latency_median_ms",
                    "campaign_status",
                )
            )
            + " |"
        )

    pair_lines: list[str] = []
    for row in pairwise_rows:
        pair_lines.append(
            f"- `{row['right_variant']}` względem `{row['left_variant']}`: "
            f"ΔF1={_md(row['delta_f1_right_minus_left'])}, "
            f"ΔFPR={_md(row['delta_fpr_right_minus_left'])}, "
            f"koszt ×{_md(row['cost_ratio_right_over_left'])}, "
            f"mediana latency ×{_md(row['median_latency_ratio_right_over_left'])}; "
            f"poprawne tylko lewy={row['left_only_correct']}, "
            f"tylko prawy={row['right_only_correct']}, "
            f"zgodność akcji={row['exact_action_agreement_count']}/{row['sample_count']}."
        )
    token_cap_note = ""
    adjustments = compatibility.get("token_cap_adjustments", [])
    if adjustments:
        adjustment = adjustments[0] if adjustments else {}
        token_cap_note = (
            "\n\nTo jest token-cap-adjusted system bundle dla ramienia "
            f"`{_md(adjustment.get('variant_id'))}`: "
            f"`max_output_tokens` Direct={_md(adjustment.get('direct_max_output_tokens'))}, "
            f"CrewAI={_md(adjustment.get('crewai_max_output_tokens'))}. "
            "Porównanie nie jest apples-to-apples ani czystą deltą frameworka; "
            "różnice mogą obejmować wpływ odmiennego limitu outputu."
        )
    return (
        "# Porównanie benchmarków phishing classifier\n\n"
        "Status wniosku: `INCONCLUSIVE`\n\n"
        f"Typ porównania: `{compatibility['comparison_type']}`. "
        f"Baseline: `{compatibility['baseline_variant']}`."
        + token_cap_note
        + "\n\n"
        f"Ten sam profil requestu API: "
        f"`{str(compatibility['same_request_profile']).lower()}`; "
        f"profile: `{', '.join(compatibility['request_profiles'])}`.\n\n"
        + "\n".join(table_lines)
        + "\n\n## Różnice sparowane\n\n"
        + "\n".join(pair_lines)
        + "\n\n## Jak używać plików\n\n"
        "- `runs.csv`: jeden wiersz na model/silnik — wykresy F1, FPR, kosztu i latency.\n"
        "- `cases.csv`: format long/tidy — analiza błędów według scenariusza, trudności i klasy.\n"
        "- `pairwise.csv`: zgodność oraz różnice dwóch wariantów na dokładnie tych samych próbkach.\n"
        "- `comparison.json`: pełny eksport maszynowy wraz z hashami źródeł.\n\n"
        "## Ograniczenie interpretacji\n\n"
        f"{COMPARISON_DISCLAIMER} Wartość McNemara jest wyłącznie opisowa i nie "
        "zmienia statusu `INCONCLUSIVE`.\n"
    )


def compare_runs(
    *,
    named_run_dirs: list[tuple[str, Path]],
    labels_path: Path,
    output_dir: Path,
    repo_root: Path,
) -> Path:
    if not 2 <= len(named_run_dirs) <= 20:
        raise ContractError("compare requires between 2 and 20 named runs")
    variant_ids = [variant_id for variant_id, _ in named_run_dirs]
    if len(set(variant_ids)) != len(variant_ids):
        raise ContractError("compare variant names must be unique")
    if any(not VARIANT_ID_PATTERN.fullmatch(variant_id) for variant_id in variant_ids):
        raise ContractError("compare variant name has invalid characters")

    resolved_dirs = [path.resolve() for _, path in named_run_dirs]
    if len(set(resolved_dirs)) != len(resolved_dirs):
        raise ContractError("the same run directory cannot be compared twice")

    repo_root = repo_root.resolve()
    labels_path = labels_path.resolve()
    try:
        labels = read_jsonl(labels_path)
    except ValueError as exc:
        raise ContractError(str(exc)) from exc
    _validate_quality_labels(labels)
    output_dir = output_dir.resolve()
    if output_dir in {Path("/").resolve(), Path.home().resolve(), repo_root}:
        raise ContractError("comparison output directory is too broad")
    if any(
        output_dir == run_dir
        or output_dir.is_relative_to(run_dir)
        or run_dir.is_relative_to(output_dir)
        for run_dir in resolved_dirs
    ):
        raise ContractError("comparison output cannot overlap a source run directory")

    runs = [
        _load_run(variant_id, run_dir, labels, labels_path)
        for variant_id, run_dir in zip(variant_ids, resolved_dirs, strict=True)
    ]
    run_ids = [run.manifest["run_id"] for run in runs]
    if len(set(run_ids)) != len(run_ids):
        raise ContractError("compare requires distinct run_id values")
    compatibility = _compatibility(runs)

    run_rows = [_run_row(run) for run in runs]
    run_rows_by_id = {row["variant_id"]: row for row in run_rows}
    case_rows = [row for run in runs for row in _case_rows(run)]
    pairwise_rows = _pairwise_rows(runs, run_rows_by_id)
    runs_csv = _csv_payload(run_rows)
    cases_csv = _csv_payload(case_rows)
    pairwise_csv = _csv_payload(pairwise_rows)
    report = _render_report(
        run_rows=run_rows,
        pairwise_rows=pairwise_rows,
        compatibility=compatibility,
    )

    ensure_private_directory(output_dir)
    atomic_write_text(output_dir / "runs.csv", runs_csv)
    atomic_write_text(output_dir / "cases.csv", cases_csv)
    atomic_write_text(output_dir / "pairwise.csv", pairwise_csv)
    atomic_write_text(output_dir / "report.md", report)

    source_artifacts = {}
    for run in runs:
        source_artifacts[run.variant_id] = {
            "run_dir": str(run.run_dir),
            "run_id": run.manifest["run_id"],
            "run_manifest_sha256": sha256_file(run.run_dir / "run_manifest.json"),
            "results_sha256": sha256_file(run.run_dir / "results.jsonl"),
            "attempts_sha256": sha256_file(run.run_dir / "attempts.jsonl"),
            "budget_ledger_sha256": sha256_file(
                run.run_dir / "budget_ledger.json"
            ),
            "metrics_sha256": sha256_file(run.run_dir / "scoring" / "metrics.json"),
            "scored_results_sha256": sha256_file(
                run.run_dir / "scoring" / "scored_results.jsonl"
            ),
        }
    comparison = {
        "schema_version": "1.0",
        "record_type": "BenchmarkComparison",
        "generated_at": utc_now(),
        "comparison_status": "DESCRIPTIVE_ONLY",
        "comparative_conclusion": "INCONCLUSIVE",
        "eligible_for_ranking": False,
        "disclaimer": COMPARISON_DISCLAIMER,
        "csv_formula_escaping": "apostrophe_prefix_after_leading_whitespace",
        "compatibility": compatibility,
        "runs": run_rows,
        "cases": case_rows,
        "pairwise": pairwise_rows,
        "source_artifacts": source_artifacts,
        "trusted_labels": {
            "path": str(labels_path),
            "sha256": sha256_file(labels_path),
        },
        "export_artifacts": {
            "runs_csv_sha256": sha256_text(runs_csv),
            "cases_csv_sha256": sha256_text(cases_csv),
            "pairwise_csv_sha256": sha256_text(pairwise_csv),
            "report_md_sha256": sha256_text(report),
        },
    }
    atomic_write_json(output_dir / "comparison.json", comparison)
    return output_dir
