"""F002 P4: 端到端 run() 入口（spec §6.2 / §7.5）

把 P1.5 executor + P2 router + P3 generator/reviewer + P4 promoter 串成闭环：
1. route(question, dataset, library) → Route
2. 取 Plan：A 轨 from template.to_plan_dict(); B 轨 route.plan; fallback generator.generate()
3. execute(plan, dataset) → RunResult
4. reviewer_enabled 时调 reviewer.review()
5. save_run(RunRecord) 沉淀
6. fallback 生成的 Plan 也存 plans/ 供下次复用
7. scan_and_promote() 检查晋升机会

A 轨模板变量化（外部 AI P1 修复）：
- 模板 args 支持 {{numeric_col}} / {{group_col}} / {{time_col}} 占位符
- 命中模板后 resolve_template_variables(tpl, ds) 注入 dataset 实际列名
- 不匹配则返回 None（router 应判未命中走 B/fallback）

返回 RunResult（扩展含 matched_template_id / matched_plan_id / llm_calls）

设计依据：spec §6.2 / §7.1 / §7.5 / AC-6 / AC-11
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

from clowder_analytics.adapters.base import Dataset
from clowder_analytics.ai.base import AIPlanGenerator, AIReviewer
from clowder_analytics.ai.fake import FakePlanGenerator, FakeReviewer
from clowder_analytics.flow_library.models import RunRecord, Template
from clowder_analytics.flow_library.promoter import Promoter
from clowder_analytics.flow_library.store import FlowLibrary
from clowder_analytics.orchestrator.executor import ProgressCallback, execute
from clowder_analytics.orchestrator.plan import Plan, RunResult, Step
from clowder_analytics.orchestrator.router import Route, route

_ = field  # re-exported for dataclass users importing from this module


# ===== 模板列名变量解析（外部 AI P1 修复） =====

# 占位符 → 选择函数
_PLACEHOLDER_PATTERNS = (
    "{{numeric_col}}", "{{group_col}}", "{{time_col}}", "{{category_col}}",
)


def _pick_numeric_col(df: pd.DataFrame) -> str | None:
    """选数值列（偏好 sales/price/count/amount/value/qty）"""
    hints = ["sales", "price", "count", "amount", "value", "qty", "金额", "销售额"]
    cols = list(df.columns)
    for h in hints:
        for c in cols:
            if h in str(c).lower() and pd.api.types.is_numeric_dtype(df[c]):
                return c
    # 兜底：第一个数值列
    for c in cols:
        if pd.api.types.is_numeric_dtype(df[c]):
            return c
    return None


def _pick_group_col(df: pd.DataFrame) -> str | None:
    """选文本列（偏好 brand/name/产品/品牌）"""
    hints = ["brand", "name", "产品", "品牌", "label"]
    cols = list(df.columns)
    for h in hints:
        for c in cols:
            if h in str(c).lower() and not pd.api.types.is_numeric_dtype(df[c]):
                return c
    # 兜底：第一个非数值列
    for c in cols:
        if not pd.api.types.is_numeric_dtype(df[c]):
            return c
    return None


def _pick_category_col(df: pd.DataFrame) -> str | None:
    """选品类列（偏好 category/cat/品类）—— 用于"品类对比" intent"""
    hints = ["category", "cat", "品类", "类别", "分类"]
    cols = list(df.columns)
    for h in hints:
        for c in cols:
            if h in str(c).lower() and not pd.api.types.is_numeric_dtype(df[c]):
                return c
    # 兜底：回退到通用 group_col
    return _pick_group_col(df)


def _pick_time_col(df: pd.DataFrame) -> str | None:
    """选 datetime 列"""
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            return c
    # 尝试 parse 常见列名
    for c in df.columns:
        if any(k in str(c).lower() for k in ("date", "month", "时间", "日期")):
            return c
    return None


def _resolve_value(placeholder: str, dataset: Dataset) -> str:
    """把单个占位符解析为实际列名，找不到抛 ValueError"""
    if placeholder == "{{numeric_col}}":
        col = _pick_numeric_col(dataset.df)
        if col is None:
            raise ValueError("dataset 无数值列，无法解析 {{numeric_col}}")
        return col
    if placeholder == "{{group_col}}":
        col = _pick_group_col(dataset.df)
        if col is None:
            raise ValueError("dataset 无文本列，无法解析 {{group_col}}")
        return col
    if placeholder == "{{category_col}}":
        col = _pick_category_col(dataset.df)
        if col is None:
            raise ValueError("dataset 无品类列，无法解析 {{category_col}}")
        return col
    if placeholder == "{{time_col}}":
        col = _pick_time_col(dataset.df)
        if col is None:
            raise ValueError("dataset 无 datetime 列，无法解析 {{time_col}}")
        return col
    return placeholder


def _resolve_args(args: Any, dataset: Dataset) -> Any:
    """递归解析 args 中的占位符（dict key+value / list / str）

    注意：dict 的 key 也可能是占位符（如 agg: {"{{numeric_col}}": "sum"}），
    必须同时解析 key 和 value。
    """
    if isinstance(args, str):
        if args in _PLACEHOLDER_PATTERNS:
            return _resolve_value(args, dataset)
        return args
    if isinstance(args, list):
        return [_resolve_args(x, dataset) for x in args]
    if isinstance(args, dict):
        # key 和 value 都递归解析
        return {
            _resolve_args(k, dataset) if isinstance(k, str) else k: _resolve_args(v, dataset)
            for k, v in args.items()
        }
    return args


def resolve_template_variables(template: Template, dataset: Dataset) -> Template:
    """把模板 steps 里的 {{numeric_col}} / {{group_col}} / {{time_col}} 解析为实际列名

    外部 AI P1 修复：模板 schema_fingerprint='*' 通配任意数据源，
    但 args 硬编码 sales/brand 列名导致命中后失败。
    修法：模板用占位符，本函数注入 dataset 实际列名。

    返回新 Template 对象（不修改原对象），steps 已替换占位符。
    """
    new_steps = [
        Step(op=s.op, args=_resolve_args(s.args, dataset)) for s in template.steps
    ]
    # 返回新 Template（保留原元信息）
    return Template(
        template_id=template.template_id,
        intent=template.intent,
        schema_fingerprint=template.schema_fingerprint,
        steps=new_steps,
        reviewer_enabled=template.reviewer_enabled,
        fallback_strategy=template.fallback_strategy,
        created_at=template.created_at,
        promoted_from_plan_id=template.promoted_from_plan_id,
        stability=template.stability,
        confidence=template.confidence,
    )


@dataclass
class FullRunResult(RunResult):
    """run() 返回结果，扩展 RunResult 含路由与 LLM 元信息"""
    matched_template_id: str | None = None
    matched_plan_id: str | None = None
    llm_calls: int = 0
    duration_ms: int = 0

    def to_run_record(self, fp: str, intent: str) -> RunRecord:
        return RunRecord(
            schema_fingerprint=fp,
            intent=intent,
            route=self.route,
            success=all(s["ok"] for s in self.log),
            matched_template_id=self.matched_template_id,
            matched_plan_id=self.matched_plan_id,
            steps=self.log,
            llm_calls=self.llm_calls,
            duration_ms=self.duration_ms,
        )


def run(
    question: str,
    dataset: Dataset,
    library: FlowLibrary | None = None,
    generator: AIPlanGenerator | None = None,
    reviewer: AIReviewer | None = None,
    enable_review: bool = True,
    progress: ProgressCallback | None = None,
    on_review_delta: Callable[[str], None] | None = None,
) -> FullRunResult:
    """端到端运行（spec §6.2 / §7.5）

    Args:
        question: 用户问题
        dataset: Dataset
        library: Flow Library 实例（None 用默认）
        generator: fallback 时的 Plan 生成器（None 用 FakePlanGenerator）
        reviewer: AI Reviewer（None 用 FakeReviewer）
        enable_review: 全局开关；plan.reviewer_enabled 也需 True 才调
        progress: 可选进度回调 progress(stage, current, total, detail)。
            阶段序列（真实 LLM fallback 路径完整版）：
              route(0/1) → llm(0/1, detail=模型名) → execute(1..N/N) → review(0/1) → promote(0/1)
            A/B 轨命中时无 llm 阶段。回调抛异常被吞掉，不影响分析主流程。
        on_review_delta: 可选流式回调（G18）——reviewer 每产出一段文本调一次，
            用于 web 端流式渲染 AI 思考过程。reviewer 不支持流式时
            全文一次性回调（base 默认回落），行为向后兼容。

    Returns:
        FullRunResult
    """
    if library is None:
        library = FlowLibrary()
    if generator is None:
        generator = FakePlanGenerator()
    if reviewer is None:
        reviewer = FakeReviewer()

    def _p(stage: str, current: int = 0, total: int = 1,
           detail: str | None = None) -> None:
        """安全转发进度回调（渲染异常不反噬分析）"""
        if progress is None:
            return
        try:
            progress(stage, current, total, detail)
        except Exception:
            pass

    t0 = time.perf_counter()
    _p("route")
    r = route(question, dataset, library)
    llm_calls = 0
    matched_template_id: str | None = None
    matched_plan_id: str | None = None

    # 取 Plan
    if r.kind == "A" and r.template is not None:
        # 外部 AI P1 修复：模板变量化——命中后注入 dataset 实际列名
        resolved_tpl = resolve_template_variables(r.template, dataset)
        plan = Plan.from_dict(resolved_tpl.to_plan_dict())
        matched_template_id = r.template.template_id
        _p("template", detail=f"命中模板 {matched_template_id}")
    elif r.kind == "B" and r.plan is not None:
        plan = r.plan
        matched_plan_id = plan.plan_id
        _p("plan", detail=f"命中 Plan {matched_plan_id}")
    else:
        # fallback：router 已判 A/B 都未命中（router L67/L72 调过 match_template/match_plan）
        # 生成新 Plan 并沉淀，下次同 (fp, intent) 走 B 轨命中
        # （spec §7.1 B 轨：fallback 生成的 Plan save 后下次复用）
        # 关羽 P2-3 修复：删除原 L99-102 的 match_plan 复用分支（死代码——
        # router 已调 match_plan 判未命中，这里再调必然返回 None）
        _p("llm", detail="调用模型中（通常 5-30 秒，请稍候）")
        plan = generator.generate(question, dataset, intent=r.intent)
        llm_calls = 1
        library.save_plan(plan)
        matched_plan_id = plan.plan_id
        _p("llm", 1, 1, f"已生成 {plan.plan_id}")

    # 执行
    inner = execute(plan, dataset, progress=progress)

    # Reviewer（plan.reviewer_enabled 且 enable_review 同时为 True）
    # G18：on_review_delta 存在时走流式通道（不支持流式的 reviewer 全文一次回调）
    review_text: str | None = None
    if enable_review and plan.reviewer_enabled:
        _p("review", detail="AI 分析中（流式输出）")
        if on_review_delta is not None:
            review_text = reviewer.review_stream(
                dataset, inner.charts, inner.log, on_delta=on_review_delta,
            )
        else:
            review_text = reviewer.review(dataset, inner.charts, inner.log)
        _p("review", 1, 1, "完成")

    duration_ms = int((time.perf_counter() - t0) * 1000)

    result = FullRunResult(
        df=inner.df,
        charts=inner.charts,
        log=inner.log,
        route=r.kind,
        review=review_text,
        plan_id=plan.plan_id,
        matched_template_id=matched_template_id,
        matched_plan_id=matched_plan_id,
        llm_calls=llm_calls,
        duration_ms=duration_ms,
    )

    # 沉淀 RunRecord
    run_rec = result.to_run_record(dataset.schema_fingerprint, r.intent or "")
    library.save_run(run_rec)

    # 自进化检查：每次运行后检查 (fp, intent, plan_id) 是否满足晋升条件
    # （B 轨复用的 plan 也应有机会晋升，不只 fallback 路径）
    if matched_plan_id and r.intent:
        Promoter(library=library).promote(
            dataset.schema_fingerprint, r.intent, matched_plan_id,
        )

    return result
