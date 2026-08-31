"""F002 P1: Cleaner 原子 op 红测（spec §4.2）

按 D10：先红测再实现。覆盖 6 个 Cleaner op：
- remove_duplicates
- fill_missing
- convert_types
- remove_outliers
- normalize_text
- map_fields

每个 op 接口：f(df, **args) -> (df_or_result, op_report)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from clowder_analytics.atomic.cleaner import (
    fill_missing,
    map_fields,
    normalize_text,
    remove_duplicates,
    remove_outliers,
    convert_types,
)


# ===== remove_duplicates =====

def test_remove_duplicates_basic():
    df = pd.DataFrame({"id": [1, 1, 2], "v": [10, 20, 30]})
    out, report = remove_duplicates(df, keys=["id"])
    assert len(out) == 2
    assert report["removed"] == 1


def test_remove_duplicates_keep_last():
    df = pd.DataFrame({"id": [1, 1, 2], "v": [10, 20, 30]})
    out, _ = remove_duplicates(df, keys=["id"], keep="last")
    assert out.loc[out["id"] == 1, "v"].iloc[0] == 20


def test_remove_duplicates_keep_max_review():
    df = pd.DataFrame({
        "id": [1, 1, 2],
        "v": [10, 20, 30],
        "reviews": [5, 100, 50],
    })
    out, _ = remove_duplicates(
        df, keys=["id"], keep="max_review", review_col="reviews"
    )
    assert out.loc[out["id"] == 1, "v"].iloc[0] == 20  # 100 reviews 那条


# ===== fill_missing =====

def test_fill_missing_zero():
    df = pd.DataFrame({"a": [1.0, None, 3.0]})
    out, report = fill_missing(df, columns=["a"], strategy="zero")
    assert out["a"].iloc[1] == 0
    assert report["filled"] == 1


def test_fill_missing_mean():
    df = pd.DataFrame({"a": [10.0, None, 20.0]})
    out, _ = fill_missing(df, columns=["a"], strategy="mean")
    assert out["a"].iloc[1] == 15.0


def test_fill_missing_drop():
    df = pd.DataFrame({"a": [1.0, None, 3.0]})
    out, _ = fill_missing(df, columns=["a"], strategy="drop")
    assert len(out) == 2


def test_fill_missing_ffill():
    df = pd.DataFrame({"a": [1.0, None, None, 4.0]})
    out, _ = fill_missing(df, columns=["a"], strategy="ffill")
    assert out["a"].tolist() == [1.0, 1.0, 1.0, 4.0]


# ===== convert_types =====

def test_convert_types_to_int():
    df = pd.DataFrame({"a": ["1", "2", "3"]})
    out, report = convert_types(df, column_types={"a": "int"})
    assert out["a"].dtype.kind == "i"


def test_convert_types_to_datetime():
    df = pd.DataFrame({"d": ["2026-01-01", "2026-02-01"]})
    out, _ = convert_types(df, column_types={"d": "datetime"})
    assert out["d"].dtype.kind == "M"


def test_convert_types_to_category():
    df = pd.DataFrame({"brand": ["a", "b", "a"]})
    out, _ = convert_types(df, column_types={"brand": "category"})
    assert str(out["brand"].dtype) == "category"


# ===== remove_outliers =====

def test_remove_outliers_iqr():
    df = pd.DataFrame({"v": [1, 2, 3, 4, 100]})  # 100 是异常
    out, report = remove_outliers(df, column="v", method="iqr", threshold=1.5)
    assert 100 not in out["v"].values
    assert report["removed"] == 1


def test_remove_outliers_zscore():
    np.random.seed(0)
    arr = list(np.random.normal(50, 5, 20)) + [1000]  # 1000 是异常
    df = pd.DataFrame({"v": arr})
    out, _ = remove_outliers(df, column="v", method="zscore", threshold=3.0)
    assert 1000 not in out["v"].values


# ===== normalize_text =====

def test_normalize_text_trim_lower():
    df = pd.DataFrame({"brand": ["  小米 ", "华为", "  OPPO  "]})
    out, _ = normalize_text(df, columns=["brand"], ops=["trim", "lower"])
    # trim 去首尾空白；lower 转英文小写，中文不变
    assert out["brand"].tolist() == ["小米", "华为", "oppo"]


def test_normalize_text_strip_punct():
    df = pd.DataFrame({"brand": ["小米（官方）", "华为。" ]})
    out, _ = normalize_text(df, columns=["brand"], ops=["strip_punct"])
    assert "（" not in out["brand"].iloc[0]
    assert "。" not in out["brand"].iloc[1]


# ===== map_fields =====

def test_map_fields_rename():
    df = pd.DataFrame({"brand_name": ["a"], "sales_volume": [10]})
    out, report = map_fields(df, mapping={"brand_name": "brand", "sales_volume": "sales"})
    assert "brand" in out.columns
    assert "sales" in out.columns
    assert "brand_name" not in out.columns


def test_map_fields_partial():
    df = pd.DataFrame({"a": [1], "b": [2]})
    out, _ = map_fields(df, mapping={"a": "alpha"})
    assert list(out.columns) == ["alpha", "b"]
