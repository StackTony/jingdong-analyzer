"""F002 P1: Dataset 抽象 + DataSourceAdapter 红测（TDD）

测试覆盖：
- Dataset 数据类构造 + 字段
- ColumnSpec 语义提示
- compute_fingerprint 算法（D2/D4：base + semantic_hint 两层）
- Adapter 注册表

按 D10：先红测再实现。
"""
from __future__ import annotations

import pandas as pd
import pytest

from clowder_analytics.adapters.base import (
    ColumnSpec,
    Dataset,
    DataSourceAdapter,
    compute_fingerprint,
)


# ===== ColumnSpec =====

def test_column_spec_basic():
    cs = ColumnSpec(name="brand", dtype="object", semantic_hint="brand")
    assert cs.name == "brand"
    assert cs.dtype == "object"
    assert cs.semantic_hint == "brand"


def test_column_spec_semantic_hint_optional():
    cs = ColumnSpec(name="price", dtype="float64")
    assert cs.semantic_hint is None


# ===== Dataset =====

def test_dataset_construct_minimal():
    df = pd.DataFrame({"brand": ["a", "b"], "sales": [10, 20]})
    ds = Dataset(
        df=df,
        schema_fingerprint="abc123",
        metadata={"source": "test"},
        source_type="excel",
        columns=[ColumnSpec(name="brand", dtype="object")],
    )
    assert len(ds.df) == 2
    assert ds.source_type == "excel"


# ===== compute_fingerprint (D2/D4) =====

def test_fingerprint_stable_same_schema():
    df1 = pd.DataFrame({"brand": ["a"], "sales": [10]})
    df2 = pd.DataFrame({"brand": ["x", "y"], "sales": [99, 100]})
    fp1 = compute_fingerprint(df1)
    fp2 = compute_fingerprint(df2)
    assert fp1 == fp2  # 同 schema（列名+dtype），样本值不同 → 同 fp


def test_fingerprint_different_when_columns_differ():
    df1 = pd.DataFrame({"brand": ["a"], "sales": [10]})
    df2 = pd.DataFrame({"brand": ["a"], "price": [10]})
    assert compute_fingerprint(df1) != compute_fingerprint(df2)


def test_fingerprint_case_insensitive_columns():
    df1 = pd.DataFrame({"Brand": ["a"], "Sales": [10]})
    df2 = pd.DataFrame({"brand": ["a"], "sales": [10]})
    assert compute_fingerprint(df1) == compute_fingerprint(df2)


def test_fingerprint_with_semantic_hints():
    """D2 调整：同名不同义列应能区分"""
    df = pd.DataFrame({"id": [1, 2], "value": [10, 20]})
    fp_no_hint = compute_fingerprint(df)
    fp_with_hint = compute_fingerprint(df, column_hints={"id": "product_id"})
    # 加 hint 应改变 fingerprint（hint 是语义层，区分同名不同义）
    assert fp_no_hint != fp_with_hint


def test_fingerprint_hex_16():
    df = pd.DataFrame({"a": [1]})
    fp = compute_fingerprint(df)
    assert len(fp) == 16
    int(fp, 16)  # is valid hex


# ===== Adapter ABC =====

def test_adapter_is_abstract():
    with pytest.raises(TypeError):
        DataSourceAdapter()  # type: ignore[abstract]


def test_adapter_subclass_must_implement_load():
    class BadAdapter(DataSourceAdapter):
        pass

    with pytest.raises(TypeError):
        BadAdapter()  # type: ignore[abstract]


def test_adapter_subclass_with_load_ok():
    class FakeAdapter(DataSourceAdapter):
        def load(self, source_desc):
            return None

        def supported_types(self):
            return ["fake"]

    a = FakeAdapter()
    assert a.supported_types() == ["fake"]
