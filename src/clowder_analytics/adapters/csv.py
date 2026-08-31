"""F002 P1: CSV Adapter（spec §3.3）

读 .csv / .tsv 文件，自动编码检测。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from clowder_analytics.adapters.base import (
    ColumnSpec,
    Dataset,
    DataSourceAdapter,
    compute_fingerprint,
)


class CsvAdapter(DataSourceAdapter):
    """读 CSV/TSV 为 Dataset"""

    def load(self, source_desc: dict[str, Any]) -> Dataset:
        path = Path(source_desc["path"])
        sep = source_desc.get("sep", ",")
        # encoding 不指定时 pandas 自动检测（fallback utf-8）
        encoding = source_desc.get("encoding")
        try:
            df = pd.read_csv(path, sep=sep, encoding=encoding)
        except UnicodeDecodeError:
            df = pd.read_csv(path, sep=sep, encoding="gbk")

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
                "path": str(path),
                "row_count": len(df),
                "encoding": encoding or "auto",
            },
            source_type="csv",
            columns=columns,
        )

    def supported_types(self) -> list[str]:
        return ["csv"]
