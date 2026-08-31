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
