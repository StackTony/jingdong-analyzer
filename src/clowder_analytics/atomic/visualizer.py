"""F002 P1: Visualizer 原子 op（spec §4.4）

按 ChartSpec 渲染图表，4 类：bar / line / scatter / heatmap。
plotly 渲染，未装时抛 NotImplementedError。

mode:
    - "static": 输出 Figure（调用方决定怎么展示）
    - "interactive": 输出 Figure（Streamlit 用 st.plotly_chart 渲染）

G2 大数据量优化：render(max_rows=N) 采样到前 N 行喂 plotly，
避免 33 万行 bar chart 全量序列化 JSON 卡浏览器。
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from clowder_analytics.atomic.spec import ChartSpec


def render(chart_spec: ChartSpec, mode: str = "static", max_rows: int | None = None) -> Any:
    """按 ChartSpec 渲染 plotly Figure

    Args:
        chart_spec: ChartSpec 数据类
        mode: "static"（默认）| "interactive"——MVP 两者都返回 Figure，
              渲染策略由调用方决定（CLI 出 PNG，Streamlit 出交互组件）
        max_rows: 大数据采样上限，None 时全量传（向后兼容）；
                  传 N 时只用 chart_spec.data.head(N) 喂 plotly，
                  避免 33 万行 DataFrame 全量序列化卡浏览器。
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
    # G2: 大数据采样（heatmap 是矩阵，不采样行）
    if max_rows is not None and t != "heatmap":
        df = df.head(max_rows)

    # G17 根因B：ChartSpec.y 可能是 list（model.aggregate 恒产出
    # y=list(agg.keys())，哪怕单指标）。旧代码 go.Bar(y=df[list]) 让 plotly
    # 收到 2D 嵌套数组 → 空图/畸形图，多指标也只画一个错 trace（「维度少」）。
    # 修法：bar/line 逐列展开——单列 y → 1 trace，多列 y → N trace（每列命名）。
    if t == "bar":
        traces = [
            go.Bar(x=df[chart_spec.x], y=df[col], name=col)
            for col in _y_cols(chart_spec.y)
        ]
        fig = go.Figure(traces)
        fig.update_layout(title=chart_spec.title)
        return fig

    if t == "line":
        traces = [
            go.Scatter(x=df[chart_spec.x], y=df[col], mode="lines+markers", name=col)
            for col in _y_cols(chart_spec.y)
        ]
        fig = go.Figure(traces)
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


def _y_cols(y: str | list[str]) -> list[str]:
    """归一化 ChartSpec.y 为列名列表（G17：str → [str]，list → 原样）"""
    return [y] if isinstance(y, str) else list(y)
