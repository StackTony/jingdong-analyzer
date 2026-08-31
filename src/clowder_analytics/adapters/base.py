"""F002 P1: DataSource Adapter 基础抽象（spec §3）

核心抽象：
- ColumnSpec: 列声明（name + dtype + semantic_hint）
- Dataset: 统一数据对象（df + schema_fingerprint + metadata + source_type + columns）
- DataSourceAdapter: 数据源适配器 ABC
- compute_fingerprint: schema 指纹算法（D2/D4 调整：base + semantic_hint 两层）

设计依据：ADR-0001 D2/D4
- base 层：列名小写归一 + dtype（稳定 hash）
- semantic_hint 层：用户/LLM 声明的列语义（可选）
- 同名不同义列靠 hint 区分（spec R8 风险应对）
"""
from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class ColumnSpec:
    """列声明（spec §3.1）"""
    name: str
    dtype: str
    semantic_hint: str | None = None


@dataclass
class Dataset:
    """统一数据对象（spec §3.1）

    所有 DataSource Adapter 输出此对象，下游 Cleaner/Modeler/Visualizer
    不感知源差异。
    """
    df: pd.DataFrame
    schema_fingerprint: str
    metadata: dict[str, Any] = field(default_factory=dict)
    source_type: str = ""
    columns: list[ColumnSpec] = field(default_factory=list)


def compute_fingerprint(
    df: pd.DataFrame,
    column_hints: dict[str, str] | None = None,
) -> str:
    """schema 指纹算法（ADR-0001 D2/D4）

    两层：
    1. base 层：列名小写归一 + dtype（spec §3.4 原方案）
    2. semantic_hint 层：用户/LLM 声明的列语义（可选，区分同名不同义）

    不含样本值（样本会变，导致 fp 不稳定）。

    Returns:
        16 字符 hex 串
    """
    base = sorted((c.lower(), str(df[c].dtype)) for c in df.columns)
    hints = sorted((k, v) for k, v in (column_hints or {}).items())
    payload = json.dumps({"base": base, "hints": hints}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class DataSourceAdapter(ABC):
    """数据源适配器抽象基类（spec §3.2）"""

    @abstractmethod
    def load(self, source_desc: Any) -> Dataset:
        """加载源数据为 Dataset"""
        raise NotImplementedError

    @abstractmethod
    def supported_types(self) -> list[str]:
        """该 Adapter 支持的源类型列表"""
        raise NotImplementedError
