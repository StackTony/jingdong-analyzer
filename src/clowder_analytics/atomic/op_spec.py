"""F002 P3+ 原子能力 spec 清单（spec §4.1）

每个 op 的 args_schema + description，供 LLM Plan 生成器检索。
spec §4.1：每个能力自带 spec() 返回 (name, args_schema, description)。

集中定义避免分散在 cleaner/modeler 各函数里——
也方便后续 LLM 自动发现新 op。
"""
from __future__ import annotations

from typing import Any


# 每个 op 的 args schema：字段名 → 类型 + 是否必填 + 说明
OP_SPECS: dict[str, dict[str, Any]] = {
    # ===== Cleaner =====
    "clean.remove_duplicates": {
        "description": "按 keys 去重；keep: first|last|max_review（max_review 需 review_col）",
        "args": {
            "keys": {"type": "list[str]", "required": True, "desc": "去重键列名"},
            "keep": {"type": "str", "required": False, "default": "first",
                     "enum": ["first", "last", "max_review"]},
            "review_col": {"type": "str", "required": False,
                           "desc": "keep=max_review 时取此列最大的行"},
        },
    },
    "clean.fill_missing": {
        "description": "缺值填充；strategy: zero|mean|median|ffill|drop",
        "args": {
            "columns": {"type": "list[str]", "required": True, "desc": "填充列名"},
            "strategy": {"type": "str", "required": False, "default": "zero",
                         "enum": ["zero", "mean", "median", "ffill", "drop"]},
        },
    },
    "clean.convert_types": {
        "description": "类型转换",
        "args": {
            "column_types": {"type": "dict[str,str]", "required": True,
                             "desc": "列名 → int|float|datetime|category"},
        },
    },
    "clean.remove_outliers": {
        "description": "异常值剔除；method: iqr|zscore",
        "args": {
            "column": {"type": "str", "required": True},
            "method": {"type": "str", "required": False, "default": "iqr",
                       "enum": ["iqr", "zscore"]},
            "threshold": {"type": "float", "required": False, "default": 1.5},
        },
    },
    "clean.normalize_text": {
        "description": "文本标准化；ops: trim|lower|strip_punct",
        "args": {
            "columns": {"type": "list[str]", "required": True, "desc": "标准化列名"},
            "ops": {"type": "list[str]", "required": True,
                    "enum": ["trim", "lower", "strip_punct"],
                    "desc": "操作序列"},
        },
    },
    "clean.map_fields": {
        "description": "字段重命名",
        "args": {
            "mapping": {"type": "dict[str,str]", "required": True,
                        "desc": "旧列名 → 新列名"},
        },
    },
    # ===== Modeler =====
    "model.aggregate": {
        "description": "聚合；输出 ChartSpec(bar)",
        "args": {
            "group_by": {"type": "list[str]", "required": True, "desc": "分组列名"},
            "agg": {"type": "dict[str,str]", "required": True,
                    "desc": "数值列 → sum|mean|count|max|min 等 pandas agg"},
        },
    },
    "model.topn": {
        "description": "TopN 排名（降序）；输出 ChartSpec(bar)",
        "args": {
            "group_by": {"type": "list[str]", "required": True},
            "value_col": {"type": "str", "required": True, "desc": "排名数值列"},
            "n": {"type": "int", "required": True, "desc": "Top N"},
            "rank_by": {"type": "str", "required": False, "default": "value",
                        "enum": ["value"]},
        },
    },
    "model.trend": {
        "description": "时序聚合（按 freq 重采样求和）；输出 ChartSpec(line)",
        "args": {
            "time_col": {"type": "str", "required": True, "desc": "时间列名"},
            "value_col": {"type": "str", "required": True},
            "freq": {"type": "str", "required": False, "default": "M",
                     "desc": "pandas offset alias: M/W/D"},
        },
    },
    "model.correlation": {
        "description": "相关性矩阵；输出 ChartSpec(heatmap)",
        "args": {
            "columns": {"type": "list[str]", "required": True},
            "method": {"type": "str", "required": False, "default": "pearson",
                       "enum": ["pearson", "spearman"]},
        },
    },
    "model.cluster": {
        "description": "K-means 聚类（需 sklearn）；输出 ChartSpec(scatter)",
        "args": {
            "columns": {"type": "list[str]", "required": True},
            "k": {"type": "int", "required": True, "desc": "簇数"},
            "method": {"type": "str", "required": False, "default": "kmeans"},
        },
    },
    "model.anomaly_attribution": {
        "description": "异常归因（vs baseline）；输出 ChartSpec(bar)",
        "args": {
            "value_col": {"type": "str", "required": True},
            "group_by": {"type": "list[str]", "required": True},
            "baseline": {"type": "str", "required": False, "default": "mean",
                         "enum": ["mean", "median"]},
        },
    },
}


def format_op_specs_for_llm() -> str:
    """格式化 op spec 清单给 LLM prompt 用

    输出形如：
        clean.remove_duplicates:
          description: ...
          args:
            keys (list[str], required): 去重键列名
            keep (str, optional, default=first): enum=[first, last, max_review]
    """
    lines = []
    for op_name, spec in sorted(OP_SPECS.items()):
        lines.append(f"{op_name}:")
        lines.append(f"  description: {spec['description']}")
        lines.append("  args:")
        for arg_name, arg_spec in spec["args"].items():
            req = "required" if arg_spec.get("required") else "optional"
            type_str = arg_spec.get("type", "any")
            default = arg_spec.get("default")
            enum = arg_spec.get("enum")
            desc = arg_spec.get("desc", "")
            parts = [f"{arg_name} ({type_str}, {req}"]
            if default is not None:
                parts.append(f", default={default}")
            if enum:
                parts.append(f", enum={enum}")
            parts.append(f"): {desc}")
            lines.append(f"    {''.join(parts)}")
    return "\n".join(lines)
