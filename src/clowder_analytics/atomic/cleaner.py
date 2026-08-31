"""F002 P1: Cleaner 原子能力集（spec §4.2）

6 个清洗 op：
- remove_duplicates: 按 keys 去重
- fill_missing: 缺值填充
- convert_types: 类型转换
- remove_outliers: 异常值剔除
- normalize_text: 文本标准化
- map_fields: 字段重命名/映射

接口约定：f(df, **args) -> (df, op_report)
op_report 是 dict，至少含 affected 行数
"""
from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd


# ===== remove_duplicates =====

def remove_duplicates(
    df: pd.DataFrame,
    keys: list[str],
    keep: str = "first",
    review_col: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """按 keys 去重

    keep:
        - "first": 保留第一条（默认）
        - "last": 保留最后一条
        - "max_review": 保留 review_col 最大的那条
    """
    before = len(df)
    if keep == "max_review":
        if not review_col:
            raise ValueError("keep=max_review 需要 review_col")
        idx = df.groupby(keys)[review_col].idxmax()
        out = df.loc[idx].reset_index(drop=True)
    else:
        out = df.drop_duplicates(subset=keys, keep=keep).reset_index(drop=True)
    return out, {"removed": before - len(out), "kept": len(out)}


# ===== fill_missing =====

def fill_missing(
    df: pd.DataFrame,
    columns: list[str],
    strategy: str = "zero",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """缺值填充

    strategy:
        - "zero": 填 0
        - "mean": 填均值（数值列）
        - "median": 填中位数（数值列）
        - "ffill": 前向填充
        - "drop": 删掉缺值行
    """
    out = df.copy()
    filled = 0
    if strategy == "drop":
        out = out.dropna(subset=columns).reset_index(drop=True)
        return out, {"filled": 0, "dropped": len(df) - len(out)}
    for col in columns:
        n_na = out[col].isna().sum()
        if strategy == "zero":
            out[col] = out[col].fillna(0)
        elif strategy == "mean":
            out[col] = out[col].fillna(out[col].mean())
        elif strategy == "median":
            out[col] = out[col].fillna(out[col].median())
        elif strategy == "ffill":
            out[col] = out[col].ffill()
        else:
            raise ValueError(f"未知 strategy: {strategy}")
        filled += int(n_na)
    return out, {"filled": filled}


# ===== convert_types =====

def convert_types(
    df: pd.DataFrame,
    column_types: dict[str, str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """类型转换

    column_types 形如 {"col": "int"|"float"|"datetime"|"category"}
    """
    out = df.copy()
    converted = 0
    for col, t in column_types.items():
        if t == "int":
            out[col] = pd.to_numeric(out[col], errors="coerce").astype("Int64")
        elif t == "float":
            out[col] = pd.to_numeric(out[col], errors="coerce")
        elif t == "datetime":
            out[col] = pd.to_datetime(out[col], errors="coerce")
        elif t == "category":
            out[col] = out[col].astype("category")
        else:
            raise ValueError(f"未知类型: {t}")
        converted += 1
    return out, {"converted": converted}


# ===== remove_outliers =====

def remove_outliers(
    df: pd.DataFrame,
    column: str,
    method: str = "iqr",
    threshold: float = 1.5,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """异常值剔除

    method:
        - "iqr": Q1 - threshold*IQR 以下或 Q3 + threshold*IQR 以上视为异常
        - "zscore": |z| > threshold 视为异常
    """
    s = df[column]
    if method == "iqr":
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        lo, hi = q1 - threshold * iqr, q3 + threshold * iqr
        mask = (s >= lo) & (s <= hi)
    elif method == "zscore":
        z = (s - s.mean()) / s.std()
        mask = z.abs() <= threshold
    else:
        raise ValueError(f"未知 method: {method}")
    out = df[mask].reset_index(drop=True)
    return out, {"removed": len(df) - len(out), "kept": len(out)}


# ===== normalize_text =====

def normalize_text(
    df: pd.DataFrame,
    columns: list[str],
    ops: list[str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """文本标准化

    ops:
        - "trim": 去首尾空白
        - "lower": 转小写
        - "strip_punct": 去中英文标点
    """
    out = df.copy()
    for col in columns:
        s = out[col].astype(str)
        if "trim" in ops:
            s = s.str.strip()
        if "lower" in ops:
            s = s.str.lower()
        if "strip_punct" in ops:
            # 去中文标点（含全角）+ 英文标点
            s = s.str.replace(
                r"[，。！？；：（）【】「」、\,\.\!\?\;\:\(\)\[\]\{\}\"'\s]",
                "",
                regex=True,
            )
        out[col] = s
    return out, {"affected_columns": len(columns)}


# ===== map_fields =====

def map_fields(
    df: pd.DataFrame,
    mapping: dict[str, str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """字段重命名/映射"""
    out = df.rename(columns=mapping)
    return out, {"renamed": len(mapping)}
