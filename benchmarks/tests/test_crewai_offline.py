from __future__ import annotations

import importlib.util
import json
import os
import socket
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"

import sys

sys.path.insert(0, str(BENCHMARKS_DIR))

from phishing_bench.contracts import (  # noqa: E402
    CREWAI_QUALITY_PILOT_PROFILE,
    CREWAI_SMOKE_PROFILE,
    load_and_validate_campaign,
)
from phishing_bench.crewai_offline import (  # noqa: E402
    CrewCallObservation,
    CrewWorkflowExecution,
    _execute_real_workflow,
    _import_benchmark_factory,
    _openai_only_network_guard,
    _security_events,
    build_frozen_domain_evidence,
    crewai_runtime_preflight,
    run_crewai_campaign,
)
from phishing_bench.io_utils import read_json, read_jsonl, sha256_text  # noqa: E402
from phishing_bench.scoring import score_run  # noqa: E402


SMOKE_CONFIG = (
    BENCHMARKS_DIR
    / "campaigns"
    / "BUDGET_30H_CREWAI_OFFLINE_SMOKE_001"
    / "runtime_config.json"
)
PILOT_CONFIG = (
    BENCHMARKS_DIR
    / "campaigns"
    / "BUDGET_30H_CREWAI_OFFLINE_PILOT_030_001"
    / "runtime_config.json"
)
DIRECT_PILOT_CONFIG = (
    BENCHMARKS_DIR
    / "campaigns"
    / "BUDGET_30H_OPENAI_PILOT_030_001"
    / "runtime_config.json"
)
HAS_CREWAI = importlib.util.find_spec("crewai") is not None


class CrewAIOfflineContractTests(unittest.TestCase):
    def test_campaigns_freeze_same_model_and_pilot_dataset_as_direct(self) -> None:
        smoke, smoke_assets = load_and_validate_campaign(SMOKE_CONFIG, REPO_ROOT)
        pilot, pilot_assets = load_and_validate_campaign(PILOT_CONFIG, REPO_ROOT)
        direct, direct_assets = load_and_validate_campaign(
            DIRECT_PILOT_CONFIG, REPO_ROOT
        )

        self.assertEqual(smoke["evaluation_profile"], CREWAI_SMOKE_PROFILE)
        self.assertEqual(
            pilot["evaluation_profile"], CREWAI_QUALITY_PILOT_PROFILE
        )
        self.assertEqual(pilot["requested_model"], direct["requested_model"])
        self.assertEqual(pilot["dataset_path"], direct["dataset_path"])
        self.assertEqual(pilot_assets["dataset"], direct_assets["dataset"])
        self.assertEqual(len(smoke_assets["dataset"]), 5)
        self.assertEqual(len(pilot_assets["dataset"]), 30)
        self.assertEqual(pilot["framework_config"]["max_llm_calls_per_sample"], 3)
        self.assertEqual(pilot["max_retries_per_sample"], 0)

    def test_frozen_domain_evidence_is_local_deterministic_and_label_free(self) -> None:
        _, assets = load_and_validate_campaign(PILOT_CONFIG, REPO_ROOT)
        record = assets["dataset"][0]
        first, first_tools = build_frozen_domain_evidence(
            record, assets["frozen_domain_evidence"]
        )
        second, second_tools = build_frozen_domain_evidence(
            record, assets["frozen_domain_evidence"]
        )

        self.assertEqual(first, second)
        self.assertEqual(first_tools, second_tools)
        self.assertFalse(first["network_used"])
        self.assertEqual(len(first_tools), 2)
        serialized = json.dumps(first, ensure_ascii=False).casefold()
        self.assertNotIn("class_label", serialized)
        self.assertNotIn("acceptable_actions", serialized)
        self.assertTrue(
            all(
                row["registration_status"] == "not_applicable_reserved_tld"
                for row in first["domains"]
            )
        )

    def test_network_guard_blocks_non_openai_hostname_before_dns(self) -> None:
        with self.assertRaisesRegex(PermissionError, "network guard blocked hostname"):
            with _openai_only_network_guard():
                socket.getaddrinfo("rdap.org", 443)

    def test_partial_provider_failure_is_not_mislabeled_as_role_drift(self) -> None:
        config, _ = load_and_validate_campaign(SMOKE_CONFIG, REPO_ROOT)
        failed_call = CrewCallObservation(
            call_id="call-1",
            role="domain_analyst",
            task_name="domain_analysis",
            request_sha256=sha256_text("request"),
            response_sha256=None,
            model=config["requested_model"],
            usage=None,
            latency_ms=1.0,
            finish_reason=None,
            response_id=None,
            status="failed",
            error="rate limited",
        )
        execution = CrewWorkflowExecution(
            raw_output=None,
            calls=(failed_call,),
            runtime_audit={},
            error="OpenAI API call failed: rate limited",
        )

        events = _security_events(execution, config=config, api_key="sk-placeholder")
        self.assertFalse(any(row["type"] == "configuration_drift" for row in events))


@unittest.skipUnless(HAS_CREWAI, "requires the pinned backend CrewAI environment")
class CrewAIRuntimeTests(unittest.TestCase):
    def test_preflight_builds_three_guarded_agents_without_loading_env_key(self) -> None:
        config, assets = load_and_validate_campaign(SMOKE_CONFIG, REPO_ROOT)
        original = os.environ.pop("OPENAI_API_KEY", None)
        try:
            report = crewai_runtime_preflight(config, assets)
            self.assertNotIn("OPENAI_API_KEY", os.environ)
        finally:
            if original is not None:
                os.environ["OPENAI_API_KEY"] = original

        self.assertEqual(report["installed_crewai_version"], "1.15.8")
        self.assertEqual(report["provider_calls_made"], 0)
        self.assertFalse(report["telemetry"]["anonymous_exporter_ready"])
        self.assertFalse(report["telemetry"]["tracing_enabled"])
        self.assertFalse(report["telemetry"]["first_run_trace_collection"])
        self.assertEqual(
            [
                row["model"]
                for row in report["effective_profile"]["agents"]
            ],
            [config["requested_model"]] * 3,
        )
        self.assertEqual(
            [row["benchmark_role"] for row in report["effective_profile"]["agents"]],
            ["domain_analyst", "content_analyst", "orchestrator"],
        )

    def test_hard_call_budget_blocks_fourth_delegate_call(self) -> None:
        from guardian_classic.benchmark_crew import (
            BenchmarkCallBudget,
            GuardedBenchmarkLLM,
        )

        delegate = Mock()
        delegate.call.return_value = "ok"
        budget = BenchmarkCallBudget(max_calls=3)
        guarded = GuardedBenchmarkLLM(
            call_budget=budget,
            benchmark_role="test_role",
            delegate=delegate,
            model="openai/gpt-4o-mini-2024-07-18",
            temperature=0,
            max_tokens=500,
            timeout=45,
            additional_params={"max_retries": 0, "store": False},
        )

        self.assertEqual([guarded.call("x") for _ in range(3)], ["ok"] * 3)
        with self.assertRaisesRegex(RuntimeError, "call ceiling exceeded"):
            guarded.call("blocked")
        self.assertEqual(delegate.call.call_count, 3)
        self.assertEqual(budget.used, 3)

    def test_real_crewai_kickoff_uses_exactly_one_call_per_role_offline(self) -> None:
        """Exercise CrewAI itself while replacing only the provider boundary."""

        config, assets = load_and_validate_campaign(SMOKE_CONFIG, REPO_ROOT)
        record = assets["dataset"][0]
        evidence, _ = build_frozen_domain_evidence(
            record, assets["frozen_domain_evidence"]
        )
        final_output = json.dumps(
            {
                "trustScore": 10,
                "verdict": "phishing",
                "confidence": 0.99,
                "reasoning": "Wiadomość wyłudza dane logowania.",
                "categories": [
                    "credential_request",
                    "urgency",
                    "suspicious_link",
                ],
                "policyAssessment": None,
            },
            ensure_ascii=False,
        )
        responses = (
            "Domena jest zarezerwowana do testów; sygnał produktu wskazuje ryzyko.",
            "Treść wymusza pilne podanie hasła i kodu SMS przez link.",
            final_output,
        )
        build_benchmark_crew, _ = _import_benchmark_factory()
        bundle = build_benchmark_crew(
            api_key="sk-test-placeholder-not-real",
            requested_model=config["requested_model"],
            temperature=config["temperature"],
            max_output_tokens=config["max_output_tokens"],
            request_timeout_seconds=config["request_timeout_seconds"],
            max_llm_calls=config["framework_config"]["max_llm_calls_per_sample"],
            response_schema=assets["response_schema"],
            profile=assets["crew_profile"],
        )
        self.addCleanup(bundle.close)

        prepared = [
            agent.llm.delegate._prepare_completion_params(  # noqa: SLF001
                [{"role": "user", "content": "offline contract probe"}],
                tools=[],
            )
            for agent in bundle.crew.agents
        ]
        self.assertTrue(
            all(params["model"] == config["requested_model"] for params in prepared)
        )
        self.assertTrue(all(params["store"] is False for params in prepared))
        self.assertTrue(all(params["max_tokens"] == 500 for params in prepared))
        self.assertTrue(all(params["temperature"] == 0 for params in prepared))
        self.assertTrue(all("tools" not in params for params in prepared))
        self.assertTrue(all(agent.llm.delegate.custom_openai for agent in bundle.crew.agents))
        self.assertNotIn("response_format", prepared[0])
        self.assertNotIn("response_format", prepared[1])
        self.assertEqual(prepared[2]["response_format"], assets["response_schema"])

        provider_mocks: list[Mock] = []
        with ExitStack() as stack:
            for agent, response in zip(
                bundle.crew.agents, responses, strict=True
            ):
                provider_call = Mock(return_value=response)
                provider_mocks.append(provider_call)
                stack.enter_context(
                    unittest.mock.patch.object(
                        agent.llm.delegate, "call", provider_call
                    )
                )
            output = bundle.crew.kickoff(
                inputs={
                    "benchmark_system_prompt": assets["prompt"],
                    "record_payload": json.dumps(record, ensure_ascii=False, indent=2),
                    "frozen_domain_evidence": json.dumps(
                        evidence, ensure_ascii=False, indent=2
                    ),
                }
            )

        self.assertEqual(bundle.call_budget.used, 3)
        self.assertEqual(
            bundle.call_budget.roles,
            ("domain_analyst", "content_analyst", "orchestrator"),
        )
        self.assertEqual([mock.call_count for mock in provider_mocks], [1, 1, 1])
        self.assertEqual(json.loads(output.raw), json.loads(final_output))

    def test_native_openai_adapter_events_and_payload_without_network(self) -> None:
        """Mock HTTP only; exercise native CrewAI OpenAI request/event handling."""

        # Always enter through the benchmark import gate. CrewAI computes its
        # storage directory while importing, even though persistence is
        # disabled for this benchmark.
        _import_benchmark_factory()
        from crewai.llms.providers.openai.completion import OpenAICompletion
        from openai.types.chat import ChatCompletion

        config, assets = load_and_validate_campaign(SMOKE_CONFIG, REPO_ROOT)
        record = assets["dataset"][0]
        evidence, _ = build_frozen_domain_evidence(
            record, assets["frozen_domain_evidence"]
        )
        final_output = json.dumps(
            {
                "trustScore": 10,
                "verdict": "phishing",
                "confidence": 0.99,
                "reasoning": "Wiadomość wyłudza dane logowania.",
                "categories": ["credential_request", "urgency", "suspicious_link"],
                "policyAssessment": None,
            },
            ensure_ascii=False,
        )

        def response(response_id: str, content: str) -> ChatCompletion:
            return ChatCompletion.model_validate(
                {
                    "id": response_id,
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "index": 0,
                            "message": {"content": content, "role": "assistant"},
                        }
                    ],
                    "created": 1,
                    "model": config["requested_model"],
                    "object": "chat.completion",
                    "usage": {
                        "completion_tokens": 20,
                        "prompt_tokens": 100,
                        "total_tokens": 120,
                    },
                }
            )

        create = Mock(
            side_effect=[
                response("chatcmpl-domain", "Raport domenowy."),
                response("chatcmpl-content", "Raport treściowy."),
                response("chatcmpl-final", final_output),
            ]
        )
        sync_client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
            close=Mock(),
        )

        class FakeAsyncClient:
            async def close(self) -> None:
                return None

        with unittest.mock.patch.object(
            OpenAICompletion, "_build_sync_client", return_value=sync_client
        ), unittest.mock.patch.object(
            OpenAICompletion, "_build_async_client", side_effect=FakeAsyncClient
        ):
            execution = _execute_real_workflow(
                config=config,
                assets=assets,
                record=record,
                evidence=evidence,
                api_key="sk-test-placeholder-not-real",
            )

        self.assertIsNone(execution.error)
        self.assertEqual(json.loads(execution.raw_output or ""), json.loads(final_output))
        self.assertEqual(
            [(call.role, call.task_name) for call in execution.calls],
            [
                ("domain_analyst", "domain_analysis"),
                ("content_analyst", "content_analysis"),
                ("orchestrator", "synthesis"),
            ],
        )
        self.assertTrue(all(call.model == config["requested_model"] for call in execution.calls))
        self.assertTrue(all(call.finish_reason == "stop" for call in execution.calls))
        self.assertTrue(all(call.usage is not None for call in execution.calls))
        self.assertEqual(create.call_count, 3)
        outgoing = [call.kwargs for call in create.call_args_list]
        self.assertTrue(all(row["model"] == config["requested_model"] for row in outgoing))
        self.assertTrue(all(row["store"] is False for row in outgoing))
        self.assertTrue(all(row["max_tokens"] == 500 for row in outgoing))
        self.assertTrue(all("tools" not in row for row in outgoing))
        self.assertNotIn("response_format", outgoing[0])
        self.assertNotIn("response_format", outgoing[1])
        self.assertEqual(outgoing[2]["response_format"], assets["response_schema"])

    def test_fake_run_writes_reconciling_call_and_frozen_tool_artifacts(self) -> None:
        valid_output = json.dumps(
            {
                "trustScore": 95,
                "verdict": "safe",
                "confidence": 0.95,
                "reasoning": "Brak konkretnych oznak phishingu.",
                "categories": [],
                "policyAssessment": None,
            },
            ensure_ascii=False,
        )

        def fake_executor(**kwargs: object) -> CrewWorkflowExecution:
            config = kwargs["config"]
            assert isinstance(config, dict)
            calls = tuple(
                CrewCallObservation(
                    call_id=f"framework-{role}",
                    role=role,
                    task_name=task,
                    request_sha256=sha256_text(f"request-{role}"),
                    response_sha256=sha256_text(f"response-{role}"),
                    model=config["requested_model"],
                    usage={
                        "input_tokens": 100,
                        "cached_input_tokens": 0,
                        "output_tokens": 20,
                        "reasoning_tokens": 0,
                        "total_tokens": 120,
                    },
                    latency_ms=10.0,
                    finish_reason="stop",
                    response_id=f"response-{role}",
                    status="success",
                    error=None,
                )
                for role, task in zip(
                    ("domain_analyst", "content_analyst", "orchestrator"),
                    ("domain_analysis", "content_analysis", "synthesis"),
                    strict=True,
                )
            )
            return CrewWorkflowExecution(
                raw_output=valid_output,
                calls=calls,
                runtime_audit={"fake": True},
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "runs"
            run_dir = run_crewai_campaign(
                config_path=SMOKE_CONFIG,
                repo_root=REPO_ROOT,
                output_root=output_root,
                api_key="sk-test-placeholder-not-real",
                workflow_executor=fake_executor,
            )
            manifest = read_json(run_dir / "run_manifest.json")
            results = read_jsonl(run_dir / "results.jsonl")
            calls = read_jsonl(run_dir / "calls.jsonl")
            tool_events = read_jsonl(run_dir / "tool_events.jsonl")

            self.assertEqual(manifest["status"], "completed")
            self.assertEqual(len(results), 5)
            self.assertEqual(len(calls), 15)
            self.assertEqual(len(tool_events), 10)
            self.assertTrue(all(row["network_used"] is False for row in tool_events))
            self.assertTrue(all(row["llm_call_count"] == 3 for row in results))
            self.assertTrue(all(row["response_schema_valid"] for row in results))

            scoring_dir = score_run(
                run_dir=run_dir,
                labels_path=(
                    BENCHMARKS_DIR
                    / "secure_scoring"
                    / "openai_smoke_v1"
                    / "labels.jsonl"
                ),
                output_dir=None,
                repo_root=REPO_ROOT,
            )
            self.assertTrue((scoring_dir / "report.md").is_file())


if __name__ == "__main__":
    unittest.main()
