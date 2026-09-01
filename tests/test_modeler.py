"""F002 P1: Modeler 原子 op 红测（spec §4.3）

按 D10：先红测再实现。覆盖 6 个 Modeler op：
- aggregate: group_by + agg
- topn: TopN 排名
- trend: 时序聚合
- correlation: 相关性矩阵
- cluster: K-means 聚类
- anomaly_attribution: 异常归因

接口：f(df, **args) -> (df_or_result, chart_spec)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from clowder_analytics.atomic.modeler import (
    aggregate,
    anomaly_attribution,
    cluster,
    correlation,
    topn,
    trend,
)
from clowder_analytics.atomic.spec import ChartSpec


# ===== aggregate =====

def test_aggregate_basic():
    df = pd.DataFrame({
        "brand": ["a", "a", "b"],
        "sales": [10, 20, 30],
    })
    out, chart = aggregate(df, group_by=["brand"], agg={"sales": "sum"})
    assert len(out) == 2
    assert out.loc[out["brand"] == "a", "sales"].iloc[0] == 30
    assert isinstance(chart, ChartSpec)
    assert chart.type == "bar"


# ===== topn =====

def test_topn_value():
    df = pd.DataFrame({
        "brand": ["a", "b", "c", "d"],
        "sales": [10, 30, 20, 40],
    })
    out, chart = topn(df, group_by=["brand"], value_col="sales", n=2, rank_by="value")
    assert len(out) == 2
    assert out["sales"].tolist() == [40, 30]  # 降序
    assert chart.type == "bar"


def test_topn_volume():
    df = pd.DataFrame({
        "brand": ["a", "b"],
        "sales": [10, 30],
    })
    out, _ = topn(df, group_by=["brand"], value_col="sales", n=5, rank_by="value")
    assert len(out) == 2  # 不足 N 时返回全部


# ===== trend =====

def test_trend_monthly():
    df = pd.DataFrame({
        "month": ["2026-01", "2026-01", "2026-02"],
        "sales": [100, 50, 80],
    })
    df["month"] = pd.to_datetime(df["month"])
    out, chart = trend(df, time_col="month", value_col="sales", freq="M")
    assert len(out) == 2  # 两个月
    assert chart.type == "line"


# ===== correlation =====

def test_correlation_pearson():
    np.random.seed(0)
    df = pd.DataFrame({
        "a": np.random.normal(0, 1, 50),
        "b": np.random.normal(0, 1, 50),
    })
    out, chart = correlation(df, columns=["a", "b"], method="pearson")
    assert out.shape == (2, 2)
    assert chart.type == "heatmap"


# ===== cluster =====

def test_cluster_kmeans():
    try:
        import sklearn  # noqa
    except ImportError:
        pytest.skip("sklearn 未装，cluster 跳过")
    np.random.seed(42)
    df = pd.DataFrame({
        "x": [1.0, 1.1, 8.0, 8.1],
        "y": [1.0, 1.1, 8.0, 8.1],
    })
    out, chart = cluster(df, columns=["x", "y"], k=2, method="kmeans")
    assert "cluster" in out.columns
    assert set(out["cluster"]) == {0, 1}
    assert chart.type == "scatter"


def test_cluster_requires_sklearn_if_unavailable():
    """sklearn 未装时 cluster 应抛 NotImplementedError 不崩"""
    try:
        import sklearn  # noqa
        pytest.skip("sklearn installed, skip unavailable test")
    except ImportError:
        df = pd.DataFrame({"x": [1, 2], "y": [1, 2]})
        with pytest.raises(NotImplementedError):
            cluster(df, columns=["x", "y"], k=2, method="kmeans")


# ===== anomaly_attribution =====

def test_anomaly_attribution_basic():
    df = pd.DataFrame({
        "brand": ["a", "b", "c"],
        "sales": [100, 200, 50],  # c 是异常低
    })
    out, chart = anomaly_attribution(
        df, value_col="sales", group_by=["brand"], baseline="mean"
    )
    assert "deviation" in out.columns
    assert chart.type == "bar"


# ===== P1-1: ChartSpec.data 应是 DataFrame 引用（B 方案架构改动） =====
# 外部 AI P1-1 finding：6 处 to_dict("records") 把聚合后 DataFrame 全量转 dict，
# 33 万行 = +399MB 内存，Web 渲染会卡死。
# B 方案：ChartSpec.data 改 DataFrame 引用 + to_json() 惰性序列化 + 采样上限。

def test_chart_spec_data_is_dataframe_not_dict_list():
    """ChartSpec.data 应是 DataFrame 引用，不是 dict list

    外部 AI P1-1：原 to_dict("records") 立即序列化全量数据。
    B 方案：存 DataFrame 引用，调用方需要时调 to_json() 惰性序列化。
    """
    df = pd.DataFrame({"brand": ["a", "b"], "sales": [10, 20]})
    out, chart = aggregate(df, group_by=["brand"], agg={"sales": "sum"})
    # data 应是 DataFrame，不是 list[dict]
    assert isinstance(chart.data, pd.DataFrame), (
        f"ChartSpec.data 应是 DataFrame（B 方案架构改动），"
        f"实际类型 {type(chart.data).__name__}"
    )


def test_chart_spec_to_json_lazy_serialization_with_sampling():
    """ChartSpec.to_json() 惰性序列化 + max_rows 采样上限

    外部 AI P1-1：33 万行 to_dict 立即占 +399MB。
    B 方案：to_json(max_rows=N) 只序列化前 N 行，超出标记"已采样"。
    """
    # 构造 5000 行聚合结果
    df = pd.DataFrame({
        "brand": [f"b{i}" for i in range(5000)],
        "sales": range(5000),
    })
    out, chart = aggregate(df, group_by=["brand"], agg={"sales": "sum"})
    # to_json 默认 max_rows=1000
    data = chart.to_json()
    assert isinstance(data, list)
    assert len(data) == 1000, (
        f"to_json 默认 max_rows=1000，实际 {len(data)}"
    )
    # 显式 max_rows=500
    data_500 = chart.to_json(max_rows=500)
    assert len(data_500) == 500


def test_chart_spec_to_json_returns_full_when_under_limit():
    """行数低于 max_rows 时 to_json 返回全量"""
    df = pd.DataFrame({"brand": ["a", "b", "c"], "sales": [10, 20, 30]})
    out, chart = aggregate(df, group_by=["brand"], agg={"sales": "sum"})
    data = chart.to_json()
    assert len(data) == 3  # 全量


# ===== P1-2: modeler.trend 对字符串日期列应自动转 datetime =====
# 外部 AI P1-2 finding：P2 修复不彻底，FakePlanGenerator 加了 _pick_time_col，
# 但 modeler.trend 本身仍直接 set_index().resample()，
# 字符串日期列（如 "2026-01"）会 TypeError。

def test_trend_handles_string_date_column():
    """trend 对字符串日期列应自动 pd.to_datetime 转换再 resample"""
    df = pd.DataFrame({
        "month": ["2026-01-31", "2026-02-28", "2026-03-31"],  # 字符串
        "sales": [100, 200, 150],
    })
    out, chart = trend(df, time_col="month", value_col="sales", freq="M")
    # 应成功执行，不抛 TypeError
    assert len(out) > 0
    assert chart.type == "line"


def test_trend_raises_on_unparseable_date_column():
    """trend 对无法解析为 datetime 的列应抛明确错误"""
    import pytest
    df = pd.DataFrame({
        "month": ["abc", "def", "ghi"],  # 无法解析
        "sales": [100, 200, 150],
    })
    with pytest.raises((ValueError, TypeError)):
        trend(df, time_col="month", value_col="sales", freq="M")
