"""F002 P3+ 真实 LLM Provider / Generator / Reviewer 红测

测试策略：
1. LLMProvider 抽象不可实例化
2. OpenAICompatibleProvider 接口正确（用 mock SDK 验证调用参数）
3. LLMPlanGenerator 用 mock provider 测 prompt 构造 + JSON 解析 + 重试
4. LLMReviewer 用 mock provider 测 prompt 构造
5. _parse_json / _validate_plan 容错

不调真实 endpoint（避免网络依赖 + 速率限制）。
真实端到端冒烟见 tests/test_llm_smoke.py（手动运行，需 CSI_API_KEY）。
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pandas as pd
import pytest

from clowder_analytics.adapters.base import Dataset, compute_fingerprint
from clowder_analytics.ai.base import AIPlanGenerator, AIReviewer
from clowder_analytics.ai.llm_plan_generator import LLMPlanGenerator
from clowder_analytics.ai.llm_provider import (
    LLMProvider,
    OpenAICompatibleProvider,
    ProviderConfig,
    load_provider,
)
from clowder_analytics.ai.llm_reviewer import LLMReviewer
from clowder_analytics.orchestrator.plan import Plan


def _make_dataset(df: pd.DataFrame) -> Dataset:
    return Dataset(df=df, schema_fingerprint=compute_fingerprint(df))


# ===== LLMProvider 抽象 =====

def test_llm_provider_abstract_cannot_instantiate():
    with pytest.raises(TypeError):
        LLMProvider()


def test_openai_provider_interface():
    """OpenAICompatibleProvider 接口正确"""
    config = ProviderConfig(
        name="test", base_url="http://localhost/v1/",
        api_key="sk-test", model="GLM-5.2",
    )
    p = OpenAICompatibleProvider(config)
    assert p.config.model == "GLM-5.2"
    assert p.config.base_url == "http://localhost/v1/"


def test_openai_provider_chat_requires_openai_sdk(monkeypatch):
    """openai SDK 未装时抛 NotImplementedError"""
    config = ProviderConfig(
        name="test", base_url="http://localhost/v1/",
        api_key="sk-test", model="GLM-5.2",
    )
    p = OpenAICompatibleProvider(config)

    # 模拟 openai 模块不存在
    import sys
    monkeypatch.setitem(sys.modules, "openai", None)
    with pytest.raises(NotImplementedError) as e:
        p.chat(messages=[{"role": "user", "content": "hi"}])
    assert "openai" in str(e.value).lower()


def test_openai_provider_chat_calls_sdk():
    """正常调用时构造 OpenAI client 并调 chat.completions.create"""
    config = ProviderConfig(
        name="test", base_url="http://localhost/v1/",
        api_key="sk-test", model="GLM-5.2",
    )
    p = OpenAICompatibleProvider(config)

    # Mock openai SDK
    fake_client = MagicMock()
    fake_choice = MagicMock()
    fake_choice.message.content = "hello from LLM"
    fake_resp = MagicMock()
    fake_resp.choices = [fake_choice]
    fake_client.chat.completions.create.return_value = fake_resp

    with patch("openai.OpenAI", return_value=fake_client):
        result = p.chat(
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.5, max_tokens=100,
        )
    assert result == "hello from LLM"
    # 验证调用参数
    create_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert create_kwargs["model"] == "GLM-5.2"
    assert create_kwargs["temperature"] == 0.5
    assert create_kwargs["max_tokens"] == 100
    assert create_kwargs["messages"] == [{"role": "user", "content": "hi"}]


def test_openai_provider_chat_with_response_format():
    """response_format 参数透传"""
    config = ProviderConfig(name="t", base_url="x", api_key="y", model="m")
    p = OpenAICompatibleProvider(config)
    fake_client = MagicMock()
    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock()]
    fake_resp.choices[0].message.content = "{}"
    fake_client.chat.completions.create.return_value = fake_resp
    with patch("openai.OpenAI", return_value=fake_client):
        p.chat(
            messages=[{"role": "user", "content": "x"}],
            response_format={"type": "json_object"},
        )
    create_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert create_kwargs["response_format"] == {"type": "json_object"}


# ===== load_provider 配置加载 =====

# G14 后生产 yaml 无 csi provider（铲屎官改为 euler-y 直填 key），
# 这些测试改用隔离的 mock 配置，不绑死生产 yaml 内容
_ENV_STYLE_YAML = """
default_provider: testprov

providers:
  testprov:
    name: test provider
    base_url: http://localhost:8080/v1/
    api_key_env: TESTPROV_API_KEY
    model: GLM-5.2
    protocol: openai
    temperature: 0.3
    max_tokens: 4000
    timeout_seconds: 120
"""


@pytest.fixture
def env_style_yaml(tmp_path, monkeypatch):
    """写 env 风格配置到临时文件，patch 配置路径"""
    cfg = tmp_path / "env_style.yaml"
    cfg.write_text(_ENV_STYLE_YAML, encoding="utf-8")
    import clowder_analytics.ai.llm_provider as mod
    monkeypatch.setattr(mod, "_CONFIG_PATH", cfg)
    monkeypatch.setattr(mod, "_CONFIG_CACHE", None)
    return cfg


def test_load_provider_unknown_raises(env_style_yaml):
    with pytest.raises(KeyError):
        load_provider("nonexistent_provider")


def test_load_provider_missing_api_key_raises(env_style_yaml, monkeypatch):
    """apiKey 环境变量未设时报错"""
    monkeypatch.delenv("TESTPROV_API_KEY", raising=False)
    with pytest.raises(RuntimeError) as e:
        load_provider("testprov")
    assert "TESTPROV_API_KEY" in str(e.value)


def test_load_provider_with_api_key(env_style_yaml, monkeypatch):
    """apiKey 环境变量设了能加载（不调真实 SDK）"""
    monkeypatch.setenv("TESTPROV_API_KEY", "sk-test")
    p = load_provider("testprov")
    assert isinstance(p, OpenAICompatibleProvider)
    assert p.config.api_key == "sk-test"
    assert p.config.model == "GLM-5.2"


def test_load_provider_default_is_configured(env_style_yaml, monkeypatch):
    """不传 name 时取 default_provider"""
    monkeypatch.setenv("TESTPROV_API_KEY", "sk-test")
    p = load_provider()
    assert p.config.name == "testprov"


# ===== 多 provider 多 model 配置（G13 通用 LLM 对接）=====

# 新 yaml 格式：providers.<name>.models.<model_id> 多 model 结构
_MULTI_PROVIDER_YAML = """
default_provider: glm

providers:
  glm:
    name: Zhipu GLM
    base_url: http://76.53.227.83:4000/v1/
    api_key_env: GLM_API_KEY
    protocol: openai
    timeout_seconds: 120
    default_model: glm-5.2
    models:
      glm-5.2:
        name: GLM-5.2
        max_tokens: 4000
        temperature: 0.3

  euler-y:
    name: Huawei Euler-Y
    base_url: https://aigateway.csitool.rnd.huawei.com/v1/
    api_key_env: EULER_Y_API_KEY
    protocol: openai
    timeout_seconds: 120
    models:
      Qwen3.5-122B-A10B:
        name: Qwen3.5-122B-A10B
        max_tokens: 4000
      Deepseek-V4-Flash:
        name: Deepseek-V4-Flash
      MiniMax-M2.7:
        name: MiniMax-2.7
"""


@pytest.fixture
def multi_provider_yaml(tmp_path, monkeypatch):
    """写新格式 yaml 到临时文件，patch 配置路径"""
    cfg = tmp_path / "ai_providers.yaml"
    cfg.write_text(_MULTI_PROVIDER_YAML, encoding="utf-8")
    import clowder_analytics.ai.llm_provider as mod
    monkeypatch.setattr(mod, "_CONFIG_PATH", cfg)
    monkeypatch.setattr(mod, "_CONFIG_CACHE", None)
    return cfg


def test_load_provider_multi_model_selects_specified_model(multi_provider_yaml, monkeypatch):
    """load_provider(name, model=...) 选 provider 下指定 model"""
    monkeypatch.setenv("GLM_API_KEY", "sk-glm-test")
    p = load_provider("glm", model="glm-5.2")
    assert p.config.model == "glm-5.2"
    assert p.config.max_tokens == 4000


def test_load_provider_multi_model_different_model_in_same_provider(multi_provider_yaml, monkeypatch):
    """同一 provider 下选不同 model"""
    monkeypatch.setenv("EULER_Y_API_KEY", "sk-euler-test")
    p = load_provider("euler-y", model="Deepseek-V4-Flash")
    assert p.config.model == "Deepseek-V4-Flash"
    # Deepseek-V4-Flash 没写 max_tokens，用默认
    assert p.config.max_tokens == 2000


def test_load_provider_default_model_when_not_specified(multi_provider_yaml, monkeypatch):
    """不传 model 时取 default_model 字段"""
    monkeypatch.setenv("GLM_API_KEY", "sk-glm-test")
    p = load_provider("glm")
    assert p.config.model == "glm-5.2"


def test_load_provider_first_model_when_no_default(multi_provider_yaml, monkeypatch):
    """没 default_model 字段时取 models 第一个（euler-y 没 default_model）"""
    monkeypatch.setenv("EULER_Y_API_KEY", "sk-euler-test")
    p = load_provider("euler-y")
    # models dict 顺序：Qwen3.5-122B-A10B 在前
    assert p.config.model == "Qwen3.5-122B-A10B"


def test_load_provider_unknown_model_raises(multi_provider_yaml, monkeypatch):
    """provider 存在但 model 不存在时报错"""
    monkeypatch.setenv("GLM_API_KEY", "sk-glm-test")
    with pytest.raises(KeyError) as e:
        load_provider("glm", model="nonexistent-model")
    assert "nonexistent-model" in str(e.value)


def test_load_provider_backcompat_old_single_model_format(monkeypatch, tmp_path):
    """向后兼容：老格式 providers.csi.model 顶层单 model 仍工作"""
    old_yaml = """
default_provider: csi
providers:
  csi:
    name: csi.ai
    base_url: http://localhost:8080/v1/
    api_key_env: CSI_API_KEY
    model: GLM-5.2
    protocol: openai
    temperature: 0.3
    max_tokens: 4000
    timeout_seconds: 120
"""
    cfg = tmp_path / "old.yaml"
    cfg.write_text(old_yaml, encoding="utf-8")
    import clowder_analytics.ai.llm_provider as mod
    monkeypatch.setattr(mod, "_CONFIG_PATH", cfg)
    monkeypatch.setattr(mod, "_CONFIG_CACHE", None)
    monkeypatch.setenv("CSI_API_KEY", "sk-test")
    p = load_provider("csi")
    assert p.config.model == "GLM-5.2"
    assert p.config.max_tokens == 4000


# ===== LLMPlanGenerator（用 mock provider） =====

class MockProvider(LLMProvider):
    """确定性 mock，按预设返回内容"""
    def __init__(self, responses: list[str]):
        self.responses = responses
        self.calls = 0
        self.last_messages: list[dict] = []

    def chat(self, messages, temperature=0.3, max_tokens=2000, response_format=None):
        self.last_messages = messages
        r = self.responses[self.calls]
        self.calls += 1
        return r


def test_llm_plan_generator_returns_valid_plan():
    """LLM 返回有效 JSON → 解析为 Plan"""
    df = pd.DataFrame({"brand": ["a", "b", "c"], "sales": [10, 20, 30]})
    ds = _make_dataset(df)
    mock = MockProvider([json.dumps({
        "plan_id": "llm-001",
        "intent": "TopN 趋势分析",
        "schema_fingerprint": ds.schema_fingerprint,
        "steps": [
            {"op": "model.topn", "args": {"group_by": ["brand"], "value_col": "sales", "n": 30, "rank_by": "value"}},
        ],
        "reviewer_enabled": True,
        "fallback_strategy": "abort_on_first_error",
    })])
    gen = LLMPlanGenerator(provider=mock)
    plan = gen.generate("Top30 品牌", ds, intent="TopN 趋势分析")
    assert isinstance(plan, Plan)
    assert plan.plan_id == "llm-001"
    assert plan.intent == "TopN 趋势分析"
    assert plan.schema_fingerprint == ds.schema_fingerprint
    assert len(plan.steps) == 1
    assert plan.steps[0].op == "model.topn"


def test_llm_plan_generator_prompt_contains_question_and_schema():
    """user prompt 含问题 + schema 指纹 + op 清单（含 args schema）"""
    df = pd.DataFrame({"brand": ["a"], "sales": [10]})
    ds = _make_dataset(df)
    mock = MockProvider([json.dumps({
        "plan_id": "p1", "intent": "X", "schema_fingerprint": ds.schema_fingerprint,
        "steps": [{"op": "model.topn", "args": {}}],
    })])
    gen = LLMPlanGenerator(provider=mock)
    gen.generate("我的问题XYZ", ds, intent="X")
    user_msg = mock.last_messages[1]["content"]
    assert "我的问题XYZ" in user_msg
    assert ds.schema_fingerprint in user_msg
    assert "model.topn" in user_msg  # op 清单
    assert "brand" in user_msg  # 列信息
    assert "sales" in user_msg
    # args schema 注入
    assert "args:" in user_msg
    assert "required" in user_msg
    assert "group_by" in user_msg  # 具体字段名


def test_op_specs_format_for_llm_contains_all_ops():
    """op spec 格式化输出含全部 12 个 op + args schema"""
    from clowder_analytics.atomic.op_spec import OP_SPECS, format_op_specs_for_llm
    output = format_op_specs_for_llm()
    assert "clean.remove_duplicates" in output
    assert "model.topn" in output
    assert "description:" in output
    assert "args:" in output
    # 至少 12 个 op（6 clean + 6 model）
    assert len(OP_SPECS) >= 12


def test_op_specs_field_names_match_real_signatures():
    """op spec 里的 args 字段名必须与真实 op 函数签名一致
    （避免 LLM 用错字段名如 fields vs columns）"""
    from clowder_analytics.atomic.op_spec import OP_SPECS
    # 抽样验证几个关键 op
    assert set(OP_SPECS["clean.normalize_text"]["args"].keys()) == {"columns", "ops"}
    assert set(OP_SPECS["model.aggregate"]["args"].keys()) == {"group_by", "agg"}
    assert set(OP_SPECS["model.topn"]["args"].keys()) == {"group_by", "value_col", "n", "rank_by"}


def test_llm_plan_generator_retries_on_invalid_json():
    """LLM 输出非 JSON → 重试一次"""
    df = pd.DataFrame({"brand": ["a"], "sales": [10]})
    ds = _make_dataset(df)
    mock = MockProvider([
        "这不是 JSON",  # 第一次失败
        json.dumps({  # 第二次成功
            "plan_id": "p2", "intent": "X", "schema_fingerprint": ds.schema_fingerprint,
            "steps": [{"op": "model.topn", "args": {}}],
        }),
    ])
    gen = LLMPlanGenerator(provider=mock)
    plan = gen.generate("问题", ds, intent="X")
    assert plan.plan_id == "p2"
    assert mock.calls == 2


def test_llm_plan_generator_fails_after_max_retries():
    """连续 2 次失败抛 RuntimeError"""
    df = pd.DataFrame({"brand": ["a"], "sales": [10]})
    ds = _make_dataset(df)
    mock = MockProvider(["not json 1", "not json 2"])
    gen = LLMPlanGenerator(provider=mock)
    with pytest.raises(RuntimeError) as e:
        gen.generate("问题", ds, intent="X")
    assert "JSON" in str(e.value) or "重试" in str(e.value) or "2" in str(e.value)


def test_llm_plan_generator_strips_markdown_fence():
    """LLM 输出被 ```json 包裹时能解析"""
    df = pd.DataFrame({"brand": ["a"], "sales": [10]})
    ds = _make_dataset(df)
    fenced = """```json
{"plan_id": "p3", "intent": "X", "schema_fingerprint": "%s", "steps": [{"op": "model.topn", "args": {}}]}
```""" % ds.schema_fingerprint
    mock = MockProvider([fenced])
    gen = LLMPlanGenerator(provider=mock)
    plan = gen.generate("问题", ds, intent="X")
    assert plan.plan_id == "p3"


def test_llm_plan_generator_extracts_json_from_surrounding_text():
    """LLM 输出前后有非 JSON 文字时能提取"""
    df = pd.DataFrame({"brand": ["a"], "sales": [10]})
    ds = _make_dataset(df)
    content = """好的，这是 Plan：
{"plan_id": "p4", "intent": "X", "schema_fingerprint": "%s", "steps": [{"op": "model.topn", "args": {}}]}
希望对你有帮助。""" % ds.schema_fingerprint
    mock = MockProvider([content])
    gen = LLMPlanGenerator(provider=mock)
    plan = gen.generate("问题", ds, intent="X")
    assert plan.plan_id == "p4"


def test_llm_plan_generator_validates_missing_fields():
    """Plan 缺字段 → 重试"""
    df = pd.DataFrame({"brand": ["a"], "sales": [10]})
    ds = _make_dataset(df)
    mock = MockProvider([
        json.dumps({"plan_id": "x"}),  # 缺 intent/steps
        json.dumps({  # 补全
            "plan_id": "p5", "intent": "X", "schema_fingerprint": ds.schema_fingerprint,
            "steps": [{"op": "model.topn", "args": {}}],
        }),
    ])
    gen = LLMPlanGenerator(provider=mock)
    plan = gen.generate("问题", ds, intent="X")
    assert plan.plan_id == "p5"
    assert mock.calls == 2


def test_llm_plan_generator_generated_plan_can_be_executed():
    """生成的 Plan 能被 executor 跑通"""
    from clowder_analytics.orchestrator.executor import execute
    df = pd.DataFrame({"brand": ["a", "b", "c"], "sales": [10, 20, 30]})
    ds = _make_dataset(df)
    mock = MockProvider([json.dumps({
        "plan_id": "p_exec",
        "intent": "TopN 趋势分析",
        "schema_fingerprint": ds.schema_fingerprint,
        "steps": [
            {"op": "model.topn", "args": {"group_by": ["brand"], "value_col": "sales", "n": 3, "rank_by": "value"}},
        ],
    })])
    gen = LLMPlanGenerator(provider=mock)
    plan = gen.generate("Top10", ds, intent="TopN 趋势分析")
    result = execute(plan, ds)
    assert all(s["ok"] for s in result.log)


# ===== LLMReviewer（用 mock provider） =====

def test_llm_reviewer_returns_provider_output():
    """Reviewer 返回 LLM 输出"""
    df = pd.DataFrame({"brand": ["a", "b", "c"], "sales": [100, 200, 50]})
    ds = _make_dataset(df)
    mock = MockProvider(["## 异常解释\n## 趋势点睛\n## 建议下一步"])
    reviewer = LLMReviewer(provider=mock)
    report = reviewer.review(ds, charts=[], run_log=[])
    assert "## 异常解释" in report


def test_llm_reviewer_prompt_contains_data_summary():
    """user prompt 含数据摘要 + 图表描述 + 执行日志"""
    df = pd.DataFrame({"brand": ["a", "b"], "sales": [10, 20]})
    ds = _make_dataset(df)
    mock = MockProvider(["报告"])
    reviewer = LLMReviewer(provider=mock)
    reviewer.review(ds, charts=[], run_log=[{"step": "x", "ok": True}])
    user_msg = mock.last_messages[1]["content"]
    assert "brand" in user_msg
    assert "sales" in user_msg
    assert "mean=" in user_msg or "无数值列" in user_msg


def test_llm_reviewer_prompt_includes_charts():
    """prompt 含图表描述"""
    from clowder_analytics.atomic.spec import ChartSpec
    df = pd.DataFrame({"brand": ["a"], "sales": [10]})
    ds = _make_dataset(df)
    mock = MockProvider(["报告"])
    reviewer = LLMReviewer(provider=mock)
    chart = ChartSpec(type="bar", data=pd.DataFrame(), title="TopN", x="brand", y="sales")
    reviewer.review(ds, charts=[chart], run_log=[])
    user_msg = mock.last_messages[1]["content"]
    assert "bar" in user_msg
    assert "TopN" in user_msg


def test_llm_reviewer_prompt_includes_run_log():
    """prompt 含执行日志"""
    df = pd.DataFrame({"brand": ["a"], "sales": [10]})
    ds = _make_dataset(df)
    mock = MockProvider(["报告"])
    reviewer = LLMReviewer(provider=mock)
    log = [
        {"step": "clean.x", "ok": True},
        {"step": "model.y", "ok": False, "err": "boom"},
    ]
    reviewer.review(ds, charts=[], run_log=log)
    user_msg = mock.last_messages[1]["content"]
    assert "clean.x" in user_msg
    assert "model.y" in user_msg
    assert "OK" in user_msg or "FAIL" in user_msg


# ===== P2-1: max_tokens 应读 ProviderConfig，不硬编码 2000 =====

def test_llm_plan_generator_max_tokens_reads_provider_config():
    """LLMPlanGenerator 调 provider.chat 时 max_tokens 应从 provider.config.max_tokens 读

    关羽 P2-1：llm_plan_generator.py:124 硬编码 max_tokens=2000 覆盖 yaml 的 4000。
    修法：用 self.provider.config.max_tokens 代替硬编码。
    """
    from unittest.mock import MagicMock
    from clowder_analytics.ai.llm_provider import ProviderConfig

    df = pd.DataFrame({"brand": ["a"], "sales": [10]})
    ds = _make_dataset(df)

    # 构造 config.max_tokens=4000 的 mock provider
    fake_provider = MagicMock()
    fake_provider.config = ProviderConfig(
        name="csi", base_url="x", api_key="y", model="m", max_tokens=4000,
    )
    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock()]
    fake_resp.choices[0].message.content = json.dumps({
        "plan_id": "p1", "intent": "X", "schema_fingerprint": ds.schema_fingerprint,
        "steps": [{"op": "model.topn", "args": {}}],
    })
    fake_provider.chat.return_value = fake_resp.choices[0].message.content

    gen = LLMPlanGenerator(provider=fake_provider)
    gen.generate("问题", ds, intent="X")

    # 关键断言：max_tokens 应是 config 里的 4000，不是硬编码 2000
    call_kwargs = fake_provider.chat.call_args.kwargs
    assert call_kwargs["max_tokens"] == 4000, (
        f"max_tokens 应读 provider.config.max_tokens (4000)，"
        f"实际传了 {call_kwargs['max_tokens']}（硬编码 2000 bug）"
    )


# ===== P2-2: scan_and_promote 不应只扫 route=="B" =====

def test_scan_and_promote_covers_fallback_route_runs():
    """scan_and_promote 应覆盖所有 route 的 run，不只 route=="B"

    关羽 P2-2：promoter.py:159 过滤 r.route=="B"，漏 fallback 路径。
    spec §7.3 路径1"命中执行 ≥ N 次"不区分路由。
    修法：去掉 r.route == "B" 过滤。

    场景：fallback 生成的 plan，run 记 route="fallback" + matched_plan_id。
    scan_and_promote 应能扫到并触发晋升检查。
    """
    import tempfile
    from pathlib import Path
    from clowder_analytics.flow_library.store import FlowLibrary
    from clowder_analytics.flow_library.promoter import Promoter
    from clowder_analytics.flow_library.models import RunRecord
    from clowder_analytics.orchestrator.plan import Plan, Step

    df = pd.DataFrame({"brand": ["a", "b"], "sales": [10, 20]})
    fp = compute_fingerprint(df)

    with tempfile.TemporaryDirectory() as td:
        lib = FlowLibrary(base_dir=td)
        # 构造一个 plan
        plan = Plan(
            plan_id="fb-001", intent="测试", schema_fingerprint=fp,
            steps=[Step(op="model.topn", args={"group_by": ["brand"], "value_col": "sales", "n": 2, "rank_by": "value"})],
        )
        lib.save_plan(plan)

        # 记 3 次成功 run，route="fallback"（不是 "B"）
        for _ in range(3):
            lib.save_run(RunRecord(
                schema_fingerprint=fp, intent="测试",
                route="fallback", success=True,
                matched_plan_id="fb-001",
            ))

        promoter = Promoter(lib)
        # scan_and_promote 应扫到 route="fallback" 的 run 并晋升
        promoted = promoter.scan_and_promote()
        assert len(promoted) >= 1, (
            "scan_and_promote 应覆盖 route='fallback' 的 run，"
            "不只 route=='B'（关羽 P2-2）"
        )


# ===== P2-3: run.py fallback 路径死代码 =====
# 关羽 P2-3：run.py:99-102 fallback 先调 match_plan，但 router 已判 B 未命中
# （否则不走 fallback），match_plan 必然返回 None，是死代码。
#
# 删死代码是纯 refactor（外部行为不变：删前删后 fallback 都走 generator.generate，
# llm_calls=1）。TDD refactor 阶段不写新测试，靠现有 test_run_fallback_then_b_track_on_second_call
# + test_run_auto_promote_after_three_successes 等保护行为。
# 此处留注释标记，修复在 run.py L99-102。


# ===== P2-1 后续：LLMReviewer max_tokens 同模式漏网 =====

def test_llm_reviewer_max_tokens_reads_provider_config():
    """LLMReviewer 调 provider.chat 时 max_tokens 应从 provider.config.max_tokens 读

    关羽 P2-1 同模式漏网：llm_reviewer.py:40 硬编码 max_tokens=2000，
    覆盖 yaml 配置的 max_tokens（如 4000）。
    修法：用 self.provider.config.max_tokens 代替硬编码。
    """
    from unittest.mock import MagicMock
    from clowder_analytics.ai.llm_provider import ProviderConfig

    df = pd.DataFrame({"brand": ["a"], "sales": [10]})
    ds = _make_dataset(df)

    # 构造 config.max_tokens=4000 的 mock provider
    fake_provider = MagicMock()
    fake_provider.config = ProviderConfig(
        name="csi", base_url="x", api_key="y", model="m", max_tokens=4000,
    )
    fake_provider.chat.return_value = "## 异常解释\n## 趋势点睛\n## 建议下一步"

    reviewer = LLMReviewer(provider=fake_provider)
    reviewer.review(ds, charts=[], run_log=[])

    # 关键断言：max_tokens 应是 config 里的 4000，不是硬编码 2000
    call_kwargs = fake_provider.chat.call_args.kwargs
    assert call_kwargs["max_tokens"] == 4000, (
        f"max_tokens 应读 provider.config.max_tokens (4000)，"
        f"实际传了 {call_kwargs.get('max_tokens')}（llm_reviewer.py:40 硬编码 2000 同模式 bug）"
    )


# ===== G14: api_key 直填 + 模型枚举 API + default_provider 兜底 =====

_DIRECT_KEY_YAML = """
default_provider: euler-y

providers:
  euler-y:
    name: csi
    base_url: http://localhost:9999/v1/
    api_key: sk-test-direct-key-12345  # 直填 key 格式测试（假 key）
    protocol: openai
    timeout_seconds: 120
    models:
      GLM-5.3-Flash:
        name: GLM-5.3-Flash
        max_tokens: 4000
      GLM-5.3:
        name: GLM-5.3
      Qwen3.8-Flash:
        name: Qwen3.8-Flash

  env-style:
    name: env style provider
    base_url: http://localhost:9999/v1/
    api_key_env: ENV_STYLE_API_KEY
    protocol: openai
    model: m1  # 老格式：顶层单 model
"""


@pytest.fixture
def direct_key_yaml(tmp_path, monkeypatch):
    cfg = tmp_path / "ai_providers.yaml"
    cfg.write_text(_DIRECT_KEY_YAML, encoding="utf-8")
    import clowder_analytics.ai.llm_provider as mod
    monkeypatch.setattr(mod, "_CONFIG_PATH", cfg)
    monkeypatch.setattr(mod, "_CONFIG_CACHE", None)
    return cfg


def test_api_key_direct_field_no_env_needed(direct_key_yaml):
    """api_key 直填字段：不需要环境变量，直接用配置里的 key"""
    p = load_provider("euler-y", model="GLM-5.3-Flash")
    assert p.config.api_key == "sk-test-direct-key-12345"
    assert p.config.model == "GLM-5.3-Flash"


def test_api_key_direct_takes_priority_over_env(direct_key_yaml, monkeypatch):
    """api_key 直填优先于 api_key_env"""
    monkeypatch.setenv("EULER_Y_API_KEY", "sk-from-env")
    p = load_provider("euler-y")
    # 直填的 key 优先
    assert p.config.api_key == "sk-test-direct-key-12345"


def test_list_providers_returns_provider_model_structure(direct_key_yaml):
    """list_providers() 返回页面展示用的结构"""
    from clowder_analytics.ai.llm_provider import list_providers
    providers = list_providers()
    assert isinstance(providers, list)
    names = [p["name"] for p in providers]
    assert "euler-y" in names
    assert "env-style" in names
    # euler-y 的 models 列表
    euler = next(p for p in providers if p["name"] == "euler-y")
    assert set(euler["models"]) == {"GLM-5.3-Flash", "GLM-5.3", "Qwen3.8-Flash"}
    # 老格式顶层 model 也应出现在 models 里
    # default_model 未写时 None
    assert euler["default_model"] is None


def test_list_providers_old_format_model_in_models(direct_key_yaml):
    """老格式顶层 model 字段也出现在 list_providers 的 models 里"""
    from clowder_analytics.ai.llm_provider import list_providers
    providers = list_providers()
    env_style = next(p for p in providers if p["name"] == "env-style")
    assert env_style["models"] == ["m1"]
    assert env_style["default_model"] == "m1"


def test_default_provider_fallback_to_first(direct_key_yaml):
    """default_provider 不存在时兜底取第一个 provider（不 KeyError）"""
    from clowder_analytics.ai.llm_provider import get_default_provider_name
    # yaml 里 default_provider: euler-y 存在
    assert get_default_provider_name() == "euler-y"


def test_default_provider_missing_falls_back(tmp_path, monkeypatch):
    """default_provider 指向不存在的 provider 时取第一个"""
    broken_yaml = """
default_provider: nonexistent
providers:
  alpha:
    name: alpha
    base_url: http://localhost/v1/
    api_key: sk-direct
    protocol: openai
    models:
      a-model:
        name: a-model
"""
    cfg = tmp_path / "broken.yaml"
    cfg.write_text(broken_yaml, encoding="utf-8")
    import clowder_analytics.ai.llm_provider as mod
    monkeypatch.setattr(mod, "_CONFIG_PATH", cfg)
    monkeypatch.setattr(mod, "_CONFIG_CACHE", None)
    from clowder_analytics.ai.llm_provider import get_default_provider_name
    assert get_default_provider_name() == "alpha"
    # load_provider() 不传 name 也不炸
    p = load_provider()
    assert p.config.name == "alpha"


# ===== G15: ai_providers.local.yaml 两层配置 + api_key_env 值校验 =====

import pytest as _pytest  # noqa: E402


@_pytest.fixture
def two_layer_yaml(tmp_path, monkeypatch):
    """主配置（key 走 env）+ local 配置（直填 key）两层 fixture"""
    main_yaml = tmp_path / "ai_providers.yaml"
    main_yaml.write_text(
        "default_provider: euler-y\n"
        "providers:\n"
        "  euler-y:\n"
        "    name: csi\n"
        "    base_url: http://localhost:9999/v1/\n"
        "    api_key_env: EULER_Y_API_KEY\n"
        "    protocol: openai\n"
        "    default_model: GLM-5.3-Flash\n"
        "    models:\n"
        "      GLM-5.3-Flash:\n"
        "        name: GLM-5.3-Flash\n",
        encoding="utf-8",
    )
    import clowder_analytics.ai.llm_provider as mod
    monkeypatch.setattr(mod, "_CONFIG_PATH", main_yaml)
    monkeypatch.setattr(mod, "_LOCAL_CONFIG_PATH", tmp_path / "ai_providers.local.yaml")
    monkeypatch.setattr(mod, "_CONFIG_CACHE", None)
    return tmp_path


def test_local_yaml_overrides_api_key(two_layer_yaml, monkeypatch):
    """local yaml 直填 key 深合并覆盖主配置——env 未设也能加载"""
    local = two_layer_yaml / "ai_providers.local.yaml"
    local.write_text(
        "providers:\n"
        "  euler-y:\n"
        "    api_key: sk-from-local-file\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("EULER_Y_API_KEY", raising=False)
    p = load_provider("euler-y")
    assert p.config.api_key == "sk-from-local-file"
    # local 只覆盖 key，主配置其余字段（base_url/models）保留
    assert p.config.base_url == "http://localhost:9999/v1/"
    assert p.config.model == "GLM-5.3-Flash"


def test_local_yaml_merge_nested_models(two_layer_yaml, monkeypatch):
    """local 可深合并嵌套字段（如给某 model 加 max_tokens）而不清掉兄弟字段"""
    local = two_layer_yaml / "ai_providers.local.yaml"
    local.write_text(
        "providers:\n"
        "  euler-y:\n"
        "    models:\n"
        "      GLM-5.3-Flash:\n"
        "        max_tokens: 8000\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EULER_Y_API_KEY", "sk-from-env")
    p = load_provider("euler-y")
    # local 合并后的 max_tokens 生效
    assert p.config.max_tokens == 8000
    # 主配置的其他 model 字段仍在（models map 不被整体替换）
    from clowder_analytics.ai.llm_provider import list_providers
    models = list_providers()[0]["models"]
    assert models == ["GLM-5.3-Flash"]


def test_no_local_yaml_uses_main_only(two_layer_yaml, monkeypatch):
    """没有 local 文件时纯用主配置（env 生效路径不变）"""
    monkeypatch.setenv("EULER_Y_API_KEY", "sk-from-env")
    p = load_provider("euler-y")
    assert p.config.api_key == "sk-from-env"


def test_api_key_env_looking_like_key_rejected(two_layer_yaml):
    """api_key_env 值长得像 key（sk- 开头）→ 明确报错防填错（LL-049 现场复现）"""
    import clowder_analytics.ai.llm_provider as mod
    main = two_layer_yaml / "ai_providers.yaml"
    main.write_text(
        "providers:\n"
        "  euler-y:\n"
        "    name: csi\n"
        "    base_url: http://localhost:9999/v1/\n"
        "    api_key_env: sk-fake-invalid-key-sample\n"
        "    protocol: openai\n"
        "    models:\n"
        "      GLM-5.3-Flash:\n"
        "        name: GLM-5.3-Flash\n",
        encoding="utf-8",
    )
    # match 用英文/变量名片段（避免 Windows GBK 控制台下中文 match 不稳）
    with _pytest.raises(RuntimeError, match=r"api_key_env.*EULER_Y_API_KEY.*ai_providers\.local\.yaml"):
        load_provider("euler-y")
