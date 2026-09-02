"""F002 P1: CSV Adapter（spec §3.3）

读 .csv / .tsv 文件，自动编码检测。

G1 大数据量优化：支持 max_rows 采样加载（pd.read_csv(nrows=N)），
避免 33 万行 CSV 全量加载 OOM。采样时 metadata 标 sampled=True + full_row_count。
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
        max_rows = source_desc.get("max_rows")

        read_kwargs = {"sep": sep, "encoding": encoding}
        if max_rows is not None:
            read_kwargs["nrows"] = max_rows

        try:
            df = pd.read_csv(path, **read_kwargs)
        except UnicodeDecodeError:
            df = pd.read_csv(path, sep=sep, encoding="gbk", **{k: v for k, v in read_kwargs.items() if k != "encoding"})

        # 采样时拿全量行数（不加载到内存，只数行）
        full_row_count = len(df)
        sampled = False
        if max_rows is not None:
            full_row_count = _count_csv_rows(path, sep, encoding)
            sampled = True

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
                "sampled": sampled,
                "full_row_count": full_row_count,
            },
            source_type="csv",
            columns=columns,
        )

    def supported_types(self) -> list[str]:
        return ["csv"]


def _count_csv_rows(path: Path, sep: str, encoding: str | None) -> int:
    """数 CSV 总行数（不算 header），不加载到内存"""
    import csv
    enc = encoding or "utf-8"
    with open(path, "r", encoding=enc, newline="") as f:
        reader = csv.reader(f, delimiter=sep)
        count = sum(1 for _ in reader) - 1  # 减 header
    return max(count, 0)
