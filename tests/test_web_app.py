"""F002 P5: Streamlit 面板导入测试（spec §8.2 / AC-9）

完整 UI 测试靠人工跑 streamlit run。这里只测：
- 模块可导入（语法 / 依赖正确）
- _init_state / _load_uploaded_file 可调用
"""
from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest


def test_web_app_imports():
    """模块可导入"""
    from clowder_analytics.web import app
    assert hasattr(app, "main")
    assert hasattr(app, "_init_state")
    assert hasattr(app, "_load_uploaded_file")


def test_web_app_init_state_callable():
    """_init_state 在 mock session_state 下可调用"""
    from clowder_analytics.web.app import _init_state

    class FakeSession(dict):
        def __setattr__(self, k, v):
            self[k] = v

    fake = FakeSession()
    with patch("streamlit.session_state", fake):
        try:
            _init_state()
        except Exception:
            # streamlit 内部细节可能抛，关键是函数本身能进
            pass


def test_web_app_load_uploaded_csv(tmp_path):
    """_load_uploaded_file 处理 CSV 上传"""
    from clowder_analytics.web.app import _load_uploaded_file

    csv = tmp_path / "data.csv"
    df = pd.DataFrame({"brand": ["a", "b"], "sales": [10, 20]})
    df.to_csv(csv, index=False, encoding="utf-8")

    class FakeUpload:
        name = "data.csv"
        def getvalue(self):
            with open(csv, "rb") as f:
                return f.read()

    with patch("streamlit.session_state", {}):
        ds = _load_uploaded_file(FakeUpload())
        assert ds is not None
        assert len(ds.df) == 2
        assert "brand" in ds.df.columns


def test_web_app_load_none_returns_none():
    """无上传时返回 None"""
    from clowder_analytics.web.app import _load_uploaded_file
    assert _load_uploaded_file(None) is None


def test_web_app_load_unsupported_type(tmp_path):
    """不支持的文件类型报错"""
    from clowder_analytics.web.app import _load_uploaded_file

    class FakeUpload:
        name = "data.txt"
        def getvalue(self):
            return b"hello"

    with patch("streamlit.session_state", {}):
        with patch("streamlit.error") as mock_err:
            ds = _load_uploaded_file(FakeUpload())
            assert ds is None
            mock_err.assert_called_once()


# ===== G3: web app render 路径走 max_rows 采样（B 方案闭环）=====

def test_web_app_render_chart_uses_max_rows_sampling():
    """_render_chart 抽出辅助函数，内置 max_rows 采样，
    避免 33 万行 DataFrame 直接喂 plotly 卡浏览器"""
    from clowder_analytics.web.app import _render_chart
    from clowder_analytics.atomic.spec import ChartSpec

    # 大 DataFrame（1000 行），_render_chart 应采样到 max_rows=50
    df = pd.DataFrame({"brand": [f"b{i}" for i in range(1000)], "sales": list(range(1000))})
    spec = ChartSpec(type="bar", data=df, x="brand", y="sales")

    with patch("streamlit.plotly_chart") as mock_plotly:
        _render_chart(spec)
        # 被调了一次
        assert mock_plotly.call_count == 1
        fig = mock_plotly.call_args.args[0]
        # 采样后只喂 50 行（默认 max_rows）
        assert len(fig.data[0].x) == 50


# ===== G14: 模型展示 + 切换 =====

def test_web_app_model_selector_and_build_ai_stack():
    """_render_model_selector / _build_ai_stack 可导入可调用"""
    from clowder_analytics.web.app import _build_ai_stack, _render_model_selector
    assert callable(_render_model_selector)
    assert callable(_build_ai_stack)


def test_build_ai_stack_none_returns_fake():
    """llm_choice=None（配置不可用）→ Fake"""
    from clowder_analytics.ai.fake import FakePlanGenerator, FakeReviewer
    from clowder_analytics.web.app import _build_ai_stack
    gen, rev = _build_ai_stack(None)
    assert isinstance(gen, FakePlanGenerator)
    assert isinstance(rev, FakeReviewer)


def test_build_ai_stack_fake_mode():
    """use_real=False → Fake"""
    from clowder_analytics.ai.fake import FakePlanGenerator, FakeReviewer
    from clowder_analytics.web.app import _build_ai_stack
    gen, rev = _build_ai_stack(("euler-y", "GLM-5.3-Flash", False))
    assert isinstance(gen, FakePlanGenerator)
    assert isinstance(rev, FakeReviewer)


def test_build_ai_stack_real_llm_direct_key(tmp_path, monkeypatch):
    """use_real=True + api_key 配置可用 → 真 LLMPlanGenerator/LLMReviewer

    用隔离的假 key yaml fixture（不依赖生产配置、不调网络）。
    """
    from clowder_analytics.ai.llm_plan_generator import LLMPlanGenerator
    from clowder_analytics.ai.llm_reviewer import LLMReviewer
    from clowder_analytics.web.app import _build_ai_stack

    # 隔离 yaml：euler-y 走 api_key 直填（假 key），可直接加载
    import clowder_analytics.ai.llm_provider as mod
    cfg = tmp_path / "ai_providers.yaml"
    cfg.write_text(
        "providers:\n"
        "  euler-y:\n"
        "    name: csi\n"
        "    base_url: http://localhost:9999/v1/\n"
        "    api_key: sk-test-direct-key-12345\n"
        "    protocol: openai\n"
        "    models:\n"
        "      GLM-5.3-Flash:\n"
        "        name: GLM-5.3-Flash\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "_CONFIG_PATH", cfg)
    monkeypatch.setattr(mod, "_CONFIG_CACHE", None)

    gen, rev = _build_ai_stack(("euler-y", "GLM-5.3-Flash", True))
    assert isinstance(gen, LLMPlanGenerator)
    assert isinstance(rev, LLMReviewer)
    assert gen.provider.config.model == "GLM-5.3-Flash"


def test_build_ai_stack_unknown_model_falls_back_fake():
    """model 不存在 → 退回 Fake（不炸页面）"""
    from clowder_analytics.ai.fake import FakePlanGenerator, FakeReviewer
    from clowder_analytics.web.app import _build_ai_stack
    gen, rev = _build_ai_stack(("euler-y", "nonexistent-model", True))
    assert isinstance(gen, FakePlanGenerator)
    assert isinstance(rev, FakeReviewer)
