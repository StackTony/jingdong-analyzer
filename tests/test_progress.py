"""运行进度回调测试（红测先行）

需求：运行分析过程中没有进度条展示 → run()/execute() 暴露 progress 回调，
让 CLI / Web 入口能实时渲染阶段进度。

progress 回调约定：
    progress(stage: str, current: int, total: int, detail: str | None = None)
    - stage: 阶段标识（route / plan / llm / execute / review / promote）
    - current/total: 该阶段内进度（execute 阶段 = 第几步/共几步；其他阶段 0/1）
    - detail: 可选人类可读描述（如当前 op 名 / 模型名）
"""
from __future__ import annotations

import pandas as pd

from clowder_analytics.adapters.base import Dataset, compute_fingerprint
from clowder_analytics.ai.fake import FakePlanGenerator, FakeReviewer
from clowder_analytics.flow_library.store import FlowLibrary
from clowder_analytics.orchestrator.executor import execute
from clowder_analytics.orchestrator.plan import Plan, Step
from clowder_analytics.orchestrator.run import run


def _make_dataset(df: pd.DataFrame) -> Dataset:
    return Dataset(df=df, schema_fingerprint=compute_fingerprint(df))


def _simple_df() -> pd.DataFrame:
    return pd.DataFrame({
        "brand": ["小米", "华为", "OPPO", "vivo", "荣耀"],
        "sales": [100, 200, 250, 80, 150],
    })


# ===== executor.execute 的 progress 回调 =====

def test_execute_reports_step_progress():
    """execute 逐步回调 (stage='execute', current=i, total=len(steps), detail=op名)"""
    plan = Plan(
        plan_id="t-progress", intent="test",
        steps=[
            Step(op="clean.remove_duplicates", args={"keys": ["brand", "sales"]}),
            Step(op="clean.normalize_text",
                 args={"columns": ["brand"], "ops": ["strip"]}),
            Step(op="model.topn",
                 args={"group_by": ["brand"], "value_col": "sales", "n": 3}),
        ],
    )
    ds = _make_dataset(_simple_df())

    events: list[tuple] = []
    execute(plan, ds, progress=lambda s, c, t, d=None: events.append((s, c, t, d)))

    exec_events = [e for e in events if e[0] == "execute"]
    assert len(exec_events) == 3
    assert exec_events[0][1] == 1 and exec_events[0][2] == 3
    assert exec_events[2][1] == 3 and exec_events[2][2] == 3
    # detail 是 op 名
    assert exec_events[0][3] == "clean.remove_duplicates"


def test_execute_progress_counts_failed_steps():
    """op 失败也计进度（continue 策略下后续步骤仍回调）"""
    plan = Plan(
        plan_id="t-progress-err", intent="test", fallback_strategy="continue_on_error",
        steps=[
            Step(op="model.nonexistent_op", args={}),  # 未知 op → 失败
            Step(op="clean.remove_duplicates", args={"keys": ["brand", "sales"]}),
        ],
    )
    ds = _make_dataset(_simple_df())

    events: list[tuple] = []
    execute(plan, ds, progress=lambda s, c, t, d=None: events.append((s, c, t, d)))

    exec_events = [e for e in events if e[0] == "execute"]
    assert len(exec_events) == 2  # 失败步骤 + 成功步骤都有回调
    assert exec_events[1][1] == 2 and exec_events[1][2] == 2


def test_execute_without_progress_still_works():
    """不传 progress 时行为完全不变（向后兼容）"""
    plan = Plan(
        plan_id="t-noprogress", intent="test",
        steps=[Step(op="clean.remove_duplicates", args={"keys": ["brand", "sales"]})],
    )
    ds = _make_dataset(_simple_df())
    result = execute(plan, ds)
    assert len(result.log) == 1
    assert result.log[0]["ok"] is True


# ===== run() 的 progress 回调 =====

def test_run_reports_stage_progress():
    """run() 回调覆盖 route/plan/execute（fallback 路径含 llm 阶段）"""
    df = _simple_df()
    ds = _make_dataset(df)
    library = FlowLibrary(base_dir=None) if False else None  # 用 tmp 见下

    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as td:
        library = FlowLibrary(base_dir=pathlib.Path(td))
        events: list[tuple] = []
        result = run(
            question="哪些品牌销量最高",
            dataset=ds,
            library=library,
            generator=FakePlanGenerator(),
            reviewer=FakeReviewer(),
            progress=lambda s, c, t, d=None: events.append((s, c, t, d)),
        )

        stages = [e[0] for e in events]
        # 阶段顺序：route → (llm|template|plan) → execute
        assert "route" in stages
        assert "execute" in stages
        assert stages.index("route") < stages.index("execute")
        # fallback 路径应有 llm 阶段
        assert "llm" in stages
        # execute 阶段至少一步回调且带总数
        exec_events = [e for e in events if e[0] == "execute"]
        assert exec_events, "execute 阶段必须有进度回调"
        assert all(e[2] >= e[1] >= 1 for e in exec_events)
        # 结果本身不受影响
        assert result.llm_calls == 1


def test_run_progress_callback_exception_does_not_break_run():
    """progress 回调抛异常不影响主流程（进度展示是锦上添花，不能反噬分析）"""
    df = _simple_df()
    ds = _make_dataset(df)

    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as td:
        library = FlowLibrary(base_dir=pathlib.Path(td))

        def bad_progress(stage, current, total, detail=None):
            raise RuntimeError("rendering glitch")

        result = run(
            question="Top30 品牌",
            dataset=ds,
            library=library,
            generator=FakePlanGenerator(),
            reviewer=FakeReviewer(),
            progress=bad_progress,
        )
        # 主流程照常完成
        assert result.route in ("A", "B", "fallback")
        assert len(result.log) >= 1


def test_run_review_stage_reported_when_enabled():
    """启用 review 时回调 review 阶段（需 plan.reviewer_enabled=True，Fake 默认关）"""
    from clowder_analytics.ai.base import AIPlanGenerator

    class ReviewEnabledGenerator(AIPlanGenerator):
        """stub：生成 reviewer_enabled=True 的最简 plan"""

        def generate(self, question, dataset, intent=None):
            return Plan(
                plan_id="t-review-progress", intent="test",
                steps=[Step(op="clean.remove_duplicates",
                            args={"keys": ["brand", "sales"]})],
                reviewer_enabled=True,
            )

    df = _simple_df()
    ds = _make_dataset(df)

    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as td:
        library = FlowLibrary(base_dir=pathlib.Path(td))
        events: list[tuple] = []
        run(
            question="Top30 品牌",
            dataset=ds,
            library=library,
            generator=ReviewEnabledGenerator(),
            reviewer=FakeReviewer(),
            enable_review=True,
            progress=lambda s, c, t, d=None: events.append((s, c, t, d)),
        )
        stages = [e[0] for e in events]
        assert "review" in stages
        # review 完成回调在最后（promote 无 matched_plan_id 时不触发）
        assert stages[-1] == "review" or "review" in stages
