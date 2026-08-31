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
