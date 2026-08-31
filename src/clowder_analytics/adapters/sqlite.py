"""F002 P1: SQLite Adapter（spec §3.3）

接 sqlite:///<path>，读整张表或自定义 query。
复用 F001 的 sqlalchemy 资产（data/jd_analytics.db）。
"""
from __future__ import annotations

from typing import Any

import pandas as pd
from sqlalchemy import create_engine, text

from clowder_analytics.adapters.base import (
    ColumnSpec,
    Dataset,
    DataSourceAdapter,
    compute_fingerprint,
)


class SqliteAdapter(DataSourceAdapter):
    """读 SQLite DB 为 Dataset"""

    def load(self, source_desc: dict[str, Any]) -> Dataset:
        conn_str = source_desc["conn_str"]
        table = source_desc.get("table")
        query = source_desc.get("query")

        if not table and not query:
            raise ValueError("SqliteAdapter 需要 'table' 或 'query' 之一")

        engine = create_engine(conn_str)
        try:
            if query:
                df = pd.read_sql(text(query), engine.connect())
            else:
                df = pd.read_sql_table(table, engine)
        finally:
            engine.dispose()

        column_hints = source_desc.get("column_hints")
        fp = compute_fingerprint(df, column_hints)
        columns = [
            ColumnSpec(name=c, dtype=str(df[c].dtype))
            for c in df.columns
        ]
        return Dataset(
            df=df,
            schema_fingerprint=fp,
            metadata={
                "conn_str": conn_str,
                "table": table,
                "query": query,
                "row_count": len(df),
            },
            source_type="sqlite",
            columns=columns,
        )

    def supported_types(self) -> list[str]:
        return ["sqlite"]
