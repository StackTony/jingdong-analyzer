"""F002 P1: Modeler 原子能力集（spec §4.3）

6 个建模 op：
- aggregate: group_by + agg
- topn: TopN 排名（降序）
- trend: 时序聚合（按 freq 重采样）
- correlation: 相关性矩阵
- cluster: K-means 聚类（依赖 sklearn，可选）
- anomaly_attribution: 异常归因（vs baseline）

接口约定：f(df, **args) -> (df_or_result, ChartSpec)
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from clowder_analytics.atomic.spec import ChartSpec


# ===== aggregate =====

def aggregate(
    df: pd.DataFrame,
    group_by: list[str],
    agg: dict[str, str],
) -> tuple[pd.DataFrame, ChartSpec]:
    """聚合"""
    out = df.groupby(group_by, as_index=False).agg(agg)
    chart = ChartSpec(
        type="bar",
        data=out.to_dict("records"),
        title=f"Aggregate by {','.join(group_by)}",
        x=group_by[0],
        y=list(agg.keys()),
    )
    return out, chart


# ===== topn =====

def topn(
    df: pd.DataFrame,
    group_by: list[str],
    value_col: str,
    n: int,
    rank_by: str = "value",
) -> tuple[pd.DataFrame, ChartSpec]:
    """TopN 排名"""
    if rank_by == "value":
        out = df.nlargest(n, value_col).reset_index(drop=True)
    else:
        raise ValueError(f"未知 rank_by: {rank_by}")
    chart = ChartSpec(
        type="bar",
        data=out.to_dict("records"),
        title=f"Top {n} by {value_col}",
        x=group_by[0],
        y=value_col,
    )
    return out, chart


# ===== trend =====

def trend(
    df: pd.DataFrame,
    time_col: str,
    value_col: str,
    freq: str = "M",
) -> tuple[pd.DataFrame, ChartSpec]:
    """时序聚合（按 freq 重采样求和）

    freq: pandas offset alias, e.g. "M" month, "W" week, "D" day
    """
    # pandas 2.2+ 弃用 "M" 改 "ME"；接受用户传入两种
    freq_normalized = freq
    if freq == "M":
        freq_normalized = "ME"
    out = (
        df.set_index(time_col)
        .resample(freq_normalized)[value_col]
        .sum()
        .reset_index()
    )
    chart = ChartSpec(
        type="line",
        data=out.to_dict("records"),
        title=f"Trend by {freq}",
        x=time_col,
        y=value_col,
    )
    return out, chart


# ===== correlation =====

def correlation(
    df: pd.DataFrame,
    columns: list[str],
    method: str = "pearson",
) -> tuple[pd.DataFrame, ChartSpec]:
    """相关性矩阵"""
    out = df[columns].corr(method=method)
    chart = ChartSpec(
        type="heatmap",
        data=out.to_dict(),
        title=f"Correlation ({method})",
        x=columns,
        y=columns,
    )
    return out, chart


# ===== cluster =====

def cluster(
    df: pd.DataFrame,
    columns: list[str],
    k: int,
    method: str = "kmeans",
) -> tuple[pd.DataFrame, ChartSpec]:
    """K-means 聚类（依赖 sklearn，可选）"""
    try:
        from sklearn.cluster import KMeans
    except ImportError as e:
        raise NotImplementedError(
            "cluster op 需要 sklearn：pip install scikit-learn"
        ) from e

    if method != "kmeans":
        raise ValueError(f"未知 method: {method}")

    X = df[columns].values
    km = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels = km.fit_predict(X)
    out = df.copy()
    out["cluster"] = labels
    chart = ChartSpec(
        type="scatter",
        data=out.to_dict("records"),
        title=f"KMeans k={k}",
        x=columns[0],
        y=columns[1] if len(columns) > 1 else "",
    )
    return out, chart


# ===== anomaly_attribution =====

def anomaly_attribution(
    df: pd.DataFrame,
    value_col: str,
    group_by: list[str],
    baseline: str = "mean",
) -> tuple[pd.DataFrame, ChartSpec]:
    """异常归因：每行 vs baseline 偏离"""
    if baseline == "mean":
        base = df[value_col].mean()
    elif baseline == "median":
        base = df[value_col].median()
    else:
        raise ValueError(f"未知 baseline: {baseline}")
    out = df.copy()
    out["deviation"] = out[value_col] - base
    out["deviation_pct"] = (out["deviation"] / base * 100).round(2) if base else 0
    chart = ChartSpec(
        type="bar",
        data=out.to_dict("records"),
        title=f"Anomaly vs {baseline}",
        x=group_by[0],
        y="deviation",
    )
    return out, chart
