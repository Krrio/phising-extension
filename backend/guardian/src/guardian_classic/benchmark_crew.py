"""Hardened CrewAI construction used only by the offline benchmark track.

The production ``GuardianClassic`` crew intentionally remains unchanged.  This
module makes every benchmark-relevant CrewAI default explicit and supplies a
shared call counter that blocks a fourth LLM call before it can reach the
provider.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import sqlite3
import ssl
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Literal
from unittest.mock import patch

from crewai import Agent, Crew, LLM, Process, Task
from crewai.llms.base_llm import BaseLLM
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


EXPECTED_AGENT_KEYS = ("domain_analyst", "content_analyst", "orchestrator")
EXPECTED_TASK_KEYS = ("domain_analysis", "content_analysis", "synthesis")
_ORIGINAL_SQLITE_CONNECT = sqlite3.connect
_STRUCTURED_PROVIDER_FAILURE_KINDS = frozenset(
    {"rate_limit", "timeout", "provider_http_error"}
)


@dataclass(frozen=True)
class BenchmarkProviderFailure:
    """Secret-free provider failure captured before CrewAI stringifies it."""

    kind: str
    status_code: int | None
    provider_status: str | None
    message: str

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "status_code": self.status_code,
            "provider_status": self.provider_status,
            "message": self.message,
        }


def _secret_free_text(value: Any, *, api_key: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    sanitized = value.replace(api_key, "[REDACTED]") if api_key else value
    sanitized = " ".join(sanitized.split())
    return sanitized[:1_000] or None


def _google_failure_from_exception(
    error: Exception, *, api_key: str | None
) -> BenchmarkProviderFailure:
    """Classify Google/API failures from attributes, never their text repr."""

    # google-genai ``APIError`` publishes the HTTP code directly. HTTPX HTTP
    # errors instead expose it on ``response``. Deliberately do not coerce a
    # textual value: that would reintroduce exception-string parsing.
    code = getattr(error, "code", None)
    status_code = code if isinstance(code, int) and not isinstance(code, bool) else None
    if status_code is None:
        response = getattr(error, "response", None)
        response_code = getattr(response, "status_code", None)
        if isinstance(response_code, int) and not isinstance(response_code, bool):
            status_code = response_code

    try:
        from httpx import TimeoutException
    except ImportError:  # pragma: no cover - CrewAI's Gemini extra requires HTTPX
        timeout_types: tuple[type[BaseException], ...] = (TimeoutError,)
    else:
        timeout_types = (TimeoutError, TimeoutException)

    if status_code == 429:
        kind = "rate_limit"
    elif status_code == 504 or isinstance(error, timeout_types):
        kind = "timeout"
    elif status_code is not None or any(
        hasattr(error, field) for field in ("code", "status", "message")
    ):
        kind = "provider_http_error"
    else:
        kind = "runner_error"

    provider_status = _secret_free_text(
        getattr(error, "status", None), api_key=api_key
    )
    message = _secret_free_text(getattr(error, "message", None), api_key=api_key)
    if message is None:
        message = (
            "Google Gemini request timed out"
            if kind == "timeout"
            else "Google Gemini provider call failed"
            if kind != "runner_error"
            else "CrewAI Google LLM call failed"
        )
    return BenchmarkProviderFailure(
        kind=kind,
        status_code=status_code,
        provider_status=provider_status,
        message=message,
    )


class BenchmarkVerdict(BaseModel):
    """Native Gemini structured output matching the frozen benchmark schema."""

    model_config = ConfigDict(extra="forbid")

    trustScore: int = Field(ge=0, le=100)
    verdict: Literal["safe", "suspicious", "phishing"]
    confidence: float = Field(ge=0, le=1)
    reasoning: str
    categories: list[
        Literal[
            "credential_request",
            "urgency",
            "impersonation",
            "suspicious_link",
            "suspicious_domain",
            "financial",
        ]
    ]
    policyAssessment: None


class _ClosingSQLiteConnection(sqlite3.Connection):
    """Work around CrewAI 1.15.8 SQLite contexts not closing on Python 3.13."""

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc, traceback))
        finally:
            self.close()


def _closing_sqlite_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
    kwargs.setdefault("factory", _ClosingSQLiteConnection)
    return _ORIGINAL_SQLITE_CONNECT(*args, **kwargs)


class EphemeralTaskOutputHandler:
    """In-memory replacement for CrewAI's implicit kickoff SQLite store."""

    def __init__(self) -> None:
        self._rows: list[dict[str, Any]] = []

    def update(self, task_index: int, log: dict[str, Any]) -> None:
        self._rows = [
            row for row in self._rows if row.get("task_index") != task_index
        ]
        task = log["task"]
        self._rows.append(
            {
                "task_id": str(task.id),
                "expected_output": task.expected_output,
                "output": log["output"],
                "task_index": task_index,
                "inputs": log.get("inputs", {}),
                "was_replayed": bool(log.get("was_replayed", False)),
            }
        )

    def add(
        self,
        task: Task,
        output: dict[str, Any],
        task_index: int,
        inputs: dict[str, Any] | None = None,
        was_replayed: bool = False,
    ) -> None:
        self.update(
            task_index,
            {
                "task": task,
                "output": output,
                "inputs": inputs or {},
                "was_replayed": was_replayed,
            },
        )

    def reset(self) -> None:
        self._rows.clear()

    def load(self) -> list[dict[str, Any]]:
        return sorted(self._rows, key=lambda row: int(row["task_index"]))


@dataclass
class BenchmarkCallBudget:
    """Thread-safe logical LLM-call ceiling shared by all three agents."""

    max_calls: int
    _used: int = 0
    _roles: list[str] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def consume(self, role: str) -> None:
        with self._lock:
            if self._used >= self.max_calls:
                raise RuntimeError(
                    "CrewAI benchmark LLM call ceiling exceeded before provider request"
                )
            self._used += 1
            self._roles.append(role)

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    @property
    def roles(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._roles)


class GuardedBenchmarkLLM(BaseLLM):
    """Hard call guard around an explicitly constructed ``crewai.LLM``."""

    timeout: float | int | None = None
    _call_budget: BenchmarkCallBudget = PrivateAttr()
    _benchmark_role: str = PrivateAttr()
    _delegate: BaseLLM = PrivateAttr()
    _provider_failure: BenchmarkProviderFailure | None = PrivateAttr(default=None)

    def __init__(
        self,
        *,
        call_budget: BenchmarkCallBudget,
        benchmark_role: str,
        delegate: BaseLLM,
        **data: Any,
    ) -> None:
        super().__init__(**data)
        self._call_budget = call_budget
        self._benchmark_role = benchmark_role
        self._delegate = delegate

    def call(self, *args: Any, **kwargs: Any) -> Any:
        self._call_budget.consume(self._benchmark_role)
        self._provider_failure = None
        try:
            return self._delegate.call(*args, **kwargs)
        except Exception as exc:
            if getattr(self._delegate, "provider", None) == "gemini":
                failure = _google_failure_from_exception(
                    exc,
                    api_key=(self.api_key if isinstance(self.api_key, str) else None),
                )
                if failure.kind in _STRUCTURED_PROVIDER_FAILURE_KINDS:
                    self._provider_failure = failure
            raise

    async def acall(self, *args: Any, **kwargs: Any) -> Any:
        self._call_budget.consume(self._benchmark_role)
        self._provider_failure = None
        try:
            return await self._delegate.acall(*args, **kwargs)
        except Exception as exc:
            if getattr(self._delegate, "provider", None) == "gemini":
                failure = _google_failure_from_exception(
                    exc,
                    api_key=(self.api_key if isinstance(self.api_key, str) else None),
                )
                if failure.kind in _STRUCTURED_PROVIDER_FAILURE_KINDS:
                    self._provider_failure = failure
            raise

    def supports_stop_words(self) -> bool:
        return self._delegate.supports_stop_words()

    def supports_multimodal(self) -> bool:
        return self._delegate.supports_multimodal()

    def get_context_window_size(self) -> int:
        return self._delegate.get_context_window_size()

    @property
    def delegate(self) -> BaseLLM:
        return self._delegate

    @property
    def benchmark_role(self) -> str:
        return self._benchmark_role

    @property
    def provider_failure(self) -> dict[str, Any] | None:
        if self._provider_failure is None:
            return None
        return self._provider_failure.as_public_dict()


@dataclass(frozen=True)
class BenchmarkCrewBundle:
    crew: Crew
    call_budget: BenchmarkCallBudget

    @property
    def provider_failures(self) -> dict[str, dict[str, Any]]:
        failures: dict[str, dict[str, Any]] = {}
        for agent in self.crew.agents:
            llm = agent.llm
            if not isinstance(llm, GuardedBenchmarkLLM):
                continue
            failure = llm.provider_failure
            if failure is not None:
                failures[llm.benchmark_role] = failure
        return failures

    def close(self) -> None:
        """Close eager provider clients and scrub their credential references."""

        for agent in self.crew.agents:
            llm = agent.llm
            if not isinstance(llm, GuardedBenchmarkLLM):
                continue
            delegate = llm.delegate
            if getattr(delegate, "provider", None) == "gemini":
                # google-genai exposes sync and async transports through the
                # same Client. Both must be closed explicitly.
                client = getattr(delegate, "_client", None)
                if client is not None:
                    client.close()
                    close_result = client.aio.aclose()
                    if inspect.isawaitable(close_result):
                        asyncio.run(close_result)
                    delegate._client = None
                delegate.api_key = None
                llm.api_key = None
                continue
            sync_client = getattr(delegate, "_client", None)
            if sync_client is not None:
                sync_client.close()
                delegate._client = None
            async_client = getattr(delegate, "_async_client", None)
            if async_client is not None:
                close_result = async_client.close()
                if inspect.isawaitable(close_result):
                    asyncio.run(close_result)
                delegate._async_client = None
            delegate.api_key = None
            llm.api_key = None
        self.crew._task_output_handler.reset()


def _agent(
    *,
    definition: dict[str, Any],
    llm: GuardedBenchmarkLLM,
    execution_timeout_seconds: int,
) -> Agent:
    return Agent(
        role=definition["role"],
        goal=definition["goal"],
        backstory=definition["backstory"],
        llm=llm,
        tools=[],
        verbose=False,
        cache=False,
        memory=False,
        allow_delegation=False,
        allow_code_execution=False,
        max_iter=1,
        max_retry_limit=0,
        max_execution_time=execution_timeout_seconds,
        respect_context_window=False,
        reasoning=False,
        planning=False,
        inject_date=False,
        guardrail=None,
        guardrail_max_retries=0,
    )


def build_benchmark_crew(
    *,
    api_key: str,
    requested_model: str,
    temperature: float | None,
    max_output_tokens: int,
    request_timeout_seconds: float,
    max_llm_calls: int,
    response_schema: dict[str, Any],
    profile: dict[str, Any],
    provider: str = "openai",
    thinking_level: str | None = None,
    reasoning_effort: str | None = None,
    tls_context: ssl.SSLContext | None = None,
) -> BenchmarkCrewBundle:
    """Build one fresh, memoryless three-agent crew for one sample."""

    agents_config = profile["agents"]
    tasks_config = profile["tasks"]
    if tuple(agents_config) != EXPECTED_AGENT_KEYS:
        raise ValueError("benchmark crew agent order/profile drift")
    if tuple(tasks_config) != EXPECTED_TASK_KEYS:
        raise ValueError("benchmark crew task order/profile drift")
    if max_llm_calls != 3:
        raise ValueError("benchmark crew requires exactly three allowed LLM calls")
    expected_schema = response_schema.get("json_schema", {}).get("schema", {})
    if (
        response_schema.get("type") != "json_schema"
        or response_schema.get("json_schema", {}).get("strict") is not True
        or expected_schema.get("additionalProperties") is not False
        or set(expected_schema.get("properties", {}))
        != {
            "trustScore",
            "verdict",
            "confidence",
            "reasoning",
            "categories",
            "policyAssessment",
        }
        or expected_schema.get("required")
        != [
            "trustScore",
            "verdict",
            "confidence",
            "reasoning",
            "categories",
            "policyAssessment",
        ]
    ):
        raise ValueError("benchmark response format differs from frozen schema")

    call_budget = BenchmarkCallBudget(max_calls=max_llm_calls)
    model = requested_model

    def make_llm(role: str, *, structured: bool) -> GuardedBenchmarkLLM:
        if provider == "google":
            expected_thinking_level = (
                "low" if model == "gemini-3.7-flash" else "minimal"
            )
            if (
                temperature is not None
                or thinking_level != expected_thinking_level
                or reasoning_effort is not None
            ):
                raise ValueError("native Gemini benchmark generation profile drift")
            if tls_context is None:
                raise ValueError("native Gemini benchmark requires a verified TLS context")
            if (
                not tls_context.check_hostname
                or tls_context.verify_mode != ssl.CERT_REQUIRED
                or int(tls_context.cert_store_stats().get("x509_ca", 0)) <= 0
            ):
                raise ValueError("native Gemini benchmark TLS verification drift")

            import httpx
            from google.genai import types

            # A custom async HTTPX transport disables google-genai's optional
            # aiohttp path (whose session otherwise hard-codes trust_env=True).
            # The SDK still owns and closes the AsyncClient and its transport.
            async_transport = httpx.AsyncHTTPTransport(
                verify=tls_context,
                retries=0,
            )
            http_options = types.HttpOptions(
                api_version="v1",
                timeout=int(request_timeout_seconds * 1000),
                retry_options=types.HttpRetryOptions(attempts=1),
                client_args={
                    "verify": tls_context,
                    "trust_env": False,
                    "follow_redirects": False,
                },
                async_client_args={
                    "verify": tls_context,
                    "trust_env": False,
                    "follow_redirects": False,
                    "transport": async_transport,
                },
                # google-genai 1.65.0 does not yet type this new root field,
                # but HttpOptions.extra_body is recursively merged into the
                # GenerateContent request body.
                extra_body={"store": False},
            )
            thinking_enum = getattr(
                types.ThinkingLevel, expected_thinking_level.upper()
            )
            thinking_config = types.ThinkingConfig(
                thinking_level=thinking_enum,
                include_thoughts=False,
            )
            delegate = LLM(
                model=model,
                provider="gemini",
                api_key=api_key,
                temperature=None,
                max_output_tokens=max_output_tokens,
                stream=False,
                response_format=BenchmarkVerdict if structured else None,
                thinking_config=thinking_config,
                client_params={"http_options": http_options},
                use_vertexai=False,
            )
            return GuardedBenchmarkLLM(
                call_budget=call_budget,
                benchmark_role=role,
                delegate=delegate,
                model=model,
                provider="gemini",
                api_key=api_key,
                temperature=None,
                max_tokens=max_output_tokens,
                timeout=request_timeout_seconds,
                stream=False,
                additional_params={
                    "api": "native_generate_content_v1",
                    "provider_max_attempts": 1,
                    "store": False,
                    "thinking_level": expected_thinking_level,
                    "include_thoughts": False,
                    "use_vertexai": False,
                },
            )

        if provider != "openai":
            raise ValueError(f"unsupported benchmark provider: {provider}")
        is_gpt54 = model in {
            "gpt-5.4-nano-2026-03-17",
            "gpt-5.4-mini-2026-03-17",
        }
        expected_reasoning_effort = "none" if is_gpt54 else None
        if (
            temperature != 0
            or thinking_level is not None
            or reasoning_effort != expected_reasoning_effort
            or tls_context is not None
        ):
            raise ValueError("native OpenAI benchmark generation profile drift")
        # Send the exact frozen Direct schema instead of letting CrewAI add
        # Pydantic titles/descriptions that would change the comparison bundle.
        provider_params: dict[str, Any] = {"store": False}
        if is_gpt54:
            # CrewAI 1.15.8 recognizes reasoning_effort only for legacy o1 names.
            # additional_params is merged into the real Chat Completions payload,
            # so pin the supported GPT-5.4 value explicitly at the wire boundary.
            provider_params["reasoning_effort"] = "none"
        if structured:
            # OpenAICompletion 1.15.8's typed ``response_format`` field rejects
            # a json_schema dict even though its request builder supports one.
            # additional_params is merged into the actual provider payload.
            provider_params["response_format"] = response_schema
        token_limit_kwargs = (
            {"max_completion_tokens": max_output_tokens}
            if is_gpt54
            else {"max_tokens": max_output_tokens}
        )
        delegate = LLM(
            model=model,
            provider="openai",
            api_key=api_key,
            base_url="https://api.openai.com/v1",
            custom_openai=True,
            temperature=temperature,
            timeout=request_timeout_seconds,
            stream=False,
            max_retries=0,
            store=False,
            api="completions",
            additional_params=provider_params,
            **token_limit_kwargs,
        )
        outer_params: dict[str, Any] = {"max_retries": 0, "store": False}
        if is_gpt54:
            outer_params.update(
                {
                    "reasoning_effort": "none",
                    "token_limit_field": "max_completion_tokens",
                }
            )
        return GuardedBenchmarkLLM(
            call_budget=call_budget,
            benchmark_role=role,
            delegate=delegate,
            model=model,
            provider="openai",
            api_key=api_key,
            base_url="https://api.openai.com/v1",
            temperature=temperature,
            max_tokens=max_output_tokens,
            timeout=request_timeout_seconds,
            stream=False,
            additional_params=outer_params,
        )

    domain_agent = _agent(
        definition=agents_config["domain_analyst"],
        llm=make_llm("domain_analyst", structured=False),
        execution_timeout_seconds=int(request_timeout_seconds),
    )
    content_agent = _agent(
        definition=agents_config["content_analyst"],
        llm=make_llm("content_analyst", structured=False),
        execution_timeout_seconds=int(request_timeout_seconds),
    )
    orchestrator_agent = _agent(
        definition=agents_config["orchestrator"],
        llm=make_llm("orchestrator", structured=True),
        execution_timeout_seconds=int(request_timeout_seconds),
    )

    domain_task = Task(
        name="domain_analysis",
        description=tasks_config["domain_analysis"]["description"],
        expected_output=tasks_config["domain_analysis"]["expected_output"],
        agent=domain_agent,
        tools=[],
        async_execution=False,
        output_json=None,
        output_pydantic=None,
        guardrail=None,
        guardrails=None,
        guardrail_max_retries=0,
    )
    content_task = Task(
        name="content_analysis",
        description=tasks_config["content_analysis"]["description"],
        expected_output=tasks_config["content_analysis"]["expected_output"],
        agent=content_agent,
        tools=[],
        async_execution=False,
        output_json=None,
        output_pydantic=None,
        guardrail=None,
        guardrails=None,
        guardrail_max_retries=0,
    )
    synthesis_task = Task(
        name="synthesis",
        description=tasks_config["synthesis"]["description"],
        expected_output=tasks_config["synthesis"]["expected_output"],
        agent=orchestrator_agent,
        context=[domain_task, content_task],
        tools=[],
        async_execution=False,
        output_json=None,
        output_pydantic=None,
        guardrail=None,
        guardrails=None,
        guardrail_max_retries=0,
    )
    # CrewAI constructs a SQLite task-output handler even with memory=False.
    # Close its one initialization connection, then replace it before kickoff
    # so no task prompt/output is persisted outside benchmark artifacts.
    with patch.object(sqlite3, "connect", _closing_sqlite_connect):
        benchmark_crew = Crew(
            name="Guardian CrewAI Offline Benchmark",
            agents=[domain_agent, content_agent, orchestrator_agent],
            tasks=[domain_task, content_task, synthesis_task],
            process=Process.sequential,
            verbose=False,
            memory=False,
            cache=False,
            planning=False,
            share_crew=False,
            tracing=False,
            stream=False,
        )
    benchmark_crew._task_output_handler = EphemeralTaskOutputHandler()
    return BenchmarkCrewBundle(crew=benchmark_crew, call_budget=call_budget)


def audit_benchmark_crew(
    bundle: BenchmarkCrewBundle, *, expected_max_output_tokens: int = 500
) -> dict[str, Any]:
    """Assert and return the effective no-hidden-capability runtime profile."""

    if (
        isinstance(expected_max_output_tokens, bool)
        or not isinstance(expected_max_output_tokens, int)
        or expected_max_output_tokens <= 0
    ):
        raise ValueError("expected_max_output_tokens must be a positive integer")

    benchmark_crew = bundle.crew
    if (
        benchmark_crew.process != Process.sequential
        or benchmark_crew.memory is not False
        or benchmark_crew.cache is not False
        or benchmark_crew.planning is not False
        or benchmark_crew.share_crew is not False
        or benchmark_crew.tracing is not False
        or benchmark_crew.stream is not False
        or len(benchmark_crew.agents) != 3
        or len(benchmark_crew.tasks) != 3
        or not isinstance(
            benchmark_crew._task_output_handler, EphemeralTaskOutputHandler
        )
    ):
        raise ValueError("effective CrewAI crew profile drift")

    agent_rows: list[dict[str, Any]] = []
    for expected_key, agent in zip(EXPECTED_AGENT_KEYS, benchmark_crew.agents, strict=True):
        llm = agent.llm
        if not isinstance(llm, GuardedBenchmarkLLM):
            raise ValueError("benchmark agent is missing GuardedBenchmarkLLM")
        if (
            agent.tools
            or agent.allow_delegation
            or agent.allow_code_execution
            or agent.max_iter != 1
            or agent.max_retry_limit != 0
            or agent.respect_context_window
            or agent.reasoning
            or agent.planning
            or agent.inject_date
            or agent.guardrail_max_retries != 0
            or agent.cache
            or agent.memory not in (False, None)
            or llm.stream
            or llm.delegate.model != llm.model
            or llm.delegate.temperature != llm.temperature
            or llm.delegate.stream
        ):
            raise ValueError(f"effective CrewAI agent profile drift: {expected_key}")

        if llm.delegate.provider == "gemini":
            from google.genai import types

            expected_thinking_level = (
                "low" if llm.model == "gemini-3.7-flash" else "minimal"
            )
            expected_thinking_enum = getattr(
                types.ThinkingLevel, expected_thinking_level.upper()
            )
            expected_outer_params = {
                "api": "native_generate_content_v1",
                "provider_max_attempts": 1,
                "store": False,
                "thinking_level": expected_thinking_level,
                "include_thoughts": False,
                "use_vertexai": False,
            }
            response_format = getattr(llm.delegate, "response_format", None)
            expected_response_format = (
                BenchmarkVerdict if expected_key == "orchestrator" else None
            )
            generation_config = llm.delegate._prepare_generation_config(
                response_model=response_format
            )
            wire_response_schema = generation_config.response_json_schema
            structured = expected_key == "orchestrator"
            thinking = getattr(llm.delegate, "thinking_config", None)
            client_params = getattr(llm.delegate, "client_params", None)
            http_options = (
                client_params.get("http_options")
                if isinstance(client_params, dict)
                else None
            )
            client_args = getattr(http_options, "client_args", None)
            async_client_args = getattr(http_options, "async_client_args", None)
            sync_verify = (
                client_args.get("verify") if isinstance(client_args, dict) else None
            )
            async_verify = (
                async_client_args.get("verify")
                if isinstance(async_client_args, dict)
                else None
            )
            native_client = getattr(llm.delegate, "_client", None)
            api_client = getattr(native_client, "_api_client", None)
            effective_http = getattr(api_client, "_http_options", None)
            timeout_seconds = llm.timeout
            valid_timeout = (
                isinstance(timeout_seconds, (int, float))
                and not isinstance(timeout_seconds, bool)
                and timeout_seconds > 0
            )
            expected_timeout_ms = (
                int(float(timeout_seconds) * 1_000) if valid_timeout else None
            )
            wire_probe = (
                api_client._build_request(
                    "post",
                    f"models/{llm.model}:generateContent",
                    {"contents": []},
                )
                if api_client is not None
                else None
            )
            if (
                llm.provider != "gemini"
                or llm.temperature is not None
                or llm.base_url is not None
                or llm.max_tokens != expected_max_output_tokens
                or not valid_timeout
                or agent.max_execution_time != int(float(timeout_seconds))
                or llm.additional_params != expected_outer_params
                or getattr(llm.delegate, "max_output_tokens", None)
                != expected_max_output_tokens
                or getattr(llm.delegate, "use_vertexai", None) is not False
                or getattr(llm.delegate, "project", None) is not None
                or response_format is not expected_response_format
                or generation_config.max_output_tokens != expected_max_output_tokens
                or generation_config.temperature is not None
                or generation_config.tools is not None
                or generation_config.thinking_config is None
                or generation_config.thinking_config.thinking_level
                != expected_thinking_enum
                or generation_config.thinking_config.include_thoughts is not False
                or (generation_config.response_mime_type == "application/json")
                is not structured
                or (isinstance(wire_response_schema, dict)) is not structured
                or generation_config.response_schema is not None
                or not isinstance(thinking, types.ThinkingConfig)
                or thinking.thinking_level != expected_thinking_enum
                or thinking.include_thoughts is not False
                or not isinstance(http_options, types.HttpOptions)
                or http_options.api_version != "v1"
                or http_options.timeout != expected_timeout_ms
                or http_options.extra_body != {"store": False}
                or http_options.retry_options is None
                or http_options.retry_options.attempts != 1
                or not isinstance(client_args, dict)
                or client_args.get("trust_env") is not False
                or client_args.get("follow_redirects") is not False
                or not isinstance(sync_verify, ssl.SSLContext)
                or not sync_verify.check_hostname
                or sync_verify.verify_mode != ssl.CERT_REQUIRED
                or not isinstance(async_client_args, dict)
                or async_client_args.get("trust_env") is not False
                or async_client_args.get("follow_redirects") is not False
                or not isinstance(async_verify, ssl.SSLContext)
                or async_verify is not sync_verify
                or async_client_args.get("transport") is None
                or native_client is None
                or native_client.vertexai
                or effective_http is None
                or effective_http.api_version != "v1"
                or effective_http.timeout != expected_timeout_ms
                or effective_http.extra_body != {"store": False}
                or effective_http.retry_options is None
                or effective_http.retry_options.attempts != 1
                or api_client._use_aiohttp()
                or wire_probe is None
                or wire_probe.url
                != (
                    "https://generativelanguage.googleapis.com/"
                    f"v1/models/{llm.model}:generateContent"
                )
                or not isinstance(wire_probe.data, dict)
                or wire_probe.data.get("store") is not False
            ):
                raise ValueError(
                    f"effective CrewAI Gemini provider profile drift: {expected_key}"
                )
            schema_sha256 = (
                hashlib.sha256(
                    json.dumps(
                        wire_response_schema,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                if structured
                else None
            )
            agent_rows.append(
                {
                    "benchmark_role": expected_key,
                    "crewai_role": agent.role,
                    "model": llm.model,
                    "provider": llm.provider,
                    "api": "native_generate_content_v1",
                    "store": http_options.extra_body["store"],
                    "wire_store_false_verified": True,
                    "provider_max_attempts": http_options.retry_options.attempts,
                    "api_version": http_options.api_version,
                    "use_vertexai": llm.delegate.use_vertexai,
                    "trust_env": client_args["trust_env"],
                    "follow_redirects": client_args["follow_redirects"],
                    "async_transport": "httpx",
                    "max_iter": agent.max_iter,
                    "max_retry_limit": agent.max_retry_limit,
                    "max_execution_time": agent.max_execution_time,
                    "max_tokens": llm.max_tokens,
                    "timeout": llm.timeout,
                    "thinking_level": expected_thinking_level,
                    "include_thoughts": thinking.include_thoughts,
                    "wire_tools": "absent",
                    "response_schema_sha256": schema_sha256,
                    "response_format": (
                        "strict_json_schema"
                        if expected_key == "orchestrator"
                        else "text"
                    ),
                }
            )
            continue

        is_gpt54 = llm.model in {
            "gpt-5.4-nano-2026-03-17",
            "gpt-5.4-mini-2026-03-17",
        }
        expected_outer_params: dict[str, Any] = {
            "max_retries": 0,
            "store": False,
        }
        if is_gpt54:
            expected_outer_params.update(
                {
                    "reasoning_effort": "none",
                    "token_limit_field": "max_completion_tokens",
                }
            )
        delegate_params = getattr(llm.delegate, "additional_params", None)
        prepared = llm.delegate._prepare_completion_params(
            [{"role": "user", "content": "offline benchmark contract probe"}],
            tools=[],
        )
        token_limit_matches = (
            prepared.get("max_completion_tokens") == llm.max_tokens
            and "max_tokens" not in prepared
            and getattr(llm.delegate, "max_completion_tokens", None) == llm.max_tokens
            and getattr(llm.delegate, "max_tokens", None) is None
            and prepared.get("reasoning_effort") == "none"
            if is_gpt54
            else prepared.get("max_tokens") == llm.max_tokens
            and "max_completion_tokens" not in prepared
            and getattr(llm.delegate, "max_tokens", None) == llm.max_tokens
            and "reasoning_effort" not in prepared
        )
        if (
            llm.delegate.provider != "openai"
            or llm.provider != "openai"
            or llm.temperature != 0
            or llm.base_url != "https://api.openai.com/v1"
            or llm.additional_params != expected_outer_params
            or getattr(llm.delegate, "max_retries", None) != 0
            or getattr(llm.delegate, "store", None) is not False
            or getattr(llm.delegate, "api", None) != "completions"
            or getattr(llm.delegate, "custom_openai", None) is not True
            or llm.delegate.base_url != "https://api.openai.com/v1"
            or llm.delegate.timeout != llm.timeout
            or not isinstance(delegate_params, dict)
            or not token_limit_matches
            or prepared.get("store") is not False
            or prepared.get("model") != llm.model
            or "tools" in prepared
        ):
            raise ValueError(f"effective CrewAI provider params drift: {expected_key}")
        expected_delegate_params: dict[str, Any] = {"store": False}
        if is_gpt54:
            expected_delegate_params["reasoning_effort"] = "none"
        if expected_key == "orchestrator":
            response_format = delegate_params.get("response_format")
            if (
                not isinstance(response_format, dict)
                or response_format.get("type") != "json_schema"
                or response_format.get("json_schema", {}).get("strict") is not True
            ):
                raise ValueError("orchestrator lost the frozen strict response format")
            expected_delegate_params["response_format"] = response_format
        if delegate_params != expected_delegate_params:
            raise ValueError(f"effective CrewAI provider params drift: {expected_key}")
        agent_rows.append(
            {
                "benchmark_role": expected_key,
                "crewai_role": agent.role,
                "model": llm.model,
                "provider": llm.provider,
                "api": llm.delegate.api,
                "custom_openai_endpoint_lock": llm.delegate.custom_openai,
                "store": llm.delegate.additional_params.get("store"),
                "provider_max_retries": llm.delegate.max_retries,
                "max_iter": agent.max_iter,
                "max_retry_limit": agent.max_retry_limit,
                "max_execution_time": agent.max_execution_time,
                "max_tokens": llm.max_tokens,
                "token_limit_field": (
                    "max_completion_tokens" if is_gpt54 else "max_tokens"
                ),
                "reasoning_effort": "none" if is_gpt54 else None,
                "timeout": llm.timeout,
                "response_format": (
                    "strict_json_schema" if expected_key == "orchestrator" else "text"
                ),
            }
        )

    for expected_key, task in zip(EXPECTED_TASK_KEYS, benchmark_crew.tasks, strict=True):
        if (
            task.name != expected_key
            or task.tools
            or task.async_execution
            or task.output_json is not None
            or task.output_pydantic is not None
            or task.guardrail is not None
            or task.guardrails is not None
            or task.guardrail_max_retries != 0
        ):
            raise ValueError(f"effective CrewAI task profile drift: {expected_key}")

    return {
        "process": "sequential",
        "agent_count": len(benchmark_crew.agents),
        "task_count": len(benchmark_crew.tasks),
        "memory": False,
        "cache": False,
        "planning": False,
        "delegation": False,
        "tracing": False,
        "task_output_storage": "ephemeral_in_memory",
        "tools_on_agents": "absent",
        "max_llm_calls_per_sample": bundle.call_budget.max_calls,
        "agents": agent_rows,
    }
