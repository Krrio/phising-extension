from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock


REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"
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
from phishing_bench.scoring import score_run  # noqa: E402


SMOKE_CONFIG = (
    BENCHMARKS_DIR
    / "campaigns"
    / "BUDGET_30H_CREWAI_GOOGLE_GEMINI35_FLASH_LITE_OFFLINE_SMOKE_001"
    / "runtime_config.json"
)
SMOKE_LABELS = (
    BENCHMARKS_DIR / "secure_scoring" / "openai_smoke_v1" / "labels.jsonl"
)
HAS_CREWAI = importlib.util.find_spec("crewai") is not None
FAKE_KEY = "gemini-crewai_FAKE_SECRET_security_failure_123456"


@unittest.skipUnless(HAS_CREWAI, "requires the pinned backend CrewAI environment")
class CrewAIGeminiSecurityFailureTests(unittest.TestCase):
    def test_network_guard_permission_error_remains_a_security_failure(self) -> None:
        with _isolated_provider_environment("google"):
            _import_benchmark_factory("google")
        from guardian_classic.benchmark_crew import (
            BenchmarkCallBudget,
            BenchmarkCrewBundle,
            GuardedBenchmarkLLM,
        )

        config, _ = load_and_validate_campaign(SMOKE_CONFIG, REPO_ROOT)
        marker = "network guard blocked hostname: unexpected.invalid"
        delegate = Mock()
        delegate.provider = "gemini"
        delegate.call.side_effect = PermissionError(marker)
        call_budget = BenchmarkCallBudget(max_calls=1)
        guarded = GuardedBenchmarkLLM(
            call_budget=call_budget,
            benchmark_role="domain_analyst",
            delegate=delegate,
            model=config["requested_model"],
            provider="gemini",
            api_key=FAKE_KEY,
            temperature=None,
            max_tokens=500,
            timeout=120,
            stream=False,
        )

        with self.assertRaisesRegex(PermissionError, "network guard blocked") as raised:
            guarded.call("synthetic request")

        self.assertIsNone(guarded.provider_failure)
        bundle = BenchmarkCrewBundle(
            crew=Mock(agents=[Mock(llm=guarded)]),
            call_budget=call_budget,
        )
        self.assertEqual(bundle.provider_failures, {})
        preserved_error = str(raised.exception)
        self.assertIn("network guard blocked", preserved_error)

        executor_calls = 0

        def fake_executor(**kwargs: object) -> CrewWorkflowExecution:
            nonlocal executor_calls
            del kwargs
            executor_calls += 1
            if executor_calls > 1:
                self.fail("security failure must stop before a second workflow")
            return CrewWorkflowExecution(
                raw_output=None,
                calls=(
                    CrewCallObservation(
                        call_id="network-guard-call-1",
                        role="domain_analyst",
                        task_name="domain_analysis",
                        request_sha256=sha256_text("blocked network request"),
                        response_sha256=None,
                        model=config["requested_model"],
                        usage=None,
                        latency_ms=1.0,
                        finish_reason=None,
                        response_id=None,
                        status="failed",
                        error=preserved_error,
                    ),
                ),
                runtime_audit={"fake": True},
                error=f"Task execution failed: {preserved_error}",
            )

        with tempfile.TemporaryDirectory() as temporary:
            run_dir = run_crewai_campaign(
                config_path=SMOKE_CONFIG,
                repo_root=REPO_ROOT,
                output_root=Path(temporary) / "runs",
                api_key=FAKE_KEY,
                workflow_executor=fake_executor,
            )
            results = read_jsonl(run_dir / "results.jsonl")
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
            [result["status"] for result in results],
            ["security_fail"] + ["campaign_stopped"] * 4,
        )
        first_events = results[0]["security_events"]
        self.assertEqual(len(first_events), 1)
        self.assertEqual(first_events[0]["type"], "unauthorized_network_egress")
        self.assertEqual(first_events[0]["severity"], "critical")
        self.assertTrue(first_events[0]["blocked"])
        self.assertEqual(manifest["status"], "security_fail")
        self.assertEqual(metrics["campaign_status"], "SECURITY_FAIL")


if __name__ == "__main__":
    unittest.main()
