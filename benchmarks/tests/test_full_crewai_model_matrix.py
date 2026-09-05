from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"

import sys

sys.path.insert(0, str(BENCHMARKS_DIR))

from phishing_bench.contracts import (  # noqa: E402
    CREWAI_CONCISE_V2_CAMPAIGN_IDS,
    CREWAI_CURRENT_MODEL_MATRIX_CAMPAIGN_IDS,
    CREWAI_GEMINI37_OUTPUT_RECOVERY_CAMPAIGN_IDS,
    CREWAI_GEMINI31_FLASH_LITE_QUALITY_PILOT_PROFILE,
    CREWAI_GEMINI31_FLASH_LITE_SMOKE_PROFILE,
    CREWAI_GEMINI37_FLASH_QUALITY_PILOT_PROFILE,
    CREWAI_GEMINI37_FLASH_SMOKE_PROFILE,
    CREWAI_GPT54_MINI_QUALITY_PILOT_PROFILE,
    CREWAI_GPT54_MINI_SMOKE_PROFILE,
    CREWAI_GPT54_NANO_QUALITY_PILOT_PROFILE,
    CREWAI_GPT54_NANO_SMOKE_PROFILE,
    ContractError,
    campaign_live_block_reason,
    load_and_validate_campaign,
    validate_runtime_config,
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
            config("BUDGET_30H_CREWAI_OPENAI_GPT54_NANO_OFFLINE_SMOKE_003"),
            config("BUDGET_30H_CREWAI_OPENAI_GPT54_NANO_OFFLINE_PILOT_030_002"),
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
            config("BUDGET_30H_CREWAI_OPENAI_GPT54_MINI_OFFLINE_SMOKE_002"),
            config("BUDGET_30H_CREWAI_OPENAI_GPT54_MINI_OFFLINE_PILOT_030_002"),
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
            config("BUDGET_30H_CREWAI_GOOGLE_GEMINI31_FLASH_LITE_OFFLINE_SMOKE_002"),
            config("BUDGET_30H_CREWAI_GOOGLE_GEMINI31_FLASH_LITE_OFFLINE_PILOT_030_002"),
        ),
    },
    "gemini37": {
        "profiles": (
            CREWAI_GEMINI37_FLASH_SMOKE_PROFILE,
            CREWAI_GEMINI37_FLASH_QUALITY_PILOT_PROFILE,
        ),
        "direct": (
            config("BUDGET_30H_GOOGLE_NATIVE_GEMINI37_FLASH_SMOKE_002"),
            config("BUDGET_30H_GOOGLE_NATIVE_GEMINI37_FLASH_PILOT_030_001"),
        ),
        "crew": (
            config("BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_SMOKE_003"),
            config("BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_PILOT_030_003"),
        ),
    },
}

SUPERSEDED_OR_COMPLETED_V1 = (
    "BUDGET_30H_CREWAI_OPENAI_GPT54_NANO_OFFLINE_SMOKE_001",
    "BUDGET_30H_CREWAI_OPENAI_GPT54_NANO_OFFLINE_SMOKE_002",
    "BUDGET_30H_CREWAI_OPENAI_GPT54_NANO_OFFLINE_PILOT_030_001",
    "BUDGET_30H_CREWAI_OPENAI_GPT54_MINI_OFFLINE_SMOKE_001",
    "BUDGET_30H_CREWAI_OPENAI_GPT54_MINI_OFFLINE_PILOT_030_001",
    "BUDGET_30H_CREWAI_GOOGLE_GEMINI31_FLASH_LITE_OFFLINE_SMOKE_001",
    "BUDGET_30H_CREWAI_GOOGLE_GEMINI31_FLASH_LITE_OFFLINE_PILOT_030_001",
    "BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_SMOKE_001",
    "BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_PILOT_030_001",
    "BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_SMOKE_002",
    "BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_PILOT_030_002",
)

V1_TO_CONCISE_V2_PAIRS = (
    (
        "BUDGET_30H_CREWAI_OPENAI_GPT54_NANO_OFFLINE_SMOKE_002",
        "BUDGET_30H_CREWAI_OPENAI_GPT54_NANO_OFFLINE_SMOKE_003",
    ),
    (
        "BUDGET_30H_CREWAI_OPENAI_GPT54_NANO_OFFLINE_PILOT_030_001",
        "BUDGET_30H_CREWAI_OPENAI_GPT54_NANO_OFFLINE_PILOT_030_002",
    ),
    (
        "BUDGET_30H_CREWAI_OPENAI_GPT54_MINI_OFFLINE_SMOKE_001",
        "BUDGET_30H_CREWAI_OPENAI_GPT54_MINI_OFFLINE_SMOKE_002",
    ),
    (
        "BUDGET_30H_CREWAI_OPENAI_GPT54_MINI_OFFLINE_PILOT_030_001",
        "BUDGET_30H_CREWAI_OPENAI_GPT54_MINI_OFFLINE_PILOT_030_002",
    ),
    (
        "BUDGET_30H_CREWAI_GOOGLE_GEMINI31_FLASH_LITE_OFFLINE_SMOKE_001",
        "BUDGET_30H_CREWAI_GOOGLE_GEMINI31_FLASH_LITE_OFFLINE_SMOKE_002",
    ),
    (
        "BUDGET_30H_CREWAI_GOOGLE_GEMINI31_FLASH_LITE_OFFLINE_PILOT_030_001",
        "BUDGET_30H_CREWAI_GOOGLE_GEMINI31_FLASH_LITE_OFFLINE_PILOT_030_002",
    ),
    (
        "BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_SMOKE_001",
        "BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_SMOKE_002",
    ),
    (
        "BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_PILOT_030_001",
        "BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_PILOT_030_002",
    ),
)

GEMINI37_V2_TO_OUTPUT_RECOVERY_V3_PAIRS = (
    (
        "BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_SMOKE_002",
        "BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_SMOKE_003",
    ),
    (
        "BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_PILOT_030_002",
        "BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_PILOT_030_003",
    ),
)


class FullCrewAIModelMatrixContractTests(unittest.TestCase):
    def test_nano_auth_retry_changes_only_campaign_and_config_ids(self) -> None:
        failed_auth = read_json(
            config("BUDGET_30H_CREWAI_OPENAI_GPT54_NANO_OFFLINE_SMOKE_001")
        )
        corrected_auth = read_json(
            config("BUDGET_30H_CREWAI_OPENAI_GPT54_NANO_OFFLINE_SMOKE_002")
        )

        for value in (failed_auth, corrected_auth):
            value.pop("campaign_id")
            value.pop("config_id")

        self.assertEqual(corrected_auth, failed_auth)

    def test_every_model_has_matching_direct_and_crewai_smoke_and_pilot_assets(self) -> None:
        framework_profiles = []
        crew_prompts = []
        crew_profiles = []
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
                        self.assertEqual(direct["max_output_tokens"], 500)
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
                        self.assertEqual(crew["max_output_tokens"], 1000)
                        self.assertFalse(
                            crew["system_bundle_delta"]["same_max_output_tokens"]
                        )
                        self.assertEqual(
                            crew["system_bundle_delta"]["direct_max_output_tokens"],
                            500,
                        )
                        self.assertEqual(
                            crew["system_bundle_delta"]["crewai_max_output_tokens"],
                            1000,
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
                    crew_prompts.append(crew_assets["prompt"])
                    crew_profiles.append(crew_assets["crew_profile"])

        self.assertTrue(
            all(value == framework_profiles[0] for value in framework_profiles[1:])
        )
        self.assertTrue(all(value == crew_prompts[0] for value in crew_prompts[1:]))
        self.assertTrue(
            all(value == crew_profiles[0] for value in crew_profiles[1:])
        )
        self.assertEqual(
            crew_profiles[0]["profile_id"],
            "guardian_crewai_offline_v2_concise_specialists",
        )
        self.assertIn("najwyżej 600 znaków", str(crew_profiles[0]))

    def test_campaign_gates_match_audited_matrix_progress(self) -> None:
        matrix_campaign_ids = set()
        for name, row in MATRIX.items():
            with self.subTest(model=name):
                smoke, _ = load_and_validate_campaign(row["crew"][0], REPO_ROOT)
                pilot, _ = load_and_validate_campaign(row["crew"][1], REPO_ROOT)
                matrix_campaign_ids.update((smoke["campaign_id"], pilot["campaign_id"]))
                if name == "gpt54_nano":
                    self.assertIn(
                        "64067e56", campaign_live_block_reason(smoke) or ""
                    )
                    self.assertIn(
                        "195f5483", campaign_live_block_reason(pilot) or ""
                    )
                elif name == "gpt54_mini":
                    self.assertIn(
                        "f469a51c", campaign_live_block_reason(smoke) or ""
                    )
                    self.assertIn(
                        "22232745", campaign_live_block_reason(pilot) or ""
                    )
                elif name == "gemini31":
                    self.assertIn(
                        "57ccf719", campaign_live_block_reason(smoke) or ""
                    )
                    self.assertIn(
                        "d4383f53", campaign_live_block_reason(pilot) or ""
                    )
                else:
                    self.assertIn(
                        "4edc9af3", campaign_live_block_reason(smoke) or ""
                    )
                    self.assertIn(
                        "f345115d", campaign_live_block_reason(pilot) or ""
                    )
        self.assertEqual(
            matrix_campaign_ids,
            set(CREWAI_CURRENT_MODEL_MATRIX_CAMPAIGN_IDS),
        )
        self.assertEqual(
            set(CREWAI_CONCISE_V2_CAMPAIGN_IDS) - matrix_campaign_ids,
            {
                "BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_SMOKE_002",
                "BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_PILOT_030_002",
            },
        )

    def test_v1_matrix_campaigns_cannot_be_mixed_with_concise_v2(self) -> None:
        for campaign_id in SUPERSEDED_OR_COMPLETED_V1:
            with self.subTest(campaign_id=campaign_id):
                config_value, _ = load_and_validate_campaign(
                    config(campaign_id), REPO_ROOT
                )
                self.assertIsNotNone(campaign_live_block_reason(config_value))

    def test_concise_v2_changes_only_versioned_prompt_and_profile_assets(self) -> None:
        for v1_id, v2_id in V1_TO_CONCISE_V2_PAIRS:
            with self.subTest(v2_id=v2_id):
                v1 = read_json(config(v1_id))
                v2 = read_json(config(v2_id))
                for value in (v1, v2):
                    value.pop("campaign_id")
                    value.pop("config_id")
                    value.pop("prompt_path")
                    value.pop("crew_profile_path")
                    value["expected_asset_sha256"].pop("prompt")
                    value["expected_asset_sha256"].pop("crew_profile")
                self.assertEqual(v2, v1)

    def test_gemini37_output_recovery_changes_only_disclosed_token_budget(self) -> None:
        recovery_ids = set()
        for v2_id, v3_id in GEMINI37_V2_TO_OUTPUT_RECOVERY_V3_PAIRS:
            with self.subTest(v3_id=v3_id):
                v2 = read_json(config(v2_id))
                v3 = read_json(config(v3_id))
                recovery_ids.add(v3["campaign_id"])

                self.assertEqual(v2["max_output_tokens"], 500)
                self.assertEqual(v3["max_output_tokens"], 1000)
                self.assertFalse(v3["system_bundle_delta"]["same_max_output_tokens"])
                self.assertEqual(
                    v3["system_bundle_delta"]["direct_max_output_tokens"], 500
                )
                self.assertEqual(
                    v3["system_bundle_delta"]["crewai_max_output_tokens"], 1000
                )
                self.assertEqual(
                    v3["system_bundle_delta"]["additional_components"][-1],
                    "gemini37_hidden_reasoning_output_cap_recovery",
                )
                expected_v3_cap = 1.25 if "PILOT" in v3_id else 0.25
                self.assertEqual(v3["budget"]["max_cost_usd"], expected_v3_cap)

                for value in (v2, v3):
                    value.pop("campaign_id")
                    value.pop("config_id")
                    value.pop("max_output_tokens")
                if "PILOT" in v3_id:
                    v2["budget"].pop("max_cost_usd")
                    v3["budget"].pop("max_cost_usd")
                v3_delta = v3["system_bundle_delta"]
                v3_delta.pop("same_max_output_tokens")
                v3_delta.pop("direct_max_output_tokens")
                v3_delta.pop("crewai_max_output_tokens")
                v3_delta["additional_components"].pop()
                self.assertEqual(v3, v2)

        self.assertEqual(
            recovery_ids,
            set(CREWAI_GEMINI37_OUTPUT_RECOVERY_CAMPAIGN_IDS),
        )

    def test_gemini37_output_recovery_limit_is_exact_and_campaign_scoped(self) -> None:
        recovery = read_json(
            config("BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_SMOKE_003")
        )
        recovery["max_output_tokens"] = 999
        with self.assertRaisesRegex(ContractError, "max_output_tokens=1000"):
            validate_runtime_config(recovery, REPO_ROOT)

        historical = read_json(
            config("BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_SMOKE_002")
        )
        historical["max_output_tokens"] = 1000
        with self.assertRaisesRegex(ContractError, "max_output_tokens=500"):
            validate_runtime_config(historical, REPO_ROOT)

        direct = read_json(
            config("BUDGET_30H_GOOGLE_NATIVE_GEMINI37_FLASH_SMOKE_002")
        )
        direct["max_output_tokens"] = 1000
        with self.assertRaisesRegex(ContractError, "Direct.*max_output_tokens=500"):
            validate_runtime_config(direct, REPO_ROOT)

        recovery_pilot = read_json(
            config(
                "BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_PILOT_030_003"
            )
        )
        recovery_pilot["budget"]["max_cost_usd"] = 1.24
        with self.assertRaisesRegex(ContractError, "cost variant drift"):
            validate_runtime_config(recovery_pilot, REPO_ROOT)

        historical_pilot = read_json(
            config(
                "BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_PILOT_030_002"
            )
        )
        historical_pilot["budget"]["max_cost_usd"] = 1.25
        with self.assertRaisesRegex(ContractError, "cost variant drift"):
            validate_runtime_config(historical_pilot, REPO_ROOT)

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
        expected = {
            "gemini31": ("minimal", 500),
            "gemini37": ("low", 1000),
        }
        for name, (thinking_level, max_tokens) in expected.items():
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
                self.assertEqual(
                    [row["max_tokens"] for row in report["effective_profile"]["agents"]],
                    [max_tokens] * 3,
                )
                self.assertTrue(
                    all(
                        row["wire_store_false_verified"] is True
                        for row in report["effective_profile"]["agents"]
                    )
                )


if __name__ == "__main__":
    unittest.main()
