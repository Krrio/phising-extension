"""Hardened CrewAI construction used only by the offline benchmark track.

The production ``GuardianClassic`` crew intentionally remains unchanged.  This
module makes every benchmark-relevant CrewAI default explicit and supplies a
shared call counter that blocks a fourth LLM call before it can reach the
provider.
"""

from __future__ import annotations

import asyncio
import inspect
import sqlite3
from dataclasses import dataclass, field
from threading import Lock
from typing import Any
from unittest.mock import patch

from crewai import Agent, Crew, LLM, Process, Task
from crewai.llms.base_llm import BaseLLM
from pydantic import PrivateAttr


EXPECTED_AGENT_KEYS = ("domain_analyst", "content_analyst", "orchestrator")
EXPECTED_TASK_KEYS = ("domain_analysis", "content_analysis", "synthesis")
_ORIGINAL_SQLITE_CONNECT = sqlite3.connect


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
        return self._delegate.call(*args, **kwargs)

    async def acall(self, *args: Any, **kwargs: Any) -> Any:
        self._call_budget.consume(self._benchmark_role)
        return await self._delegate.acall(*args, **kwargs)

    def supports_stop_words(self) -> bool:
        return self._delegate.supports_stop_words()

    def supports_multimodal(self) -> bool:
        return self._delegate.supports_multimodal()

    def get_context_window_size(self) -> int:
        return self._delegate.get_context_window_size()

    @property
    def delegate(self) -> BaseLLM:
        return self._delegate


@dataclass(frozen=True)
class BenchmarkCrewBundle:
    crew: Crew
    call_budget: BenchmarkCallBudget

    def close(self) -> None:
        """Close eager native OpenAI clients created by CrewAI for this sample."""

        for agent in self.crew.agents:
            llm = agent.llm
            if not isinstance(llm, GuardedBenchmarkLLM):
                continue
            delegate = llm.delegate
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
    temperature: float,
    max_output_tokens: int,
    request_timeout_seconds: float,
    max_llm_calls: int,
    response_schema: dict[str, Any],
    profile: dict[str, Any],
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
    # With an explicit native provider CrewAI 1.15.8 forwards ``model`` as-is.
    # Therefore use the exact OpenAI snapshot ID here; an ``openai/`` prefix
    # would reach the API and fail as an unknown model.
    model = requested_model

    def make_llm(role: str, *, structured: bool) -> GuardedBenchmarkLLM:
        # Send the exact frozen Direct schema instead of letting CrewAI add
        # Pydantic titles/descriptions that would change the comparison bundle.
        provider_params: dict[str, Any] = {"store": False}
        if structured:
            # OpenAICompletion 1.15.8's typed ``response_format`` field rejects
            # a json_schema dict even though its request builder supports one.
            # additional_params is merged into the actual provider payload.
            provider_params["response_format"] = response_schema
        delegate = LLM(
            model=model,
            provider="openai",
            api_key=api_key,
            base_url="https://api.openai.com/v1",
            custom_openai=True,
            temperature=temperature,
            max_tokens=max_output_tokens,
            timeout=request_timeout_seconds,
            stream=False,
            max_retries=0,
            store=False,
            api="completions",
            additional_params=provider_params,
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
            additional_params={"max_retries": 0, "store": False},
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


def audit_benchmark_crew(bundle: BenchmarkCrewBundle) -> dict[str, Any]:
    """Assert and return the effective no-hidden-capability runtime profile."""

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
            or llm.temperature != 0
            or llm.base_url != "https://api.openai.com/v1"
            or llm.stream
            or llm.additional_params != {"max_retries": 0, "store": False}
            or getattr(llm.delegate, "max_retries", None) != 0
            or getattr(llm.delegate, "store", None) is not False
            or getattr(llm.delegate, "api", None) != "completions"
            or getattr(llm.delegate, "custom_openai", None) is not True
            or llm.delegate.provider != "openai"
            or llm.delegate.model != llm.model
            or llm.delegate.base_url != "https://api.openai.com/v1"
            or llm.delegate.temperature != llm.temperature
            or llm.delegate.max_tokens != llm.max_tokens
            or llm.delegate.timeout != llm.timeout
            or llm.delegate.stream
        ):
            raise ValueError(f"effective CrewAI agent profile drift: {expected_key}")
        delegate_params = getattr(llm.delegate, "additional_params", None)
        if not isinstance(delegate_params, dict):
            raise ValueError(f"effective CrewAI provider params drift: {expected_key}")
        expected_delegate_params: dict[str, Any] = {"store": False}
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
