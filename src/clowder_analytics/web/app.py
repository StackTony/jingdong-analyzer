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


def _render_model_selector() -> tuple[str, str, bool] | None:
    """sidebar 模型选择器（G14）：展示当前模型 + 切换 provider/model

    Returns:
        (provider_name, model_id, use_real_llm)；配置不可用时返回 None
    """
    try:
        from clowder_analytics.ai.llm_provider import (
            get_default_provider_name,
            list_providers,
        )
        providers = list_providers()
        if not providers:
            st.sidebar.caption("（ai_providers.yaml 未配置 provider）")
            return None
    except Exception as e:
        st.sidebar.caption(f"（LLM 配置加载失败：{e}）")
        return None

    default_name = get_default_provider_name()
    provider_names = [p["name"] for p in providers]
    default_idx = provider_names.index(default_name) if default_name in provider_names else 0

    with st.sidebar:
        st.divider()
        st.header("🤖 AI 模型")
        selected_provider = st.selectbox(
            "Provider", provider_names, index=default_idx,
        )
        provider_info = next(p for p in providers if p["name"] == selected_provider)
        models = provider_info["models"]
        if not models:
            st.caption("（该 provider 无 model 配置）")
            return None
        default_model = provider_info.get("default_model") or models[0]
        model_idx = models.index(default_model) if default_model in models else 0
        selected_model = st.selectbox("Model", models, index=model_idx)
        use_real_llm = st.checkbox("使用真实 LLM", value=True)
        # 当前模型展示（铲屎官要求：页面展示 AI 当前使用模型）
        if use_real_llm:
            st.caption(f"当前模型：**{selected_provider}** / **{selected_model}**")
        else:
            st.caption("当前模型：**Fake**（离线模式，不调 LLM）")
        return selected_provider, selected_model, use_real_llm


def _build_ai_stack(llm_choice: tuple[str, str, bool] | None):
    """按模型选择构造 (generator, reviewer)

    真实 LLM：load_provider(provider, model) → LLMPlanGenerator / LLMReviewer
    Fake / 未配置：FakePlanGenerator / FakeReviewer
    """
    if llm_choice is None:
        return FakePlanGenerator(), FakeReviewer()
    provider_name, model_id, use_real = llm_choice
    if not use_real:
        return FakePlanGenerator(), FakeReviewer()
    try:
        from clowder_analytics.ai.llm_plan_generator import LLMPlanGenerator
        from clowder_analytics.ai.llm_reviewer import LLMReviewer
        from clowder_analytics.ai.llm_provider import load_provider
        provider = load_provider(provider_name, model=model_id)
        return LLMPlanGenerator(provider=provider), LLMReviewer(provider=provider)
    except (RuntimeError, KeyError, NotImplementedError) as e:
        st.sidebar.warning(f"LLM 加载失败，退回 Fake：{e}")
        return FakePlanGenerator(), FakeReviewer()


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

    # ===== 左侧：模型选择（G14：展示当前模型 + 切换）=====
    llm_choice = _render_model_selector()

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
            # G14：按 sidebar 模型选择构造 generator/reviewer（真实 LLM / Fake）
            generator, reviewer = _build_ai_stack(llm_choice)
            result = run(
                question=question,
                dataset=ds,
                library=st.session_state.library,
                generator=generator,
                reviewer=reviewer,
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
    col_a, col_b, col_c, col_d = st.columns(4)
    with col_a:
        st.metric("路由", result.route)
    with col_b:
        st.metric("LLM 调用", result.llm_calls)
    with col_c:
        st.metric("执行步骤", f"{sum(1 for s in result.log if s.get('ok'))}/{len(result.log)}")
    with col_d:
        # G14：结果区展示当前使用模型
        if llm_choice is not None and llm_choice[2]:
            st.metric("当前模型", llm_choice[1])
        else:
            st.metric("当前模型", "Fake")

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
                _render_chart(chart_spec)

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


# ===== G3: 大数据采样渲染辅助 =====

# web 端默认 max_rows：避免 33 万行 bar chart 全量序列化 JSON 卡浏览器
# heatmap 是矩阵不采样，bar/line/scatter 采样到前 50 行（交互够用）
WEB_RENDER_MAX_ROWS = 50


def _render_chart(chart_spec) -> None:
    """web app 渲染 chart 的辅助函数（G3 闭环 B 方案）

    内置 max_rows=50 采样，避免大数据量全量喂 plotly 卡浏览器。
    plotly 未装时 fallback 到 st.warning。
    """
    try:
        from clowder_analytics.atomic.visualizer import render
        # G2+G3: 调 render 传 max_rows，B 方案 to_json 闭环
        # heatmap 是矩阵不采样，其他类型采样到 WEB_RENDER_MAX_ROWS
        max_rows = None if chart_spec.type == "heatmap" else WEB_RENDER_MAX_ROWS
        fig = render(chart_spec, mode="interactive", max_rows=max_rows)
        st.plotly_chart(fig, use_container_width=True)
    except NotImplementedError as e:
        st.warning(f"plotly 未装，跳过渲染：{e}")


if __name__ == "__main__":
    main()
