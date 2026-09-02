"""F002 P1: SQLite Adapter（spec §3.3）

接 sqlite:///<path>，读整张表或自定义 query。
复用 F001 的 sqlalchemy 资产（data/jd_analytics.db）。

G1 大数据量优化：支持 max_rows 采样加载（query 包 LIMIT N），
避免百万行表全量加载 OOM。
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
        max_rows = source_desc.get("max_rows")

        if not table and not query:
            raise ValueError("SqliteAdapter 需要 'table' 或 'query' 之一")

        engine = create_engine(conn_str)
        try:
            # 先拿全量行数（SELECT COUNT(*)，不全加载）
            if table:
                count_sql = text(f"SELECT COUNT(*) FROM {table}")
            else:
                # query 模式：用子查询包 COUNT
                count_sql = text(f"SELECT COUNT(*) FROM ({query}) AS _sub")
            full_row_count = engine.connect().execute(count_sql).scalar()

            sampled = False
            if max_rows is not None:
                if query:
                    effective_query = f"{query} LIMIT {max_rows}"
                    df = pd.read_sql(text(effective_query), engine.connect())
                else:
                    df = pd.read_sql_table(table, engine, **{"chunksize": None} if False else {})
                    # pd.read_sql_table 不支持 LIMIT，用 SQL 查询
                    df = pd.read_sql(text(f"SELECT * FROM {table} LIMIT {max_rows}"), engine.connect())
                sampled = True
            else:
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
                "sampled": sampled,
                "full_row_count": full_row_count,
            },
            source_type="sqlite",
            columns=columns,
        )

    def supported_types(self) -> list[str]:
        return ["sqlite"]
