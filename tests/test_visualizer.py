"""F002 P1: Visualizer 原子 op 红测（spec §4.4）

4 类图表：bar / line / scatter / heatmap
按 ChartSpec 渲染。plotly 未装时跳过。
"""
from __future__ import annotations

import pandas as pd
import pytest

from clowder_analytics.atomic.spec import ChartSpec
from clowder_analytics.atomic.visualizer import render


def _plotly_available() -> bool:
    try:
        import plotly  # noqa
        return True
    except ImportError:
        return False


def test_render_bar():
    """bar chart 渲染返回 Figure"""
    if not _plotly_available():
        pytest.skip("plotly 未装")
    df = pd.DataFrame({"brand": ["a", "b"], "sales": [10, 20]})
    spec = ChartSpec(type="bar", data=df.to_dict("records"), x="brand", y="sales")
    fig = render(spec, mode="static")
    assert fig is not None
    assert hasattr(fig, "data")


def test_render_line():
    if not _plotly_available():
        pytest.skip("plotly 未装")
    df = pd.DataFrame({"month": ["2026-01", "2026-02"], "sales": [100, 80]})
    spec = ChartSpec(type="line", data=df.to_dict("records"), x="month", y="sales")
    fig = render(spec, mode="static")
    assert hasattr(fig, "data")


def test_render_scatter():
    if not _plotly_available():
        pytest.skip("plotly 未装")
    df = pd.DataFrame({"x": [1, 2, 3], "y": [4, 5, 6]})
    spec = ChartSpec(type="scatter", data=df.to_dict("records"), x="x", y="y")
    fig = render(spec, mode="static")
    assert hasattr(fig, "data")


def test_render_heatmap():
    if not _plotly_available():
        pytest.skip("plotly 未装")
    df = pd.DataFrame({"a": [1.0], "b": [0.5]})
    spec = ChartSpec(type="heatmap", data=df.to_dict(), x=["a", "b"], y=["a", "b"])
    fig = render(spec, mode="static")
    assert hasattr(fig, "data")


def test_render_unknown_type_raises():
    """未知 chart type 应抛 ValueError"""
    if not _plotly_available():
        pytest.skip("plotly 未装")
    spec = ChartSpec(type="pie", data={}, x="", y="")
    with pytest.raises(ValueError):
        render(spec, mode="static")
