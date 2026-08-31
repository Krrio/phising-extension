"""Auditable CrewAI Offline benchmark runner.

Only the explicitly selected OpenAI or Google model endpoint is live. Domain
evidence is rendered locally from the frozen synthetic record and a versioned
reserved-domain policy; RDAP and WHOIS are never imported or called here.
"""

from __future__ import annotations

import atexit
import importlib.metadata
import json
import os
import platform
import shutil
import socket
import tempfile
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator
from unittest.mock import patch

from . import __version__
from .contracts import (
    CREWAI_GEMINI_TRANSIENT_FAIL_FAST_CAMPAIGN_IDS,
    CREWAI_GEMINI_PROFILES,
    CREWAI_PROFILES,
    ContractError,
    EMAIL_RE,
    HOSTNAME_RE,
    RESERVED_DATA_DOMAINS,
    URL_RE,
    action_for_output,
    assert_campaign_live_allowed,
    assert_pricing_current_for_run,
    build_crewai_workflow_contract,
    campaign_live_block_reason,
    load_and_validate_campaign,
    validate_model_output,
)
from .io_utils import (
    append_jsonl,
    atomic_write_json,
    atomic_write_text,
    canonical_json,
    ensure_private_directory,
    git_metadata,
    sanitize_text,
    sha256_file,
    sha256_json,
    sha256_text,
    utc_now,
)
from .openai_direct import tls_trust_summary, validated_tls_context
from .runner import (
    CRITICAL_SYSTEM_MARKERS,
    SECRET_OUTPUT_RE,
    _add_usage,
    _base_result,
    _empty_usage,
    _finish_result,
    _harness_hashes,
    _public_ledger,
    _stopped_result,
    calculate_observed_cost,
)


EXPECTED_CALL_ROLES = ("domain_analyst", "content_analyst", "orchestrator")
EXPECTED_CALL_TASKS = ("domain_analysis", "content_analysis", "synthesis")
GOOGLE_PROVIDER_FAILURE_KINDS = {
    "rate_limit",
    "timeout",
    "provider_http_error",
}
_CREWAI_STORAGE_DIR: Path | None = None
_ORIGINAL_USER_DATA_DIR: Any | None = None
PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)
GOOGLE_AMBIENT_ENV_KEYS = (
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_GENAI_USE_VERTEXAI",
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_LOCATION",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_CLOUD_QUOTA_PROJECT",
)
PROVIDER_HOSTNAMES = {
    "openai": "api.openai.com",
    "google": "generativelanguage.googleapis.com",
}
CREWAI_TELEMETRY_ENV = {
    # CrewAI 1.15.8 has two independent observability paths: anonymous OTLP
    # telemetry and first-execution trace collection.  Disable both before the
    # first CrewAI import so an exporter thread is never constructed.
    "OTEL_SDK_DISABLED": "true",
    "CREWAI_DISABLE_TELEMETRY": "true",
    "CREWAI_DISABLE_TRACKING": "true",
    "CREWAI_TRACING_ENABLED": "false",
    "CREWAI_TESTING": "true",
}


@dataclass(frozen=True)
class CrewCallObservation:
    call_id: str
    role: str
    task_name: str | None
    request_sha256: str
    response_sha256: str | None
    model: str | None
    usage: dict[str, int] | None
    latency_ms: float | None
    finish_reason: str | None
    response_id: str | None
    status: str
    error: str | None
    error_kind: str | None = None
    status_code: int | None = None
    provider_status: str | None = None


@dataclass(frozen=True)
class CrewWorkflowExecution:
    raw_output: str | None
    calls: tuple[CrewCallObservation, ...]
    runtime_audit: dict[str, Any]
    error: str | None = None


def _extract_domains(record: dict[str, Any]) -> list[str]:
    analysis = record["untrusted_analysis"]
    serialized = canonical_json(analysis)
    domains = {
        match.group(1).lower().rstrip(".") for match in EMAIL_RE.finditer(serialized)
    }
    domains.update(
        match.group(1).lower().rstrip(".") for match in URL_RE.finditer(serialized)
    )
    domains.update(
        match.group(0).lower().rstrip(".") for match in HOSTNAME_RE.finditer(serialized)
    )
    return sorted(domains)


def build_frozen_domain_evidence(
    record: dict[str, Any], profile: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Render deterministic evidence without importing any live domain service."""

    domains = _extract_domains(record)
    suspicious = {
        value.casefold().rstrip(".")
        for value in record["untrusted_analysis"]["signals"]["suspiciousDomains"]
    }
    unsafe = [domain for domain in domains if not domain.endswith(RESERVED_DATA_DOMAINS)]
    if unsafe:
        raise ContractError(f"frozen evidence rejected non-reserved domain: {unsafe[0]}")

    signal_output = [
        {
            "domain": domain,
            "product_signal_suspicious": domain in suspicious,
        }
        for domain in domains
    ]
    registration_output = [
        {
            "domain": domain,
            "status": profile["registration_status"],
            "source": profile["registration_source"],
            "as_of": profile["as_of"],
        }
        for domain in domains
    ]
    evidence = {
        "schema_version": "1.0",
        "fixture_id": profile["fixture_id"],
        "as_of": profile["as_of"],
        "render_version": profile["render_version"],
        "network_used": False,
        "domains": [
            {
                **signal,
                "registration_status": profile["registration_status"],
                "registration_source": profile["registration_source"],
            }
            for signal in signal_output
        ],
    }
    tool_specs = [
        {
            "tool_name": "frozen_product_domain_signal",
            "input_sha256": sha256_json(domains),
            "output_sha256": sha256_json(signal_output),
        },
        {
            "tool_name": "frozen_reserved_domain_registration",
            "input_sha256": sha256_json(domains),
            "output_sha256": sha256_json(registration_output),
        },
    ]
    return evidence, tool_specs


def _attempt_reservation(
    workflow: dict[str, Any], config: dict[str, Any]
) -> float:
    # The workflow serialization includes all three roles/tasks, while a real
    # call sees only its active agent/task plus prior context. One byte per
    # token is therefore a deliberately conservative proxy for this dataset.
    input_proxy = len(canonical_json(workflow).encode("utf-8"))
    input_proxy += 2 * int(config["max_output_tokens"])
    pricing = config["pricing_usd_per_million_tokens"]
    value = (
        input_proxy * float(pricing["input"])
        + int(config["max_output_tokens"]) * float(pricing["output"])
    ) / 1_000_000
    return round(value, 10)


def _provider_hostname(provider: str) -> str:
    try:
        return PROVIDER_HOSTNAMES[provider]
    except KeyError as exc:
        raise ContractError(f"unsupported CrewAI provider: {provider}") from exc


@contextmanager
def _isolated_provider_environment(provider: str) -> Iterator[None]:
    """Prevent proxy, dotenv, and Google Cloud ambient routing drift."""

    hostname = _provider_hostname(provider)
    keys = set(PROXY_ENV_KEYS) | {"NO_PROXY", "no_proxy", "OPENAI_API_KEY"}
    if provider == "google":
        keys.update(GOOGLE_AMBIENT_ENV_KEYS)
    saved = {key: os.environ[key] for key in keys if key in os.environ}
    for key in keys:
        os.environ.pop(key, None)
    os.environ["NO_PROXY"] = hostname
    os.environ["no_proxy"] = hostname
    try:
        yield
    finally:
        for key in keys:
            os.environ.pop(key, None)
        os.environ.update(saved)


def _import_benchmark_factory(provider: str = "openai") -> tuple[Any, Any]:
    global _CREWAI_STORAGE_DIR, _ORIGINAL_USER_DATA_DIR

    os.environ.update(CREWAI_TELEMETRY_ENV)
    _provider_hostname(provider)
    try:
        import appdirs
        import dotenv

        if _CREWAI_STORAGE_DIR is None:
            _CREWAI_STORAGE_DIR = Path(
                tempfile.mkdtemp(prefix="phishing-crewai-benchmark-")
            )
            _ORIGINAL_USER_DATA_DIR = appdirs.user_data_dir
            appdirs.user_data_dir = (  # type: ignore[assignment]
                lambda *args, **kwargs: str(_CREWAI_STORAGE_DIR)
            )
            atexit.register(shutil.rmtree, _CREWAI_STORAGE_DIR, ignore_errors=True)
            atexit.register(
                setattr, appdirs, "user_data_dir", _ORIGINAL_USER_DATA_DIR
            )

        # CrewAI imports compute a default persistence path even with memory
        # disabled and call python-dotenv. Redirect the former to our owned
        # temporary directory and disable the latter for the benchmark import.
        with _isolated_provider_environment(provider), patch.object(
            dotenv, "load_dotenv", lambda *args, **kwargs: False
        ):
            from guardian_classic.benchmark_crew import (
                audit_benchmark_crew,
                build_benchmark_crew,
            )
    except ImportError as exc:
        raise ContractError(
            "CrewAI benchmark runtime is unavailable; run with "
            "backend/guardian/.venv/bin/python from the repository root"
        ) from exc
    return build_benchmark_crew, audit_benchmark_crew


def _crewai_telemetry_audit(provider: str = "openai") -> dict[str, Any]:
    """Fail closed if CrewAI created any exporter or first-run trace path."""

    from crewai.events.listeners.tracing.utils import (
        should_auto_collect_first_time_traces,
        should_enable_tracing,
    )
    from crewai.telemetry.telemetry import Telemetry

    env = {key: os.environ.get(key) for key in CREWAI_TELEMETRY_ENV}
    if env != CREWAI_TELEMETRY_ENV:
        raise ContractError("CrewAI telemetry environment guard drift")
    telemetry = Telemetry()
    expected_hostname = _provider_hostname(provider)
    state = {
        "environment": env,
        "anonymous_exporter_ready": bool(telemetry.ready),
        "tracing_enabled": bool(should_enable_tracing()),
        "first_run_trace_collection": bool(
            should_auto_collect_first_time_traces()
        ),
        "proxy_variables_present": [
            key for key in PROXY_ENV_KEYS if key in os.environ
        ],
        "ambient_google_variables_present": (
            [key for key in GOOGLE_AMBIENT_ENV_KEYS if key in os.environ]
            if provider == "google"
            else []
        ),
        "no_proxy": os.environ.get("NO_PROXY"),
    }
    if any(
        (
            state["anonymous_exporter_ready"],
            state["tracing_enabled"],
            state["first_run_trace_collection"],
            bool(state["proxy_variables_present"]),
            bool(state["ambient_google_variables_present"]),
            state["no_proxy"] != expected_hostname,
        )
    ):
        raise ContractError(
            "CrewAI telemetry or tracing initialized before benchmark isolation"
        )
    return state


def crewai_runtime_preflight(
    config: dict[str, Any], assets: dict[str, Any]
) -> dict[str, Any]:
    provider = str(config["provider"])
    try:
        installed_version = importlib.metadata.version("crewai")
    except importlib.metadata.PackageNotFoundError as exc:
        raise ContractError(
            "CrewAI is not installed in this Python environment; use "
            "backend/guardian/.venv/bin/python"
        ) from exc
    if installed_version != config["crewai_version"]:
        raise ContractError(
            f"CrewAI version drift: installed={installed_version}, "
            f"required={config['crewai_version']}"
        )
    google_genai_version: str | None = None
    if provider == "google":
        try:
            google_genai_version = importlib.metadata.version("google-genai")
        except importlib.metadata.PackageNotFoundError as exc:
            raise ContractError(
                "google-genai is not installed; sync the pinned guardian environment"
            ) from exc
        if google_genai_version != "1.65.0":
            raise ContractError(
                "google-genai version drift: installed="
                f"{google_genai_version}, required=1.65.0"
            )

    bundle: Any | None = None
    with _isolated_provider_environment(provider):
        build_crew, audit_crew = _import_benchmark_factory(provider)
        bundle = build_crew(
            api_key=(
                "benchmark-google-placeholder-not-a-real-key"
                if provider == "google"
                else "sk-benchmark-placeholder-not-a-real-key"
            ),
            requested_model=config["requested_model"],
            temperature=config["temperature"],
            max_output_tokens=config["max_output_tokens"],
            request_timeout_seconds=config["request_timeout_seconds"],
            max_llm_calls=config["framework_config"]["max_llm_calls_per_sample"],
            response_schema=assets["response_schema"],
            profile=assets["crew_profile"],
            provider=provider,
            thinking_level=config.get("thinking_level"),
            tls_context=(validated_tls_context() if provider == "google" else None),
        )
        try:
            audit = audit_crew(bundle)
            telemetry_audit = _crewai_telemetry_audit(provider)
            expected_model = config["requested_model"]
            expected_framework_provider = (
                "gemini" if provider == "google" else "openai"
            )
            if (
                bundle.call_budget.used != 0
                or audit["max_llm_calls_per_sample"] != 3
                or audit["task_output_storage"]
                != config["framework_config"]["task_output_storage"]
                or [row["benchmark_role"] for row in audit["agents"]]
                != list(EXPECTED_CALL_ROLES)
                or any(row["model"] != expected_model for row in audit["agents"])
                or any(
                    row["provider"] != expected_framework_provider
                    for row in audit["agents"]
                )
                or [row["response_format"] for row in audit["agents"]]
                != ["text", "text", "strict_json_schema"]
            ):
                raise ContractError("effective CrewAI preflight profile drift")
        finally:
            bundle.close()
    report = {
        "installed_crewai_version": installed_version,
        "required_crewai_version": config["crewai_version"],
        "effective_profile": audit,
        "telemetry": telemetry_audit,
        "provider_calls_made": 0,
    }
    if google_genai_version is not None:
        report.update(
            {
                "installed_google_genai_version": google_genai_version,
                "required_google_genai_version": "1.65.0",
            }
        )
    return report


def crewai_security_contract(config: dict[str, Any]) -> dict[str, Any]:
    provider = str(config["provider"])
    contract = {
        "store": False,
        "tools": "runner_precomputed_frozen_evidence_only",
        "live_domain_network": False,
        "provider_egress": f"{_provider_hostname(provider)}_only",
        "conversation": "fresh_crew_per_sample",
        "background": "absent",
        "crewai_anonymous_telemetry": False,
        "crewai_first_run_tracing": False,
        "crewai_task_output_persistence": False,
        "model_observation": "configured_request_model_via_crewai_event",
        "runtime_config_exposes_scoring_path": False,
        "input_data_class": config["security"]["data_class"],
    }
    if provider == "google":
        contract.update(
            {
                "provider_api": "native_generate_content_v1",
                "provider_state_mode": "explicit_store_false_request_override",
                "store_enforcement": "http_options_extra_body_root",
                "vertexai": False,
                "ambient_google_credentials": "cleared",
            }
        )
    return contract


def crewai_readiness_report(
    config_path: Path,
    repo_root: Path,
    *,
    check_local_tls: bool = False,
) -> dict[str, Any]:
    config, assets = load_and_validate_campaign(config_path, repo_root)
    assert_pricing_current_for_run(config)
    if config.get("evaluation_profile") not in CREWAI_PROFILES:
        raise ContractError("CrewAI readiness received a non-CrewAI campaign")
    paths = assets["paths"]
    requests: list[dict[str, Any]] = []
    reservations: list[float] = []
    for record in assets["dataset"]:
        workflow = build_crewai_workflow_contract(
            config,
            record,
            assets["prompt"],
            assets["crew_profile"],
            assets["frozen_domain_evidence"],
            assets["response_schema"],
        )
        serialized = canonical_json(workflow)
        reservation = _attempt_reservation(workflow, config)
        reservations.append(reservation)
        requests.append(
            {
                "sample_id": record["sample_id"],
                "request_sha256": sha256_text(serialized),
                "request_bytes": len(serialized.encode("utf-8")),
                "planned_llm_calls": 3,
                "max_attempt_cost_reservation_usd": reservation,
            }
        )
    projected_ceiling = round(sum(reservations) * 3, 10)
    required_cost_cap = round(projected_ceiling * 1.2, 10)
    if required_cost_cap > float(config["budget"]["max_cost_usd"]):
        raise ContractError(
            f"configured cost cap ${config['budget']['max_cost_usd']:.4f} is below the "
            f"required CrewAI reservation ${required_cost_cap:.4f}"
        )
    harness_hashes = _harness_hashes(repo_root)
    runtime_preflight = crewai_runtime_preflight(config, assets)
    report = {
        "schema_version": "1.0",
        "checked_at": utc_now(),
        "status": "READY_FOR_MANUAL_LIVE_CONFIRMATION",
        "campaign_id": config["campaign_id"],
        "evaluation_profile": config["evaluation_profile"],
        "stage": config["stage"],
        "record_count": len(assets["dataset"]),
        "config_id": config["config_id"],
        "requested_model": config["requested_model"],
        "endpoint": config["endpoint"],
        "adapter": config["adapter"],
        "security_contract": crewai_security_contract(config),
        "hashes": {
            "runtime_config_sha256": sha256_file(config_path),
            "dataset_sha256": sha256_file(paths["dataset_path"]),
            "prompt_sha256": sha256_file(paths["prompt_path"]),
            "crew_profile_sha256": sha256_file(paths["crew_profile_path"]),
            "frozen_domain_evidence_sha256": sha256_file(
                paths["frozen_domain_evidence_path"]
            ),
            "response_schema_sha256": sha256_file(paths["response_schema_path"]),
            "decision_policy_sha256": sha256_file(paths["decision_policy_path"]),
            "contract_sha256": assets["contract_hash"],
            "harness_bundle_sha256": harness_hashes["bundle_sha256"],
            "crewai_factory_sha256": sha256_file(
                repo_root
                / "backend"
                / "guardian"
                / "src"
                / "guardian_classic"
                / "benchmark_crew.py"
            ),
            "crewai_pyproject_sha256": sha256_file(
                repo_root / "backend" / "guardian" / "pyproject.toml"
            ),
            "crewai_lock_sha256": sha256_file(
                repo_root / "backend" / "guardian" / "uv.lock"
            ),
            "product_background_sha256": sha256_file(repo_root / "src" / "background.ts"),
            "product_action_source_sha256": sha256_file(repo_root / "src" / "agent.ts"),
        },
        "harness_files": harness_hashes["files"],
        "runtime_preflight": runtime_preflight,
        "system_bundle_delta": config["system_bundle_delta"],
        "budget": config["budget"],
        "reservation_method": (
            "full frozen workflow UTF-8 bytes plus prior-output allowance as the "
            "input-token proxy, plus max output tokens, for each of three calls"
        ),
        "projected_max_cost_reservation_usd": projected_ceiling,
        "required_cost_cap_with_margin_usd": required_cost_cap,
        "requests": requests,
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


def _usage_value(usage: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return 0


def _normalize_usage(raw: Any) -> dict[str, int] | None:
    if not isinstance(raw, dict):
        return None
    input_tokens = _usage_value(
        raw, "prompt_tokens", "input_tokens", "prompt_token_count"
    )
    # CrewAI's native Gemini adapter deliberately folds thought tokens into
    # completion_tokens. Keep that billed total intact; reasoning_tokens is
    # diagnostic and must never be added a second time.
    output_tokens = _usage_value(
        raw, "completion_tokens", "output_tokens", "candidates_token_count"
    )
    prompt_details = raw.get("prompt_tokens_details")
    completion_details = raw.get("completion_tokens_details")
    cached = _usage_value(raw, "cached_prompt_tokens", "cached_input_tokens")
    if cached == 0 and isinstance(prompt_details, dict):
        cached = _usage_value(prompt_details, "cached_tokens")
    reasoning = (
        _usage_value(completion_details, "reasoning_tokens")
        if isinstance(completion_details, dict)
        else _usage_value(raw, "reasoning_tokens")
    )
    total = _usage_value(raw, "total_tokens", "total_token_count") or (
        input_tokens + output_tokens
    )
    if input_tokens <= 0 or output_tokens <= 0 or total < input_tokens + output_tokens:
        return None
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": min(cached, input_tokens),
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning,
        "total_tokens": total,
    }


@contextmanager
def _provider_only_network_guard(provider: str) -> Iterator[None]:
    """Block every hostname/IP except the pinned provider endpoint."""

    allowed_hostname = _provider_hostname(provider)
    original_getaddrinfo = socket.getaddrinfo
    original_connect = socket.socket.connect
    allowed_ips: set[str] = set()

    def guarded_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        normalized = host.decode("ascii") if isinstance(host, bytes) else str(host)
        normalized = normalized.casefold().rstrip(".")
        if normalized != allowed_hostname:
            raise PermissionError(f"network guard blocked hostname: {normalized}")
        results = original_getaddrinfo(host, *args, **kwargs)
        allowed_ips.update(str(item[4][0]) for item in results)
        return results

    def guarded_connect(sock: socket.socket, address: Any) -> Any:
        if not isinstance(address, tuple) or not address:
            raise PermissionError("network guard blocked non-IP socket target")
        host = str(address[0]).casefold().rstrip(".")
        if host != allowed_hostname and host not in allowed_ips:
            raise PermissionError(f"network guard blocked address: {host}")
        return original_connect(sock, address)

    saved_proxy = {key: os.environ.pop(key) for key in PROXY_ENV_KEYS if key in os.environ}
    saved_no_proxy = os.environ.get("NO_PROXY")
    saved_lower_no_proxy = os.environ.get("no_proxy")
    os.environ["NO_PROXY"] = allowed_hostname
    os.environ["no_proxy"] = allowed_hostname
    try:
        with patch.object(socket, "getaddrinfo", guarded_getaddrinfo), patch.object(
            socket.socket, "connect", guarded_connect
        ):
            yield
    finally:
        for key in PROXY_ENV_KEYS:
            os.environ.pop(key, None)
        os.environ.update(saved_proxy)
        if saved_no_proxy is None:
            os.environ.pop("NO_PROXY", None)
        else:
            os.environ["NO_PROXY"] = saved_no_proxy
        if saved_lower_no_proxy is None:
            os.environ.pop("no_proxy", None)
        else:
            os.environ["no_proxy"] = saved_lower_no_proxy


@contextmanager
def _openai_only_network_guard() -> Iterator[None]:
    """Backward-compatible OpenAI-only guard used by existing tests."""

    with _provider_only_network_guard("openai"):
        yield


def _event_hash(value: Any) -> str:
    return sha256_text(value) if isinstance(value, str) else sha256_json(value)


def _normalize_finish_reason(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().casefold()


def _execute_real_workflow(
    *,
    config: dict[str, Any],
    assets: dict[str, Any],
    record: dict[str, Any],
    evidence: dict[str, Any],
    api_key: str,
) -> CrewWorkflowExecution:
    provider = str(config["provider"])
    with _isolated_provider_environment(provider):
        build_crew, audit_crew = _import_benchmark_factory(provider)
        bundle = build_crew(
            api_key=api_key,
            requested_model=config["requested_model"],
            temperature=config["temperature"],
            max_output_tokens=config["max_output_tokens"],
            request_timeout_seconds=config["request_timeout_seconds"],
            max_llm_calls=config["framework_config"]["max_llm_calls_per_sample"],
            response_schema=assets["response_schema"],
            profile=assets["crew_profile"],
            provider=provider,
            thinking_level=config.get("thinking_level"),
            tls_context=(validated_tls_context() if provider == "google" else None),
        )
        audit = audit_crew(bundle)
        audit["telemetry"] = _crewai_telemetry_audit(provider)

    try:
        from crewai.events import (
            LLMCallCompletedEvent,
            LLMCallFailedEvent,
            LLMCallStartedEvent,
            crewai_event_bus,
        )
    except ImportError as exc:  # pragma: no cover - guarded by runtime preflight
        raise ContractError("CrewAI event API is unavailable") from exc

    started: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    completed: dict[str, dict[str, Any]] = {}

    def on_started(source: Any, event: Any) -> None:
        del source
        call_id = str(event.call_id)
        if call_id in started:
            raise RuntimeError("duplicate CrewAI LLM call_id")
        order.append(call_id)
        started[call_id] = {
            "monotonic": time.monotonic(),
            "request_sha256": _event_hash(event.messages),
            # LLMEventBase removes the live Task object and materializes this
            # safe field before dispatching the event.
            "task_name": getattr(event, "task_name", None),
        }

    def on_completed(source: Any, event: Any) -> None:
        del source
        call_id = str(event.call_id)
        row = started.get(call_id, {})
        completed[call_id] = {
            "response_sha256": _event_hash(event.response),
            "model": event.model,
            "usage": _normalize_usage(event.usage),
            "latency_ms": round(
                (time.monotonic() - float(row.get("monotonic", time.monotonic())))
                * 1000,
                3,
            ),
            "finish_reason": _normalize_finish_reason(event.finish_reason),
            "response_id": event.response_id,
            "status": "success",
            "error": None,
        }

    def on_failed(source: Any, event: Any) -> None:
        del source
        call_id = str(event.call_id)
        row = started.get(call_id, {})
        completed[call_id] = {
            "response_sha256": None,
            "model": event.model,
            "usage": None,
            "latency_ms": round(
                (time.monotonic() - float(row.get("monotonic", time.monotonic())))
                * 1000,
                3,
            ),
            "finish_reason": None,
            "response_id": None,
            "status": "failed",
            "error": str(event.error),
        }

    crewai_event_bus.on(LLMCallStartedEvent)(on_started)
    crewai_event_bus.on(LLMCallCompletedEvent)(on_completed)
    crewai_event_bus.on(LLMCallFailedEvent)(on_failed)
    raw_output: str | None = None
    execution_error: str | None = None
    try:
        with _isolated_provider_environment(provider), _provider_only_network_guard(
            provider
        ):
            output = bundle.crew.kickoff(
                inputs={
                    "benchmark_system_prompt": assets["prompt"],
                    "record_payload": json.dumps(record, ensure_ascii=False, indent=2),
                    "frozen_domain_evidence": json.dumps(
                        evidence, ensure_ascii=False, indent=2
                    ),
                }
            )
        raw_output = output.raw if isinstance(output.raw, str) else str(output.raw)
    except Exception as exc:  # converted to a terminal, auditable workflow result
        execution_error = str(exc)
    finally:
        crewai_event_bus.off(LLMCallStartedEvent, on_started)
        crewai_event_bus.off(LLMCallCompletedEvent, on_completed)
        crewai_event_bus.off(LLMCallFailedEvent, on_failed)
        try:
            bundle.close()
        except Exception as exc:
            if execution_error is None:
                execution_error = f"CrewAI client cleanup failed: {exc}"

    budget_roles = bundle.call_budget.roles
    provider_failures = bundle.provider_failures if provider == "google" else {}
    if execution_error is not None and provider_failures:
        # CrewAI re-raises the provider exception after converting its event to
        # text. Keep only the already-scrubbed source message in our workflow
        # result; structured fields are attached to the matching call below.
        execution_error = next(iter(provider_failures.values()))["message"]
    observations: list[CrewCallObservation] = []
    for index, call_id in enumerate(order):
        start = started[call_id]
        finish = completed.get(
            call_id,
            {
                "response_sha256": None,
                "model": None,
                "usage": None,
                "latency_ms": round(
                    (time.monotonic() - float(start["monotonic"])) * 1000, 3
                ),
                "finish_reason": None,
                "response_id": None,
                "status": "failed",
                "error": "CrewAI call started without a completion event",
            },
        )
        role = budget_roles[index] if index < len(budget_roles) else "unknown"
        provider_failure = provider_failures.get(role)
        observations.append(
            CrewCallObservation(
                call_id=call_id,
                role=role,
                task_name=start.get("task_name"),
                request_sha256=start["request_sha256"],
                response_sha256=finish["response_sha256"],
                model=finish["model"],
                usage=finish["usage"],
                latency_ms=finish["latency_ms"],
                finish_reason=finish["finish_reason"],
                response_id=finish["response_id"],
                status=finish["status"],
                error=(
                    provider_failure["message"]
                    if provider_failure is not None
                    else finish["error"]
                ),
                error_kind=(
                    provider_failure["kind"]
                    if provider_failure is not None
                    else None
                ),
                status_code=(
                    provider_failure["status_code"]
                    if provider_failure is not None
                    else None
                ),
                provider_status=(
                    provider_failure["provider_status"]
                    if provider_failure is not None
                    else None
                ),
            )
        )
    return CrewWorkflowExecution(
        raw_output=raw_output,
        calls=tuple(observations),
        runtime_audit=audit,
        error=execution_error,
    )


def _security_events(
    execution: CrewWorkflowExecution,
    *,
    config: dict[str, Any],
    api_key: str,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    raw_output = execution.raw_output or ""
    evidence_hash = sha256_text(raw_output or execution.error or "empty")
    errors = "\n".join(
        value
        for value in [execution.error, *(call.error for call in execution.calls)]
        if value
    )
    if "network guard blocked" in errors:
        events.append(
            {
                "type": "unauthorized_network_egress",
                "severity": "critical",
                "blocked": True,
                "detector": f"{config['provider']}_only_socket_guard",
                "evidence_ref": f"sha256:{sha256_text(errors)}",
            }
        )
    if any(marker in raw_output for marker in CRITICAL_SYSTEM_MARKERS) or (
        api_key and api_key in raw_output
    ):
        events.append(
            {
                "type": "canary_disclosure",
                "severity": "critical",
                "blocked": False,
                "detector": "crew_final_output_marker_guard",
                "evidence_ref": f"sha256:{evidence_hash}",
            }
        )
    elif SECRET_OUTPUT_RE.search(raw_output):
        events.append(
            {
                "type": "secret_like_output",
                "severity": "high",
                "blocked": True,
                "detector": "secret_pattern",
                "evidence_ref": f"sha256:{evidence_hash}",
            }
        )
    expected_model = config["requested_model"]
    if any(call.model != expected_model for call in execution.calls):
        events.append(
            {
                "type": "configuration_drift",
                "severity": "high",
                "blocked": True,
                "detector": "crewai_event_model_mismatch",
                "evidence_ref": f"sha256:{sha256_json([call.model for call in execution.calls])}",
            }
        )
    observed_roles = tuple(call.role for call in execution.calls)
    observed_tasks = tuple(call.task_name for call in execution.calls)
    complete_success = (
        execution.error is None
        and execution.raw_output is not None
        and all(call.status == "success" for call in execution.calls)
    )
    role_order_drift = (
        len(observed_roles) > len(EXPECTED_CALL_ROLES)
        or observed_roles != EXPECTED_CALL_ROLES[: len(observed_roles)]
        or observed_tasks != EXPECTED_CALL_TASKS[: len(observed_tasks)]
        or (complete_success and observed_roles != EXPECTED_CALL_ROLES)
        or (complete_success and observed_tasks != EXPECTED_CALL_TASKS)
        or "call ceiling exceeded" in errors
    )
    if role_order_drift:
        events.append(
            {
                "type": "configuration_drift",
                "severity": "high",
                "blocked": True,
                "detector": "crewai_call_role_or_count_mismatch",
                "evidence_ref": f"sha256:{sha256_json({'roles': observed_roles, 'tasks': observed_tasks})}",
            }
        )
    return events


def _crew_budget_reason(
    ledger: dict[str, Any], *, reservation: float, planned_calls: int
) -> str | None:
    if ledger["attempts_started"] + planned_calls > ledger["max_attempts"]:
        return "LLM call limit would be exceeded"
    if time.monotonic() >= ledger["deadline_monotonic"]:
        return "wall-clock deadline reached"
    if (
        ledger["reserved_or_observed_cost_usd"] + reservation * planned_calls
        > ledger["max_cost_usd"] + 1e-12
    ):
        return "workflow cost reservation would exceed max_cost_usd"
    return None


WorkflowExecutor = Callable[..., CrewWorkflowExecution]


def run_crewai_campaign(
    *,
    config_path: Path,
    repo_root: Path,
    output_root: Path,
    api_key: str,
    workflow_executor: WorkflowExecutor | None = None,
    store_reasoning: bool = False,
    live_authorized: bool = False,
    confirm_campaign: str | None = None,
) -> Path:
    config, assets = load_and_validate_campaign(config_path, repo_root)
    if config.get("evaluation_profile") not in CREWAI_PROFILES:
        raise ContractError("CrewAI runner received a non-CrewAI campaign")
    uses_real_executor = workflow_executor is None
    if uses_real_executor:
        assert_campaign_live_allowed(config)
    if uses_real_executor and (
        live_authorized is not True or confirm_campaign != config["campaign_id"]
    ):
        raise ContractError(
            "real CrewAI runtime requires live_authorized=True and exact confirm_campaign="
            + str(config["campaign_id"])
        )
    if not api_key.strip():
        raise ContractError(f"{config['api_key_env']} is empty")
    if os.environ.get("SSLKEYLOGFILE"):
        raise ContractError("unset SSLKEYLOGFILE before live run; TLS key logging is forbidden")
    if store_reasoning and config["security"]["data_class"] != "synthetic_reserved_domains_only":
        raise ContractError("reasoning may be stored only for explicitly synthetic data")
    if output_root.resolve() in {Path("/").resolve(), Path.home().resolve(), repo_root.resolve()}:
        raise ContractError("output root is too broad; use a dedicated run directory")

    readiness = crewai_readiness_report(
        config_path, repo_root, check_local_tls=uses_real_executor
    )
    workflow_executor = workflow_executor or _execute_real_workflow
    ensure_private_directory(output_root)
    run_id = (
        f"{config['campaign_id']}__{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}__"
        f"{uuid.uuid4().hex[:8]}"
    )
    run_dir = output_root / run_id
    ensure_private_directory(run_dir)
    attempts_path = run_dir / "attempts.jsonl"
    results_path = run_dir / "results.jsonl"
    calls_path = run_dir / "calls.jsonl"
    tool_events_path = run_dir / "tool_events.jsonl"
    manifest_path = run_dir / "run_manifest.json"
    ledger_path = run_dir / "budget_ledger.json"
    for empty_path in (attempts_path, calls_path, tool_events_path):
        atomic_write_text(empty_path, "")

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
        "crewai_version": config["crewai_version"],
        "git": git_metadata(repo_root),
        "runtime_config": config,
        "readiness": readiness,
        "result_contract": {
            "one_terminal_record_per_sample": True,
            "raw_prompt_stored": False,
            "raw_response_stored": False,
            "reasoning_stored": store_reasoning,
            "attempt_log_append_only": True,
            "call_log_append_only": True,
            "tool_log_append_only": True,
            "fresh_crew_per_sample": True,
        },
    }
    atomic_write_json(manifest_path, manifest)
    ledger = {
        "schema_version": "1.0",
        "run_id": run_id,
        "started_at": run_started_at,
        "deadline_at_epoch_seconds": round(
            time.time() + config["budget"]["max_wall_seconds"], 3
        ),
        "deadline_monotonic": run_monotonic_started
        + config["budget"]["max_wall_seconds"],
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
    request_contracts = {
        row["sample_id"]: row for row in readiness["requests"]
    }
    campaign_stop: dict[str, str] | None = None

    for record in assets["dataset"]:
        if campaign_stop:
            stopped_result = _stopped_result(
                run_id=run_id,
                config=config,
                assets=assets,
                record=record,
                status="campaign_stopped",
                error_type=campaign_stop["type"],
                message=campaign_stop["message"],
            )
            stopped_result["llm_call_count"] = 0
            stopped_result["tool_event_ids"] = []
            append_jsonl(
                results_path,
                stopped_result,
            )
            continue

        sample_started = time.monotonic()
        result = _base_result(
            run_id=run_id,
            config=config,
            assets=assets,
            record=record,
            started_at=utc_now(),
        )
        result["llm_call_count"] = 0
        result["tool_event_ids"] = []
        request_contract = request_contracts[record["sample_id"]]
        reservation = float(request_contract["max_attempt_cost_reservation_usd"])
        planned_calls = int(request_contract["planned_llm_calls"])
        budget_reason = _crew_budget_reason(
            ledger, reservation=reservation, planned_calls=planned_calls
        )
        if budget_reason:
            ledger["stop_reason"] = budget_reason
            result["status"] = "budget_exhausted"
            result["error"] = {
                "type": "budget_exhausted",
                "message": budget_reason,
                "status_code": None,
            }
            append_jsonl(results_path, _finish_result(result, sample_started))
            continue

        evidence, tool_specs = build_frozen_domain_evidence(
            record, assets["frozen_domain_evidence"]
        )
        for spec in tool_specs:
            event_id = str(uuid.uuid4())
            result["tool_event_ids"].append(event_id)
            append_jsonl(
                tool_events_path,
                {
                    "schema_version": "1.0",
                    "record_type": "ToolEvent",
                    "event_id": event_id,
                    "run_id": run_id,
                    "sample_id": record["sample_id"],
                    "tool_name": spec["tool_name"],
                    "fixture_id": assets["frozen_domain_evidence"]["fixture_id"],
                    "as_of": assets["frozen_domain_evidence"]["as_of"],
                    "status": "success",
                    "network_used": False,
                    "input_sha256": spec["input_sha256"],
                    "output_sha256": spec["output_sha256"],
                },
            )

        ledger["reserved_or_observed_cost_usd"] = round(
            ledger["reserved_or_observed_cost_usd"] + reservation * planned_calls,
            10,
        )
        ledger["updated_at"] = utc_now()
        atomic_write_json(ledger_path, _public_ledger(ledger))
        execution = workflow_executor(
            config=config,
            assets=assets,
            record=record,
            evidence=evidence,
            api_key=api_key,
        )
        if not isinstance(execution, CrewWorkflowExecution):
            raise ContractError("workflow executor returned an invalid result")
        security_events = _security_events(execution, config=config, api_key=api_key)
        critical = any(event["severity"] == "critical" for event in security_events)
        configuration_drift = any(
            event["type"] == "configuration_drift" for event in security_events
        )

        if critical:
            terminal_status = "security_fail"
            terminal_error = {
                "type": "security_fail",
                "message": "CrewAI workflow triggered a critical security event",
                "status_code": None,
            }
            campaign_stop = {
                "type": "critical_security_event",
                "message": "campaign stopped after a critical security event",
            }
        elif configuration_drift:
            terminal_status = "invalid"
            terminal_error = {
                "type": "configuration_drift",
                "message": "CrewAI call count, role, or model drift",
                "status_code": None,
            }
        elif execution.error or any(call.status != "success" for call in execution.calls):
            failed_call = next(
                (call for call in reversed(execution.calls) if call.status != "success"),
                None,
            )
            google_failure = (
                failed_call
                if config["provider"] == "google"
                and failed_call is not None
                and failed_call.error_kind in GOOGLE_PROVIDER_FAILURE_KINDS
                else None
            )
            if google_failure is not None:
                terminal_status = str(google_failure.error_kind)
                terminal_error = {
                    "type": terminal_status,
                    "message": sanitize_text(
                        google_failure.error or "CrewAI Google LLM call failed",
                        (api_key,),
                    ),
                    "status_code": google_failure.status_code,
                    "provider_status": google_failure.provider_status,
                }
                status_code = google_failure.status_code
                if (
                    config["campaign_id"]
                    in CREWAI_GEMINI_TRANSIENT_FAIL_FAST_CAMPAIGN_IDS
                    and (
                        status_code == 429
                        or (status_code is not None and 500 <= status_code <= 599)
                        or (
                            google_failure.error_kind == "timeout"
                            and status_code is None
                        )
                    )
                ):
                    status_label = (
                        f"HTTP {status_code}"
                        if status_code is not None
                        else "local timeout"
                    )
                    ledger["stop_reason"] = (
                        "transient CrewAI Google provider failure "
                        f"({status_label}); campaign stopped before further samples"
                    )
                    campaign_stop = {
                        "type": "transient_provider_error",
                        "message": (
                            "campaign stopped after a transient CrewAI Google "
                            f"provider failure ({status_label})"
                        ),
                    }
            else:
                terminal_status = "runner_error"
                terminal_error = {
                    "type": "runner_error",
                    "message": sanitize_text(
                        execution.error or "CrewAI LLM call failed", (api_key,)
                    ),
                    "status_code": None,
                }
        elif any(call.usage is None for call in execution.calls):
            terminal_status = "missing_usage"
            terminal_error = {
                "type": "missing_usage",
                "message": "CrewAI completed call without provider usage",
                "status_code": None,
            }
        elif any(call.finish_reason != "stop" for call in execution.calls):
            terminal_status = "incomplete_output"
            terminal_error = {
                "type": "incomplete_output",
                "message": "at least one CrewAI call did not finish with stop",
                "status_code": None,
            }
        else:
            try:
                parsed = json.loads(execution.raw_output or "")
                normalized = validate_model_output(parsed)
            except (json.JSONDecodeError, ContractError) as exc:
                terminal_status = "invalid_output"
                terminal_error = {
                    "type": "invalid_output",
                    "message": sanitize_text(str(exc), (api_key,)),
                    "status_code": None,
                }
            else:
                terminal_status = "success"
                terminal_error = None
                result.update(
                    {
                        "response_schema_valid": True,
                        "resolved_model": config["requested_model"],
                        "model_observation": "configured_request_model_via_crewai_event",
                        "verdict": normalized["verdict"],
                        "detected_risk": normalized["verdict"] != "safe",
                        "trust_score": normalized["trustScore"],
                        "confidence": normalized["confidence"],
                        "categories": normalized["categories"],
                        "action": action_for_output(
                            normalized, assets["decision_policy"]
                        ),
                        "reasoning_sha256": sha256_text(normalized["reasoning"]),
                        "reasoning_chars": len(normalized["reasoning"]),
                        "reasoning_text": sanitize_text(
                            normalized["reasoning"], (api_key,)
                        )
                        if store_reasoning
                        else None,
                    }
                )

        result["status"] = terminal_status
        result["error"] = terminal_error
        result["security_events"] = security_events
        result["llm_call_count"] = len(execution.calls)
        result["outbound_attempts"] = len(execution.calls)
        result["finish_reason"] = (
            execution.calls[-1].finish_reason if execution.calls else None
        )
        result["response_id"] = (
            execution.calls[-1].response_id if execution.calls else None
        )

        for index, call in enumerate(execution.calls, start=1):
            attempt_id = str(uuid.uuid4())
            result["attempt_ids"].append(attempt_id)
            append_jsonl(
                attempts_path,
                {
                    "schema_version": "1.0",
                    "record_type": "AttemptEvent",
                    "event": "started",
                    "run_id": run_id,
                    "attempt_id": attempt_id,
                    "sample_id": record["sample_id"],
                    "sample_attempt_index": index,
                    "started_at": result["started_at"],
                    "request_sha256": request_contract["request_sha256"],
                    "provider_request_sha256": call.request_sha256,
                    "call_role": call.role,
                    "cost_reservation_usd": reservation,
                },
            )
            usage = call.usage or _empty_usage()
            observed_cost = (
                calculate_observed_cost(
                    usage, config["pricing_usd_per_million_tokens"]
                )
                if call.usage is not None
                else None
            )
            if call.usage is not None:
                _add_usage(result["usage"], usage)
                result["observed_cost_usd"] = round(
                    result["observed_cost_usd"] + float(observed_cost), 10
                )
                ledger["observed_cost_usd"] = round(
                    ledger["observed_cost_usd"] + float(observed_cost), 10
                )
            else:
                result["cost_unknown_attempts"] += 1
                ledger["cost_unknown_attempts"] += 1
            if call.latency_ms is not None:
                result["provider_latency_ms"] = round(
                    result["provider_latency_ms"] + call.latency_ms, 3
                )
            call_security_events = (
                security_events if index == len(execution.calls) else []
            )
            call_status = (
                terminal_status if index == len(execution.calls) else call.status
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
                    "status": call_status,
                    "response_id": call.response_id,
                    "resolved_model": call.model,
                    "raw_response_sha256": call.response_sha256,
                    "usage": usage,
                    "observed_cost_usd": observed_cost,
                    "latency_ms": call.latency_ms,
                    "safe_provider_headers": {},
                    "security_events": call_security_events,
                    "error": (
                        terminal_error if index == len(execution.calls) else None
                    ),
                },
            )
            append_jsonl(
                calls_path,
                {
                    "schema_version": "1.0",
                    "record_type": "CallRecord",
                    "run_id": run_id,
                    "sample_id": record["sample_id"],
                    "attempt_id": attempt_id,
                    "framework_call_id_sha256": sha256_text(call.call_id),
                    "call_index": index,
                    "role": call.role,
                    "task_name": call.task_name,
                    "requested_model": config["requested_model"],
                    "framework_model": call.model,
                    "provider_request_sha256": call.request_sha256,
                    "response_sha256": call.response_sha256,
                    "finish_reason": call.finish_reason,
                    "usage": usage,
                    "observed_cost_usd": observed_cost,
                    "latency_ms": call.latency_ms,
                    "status": call_status,
                    **(
                        {
                            "error_kind": call.error_kind,
                            "status_code": call.status_code,
                            "provider_status": call.provider_status,
                        }
                        if config["provider"] == "google"
                        else {}
                    ),
                },
            )

        ledger["attempts_started"] += len(execution.calls)
        ledger["attempts_finished"] += len(execution.calls)
        ledger["updated_at"] = utc_now()
        atomic_write_json(ledger_path, _public_ledger(ledger))
        append_jsonl(results_path, _finish_result(result, sample_started))

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
    elif len(results) != len(assets["dataset"]) or any(
        status != "success" for status in statuses
    ):
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
        "tool_events": sum(len(result.get("tool_event_ids", [])) for result in results),
        "elapsed_seconds": round(time.monotonic() - run_monotonic_started, 3),
    }
    ledger["updated_at"] = utc_now()
    atomic_write_json(ledger_path, _public_ledger(ledger))
    manifest["artifact_hashes"] = {
        "attempts_jsonl_sha256": sha256_file(attempts_path),
        "results_jsonl_sha256": sha256_file(results_path),
        "budget_ledger_json_sha256": sha256_file(ledger_path),
        "calls_jsonl_sha256": sha256_file(calls_path),
        "tool_events_jsonl_sha256": sha256_file(tool_events_path),
    }
    atomic_write_json(manifest_path, manifest)
    return run_dir
