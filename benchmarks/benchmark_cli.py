#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from phishing_bench.contracts import (
    CREWAI_PROFILES,
    ContractError,
    load_and_validate_campaign,
)
from phishing_bench.comparison import compare_runs, parse_named_run
from phishing_bench.runner import api_key_from_environment, readiness_report, run_campaign
from phishing_bench.scoring import score_run


BENCHMARKS_DIR = Path(__file__).resolve().parent
REPO_ROOT = BENCHMARKS_DIR.parent
DEFAULT_CONFIG = (
    REPO_ROOT
    / "benchmarks"
    / "campaigns"
    / "BUDGET_30H_OPENAI_SMOKE_001"
    / "runtime_config.json"
)


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="benchmark_cli.py",
        description=(
            "Bezpieczny harness OpenAI Direct i CrewAI Offline: smoke oraz "
            "syntetyczny pilot jakości."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="Waliduje kontrakt i budżet bez wywołań API.")
    validate.add_argument("--campaign", type=_path, default=DEFAULT_CONFIG)

    run = commands.add_parser(
        "run", help="Wykonuje dry-run albo jawnie potwierdzony live run wybranej kampanii."
    )
    run.add_argument("--campaign", type=_path, default=DEFAULT_CONFIG)
    run.add_argument("--output-root", type=_path, default=REPO_ROOT / "benchmark-runs")
    run.add_argument("--live", action="store_true", help="Zezwala na płatne outbound API calls.")
    run.add_argument(
        "--store-reasoning",
        action="store_true",
        help="Opt-in tylko dla danych syntetycznych; raport nigdy nie renderuje reasoning.",
    )
    run.add_argument(
        "--confirm-campaign",
        help="Dla live podaj dokładny campaign_id; chroni przed przypadkowym wydatkiem.",
    )

    score = commands.add_parser("score", help="Łączy zakończony run z osobnym scoring bundle.")
    score.add_argument("--run-dir", type=_path, required=True)
    score.add_argument("--labels", type=_path, required=True)
    score.add_argument("--output-dir", type=_path)

    compare = commands.add_parser(
        "compare",
        help="Porównuje offline co najmniej dwa scored quality runy i eksportuje dane do wykresów.",
    )
    compare.add_argument(
        "--run",
        dest="named_runs",
        action="append",
        type=parse_named_run,
        required=True,
        metavar="NAZWA=RUN_DIR",
        help="Powtarzalny wariant; pierwszy jest baseline.",
    )
    compare.add_argument("--labels", type=_path, required=True)
    compare.add_argument("--output-dir", type=_path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            config, _ = load_and_validate_campaign(args.campaign, REPO_ROOT)
            if config.get("evaluation_profile") in CREWAI_PROFILES:
                from phishing_bench.crewai_offline import crewai_readiness_report

                report = crewai_readiness_report(
                    args.campaign, REPO_ROOT, check_local_tls=True
                )
            else:
                report = readiness_report(args.campaign, REPO_ROOT, check_local_tls=True)
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            return 0

        if args.command == "run":
            config, _ = load_and_validate_campaign(args.campaign, REPO_ROOT)
            if not args.live:
                if config.get("evaluation_profile") in CREWAI_PROFILES:
                    from phishing_bench.crewai_offline import crewai_readiness_report

                    report = crewai_readiness_report(
                        args.campaign, REPO_ROOT, check_local_tls=True
                    )
                else:
                    report = readiness_report(
                        args.campaign, REPO_ROOT, check_local_tls=True
                    )
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
                print(
                    "\nDRY-RUN: nie wykonano żadnego requestu. "
                    "Do live wymagane są --live oraz --confirm-campaign z dokładnym campaign_id."
                )
                return 0
            if args.confirm_campaign != config["campaign_id"]:
                raise ContractError(
                    "live run wymaga --confirm-campaign " + str(config["campaign_id"])
                )
            api_key = api_key_from_environment(args.campaign, REPO_ROOT)
            if not api_key:
                raise ContractError("ustaw OPENAI_API_KEY w środowisku procesu")
            if config.get("evaluation_profile") in CREWAI_PROFILES:
                # Import only after the CLI has independently confirmed an
                # explicitly exported key. CrewAI 1.15.8 can load .env during
                # import and must never bypass this gate.
                from phishing_bench.crewai_offline import run_crewai_campaign

                run_dir = run_crewai_campaign(
                    config_path=args.campaign,
                    repo_root=REPO_ROOT,
                    output_root=args.output_root,
                    api_key=api_key,
                    store_reasoning=args.store_reasoning,
                    live_authorized=args.live,
                    confirm_campaign=args.confirm_campaign,
                )
            else:
                run_dir = run_campaign(
                    config_path=args.campaign,
                    repo_root=REPO_ROOT,
                    output_root=args.output_root,
                    api_key=api_key,
                    store_reasoning=args.store_reasoning,
                    live_authorized=args.live,
                    confirm_campaign=args.confirm_campaign,
                )
            print(f"Run zakończony. Wyniki: {run_dir}")
            return 0

        if args.command == "score":
            output_dir = score_run(
                run_dir=args.run_dir,
                labels_path=args.labels,
                output_dir=args.output_dir,
                repo_root=REPO_ROOT,
            )
            print(f"Scoring i raport: {output_dir}")
            return 0

        if args.command == "compare":
            output_dir = compare_runs(
                named_run_dirs=args.named_runs,
                labels_path=args.labels,
                output_dir=args.output_dir,
                repo_root=REPO_ROOT,
            )
            print(f"Porównanie i dane do wykresów: {output_dir}")
            return 0

        raise AssertionError("unreachable command")
    except (ContractError, FileNotFoundError, PermissionError, json.JSONDecodeError) as exc:
        print(f"BŁĄD: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
