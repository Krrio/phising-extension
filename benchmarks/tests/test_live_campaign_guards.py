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
G37_PILOT_CONFIG = (
    BENCHMARKS_DIR / "campaigns" / G37_PILOT_ID / "runtime_config.json"
)
CREW_GEMINI_PILOT_CONFIG = (
    BENCHMARKS_DIR / "campaigns" / CREW_GEMINI_PILOT_ID / "runtime_config.json"
)
CREW_GEMINI_SMOKE_001_CONFIG = (
    BENCHMARKS_DIR
    / "campaigns"
    / CREW_GEMINI_SMOKE_001_ID
    / "runtime_config.json"
)
HAS_CREWAI = importlib.util.find_spec("crewai") is not None
FAKE_KEY = "gemini_FAKE_live_guard_secret_123456"


class ClosedCampaignGuardTests(unittest.TestCase):
    def test_fail_fast_policy_is_frozen_only_for_active_120_second_campaigns(
        self,
    ) -> None:
        self.assertNotIn(
            CREW_GEMINI_SMOKE_001_ID,
            CREWAI_GEMINI_TRANSIENT_FAIL_FAST_CAMPAIGN_IDS,
        )
        self.assertEqual(
            CREWAI_GEMINI_TRANSIENT_FAIL_FAST_CAMPAIGN_IDS,
            frozenset({CREW_GEMINI_SMOKE_002_ID, CREW_GEMINI_PILOT_002_ID}),
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

    def test_cli_blocks_closed_campaign_before_reading_api_key(self) -> None:
        for campaign_id, config_path in (
            (G37_PILOT_ID, G37_PILOT_CONFIG),
            (CREW_GEMINI_SMOKE_001_ID, CREW_GEMINI_SMOKE_001_CONFIG),
            (CREW_GEMINI_PILOT_ID, CREW_GEMINI_PILOT_CONFIG),
        ):
            with self.subTest(campaign_id=campaign_id):
                stderr = io.StringIO()
                with (
                    patch.dict(os.environ, {"GEMINI_API_KEY": ""}),
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


if __name__ == "__main__":
    unittest.main()
