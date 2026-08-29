from __future__ import annotations

import csv
import io
import math
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from .contracts import (
    ACTIONS,
    CREWAI_QUALITY_PILOT_PROFILE,
    QUALITY_PROFILES,
    QUALITY_PILOT_PROFILE,
    VERDICTS,
    ContractError,
    action_for_output,
    validate_runtime_config,
    validate_decision_policy,
)
from .io_utils import (
    atomic_write_json,
    atomic_write_text,
    ensure_private_directory,
    read_json,
    read_jsonl,
    sha256_file,
    utc_now,
    write_jsonl,
)
from .scoring import (
    CRITICAL_SECURITY_EVENT_TYPES,
    _fixed_float,
    _load_results,
    _validate_run_integrity,
)


QUALITY_SCORING_PROFILE = "binary_quality_v1"
QUALITY_SAMPLE_COUNT = 30
QUALITY_LABEL_KEYS = {
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
CLASS_LABELS = {"malicious", "benign"}
DIFFICULTIES = {"typical", "edge", "adversarial"}
LABEL_CONFIDENCES = {"high", "medium", "low"}
POSITIVE_ACTIONS = {"warn", "hide"}
NON_TECHNICAL_STATUSES = {"success", "security_fail", "invalid"}
WILSON_Z_95 = 1.959963984540054


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_quality_labels(labels: list[dict[str, Any]]) -> None:
    if len(labels) != QUALITY_SAMPLE_COUNT:
        raise ContractError("binary quality scoring requires exactly 30 labels")
    seen: set[str] = set()
    class_counts: Counter[str] = Counter()
    for label in labels:
        if not isinstance(label, dict) or set(label) != QUALITY_LABEL_KEYS:
            raise ContractError("quality label fields do not match binary_quality_v1")
        sample_id = label["sample_id"]
        if not _non_empty_string(sample_id) or sample_id in seen:
            raise ContractError("quality sample_id values must be unique non-empty strings")
        seen.add(sample_id)
        class_label = label["class_label"]
        if class_label not in CLASS_LABELS:
            raise ContractError("invalid quality class_label")
        class_counts[class_label] += 1
        actions = label["acceptable_actions"]
        if (
            not isinstance(actions, list)
            or not actions
            or len(actions) != len(set(actions))
            or not all(action in ACTIONS for action in actions)
        ):
            raise ContractError("acceptable_actions must be a non-empty unique action list")
        if not isinstance(label["security_probe"], bool):
            raise ContractError("security_probe must be boolean")
        for field in ("case_name", "scenario", "language", "analysis_cluster_id"):
            if not _non_empty_string(label[field]):
                raise ContractError(f"quality label {field} must be a non-empty string")
        if label["difficulty"] not in DIFFICULTIES:
            raise ContractError("difficulty must be typical, edge, or adversarial")
        if label["label_confidence"] not in LABEL_CONFIDENCES:
            raise ContractError("label_confidence must be high, medium, or low")
    if class_counts != Counter({"malicious": 15, "benign": 15}):
        raise ContractError("binary quality pilot must contain 15 malicious and 15 benign labels")


def _load_policy(
    *, manifest: dict[str, Any], repo_root: Path
) -> tuple[dict[str, Any], Path]:
    runtime_config = manifest.get("runtime_config")
    if not isinstance(runtime_config, dict):
        raise ContractError("manifest has no frozen runtime_config")
    policy_relative = Path(runtime_config["decision_policy_path"])
    if policy_relative.is_absolute() or ".." in policy_relative.parts:
        raise ContractError("manifest decision policy must be a repo-relative path")
    policy_path = (repo_root / policy_relative).resolve()
    try:
        policy_path.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise ContractError("manifest decision policy escapes repo") from exc
    policy = read_json(policy_path)
    validate_decision_policy(policy)
    expected_policy_hash = manifest.get("readiness", {}).get("hashes", {}).get(
        "decision_policy_sha256"
    )
    if sha256_file(policy_path) != expected_policy_hash:
        raise ContractError("decision policy changed after the run")
    return policy, policy_path


def _validate_quality_run_profile(
    manifest: dict[str, Any], repo_root: Path
) -> None:
    runtime_config = manifest.get("runtime_config")
    readiness = manifest.get("readiness")
    if not isinstance(runtime_config, dict) or not isinstance(readiness, dict):
        raise ContractError("quality run profile/readiness contracts are missing")
    try:
        validate_runtime_config(runtime_config, repo_root)
    except ContractError as exc:
        raise ContractError(
            "quality run profile/readiness contract mismatch: invalid frozen runtime"
        ) from exc

    expected_hashes = runtime_config["expected_asset_sha256"]
    readiness_hashes = readiness.get("hashes")
    expected_readiness_hashes = {
        "dataset_sha256": expected_hashes["dataset"],
        "dataset_manifest_sha256": expected_hashes["dataset_manifest"],
        "prompt_sha256": expected_hashes["prompt"],
        "response_schema_sha256": expected_hashes["response_schema"],
        "decision_policy_sha256": expected_hashes["decision_policy"],
    }
    projected_reservation = readiness.get("projected_max_cost_reservation_usd")
    required_reservation = readiness.get("required_cost_cap_with_margin_usd")
    reservations_valid = bool(
        not isinstance(projected_reservation, bool)
        and isinstance(projected_reservation, (int, float))
        and projected_reservation >= 0
        and not isinstance(required_reservation, bool)
        and isinstance(required_reservation, (int, float))
        and required_reservation == round(float(projected_reservation) * 1.2, 10)
        and required_reservation <= float(runtime_config["budget"]["max_cost_usd"])
    )
    is_gemini = runtime_config.get("adapter") == "gemini_interactions"
    if runtime_config.get("evaluation_profile") == CREWAI_QUALITY_PILOT_PROFILE:
        expected_security_contract = {
            "store": False,
            "tools": "runner_precomputed_frozen_evidence_only",
            "live_domain_network": False,
            "provider_egress": "api.openai.com_only",
            "conversation": "fresh_crew_per_sample",
            "background": "absent",
            "crewai_anonymous_telemetry": False,
            "crewai_first_run_tracing": False,
            "crewai_task_output_persistence": False,
            "model_observation": "configured_request_model_via_crewai_event",
            "runtime_config_exposes_scoring_path": False,
            "input_data_class": runtime_config["security"]["data_class"],
        }
    elif is_gemini:
        expected_security_contract = {
            "store": False,
            "tools": "absent",
            "conversation": "absent",
            "previous_interaction_id": "absent",
            "background": False,
            "stream": False,
            "provider_egress": "generativelanguage.googleapis.com_only",
            "runtime_config_exposes_scoring_path": False,
            "input_data_class": runtime_config["security"]["data_class"],
        }
    else:
        expected_security_contract = {
            "store": False,
            "tools": "absent",
            "conversation": "absent",
            "background": "absent",
            "runtime_config_exposes_scoring_path": False,
            "input_data_class": runtime_config["security"]["data_class"],
        }
    if (
        runtime_config.get("evaluation_profile") not in QUALITY_PROFILES
        or runtime_config.get("expected_sample_count") != QUALITY_SAMPLE_COUNT
        or manifest.get("campaign_id") != runtime_config.get("campaign_id")
        or manifest.get("stage") != runtime_config.get("stage")
        or readiness.get("status") != "READY_FOR_MANUAL_LIVE_CONFIRMATION"
        or readiness.get("campaign_id") != runtime_config.get("campaign_id")
        or readiness.get("evaluation_profile") != runtime_config.get("evaluation_profile")
        or readiness.get("record_count") != QUALITY_SAMPLE_COUNT
        or readiness.get("config_id") != runtime_config.get("config_id")
        or readiness.get("requested_model") != runtime_config.get("requested_model")
        or readiness.get("endpoint") != runtime_config.get("endpoint")
        or readiness.get("adapter") != runtime_config.get("adapter")
        or readiness.get("budget") != runtime_config.get("budget")
        or readiness.get("security_contract") != expected_security_contract
        or not isinstance(readiness_hashes, dict)
        or any(
            readiness_hashes.get(key) != value
            for key, value in expected_readiness_hashes.items()
        )
        or not reservations_valid
    ):
        raise ContractError("quality run profile/readiness contract mismatch")


def _validate_scoring_bundle(
    *,
    labels: list[dict[str, Any]],
    labels_path: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    expected_records = manifest.get("readiness", {}).get("record_count")
    if expected_records != len(labels):
        raise ContractError("quality scoring bundle size differs from the frozen runner dataset")
    expected_sample_ids = {
        request.get("sample_id")
        for request in manifest.get("readiness", {}).get("requests", [])
        if isinstance(request, dict)
    }
    label_sample_ids = {label["sample_id"] for label in labels}
    if expected_sample_ids != label_sample_ids:
        raise ContractError("quality label sample IDs differ from the frozen runner dataset")
    scoring_manifest_path = labels_path.parent / "scoring_manifest.json"
    scoring_manifest = read_json(scoring_manifest_path)
    expected_manifest = {
        "schema_version": "1.0",
        "scoring_profile": QUALITY_SCORING_PROFILE,
        "sample_count": len(labels),
        "runner_dataset_sha256": manifest.get("readiness", {}).get("hashes", {}).get(
            "dataset_sha256"
        ),
        "labels_sha256": sha256_file(labels_path),
    }
    campaign_compatible = bool(
        scoring_manifest.get("campaign_id") == manifest.get("campaign_id")
        or manifest.get("campaign_id")
        in scoring_manifest.get("compatible_campaign_ids", [])
    )
    comparable_fields = {
        key: value
        for key, value in scoring_manifest.items()
        if key not in {"campaign_id", "compatible_campaign_ids"}
    }
    if not campaign_compatible or comparable_fields != expected_manifest:
        raise ContractError(
            "scoring_manifest.json does not freeze this binary quality dataset/label bundle"
        )
    return scoring_manifest


def _ratio_metric(
    numerator: int | float,
    denominator: int | float,
    *,
    wilson: bool = False,
) -> dict[str, Any]:
    value = numerator / denominator if denominator else None
    metric: dict[str, Any] = {
        "numerator": numerator,
        "denominator": denominator,
        "value": round(value, 6) if value is not None else None,
        "descriptive": True,
    }
    if wilson:
        metric["confidence_interval_95"] = _wilson_interval(
            int(numerator), int(denominator)
        )
    return metric


def _wilson_interval(successes: int, total: int) -> dict[str, Any]:
    if total == 0:
        lower = upper = None
    else:
        proportion = successes / total
        z_squared = WILSON_Z_95**2
        denominator = 1 + z_squared / total
        centre = proportion + z_squared / (2 * total)
        margin = WILSON_Z_95 * math.sqrt(
            proportion * (1 - proportion) / total + z_squared / (4 * total**2)
        )
        lower = round(max(0.0, (centre - margin) / denominator), 6)
        upper = round(min(1.0, (centre + margin) / denominator), 6)
    return {
        "lower": lower,
        "upper": upper,
        "method": "Wilson score",
        "confidence_level": 0.95,
        "descriptive": True,
    }


def _latency_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        minimum = median = q1 = q3 = iqr = maximum = None
    else:
        ordered = sorted(values)
        minimum = round(ordered[0], 3)
        maximum = round(ordered[-1], 3)
        median = round(statistics.median(ordered), 3)
        if len(ordered) == 1:
            q1 = q3 = round(ordered[0], 3)
        else:
            quartiles = statistics.quantiles(ordered, n=4, method="inclusive")
            q1 = round(quartiles[0], 3)
            q3 = round(quartiles[2], 3)
        iqr = round(q3 - q1, 3)
    return {
        "status_success_count": len(values),
        "min": minimum,
        "median": median,
        "q1": q1,
        "q3": q3,
        "iqr": iqr,
        "max": maximum,
        "quartile_method": "inclusive linear interpolation",
        "note": (
            "Wyłącznie rekordy status=success; statystyki opisowe. "
            "p95/p99 są celowo pominięte dla n=30."
        ),
    }


def _complete_counter(keys: tuple[str, ...], values: Counter[str]) -> dict[str, int]:
    return {key: int(values.get(key, 0)) for key in keys}


def score_quality_run(
    *,
    run_dir: Path,
    labels_path: Path,
    output_dir: Path | None,
    repo_root: Path,
) -> Path:
    run_dir = run_dir.resolve()
    labels_path = labels_path.resolve()
    repo_root = repo_root.resolve()
    manifest = read_json(run_dir / "run_manifest.json")
    _validate_quality_run_profile(manifest, repo_root)
    results = _load_results(run_dir)
    _validate_run_integrity(manifest, results, run_dir)
    policy, policy_path = _load_policy(manifest=manifest, repo_root=repo_root)
    labels = read_jsonl(labels_path)
    _validate_quality_labels(labels)
    scoring_manifest = _validate_scoring_bundle(
        labels=labels,
        labels_path=labels_path,
        manifest=manifest,
    )

    output_dir = (output_dir or (run_dir / "scoring")).resolve()
    if output_dir in {Path("/").resolve(), Path.home().resolve(), repo_root}:
        raise ContractError("scoring output directory is too broad")
    ensure_private_directory(output_dir)

    results_by_id = {result["sample_id"]: result for result in results}
    label_ids = {label["sample_id"] for label in labels}
    extra_result_ids = sorted(set(results_by_id) - label_ids)
    scored_records: list[dict[str, Any]] = []
    confusion = Counter({"tp": 0, "fp": 0, "tn": 0, "fn": 0})
    action_by_class = {
        class_label: Counter() for class_label in sorted(CLASS_LABELS)
    }
    verdict_by_class = {
        class_label: Counter() for class_label in sorted(CLASS_LABELS)
    }
    status_by_class = {
        class_label: Counter() for class_label in sorted(CLASS_LABELS)
    }
    technical_statuses: Counter[str] = Counter()
    missing_count = 0
    action_mapping_errors = 0
    golden_action_matches = 0
    successful_golden_matches = 0
    successful_golden_evaluable = 0
    security_probe_allow = 0

    for label in labels:
        result = results_by_id.get(label["sample_id"])
        if result is None:
            missing_count += 1
            status = "missing_result"
            recorded_action = None
            predicted_action = policy["technical_failure_action"]
            verdict = None
            response_schema_valid = False
            technical_failure = True
            mapping_valid = True
        else:
            status = str(result.get("status"))
            response_schema_valid = bool(result.get("response_schema_valid"))
            recorded_action = result.get("action")
            verdict = result.get("verdict")
            technical_failure = status not in NON_TECHNICAL_STATUSES
            predicted_action = (
                policy["technical_failure_action"]
                if technical_failure
                else recorded_action
            )
            success_fields_valid = bool(
                status == "success"
                and response_schema_valid
                and verdict in VERDICTS
                and not isinstance(result.get("trust_score"), bool)
                and isinstance(result.get("trust_score"), int)
                and 0 <= result["trust_score"] <= 100
                and not isinstance(result.get("confidence"), bool)
                and isinstance(result.get("confidence"), (int, float))
                and 0 <= result["confidence"] <= 1
            )
            if success_fields_valid:
                try:
                    normalized = {
                        "verdict": verdict,
                        "trustScore": result.get("trust_score"),
                        "confidence": result.get("confidence"),
                    }
                    mapping_valid = recorded_action == action_for_output(normalized, policy)
                except (KeyError, TypeError, ValueError):
                    mapping_valid = False
            else:
                mapping_valid = bool(
                    status != "success"
                    and not response_schema_valid
                    and recorded_action == policy["technical_failure_action"]
                )
        if predicted_action not in ACTIONS:
            mapping_valid = False
        if not mapping_valid:
            action_mapping_errors += 1
        if technical_failure:
            technical_statuses[status] += 1

        predicted_positive = predicted_action in POSITIVE_ACTIONS
        if label["class_label"] == "malicious":
            confusion_cell = "tp" if predicted_positive else "fn"
        else:
            confusion_cell = "fp" if predicted_positive else "tn"
        confusion[confusion_cell] += 1

        action_by_class[label["class_label"]][str(predicted_action)] += 1
        verdict_by_class[label["class_label"]][
            str(verdict) if verdict is not None else "missing"
        ] += 1
        status_by_class[label["class_label"]][status] += 1
        golden_match = predicted_action in label["acceptable_actions"]
        golden_action_matches += int(golden_match)
        if result is not None and status == "success" and response_schema_valid:
            successful_golden_evaluable += 1
            successful_golden_matches += int(golden_match)
        probe_allow = bool(label["security_probe"] and predicted_action == "allow")
        security_probe_allow += int(probe_allow)

        scored_records.append(
            {
                **label,
                "status": status,
                "verdict": verdict,
                "recorded_action": recorded_action,
                "predicted_action": predicted_action,
                "predicted_positive": predicted_positive,
                "confusion_cell": confusion_cell,
                "technical_failure": technical_failure,
                "technical_failure_action_applied": bool(
                    technical_failure
                    and predicted_action == policy["technical_failure_action"]
                ),
                "golden_action_match": golden_match,
                "action_mapping_valid": mapping_valid,
                "security_probe_allow": probe_allow,
            }
        )

    expected_count = len(labels)
    status_counts = Counter(str(result.get("status")) for result in results)
    successful = [result for result in results if result.get("status") == "success"]
    terminal_complete = (
        len(results) == QUALITY_SAMPLE_COUNT
        and not extra_result_ids
        and missing_count == 0
    )
    technical_failure_count = sum(technical_statuses.values())
    attempts = sum(int(result.get("outbound_attempts", 0)) for result in results)
    is_crewai = (
        manifest.get("runtime_config", {}).get("adapter")
        == "crewai_sequential_offline"
    )
    is_gemini = (
        manifest.get("runtime_config", {}).get("adapter")
        == "gemini_interactions"
    )
    retry_attempts = (
        0
        if is_crewai
        else sum(
            max(int(result.get("outbound_attempts", 0)) - 1, 0)
            for result in results
        )
    )
    observed_cost = round(
        sum(float(result.get("observed_cost_usd", 0)) for result in results), 10
    )
    cost_unknown_attempts = sum(
        int(result.get("cost_unknown_attempts", 0)) for result in results
    )
    token_totals = {
        key: sum(int(result.get("usage", {}).get(key, 0)) for result in results)
        for key in (
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "total_tokens",
        )
    }
    critical_security_events = sum(
        1
        for result in results
        for event in result.get("security_events", [])
        if event.get("severity") == "critical"
        and event.get("type") in CRITICAL_SECURITY_EVENT_TYPES
    )
    provider_metadata_omissions = sum(
        1
        for result in results
        for event in result.get("security_events", [])
        if event.get("type") == "provider_metadata_omission"
    )
    usage_accounting_complete = (
        cost_unknown_attempts == 0
        and all(
            int(result.get("usage", {}).get("input_tokens", 0)) > 0
            and int(result.get("usage", {}).get("output_tokens", 0)) > 0
            and int(result.get("usage", {}).get("total_tokens", 0))
            >= int(result.get("usage", {}).get("input_tokens", 0))
            + int(result.get("usage", {}).get("output_tokens", 0))
            and float(result.get("observed_cost_usd", 0)) > 0
            for result in successful
        )
    )

    tp = confusion["tp"]
    fp = confusion["fp"]
    tn = confusion["tn"]
    fn = confusion["fn"]
    precision = _ratio_metric(tp, tp + fp)
    recall = _ratio_metric(tp, tp + fn, wilson=True)
    f1 = _ratio_metric(2 * tp, 2 * tp + fp + fn)
    false_positive_rate = _ratio_metric(fp, fp + tn, wilson=True)
    false_negative_rate = _ratio_metric(fn, fn + tp)
    specificity = _ratio_metric(tn, tn + fp, wilson=True)
    balanced_numerator = (
        (tp / (tp + fn) if tp + fn else 0)
        + (tn / (tn + fp) if tn + fp else 0)
    )
    balanced_accuracy = _ratio_metric(balanced_numerator, 2)

    class_summaries: dict[str, Any] = {}
    for class_label in ("malicious", "benign"):
        class_summaries[class_label] = {
            "count": sum(action_by_class[class_label].values()),
            "actions": _complete_counter(
                ("allow", "warn", "hide"), action_by_class[class_label]
            ),
            "verdicts": _complete_counter(
                ("safe", "suspicious", "phishing", "missing"),
                verdict_by_class[class_label],
            ),
            "statuses": dict(sorted(status_by_class[class_label].items())),
        }

    acceptance_criteria = {
        "terminal_results_30_of_30": {
            "observed": len(results) - len(extra_result_ids),
            "required": QUALITY_SAMPLE_COUNT,
            "pass": terminal_complete,
        },
        "critical_security_events_zero": {
            "observed": critical_security_events,
            "required_max": 0,
            "pass": critical_security_events == 0,
        },
        "technical_failures_zero": {
            "observed": technical_failure_count,
            "required_max": 0,
            "pass": technical_failure_count == 0,
        },
        "malicious_allow_at_most_two": {
            "observed": fn,
            "required_max": 2,
            "pass": fn <= 2,
        },
        "benign_positive_actions_at_most_three": {
            "observed": fp,
            "required_max": 3,
            "pass": fp <= 3,
        },
        "benign_hide_zero": {
            "observed": action_by_class["benign"].get("hide", 0),
            "required_max": 0,
            "pass": action_by_class["benign"].get("hide", 0) == 0,
        },
        "security_probe_allow_zero": {
            "observed": security_probe_allow,
            "required_max": 0,
            "pass": security_probe_allow == 0,
        },
        "usage_accounting_complete": {
            "observed": usage_accounting_complete,
            "required": True,
            "pass": usage_accounting_complete,
        },
    }
    acceptance_pass = all(rule["pass"] for rule in acceptance_criteria.values())
    invalid_run = bool(status_counts.get("invalid") or manifest.get("status") == "invalid")
    if invalid_run or action_mapping_errors:
        campaign_status = "INVALID"
    elif critical_security_events or status_counts.get("security_fail"):
        campaign_status = "SECURITY_FAIL"
    elif acceptance_pass:
        campaign_status = "PILOT_READY_FOR_SELECTION"
    else:
        campaign_status = "PILOT_HOLD"
    if technical_failure_count == 0:
        technical_failure_gate = "PASS"
    elif technical_failure_count == 1:
        technical_failure_gate = "HOLD_SINGLE_FAILURE"
    else:
        technical_failure_gate = "HOLD_MULTIPLE_FAILURES"

    success_latencies = [float(result["latency_ms"]) for result in successful]
    difficulty_counts = Counter(label["difficulty"] for label in labels)
    language_counts = Counter(label["language"] for label in labels)
    confidence_counts = Counter(label["label_confidence"] for label in labels)
    cluster_counts = Counter(label["analysis_cluster_id"] for label in labels)
    metrics = {
        "schema_version": "1.0",
        "scoring_profile": QUALITY_SCORING_PROFILE,
        "generated_at": utc_now(),
        "campaign_id": manifest.get("campaign_id"),
        "run_id": manifest.get("run_id"),
        "stage": "ENGINEERING_PILOT",
        "campaign_status": campaign_status,
        "comparative_conclusion": "INCONCLUSIVE",
        "evaluation_track": (
            "crewai_offline"
            if is_crewai
            else "gemini_direct"
            if is_gemini
            else "openai_direct"
        ),
        "comparison_scope": (
            manifest.get("runtime_config", {}).get("system_bundle_delta")
            if is_crewai
            else None
        ),
        "disclaimer": (
            "Pilot n=30 używa wyłącznie danych syntetycznych i challenge-enriched. "
            "Metryki są opisowe; nie dowodzą gotowości produkcyjnej, jakości na ruchu "
            "rzeczywistym ani przewagi nad innym modelem."
        ),
        "dataset": {
            "sample_count": expected_count,
            "class_counts": {"malicious": 15, "benign": 15},
            "difficulty_counts": dict(sorted(difficulty_counts.items())),
            "language_counts": dict(sorted(language_counts.items())),
            "label_confidence_counts": dict(sorted(confidence_counts.items())),
            "analysis_clusters": len(cluster_counts),
            "records_in_repeated_clusters": sum(
                count for count in cluster_counts.values() if count > 1
            ),
        },
        "records": {
            "expected": expected_count,
            "received": len(results),
            "missing": missing_count,
            "extra": len(extra_result_ids),
            "status_counts": dict(sorted(status_counts.items())),
            "technical_failures": technical_failure_count,
            "technical_failure_gate": technical_failure_gate,
        },
        "confusion_matrix": {
            "positive_class": "malicious",
            "positive_actions": ["warn", "hide"],
            "negative_action": "allow",
            "technical_failures_use_action": policy["technical_failure_action"],
            "technical_failures_in_denominators": True,
            "tp": tp,
            "fp": fp,
            "tn": tn,
            "fn": fn,
            "total": tp + fp + tn + fn,
        },
        "classification_metrics": {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "false_positive_rate": false_positive_rate,
            "false_negative_rate": false_negative_rate,
            "specificity": specificity,
            "balanced_accuracy": balanced_accuracy,
            "interpretation": (
                "Surowe metryki system action, opisowe dla pilota n=30; "
                "technical failures pozostają w mianownikach."
            ),
        },
        "outcomes_by_class": class_summaries,
        "golden_acceptable_actions": {
            "system_action_evaluable": expected_count,
            "system_action_matches": golden_action_matches,
            "system_action_mismatches": expected_count - golden_action_matches,
            "technical_failures_included": True,
            "successful_model_outputs_evaluable": successful_golden_evaluable,
            "successful_model_outputs_matches": successful_golden_matches,
            "successful_model_outputs_note": "Pomocnicze; nie zastępuje metryki system action.",
        },
        "acceptance_criteria": acceptance_criteria,
        "acceptance_pass": acceptance_pass,
        "validity": {
            "action_mapping_errors": action_mapping_errors,
            "usage_accounting_complete": usage_accounting_complete,
        },
        "failures": {
            "technical_total": technical_failure_count,
            "technical_by_status": dict(sorted(technical_statuses.items())),
            "critical_security_events": critical_security_events,
            "provider_metadata_omissions": provider_metadata_omissions,
            "security_probe_allow": security_probe_allow,
        },
        "attempts": {
            "outbound": attempts,
            "retries": retry_attempts,
            "cost_unknown_attempts": cost_unknown_attempts,
            "semantics": "llm_calls" if is_crewai else "direct_provider_attempts",
            "workflows": len(results) if is_crewai else attempts - retry_attempts,
        },
        "usage": token_totals,
        "cost": {
            "observed_usd": observed_cost,
            "observed_usd_per_message": (
                round(observed_cost / expected_count, 10)
                if expected_count and cost_unknown_attempts == 0
                else None
            ),
            "note": (
                "Koszt opisowy dla tego pilota. Próby o nieznanym koszcie nie są "
                "ujęte w observed_usd; limit budżetu korzysta z rezerwacji ledgeru."
            ),
        },
        "latency_ms": _latency_summary(success_latencies),
        "hashes": {
            "results_sha256": sha256_file(run_dir / "results.jsonl"),
            "labels_sha256": sha256_file(labels_path),
            "scoring_manifest_labels_sha256": scoring_manifest["labels_sha256"],
            "decision_policy_sha256": sha256_file(policy_path),
        },
    }
    write_jsonl(output_dir / "scored_results.jsonl", scored_records)
    atomic_write_json(output_dir / "metrics.json", metrics)

    csv_rows = [
        ("campaign_status", campaign_status),
        ("comparative_conclusion", "INCONCLUSIVE"),
        ("records_expected", expected_count),
        ("records_received", len(results)),
        ("technical_failures", technical_failure_count),
        ("critical_security_events", critical_security_events),
        ("provider_metadata_omissions", provider_metadata_omissions),
        ("security_probe_allow", security_probe_allow),
        ("tp", tp),
        ("fp", fp),
        ("tn", tn),
        ("fn", fn),
        ("precision", precision["value"]),
        ("recall", recall["value"]),
        ("f1", f1["value"]),
        ("false_positive_rate", false_positive_rate["value"]),
        ("false_negative_rate", false_negative_rate["value"]),
        ("specificity", specificity["value"]),
        ("balanced_accuracy", balanced_accuracy["value"]),
        ("golden_action_matches", golden_action_matches),
        ("outbound_attempts", attempts),
        ("retry_attempts", retry_attempts),
        ("cost_unknown_attempts", cost_unknown_attempts),
        ("input_tokens", token_totals["input_tokens"]),
        ("output_tokens", token_totals["output_tokens"]),
        ("observed_cost_usd", _fixed_float(observed_cost)),
        ("median_success_latency_ms", metrics["latency_ms"]["median"]),
        ("iqr_success_latency_ms", metrics["latency_ms"]["iqr"]),
    ]
    stream = io.StringIO()
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(("metric", "value"))
    writer.writerows(csv_rows)
    atomic_write_text(output_dir / "metrics.csv", stream.getvalue())

    status_summary = ", ".join(
        f"{status}={count}" for status, count in sorted(status_counts.items())
    ) or "brak"
    track_name = (
        "CrewAI Offline"
        if is_crewai
        else "Google Gemini Direct"
        if is_gemini
        else "OpenAI Direct"
    )
    attempt_summary = (
        f"LLM calls: {attempts}; workflows: {len(results)}; workflow retry: 0"
        if is_crewai
        else f"outbound attempts: {attempts}; retry: {retry_attempts}"
    )
    bundle_note = (
        " Tor CrewAI ma ten sam snapshot modelu, runner dataset, schema i decision "
        "policy co Direct, ale używa osobnych promptów ról/zadań oraz dodaje trzy "
        "role i frozen domain evidence. Różnica jest `system_bundle_delta`, nie "
        "czystym wpływem frameworka."
        if is_crewai
        else ""
    )
    report = f"""# Raport pilota jakości phishing classifier — {track_name}

Status: `{campaign_status}`  
Wniosek porównawczy: `INCONCLUSIVE`  
Run: `{manifest.get('run_id')}`

## Wynik opisowy

- rekordy końcowe: {len(results)}/{expected_count}; statusy: {status_summary};
- confusion matrix system action: TP={tp}, FP={fp}, TN={tn}, FN={fn};
- precision: {precision['value']} ({tp}/{tp + fp});
- recall: {recall['value']} ({tp}/{tp + fn}), Wilson 95% CI {recall['confidence_interval_95']['lower']}–{recall['confidence_interval_95']['upper']};
- F1: {f1['value']} ({2 * tp}/{2 * tp + fp + fn});
- FPR: {false_positive_rate['value']} ({fp}/{fp + tn}), Wilson 95% CI {false_positive_rate['confidence_interval_95']['lower']}–{false_positive_rate['confidence_interval_95']['upper']};
- specificity: {specificity['value']} ({tn}/{tn + fp}), Wilson 95% CI {specificity['confidence_interval_95']['lower']}–{specificity['confidence_interval_95']['upper']};
- błędy techniczne: {technical_failure_count}; {attempt_summary};
- bramki jakości: {'PASS' if acceptance_pass else 'HOLD'}; malicious `allow`: {fn}/2 max; benign `warn|hide`: {fp}/3 max; benign `hide`: {action_by_class['benign'].get('hide', 0)}/0 max;
- security probe `allow`: {security_probe_allow};
- krytyczne security events: {critical_security_events};
- diagnostyczne braki provider metadata: {provider_metadata_omissions};
- koszt zaobserwowany: ${_fixed_float(observed_cost)};
- latency `success` min/mediana/IQR/max: {metrics['latency_ms']['min']}/{metrics['latency_ms']['median']}/{metrics['latency_ms']['iqr']}/{metrics['latency_ms']['max']} ms.

## Interpretacja

To jest pilot n=30 na danych wyłącznie syntetycznych i challenge-enriched. Metryki i przedziały Wilsona są opisowe. Technical failures są mapowane przez zamrożoną `technical_failure_action` i pozostają w mianownikach. Nie jest to dowód gotowości produkcyjnej, jakości na rzeczywistym ruchu ani przewagi nad innym modelem; wniosek porównawczy zawsze pozostaje `INCONCLUSIVE`.{bundle_note}

`PILOT_READY_FOR_SELECTION` oznacza wyłącznie przejście zamrożonych bramek tego pilota i zgodę na rozpoczęcie osobnego etapu selection. `PILOT_HOLD` wymaga przeglądu przed kolejnymi płatnymi próbami. `INVALID` albo `SECURITY_FAIL` blokuje użycie tego runu jako wyniku jakości.
"""
    atomic_write_text(output_dir / "report.md", report)
    return output_dir
