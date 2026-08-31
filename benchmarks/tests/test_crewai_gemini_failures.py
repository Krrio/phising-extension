from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock


REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"

import sys

sys.path.insert(0, str(BENCHMARKS_DIR))

from phishing_bench.contracts import load_and_validate_campaign  # noqa: E402
from phishing_bench.crewai_offline import (  # noqa: E402
    CrewCallObservation,
    CrewWorkflowExecution,
    _import_benchmark_factory,
    _isolated_provider_environment,
    run_crewai_campaign,
)
from phishing_bench.io_utils import read_json, read_jsonl, sha256_text  # noqa: E402
from phishing_bench.openai_direct import validated_tls_context  # noqa: E402
from phishing_bench.scoring import score_run  # noqa: E402


SMOKE_CONFIG = (
    BENCHMARKS_DIR
    / "campaigns"
    / "BUDGET_30H_CREWAI_GOOGLE_GEMINI35_FLASH_LITE_OFFLINE_SMOKE_001"
    / "runtime_config.json"
)
SMOKE_TIMEOUT_CONFIG = (
    BENCHMARKS_DIR
    / "campaigns"
    / "BUDGET_30H_CREWAI_GOOGLE_GEMINI35_FLASH_LITE_OFFLINE_SMOKE_002"
    / "runtime_config.json"
)
SMOKE_LABELS = (
    BENCHMARKS_DIR / "secure_scoring" / "openai_smoke_v1" / "labels.jsonl"
)
HAS_CREWAI = importlib.util.find_spec("crewai") is not None
FAKE_KEY = "gemini-crewai_FAKE_SECRET_failure_metadata_123456"


class CrewCallObservationCompatibilityTests(unittest.TestCase):
    def test_new_failure_fields_have_compatible_defaults(self) -> None:
        observation = CrewCallObservation(
            call_id="call-1",
            role="domain_analyst",
            task_name="domain_analysis",
            request_sha256=sha256_text("request"),
            response_sha256=None,
            model="gemini-3.5-flash-lite",
            usage=None,
            latency_ms=1.0,
            finish_reason=None,
            response_id=None,
            status="failed",
            error="legacy fake error",
        )

        self.assertIsNone(observation.error_kind)
        self.assertIsNone(observation.status_code)
        self.assertIsNone(observation.provider_status)


@unittest.skipUnless(HAS_CREWAI, "requires the pinned backend CrewAI environment")
class CrewAIGeminiFailureTests(unittest.TestCase):
    def test_guard_captures_google_api_error_attributes_without_secret(self) -> None:
        from google.genai import errors
        from guardian_classic.benchmark_crew import (
            BenchmarkCallBudget,
            GuardedBenchmarkLLM,
        )

        cases = (
            (429, "RESOURCE_EXHAUSTED", "rate_limit"),
            (503, "UNAVAILABLE", "provider_http_error"),
            (504, "DEADLINE_EXCEEDED", "timeout"),
            (403, "PERMISSION_DENIED", "provider_http_error"),
        )
        for code, provider_status, expected_kind in cases:
            with self.subTest(code=code):
                provider_error = errors.APIError(
                    code,
                    {
                        "error": {
                            "code": code,
                            "status": provider_status,
                            "message": f"safe provider message {FAKE_KEY}",
                        }
                    },
                )
                delegate = Mock()
                delegate.provider = "gemini"
                delegate.call.side_effect = provider_error
                guarded = GuardedBenchmarkLLM(
                    call_budget=BenchmarkCallBudget(max_calls=1),
                    benchmark_role="domain_analyst",
                    delegate=delegate,
                    model="gemini-3.5-flash-lite",
                    provider="gemini",
                    api_key=FAKE_KEY,
                    temperature=None,
                    max_tokens=500,
                    timeout=120,
                    stream=False,
                )

                with self.assertRaises(errors.APIError) as raised:
                    guarded.call("synthetic request")

                self.assertIs(raised.exception, provider_error)
                self.assertEqual(
                    guarded.provider_failure,
                    {
                        "kind": expected_kind,
                        "status_code": code,
                        "provider_status": provider_status,
                        "message": "safe provider message [REDACTED]",
                    },
                )

    def test_guard_maps_local_timeout_without_parsing_exception_text(self) -> None:
        from guardian_classic.benchmark_crew import (
            BenchmarkCallBudget,
            GuardedBenchmarkLLM,
        )

        class LocalTimeout(TimeoutError):
            def __str__(self) -> str:
                raise AssertionError("exception text must not be parsed")

        delegate = Mock()
        delegate.provider = "gemini"
        delegate.call.side_effect = LocalTimeout()
        guarded = GuardedBenchmarkLLM(
            call_budget=BenchmarkCallBudget(max_calls=1),
            benchmark_role="domain_analyst",
            delegate=delegate,
            model="gemini-3.5-flash-lite",
            provider="gemini",
            api_key=FAKE_KEY,
            temperature=None,
            max_tokens=500,
            timeout=120,
            stream=False,
        )

        with self.assertRaises(LocalTimeout):
            guarded.call("synthetic request")

        self.assertEqual(
            guarded.provider_failure,
            {
                "kind": "timeout",
                "status_code": None,
                "provider_status": None,
                "message": "Google Gemini request timed out",
            },
        )

    def test_audit_accepts_http_timeout_frozen_by_outer_llm(self) -> None:
        config, assets = load_and_validate_campaign(SMOKE_CONFIG, REPO_ROOT)
        with _isolated_provider_environment("google"):
            build_crew, audit_crew = _import_benchmark_factory("google")
            bundle = build_crew(
                api_key=FAKE_KEY,
                requested_model=config["requested_model"],
                temperature=config["temperature"],
                max_output_tokens=config["max_output_tokens"],
                request_timeout_seconds=120,
                max_llm_calls=config["framework_config"][
                    "max_llm_calls_per_sample"
                ],
                response_schema=assets["response_schema"],
                profile=assets["crew_profile"],
                provider="google",
                thinking_level=config["thinking_level"],
                tls_context=validated_tls_context(),
            )
            try:
                audit = audit_crew(bundle)
            finally:
                bundle.close()

        self.assertEqual([row["timeout"] for row in audit["agents"]], [120] * 3)
        self.assertEqual(
            [row["max_execution_time"] for row in audit["agents"]], [120] * 3
        )

    def test_transient_google_failure_stops_campaign_after_first_sample(self) -> None:
        config, _ = load_and_validate_campaign(SMOKE_TIMEOUT_CONFIG, REPO_ROOT)
        cases = (
            (429, "RESOURCE_EXHAUSTED", "rate_limit", "HTTP 429"),
            (503, "UNAVAILABLE", "provider_http_error", "HTTP 503"),
            (504, "DEADLINE_EXCEEDED", "timeout", "HTTP 504"),
            (None, None, "timeout", "local timeout"),
        )
        for (
            status_code,
            provider_status,
            error_kind,
            expected_stop_label,
        ) in cases:
            with self.subTest(status_code=status_code):
                executor_calls = 0

                def fake_executor(**kwargs: object) -> CrewWorkflowExecution:
                    nonlocal executor_calls
                    del kwargs
                    executor_calls += 1
                    if executor_calls > 1:
                        self.fail("campaign should stop before a second workflow")
                    return CrewWorkflowExecution(
                        raw_output=None,
                        calls=(
                            CrewCallObservation(
                                call_id="failed-call-1",
                                role="domain_analyst",
                                task_name="domain_analysis",
                                request_sha256=sha256_text("failed request"),
                                response_sha256=None,
                                model=config["requested_model"],
                                usage=None,
                                latency_ms=120_000.0,
                                finish_reason=None,
                                response_id=None,
                                status="failed",
                                error=(
                                    "Deadline expired before operation could "
                                    "complete."
                                ),
                                error_kind=error_kind,
                                status_code=status_code,
                                provider_status=provider_status,
                            ),
                        ),
                        runtime_audit={"fake": True},
                        error="Deadline expired before operation could complete.",
                    )

                with tempfile.TemporaryDirectory() as temporary:
                    run_dir = run_crewai_campaign(
                        config_path=SMOKE_TIMEOUT_CONFIG,
                        repo_root=REPO_ROOT,
                        output_root=Path(temporary) / "runs",
                        api_key=FAKE_KEY,
                        workflow_executor=fake_executor,
                    )
                    results = read_jsonl(run_dir / "results.jsonl")
                    attempts = read_jsonl(run_dir / "attempts.jsonl")
                    calls = read_jsonl(run_dir / "calls.jsonl")
                    ledger = read_json(run_dir / "budget_ledger.json")
                    manifest = read_json(run_dir / "run_manifest.json")
                    scoring_dir = score_run(
                        run_dir=run_dir,
                        labels_path=SMOKE_LABELS,
                        output_dir=None,
                        repo_root=REPO_ROOT,
                    )
                    metrics = read_json(scoring_dir / "metrics.json")

                    self.assertEqual(executor_calls, 1)
                    self.assertEqual(
                        [row["status"] for row in results],
                        [error_kind] + ["campaign_stopped"] * 4,
                    )
                    self.assertEqual(results[0]["error"]["type"], error_kind)
                    self.assertEqual(
                        results[0]["error"]["status_code"], status_code
                    )
                    self.assertEqual(
                        results[0]["error"]["provider_status"], provider_status
                    )
                    finished = [
                        row for row in attempts if row["event"] == "finished"
                    ]
                    self.assertEqual(len(finished), 1)
                    self.assertEqual(finished[0]["status"], error_kind)
                    self.assertEqual(
                        finished[0]["error"]["status_code"], status_code
                    )
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(calls[0]["error_kind"], error_kind)
                    self.assertEqual(calls[0]["status_code"], status_code)
                    self.assertEqual(ledger["attempts_started"], 1)
                    self.assertEqual(ledger["attempts_finished"], 1)
                    self.assertIn(expected_stop_label, ledger["stop_reason"])
                    self.assertEqual(
                        manifest["status"], "completed_with_failures"
                    )
                    self.assertEqual(
                        metrics["campaign_status"], "READINESS_FAIL"
                    )
                    self.assertEqual(
                        metrics["records"]["status_counts"],
                        {"campaign_stopped": 4, error_kind: 1},
                    )

                    for artifact in (
                        "results.jsonl",
                        "attempts.jsonl",
                        "calls.jsonl",
                        "budget_ledger.json",
                    ):
                        self.assertNotIn(
                            FAKE_KEY,
                            (run_dir / artifact).read_text(encoding="utf-8"),
                        )


if __name__ == "__main__":
    unittest.main()
