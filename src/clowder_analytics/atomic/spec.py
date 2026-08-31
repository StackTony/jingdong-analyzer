"""F002 P1: ChartSpec 声明式图表描述（spec §4.4）

Modeler 输出 ChartSpec，Visualizer 按 ChartSpec 渲染。
解耦"算什么"和"画什么"。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChartSpec:
    """声明式图表描述

    type: bar | line | scatter | heatmap（spec AC-2）
    data: 渲染所需数据（DataFrame 序列化形式 / dict）
    title: 图表标题
    x: x 轴列名
    y: y 轴列名（或列列表）
    """
    type: str
    data: dict[str, Any]
    title: str = ""
    x: str = ""
    y: str | list[str] = ""
    extra: dict[str, Any] = field(default_factory=dict)
