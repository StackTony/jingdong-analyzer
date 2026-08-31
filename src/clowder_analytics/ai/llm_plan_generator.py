"""F002 P3+ 真实 LLM Plan 生成器（spec §5.1）

LLMPlanGenerator 用 LLMProvider 生成 Plan：
1. 构造 prompt：system（角色 + 约束 + 输出格式）+ user（question + schema 摘要 + 样本 + op 清单）
2. 调 LLM，要求输出严格 JSON
3. JSON schema 校验，失败重试一次（spec §5.1）
4. 解析为 Plan 对象

op 清单来源：executor 的 op_registry
"""
from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pandas as pd

from clowder_analytics.adapters.base import Dataset
from clowder_analytics.ai.base import AIPlanGenerator
from clowder_analytics.ai.llm_provider import LLMProvider, get_prompt_section, load_provider
from clowder_analytics.atomic.op_spec import format_op_specs_for_llm
from clowder_analytics.orchestrator.executor import get_op_registry
from clowder_analytics.orchestrator.plan import Plan, Step


class LLMPlanGenerator(AIPlanGenerator):
    """用真实 LLM 生成 Plan（spec §5.1）

    构造：
        provider = load_provider("csi")
        gen = LLMPlanGenerator(provider=provider)
        plan = gen.generate(question, dataset, intent)
    """

    def __init__(self, provider: LLMProvider | None = None):
        self.provider = provider or load_provider()
        self._op_registry = get_op_registry()

    def generate(self, question: str, dataset: Dataset, intent: str | None = None) -> Plan:
        # 构造 prompt
        system_prompt = get_prompt_section("plan_generator")
        user_prompt = self._build_user_prompt(question, dataset, intent)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # 调 LLM，要求 JSON 输出
        plan_dict = self._call_with_retry(messages)

        return Plan.from_dict(plan_dict)

    def _build_user_prompt(
        self, question: str, dataset: Dataset, intent: str | None,
    ) -> str:
        df = dataset.df
        # schema 摘要
        cols_info = []
        for c in df.columns:
            dtype = str(df[c].dtype)
            sample = df[c].dropna().head(3).tolist()
            cols_info.append(f"- {c} ({dtype}): 样本 {sample}")
        cols_block = "\n".join(cols_info)

        # op 清单 + args schema（spec §4.1）
        ops_block = format_op_specs_for_llm()

        # 统计信息
        stats_block = ""
        numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        if numeric_cols:
            stats_lines = []
            for c in numeric_cols[:5]:
                s = df[c].dropna()
                stats_lines.append(
                    f"- {c}: mean={s.mean():.2f}, std={s.std():.2f}, "
                    f"range=[{s.min():.2f}, {s.max():.2f}]"
                )
            stats_block = "\n".join(stats_lines)

        intent_str = intent or "未识别（请推断）"

        return f"""## 用户问题
{question}

## 意图
{intent_str}

## Schema 指纹
{dataset.schema_fingerprint}

## 列信息
{cols_block}

## 数值统计
{stats_block or "无数值列"}

## 可用原子能力清单（含 args schema）

{ops_block}

## 输出要求
1. 生成一个 Plan JSON（仅 JSON，不要任何额外文字）
2. **严格按上面 args schema 的字段名 / 类型 / enum 填 args**——
   不要自创字段名（如用 columns 不是 fields，用 group_by 不是 dimensions）
3. plan_id 用 "{intent or 'gen'}-{uuid4().hex[:8]}"
4. schema_fingerprint 必须等于上面给出的指纹
5. steps 数组按执行顺序排列，每个 step 含 op + args
6. 每个原子能力都是单一职责纯函数，输入输出可序列化
"""

    def _call_with_retry(
        self, messages: list[dict[str, str]], max_retries: int = 2,
    ) -> dict[str, Any]:
        """调 LLM + JSON 校验 + 失败重试一次（spec §5.1）

        max_tokens 从 provider.config 读（yaml 配置生效），不硬编码。
        关羽 P2-1 修复：原硬编码 2000 覆盖 yaml 的 4000。
        """
        # 从 provider config 读 max_tokens（yaml 配置生效）
        config_max_tokens = getattr(getattr(self.provider, "config", None), "max_tokens", 2000)
        last_err = None
        for attempt in range(max_retries):
            try:
                content = self.provider.chat(
                    messages=messages,
                    temperature=0.3,
                    max_tokens=config_max_tokens,
                    response_format={"type": "json_object"},
                )
                plan_dict = self._parse_json(content)
                self._validate_plan(plan_dict)
                return plan_dict
            except (ValueError, json.JSONDecodeError, KeyError) as e:
                last_err = e
                # 重试时附加错误反馈
                messages = messages + [
                    {"role": "assistant", "content": content if attempt == 0 else ""},
                    {"role": "user", "content": f"上次输出格式错误：{e}。请只输出有效 JSON。"},
                ]
                continue
        raise RuntimeError(f"LLM 输出 JSON 校验失败 {max_retries} 次：{last_err}")

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        """容错解析 LLM 输出为 JSON

        - 去除可能的 ```json ... ``` 包裹
        - 去除前后非 JSON 文字
        """
        s = content.strip()
        # 去 markdown code fence
        if s.startswith("```"):
            lines = s.split("\n")
            # 去首行 ```xxx 和末行 ```
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            s = "\n".join(lines)
        # 找第一个 { 和最后一个 }
        first = s.find("{")
        last = s.rfind("}")
        if first == -1 or last == -1:
            raise ValueError(f"LLM 输出无 JSON 对象：{content[:200]}")
        s = s[first:last+1]
        return json.loads(s)

    @staticmethod
    def _validate_plan(d: dict[str, Any]) -> None:
        """Plan JSON schema 校验（spec §5.1）"""
        if "plan_id" not in d:
            raise KeyError("plan_id 缺失")
        if "intent" not in d:
            raise KeyError("intent 缺失")
        if "steps" not in d or not isinstance(d["steps"], list):
            raise KeyError("steps 缺失或非 list")
        for i, s in enumerate(d["steps"]):
            if "op" not in s:
                raise KeyError(f"steps[{i}] 缺 op 字段")
