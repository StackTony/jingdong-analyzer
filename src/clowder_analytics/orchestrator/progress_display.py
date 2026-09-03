"""运行进度展示（Web / CLI 共用渲染逻辑）

需求背景：运行分析（尤其真实 LLM 路径，单次 5-30 秒）期间没有任何进度反馈，
用户只看到死转圈。run()/execute() 已暴露 progress 回调（见 orchestrator/run.py），
本模块把它渲染成人类可读的进度：

Web（Streamlit）：
    holder = StProgressHolder()
    result = run(..., progress=holder.callback)
    holder.finish(success=True)
    - st.status 容器分阶段展示（✅ 已完成 / ⏳ 进行中）
    - execute 阶段附 st.progress 进度条 + 当前 op 名
    - llm 阶段展开显示"等待模型响应"提示

CLI：
    cb = CliProgressCallback()
    result = run(..., progress=cb)
    - 每阶段一行 "[2/5] ⏳ LLM 生成 Plan 中..."
    - execute 阶段逐步打印

阶段定义（见 run() docstring）：
    route → (template | plan | llm) → execute(1..N/N) → review → promote
"""
from __future__ import annotations

# 阶段中文名 + 图标（渲染用）
STAGE_LABELS = {
    "route": "🧭 路由匹配",
    "template": "📋 模板命中",
    "plan": "📦 Plan 命中",
    "llm": "🤖 LLM 生成 Plan",
    "execute": "⚙️ 执行分析步骤",
    "review": "📝 AI Reviewer",
    "promote": "🌱 自进化检查",
}


def format_stage(stage: str, current: int, total: int,
                 detail: str | None = None) -> str:
    """格式化单条进度为人类可读行（CLI 直接打印 / Web status label 用）"""
    label = STAGE_LABELS.get(stage, stage)
    if stage == "execute" and total > 1:
        base = f"{label} ({current}/{total})"
    else:
        base = label
    if detail:
        return f"{base} — {detail}"
    return base


class StProgressHolder:
    """Streamlit 进度渲染器

    用法（web/app.py）：
        with st.status("🚀 运行分析中...", expanded=True) as status:
            holder = StProgressHolder()
            holder.bind(status)
            result = run(..., progress=holder.callback)
            status.update(label="✅ 运行完成", state="complete", expanded=False)

    渲染策略：
    - 非 execute 阶段：st.status 容器内追加一行（容器 append-only，无法回改）
    - execute 阶段：单个 st.progress 进度条，text 实时显示当前步骤
      （不逐行追加——避免行序与进度条交错错乱）
    - 阶段完成态由 st.status 容器 label 统一表达（✅ 运行完成）
    """

    def __init__(self):
        self._bar = None  # execute 阶段进度条（懒创建，仅一个）
        self._container = None

    def bind(self, container) -> None:
        """绑定 st.status 容器（后续 st 元素写在容器内）"""
        self._container = container

    def callback(self, stage: str, current: int, total: int,
                 detail: str | None = None) -> None:
        import streamlit as st

        target = self._container if self._container is not None else st

        # execute 阶段：只刷新进度条，不追加行
        if stage == "execute":
            if self._bar is None:
                self._bar = target.progress(0.0, text="准备执行...")
            frac = min(current / total, 1.0) if total else 0.0
            self._bar.progress(frac, text=format_stage(stage, current, total, detail))
            return

        # 其他阶段：追加一行
        target.write(format_stage(stage, current, total, detail))


class CliProgressCallback:
    """CLI 进度回调：每阶段一行打印到 stderr（不污染 stdout 的结果输出）"""

    def __init__(self, stream=None):
        import sys
        self._stream = stream or sys.stderr

    def callback(self, stage: str, current: int, total: int,
                 detail: str | None = None) -> None:
        # execute 每步一行（op 数通常 < 8，不刷屏）
        print(format_stage(stage, current, total, detail), file=self._stream,
              flush=True)
