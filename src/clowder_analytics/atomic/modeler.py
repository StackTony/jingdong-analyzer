"""F002 P1: Modeler 原子能力集（spec §4.3）

6 个建模 op：
- aggregate: group_by + agg
- topn: TopN 排名（降序）
- trend: 时序聚合（按 freq 重采样）
- correlation: 相关性矩阵
- cluster: K-means 聚类（依赖 sklearn，可选）
- anomaly_attribution: 异常归因（vs baseline）

接口约定：f(df, **args) -> (df_or_result, ChartSpec)

B 方案架构改动（外部 AI P1-1 修复）：
- ChartSpec.data 存 DataFrame 引用（不立即 to_dict）
- 调用方调 chart.to_json(max_rows) 惰性序列化

P1-2 修复：
- trend op 内置 pd.to_datetime 预处理，字符串日期列自动转
- 无法解析时抛 ValueError（而非 set_index().resample() 的 TypeError）
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
        data=out,
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
        data=out,
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

    P1-2 修复：字符串日期列自动 pd.to_datetime 转换，
    无法解析时抛 ValueError（而非 set_index().resample() 的 TypeError）。
    """
    # pandas 2.2+ 弃用 "M" 改 "ME"；接受用户传入两种
    freq_normalized = freq
    if freq == "M":
        freq_normalized = "ME"

    # P1-2：time_col 不是 datetime 时尝试转换
    if not pd.api.types.is_datetime64_any_dtype(df[time_col]):
        try:
            df = df.copy()
            df[time_col] = pd.to_datetime(df[time_col])
        except (ValueError, TypeError) as e:
            raise ValueError(
                f"trend op 的 time_col '{time_col}' 无法解析为 datetime：{e}"
            ) from e

    out = (
        df.set_index(time_col)
        .resample(freq_normalized)[value_col]
        .sum()
        .reset_index()
    )
    chart = ChartSpec(
        type="line",
        data=out,
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
        data=out,
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
        data=out,
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
        data=out,
        title=f"Anomaly vs {baseline}",
        x=group_by[0],
        y="deviation",
    )
    return out, chart
