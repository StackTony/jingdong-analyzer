"""F002 P1: Excel Adapter（spec §3.3）

读 .xlsx / .xls 文件，支持多 sheet（默认第一个）。
输出 Dataset 对象含 schema_fingerprint。
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


class ExcelAdapter(DataSourceAdapter):
    """读 Excel 文件为 Dataset"""

    def load(self, source_desc: dict[str, Any]) -> Dataset:
        path = Path(source_desc["path"])
        sheet = source_desc.get("sheet", 0)  # 0 = 第一个 sheet
        df = pd.read_excel(path, sheet_name=sheet)

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
                "sheet": str(sheet),
                "row_count": len(df),
            },
            source_type="excel",
            columns=columns,
        )

    def supported_types(self) -> list[str]:
        return ["excel"]
