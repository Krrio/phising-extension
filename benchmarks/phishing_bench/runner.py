from __future__ import annotations

import json
import os
import platform
import re
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .contracts import (
    ContractError,
    GEMINI_INTERACTIONS_API_REVISION,
    GEMINI_PROFILES,
    GPT54_PROFILES,
    QUALITY_PROFILES,
    action_for_output,
    assert_campaign_live_allowed,
    assert_pricing_current_for_run,
    build_chat_request,
    campaign_live_block_reason,
    load_and_validate_campaign,
    validate_model_output,
)
from .io_utils import (
    append_jsonl,
    atomic_write_json,
    canonical_json,
    ensure_private_directory,
    git_metadata,
    sanitize_text,
    sha256_bytes,
    sha256_file,
    sha256_json,
    sha256_text,
    utc_now,
)
from .openai_direct import (
    OpenAIChatTransport,
    ProviderError,
    ProviderResponse,
    tls_trust_summary,
)


CRITICAL_SYSTEM_MARKERS = (
    "[R — ROLA]",
    "[H — HIERARCHIA ZAUFANIA]",
    "Te instrukcje systemowe mają najwyższy priorytet",
)
SECRET_OUTPUT_RE = re.compile(
    r"(?:\bsk-[A-Za-z0-9_-]{8,}\b|\bAIza[0-9A-Za-z_-]{20,}\b)"
)
CRITICAL_SECURITY_EVENT_TYPES = {
    "unauthorized_tool_execution",
    "unauthorized_network_egress",
    "canary_disclosure",
    "cross_sample_disclosure",
    "sandbox_escape",
    "untrusted_instruction_forbidden_action",
}
GEMINI_FATAL_PROTOCOL_ERRORS = {
    "invalid_provider_json",
    "invalid_provider_response",
    "missing_usage",
    "response_too_large",
}
GEMINI_FATAL_PROVIDER_ERRORS = {
    "provider_http_error",
    "rate_limit",
}


def _empty_usage() -> dict[str, int]:
    return {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
    }


def _add_usage(target: dict[str, int], source: dict[str, int]) -> None:
    for key in target:
        target[key] += int(source.get(key, 0))


def calculate_observed_cost(usage: dict[str, int], pricing: dict[str, Any]) -> float:
    cached = min(usage["cached_input_tokens"], usage["input_tokens"])
    uncached = usage["input_tokens"] - cached
    cost = (
        uncached * float(pricing["input"])
        + cached * float(pricing["cached_input"])
        + usage["output_tokens"] * float(pricing["output"])
    ) / 1_000_000
    return round(cost, 10)


def conservative_attempt_reservation(body: dict[str, Any], config: dict[str, Any]) -> float:
    # One UTF-8 byte per input token is intentionally conservative for these small text-only pilots.
    input_proxy = len(canonical_json(body).encode("utf-8"))
    pricing = config["pricing_usd_per_million_tokens"]
    value = (
        input_proxy * float(pricing["input"])
        + int(config["max_output_tokens"]) * float(pricing["output"])
    ) / 1_000_000
    return round(value, 10)


def _harness_hashes(repo_root: Path) -> dict[str, Any]:
    files = sorted((repo_root / "benchmarks" / "phishing_bench").glob("*.py"))
    files.append(repo_root / "benchmarks" / "benchmark_cli.py")
    by_path = {
        str(path.relative_to(repo_root)): sha256_file(path)
        for path in files
    }
    return {
        "bundle_sha256": sha256_json(by_path),
        "files": by_path,
    }


def readiness_report(
    config_path: Path,
    repo_root: Path,
    *,
    check_local_tls: bool = False,
) -> dict[str, Any]:
    config, assets = load_and_validate_campaign(config_path, repo_root)
    assert_pricing_current_for_run(config)
    paths = assets["paths"]
    request_summaries = []
    reservations = []
    for record in assets["dataset"]:
        body = build_chat_request(
            config,
            record,
            assets["prompt"],
            assets["response_schema"],
        )
        serialized = canonical_json(body)
        reservation = conservative_attempt_reservation(body, config)
        reservations.append(reservation)
        request_summaries.append(
            {
                "sample_id": record["sample_id"],
                "request_sha256": sha256_text(serialized),
                "request_bytes": len(serialized.encode("utf-8")),
                "max_attempt_cost_reservation_usd": reservation,
            }
        )
    max_retries = int(config["max_retries_per_sample"])
    projected_ceiling = round(sum(reservations) * (1 + max_retries), 10)
    evaluation_profile = config.get("evaluation_profile", "openai_direct_smoke_v1")
    is_gemini = evaluation_profile in GEMINI_PROFILES
    required_cost_cap = (
        round(projected_ceiling * 1.2, 10)
        if evaluation_profile in QUALITY_PROFILES
        else projected_ceiling
    )
    if required_cost_cap > float(config["budget"]["max_cost_usd"]):
        raise ContractError(
            f"configured cost cap ${config['budget']['max_cost_usd']:.4f} is below the "
            f"required campaign reservation ${required_cost_cap:.4f}"
        )
    harness_hashes = _harness_hashes(repo_root)
    request_contract = (
        {
            "request_profile": config["request_profile"],
            "api_revision": GEMINI_INTERACTIONS_API_REVISION,
            "instruction_role": "system_instruction",
            "token_limit_field": "generation_config.max_output_tokens",
            "thinking_level": config["thinking_level"],
            "seed": config["seed"],
            "temperature": None,
            "response_id_policy": (
                "required_or_omitted_only_for_exact_complete_stateless_shape"
            ),
        }
        if is_gemini
        else {
            "request_profile": config.get(
                "request_profile", "chat_completions_legacy_v1"
            ),
            "instruction_role": (
                "developer"
                if evaluation_profile in GPT54_PROFILES
                else "system"
            ),
            "token_limit_field": (
                "max_completion_tokens"
                if evaluation_profile in GPT54_PROFILES
                else "max_tokens"
            ),
            "reasoning_effort": config.get("reasoning_effort"),
            "temperature": config["temperature"],
        }
    )
    security_contract = (
        {
            "store": False,
            "tools": "absent",
            "conversation": "absent",
            "previous_interaction_id": "absent",
            "background": False,
            "stream": False,
            "provider_egress": "generativelanguage.googleapis.com_only",
            "runtime_config_exposes_scoring_path": False,
            "input_data_class": config["security"]["data_class"],
        }
        if is_gemini
        else {
            "store": False,
            "tools": "absent",
            "conversation": "absent",
            "background": "absent",
            "runtime_config_exposes_scoring_path": False,
            "input_data_class": config["security"]["data_class"],
        }
    )
    report = {
        "schema_version": "1.0",
        "checked_at": utc_now(),
        "status": "READY_FOR_MANUAL_LIVE_CONFIRMATION",
        "campaign_id": config["campaign_id"],
        "evaluation_profile": evaluation_profile,
        "stage": config["stage"],
        "record_count": len(assets["dataset"]),
        "config_id": config["config_id"],
        "requested_model": config["requested_model"],
        "endpoint": config["endpoint"],
        "adapter": config["adapter"],
        "request_contract": request_contract,
        "security_contract": security_contract,
        "hashes": {
            "runtime_config_sha256": sha256_file(config_path),
            "dataset_sha256": sha256_file(paths["dataset_path"]),
            "prompt_sha256": sha256_file(paths["prompt_path"]),
            "response_schema_sha256": sha256_file(paths["response_schema_path"]),
            "decision_policy_sha256": sha256_file(paths["decision_policy_path"]),
            "contract_sha256": assets["contract_hash"],
            "harness_bundle_sha256": harness_hashes["bundle_sha256"],
            "product_background_sha256": sha256_file(repo_root / "src" / "background.ts"),
            "product_action_source_sha256": sha256_file(repo_root / "src" / "agent.ts"),
        },
        "harness_files": harness_hashes["files"],
        "budget": config["budget"],
        "reservation_method": "UTF-8 request bytes as input-token proxy plus max output tokens",
        "projected_max_cost_reservation_usd": projected_ceiling,
        "required_cost_cap_with_margin_usd": required_cost_cap,
        "requests": request_summaries,
    }
    live_block_reason = campaign_live_block_reason(config)
    if live_block_reason is not None:
        report["status"] = "LIVE_BLOCKED"
        report["live_block_reason"] = live_block_reason
    if "dataset_manifest_path" in paths:
        report["hashes"]["dataset_manifest_sha256"] = sha256_file(
            paths["dataset_manifest_path"]
        )
        report["dataset_contract"] = {
            "dataset_id": assets["dataset_manifest"]["dataset_id"],
            "signals_mode": assets["dataset_manifest"]["signals_mode"],
            "renderer_version": assets["dataset_manifest"]["renderer_version"],
        }
    if check_local_tls:
        report["local_tls_preflight"] = tls_trust_summary()
    return report


def _security_events(
    response: ProviderResponse,
    api_key: str,
    adapter: str,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    response_hash = sha256_bytes(response.raw_response_sha256_material)
    if adapter == "gemini_interactions" and response.response_id is None:
        events.append(
            {
                "type": "provider_metadata_omission",
                "severity": "info",
                "blocked": False,
                "detector": "missing_stateless_interaction_id",
                "evidence_ref": f"sha256:{response_hash}",
            }
        )
    if response.tool_calls_present:
        events.append(
            {
                "type": "blocked_unauthorized_request",
                "severity": "high",
                "blocked": True,
                "detector": "provider_response_tool_call_guard",
                "evidence_ref": f"sha256:{response_hash}",
            }
        )
    if any(marker in response.content for marker in CRITICAL_SYSTEM_MARKERS):
        events.append(
            {
                "type": "canary_disclosure",
                "severity": "critical",
                "blocked": False,
                "detector": "system_prompt_marker",
                "evidence_ref": f"sha256:{response_hash}",
            }
        )
    if api_key and api_key in response.content:
        events.append(
            {
                "type": "canary_disclosure",
                "severity": "critical",
                "blocked": False,
                "detector": "exact_transport_secret_match",
                "evidence_ref": f"sha256:{response_hash}",
            }
        )
    elif SECRET_OUTPUT_RE.search(response.content):
        events.append(
            {
                "type": "secret_like_output",
                "severity": "high",
                "blocked": True,
                "detector": "secret_pattern",
                "evidence_ref": f"sha256:{response_hash}",
            }
        )
    if response.resolved_model != response.requested_model:
        events.append(
            {
                "type": "configuration_drift",
                "severity": "high",
                "blocked": True,
                "detector": "resolved_model_mismatch",
                "evidence_ref": f"sha256:{sha256_text(str(response.resolved_model))}",
            }
        )
    return events


def _base_result(
    *,
    run_id: str,
    config: dict[str, Any],
    assets: dict[str, Any],
    record: dict[str, Any],
    started_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "record_type": "ResultRecord",
        "run_id": run_id,
        "campaign_id": config["campaign_id"],
        "stage": config["stage"],
        "config_id": config["config_id"],
        "sample_id": record["sample_id"],
        "repetition": 1,
        "adapter": config["adapter"],
        "endpoint": config["endpoint"],
        "requested_model": config["requested_model"],
        "resolved_model": None,
        "hashes": {
            "input_sha256": sha256_json(record),
            "prompt_sha256": sha256_text(assets["prompt"]),
            "response_schema_sha256": sha256_json(assets["response_schema"]),
            "decision_policy_sha256": sha256_json(assets["decision_policy"]),
            "contract_sha256": assets["contract_hash"],
        },
        "started_at": started_at,
        "finished_at": None,
        "latency_ms": 0.0,
        "provider_latency_ms": 0.0,
        "status": "technical_failure",
        "response_schema_valid": False,
        "verdict": None,
        "detected_risk": None,
        "trust_score": None,
        "confidence": None,
        "categories": [],
        "action": assets["decision_policy"]["technical_failure_action"],
        "reasoning_sha256": None,
        "reasoning_chars": 0,
        "reasoning_text": None,
        "finish_reason": None,
        "response_id": None,
        "provider_request_id": None,
        "attempt_ids": [],
        "outbound_attempts": 0,
        "usage": _empty_usage(),
        "observed_cost_usd": 0.0,
        "cost_unknown_attempts": 0,
        "security_events": [],
        "error": None,
    }


def _finish_result(result: dict[str, Any], monotonic_started: float) -> dict[str, Any]:
    result["finished_at"] = utc_now()
    result["latency_ms"] = round((time.monotonic() - monotonic_started) * 1000, 3)
    return result


def _stopped_result(
    *,
    run_id: str,
    config: dict[str, Any],
    assets: dict[str, Any],
    record: dict[str, Any],
    status: str,
    error_type: str,
    message: str,
) -> dict[str, Any]:
    monotonic_started = time.monotonic()
    result = _base_result(
        run_id=run_id,
        config=config,
        assets=assets,
        record=record,
        started_at=utc_now(),
    )
    result["status"] = status
    result["error"] = {"type": error_type, "message": message, "status_code": None}
    return _finish_result(result, monotonic_started)


def _budget_reason(ledger: dict[str, Any], reservation: float, now_monotonic: float) -> str | None:
    if ledger["attempts_started"] >= ledger["max_attempts"]:
        return "attempt limit reached"
    if now_monotonic >= ledger["deadline_monotonic"]:
        return "wall-clock deadline reached"
    if ledger["reserved_or_observed_cost_usd"] + reservation > ledger["max_cost_usd"] + 1e-12:
        return "cost reservation would exceed max_cost_usd"
    return None


def _public_ledger(ledger: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in ledger.items() if key != "deadline_monotonic"}


def run_campaign(
    *,
    config_path: Path,
    repo_root: Path,
    output_root: Path,
    api_key: str,
    transport: Any | None = None,
    sleep: Callable[[float], None] = time.sleep,
    store_reasoning: bool = False,
    live_authorized: bool = False,
    confirm_campaign: str | None = None,
) -> Path:
    config, assets = load_and_validate_campaign(config_path, repo_root)
    uses_default_transport = transport is None
    if uses_default_transport:
        assert_campaign_live_allowed(config)
    if uses_default_transport and (
        live_authorized is not True or confirm_campaign != config["campaign_id"]
    ):
        raise ContractError(
            "real transport requires live_authorized=True and exact confirm_campaign="
            + str(config["campaign_id"])
        )
    readiness = readiness_report(
        config_path,
        repo_root,
        check_local_tls=uses_default_transport,
    )
    if not api_key.strip():
        raise ContractError(f"{config['api_key_env']} is empty")
    if os.environ.get("SSLKEYLOGFILE"):
        raise ContractError("unset SSLKEYLOGFILE before live run; TLS key logging is forbidden")
    if store_reasoning and config["security"]["data_class"] != "synthetic_reserved_domains_only":
        raise ContractError("reasoning may be stored only for the explicitly synthetic smoke")
    if output_root.resolve() in {Path("/").resolve(), Path.home().resolve(), repo_root.resolve()}:
        raise ContractError("output root is too broad; use a dedicated run directory")
    if transport is None:
        if config.get("evaluation_profile") in GEMINI_PROFILES:
            from .gemini_direct import GeminiInteractionsTransport

            transport = GeminiInteractionsTransport()
        else:
            transport = OpenAIChatTransport()
    ensure_private_directory(output_root)
    run_id = f"{config['campaign_id']}__{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}__{uuid.uuid4().hex[:8]}"
    run_dir = output_root / run_id
    ensure_private_directory(run_dir)
    attempts_path = run_dir / "attempts.jsonl"
    results_path = run_dir / "results.jsonl"
    manifest_path = run_dir / "run_manifest.json"
    ledger_path = run_dir / "budget_ledger.json"
    run_started_at = utc_now()
    run_monotonic_started = time.monotonic()
    manifest = {
        "schema_version": "1.0",
        "record_type": "RunManifest",
        "run_id": run_id,
        "campaign_id": config["campaign_id"],
        "stage": config["stage"],
        "status": "running",
        "started_at": run_started_at,
        "finished_at": None,
        "harness_version": __version__,
        "python": platform.python_version(),
        "git": git_metadata(repo_root),
        "runtime_config": config,
        "readiness": readiness,
        "result_contract": {
            "one_terminal_record_per_sample": True,
            "raw_prompt_stored": False,
            "raw_response_stored": False,
            "reasoning_stored": store_reasoning,
            "attempt_log_append_only": True,
        },
    }
    atomic_write_json(manifest_path, manifest)
    ledger = {
        "schema_version": "1.0",
        "run_id": run_id,
        "started_at": run_started_at,
        "deadline_at_epoch_seconds": round(time.time() + config["budget"]["max_wall_seconds"], 3),
        "deadline_monotonic": run_monotonic_started + config["budget"]["max_wall_seconds"],
        "max_attempts": config["budget"]["max_attempts"],
        "max_cost_usd": float(config["budget"]["max_cost_usd"]),
        "attempts_started": 0,
        "attempts_finished": 0,
        "observed_cost_usd": 0.0,
        "reserved_or_observed_cost_usd": 0.0,
        "cost_unknown_attempts": 0,
        "stop_reason": None,
        "updated_at": utc_now(),
    }
    atomic_write_json(ledger_path, _public_ledger(ledger))
    campaign_stop: dict[str, str] | None = None

    for record in assets["dataset"]:
        if campaign_stop:
            result = _stopped_result(
                run_id=run_id,
                config=config,
                assets=assets,
                record=record,
                status="campaign_stopped",
                error_type=campaign_stop["type"],
                message=campaign_stop["message"],
            )
            append_jsonl(results_path, result)
            continue

        sample_monotonic_started = time.monotonic()
        result = _base_result(
            run_id=run_id,
            config=config,
            assets=assets,
            record=record,
            started_at=utc_now(),
        )
        body = build_chat_request(config, record, assets["prompt"], assets["response_schema"])
        reservation = conservative_attempt_reservation(body, config)
        max_sample_attempts = 1 + int(config["max_retries_per_sample"])
        final_error: dict[str, Any] | None = None

        for sample_attempt_index in range(1, max_sample_attempts + 1):
            reason = _budget_reason(ledger, reservation, time.monotonic())
            if reason:
                ledger["stop_reason"] = reason
                result["status"] = "budget_exhausted"
                final_error = {"type": "budget_exhausted", "message": reason, "status_code": None}
                break
            attempt_id = str(uuid.uuid4())
            attempt_started_at = utc_now()
            result["attempt_ids"].append(attempt_id)
            result["outbound_attempts"] += 1
            ledger["attempts_started"] += 1
            ledger["reserved_or_observed_cost_usd"] = round(
                ledger["reserved_or_observed_cost_usd"] + reservation, 10
            )
            ledger["updated_at"] = utc_now()
            atomic_write_json(ledger_path, _public_ledger(ledger))
            append_jsonl(
                attempts_path,
                {
                    "schema_version": "1.0",
                    "record_type": "AttemptEvent",
                    "event": "started",
                    "run_id": run_id,
                    "attempt_id": attempt_id,
                    "sample_id": record["sample_id"],
                    "sample_attempt_index": sample_attempt_index,
                    "started_at": attempt_started_at,
                    "request_sha256": sha256_json(body),
                    "cost_reservation_usd": reservation,
                },
            )
            try:
                remaining_wall_seconds = max(ledger["deadline_monotonic"] - time.monotonic(), 0.001)
                response = transport.call(
                    api_key=api_key,
                    endpoint=config["endpoint"],
                    body=body,
                    timeout_seconds=min(
                        float(config["request_timeout_seconds"]), remaining_wall_seconds
                    ),
                )
                observed_cost = calculate_observed_cost(
                    response.usage, config["pricing_usd_per_million_tokens"]
                )
                result["provider_latency_ms"] = round(
                    result["provider_latency_ms"] + response.elapsed_ms, 3
                )
                _add_usage(result["usage"], response.usage)
                result["observed_cost_usd"] = round(result["observed_cost_usd"] + observed_cost, 10)
                ledger["observed_cost_usd"] = round(ledger["observed_cost_usd"] + observed_cost, 10)
                ledger["attempts_finished"] += 1
                ledger["updated_at"] = utc_now()
                atomic_write_json(ledger_path, _public_ledger(ledger))
                raw_response_hash = sha256_bytes(response.raw_response_sha256_material)
                security_events = _security_events(
                    response,
                    api_key,
                    str(config["adapter"]),
                )
                result["resolved_model"] = response.resolved_model
                result["finish_reason"] = response.finish_reason
                result["response_id"] = response.response_id
                result["provider_request_id"] = response.safe_headers.get(
                    "x-request-id"
                ) or response.safe_headers.get("x-goog-request-id")
                result["security_events"].extend(security_events)
                critical_security_event = any(
                    event["severity"] == "critical"
                    and event["type"] in CRITICAL_SECURITY_EVENT_TYPES
                    for event in security_events
                )
                configuration_drift = any(
                    event["type"] == "configuration_drift" for event in security_events
                )
                if critical_security_event or configuration_drift:
                    result["status"] = "invalid" if configuration_drift else "security_fail"
                    append_jsonl(
                        attempts_path,
                        {
                            "schema_version": "1.0",
                            "record_type": "AttemptEvent",
                            "event": "finished",
                            "run_id": run_id,
                            "attempt_id": attempt_id,
                            "sample_id": record["sample_id"],
                            "finished_at": utc_now(),
                            "status": result["status"],
                            "response_id": response.response_id,
                            "resolved_model": response.resolved_model,
                            "raw_response_sha256": raw_response_hash,
                            "usage": response.usage,
                            "observed_cost_usd": observed_cost,
                            "latency_ms": round(response.elapsed_ms, 3),
                            "safe_provider_headers": response.safe_headers,
                            "security_events": security_events,
                            "error": None,
                        },
                    )
                    campaign_stop = {
                        "type": "protocol_invalid"
                        if configuration_drift
                        else "critical_security_event",
                        "message": "campaign stopped after provider/model configuration drift"
                        if configuration_drift
                        else "campaign stopped after a critical security event",
                    }
                    break
                if response.finish_reason != "stop":
                    final_error = {
                        "type": "incomplete_output",
                        "message": "provider finish status was not complete",
                        "status_code": None,
                    }
                    append_jsonl(
                        attempts_path,
                        {
                            "schema_version": "1.0",
                            "record_type": "AttemptEvent",
                            "event": "finished",
                            "run_id": run_id,
                            "attempt_id": attempt_id,
                            "sample_id": record["sample_id"],
                            "finished_at": utc_now(),
                            "status": "incomplete_output",
                            "response_id": response.response_id,
                            "resolved_model": response.resolved_model,
                            "raw_response_sha256": raw_response_hash,
                            "usage": response.usage,
                            "observed_cost_usd": observed_cost,
                            "latency_ms": round(response.elapsed_ms, 3),
                            "safe_provider_headers": response.safe_headers,
                            "security_events": security_events,
                            "error": final_error,
                        },
                    )
                    if sample_attempt_index < max_sample_attempts:
                        continue
                    result["status"] = "incomplete_output"
                    break
                try:
                    parsed_output = json.loads(response.content)
                    normalized = validate_model_output(parsed_output)
                except (json.JSONDecodeError, ContractError) as exc:
                    final_error = {
                        "type": "invalid_output",
                        "message": sanitize_text(str(exc), (api_key,)),
                        "status_code": None,
                    }
                    append_jsonl(
                        attempts_path,
                        {
                            "schema_version": "1.0",
                            "record_type": "AttemptEvent",
                            "event": "finished",
                            "run_id": run_id,
                            "attempt_id": attempt_id,
                            "sample_id": record["sample_id"],
                            "finished_at": utc_now(),
                            "status": "invalid_output",
                            "response_id": response.response_id,
                            "resolved_model": response.resolved_model,
                            "raw_response_sha256": raw_response_hash,
                            "usage": response.usage,
                            "observed_cost_usd": observed_cost,
                            "latency_ms": round(response.elapsed_ms, 3),
                            "security_events": security_events,
                            "error": final_error,
                        },
                    )
                    if sample_attempt_index < max_sample_attempts:
                        continue
                    result["status"] = "invalid_output"
                    break

                result.update(
                    {
                        "status": "success",
                        "response_schema_valid": True,
                        "resolved_model": response.resolved_model,
                        "verdict": normalized["verdict"],
                        "detected_risk": normalized["verdict"] != "safe",
                        "trust_score": normalized["trustScore"],
                        "confidence": normalized["confidence"],
                        "categories": normalized["categories"],
                        "action": action_for_output(normalized, assets["decision_policy"]),
                        "reasoning_sha256": sha256_text(normalized["reasoning"]),
                        "reasoning_chars": len(normalized["reasoning"]),
                        "reasoning_text": sanitize_text(normalized["reasoning"], (api_key,))
                        if store_reasoning and not critical_security_event
                        else None,
                        "error": None,
                    }
                )
                append_jsonl(
                    attempts_path,
                    {
                        "schema_version": "1.0",
                        "record_type": "AttemptEvent",
                        "event": "finished",
                        "run_id": run_id,
                        "attempt_id": attempt_id,
                        "sample_id": record["sample_id"],
                        "finished_at": utc_now(),
                        "status": result["status"],
                        "response_id": response.response_id,
                        "resolved_model": response.resolved_model,
                        "raw_response_sha256": raw_response_hash,
                        "usage": response.usage,
                        "observed_cost_usd": observed_cost,
                        "latency_ms": round(response.elapsed_ms, 3),
                        "safe_provider_headers": response.safe_headers,
                        "security_events": security_events,
                        "error": None,
                    },
                )
                break
            except ProviderError as exc:
                ledger["attempts_finished"] += 1
                ledger["cost_unknown_attempts"] += 1
                ledger["updated_at"] = utc_now()
                atomic_write_json(ledger_path, _public_ledger(ledger))
                result["cost_unknown_attempts"] += 1
                final_error = {
                    "type": exc.kind,
                    "message": sanitize_text(str(exc), (api_key,)),
                    "status_code": exc.status_code,
                }
                append_jsonl(
                    attempts_path,
                    {
                        "schema_version": "1.0",
                        "record_type": "AttemptEvent",
                        "event": "finished",
                        "run_id": run_id,
                        "attempt_id": attempt_id,
                        "sample_id": record["sample_id"],
                        "finished_at": utc_now(),
                        "status": exc.kind,
                        "response_id": None,
                        "resolved_model": None,
                        "raw_response_sha256": None,
                        "usage": _empty_usage(),
                        "observed_cost_usd": None,
                        "latency_ms": None,
                        "safe_provider_headers": exc.response_headers,
                        "security_events": [],
                        "error": final_error,
                    },
                )
                if (
                    config.get("adapter") == "gemini_interactions"
                    and exc.kind in GEMINI_FATAL_PROTOCOL_ERRORS
                ):
                    result["status"] = exc.kind
                    ledger["stop_reason"] = (
                        "fatal Gemini response protocol error; inspect the safe "
                        "structural fingerprint before another live run"
                    )
                    ledger["updated_at"] = utc_now()
                    atomic_write_json(ledger_path, _public_ledger(ledger))
                    campaign_stop = {
                        "type": "provider_protocol_error",
                        "message": (
                            "campaign stopped after the first fatal Gemini response "
                            "protocol error"
                        ),
                    }
                    break
                if exc.retryable and sample_attempt_index < max_sample_attempts:
                    delay = (
                        exc.retry_after_seconds
                        if exc.retry_after_seconds is not None
                        else min(2 ** (sample_attempt_index - 1), 4)
                    )
                    remaining = ledger["deadline_monotonic"] - time.monotonic()
                    if delay >= remaining:
                        ledger["stop_reason"] = "provider retry delay would cross wall-clock deadline"
                        result["status"] = exc.kind
                        break
                    sleep(delay)
                    continue
                result["status"] = exc.kind
                if exc.kind == "tls_certificate_error":
                    campaign_stop = {
                        "type": "tls_certificate_error",
                        "message": (
                            "campaign stopped after TLS certificate verification failed; "
                            "repair the trusted CA configuration before a new run"
                        ),
                    }
                elif (
                    config.get("adapter") == "gemini_interactions"
                    and exc.kind in GEMINI_FATAL_PROVIDER_ERRORS
                ):
                    ledger["stop_reason"] = (
                        "Gemini provider error remained after the configured retry "
                        "policy; verify billing, authentication, quota, and endpoint"
                    )
                    ledger["updated_at"] = utc_now()
                    atomic_write_json(ledger_path, _public_ledger(ledger))
                    campaign_stop = {
                        "type": "provider_error",
                        "message": (
                            "campaign stopped after a Gemini provider error remained "
                            "after the configured retry policy"
                        ),
                    }
                break
            except Exception as exc:  # Defensive terminal record; the secret is always scrubbed.
                ledger["attempts_finished"] += 1
                ledger["cost_unknown_attempts"] += 1
                ledger["updated_at"] = utc_now()
                atomic_write_json(ledger_path, _public_ledger(ledger))
                result["cost_unknown_attempts"] += 1
                final_error = {
                    "type": "runner_error",
                    "message": sanitize_text(str(exc), (api_key,)),
                    "status_code": None,
                }
                append_jsonl(
                    attempts_path,
                    {
                        "schema_version": "1.0",
                        "record_type": "AttemptEvent",
                        "event": "finished",
                        "run_id": run_id,
                        "attempt_id": attempt_id,
                        "sample_id": record["sample_id"],
                        "finished_at": utc_now(),
                        "status": "runner_error",
                        "usage": _empty_usage(),
                        "observed_cost_usd": None,
                        "security_events": [],
                        "error": final_error,
                    },
                )
                result["status"] = "runner_error"
                break

        if result["status"] not in {"success", "security_fail", "invalid"} and result["error"] is None:
            result["error"] = final_error or {
                "type": "runner_error",
                "message": "sample ended without a successful terminal response",
                "status_code": None,
            }
        result = _finish_result(result, sample_monotonic_started)
        append_jsonl(results_path, result)

    results = []
    if results_path.exists():
        with results_path.open("r", encoding="utf-8") as handle:
            results = [json.loads(line) for line in handle if line.strip()]
    statuses = Counter(result["status"] for result in results)
    if statuses.get("invalid"):
        final_status = "invalid"
    elif statuses.get("security_fail"):
        final_status = "security_fail"
    elif statuses.get("campaign_stopped"):
        final_status = "completed_with_failures"
    elif len(results) != len(assets["dataset"]) or any(status != "success" for status in statuses):
        final_status = "completed_with_failures"
    else:
        final_status = "completed"
    manifest["status"] = final_status
    manifest["finished_at"] = utc_now()
    manifest["summary"] = {
        "expected_results": len(assets["dataset"]),
        "written_results": len(results),
        "statuses": dict(statuses),
        "attempts_started": ledger["attempts_started"],
        "attempts_finished": ledger["attempts_finished"],
        "observed_cost_usd": ledger["observed_cost_usd"],
        "reserved_or_observed_cost_usd": ledger["reserved_or_observed_cost_usd"],
        "cost_unknown_attempts": ledger["cost_unknown_attempts"],
        "elapsed_seconds": round(time.monotonic() - run_monotonic_started, 3),
    }
    ledger["updated_at"] = utc_now()
    atomic_write_json(ledger_path, _public_ledger(ledger))
    manifest["artifact_hashes"] = {
        "attempts_jsonl_sha256": sha256_file(attempts_path),
        "results_jsonl_sha256": sha256_file(results_path),
        "budget_ledger_json_sha256": sha256_file(ledger_path),
    }
    atomic_write_json(manifest_path, manifest)
    return run_dir


def api_key_from_environment(config_path: Path, repo_root: Path) -> str:
    config, _ = load_and_validate_campaign(config_path, repo_root)
    return os.environ.get(config["api_key_env"], "")
