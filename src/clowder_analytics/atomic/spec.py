"""F002 P1: ChartSpec 声明式图表描述（spec §4.4）

Modeler 输出 ChartSpec，Visualizer 按 ChartSpec 渲染。
解耦"算什么"和"画什么"。

B 方案架构改动（外部 AI P1-1 修复）：
- ChartSpec.data 改为 DataFrame 引用（不立即 to_dict 序列化）
- to_json(max_rows) 惰性序列化 + 采样上限
- 避免大表 to_dict 占双份内存（DataFrame + dict list）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class ChartSpec:
    """声明式图表描述

    type: bar | line | scatter | heatmap（spec AC-2）
    data: DataFrame 引用（B 方案：不立即序列化，惰性 to_json()）
    title: 图表标题
    x: x 轴列名
    y: y 轴列名（或列列表）
    """
    type: str
    data: pd.DataFrame
    title: str = ""
    x: str = ""
    y: str | list[str] = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self, max_rows: int = 1000) -> list[dict]:
        """惰性序列化：调用时才转 dict，且采样到 max_rows 行

        外部 AI P1-1 B 方案：避免 33 万行 to_dict 占 +399MB 内存。
        Web 渲染 / CLI 输出时调用方主动调 to_json(max_rows=N) 控制采样。

        Args:
            max_rows: 最大行数，超出只取前 N 行（默认 1000）

        Returns:
            list[dict]——DataFrame 的 records 格式
        """
        if len(self.data) > max_rows:
            return self.data.head(max_rows).to_dict("records")
        return self.data.to_dict("records")
