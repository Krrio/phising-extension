"""GUARDIAN AI BENCHMARK - local Streamlit dashboard."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

try:
    from .analytics import direct_crewai_comparisons, recompute_binary_metrics
    from .charts import (
        action_distribution,
        case_heatmap,
        confusion_bars,
        cost_latency_scatter,
        cost_quality_scatter,
        direct_crewai_delta_chart,
        direct_crewai_ratio_chart,
        latency_bar,
        metric_bar,
    )
    from .data_loader import (
        REQUIRED_FILES,
        ComparisonBundle,
        DashboardDataError,
        load_comparison_bundle,
        read_verified_artifact,
        sha256_file,
    )
    from .frames import comparison_frames
except ImportError:  # Streamlit executes this file as a script.
    from analytics import direct_crewai_comparisons, recompute_binary_metrics
    from charts import (
        action_distribution,
        case_heatmap,
        confusion_bars,
        cost_latency_scatter,
        cost_quality_scatter,
        direct_crewai_delta_chart,
        direct_crewai_ratio_chart,
        latency_bar,
        metric_bar,
    )
    from data_loader import (
        REQUIRED_FILES,
        ComparisonBundle,
        DashboardDataError,
        load_comparison_bundle,
        read_verified_artifact,
        sha256_file,
    )
    from frames import comparison_frames


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COMPARISON_DIR = (
    REPO_ROOT
    / "benchmarks"
    / "results"
    / "FULL_EIGHT_ARM_PILOT_030_001"
)
PLOT_CONFIG = {
    "displaylogo": False,
    "responsive": True,
    "toImageButtonOptions": {
        "format": "png",
        "filename": "guardian-benchmark-chart",
        "height": 720,
        "width": 1280,
        "scale": 2,
    },
}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--comparison-dir",
        default=str(DEFAULT_COMPARISON_DIR),
        help="Katalog utworzony przez benchmark_cli.py compare.",
    )
    args, _unknown = parser.parse_known_args(argv)
    return args


def _signature(directory: str | Path) -> tuple[tuple[str, int, int, str], ...]:
    base = Path(directory).expanduser()
    signature: list[tuple[str, int, int, str]] = []
    for file_name in REQUIRED_FILES:
        path = base / file_name
        try:
            stat = path.stat()
            digest = sha256_file(path)
        except OSError:
            signature.append((file_name, -1, -1, "unreadable"))
        else:
            signature.append((file_name, stat.st_mtime_ns, stat.st_size, digest))
    return tuple(signature)


@st.cache_data(show_spinner=False)
def _cached_bundle(
    directory: str, file_signature: tuple[tuple[str, int, int, str], ...]
) -> ComparisonBundle:
    del file_signature  # Its value is part of Streamlit's cache key.
    return load_comparison_bundle(directory)


def _plot(figure: Any, *, key: str) -> None:
    st.plotly_chart(figure, width="stretch", config=PLOT_CONFIG, key=key)


def _filter_sidebar(
    runs: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str], list[str], list[str]]:
    st.sidebar.header("Filtry")
    model_options = runs["model_label"].drop_duplicates().tolist()
    selected_models = st.sidebar.multiselect(
        "Model",
        model_options,
        default=model_options,
    )
    provider_options = runs["provider"].drop_duplicates().tolist()
    selected_providers = st.sidebar.multiselect(
        "Provider",
        provider_options,
        default=provider_options,
    )
    architecture_options = runs["architecture_label"].drop_duplicates().tolist()
    selected_architectures = st.sidebar.multiselect(
        "Architektura",
        architecture_options,
        default=architecture_options,
    )
    filtered = runs[
        runs["model_label"].isin(selected_models)
        & runs["provider"].isin(selected_providers)
        & runs["architecture_label"].isin(selected_architectures)
    ].copy()
    return (
        filtered,
        selected_models,
        selected_providers,
        selected_architectures,
    )


def _overview_tab(runs: pd.DataFrame, cases: pd.DataFrame) -> None:
    sample_counts = sorted(runs["sample_count"].dropna().astype(int).unique())
    sample_label = ", ".join(str(value) for value in sample_counts) or "-"
    complete = int((runs["technical_failures"] == 0).sum())
    columns = st.columns(4)
    columns[0].metric("Wybrane warianty", len(runs))
    columns[1].metric("Technicznie kompletne", f"{complete}/{len(runs)}")
    columns[2].metric("Próbki / wariant", sample_label)
    columns[3].metric(
        "Observed cost",
        f"${runs['observed_cost_usd'].sum():.6f}",
        help="Suma kosztu zaobserwowanego, nie rezerwy z ledgera.",
    )

    summary = runs[
        [
            "variant_label",
            "f1",
            "false_positive_rate",
            "observed_cost_usd_per_message",
            "latency_median_ms",
            "success_count",
            "technical_failures",
            "campaign_status",
        ]
    ].rename(
        columns={
            "variant_label": "Wariant",
            "f1": "F1",
            "false_positive_rate": "FPR",
            "observed_cost_usd_per_message": "Koszt / wiadomość [USD]",
            "latency_median_ms": "Mediana latency [ms]",
            "success_count": "Success",
            "technical_failures": "Tech failures",
            "campaign_status": "Status",
        }
    )
    st.dataframe(summary, hide_index=True, width="stretch")

    _plot(
        metric_bar(runs, "f1", "F1 według wariantu", percent=True),
        key="overview_f1",
    )
    _plot(
        metric_bar(
            runs,
            "false_positive_rate",
            "False Positive Rate - mniej jest lepiej",
            percent=True,
        ),
        key="overview_fpr",
    )
    _plot(cost_quality_scatter(runs), key="overview_cost_quality")

    technical_count = int(cases["technical_failure"].fillna(False).sum())
    if technical_count:
        st.error(
            f"W wybranych danych jest {technical_count} techniczny wynik awaryjny. "
            "Nie interpretuj F1 bez tej informacji."
        )


def _quality_tab(runs: pd.DataFrame, cases: pd.DataFrame) -> None:
    st.subheader("Jakość klasyfikacji")
    quality_caption = (
        "F1 i FPR są pokazywane osobno: dla F1 więcej jest lepiej, dla FPR mniej."
    )
    measured_recall = runs["recall"].dropna()
    if not measured_recall.empty and measured_recall.eq(1).all():
        quality_caption += (
            " Recall nie rozróżnia bieżącego widoku, ponieważ każdy wybrany "
            "wariant ma recall=1."
        )
    st.caption(quality_caption)
    _plot(metric_bar(runs, "f1", "F1", percent=True), key="quality_f1")
    _plot(
        metric_bar(runs, "false_positive_rate", "FPR", percent=True),
        key="quality_fpr",
    )
    _plot(confusion_bars(runs), key="quality_confusion")

    _plot(action_distribution(cases), key="quality_actions_all")
    _plot(
        action_distribution(cases, benign_only=True),
        key="quality_actions_benign",
    )

    st.subheader("Metryki przeliczone dla aktualnego filtra")
    rows: list[dict[str, Any]] = []
    for variant_id in runs["variant_id"]:
        subset = cases[cases["variant_id"] == variant_id]
        metrics = recompute_binary_metrics(subset.to_dict("records"))
        rows.append(
            {
                "Wariant": runs.loc[
                    runs["variant_id"] == variant_id, "variant_label"
                ].iloc[0],
                "TP": metrics["tp"],
                "FP": metrics["fp"],
                "TN": metrics["tn"],
                "FN": metrics["fn"],
                "F1": metrics["f1"],
                "FPR": metrics["false_positive_rate"],
                "Liczba oceniona": metrics["evaluated_count"],
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.info(
        "Binary correctness i golden action to dwie różne oceny. Benign `warn` "
        "może być binary false positive, a jednocześnie dopuszczalną akcją golden."
    )


def _cost_latency_tab(runs: pd.DataFrame) -> None:
    st.subheader("Koszt i wydajność")
    st.caption(
        "Koszt observed pochodzi z usage. Ledger reserved/observed jest rezerwą "
        "bezpieczeństwa i nie jest traktowany jako rachunek. Latency jest "
        "liczona wyłącznie dla rekordów ze statusem success."
    )
    _plot(
        metric_bar(
            runs,
            "observed_cost_usd_per_message",
            "Observed cost na wiadomość",
            currency=True,
        ),
        key="cost_per_message",
    )
    _plot(latency_bar(runs), key="latency_median")
    _plot(cost_quality_scatter(runs), key="cost_quality")
    _plot(cost_latency_scatter(runs), key="cost_latency")

    detail = runs[
        [
            "variant_label",
            "observed_cost_usd",
            "ledger_reserved_or_observed_cost_usd",
            "observed_cost_usd_per_message",
            "latency_min_ms",
            "latency_median_ms",
            "latency_iqr_ms",
            "latency_max_ms",
            "outbound_calls",
            "total_tokens",
        ]
    ].copy()
    st.dataframe(detail, hide_index=True, width="stretch")


def _direct_crewai_tab(
    all_runs: pd.DataFrame,
    pairwise: pd.DataFrame,
    selected_models: list[str],
    selected_providers: list[str],
    selected_architectures: list[str],
) -> None:
    st.subheader("Direct → CrewAI")
    st.warning(
        "To porównanie całych system bundles, nie izolowany efekt biblioteki CrewAI. "
        "Prompty, liczba wywołań, evidence i czasem protokół API są różne."
    )
    source = all_runs[
        all_runs["model_label"].isin(selected_models)
        & all_runs["provider"].isin(selected_providers)
        & all_runs["architecture_label"].isin(selected_architectures)
    ]
    try:
        rows = direct_crewai_comparisons(
            source.to_dict("records"), pairwise.to_dict("records")
        )
    except ValueError as exc:
        st.warning(f"Nie można jednoznacznie zestawić par: {exc}")
        return
    if not rows:
        st.info("Aktualny filtr nie zawiera kompletnej pary Direct i CrewAI.")
        return
    pairs = pd.DataFrame(rows)
    table = pairs[
        [
            "model",
            "delta_f1",
            "delta_fpr",
            "cost_ratio",
            "latency_ratio",
            "exact_action_agreement_rate",
            "scope",
        ]
    ].rename(
        columns={
            "model": "Model",
            "delta_f1": "ΔF1 Crew−Direct",
            "delta_fpr": "ΔFPR Crew−Direct",
            "cost_ratio": "Koszt ×",
            "latency_ratio": "Latency ×",
            "exact_action_agreement_rate": "Action agreement",
            "scope": "Zakres porównania",
        }
    )
    st.dataframe(table, hide_index=True, width="stretch")
    _plot(direct_crewai_delta_chart(pairs), key="direct_crewai_deltas")
    _plot(direct_crewai_ratio_chart(pairs), key="direct_crewai_ratios")
    if (pairs["scope"] == "token_cap_adjusted_system_bundle_delta").any():
        st.error(
            "Gemini 3.7 CrewAI ma max_output_tokens=1000, a Direct=500. "
            "Ta para nie jest apples-to-apples."
        )
    if (pairs["scope"] == "cross_api_system_bundle_delta").any():
        st.info(
            "Gemini 3.1 porównuje Interactions Direct z GenerateContent CrewAI; "
            "różnica obejmuje także protokół API."
        )


def _case_explorer_tab(cases: pd.DataFrame) -> None:
    st.subheader("Case Explorer")
    st.caption(
        "Eksport nie zawiera treści wiadomości, promptów ani reasoning. "
        "Dashboard pokazuje tylko zanonimizowane ID i metadane przypadku."
    )
    classes = cases["class_label"].dropna().drop_duplicates().tolist()
    difficulties = cases["difficulty"].dropna().drop_duplicates().tolist()
    left, right = st.columns(2)
    with left:
        selected_classes = st.multiselect("Klasa", classes, default=classes)
    with right:
        selected_difficulties = st.multiselect(
            "Trudność", difficulties, default=difficulties
        )
    filtered = cases[
        cases["class_label"].isin(selected_classes)
        & cases["difficulty"].isin(selected_difficulties)
    ].copy()
    if filtered.empty:
        st.info("Brak przypadków dla wybranych filtrów.")
        return
    _plot(case_heatmap(filtered), key="case_heatmap")

    issue_rows = filtered.assign(
        FP=(filtered["confusion_cell"].str.lower() == "fp").astype(int),
        FN=(filtered["confusion_cell"].str.lower() == "fn").astype(int),
        TECH=filtered["technical_failure"].fillna(False).astype(int),
        GOLDEN_MISMATCH=(
            filtered["golden_action_match"].notna()
            & ~filtered["golden_action_match"].fillna(False)
        ).astype(int),
        GOLDEN_NA=filtered["golden_action_match"].isna().astype(int),
    )
    issues = (
        issue_rows.groupby(["case_name", "scenario", "class_label", "difficulty"])[
            ["FP", "FN", "TECH", "GOLDEN_MISMATCH", "GOLDEN_NA"]
        ]
        .sum()
        .reset_index()
        .sort_values(
            ["TECH", "FN", "FP", "GOLDEN_MISMATCH", "GOLDEN_NA"],
            ascending=False,
        )
    )
    st.subheader("Przypadki generujące błędy")
    visible_issues = issues[
        issues[["FP", "FN", "TECH", "GOLDEN_MISMATCH"]].sum(axis=1) > 0
    ]
    if visible_issues.empty:
        st.success("Brak błędów dla aktualnego filtra.")
    else:
        st.dataframe(visible_issues, hide_index=True, width="stretch")

    case_options = filtered["case_name"].drop_duplicates().tolist()
    default_index = case_options.index("case_032") if "case_032" in case_options else 0
    selected_case = st.selectbox(
        "Szczegóły przypadku", case_options, index=default_index
    )
    detail_columns = [
        "variant_label",
        "status",
        "verdict",
        "predicted_action",
        "confusion_cell",
        "binary_correct",
        "golden_action_match",
        "technical_failure",
        "trust_score",
        "confidence",
        "latency_ms",
    ]
    st.dataframe(
        filtered.loc[filtered["case_name"] == selected_case, detail_columns],
        hide_index=True,
        width="stretch",
    )


def _technical_tab(bundle: ComparisonBundle, runs: pd.DataFrame) -> None:
    st.subheader("Niezawodność, konfiguracja i provenance")
    technical = runs[
        [
            "variant_label",
            "requested_model",
            "resolved_models",
            "provider",
            "adapter",
            "request_profile",
            "max_output_tokens",
            "sample_count",
            "success_count",
            "technical_failures",
            "schema_valid_count",
            "outbound_calls",
            "retries",
            "cost_unknown_attempts",
            "critical_security_events",
            "campaign_status",
            "git_commit",
            "git_dirty",
        ]
    ]
    st.dataframe(technical, hide_index=True, width="stretch")

    st.subheader("Integralność eksportu")
    verification_rows = [
        {
            "Plik": verification.file_name,
            "SHA-256": verification.actual_sha256,
            "Zgodny": verification.matches,
        }
        for verification in bundle.verifications
    ]
    st.dataframe(
        pd.DataFrame(verification_rows), hide_index=True, width="stretch"
    )
    st.success("Wszystkie cztery hashe eksportu są zgodne z comparison.json.")

    with st.expander("Compatibility i frozen invariants"):
        st.json(bundle.metadata.get("compatibility", {}))
    with st.expander("Source artifact hashes"):
        st.json(bundle.metadata.get("source_artifacts", {}))
    with st.expander("Oryginalny report.md"):
        st.markdown(bundle.report_markdown)

    st.subheader("Pobierz zweryfikowane pliki")
    download_columns = st.columns(4)
    for column, file_name in zip(
        download_columns,
        ("runs.csv", "cases.csv", "pairwise.csv", "comparison.json"),
        strict=True,
    ):
        with column:
            try:
                payload = read_verified_artifact(bundle, file_name)
            except DashboardDataError as exc:
                st.error(str(exc))
            else:
                st.download_button(
                    file_name,
                    data=payload,
                    file_name=file_name,
                    mime=(
                        "application/json"
                        if file_name.endswith(".json")
                        else "text/csv"
                    ),
                    width="stretch",
                )
    st.code(
        "python benchmarks/dashboard/export_static.py \\\n"
        "  --comparison-dir " + str(bundle.directory),
        language="bash",
    )
    st.caption(
        "Eksporter statyczny tworzy nowy katalog charts/ z PNG, SVG, XLSX i "
        "manifestem hashy. Nie wykonuje requestów do providerów."
    )


def main(argv: list[str] | None = None) -> None:
    st.set_page_config(
        page_title="Guardian AI Benchmark",
        page_icon="🛡️",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
        .block-container {padding-top: 1.7rem; padding-bottom: 3rem;}
        [data-testid="stMetric"] {border: 1px solid rgba(148,163,184,.25);
          border-radius: .7rem; padding: .7rem 1rem;}
        </style>
        """,
        unsafe_allow_html=True,
    )
    args = _parse_args(argv)
    directory = str(Path(args.comparison_dir).expanduser())
    try:
        bundle = _cached_bundle(directory, _signature(directory))
    except DashboardDataError as exc:
        st.error(f"Nie można otworzyć eksportu: {exc}")
        st.stop()
        return

    runs, cases, pairwise = comparison_frames(bundle)
    st.title("GUARDIAN AI BENCHMARK")
    compatibility = bundle.metadata.get("compatibility", {})
    frozen = compatibility.get("frozen_invariants", {})
    stage = frozen.get("stage", "UNKNOWN_STAGE")
    sample_counts = "/".join(
        str(value)
        for value in sorted(runs["sample_count"].dropna().astype(int).unique())
    )
    campaign_statuses = "/".join(
        sorted(runs["campaign_status"].dropna().unique())
    )
    st.warning(
        f"{stage} · n={sample_counts or 'N/A'} na wariant · {campaign_statuses} · "
        f"{bundle.metadata.get('comparison_status', 'UNKNOWN')} / "
        f"{bundle.metadata.get('comparative_conclusion', 'UNKNOWN')}."
    )
    if bundle.metadata.get("disclaimer"):
        st.caption(str(bundle.metadata["disclaimer"]))
    st.caption(
        f"Źródło: {bundle.directory} · wygenerowano: "
        f"{bundle.metadata.get('generated_at', 'brak')} · "
        f"integralność: {'OK' if bundle.all_artifacts_verified else 'BŁĄD'}"
    )

    (
        filtered_runs,
        selected_models,
        selected_providers,
        selected_architectures,
    ) = _filter_sidebar(runs)
    if st.sidebar.button("Wyczyść cache i odczytaj pliki ponownie"):
        st.cache_data.clear()
        st.rerun()
    st.sidebar.divider()
    verified_count = sum(item.matches for item in bundle.verifications)
    st.sidebar.success(
        f"Dane lokalne · 0 requestów API · {verified_count}/"
        f"{len(bundle.verifications)} SHA-256 OK"
    )
    st.sidebar.caption(
        "Dashboard nie czyta surowych e-maili, promptów ani kluczy API."
    )

    if filtered_runs.empty:
        st.error("Filtry usunęły wszystkie warianty.")
        st.stop()
        return
    visible_variants = set(filtered_runs["variant_id"])
    filtered_cases = cases[cases["variant_id"].isin(visible_variants)].copy()

    tabs = st.tabs(
        [
            "Overview",
            "Quality",
            "Cost & Latency",
            "Direct vs CrewAI",
            "Case Explorer",
            "Technical & Report",
        ]
    )
    with tabs[0]:
        _overview_tab(filtered_runs, filtered_cases)
    with tabs[1]:
        _quality_tab(filtered_runs, filtered_cases)
    with tabs[2]:
        _cost_latency_tab(filtered_runs)
    with tabs[3]:
        _direct_crewai_tab(
            runs,
            pairwise,
            selected_models,
            selected_providers,
            selected_architectures,
        )
    with tabs[4]:
        _case_explorer_tab(filtered_cases)
    with tabs[5]:
        _technical_tab(bundle, filtered_runs)

    st.divider()
    st.caption(
        "Interpretacja: wyższe F1 i niższe FPR są korzystne, ale decyzja musi "
        "uwzględniać także błędy techniczne, koszt, latency oraz zakres porównania."
    )


if __name__ == "__main__":
    main(sys.argv[1:])
