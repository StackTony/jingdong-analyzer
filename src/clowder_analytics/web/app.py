"""F002 P5: Streamlit 面板（spec §8.2 / AC-9）

单页应用：
- 左侧：上传 Excel/CSV → 显示 schema + 指纹
- 中间：选分析意图（下拉 + 自然语言输入）→ 显示命中的 A/B/兜底路径
- 右侧：交互图 + AI 报告 + 采纳/拒绝按钮（反馈写回运行日志）

启动：streamlit run src/clowder_analytics/web/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from clowder_analytics.adapters.base import Dataset, compute_fingerprint
from clowder_analytics.adapters.csv import CsvAdapter
from clowder_analytics.adapters.excel import ExcelAdapter
from clowder_analytics.ai.fake import FakePlanGenerator, FakeReviewer
from clowder_analytics.flow_library.store import FlowLibrary
from clowder_analytics.orchestrator.run import run


# ===== Session state 初始化 =====

def _init_state():
    if "library" not in st.session_state:
        st.session_state.library = FlowLibrary()
    if "last_result" not in st.session_state:
        st.session_state.last_result = None
    if "last_question" not in st.session_state:
        st.session_state.last_question = ""


def _load_uploaded_file(uploaded) -> Dataset | None:
    if uploaded is None:
        return None
    suffix = Path(uploaded.name).suffix.lower()
    tmp_path = Path("._tmp_upload") / uploaded.name
    tmp_path.parent.mkdir(exist_ok=True)
    with open(tmp_path, "wb") as f:
        f.write(uploaded.getvalue())
    try:
        if suffix == ".csv":
            return CsvAdapter().load({"path": tmp_path})
        if suffix in (".xlsx", ".xls"):
            return ExcelAdapter().load({"path": tmp_path})
        st.error(f"不支持的文件类型: {suffix}")
        return None
    except Exception as e:
        st.error(f"加载失败: {e}")
        return None


def main():
    st.set_page_config(
        page_title="Clowder AI 通用数据分析",
        page_icon="🐾",
        layout="wide",
    )
    _init_state()

    st.title("🐾 Clowder AI 通用数据分析框架")
    st.caption("F002 双轨自进化：A 模板 / B Plan / LLM 兜底")

    # ===== 左侧：数据源 =====
    with st.sidebar:
        st.header("📁 数据源")
        uploaded = st.file_uploader(
            "上传 Excel / CSV", type=["csv", "xlsx", "xls"],
        )
        if uploaded:
            ds = _load_uploaded_file(uploaded)
            if ds is not None:
                st.session_state.dataset = ds
                st.success(f"加载成功：{len(ds.df)} 行 × {len(ds.df.columns)} 列")
                st.write(f"**Schema 指纹**: `{ds.schema_fingerprint}`")
                st.write("**列信息**:")
                for col in ds.columns:
                    st.text(f"  {col.name} ({col.dtype})")
                with st.expander("前 5 行预览"):
                    st.dataframe(ds.df.head())

        st.divider()
        st.header("⚙️ 选项")
        enable_review = st.checkbox("启用 AI Reviewer", value=True)
        lib_dir = st.text_input("Flow Library 目录（可选）", value="")
        if lib_dir:
            st.session_state.library = FlowLibrary(base_dir=lib_dir)

    # ===== 中间：分析意图 =====
    if "dataset" not in st.session_state:
        st.info("👈 请先在左侧上传数据文件")
        return

    ds: Dataset = st.session_state.dataset

    st.header("🔍 分析意图")
    col1, col2 = st.columns([1, 2])
    with col1:
        intent_preset = st.selectbox(
            "常用意图", [
                "自定义",
                "Top30 品牌销量",
                "哪些品牌销量异常",
                "近 6 个月趋势",
                "价格和销量相关性",
                "品类对比",
            ],
        )
    with col2:
        if intent_preset == "自定义":
            question = st.text_input("或输入你的问题", "")
        else:
            question = intent_preset
            st.text(f"问题: {question}")

    if st.button("🚀 运行分析", type="primary", disabled=not question):
        with st.spinner("运行中..."):
            result = run(
                question=question,
                dataset=ds,
                library=st.session_state.library,
                generator=FakePlanGenerator(),
                reviewer=FakeReviewer(),
                enable_review=enable_review,
            )
            st.session_state.last_result = result
            st.session_state.last_question = question

    # ===== 右侧：结果 =====
    result = st.session_state.last_result
    if result is None:
        st.info("点击「运行分析」查看结果")
        return

    st.header("📊 运行结果")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.metric("路由", result.route)
    with col_b:
        st.metric("LLM 调用", result.llm_calls)
    with col_c:
        st.metric("执行步骤", f"{sum(1 for s in result.log if s.get('ok'))}/{len(result.log)}")

    if result.matched_template_id:
        st.write(f"**命中模板**: {result.matched_template_id}")
    if result.matched_plan_id:
        st.write(f"**命中 Plan**: {result.matched_plan_id}")

    st.subheader("数据结果")
    st.dataframe(result.df.head(50), use_container_width=True)

    if result.charts:
        st.subheader("📈 图表")
        for i, chart_spec in enumerate(result.charts):
            with st.expander(f"图 {i+1}: {chart_spec.type} - {chart_spec.title}", expanded=True):
                try:
                    from clowder_analytics.atomic.visualizer import render
                    fig = render(chart_spec, mode="interactive")
                    st.plotly_chart(fig, use_container_width=True)
                except NotImplementedError as e:
                    st.warning(f"plotly 未装，跳过渲染：{e}")

    if result.review:
        st.subheader("📝 AI Reviewer 报告")
        st.markdown(result.review)

        st.divider()
        st.subheader("💬 反馈")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ 采纳"):
                _save_feedback(st.session_state.library, result, adopted=True)
                st.success("已记录采纳")
        with col2:
            if st.button("❌ 拒绝"):
                _save_feedback(st.session_state.library, result, adopted=False)
                st.warning("已记录拒绝")


def _save_feedback(library: FlowLibrary, result, adopted: bool):
    """把反馈写回最近一次 RunRecord（追加新记录标记采纳/拒绝）"""
    from clowder_analytics.flow_library.models import RunRecord
    rec = RunRecord(
        schema_fingerprint="",
        intent="",
        route=result.route,
        success=all(s.get("ok") for s in result.log),
        matched_template_id=result.matched_template_id,
        matched_plan_id=result.matched_plan_id,
        user_adopted=adopted,
    )
    library.save_run(rec)


if __name__ == "__main__":
    main()
