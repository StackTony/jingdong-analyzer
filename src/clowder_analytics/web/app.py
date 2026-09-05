"""F002 P5: Streamlit 面板（spec §8.2 / AC-9）+ G16 Flow Library 管理

单页应用：
- 左侧：上传 Excel/CSV → 显示 schema + 指纹
- 中间：选分析意图（下拉 + 自然语言输入）→ 显示命中的 A/B/兜底路径
- 右侧：交互图 + AI 报告 + 采纳/拒绝按钮（反馈写回运行日志）
- G16 tab：Flow Library 管理（查看/更新/删除 Plan 模板，删除二次确认）

启动：streamlit run src/clowder_analytics/web/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

from clowder_analytics.adapters.base import Dataset, compute_fingerprint
from clowder_analytics.adapters.csv import CsvAdapter
from clowder_analytics.adapters.excel import ExcelAdapter
from clowder_analytics.ai.fake import FakePlanGenerator, FakeReviewer
from clowder_analytics.flow_library.models import Template
from clowder_analytics.flow_library.store import FlowLibrary
from clowder_analytics.orchestrator.plan import Step
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

    # ===== G16: 顶层 tab——分析 / Flow Library 管理 =====
    tab_analyze, tab_manage = st.tabs(["🔍 分析", "📚 Flow Library 管理"])

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

    # ===== G16: 管理页先渲染（分析页有 early return，顺序靠 st.tabs 调用序保证显示）=====
    with tab_manage:
        _render_flow_library_manager(st.session_state.library)

    # ===== 中间：分析意图（tab_analyze 内）=====
    with tab_analyze:
        _render_analysis_tab(llm_choice, enable_review)


def _render_analysis_tab(llm_choice, enable_review: bool):
    """分析主流程（G16 抽出，供 tab_analyze 容器调用）"""
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
        # 进度展示：st.status 分阶段容器 + execute 进度条（替代原死转圈 spinner）
        from clowder_analytics.orchestrator.progress_display import StProgressHolder

        # G18：AI Reviewer 流式渲染——st.empty 占位，delta 到达时增量刷新，
        # 用户看到 AI 思考过程逐步展开而不是死等（节流防每 chunk 重渲染卡顿）
        review_placeholder = st.empty()
        stream_state = {"buf": [], "dirty": 0}

        def _on_review_delta(chunk: str) -> None:
            stream_state["buf"].append(chunk)
            stream_state["dirty"] += 1
            if stream_state["dirty"] >= 8:  # 每 ~8 chunk 刷一次（节流）
                try:
                    review_placeholder.markdown("".join(stream_state["buf"]))
                    stream_state["dirty"] = 0
                except Exception:
                    pass  # 渲染异常不反噬分析主流程

        with st.status("🚀 运行分析中...", expanded=True) as status:
            holder = StProgressHolder()
            holder.bind(status)
            # G14：按 sidebar 模型选择构造 generator/reviewer（真实 LLM / Fake）
            generator, reviewer = _build_ai_stack(llm_choice)
            result = run(
                question=question,
                dataset=ds,
                library=st.session_state.library,
                generator=generator,
                reviewer=reviewer,
                enable_review=enable_review,
                progress=holder.callback,
                on_review_delta=_on_review_delta,
            )
            status.update(
                label=f"✅ 运行完成（{result.duration_ms / 1000:.1f}s）",
                state="complete", expanded=False,
            )
        # 流式区最终定格：全文（结果区还有正式渲染，这里清掉避免重复）
        if result.review:
            review_placeholder.empty()
        else:
            review_placeholder.empty()
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
        # G18：reviewer 调用也计入（Plan 生成 + AI 报告各计 1）
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

    # G17 需求③：Plan 执行过程可见 + 默认折叠（每步成败/错误/图表产出）
    if result.log:
        with st.expander(
            f"🔍 执行过程（{sum(1 for s in result.log if s.get('ok'))}"
            f"/{len(result.log)} 步成功）",
            expanded=False,
        ):
            st.markdown(_format_run_log(result.log))

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


def _format_run_log(log: list[dict]) -> str:
    """把 executor run_log 渲染成 markdown 步骤表（G17 需求③ / G18 增强）

    每步一行：序号 + 成败标记 + op 名 + 人类可读摘要。
    G18 增强：args（用到的列/参数）+ shape 变化（行数变化）+ chart 维度。
    失败步显示错误原因。
    """
    if not log:
        return "_本次运行没有产生步骤日志_"
    lines = [
        f"{idx}. {'✅' if e.get('ok') else '❌'} `{e.get('step', '?')}`{_step_detail(e)}"
        for idx, e in enumerate(log, start=1)
    ]
    return "\n".join(lines)


def _shape_bits(entry: dict) -> str:
    """渲染数据形态变化：`33万行 → 20行`（shape_after 为 None 时只显示 before）"""
    before = entry.get("shape_before")
    after = entry.get("shape_after")
    if before is None:
        return ""
    if after is None or tuple(after) == tuple(before):
        return f" · {before[0]} 行"
    return f" · {tuple(before)[0]} 行 → {tuple(after)[0]} 行"


def _args_bits(entry: dict) -> str:
    """渲染本步参数：`按 brand 聚合 sales` 类摘要（列名优先，值太长截断）"""
    args = entry.get("args")
    if not isinstance(args, dict) or not args:
        return ""
    bits = []
    for k, v in args.items():
        if isinstance(v, (list, tuple)):
            val = "/".join(str(x) for x in v[:3])
        elif isinstance(v, dict):
            val = "/".join(str(x) for x in list(v.keys())[:3]) or str(v)
        else:
            val = str(v)
        if len(val) > 24:
            val = val[:24] + "…"
        bits.append(f"{k}={val}")
    return f" · {', '.join(bits)}" if bits else ""


def _step_detail(entry: dict) -> str:
    """从单条 run_log entry 提取摘要（G18 增强）

    成功步：args + shape 变化 + report 明细（chart 维度或 op 统计）。
    失败步：err（含 args 便于定位哪组参数失败）。
    旧格式 entry（无 args/shape，report 只有 chart_spec 字符串）向后兼容。
    """
    if not entry.get("ok"):
        err = entry.get("err")
        msg = f" — 失败：{err}" if err else " — 失败"
        return msg + _args_bits(entry)

    report = entry.get("report")
    report_bits = ""
    if isinstance(report, dict) and report:
        if "chart_spec" in report:
            chart_desc = [f"产出 {report['chart_spec']} 图"]
            for key in ("title", "x", "y"):
                if report.get(key):
                    chart_desc.append(f"{key}={report[key]}")
            report_bits = f" → {', '.join(chart_desc)}"
        else:
            bits = [f"{k}={v}" for k, v in list(report.items())[:2]]
            report_bits = f" — {', '.join(bits)}"

    return f"{report_bits}{_args_bits(entry)}{_shape_bits(entry)}"


# ===== G16: Flow Library 管理（查看/更新/删除）=====

def _parse_steps_yaml(text: str) -> list[Step]:
    """把编辑框里的 YAML steps 文本解析为 Step 列表

    Raises:
        ValueError: YAML 非法 / 顶层不是列表 / 列表项缺 op
    """
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ValueError(f"steps YAML 解析失败: {e}") from e
    if not isinstance(data, list):
        raise ValueError("steps 必须是 YAML 列表（- op: ... 开头）")
    steps = []
    for i, item in enumerate(data):
        if not isinstance(item, dict) or "op" not in item:
            raise ValueError(f"第 {i + 1} 项缺少 op 字段")
        steps.append(Step(op=item["op"], args=item.get("args") or {}))
    return steps


def _apply_template_edit(
    library: FlowLibrary,
    template_id: str,
    steps: list[Step],
    intent: str,
    reviewer_enabled: bool,
) -> Template:
    """应用模板编辑：只改业务字段，元字段从库中原模板读取保持一致

    G16 验收点：更新保 promoted_from_plan_id / stability 元字段一致——
    调用方（编辑表单）不接触元字段，本函数从存储读原值回填，杜绝覆盖丢失。

    Raises:
        KeyError: 模板不存在
    """
    original = library.load_template(template_id)
    if original is None:
        raise KeyError(f"模板不存在: {template_id}")
    updated = Template(
        template_id=template_id,
        intent=intent,
        schema_fingerprint=original.schema_fingerprint,
        steps=steps,
        reviewer_enabled=reviewer_enabled,
        fallback_strategy=original.fallback_strategy,
        created_at=original.created_at,
        promoted_from_plan_id=original.promoted_from_plan_id,
        stability=original.stability,
        confidence=original.confidence,
    )
    library.update_template(updated)
    return updated


def _render_flow_library_manager(library: FlowLibrary) -> None:
    """G16 Flow Library 管理页：查看/更新/删除模板与 Plan

    删除是破坏性操作 → 二次确认（session_state 记住待删 id，确认按钮才执行）。
    """
    st.subheader("📚 Flow Library 管理")

    tab_tpl, tab_plan = st.tabs(["A 轨模板", "B 轨 Plan"])

    # ---- A 轨模板 ----
    with tab_tpl:
        templates = library.list_templates()
        if not templates:
            st.info("暂无模板（运行分析后由晋升机制生成，或 cold_start 内置）")
        else:
            options = {f"{t.template_id}（{t.intent} / {t.stability}）": t.template_id for t in templates}
            selected_label = st.selectbox("选择模板", list(options.keys()), key="g16_tpl_select")
            tpl_id = options[selected_label]
            tpl = library.load_template(tpl_id)
            if tpl is None:
                st.error(f"模板加载失败: {tpl_id}")
                return

            col_info, col_meta = st.columns(2)
            with col_info:
                st.write(f"**意图**: {tpl.intent}")
                st.write(f"**Schema 指纹**: `{tpl.schema_fingerprint}`")
                st.write(f"**Reviewer**: {'开' if tpl.reviewer_enabled else '关'}")
            with col_meta:
                st.write(f"**stability**: `{tpl.stability}`")
                st.write(f"**promoted_from**: `{tpl.promoted_from_plan_id or '—'}`")
                st.write(f"**confidence**: {tpl.confidence}")

            st.write("**Steps**（YAML 编辑，保存后生效）:")
            steps_text = st.text_area(
                "steps",
                value=yaml.safe_dump(
                    [{"op": s.op, "args": s.args} for s in tpl.steps],
                    allow_unicode=True, sort_keys=False,
                ),
                height=200,
                key=f"g16_tpl_steps_{tpl_id}",
                label_visibility="collapsed",
            )
            edit_intent = st.text_input("意图", value=tpl.intent, key=f"g16_tpl_intent_{tpl_id}")
            edit_reviewer = st.checkbox("启用 Reviewer", value=tpl.reviewer_enabled, key=f"g16_tpl_rev_{tpl_id}")

            if st.button("💾 保存修改", key=f"g16_tpl_save_{tpl_id}", type="primary"):
                try:
                    steps = _parse_steps_yaml(steps_text)
                    _apply_template_edit(
                        library, template_id=tpl_id,
                        steps=steps, intent=edit_intent, reviewer_enabled=edit_reviewer,
                    )
                    st.success(f"模板 {tpl_id} 已更新（元字段保持不变）")
                    st.rerun()
                except ValueError as e:
                    st.error(f"保存失败: {e}")
                except KeyError as e:
                    st.error(f"保存失败: {e}")

            # 删除：二次确认状态机
            confirm_key = f"g16_tpl_del_confirm_{tpl_id}"
            if confirm_key not in st.session_state:
                st.session_state[confirm_key] = False
            if not st.session_state[confirm_key]:
                if st.button("🗑️ 删除模板", key=f"g16_tpl_del_{tpl_id}"):
                    st.session_state[confirm_key] = True
                    st.rerun()
            else:
                st.warning(f"确认删除模板 **{tpl_id}**？此操作不可恢复！")
                col_yes, col_no = st.columns(2)
                with col_yes:
                    if st.button("✅ 确认删除", key=f"g16_tpl_del_yes_{tpl_id}", type="primary"):
                        library.delete_template(tpl_id)
                        st.session_state[confirm_key] = False
                        st.success(f"模板 {tpl_id} 已删除")
                        st.rerun()
                with col_no:
                    if st.button("❌ 取消", key=f"g16_tpl_del_no_{tpl_id}"):
                        st.session_state[confirm_key] = False
                        st.rerun()

    # ---- B 轨 Plan ----
    with tab_plan:
        plans = library.list_plans()
        if not plans:
            st.info("暂无 Plan（兜底 LLM 生成后自动入库）")
        else:
            plan_options = {f"{p.plan_id}（{p.intent}）": p.plan_id for p in plans}
            plan_label = st.selectbox("选择 Plan", list(plan_options.keys()), key="g16_plan_select")
            plan_id = plan_options[plan_label]
            plan = library.load_plan(plan_id)
            if plan is None:
                st.error(f"Plan 加载失败: {plan_id}")
                return

            st.write(f"**意图**: {plan.intent}")
            st.write(f"**Schema 指纹**: `{plan.schema_fingerprint}`")
            st.write(f"**Fallback**: {plan.fallback_strategy}")
            st.json(
                [{"op": s.op, "args": s.args} for s in plan.steps],
                expanded=True,
            )

            # Plan 删除：二次确认状态机
            plan_confirm_key = f"g16_plan_del_confirm_{plan_id}"
            if plan_confirm_key not in st.session_state:
                st.session_state[plan_confirm_key] = False
            if not st.session_state[plan_confirm_key]:
                if st.button("🗑️ 删除 Plan", key=f"g16_plan_del_{plan_id}"):
                    st.session_state[plan_confirm_key] = True
                    st.rerun()
            else:
                st.warning(f"确认删除 Plan **{plan_id}**？此操作不可恢复！")
                col_yes, col_no = st.columns(2)
                with col_yes:
                    if st.button("✅ 确认删除", key=f"g16_plan_del_yes_{plan_id}", type="primary"):
                        library.delete_plan(plan_id)
                        st.session_state[plan_confirm_key] = False
                        st.success(f"Plan {plan_id} 已删除")
                        st.rerun()
                with col_no:
                    if st.button("❌ 取消", key=f"g16_plan_del_no_{plan_id}"):
                        st.session_state[plan_confirm_key] = False
                        st.rerun()


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
