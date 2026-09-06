"""Create publication-friendly static charts from a validated comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import seaborn as sns  # noqa: E402
from matplotlib.colors import ListedColormap  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

try:
    from .analytics import direct_crewai_comparisons
    from .data_loader import (
        ComparisonBundle,
        DashboardDataError,
        load_comparison_bundle,
        sha256_file,
    )
    from .frames import comparison_frames
except ImportError:  # This file is normally executed as a script.
    from analytics import direct_crewai_comparisons
    from data_loader import (
        ComparisonBundle,
        DashboardDataError,
        load_comparison_bundle,
        sha256_file,
    )
    from frames import comparison_frames


ARCHITECTURE_COLORS = {"Direct": "#2563eb", "CrewAI": "#f97316"}
OUTCOME_CODES = {"TN": 0, "TP": 1, "FP": 2, "FN": 3, "TECH": 4, "OTHER": 5}
OUTCOME_COLORS = ["#16a34a", "#0891b2", "#f59e0b", "#dc2626", "#7c3aed", "#64748b"]


def _all_positive(values: pd.Series) -> bool:
    measured = values.dropna()
    return not measured.empty and bool(measured.gt(0).all())


def _comparison_footer(bundle: ComparisonBundle, runs: pd.DataFrame) -> str:
    metadata = bundle.metadata
    compatibility = metadata.get("compatibility", {})
    frozen = compatibility.get("frozen_invariants", {})
    stage = frozen.get("stage", "unknown stage")
    sample_counts = sorted(runs["sample_count"].dropna().astype(int).unique())
    sample_text = "/".join(str(value) for value in sample_counts) or "N/A"
    statuses = "/".join(sorted(runs["campaign_status"].dropna().unique()))
    conclusion = metadata.get("comparative_conclusion", "UNKNOWN")
    comparison_status = metadata.get("comparison_status", "UNKNOWN")
    return (
        f"{stage} · n={sample_text}/variant · {statuses} · "
        f"{comparison_status}/{conclusion}"
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Eksportuj PNG, SVG i XLSX bez requestów do modeli."
    )
    parser.add_argument("--comparison-dir", required=True, type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Domyślnie: <comparison-dir>/charts. Katalog musi być pusty lub nowy.",
    )
    return parser.parse_args(argv)


def _prepare_output(path: Path) -> Path:
    output = path.expanduser().resolve()
    if output.exists():
        if not output.is_dir():
            raise ValueError(f"Output nie jest katalogiem: {output}")
        if any(output.iterdir()):
            raise ValueError(
                f"Output nie jest pusty: {output}. Użyj nowej nazwy, np. charts_v2."
            )
    else:
        output.mkdir(mode=0o700, parents=True)
    output.chmod(0o700)
    return output


def _annotate_footer(figure: plt.Figure, footer: str) -> None:
    figure.text(0.01, 0.01, footer, fontsize=8, color="#475569")


def _save_figure(
    figure: plt.Figure, output: Path, stem: str, footer: str
) -> list[Path]:
    _annotate_footer(figure, footer)
    figure.tight_layout(rect=(0, 0.08, 1, 1))
    paths: list[Path] = []
    for suffix in ("png", "svg"):
        path = output / f"{stem}.{suffix}"
        figure.savefig(path, dpi=180 if suffix == "png" else None, bbox_inches="tight")
        path.chmod(0o600)
        paths.append(path)
    plt.close(figure)
    return paths


def _bar_figure(
    runs: pd.DataFrame,
    column: str,
    title: str,
    xlabel: str,
    formatter: Callable[[float], str],
    *,
    xlim: tuple[float, float] | None = None,
    log_scale: bool = False,
) -> plt.Figure:
    data = runs.sort_values(column, ascending=True)
    figure, axis = plt.subplots(figsize=(11, max(4.8, 0.58 * len(data))))
    colors = [ARCHITECTURE_COLORS[value] for value in data["architecture_label"]]
    bars = axis.barh(data["variant_label"], data[column], color=colors)
    for bar, failures in zip(bars, data["technical_failures"], strict=True):
        if failures > 0:
            bar.set_edgecolor("#dc2626")
            bar.set_linewidth(3)
    failed = data[data["technical_failures"] > 0]
    if not failed.empty:
        axis.scatter(
            failed[column],
            failed["variant_label"],
            marker="x",
            s=90,
            linewidths=2.5,
            color="#dc2626",
            zorder=5,
        )
    axis.set_title(title, loc="left", fontweight="bold")
    active_log_scale = log_scale and _all_positive(data[column])
    scale_suffix = " - log scale" if active_log_scale else ""
    axis.set_xlabel(xlabel + scale_suffix)
    axis.set_ylabel("")
    if xlim:
        axis.set_xlim(*xlim)
    if active_log_scale:
        axis.set_xscale("log")
    axis.grid(axis="x", alpha=0.2)
    for bar, value in zip(bars, data[column], strict=True):
        axis.text(
            bar.get_width(),
            bar.get_y() + bar.get_height() / 2,
            f"  {formatter(float(value))}",
            va="center",
            fontsize=9,
        )
    axis.legend(
        handles=[
            Patch(color=color, label=label)
            for label, color in ARCHITECTURE_COLORS.items()
        ],
        frameon=False,
        loc="lower right",
    )
    if (data["technical_failures"] > 0).any():
        axis.text(
            0.99,
            0.02,
            "czerwony obrys/X = błąd techniczny",
            transform=axis.transAxes,
            ha="right",
            fontsize=8,
            color="#dc2626",
        )
    return figure


def _cost_quality_figure(runs: pd.DataFrame) -> plt.Figure:
    figure, axis = plt.subplots(figsize=(11, 7))
    for architecture, group in runs.groupby("architecture_label", sort=False):
        axis.scatter(
            group["observed_cost_usd_per_message"],
            group["f1"],
            s=100,
            color=ARCHITECTURE_COLORS[architecture],
            label=architecture,
            edgecolors=[
                "#dc2626" if failures > 0 else "#0f172a"
                for failures in group["technical_failures"]
            ],
            linewidths=[3 if failures > 0 else 1 for failures in group["technical_failures"]],
        )
        for _, row in group.iterrows():
            axis.annotate(
                row["model_label"],
                (row["observed_cost_usd_per_message"], row["f1"]),
                xytext=(6, 7),
                textcoords="offset points",
                fontsize=8,
            )
    use_log_scale = _all_positive(runs["observed_cost_usd_per_message"])
    if use_log_scale:
        axis.set_xscale("log")
    axis.set_ylim(0, 1.05)
    axis.set_xlabel(
        "Observed cost / message [USD]"
        + (" - log scale" if use_log_scale else "")
    )
    axis.set_ylabel("F1")
    axis.set_title("Koszt a jakość - wynik opisowy", loc="left", fontweight="bold")
    axis.grid(alpha=0.2)
    axis.legend(frameon=False)
    axis.text(
        0.99,
        0.02,
        "czerwony obrys = błąd techniczny",
        transform=axis.transAxes,
        ha="right",
        fontsize=8,
        color="#dc2626",
    )
    return figure


def _case_heatmap_figure(cases: pd.DataFrame) -> plt.Figure:
    data = cases.copy()

    def outcome(row: pd.Series) -> str:
        technical = row["technical_failure"]
        if pd.notna(technical) and bool(technical):
            return "TECH"
        return str(row["confusion_cell"]).upper()

    data["outcome"] = data.apply(
        outcome,
        axis=1,
    )
    order = (
        data[["case_name", "class_label", "difficulty"]]
        .drop_duplicates()
        .sort_values(["class_label", "difficulty", "case_name"])["case_name"]
        .tolist()
    )
    variant_order = data["variant_label"].drop_duplicates().tolist()
    text = data.pivot(
        index="variant_label", columns="case_name", values="outcome"
    ).reindex(index=variant_order, columns=order)
    codes = text.map(lambda value: OUTCOME_CODES.get(str(value), OUTCOME_CODES["OTHER"]))
    figure, axis = plt.subplots(figsize=(20, max(5.5, 0.65 * len(variant_order))))
    sns.heatmap(
        codes,
        cmap=ListedColormap(OUTCOME_COLORS),
        vmin=-0.5,
        vmax=len(OUTCOME_COLORS) - 0.5,
        annot=text,
        fmt="",
        linewidths=0.5,
        linecolor="white",
        cbar=False,
        ax=axis,
        annot_kws={"fontsize": 7},
    )
    axis.set_title("Wynik wariant × przypadek", loc="left", fontweight="bold")
    axis.set_xlabel("Przypadek")
    axis.set_ylabel("")
    axis.tick_params(axis="x", rotation=55, labelsize=8)
    axis.legend(
        handles=[
            Patch(color=OUTCOME_COLORS[index], label=label)
            for label, index in OUTCOME_CODES.items()
        ],
        ncol=6,
        frameon=False,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.32),
    )
    return figure


def _direct_crewai_figure(pairs: pd.DataFrame) -> plt.Figure:
    figure, axes = plt.subplots(2, 2, figsize=(13, 9))
    definitions = (
        ("delta_f1", "ΔF1 CrewAI − Direct", 0.0, False, True),
        ("delta_fpr", "ΔFPR CrewAI − Direct", 0.0, False, False),
        ("cost_ratio", "Koszt CrewAI / Direct", 1.0, True, False),
        ("latency_ratio", "Latency CrewAI / Direct", 1.0, True, False),
    )
    for axis, (column, title, reference, ratio, higher_is_better) in zip(
        axes.flat, definitions, strict=True
    ):
        values = pairs[column]
        colors = [
            "#16a34a"
            if (value > reference if higher_is_better else value < reference)
            else "#f97316"
            for value in values
        ]
        bars = axis.bar(pairs["model"], values, color=colors)
        axis.axhline(reference, color="#475569", linestyle="--", linewidth=1)
        axis.set_title(title, loc="left", fontsize=11, fontweight="bold")
        axis.tick_params(axis="x", rotation=20, labelsize=8)
        axis.grid(axis="y", alpha=0.2)
        for bar, value in zip(bars, values, strict=True):
            label = f"{value:.2f}×" if ratio else f"{value:+.3f}"
            axis.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height(),
                label,
                ha="center",
                va="bottom" if value >= reference else "top",
                fontsize=8,
            )
    figure.suptitle(
        "Direct → CrewAI: pełne system bundles, nie izolowany efekt frameworka",
        x=0.01,
        ha="left",
        fontweight="bold",
    )
    scope_labels = {
        "system_bundle_delta": "system bundle",
        "cross_api_system_bundle_delta": "cross-API system bundle",
        "token_cap_adjusted_system_bundle_delta": "token-cap-adjusted bundle",
    }
    notes = [
        f"{row['model']}: {scope_labels.get(row['scope'], row['scope'])}"
        for _, row in pairs.iterrows()
    ]
    midpoint = (len(notes) + 1) // 2
    scope_note = "Zakres: " + "; ".join(notes[:midpoint])
    if notes[midpoint:]:
        scope_note += "\n" + "; ".join(notes[midpoint:])
    figure.text(0.01, 0.035, scope_note, fontsize=8, color="#334155")
    return figure


def _write_workbook(
    output: Path,
    runs: pd.DataFrame,
    cases: pd.DataFrame,
    pairwise: pd.DataFrame,
    pairs: pd.DataFrame,
    metadata: dict,
) -> Path:
    def excel_safe(frame: pd.DataFrame) -> pd.DataFrame:
        safe = frame.copy()
        for column in safe.select_dtypes(include=["object", "string"]).columns:
            safe[column] = safe[column].map(
                lambda value: (
                    "'" + value
                    if isinstance(value, str)
                    and value.lstrip().startswith(("=", "+", "-", "@"))
                    else value
                )
            )
        return safe

    path = output / "summary.xlsx"
    methodology = pd.DataFrame(
        [
            ("comparison_status", metadata.get("comparison_status")),
            ("comparative_conclusion", metadata.get("comparative_conclusion")),
            ("eligible_for_ranking", metadata.get("eligible_for_ranking")),
            ("generated_at", metadata.get("generated_at")),
            ("disclaimer", metadata.get("disclaimer")),
        ],
        columns=["field", "value"],
    )
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        excel_safe(runs).to_excel(writer, sheet_name="Runs", index=False)
        excel_safe(cases).to_excel(writer, sheet_name="Cases", index=False)
        excel_safe(pairwise).to_excel(writer, sheet_name="Pairwise", index=False)
        excel_safe(pairs).to_excel(
            writer, sheet_name="Direct_vs_CrewAI", index=False
        )
        excel_safe(methodology).to_excel(
            writer, sheet_name="Methodology", index=False
        )
    path.chmod(0o600)
    return path


def _write_manifest(
    output: Path,
    source_dir: Path,
    source_hashes: dict,
    artifacts: list[Path],
    metadata: dict,
) -> Path:
    manifest_path = output / "charts_manifest.json"
    payload = {
        "record_type": "BenchmarkChartExport",
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_comparison_id": source_dir.name,
        "source_export_artifacts": source_hashes,
        "interpretation": (
            f"{metadata.get('comparison_status', 'UNKNOWN')} / "
            f"{metadata.get('comparative_conclusion', 'UNKNOWN')}"
        ),
        "artifacts": {
            path.name: {"sha256": sha256_file(path), "size_bytes": path.stat().st_size}
            for path in sorted(artifacts)
        },
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(manifest_path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return manifest_path


def export_static(comparison_dir: Path, output_dir: Path | None = None) -> Path:
    bundle = load_comparison_bundle(comparison_dir)
    output = _prepare_output(output_dir or bundle.directory / "charts")
    runs, cases, pairwise = comparison_frames(bundle)
    pair_columns = (
        "requested_model",
        "model",
        "direct_variant",
        "crewai_variant",
        "direct_f1",
        "crewai_f1",
        "delta_f1",
        "direct_fpr",
        "crewai_fpr",
        "delta_fpr",
        "cost_ratio",
        "latency_ratio",
        "exact_action_agreement_rate",
        "binary_prediction_agreement_rate",
        "scope",
    )
    pair_rows = direct_crewai_comparisons(
        runs.to_dict("records"), pairwise.to_dict("records")
    )
    pairs = pd.DataFrame(pair_rows, columns=pair_columns)
    sns.set_theme(style="whitegrid", context="notebook")
    footer = _comparison_footer(bundle, runs)

    artifacts: list[Path] = []
    artifacts += _save_figure(
        _bar_figure(
            runs,
            "f1",
            "F1 według wariantu",
            "F1 - więcej jest lepiej",
            lambda value: f"{value:.3f}",
            xlim=(0, 1.08),
        ),
        output,
        "01_f1",
        footer,
    )
    artifacts += _save_figure(
        _bar_figure(
            runs,
            "false_positive_rate",
            "False Positive Rate według wariantu",
            "FPR - mniej jest lepiej",
            lambda value: f"{value:.1%}",
            xlim=(0, 1.08),
        ),
        output,
        "02_fpr",
        footer,
    )
    artifacts += _save_figure(
        _bar_figure(
            runs,
            "observed_cost_usd_per_message",
            "Observed cost na wiadomość",
            "USD / message",
            lambda value: f"${value:.6f}",
            log_scale=True,
        ),
        output,
        "03_cost_per_message",
        footer,
    )
    artifacts += _save_figure(
        _bar_figure(
            runs.assign(latency_seconds=runs["latency_median_ms"] / 1000),
            "latency_seconds",
            "Mediana end-to-end latency",
            "Sekundy - mniej jest lepiej",
            lambda value: f"{value:.2f} s",
        ),
        output,
        "04_latency_median",
        footer,
    )
    artifacts += _save_figure(
        _cost_quality_figure(runs), output, "05_cost_quality_pareto", footer
    )
    artifacts += _save_figure(
        _case_heatmap_figure(cases), output, "06_case_heatmap", footer
    )
    if not pairs.empty:
        artifacts += _save_figure(
            _direct_crewai_figure(pairs),
            output,
            "07_direct_vs_crewai",
            footer,
        )
    workbook = _write_workbook(
        output, runs, cases, pairwise, pairs, bundle.metadata
    )
    artifacts.append(workbook)
    _write_manifest(
        output,
        bundle.directory,
        dict(bundle.metadata["export_artifacts"]),
        artifacts,
        bundle.metadata,
    )
    return output


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        output = export_static(args.comparison_dir, args.output_dir)
    except (DashboardDataError, OSError, ValueError) as exc:
        print(f"BŁĄD: {exc}", file=sys.stderr)
        return 2
    print(f"Wykresy i workbook: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
