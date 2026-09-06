"""Interactive Plotly charts for the local Streamlit dashboard."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


ARCHITECTURE_COLORS = {"Direct": "#2563eb", "CrewAI": "#f97316"}
PROVIDER_COLORS = {"openai": "#10b981", "google": "#8b5cf6"}
CONFUSION_COLORS = {
    "TN": "#16a34a",
    "TP": "#0891b2",
    "FP": "#f59e0b",
    "FN": "#dc2626",
    "TECH": "#7c3aed",
    "OTHER": "#64748b",
}


def _all_positive(values: pd.Series) -> bool:
    measured = values.dropna()
    return not measured.empty and bool(measured.gt(0).all())


def _finish(
    figure: go.Figure,
    *,
    height: int = 430,
    percent_axis: bool = False,
    horizontal_legend: bool = False,
    hide_y_title: bool = False,
    hide_y_grid: bool = False,
) -> go.Figure:
    layout: dict[str, Any] = {
        "height": height,
        "margin": dict(l=20, r=85 if horizontal_legend else 30, t=95, b=45),
        "legend_title_text": "",
        "title": dict(x=0.01, xanchor="left"),
        "hoverlabel": dict(namelength=-1),
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
    }
    if horizontal_legend:
        layout["legend"] = dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            bgcolor="rgba(0,0,0,0)",
        )
    figure.update_layout(**layout)
    figure.update_xaxes(
        showgrid=True,
        gridcolor="rgba(148,163,184,0.20)",
        automargin=True,
    )
    figure.update_yaxes(automargin=True)
    if hide_y_title:
        figure.update_yaxes(title_text=None)
    if hide_y_grid:
        figure.update_yaxes(showgrid=False)
    if percent_axis:
        figure.update_xaxes(tickformat=".1%")
    return figure


def _add_technical_status(
    figure: go.Figure,
    failed: pd.DataFrame,
) -> None:
    """Add a fixed status rail without changing the data-axis scale."""
    if failed.empty:
        return
    for row in failed.itertuples(index=False):
        failures = int(getattr(row, "technical_failures"))
        label = str(getattr(row, "variant_label"))
        figure.add_annotation(
            xref="paper",
            x=1.035,
            yref="y",
            y=label,
            text="&#10005;",
            showarrow=False,
            font=dict(size=22, color="#dc2626"),
            hovertext=f"{label}<br>błędy techniczne: {failures}",
            captureevents=True,
        )
    figure.add_trace(
        go.Scatter(
            x=[None],
            y=[None],
            mode="markers",
            marker=dict(symbol="x", size=12, color="#dc2626", line_width=3),
            name="błąd techniczny",
            hoverinfo="skip",
        )
    )


def metric_bar(
    runs: pd.DataFrame,
    metric: str,
    title: str,
    *,
    percent: bool = False,
    currency: bool = False,
) -> go.Figure:
    data = runs.copy().sort_values(metric, ascending=True)
    text_format = ".2%" if percent else ("$.6f" if currency else ".3f")
    hover_value = (
        "%{x:.2%}"
        if percent
        else ("$%{x:.6f}" if currency else "%{x:.4f}")
    )
    figure = px.bar(
        data,
        x=metric,
        y="variant_label",
        color="architecture_label",
        color_discrete_map=ARCHITECTURE_COLORS,
        orientation="h",
        text=metric,
        title=title,
        labels={metric: "", "variant_label": "", "architecture_label": ""},
        custom_data=[
            "variant_id",
            "campaign_status",
            "success_count",
            "technical_failures",
        ],
    )
    figure.update_traces(
        texttemplate=f"%{{x:{text_format}}}",
        textposition="outside",
        cliponaxis=False,
        hovertemplate=(
            f"%{{y}}<br>wartość={hover_value}<br>variant=%{{customdata[0]}}"
            "<br>status=%{customdata[1]}<br>success=%{customdata[2]}"
            "<br>technical failures=%{customdata[3]}<extra></extra>"
        ),
    )
    failed = data[data["technical_failures"] > 0]
    _add_technical_status(figure, failed)
    if percent:
        measured = data[metric].dropna()
        maximum = float(measured.max()) if not measured.empty else 0.0
        figure.update_xaxes(range=[0, max(0.05, maximum * 1.1)])
    if currency:
        positive_values = _all_positive(data[metric])
        figure.update_xaxes(
            tickprefix="$", type="log" if positive_values else "linear"
        )
    return _finish(
        figure,
        height=max(500, 55 * len(data)),
        percent_axis=percent,
        horizontal_legend=True,
        hide_y_title=True,
        hide_y_grid=True,
    )


def confusion_bars(runs: pd.DataFrame) -> go.Figure:
    melted = runs.melt(
        id_vars=["variant_label"],
        value_vars=["tp", "fp", "tn", "fn"],
        var_name="cell",
        value_name="count",
    )
    melted["cell"] = melted["cell"].str.upper()
    figure = px.bar(
        melted,
        x="count",
        y="variant_label",
        color="cell",
        color_discrete_map=CONFUSION_COLORS,
        category_orders={"cell": ["TP", "TN", "FP", "FN"]},
        orientation="h",
        title="Macierz pomyłek - liczby TP/TN/FP/FN",
        labels={"count": "Liczba próbek", "variant_label": "", "cell": ""},
    )
    figure.update_layout(barmode="stack")
    return _finish(
        figure,
        height=max(500, 55 * len(runs)),
        horizontal_legend=True,
        hide_y_title=True,
        hide_y_grid=True,
    )


def cost_quality_scatter(runs: pd.DataFrame) -> go.Figure:
    data = runs.copy()
    data["technical_marker"] = data["technical_failures"].map(
        lambda value: "Błąd techniczny" if value > 0 else "Technicznie kompletne"
    )
    figure = px.scatter(
        data,
        x="observed_cost_usd_per_message",
        y="f1",
        color="provider",
        symbol="architecture_label",
        color_discrete_map=PROVIDER_COLORS,
        text="model_label",
        title="Koszt a jakość - wynik opisowy",
        labels={
            "observed_cost_usd_per_message": "Koszt / wiadomość [USD]",
            "f1": "F1",
            "provider": "Provider",
            "architecture_label": "Architektura",
        },
        custom_data=[
            "variant_id",
            "false_positive_rate",
            "latency_median_ms",
            "technical_failures",
            "campaign_status",
        ],
    )
    figure.update_traces(
        marker=dict(size=14, line=dict(width=1, color="#0f172a")),
        textposition="top center",
        hovertemplate=(
            "%{text}<br>cost/message=$%{x:.6f}<br>F1=%{y:.4f}"
            "<br>FPR=%{customdata[1]:.2%}<br>latency=%{customdata[2]:.1f} ms"
            "<br>technical failures=%{customdata[3]}"
            "<br>status=%{customdata[4]}<extra></extra>"
        ),
    )
    failed = data[data["technical_failures"] > 0]
    if not failed.empty:
        figure.add_trace(
            go.Scatter(
                x=failed["observed_cost_usd_per_message"],
                y=failed["f1"],
                mode="markers",
                marker=dict(
                    size=24,
                    symbol="circle-open",
                    color="#dc2626",
                    line=dict(width=3, color="#dc2626"),
                ),
                name="ma błąd techniczny",
                hoverinfo="skip",
            )
        )
    cost_is_positive = _all_positive(data["observed_cost_usd_per_message"])
    figure.update_xaxes(
        type="log" if cost_is_positive else "linear", tickprefix="$"
    )
    figure.update_yaxes(tickformat=".1%", range=[0, 1.05], showgrid=True)
    return _finish(figure, height=520)


def latency_bar(runs: pd.DataFrame) -> go.Figure:
    data = runs.copy().sort_values("latency_median_ms", ascending=True)
    figure = px.bar(
        data,
        x="latency_median_ms",
        y="variant_label",
        color="architecture_label",
        color_discrete_map=ARCHITECTURE_COLORS,
        orientation="h",
        text="latency_median_ms",
        title="Mediana end-to-end latency",
        labels={"latency_median_ms": "", "variant_label": ""},
        custom_data=["latency_iqr_ms", "latency_min_ms", "latency_max_ms"],
    )
    figure.update_traces(
        texttemplate="%{x:.0f} ms",
        textposition="outside",
        cliponaxis=False,
        hovertemplate=(
            "%{y}<br>mediana=%{x:.1f} ms<br>IQR=%{customdata[0]:.1f} ms"
            "<br>min=%{customdata[1]:.1f} ms<br>max=%{customdata[2]:.1f} ms"
            "<extra></extra>"
        ),
    )
    failed = data[data["technical_failures"] > 0]
    _add_technical_status(figure, failed)
    return _finish(
        figure,
        height=max(500, 55 * len(data)),
        horizontal_legend=True,
        hide_y_title=True,
        hide_y_grid=True,
    )


def cost_latency_scatter(runs: pd.DataFrame) -> go.Figure:
    figure = px.scatter(
        runs,
        x="observed_cost_usd_per_message",
        y="latency_median_ms",
        color="provider",
        symbol="architecture_label",
        color_discrete_map=PROVIDER_COLORS,
        text="model_label",
        title="Koszt a mediana latency",
        labels={
            "observed_cost_usd_per_message": "Koszt / wiadomość [USD]",
            "latency_median_ms": "Mediana latency [ms]",
            "provider": "Provider",
            "architecture_label": "Architektura",
        },
        hover_data=["variant_id", "f1", "false_positive_rate"],
    )
    figure.update_traces(marker=dict(size=14), textposition="top center")
    cost_is_positive = _all_positive(runs["observed_cost_usd_per_message"])
    latency_is_positive = _all_positive(runs["latency_median_ms"])
    figure.update_xaxes(
        type="log" if cost_is_positive else "linear", tickprefix="$"
    )
    figure.update_yaxes(
        type="log" if latency_is_positive else "linear",
        ticksuffix=" ms",
        showgrid=True,
    )
    return _finish(figure, height=500)


def action_distribution(cases: pd.DataFrame, *, benign_only: bool = False) -> go.Figure:
    data = cases[cases["class_label"] == "benign"] if benign_only else cases
    counts = (
        data.groupby(["variant_label", "predicted_action"], dropna=False)
        .size()
        .reset_index(name="count")
    )
    figure = px.bar(
        counts,
        x="count",
        y="variant_label",
        color="predicted_action",
        color_discrete_map={"allow": "#16a34a", "warn": "#f59e0b", "hide": "#dc2626"},
        orientation="h",
        title=(
            "Akcje tylko dla benign"
            if benign_only
            else "Rozkład wszystkich akcji systemu"
        ),
        labels={
            "count": "Liczba próbek",
            "variant_label": "",
            "predicted_action": "Akcja",
        },
    )
    figure.update_layout(barmode="stack")
    return _finish(
        figure,
        height=max(500, 55 * counts["variant_label"].nunique()),
        horizontal_legend=True,
        hide_y_title=True,
        hide_y_grid=True,
    )


def direct_crewai_delta_chart(pairs: pd.DataFrame) -> go.Figure:
    melted = pairs.melt(
        id_vars=["model"],
        value_vars=["delta_f1", "delta_fpr"],
        var_name="metric",
        value_name="delta",
    )
    melted["metric"] = melted["metric"].map(
        {"delta_f1": "ΔF1", "delta_fpr": "ΔFPR"}
    )
    figure = px.bar(
        melted,
        x="model",
        y="delta",
        color="metric",
        barmode="group",
        color_discrete_map={"ΔF1": "#2563eb", "ΔFPR": "#f97316"},
        title="Zmiana CrewAI względem Direct",
        text="delta",
        labels={"model": "Model", "delta": "Zmiana", "metric": "Metryka"},
    )
    figure.add_hline(y=0, line_color="#475569", line_width=1)
    figure.update_traces(texttemplate="%{y:+.3f}", textposition="outside")
    figure.update_yaxes(tickformat="+.1%", showgrid=True)
    return _finish(figure, height=480)


def direct_crewai_ratio_chart(pairs: pd.DataFrame) -> go.Figure:
    melted = pairs.melt(
        id_vars=["model"],
        value_vars=["cost_ratio", "latency_ratio"],
        var_name="metric",
        value_name="ratio",
    )
    melted["metric"] = melted["metric"].map(
        {"cost_ratio": "Koszt ×", "latency_ratio": "Latency ×"}
    )
    figure = px.bar(
        melted,
        x="model",
        y="ratio",
        color="metric",
        barmode="group",
        title="Koszt i latency CrewAI względem Direct",
        text="ratio",
        labels={
            "model": "Model",
            "ratio": "Wielokrotność względem Direct",
            "metric": "Metryka",
        },
    )
    figure.add_hline(y=1, line_dash="dash", line_color="#475569")
    figure.update_traces(texttemplate="%{y:.2f}×", textposition="outside")
    figure.update_yaxes(ticksuffix="×", showgrid=True)
    return _finish(figure, height=480)


def case_heatmap(cases: pd.DataFrame) -> go.Figure:
    outcomes = cases.copy()

    def outcome(row: pd.Series) -> str:
        technical = row.get("technical_failure")
        if pd.notna(technical) and bool(technical):
            return "TECH"
        return str(row.get("confusion_cell") or "OTHER").upper()

    outcomes["outcome"] = outcomes.apply(
        outcome,
        axis=1,
    )
    order = (
        outcomes[["case_name", "class_label", "difficulty"]]
        .drop_duplicates()
        .sort_values(["class_label", "difficulty", "case_name"])["case_name"]
        .tolist()
    )
    variant_order = outcomes["variant_label"].drop_duplicates().tolist()
    code = {"TN": 0, "TP": 1, "FP": 2, "FN": 3, "TECH": 4, "OTHER": 5}
    pivot_text = outcomes.pivot(
        index="variant_label", columns="case_name", values="outcome"
    ).reindex(index=variant_order, columns=order)
    pivot_code = pivot_text.map(lambda value: code.get(str(value), 5))
    colors = [
        CONFUSION_COLORS["TN"],
        CONFUSION_COLORS["TP"],
        CONFUSION_COLORS["FP"],
        CONFUSION_COLORS["FN"],
        CONFUSION_COLORS["TECH"],
        CONFUSION_COLORS["OTHER"],
    ]
    colorscale: list[list[Any]] = []
    for index, color in enumerate(colors):
        low = max(0.0, (index - 0.49) / (len(colors) - 1))
        high = min(1.0, (index + 0.49) / (len(colors) - 1))
        colorscale.extend([[low, color], [high, color]])
    figure = go.Figure(
        data=go.Heatmap(
            z=pivot_code.values,
            x=pivot_code.columns,
            y=pivot_code.index,
            text=pivot_text.values,
            texttemplate="%{text}",
            hovertemplate="%{y}<br>%{x}: %{text}<extra></extra>",
            colorscale=colorscale,
            zmin=0,
            zmax=len(colors) - 1,
            showscale=False,
            xgap=1,
            ygap=1,
        )
    )
    figure.update_layout(title="Wynik każdego wariantu na każdej próbce")
    figure.update_xaxes(tickangle=-55)
    return _finish(figure, height=max(500, 55 * len(variant_order)))
