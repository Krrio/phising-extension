from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"

import sys

sys.path.insert(0, str(BENCHMARKS_DIR))

from phishing_bench.contracts import (  # noqa: E402
    CREWAI_GEMINI31_FLASH_LITE_QUALITY_PILOT_PROFILE,
    CREWAI_GEMINI31_FLASH_LITE_SMOKE_PROFILE,
    CREWAI_GEMINI37_FLASH_QUALITY_PILOT_PROFILE,
    CREWAI_GEMINI37_FLASH_SMOKE_PROFILE,
    CREWAI_GPT54_MINI_QUALITY_PILOT_PROFILE,
    CREWAI_GPT54_MINI_SMOKE_PROFILE,
    CREWAI_GPT54_NANO_QUALITY_PILOT_PROFILE,
    CREWAI_GPT54_NANO_SMOKE_PROFILE,
    campaign_live_block_reason,
    load_and_validate_campaign,
)
from phishing_bench.crewai_offline import (  # noqa: E402
    _import_benchmark_factory,
    crewai_runtime_preflight,
)
from phishing_bench.io_utils import read_json  # noqa: E402


CAMPAIGNS = BENCHMARKS_DIR / "campaigns"
SCORING = BENCHMARKS_DIR / "secure_scoring"
HAS_CREWAI = importlib.util.find_spec("crewai") is not None


def config(campaign_id: str) -> Path:
    return CAMPAIGNS / campaign_id / "runtime_config.json"


MATRIX = {
    "gpt54_nano": {
        "profiles": (
            CREWAI_GPT54_NANO_SMOKE_PROFILE,
            CREWAI_GPT54_NANO_QUALITY_PILOT_PROFILE,
        ),
        "direct": (
            config("BUDGET_30H_OPENAI_GPT54_NANO_SMOKE_001"),
            config("BUDGET_30H_OPENAI_GPT54_NANO_PILOT_030_001"),
        ),
        "crew": (
            config("BUDGET_30H_CREWAI_OPENAI_GPT54_NANO_OFFLINE_SMOKE_001"),
            config("BUDGET_30H_CREWAI_OPENAI_GPT54_NANO_OFFLINE_PILOT_030_001"),
        ),
    },
    "gpt54_mini": {
        "profiles": (
            CREWAI_GPT54_MINI_SMOKE_PROFILE,
            CREWAI_GPT54_MINI_QUALITY_PILOT_PROFILE,
        ),
        "direct": (
            config("BUDGET_30H_OPENAI_GPT54_MINI_SMOKE_001"),
            config("BUDGET_30H_OPENAI_GPT54_MINI_PILOT_030_001"),
        ),
        "crew": (
            config("BUDGET_30H_CREWAI_OPENAI_GPT54_MINI_OFFLINE_SMOKE_001"),
            config("BUDGET_30H_CREWAI_OPENAI_GPT54_MINI_OFFLINE_PILOT_030_001"),
        ),
    },
    "gemini31": {
        "profiles": (
            CREWAI_GEMINI31_FLASH_LITE_SMOKE_PROFILE,
            CREWAI_GEMINI31_FLASH_LITE_QUALITY_PILOT_PROFILE,
        ),
        "direct": (
            config("BUDGET_30H_GOOGLE_GEMINI31_FLASH_LITE_SMOKE_001"),
            config("BUDGET_30H_GOOGLE_GEMINI31_FLASH_LITE_PILOT_030_001"),
        ),
        "crew": (
            config("BUDGET_30H_CREWAI_GOOGLE_GEMINI31_FLASH_LITE_OFFLINE_SMOKE_001"),
            config("BUDGET_30H_CREWAI_GOOGLE_GEMINI31_FLASH_LITE_OFFLINE_PILOT_030_001"),
        ),
    },
    "gemini37": {
        "profiles": (
            CREWAI_GEMINI37_FLASH_SMOKE_PROFILE,
            CREWAI_GEMINI37_FLASH_QUALITY_PILOT_PROFILE,
        ),
        "direct": (
            config("BUDGET_30H_GOOGLE_NATIVE_GEMINI37_FLASH_SMOKE_001"),
            config("BUDGET_30H_GOOGLE_NATIVE_GEMINI37_FLASH_PILOT_030_001"),
        ),
        "crew": (
            config("BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_SMOKE_001"),
            config("BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_PILOT_030_001"),
        ),
    },
}


class FullCrewAIModelMatrixContractTests(unittest.TestCase):
    def test_every_model_has_matching_direct_and_crewai_smoke_and_pilot_assets(self) -> None:
        framework_profiles = []
        for name, row in MATRIX.items():
            with self.subTest(model=name):
                expected_profiles = row["profiles"]
                direct_paths = row["direct"]
                crew_paths = row["crew"]
                for index, expected_count in enumerate((5, 30)):
                    direct, direct_assets = load_and_validate_campaign(
                        direct_paths[index], REPO_ROOT
                    )
                    crew, crew_assets = load_and_validate_campaign(
                        crew_paths[index], REPO_ROOT
                    )
                    self.assertEqual(crew["evaluation_profile"], expected_profiles[index])
                    self.assertEqual(crew["expected_sample_count"], expected_count)
                    self.assertEqual(crew["requested_model"], direct["requested_model"])
                    self.assertEqual(crew["dataset_path"], direct["dataset_path"])
                    self.assertEqual(crew_assets["dataset"], direct_assets["dataset"])
                    self.assertEqual(
                        crew_assets["response_schema"], direct_assets["response_schema"]
                    )
                    self.assertEqual(
                        crew_assets["decision_policy"], direct_assets["decision_policy"]
                    )
                    self.assertEqual(crew["max_retries_per_sample"], 0)
                    self.assertEqual(crew["request_timeout_seconds"], 120)
                    self.assertEqual(
                        crew["budget"]["max_attempts"], expected_count * 3
                    )
                    if name == "gemini37":
                        self.assertEqual(
                            crew["system_bundle_delta"]["comparison_name"],
                            "system_bundle_delta",
                        )
                        self.assertTrue(
                            crew["system_bundle_delta"]["same_provider_api"]
                        )
                        self.assertEqual(
                            crew["system_bundle_delta"]["direct_api"],
                            "native_generate_content_v1",
                        )
                    elif name == "gemini31":
                        self.assertEqual(
                            crew["system_bundle_delta"]["comparison_name"],
                            "cross_api_system_bundle_delta",
                        )
                        self.assertFalse(
                            crew["system_bundle_delta"]["same_provider_api"]
                        )
                    framework_profiles.append(crew["framework_config"])

        self.assertTrue(
            all(value == framework_profiles[0] for value in framework_profiles[1:])
        )

    def test_only_smokes_are_live_ready_before_their_own_gate_passes(self) -> None:
        for name, row in MATRIX.items():
            with self.subTest(model=name):
                smoke, _ = load_and_validate_campaign(row["crew"][0], REPO_ROOT)
                pilot, _ = load_and_validate_campaign(row["crew"][1], REPO_ROOT)
                self.assertIsNone(campaign_live_block_reason(smoke))
                self.assertIn("prerequisite", campaign_live_block_reason(pilot) or "")

    def test_scoring_bundles_accept_the_complete_new_matrix(self) -> None:
        smoke_manifest = read_json(SCORING / "openai_smoke_v1" / "scoring_manifest.json")
        pilot_manifest = read_json(
            SCORING / "openai_pilot_030_v1" / "scoring_manifest.json"
        )
        for row in MATRIX.values():
            smoke = read_json(row["crew"][0])
            pilot = read_json(row["crew"][1])
            self.assertIn(smoke["campaign_id"], smoke_manifest["compatible_campaign_ids"])
            self.assertIn(pilot["campaign_id"], pilot_manifest["compatible_campaign_ids"])


@unittest.skipUnless(HAS_CREWAI, "requires the pinned backend CrewAI environment")
class FullCrewAIModelMatrixRuntimeTests(unittest.TestCase):
    def test_gpt54_payloads_pin_reasoning_and_completion_token_field(self) -> None:
        build_crew, _ = _import_benchmark_factory("openai")
        for name in ("gpt54_nano", "gpt54_mini"):
            with self.subTest(model=name):
                config_value, assets = load_and_validate_campaign(
                    MATRIX[name]["crew"][0], REPO_ROOT
                )
                bundle = build_crew(
                    api_key="sk-benchmark-placeholder-not-real",
                    requested_model=config_value["requested_model"],
                    temperature=config_value["temperature"],
                    max_output_tokens=config_value["max_output_tokens"],
                    request_timeout_seconds=config_value["request_timeout_seconds"],
                    max_llm_calls=3,
                    response_schema=assets["response_schema"],
                    profile=assets["crew_profile"],
                    provider="openai",
                    reasoning_effort="none",
                )
                try:
                    prepared = [
                        agent.llm.delegate._prepare_completion_params(
                            [{"role": "user", "content": "offline probe"}], tools=[]
                        )
                        for agent in bundle.crew.agents
                    ]
                    self.assertTrue(
                        all(value["reasoning_effort"] == "none" for value in prepared)
                    )
                    self.assertTrue(
                        all(value["max_completion_tokens"] == 500 for value in prepared)
                    )
                    self.assertTrue(all("max_tokens" not in value for value in prepared))
                    self.assertTrue(all(value["store"] is False for value in prepared))
                    self.assertNotIn("response_format", prepared[0])
                    self.assertNotIn("response_format", prepared[1])
                    self.assertEqual(
                        prepared[2]["response_format"], assets["response_schema"]
                    )
                finally:
                    bundle.close()

    def test_google_profiles_use_model_supported_thinking_levels(self) -> None:
        expected = {"gemini31": "minimal", "gemini37": "low"}
        for name, thinking_level in expected.items():
            with self.subTest(model=name):
                config_value, assets = load_and_validate_campaign(
                    MATRIX[name]["crew"][0], REPO_ROOT
                )
                report = crewai_runtime_preflight(config_value, assets)
                self.assertEqual(report["provider_calls_made"], 0)
                self.assertEqual(
                    [row["thinking_level"] for row in report["effective_profile"]["agents"]],
                    [thinking_level] * 3,
                )
                self.assertTrue(
                    all(
                        row["wire_store_false_verified"] is True
                        for row in report["effective_profile"]["agents"]
                    )
                )


if __name__ == "__main__":
    unittest.main()
