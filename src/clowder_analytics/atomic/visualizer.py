"""F002 P1: Visualizer 原子 op（spec §4.4）

按 ChartSpec 渲染图表，4 类：bar / line / scatter / heatmap。
plotly 渲染，未装时抛 NotImplementedError。

mode:
    - "static": 输出 Figure（调用方决定怎么展示）
    - "interactive": 输出 Figure（Streamlit 用 st.plotly_chart 渲染）
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from clowder_analytics.atomic.spec import ChartSpec


def render(chart_spec: ChartSpec, mode: str = "static") -> Any:
    """按 ChartSpec 渲染 plotly Figure

    Args:
        chart_spec: ChartSpec 数据类
        mode: "static"（默认）| "interactive"——MVP 两者都返回 Figure，
              渲染策略由调用方决定（CLI 出 PNG，Streamlit 出交互组件）
    """
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError as e:
        raise NotImplementedError(
            "Visualizer 需要 plotly：pip install plotly"
        ) from e

    t = chart_spec.type
    # B 方案：ChartSpec.data 已是 DataFrame，直接用
    df = chart_spec.data

    if t == "bar":
        fig = go.Figure([go.Bar(x=df[chart_spec.x], y=df[chart_spec.y])])
        fig.update_layout(title=chart_spec.title)
        return fig

    if t == "line":
        fig = go.Figure([go.Scatter(x=df[chart_spec.x], y=df[chart_spec.y], mode="lines+markers")])
        fig.update_layout(title=chart_spec.title)
        return fig

    if t == "scatter":
        fig = go.Figure([go.Scatter(x=df[chart_spec.x], y=df[chart_spec.y], mode="markers")])
        fig.update_layout(title=chart_spec.title)
        return fig

    if t == "heatmap":
        # correlation 返回的 DataFrame 索引和列都是 columns 列表
        fig = go.Figure(data=go.Heatmap(
            z=df.values,
            x=list(df.columns),
            y=list(df.index),
        ))
        fig.update_layout(title=chart_spec.title)
        return fig

    raise ValueError(f"未知 chart type: {t}")
