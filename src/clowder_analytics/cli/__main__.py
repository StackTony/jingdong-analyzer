"""F002 P5: CLI 入口（spec §8.1 / AC-8）

命令：
    jd-analyze inspect <path>                    # 数据源探索
    jd-analyze run --source <path> --question <text> [--no-review] [--lib <dir>]
    jd-analyze flow list-templates [--lib <dir>]
    jd-analyze flow list-plans [--lib <dir>]
    jd-analyze flow stats [--lib <dir>]
    jd-analyze flow scan-promote [--lib <dir>]

测试入口：python -m clowder_analytics.cli <args>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from clowder_analytics.adapters.base import Dataset
from clowder_analytics.adapters.csv import CsvAdapter
from clowder_analytics.adapters.excel import ExcelAdapter
from clowder_analytics.ai.fake import FakePlanGenerator, FakeReviewer
from clowder_analytics.flow_library.promoter import Promoter
from clowder_analytics.flow_library.store import FlowLibrary
from clowder_analytics.orchestrator.run import run

# Windows 控制台默认 GBK，强制 UTF-8 输出避免中文乱码
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


def _load_dataset(path: str) -> Dataset:
    """按后缀选 Adapter"""
    p = Path(path)
    if not p.exists():
        print(f"错误：文件不存在 {path}", file=sys.stderr)
        sys.exit(1)
    if p.suffix.lower() in (".csv", ".tsv"):
        return CsvAdapter().load({"path": p})
    if p.suffix.lower() in (".xlsx", ".xls"):
        return ExcelAdapter().load({"path": p})
    print(f"错误：不支持的文件类型 {p.suffix}", file=sys.stderr)
    sys.exit(1)


def _get_library(lib_dir: str | None) -> FlowLibrary:
    return FlowLibrary(base_dir=lib_dir) if lib_dir else FlowLibrary()


def cmd_inspect(args: argparse.Namespace) -> int:
    ds = _load_dataset(args.source)
    print(f"=== 数据源：{args.source} ===")
    print(f"类型: {ds.source_type}")
    print(f"行数: {len(ds.df)}")
    print(f"列数: {len(ds.df.columns)}")
    print(f"Schema 指纹: {ds.schema_fingerprint}")
    print()
    print("列信息:")
    for col in ds.columns:
        hint = f" ({col.semantic_hint})" if col.semantic_hint else ""
        print(f"  - {col.name}: {col.dtype}{hint}")
    print()
    print("前 5 行:")
    print(ds.df.head().to_string())
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    ds = _load_dataset(args.source)
    library = _get_library(args.lib)
    enable_review = not args.no_review

    result = run(
        question=args.question,
        dataset=ds,
        library=library,
        generator=FakePlanGenerator(),
        reviewer=FakeReviewer(),
        enable_review=enable_review,
    )

    print(f"=== 运行结果 ===")
    print(f"路由: {result.route}")
    print(f"Plan ID: {result.plan_id}")
    if result.matched_template_id:
        print(f"命中模板: {result.matched_template_id}")
    if result.matched_plan_id:
        print(f"命中 Plan: {result.matched_plan_id}")
    print(f"LLM 调用数: {result.llm_calls}")
    print(f"耗时: {result.duration_ms} ms")
    print(f"执行步骤: {len(result.log)} 步，"
          f"{sum(1 for s in result.log if s.get('ok'))} 步成功")
    print()
    print("最终数据（前 10 行）:")
    print(result.df.head(10).to_string())
    print()
    print(f"图表数: {len(result.charts)}")
    if result.charts:
        for i, c in enumerate(result.charts):
            print(f"  [{i+1}] {c.type}: {c.title}")
    if result.review:
        print()
        print("=== AI Reviewer 报告 ===")
        print(result.review)
    return 0


def cmd_flow_list_templates(args: argparse.Namespace) -> int:
    library = _get_library(args.lib)
    templates = library.list_templates()
    if not templates:
        print("（无模板）")
        return 0
    print(f"共 {len(templates)} 个模板：")
    for t in templates:
        print(f"  - {t.template_id} | intent={t.intent} | stability={t.stability} "
              f"| fp={t.schema_fingerprint[:8]} | steps={len(t.steps)}")
    return 0


def cmd_flow_list_plans(args: argparse.Namespace) -> int:
    library = _get_library(args.lib)
    plans = library.list_plans()
    if not plans:
        print("（无 Plan）")
        return 0
    print(f"共 {len(plans)} 个 Plan：")
    for p in plans:
        print(f"  - {p.plan_id} | intent={p.intent} | steps={len(p.steps)}")
    return 0


def cmd_flow_stats(args: argparse.Namespace) -> int:
    library = _get_library(args.lib)
    from clowder_analytics.flow_library.dashboard import compute_stats, format_stats
    stats = compute_stats(library)
    if stats.total_runs == 0:
        print("（无运行记录）")
        print()
        print(format_stats(stats))
        return 0
    print(format_stats(stats))
    return 0


def cmd_flow_scan_promote(args: argparse.Namespace) -> int:
    library = _get_library(args.lib)
    promoter = Promoter(library=library)
    promoted = promoter.scan_and_promote()
    if not promoted:
        print("（无新晋升的模板）")
    else:
        print(f"晋升 {len(promoted)} 个模板：")
        for tid in promoted:
            print(f"  - {tid}")
    # 同时检查降级
    for t in library.list_templates():
        if t.stability != "deprecated":
            demoted = promoter.check_and_demote(t.template_id)
            if demoted:
                print(f"降级: {t.template_id} → deprecated")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jd-analyze",
        description="Clowder AI 通用数据分析框架（F002）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # inspect
    p_inspect = sub.add_parser("inspect", help="数据源探索：打印 schema + 指纹")
    p_inspect.add_argument("source", help="数据源路径（.csv/.xlsx）")
    p_inspect.set_defaults(func=cmd_inspect)

    # run
    p_run = sub.add_parser("run", help="端到端跑分析")
    p_run.add_argument("--source", required=True, help="数据源路径")
    p_run.add_argument("--question", required=True, help="用户问题")
    p_run.add_argument("--no-review", action="store_true", help="跳过 AI Reviewer")
    p_run.add_argument("--lib", default=None, help="Flow Library 目录")
    p_run.set_defaults(func=cmd_run)

    # flow
    p_flow = sub.add_parser("flow", help="Flow Library 管理")
    flow_sub = p_flow.add_subparsers(dest="flow_cmd", required=True)
    for cmd_name in ("list-templates", "list-plans", "stats", "scan-promote"):
        p = flow_sub.add_parser(cmd_name)
        p.add_argument("--lib", default=None)
    p_flow.set_defaults(func=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "flow":
        flow_cmd = args.flow_cmd
        if flow_cmd == "list-templates":
            return cmd_flow_list_templates(args)
        if flow_cmd == "list-plans":
            return cmd_flow_list_plans(args)
        if flow_cmd == "stats":
            return cmd_flow_stats(args)
        if flow_cmd == "scan-promote":
            return cmd_flow_scan_promote(args)
        parser.error(f"未知 flow 子命令: {flow_cmd}")

    if hasattr(args, "func"):
        return args.func(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
