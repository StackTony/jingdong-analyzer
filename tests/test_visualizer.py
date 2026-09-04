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
    # B 方案：ChartSpec.data 是 DataFrame，不是 dict list
    df = pd.DataFrame({"brand": ["a", "b"], "sales": [10, 20]})
    spec = ChartSpec(type="bar", data=df, x="brand", y="sales")
    fig = render(spec, mode="static")
    assert fig is not None
    assert hasattr(fig, "data")


def test_render_line():
    if not _plotly_available():
        pytest.skip("plotly 未装")
    # B 方案：data 是 DataFrame
    df = pd.DataFrame({"month": ["2026-01", "2026-02"], "sales": [100, 80]})
    spec = ChartSpec(type="line", data=df, x="month", y="sales")
    fig = render(spec, mode="static")
    assert hasattr(fig, "data")


def test_render_scatter():
    if not _plotly_available():
        pytest.skip("plotly 未装")
    # B 方案：data 是 DataFrame
    df = pd.DataFrame({"x": [1, 2, 3], "y": [4, 5, 6]})
    spec = ChartSpec(type="scatter", data=df, x="x", y="y")
    fig = render(spec, mode="static")
    assert hasattr(fig, "data")


def test_render_heatmap():
    if not _plotly_available():
        pytest.skip("plotly 未装")
    # B 方案：data 是 DataFrame（correlation 矩阵）
    df = pd.DataFrame({"a": [1.0, 0.5], "b": [0.5, 1.0]})
    spec = ChartSpec(type="heatmap", data=df, x=["a", "b"], y=["a", "b"])
    fig = render(spec, mode="static")
    assert hasattr(fig, "data")


def test_render_unknown_type_raises():
    """未知 chart type 应抛 ValueError"""
    if not _plotly_available():
        pytest.skip("plotly 未装")
    # B 方案：data 必须是 DataFrame
    spec = ChartSpec(type="pie", data=pd.DataFrame(), x="", y="")
    with pytest.raises(ValueError):
        render(spec, mode="static")


# ===== G2: render(max_rows=...) 大数据采样 =====

def test_render_bar_with_max_rows_samples_data():
    """max_rows=N 时 render 只用前 N 行喂 plotly，避免浏览器卡死"""
    if not _plotly_available():
        pytest.skip("plotly 未装")
    # 模拟 1000 行大数据
    df = pd.DataFrame({"brand": [f"b{i}" for i in range(1000)], "sales": list(range(1000))})
    spec = ChartSpec(type="bar", data=df, x="brand", y="sales")
    # max_rows=50 → plotly 只收到 50 行
    fig = render(spec, mode="static", max_rows=50)
    assert len(fig.data[0].x) == 50
    assert len(fig.data[0].y) == 50


def test_render_line_with_max_rows_samples_data():
    if not _plotly_available():
        pytest.skip("plotly 未装")
    df = pd.DataFrame({"month": [f"2026-{i:02d}" for i in range(1, 13)] * 100, "sales": list(range(1200))})
    spec = ChartSpec(type="line", data=df, x="month", y="sales")
    fig = render(spec, mode="static", max_rows=100)
    assert len(fig.data[0].x) == 100


def test_render_no_max_rows_passes_full_data():
    """不传 max_rows 时全量传（向后兼容）"""
    if not _plotly_available():
        pytest.skip("plotly 未装")
    df = pd.DataFrame({"brand": ["a", "b", "c"], "sales": [1, 2, 3]})
    spec = ChartSpec(type="bar", data=df, x="brand", y="sales")
    fig = render(spec, mode="static")
    assert len(fig.data[0].x) == 3


# ===== G17 根因B：y 为 list（aggregate 单/多指标）→ 空图/错图修复 =====
#
# 现象：model.aggregate 产出 ChartSpec.y = list(agg.keys())（永远 list，哪怕单指标）。
# 旧 visualizer 直接 go.Bar(y=df[chart_spec.y])，df[列表] 返回 DataFrame，
# 喂给 plotly 得到 2D 嵌套（如 [[50],[20],[30]]）→ 渲染空图/畸形图。
# 多指标时更只画一个错 trace（铲屎官「图表维度少」）。
# 修法：y=list 时每列展开成独立一维 trace（单元素 list→1 trace，多元素→N trace）。


def test_render_bar_single_element_list_y_is_flat_1d():
    """y=['col']（aggregate 单指标）→ trace.y 必须是一维扁平，不是 2D 嵌套"""
    import numpy as np
    if not _plotly_available():
        pytest.skip("plotly 未装")
    df = pd.DataFrame({"shop": ["A", "B", "C"], "sales": [50, 20, 30]})
    spec = ChartSpec(type="bar", data=df, x="shop", y=["sales"])  # list 单元素
    fig = render(spec, mode="static")
    y = np.asarray(fig.data[0].y)
    assert y.ndim == 1, f"y 应为一维扁平，实际 ndim={y.ndim} shape={y.shape}"
    assert list(y) == [50, 20, 30]


def test_render_bar_multi_y_produces_one_trace_per_column():
    """y=['sales','gmv']（aggregate 多指标）→ 每个指标一个 trace（多系列）"""
    import numpy as np
    if not _plotly_available():
        pytest.skip("plotly 未装")
    df = pd.DataFrame({
        "shop": ["A", "B", "C"],
        "sales": [50, 20, 30],
        "gmv": [500, 200, 300],
    })
    spec = ChartSpec(type="bar", data=df, x="shop", y=["sales", "gmv"])
    fig = render(spec, mode="static")
    assert len(fig.data) == 2, f"多指标应产出 2 个 trace，实际 {len(fig.data)}"
    # 每个 trace 的 y 都是一维，且值正确
    assert list(np.asarray(fig.data[0].y)) == [50, 20, 30]
    assert list(np.asarray(fig.data[1].y)) == [500, 200, 300]
    # trace 命名区分（图例可读）
    assert {fig.data[0].name, fig.data[1].name} == {"sales", "gmv"}


def test_render_line_multi_y_produces_traces():
    """line 图同样支持 y=list 多系列（trend 未来多列场景 / 保持契约一致）"""
    import numpy as np
    if not _plotly_available():
        pytest.skip("plotly 未装")
    df = pd.DataFrame({
        "month": ["2026-01", "2026-02", "2026-03"],
        "sales": [10, 20, 30],
        "orders": [1, 2, 3],
    })
    spec = ChartSpec(type="line", data=df, x="month", y=["sales", "orders"])
    fig = render(spec, mode="static")
    assert len(fig.data) == 2
    assert list(np.asarray(fig.data[0].y)) == [10, 20, 30]


def test_render_bar_multi_y_respects_max_rows():
    """多指标 + max_rows 采样：每个 trace 都只喂前 N 行"""
    import numpy as np
    if not _plotly_available():
        pytest.skip("plotly 未装")
    df = pd.DataFrame({
        "brand": [f"b{i}" for i in range(100)],
        "sales": list(range(100)),
        "gmv": list(range(100, 200)),
    })
    spec = ChartSpec(type="bar", data=df, x="brand", y=["sales", "gmv"])
    fig = render(spec, mode="static", max_rows=10)
    assert len(fig.data) == 2
    assert len(fig.data[0].x) == 10
    assert len(np.asarray(fig.data[0].y)) == 10
    assert len(np.asarray(fig.data[1].y)) == 10
