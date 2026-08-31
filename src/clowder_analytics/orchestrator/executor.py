"""F002 P1.5: Plan 执行器（spec §6.2 / ADR-0001 D10）

P1.5 阶段不接 LLM、不接 Router、不接 Flow Library 沉淀；
仅验证"Plan + 原子 op + 执行器"链路通。

执行流程：
1. 取 plan.steps，逐步执行
2. 每步：从 op_registry 查 op callable，调用 op(df, **args) -> (df, op_report)
3. op_report 写入 run_log，op 失败抛 OpError 时按 fallback_strategy 决定 abort/continue
4. model op 返回的 ChartSpec 收集到 charts
5. 返回 RunResult

op 命名约定：
- "clean.<name>" → clowder_analytics.atomic.cleaner.<name>
- "model.<name>" → clowder_analytics.atomic.modeler.<name>
"""
from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from clowder_analytics.atomic import cleaner, modeler
from clowder_analytics.atomic.spec import ChartSpec
from clowder_analytics.adapters.base import Dataset
from clowder_analytics.orchestrator.plan import OpError, Plan, RunResult, Step


# ===== op 注册表 =====

def _build_op_registry() -> dict[str, Callable]:
    """从 cleaner / modeler 模块反射构建 op 注册表

    key: "clean.<name>" / "model.<name>"
    value: op callable（签名 f(df, **args) -> (df, op_report|ChartSpec)）
    """
    registry: dict[str, Callable] = {}
    for name in dir(cleaner):
        obj = getattr(cleaner, name)
        if callable(obj) and not name.startswith("_"):
            registry[f"clean.{name}"] = obj
    for name in dir(modeler):
        obj = getattr(modeler, name)
        if callable(obj) and not name.startswith("_"):
            registry[f"model.{name}"] = obj
    return registry


_OP_REGISTRY = _build_op_registry()


def get_op_registry() -> dict[str, Callable]:
    """供测试 / 后续 LLM spec() 检索使用"""
    return _OP_REGISTRY


# ===== 执行器 =====

def execute(plan: Plan, dataset: Dataset) -> RunResult:
    """执行 Plan，返回 RunResult（spec §6.2）

    Args:
        plan: Plan 对象
        dataset: Dataset（取 .df 作为初始 df）

    Returns:
        RunResult（df + charts + log + route/plan_id 元信息）
    """
    df: pd.DataFrame = dataset.df
    run_log: list[dict[str, Any]] = []
    charts: list[ChartSpec] = []

    for step in plan.steps:
        entry = {"step": step.op, "ok": False}
        try:
            op_fn = _OP_REGISTRY.get(step.op)
            if op_fn is None:
                raise OpError(f"未知 op: {step.op}")

            out = op_fn(df, **step.args)
            # op 约定：返回 (df_or_result, op_report_or_chartspec)
            if not isinstance(out, tuple) or len(out) != 2:
                raise OpError(f"op {step.op} 未按约定返回 (df, report) 二元组")
            new_df, op_report = out

            # model op 的 op_report 是 ChartSpec
            if isinstance(op_report, ChartSpec):
                charts.append(op_report)
                entry["report"] = {"chart_spec": op_report.type}
            else:
                entry["report"] = op_report

            df = new_df
            entry["ok"] = True
        except OpError as e:
            entry["err"] = str(e)
            run_log.append(entry)
            if plan.fallback_strategy == "abort_on_first_error":
                break
            continue
        except Exception as e:
            # 把 op 内部的 ValueError / KeyError 等包装成 OpError
            entry["err"] = f"{type(e).__name__}: {e}"
            run_log.append(entry)
            if plan.fallback_strategy == "abort_on_first_error":
                break
            continue
        run_log.append(entry)

    return RunResult(
        df=df,
        charts=charts,
        log=run_log,
        route="B",
        review=None,
        plan_id=plan.plan_id,
    )
