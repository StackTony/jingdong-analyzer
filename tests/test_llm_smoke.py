"""F002 P3+ 真实 LLM 端到端冒烟测试（需 CSI_API_KEY 环境变量）

**手动运行**，不入 CI（避免网络依赖 + 速率限制 + 推理模型慢）：

    CSI_API_KEY=sk-xxx python -m pytest tests/test_llm_smoke.py -v

验证：
1. csi provider 连通性
2. LLMPlanGenerator 生成有效 Plan（args 字段名对齐 op_spec）
3. 生成的 Plan 能被 executor 跑通
4. LLMReviewer 输出三段式报告
"""
from __future__ import annotations

import os

import pandas as pd
import pytest

from clowder_analytics.adapters.base import Dataset, compute_fingerprint
from clowder_analytics.ai.llm_plan_generator import LLMPlanGenerator
from clowder_analytics.ai.llm_provider import load_provider
from clowder_analytics.ai.llm_reviewer import LLMReviewer
from clowder_analytics.orchestrator.executor import execute
from clowder_analytics.orchestrator.plan import Plan, Step


def _has_api_key() -> bool:
    return bool(os.environ.get("CSI_API_KEY"))


@pytest.fixture
def csi_provider():
    if not _has_api_key():
        pytest.skip("CSI_API_KEY 未设，跳过真实 LLM 冒烟测试")
    return load_provider("csi")


@pytest.fixture
def sample_dataset():
    df = pd.DataFrame({
        "brand": ["小米", "华为", "OPPO", "vivo", "联想"],
        "sales": [100, 200, 250, 180, 50],
    })
    return Dataset(df=df, schema_fingerprint=compute_fingerprint(df))


def test_csi_provider_connectivity(csi_provider):
    """csi provider 连通性"""
    msg = csi_provider.chat(
        messages=[
            {"role": "system", "content": "你是助手"},
            {"role": "user", "content": "请回复 PONG"},
        ],
        temperature=0.0, max_tokens=1000,
    )
    # GLM-5.2 推理模型可能消耗 token 在 reasoning，content 可空
    # 但只要不抛异常就算连通
    assert isinstance(msg, str)


def test_llm_plan_generator_real(csi_provider, sample_dataset):
    """LLM 生成 Plan + args 对齐 op_spec + 能执行"""
    gen = LLMPlanGenerator(provider=csi_provider)
    plan = gen.generate("Top30 品牌销量", sample_dataset, intent="TopN 趋势分析")

    assert plan.intent == "TopN 趋势分析"
    assert plan.schema_fingerprint == sample_dataset.schema_fingerprint
    assert len(plan.steps) >= 1
    # 至少有一个 model op
    assert any(s.op.startswith("model.") for s in plan.steps)

    # 验证 args 字段名对齐 op_spec（关键：避免 LLM 自创字段名）
    for step in plan.steps:
        if step.op == "model.topn":
            assert "value_col" in step.args
            assert "group_by" in step.args
            assert "n" in step.args
        elif step.op == "model.aggregate":
            assert "group_by" in step.args
            assert "agg" in step.args
        elif step.op == "clean.normalize_text":
            assert "columns" in step.args
            assert "ops" in step.args

    # 执行
    result = execute(plan, sample_dataset)
    # 至少 50% 步骤成功（LLM 偶尔生成不完美 args，不要求 100%）
    ok_rate = sum(1 for s in result.log if s.get("ok")) / len(result.log)
    assert ok_rate >= 0.5, f"Plan 执行成功率过低: {ok_rate:.0%}"


def test_llm_reviewer_real(csi_provider, sample_dataset):
    """LLM Reviewer 输出三段式报告"""
    # 用固定 Plan 避免 Plan 生成随机性
    plan = Plan(
        plan_id="review-smoke", intent="异常归因",
        schema_fingerprint=sample_dataset.schema_fingerprint,
        steps=[Step(op="model.anomaly_attribution", args={
            "value_col": "sales", "group_by": ["brand"], "baseline": "mean",
        })],
    )
    result = execute(plan, sample_dataset)

    reviewer = LLMReviewer(provider=csi_provider)
    report = reviewer.review(sample_dataset, charts=result.charts, run_log=result.log)

    # 三段式结构
    assert "## 异常解释" in report
    assert "## 趋势点睛" in report
    assert "## 建议下一步" in report
    # 报告长度合理（不是空）
    assert len(report) > 100


def test_run_with_real_llm(csi_provider, sample_dataset):
    """端到端：route + LLM generate + execute + LLM review + 沉淀"""
    from clowder_analytics.flow_library.store import FlowLibrary
    from clowder_analytics.orchestrator.run import run
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        lib = FlowLibrary(base_dir=td)
        # 复制冷启动模板，避免命中冷启动走 A 轨
        # 这里想测 fallback → 真实 LLM，所以临时库故意不放模板
        result = run(
            question="Top30 品牌销量",
            dataset=sample_dataset,
            library=lib,
            generator=LLMPlanGenerator(provider=csi_provider),
            reviewer=LLMReviewer(provider=csi_provider),
            enable_review=True,
        )
        assert result.route == "fallback"
        assert result.llm_calls >= 1  # 至少调了一次 LLM（generator）
        assert len(result.log) >= 1
        # Reviewer 报告
        assert result.review is not None
        assert "## 异常解释" in result.review or "## 趋势点睛" in result.review
