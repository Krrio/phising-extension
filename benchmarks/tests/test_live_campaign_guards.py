from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"
sys.path.insert(0, str(BENCHMARKS_DIR))

from benchmark_cli import main as benchmark_main  # noqa: E402
from phishing_bench.contracts import (  # noqa: E402
    CREWAI_GEMINI_TRANSIENT_FAIL_FAST_CAMPAIGN_IDS,
    LIVE_BLOCKED_CAMPAIGNS,
    campaign_live_block_reason,
    load_and_validate_campaign,
)
from phishing_bench.crewai_offline import (  # noqa: E402
    crewai_readiness_report,
    run_crewai_campaign,
)
from phishing_bench.runner import readiness_report, run_campaign  # noqa: E402


G37_PILOT_ID = "BUDGET_30H_GOOGLE_GEMINI37_FLASH_PILOT_030_001"
CREW_GEMINI_PILOT_ID = (
    "BUDGET_30H_CREWAI_GOOGLE_GEMINI35_FLASH_LITE_OFFLINE_PILOT_030_001"
)
CREW_GEMINI_PILOT_002_ID = (
    "BUDGET_30H_CREWAI_GOOGLE_GEMINI35_FLASH_LITE_OFFLINE_PILOT_030_002"
)
CREW_GEMINI_SMOKE_001_ID = (
    "BUDGET_30H_CREWAI_GOOGLE_GEMINI35_FLASH_LITE_OFFLINE_SMOKE_001"
)
CREW_GEMINI_SMOKE_002_ID = (
    "BUDGET_30H_CREWAI_GOOGLE_GEMINI35_FLASH_LITE_OFFLINE_SMOKE_002"
)
CREW_GEMINI31_SMOKE_ID = (
    "BUDGET_30H_CREWAI_GOOGLE_GEMINI31_FLASH_LITE_OFFLINE_SMOKE_001"
)
CREW_GEMINI31_PILOT_ID = (
    "BUDGET_30H_CREWAI_GOOGLE_GEMINI31_FLASH_LITE_OFFLINE_PILOT_030_001"
)
CREW_GEMINI31_SMOKE_002_ID = (
    "BUDGET_30H_CREWAI_GOOGLE_GEMINI31_FLASH_LITE_OFFLINE_SMOKE_002"
)
CREW_GEMINI31_PILOT_002_ID = (
    "BUDGET_30H_CREWAI_GOOGLE_GEMINI31_FLASH_LITE_OFFLINE_PILOT_030_002"
)
CREW_GEMINI37_SMOKE_ID = (
    "BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_SMOKE_001"
)
CREW_GEMINI37_PILOT_ID = (
    "BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_PILOT_030_001"
)
CREW_GEMINI37_SMOKE_002_ID = (
    "BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_SMOKE_002"
)
CREW_GEMINI37_PILOT_002_ID = (
    "BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_PILOT_030_002"
)
CREW_GPT54_NANO_SMOKE_001_ID = (
    "BUDGET_30H_CREWAI_OPENAI_GPT54_NANO_OFFLINE_SMOKE_001"
)
CREW_GPT54_NANO_SMOKE_002_ID = (
    "BUDGET_30H_CREWAI_OPENAI_GPT54_NANO_OFFLINE_SMOKE_002"
)
CREW_GPT54_NANO_SMOKE_003_ID = (
    "BUDGET_30H_CREWAI_OPENAI_GPT54_NANO_OFFLINE_SMOKE_003"
)
CREW_GPT54_NANO_PILOT_002_ID = (
    "BUDGET_30H_CREWAI_OPENAI_GPT54_NANO_OFFLINE_PILOT_030_002"
)
CREW_GPT54_MINI_SMOKE_002_ID = (
    "BUDGET_30H_CREWAI_OPENAI_GPT54_MINI_OFFLINE_SMOKE_002"
)
CREW_GPT54_MINI_PILOT_002_ID = (
    "BUDGET_30H_CREWAI_OPENAI_GPT54_MINI_OFFLINE_PILOT_030_002"
)
G37_PILOT_CONFIG = (
    BENCHMARKS_DIR / "campaigns" / G37_PILOT_ID / "runtime_config.json"
)
CREW_GEMINI_PILOT_CONFIG = (
    BENCHMARKS_DIR / "campaigns" / CREW_GEMINI_PILOT_ID / "runtime_config.json"
)
CREW_GEMINI_PILOT_002_CONFIG = (
    BENCHMARKS_DIR
    / "campaigns"
    / CREW_GEMINI_PILOT_002_ID
    / "runtime_config.json"
)
CREW_GEMINI_SMOKE_001_CONFIG = (
    BENCHMARKS_DIR
    / "campaigns"
    / CREW_GEMINI_SMOKE_001_ID
    / "runtime_config.json"
)
CREW_GEMINI_SMOKE_002_CONFIG = (
    BENCHMARKS_DIR
    / "campaigns"
    / CREW_GEMINI_SMOKE_002_ID
    / "runtime_config.json"
)
CREW_GEMINI31_SMOKE_002_CONFIG = (
    BENCHMARKS_DIR
    / "campaigns"
    / CREW_GEMINI31_SMOKE_002_ID
    / "runtime_config.json"
)
CREW_GEMINI31_PILOT_002_CONFIG = (
    BENCHMARKS_DIR
    / "campaigns"
    / CREW_GEMINI31_PILOT_002_ID
    / "runtime_config.json"
)
CREW_GPT54_NANO_SMOKE_001_CONFIG = (
    BENCHMARKS_DIR
    / "campaigns"
    / CREW_GPT54_NANO_SMOKE_001_ID
    / "runtime_config.json"
)
CREW_GPT54_NANO_SMOKE_002_CONFIG = (
    BENCHMARKS_DIR
    / "campaigns"
    / CREW_GPT54_NANO_SMOKE_002_ID
    / "runtime_config.json"
)
CREW_GPT54_NANO_SMOKE_003_CONFIG = (
    BENCHMARKS_DIR
    / "campaigns"
    / CREW_GPT54_NANO_SMOKE_003_ID
    / "runtime_config.json"
)
CREW_GPT54_NANO_PILOT_002_CONFIG = (
    BENCHMARKS_DIR
    / "campaigns"
    / CREW_GPT54_NANO_PILOT_002_ID
    / "runtime_config.json"
)
CREW_GPT54_MINI_SMOKE_002_CONFIG = (
    BENCHMARKS_DIR
    / "campaigns"
    / CREW_GPT54_MINI_SMOKE_002_ID
    / "runtime_config.json"
)
CREW_GPT54_MINI_PILOT_002_CONFIG = (
    BENCHMARKS_DIR
    / "campaigns"
    / CREW_GPT54_MINI_PILOT_002_ID
    / "runtime_config.json"
)
HAS_CREWAI = importlib.util.find_spec("crewai") is not None
FAKE_KEY = "gemini_FAKE_live_guard_secret_123456"


class ClosedCampaignGuardTests(unittest.TestCase):
    def test_fail_fast_policy_is_frozen_only_for_120_second_campaigns(
        self,
    ) -> None:
        self.assertNotIn(
            CREW_GEMINI_SMOKE_001_ID,
            CREWAI_GEMINI_TRANSIENT_FAIL_FAST_CAMPAIGN_IDS,
        )
        self.assertEqual(
            CREWAI_GEMINI_TRANSIENT_FAIL_FAST_CAMPAIGN_IDS,
            frozenset(
                {
                    CREW_GEMINI_SMOKE_002_ID,
                    CREW_GEMINI_PILOT_002_ID,
                    CREW_GEMINI31_SMOKE_ID,
                    CREW_GEMINI31_PILOT_ID,
                    CREW_GEMINI31_SMOKE_002_ID,
                    CREW_GEMINI31_PILOT_002_ID,
                    CREW_GEMINI37_SMOKE_ID,
                    CREW_GEMINI37_PILOT_ID,
                    CREW_GEMINI37_SMOKE_002_ID,
                    CREW_GEMINI37_PILOT_002_ID,
                }
            ),
        )

    def test_closed_direct_pilot_is_not_reported_ready_and_cannot_run(self) -> None:
        config, _ = load_and_validate_campaign(G37_PILOT_CONFIG, REPO_ROOT)
        report = readiness_report(G37_PILOT_CONFIG, REPO_ROOT)

        self.assertIsNotNone(campaign_live_block_reason(config))
        self.assertEqual(report["status"], "LIVE_BLOCKED")
        self.assertIn("smoke", report["live_block_reason"])
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "live run is blocked"):
                run_campaign(
                    config_path=G37_PILOT_CONFIG,
                    repo_root=REPO_ROOT,
                    output_root=Path(temporary) / "runs",
                    api_key=FAKE_KEY,
                    live_authorized=True,
                    confirm_campaign=G37_PILOT_ID,
                )

    @unittest.skipUnless(HAS_CREWAI, "requires the pinned CrewAI environment")
    def test_closed_crewai_pilot_is_not_reported_ready_and_cannot_run(self) -> None:
        config, _ = load_and_validate_campaign(CREW_GEMINI_PILOT_CONFIG, REPO_ROOT)
        report = crewai_readiness_report(CREW_GEMINI_PILOT_CONFIG, REPO_ROOT)

        self.assertIsNotNone(campaign_live_block_reason(config))
        self.assertEqual(report["status"], "LIVE_BLOCKED")
        self.assertIn("45-second", report["live_block_reason"])
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "live run is blocked"):
                run_crewai_campaign(
                    config_path=CREW_GEMINI_PILOT_CONFIG,
                    repo_root=REPO_ROOT,
                    output_root=Path(temporary) / "runs",
                    api_key=FAKE_KEY,
                    live_authorized=True,
                    confirm_campaign=CREW_GEMINI_PILOT_ID,
                )

    @unittest.skipUnless(HAS_CREWAI, "requires the pinned CrewAI environment")
    def test_completed_crewai_campaigns_are_not_reported_ready_and_cannot_run(
        self,
    ) -> None:
        for campaign_id, config_path, expected_reason in (
            (
                CREW_GEMINI_SMOKE_002_ID,
                CREW_GEMINI_SMOKE_002_CONFIG,
                "recorded 5/5 successful smoke",
            ),
            (
                CREW_GEMINI_PILOT_002_ID,
                CREW_GEMINI_PILOT_002_CONFIG,
                "recorded 30/30 successful",
            ),
            (
                CREW_GPT54_NANO_SMOKE_003_ID,
                CREW_GPT54_NANO_SMOKE_003_CONFIG,
                "audited 5/5 successful",
            ),
            (
                CREW_GPT54_NANO_PILOT_002_ID,
                CREW_GPT54_NANO_PILOT_002_CONFIG,
                "recorded 30/30 technically successful",
            ),
            (
                CREW_GEMINI31_SMOKE_002_ID,
                CREW_GEMINI31_SMOKE_002_CONFIG,
                "audited 5/5 successful",
            ),
            (
                CREW_GEMINI31_PILOT_002_ID,
                CREW_GEMINI31_PILOT_002_CONFIG,
                "recorded 30/30 technically successful",
            ),
            (
                CREW_GPT54_MINI_SMOKE_002_ID,
                CREW_GPT54_MINI_SMOKE_002_CONFIG,
                "audited 5/5 successful",
            ),
            (
                CREW_GPT54_MINI_PILOT_002_ID,
                CREW_GPT54_MINI_PILOT_002_CONFIG,
                "recorded 30/30 technically successful",
            ),
        ):
            with self.subTest(campaign_id=campaign_id):
                config, _ = load_and_validate_campaign(config_path, REPO_ROOT)
                report = crewai_readiness_report(config_path, REPO_ROOT)

                self.assertIsNotNone(campaign_live_block_reason(config))
                self.assertEqual(report["status"], "LIVE_BLOCKED")
                self.assertIn(expected_reason, report["live_block_reason"])
                with tempfile.TemporaryDirectory() as temporary:
                    with self.assertRaisesRegex(ValueError, "live run is blocked"):
                        run_crewai_campaign(
                            config_path=config_path,
                            repo_root=REPO_ROOT,
                            output_root=Path(temporary) / "runs",
                            api_key=FAKE_KEY,
                            live_authorized=True,
                            confirm_campaign=campaign_id,
                        )

    def test_cli_blocks_closed_campaign_before_reading_api_key(self) -> None:
        for campaign_id, config_path in (
            (G37_PILOT_ID, G37_PILOT_CONFIG),
            (CREW_GEMINI_SMOKE_001_ID, CREW_GEMINI_SMOKE_001_CONFIG),
            (CREW_GEMINI_SMOKE_002_ID, CREW_GEMINI_SMOKE_002_CONFIG),
            (CREW_GEMINI_PILOT_ID, CREW_GEMINI_PILOT_CONFIG),
            (CREW_GEMINI_PILOT_002_ID, CREW_GEMINI_PILOT_002_CONFIG),
            (CREW_GPT54_NANO_SMOKE_001_ID, CREW_GPT54_NANO_SMOKE_001_CONFIG),
            (CREW_GPT54_NANO_SMOKE_002_ID, CREW_GPT54_NANO_SMOKE_002_CONFIG),
            (CREW_GPT54_NANO_SMOKE_003_ID, CREW_GPT54_NANO_SMOKE_003_CONFIG),
            (CREW_GPT54_NANO_PILOT_002_ID, CREW_GPT54_NANO_PILOT_002_CONFIG),
            (CREW_GEMINI31_SMOKE_002_ID, CREW_GEMINI31_SMOKE_002_CONFIG),
            (CREW_GEMINI31_PILOT_002_ID, CREW_GEMINI31_PILOT_002_CONFIG),
            (CREW_GPT54_MINI_SMOKE_002_ID, CREW_GPT54_MINI_SMOKE_002_CONFIG),
            (CREW_GPT54_MINI_PILOT_002_ID, CREW_GPT54_MINI_PILOT_002_CONFIG),
        ):
            with self.subTest(campaign_id=campaign_id):
                stderr = io.StringIO()
                with (
                    patch.dict(
                        os.environ,
                        {"GEMINI_API_KEY": "", "OPENAI_API_KEY": ""},
                    ),
                    contextlib.redirect_stderr(stderr),
                ):
                    exit_code = benchmark_main(
                        [
                            "run",
                            "--campaign",
                            str(config_path),
                            "--live",
                            "--confirm-campaign",
                            campaign_id,
                        ]
                    )

                self.assertEqual(exit_code, 2)
                self.assertIn("live run is blocked", stderr.getvalue())
                self.assertNotIn("ustaw GEMINI_API_KEY", stderr.getvalue())
                self.assertNotIn("ustaw OPENAI_API_KEY", stderr.getvalue())

    def test_cli_rejects_google_key_for_openai_before_crewai_import(self) -> None:
        wrong_key = "AIza" + "X" * 32
        stderr = io.StringIO()
        open_campaigns = {
            campaign_id: reason
            for campaign_id, reason in LIVE_BLOCKED_CAMPAIGNS.items()
            if campaign_id != CREW_GPT54_MINI_PILOT_002_ID
        }
        with (
            patch.dict(LIVE_BLOCKED_CAMPAIGNS, open_campaigns, clear=True),
            patch.dict(os.environ, {"OPENAI_API_KEY": wrong_key}),
            contextlib.redirect_stderr(stderr),
        ):
            exit_code = benchmark_main(
                [
                    "run",
                    "--campaign",
                    str(CREW_GPT54_MINI_PILOT_002_CONFIG),
                    "--live",
                    "--confirm-campaign",
                    CREW_GPT54_MINI_PILOT_002_ID,
                ]
            )

        self.assertEqual(exit_code, 2)
        self.assertIn("appears to contain a Google API key", stderr.getvalue())
        self.assertIn("no provider request was made", stderr.getvalue())
        self.assertNotIn(wrong_key, stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
