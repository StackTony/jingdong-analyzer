"""F002 P1: Excel/CSV/SQLite Adapter 红测（TDD）

按 D10：先红测再实现。覆盖：
- ExcelAdapter 读 .xlsx 多 sheet
- CsvAdapter 读 .csv 自动编码检测
- SqliteAdapter 读 jd_analytics.db
- 三个 Adapter 输出 Dataset 对象（含 schema_fingerprint）

依赖：openpyxl（Excel）/ 无（CSV 用 pandas 内置）/ sqlalchemy（SQLite，已装）
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from clowder_analytics.adapters.base import Dataset, compute_fingerprint
from clowder_analytics.adapters.csv import CsvAdapter
from clowder_analytics.adapters.excel import ExcelAdapter
from clowder_analytics.adapters.sqlite import SqliteAdapter


# ===== ExcelAdapter =====

@pytest.fixture
def sample_xlsx(tmp_path: Path) -> Path:
    df = pd.DataFrame({
        "brand": ["小米", "华为", "荣耀"],
        "sales": [100, 200, 150],
        "price": [2999.0, 3199.0, 1486.0],
    })
    path = tmp_path / "sample.xlsx"
    df.to_excel(path, index=False, sheet_name="Sheet1")
    return path


def test_excel_adapter_load_returns_dataset(sample_xlsx: Path):
    adapter = ExcelAdapter()
    ds = adapter.load({"path": str(sample_xlsx)})
    assert isinstance(ds, Dataset)
    assert ds.source_type == "excel"
    assert len(ds.df) == 3
    assert set(ds.df.columns) == {"brand", "sales", "price"}


def test_excel_adapter_fingerprint_set(sample_xlsx: Path):
    ds = ExcelAdapter().load({"path": str(sample_xlsx)})
    assert ds.schema_fingerprint
    assert len(ds.schema_fingerprint) == 16


def test_excel_adapter_metadata_has_path(sample_xlsx: Path):
    ds = ExcelAdapter().load({"path": str(sample_xlsx)})
    assert "path" in ds.metadata
    assert ds.metadata["path"] == str(sample_xlsx)


def test_excel_adapter_supported_types():
    assert "excel" in ExcelAdapter().supported_types()


def test_excel_adapter_multi_sheet(tmp_path: Path):
    df1 = pd.DataFrame({"a": [1, 2]})
    df2 = pd.DataFrame({"b": [3, 4]})
    path = tmp_path / "multi.xlsx"
    with pd.ExcelWriter(path) as w:
        df1.to_excel(w, sheet_name="S1", index=False)
        df2.to_excel(w, sheet_name="S2", index=False)
    # 默认读第一个 sheet
    ds = ExcelAdapter().load({"path": str(path)})
    assert set(ds.df.columns) == {"a"}
    # 指定 sheet
    ds2 = ExcelAdapter().load({"path": str(path), "sheet": "S2"})
    assert set(ds2.df.columns) == {"b"}


# ===== CsvAdapter =====

@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    df = pd.DataFrame({"brand": ["a", "b"], "sales": [10, 20]})
    path = tmp_path / "sample.csv"
    df.to_csv(path, index=False, encoding="utf-8")
    return path


def test_csv_adapter_load_returns_dataset(sample_csv: Path):
    ds = CsvAdapter().load({"path": str(sample_csv)})
    assert isinstance(ds, Dataset)
    assert ds.source_type == "csv"
    assert len(ds.df) == 2


def test_csv_adapter_supported_types():
    assert "csv" in CsvAdapter().supported_types()


def test_csv_adapter_fingerprint_matches_excel_same_schema(tmp_path: Path):
    """同 schema（列名+dtype）→ 同 fingerprint，无论源是 csv 还是 xlsx"""
    df = pd.DataFrame({"brand": ["x"], "sales": [1]})
    csv_path = tmp_path / "a.csv"
    xlsx_path = tmp_path / "a.xlsx"
    df.to_csv(csv_path, index=False)
    df.to_excel(xlsx_path, index=False)
    csv_fp = CsvAdapter().load({"path": str(csv_path)}).schema_fingerprint
    xlsx_fp = ExcelAdapter().load({"path": str(xlsx_path)}).schema_fingerprint
    assert csv_fp == xlsx_fp


# ===== SqliteAdapter =====

@pytest.fixture
def sample_sqlite(tmp_path: Path) -> Path:
    path = tmp_path / "test.db"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE products (brand TEXT, sales INTEGER, price REAL)")
    conn.execute("INSERT INTO products VALUES ('小米', 100, 2999.0)")
    conn.execute("INSERT INTO products VALUES ('华为', 200, 3199.0)")
    conn.commit()
    conn.close()
    return path


def test_sqlite_adapter_load_returns_dataset(sample_sqlite: Path):
    ds = SqliteAdapter().load({
        "conn_str": f"sqlite:///{sample_sqlite}",
        "table": "products",
    })
    assert isinstance(ds, Dataset)
    assert ds.source_type == "sqlite"
    assert len(ds.df) == 2


def test_sqlite_adapter_supported_types():
    assert "sqlite" in SqliteAdapter().supported_types()


def test_sqlite_adapter_with_query(sample_sqlite: Path):
    ds = SqliteAdapter().load({
        "conn_str": f"sqlite:///{sample_sqlite}",
        "query": "SELECT brand, sales FROM products WHERE sales > 150",
    })
    assert len(ds.df) == 1
    assert ds.df.iloc[0]["brand"] == "华为"
