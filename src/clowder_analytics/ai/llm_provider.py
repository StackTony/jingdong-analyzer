"""F002 P3+ 真实 LLM Provider（spec §5.3）

参考 opencode 配置：csi provider 是 OpenAI 兼容协议（chat completions）。
apiKey 不入库，走环境变量（spec §5.3 安全策略）。

LLMProvider 抽象：
- chat(messages, **opts) -> str

OpenAICompatibleProvider：用 openai SDK（已装则用，未装抛 NotImplementedError）
- 适配所有 OpenAI 兼容 endpoint（csi / 任意 OpenAI-compatible server）

load_provider(name=None) -> LLMProvider：按 yaml 配置加载
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ===== LLMProvider 抽象 =====

class LLMProvider(ABC):
    """LLM 调用抽象"""

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 2000,
        response_format: dict | None = None,
    ) -> str:
        """发送 chat 消息，返回 assistant 文本

        Args:
            messages: OpenAI 格式 [{"role": "system"|"user"|"assistant", "content": "..."}]
            temperature: 0=确定性，1=创造性
            max_tokens: 输出上限
            response_format: {"type": "json_object"} 强制 JSON 输出（如支持）

        Returns:
            assistant 文本
        """
        raise NotImplementedError


# ===== Provider 配置数据类 =====

@dataclass
class ProviderConfig:
    name: str
    base_url: str
    api_key: str  # 从 env 读出来填这里
    model: str
    protocol: str = "openai"
    temperature: float = 0.3
    max_tokens: int = 2000
    timeout_seconds: int = 60


# ===== OpenAI 兼容 Provider =====

class OpenAICompatibleProvider(LLMProvider):
    """OpenAI 兼容协议的 Provider（chat completions）

    适配 csi.ai / Azure OpenAI / 本地 vLLM / 任意 OpenAI-compatible endpoint
    """

    def __init__(self, config: ProviderConfig):
        self.config = config

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 2000,
        response_format: dict | None = None,
    ) -> str:
        try:
            from openai import OpenAI
        except ImportError as e:
            raise NotImplementedError(
                "LLM Provider 需要 openai SDK：pip install openai"
            ) from e

        client = OpenAI(
            base_url=self.config.base_url,
            api_key=self.config.api_key,
            timeout=self.config.timeout_seconds,
        )
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        # 部分 endpoint 支持 response_format
        if response_format is not None:
            kwargs["response_format"] = response_format

        resp = client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""


# ===== 配置加载 =====

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "ai_providers.yaml"
_CONFIG_CACHE: dict[str, Any] | None = None


def _load_yaml_config() -> dict[str, Any]:
    """加载 ai_providers.yaml（缓存）"""
    global _CONFIG_CACHE
    if _CONFIG_CACHE is None:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            _CONFIG_CACHE = yaml.safe_load(f)
    return _CONFIG_CACHE


def load_provider(name: str | None = None, model: str | None = None) -> LLMProvider:
    """按配置加载 provider

    Args:
        name: provider 名（None 取 default_provider）
        model: provider 下的 model id（None 取 default_model 或第一个 model）

    Returns:
        LLMProvider 实例

    Raises:
        KeyError: provider 名不存在 / model 不存在
        RuntimeError: apiKey 环境变量未设
        NotImplementedError: openai SDK 未装 / 未知 protocol

    支持两种 yaml 格式：
    - 新格式（多 model）：providers.<name>.models.<model_id> map 结构
    - 老格式（单 model）：providers.<name>.model 顶层字段（向后兼容）
    """
    cfg = _load_yaml_config()
    if name is None:
        name = cfg.get("default_provider", "csi")
    providers = cfg.get("providers", {})
    if name not in providers:
        raise KeyError(f"未知 provider: {name}；可用: {list(providers.keys())}")

    p = providers[name]
    api_key_env = p.get("api_key_env", f"{name.upper()}_API_KEY")
    api_key = os.environ.get(api_key_env, "")
    if not api_key:
        raise RuntimeError(
            f"Provider {name} 的 apiKey 环境变量 {api_key_env} 未设。"
            f"请 export {api_key_env}=sk-xxx 后重试。"
        )

    # 解析 model 配置（支持新格式 models map + 老格式顶层 model）
    model_id, model_cfg = _resolve_model(p, model)

    config = ProviderConfig(
        name=name,
        base_url=p["base_url"],
        api_key=api_key,
        model=model_id,
        protocol=p.get("protocol", "openai"),
        temperature=model_cfg.get("temperature", p.get("temperature", 0.3)),
        max_tokens=model_cfg.get("max_tokens", p.get("max_tokens", 2000)),
        timeout_seconds=p.get("timeout_seconds", 60),
    )

    if config.protocol == "openai":
        return OpenAICompatibleProvider(config)
    raise NotImplementedError(f"未知 protocol: {config.protocol}")


def _resolve_model(provider_cfg: dict, requested_model: str | None) -> tuple[str, dict]:
    """从 provider 配置解析 model_id 和 model 配置

    新格式：providers.<name>.models.<model_id> map 结构（支持多 model）
    老格式：providers.<name>.model 顶层单字段（向后兼容）

    Args:
        provider_cfg: provider 的 yaml 配置 dict
        requested_model: 用户指定的 model id，None 时取 default

    Returns:
        (model_id, model_config_dict)——model_config 可为空 dict
    """
    models = provider_cfg.get("models")
    if models is not None:
        # 新格式：多 model
        if requested_model is not None:
            if requested_model not in models:
                raise KeyError(
                    f"Provider {provider_cfg.get('name', '')} 下无 model: {requested_model}；"
                    f"可用: {list(models.keys())}"
                )
            return requested_model, models[requested_model] or {}
        # 未指定 model：取 default_model 或第一个
        default_model = provider_cfg.get("default_model")
        if default_model and default_model in models:
            return default_model, models[default_model] or {}
        # 无 default_model 取第一个
        first = next(iter(models))
        return first, models[first] or {}

    # 老格式：顶层 model 字段
    if "model" in provider_cfg:
        return provider_cfg["model"], {}

    raise KeyError(f"Provider 配置缺少 model / models 字段")


def get_prompt_section(section: str) -> str:
    """获取 yaml 中的 prompt 段（plan_generator / reviewer）"""
    cfg = _load_yaml_config()
    section_data = cfg.get(section, {})
    return section_data.get("system_prompt", "")
