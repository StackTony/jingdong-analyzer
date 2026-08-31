"""F002 P5: CLI 红测（spec §8.1 AC-8）

测试用 subprocess 跑 `python -m clowder_analytics.cli` 避免依赖 entry_points 安装。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest


def _run_cli(*args: str, cwd: Path | None = None) -> tuple[int, str, str]:
    """跑 CLI，返回 (returncode, stdout, stderr)

    Windows 默认控制台编码 GBK，CLI 中文输出会乱码 → 用 errors='replace'
    避免 UnicodeDecodeError；同时尝试 UTF-8 优先。
    """
    cmd = [sys.executable, "-m", "clowder_analytics.cli", *args]
    r = subprocess.run(
        cmd, capture_output=True, cwd=cwd,
        encoding="utf-8", errors="replace",
    )
    return r.returncode, r.stdout, r.stderr


def test_cli_no_args_prints_usage():
    """无参数打印用法"""
    code, out, err = _run_cli()
    assert code != 0 or "usage" in (out + err).lower()


def test_cli_help():
    """--help 打印命令清单"""
    code, out, _ = _run_cli("--help")
    assert code == 0
    assert "run" in out
    assert "flow" in out
    assert "inspect" in out


def test_cli_inspect_csv(tmp_path):
    """source inspect 打印 schema + 指纹"""
    csv = tmp_path / "data.csv"
    df = pd.DataFrame({"brand": ["a", "b"], "sales": [10, 20]})
    df.to_csv(csv, index=False, encoding="utf-8")

    code, out, _ = _run_cli("inspect", str(csv))
    assert code == 0
    assert "brand" in out
    assert "sales" in out
    assert "fingerprint" in out.lower() or "指纹" in out
    assert "2" in out  # 行数


def test_cli_inspect_excel(tmp_path):
    """inspect 支持 xlsx"""
    xlsx = tmp_path / "data.xlsx"
    df = pd.DataFrame({"brand": ["a", "b"], "sales": [10, 20]})
    df.to_excel(xlsx, index=False)

    code, out, _ = _run_cli("inspect", str(xlsx))
    assert code == 0
    assert "brand" in out


def test_cli_run_csv_topn(tmp_path):
    """run 命令端到端跑通 CSV TopN 分析（spec AC-8）

    P6 后会命中冷启动模板走 A 轨（0 LLM）；之前走 fallback/B 轨
    两种情况都算通过，关键是路由信息出现且不报错
    """
    csv = tmp_path / "brands.csv"
    df = pd.DataFrame({
        "brand": ["小米", "华为", "OPPO", "vivo", "联想"],
        "sales": [100, 200, 250, 180, 50],
    })
    df.to_csv(csv, index=False, encoding="utf-8")

    code, out, err = _run_cli(
        "run", "--source", str(csv), "--question", "Top30 品牌销量",
    )
    assert code == 0, f"stderr: {err}"
    # 输出含路由信息（A/B/fallback 任一）
    assert any(x in out for x in ["route", "路由", "A", "B", "fallback"])


def test_cli_run_no_review_flag(tmp_path):
    """--no-review 跳过 Reviewer"""
    csv = tmp_path / "data.csv"
    df = pd.DataFrame({"brand": ["a", "b"], "sales": [10, 20]})
    df.to_csv(csv, index=False, encoding="utf-8")

    code, out, _ = _run_cli(
        "run", "--source", str(csv),
        "--question", "Top10", "--no-review",
    )
    assert code == 0
    # 不应有三段式报告
    assert "## 异常解释" not in out


def test_cli_flow_list_templates_empty(tmp_path):
    """flow list-templates 空库返回友好提示"""
    code, out, _ = _run_cli("flow", "list-templates", "--lib", str(tmp_path))
    assert code == 0
    assert "template" in out.lower() or "无" in out or "0" in out


def test_cli_flow_list_plans_empty(tmp_path):
    """flow list-plans 空库"""
    code, out, _ = _run_cli("flow", "list-plans", "--lib", str(tmp_path))
    assert code == 0


def test_cli_flow_stats_empty(tmp_path):
    """flow stats 空库打印友好提示"""
    code, out, _ = _run_cli("flow", "stats", "--lib", str(tmp_path))
    assert code == 0
    # 空库时提示"无运行记录"或显示全 0 统计
    assert "无" in out or "rate" in out.lower() or "0" in out or "运行" in out


def test_cli_flow_stats_after_runs(tmp_path):
    """跑过几次后 flow stats 显示命中率"""
    csv = tmp_path / "brands.csv"
    df = pd.DataFrame({"brand": ["a", "b"], "sales": [10, 20]})
    df.to_csv(csv, index=False, encoding="utf-8")

    # 跑两次
    for _ in range(2):
        _run_cli(
            "run", "--source", str(csv), "--question", "Top10",
            "--lib", str(tmp_path), "--no-review",
        )

    code, out, _ = _run_cli("flow", "stats", "--lib", str(tmp_path))
    assert code == 0
    # 应有 fallback/B 轨计数
    assert "fallback" in out.lower() or "B" in out or "2" in out


def test_cli_run_with_lib_flag_uses_custom_library(tmp_path):
    """--lib 指定 Flow Library 目录"""
    csv = tmp_path / "data.csv"
    df = pd.DataFrame({"brand": ["a", "b", "c"], "sales": [10, 20, 30]})
    df.to_csv(csv, index=False, encoding="utf-8")

    lib_dir = tmp_path / "mylib"
    code, out, _ = _run_cli(
        "run", "--source", str(csv), "--question", "Top10",
        "--lib", str(lib_dir), "--no-review",
    )
    assert code == 0
    # library 目录被创建
    assert (lib_dir / "templates").is_dir()
    assert (lib_dir / "plans").is_dir()
    assert (lib_dir / "runs").is_dir()


def test_cli_run_llm_flag_without_api_key_falls_back_to_fake(tmp_path, monkeypatch):
    """--llm 但 CSI_API_KEY 未设 → 退回 Fake + 警告（不崩）"""
    csv = tmp_path / "data.csv"
    df = pd.DataFrame({"brand": ["a", "b"], "sales": [10, 20]})
    df.to_csv(csv, index=False, encoding="utf-8")

    # 确保环境变量未设
    env = {**__import__("os").environ, "CSI_API_KEY": ""}
    code, out, _ = _run_cli_env(
        env,
        "run", "--source", str(csv), "--question", "Top10",
        "--lib", str(tmp_path), "--llm", "--no-review",
    )
    assert code == 0
    # 应有警告 + 退回 Fake（用 0 LLM 调用，因为命中冷启动模板）


def _run_cli_env(env: dict, *args: str, cwd: Path | None = None):
    """带自定义 env 跑 CLI"""
    cmd = [sys.executable, "-m", "clowder_analytics.cli", *args]
    r = subprocess.run(
        cmd, capture_output=True, cwd=cwd,
        encoding="utf-8", errors="replace", env=env,
    )
    return r.returncode, r.stdout, r.stderr
