"""F002 P3+ 真实 LLM Provider（spec §5.3）

参考 opencode 配置：csi provider 是 OpenAI 兼容协议（chat completions）。
apiKey 配置主路径 = 直填 api_key 字段（铲屎官偏好：conf 里直接配 key）。
公开仓库安全约定：真实 key 只写 ai_providers.local.yaml（gitignored），
入库的 ai_providers.yaml 只留占位符（sk-xxx）；api_key_env 环境变量为兜底。

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

    def chat_stream(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ):
        """流式 chat：逐 chunk yield assistant 文本片段（G18）

        默认实现回落到非流式 chat()，把全文一次性 yield——
        子类只需在支持流式协议时覆写（如 OpenAICompatibleProvider 用 stream=True）。
        这样 Fake/Mock provider 不用改就能跑流式链路。

        Yields:
            文本片段（拼接后等于 chat() 的返回值）
        """
        yield self.chat(messages, temperature=temperature, max_tokens=max_tokens)


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

    def chat_stream(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ):
        """流式 chat（G18）：stream=True 逐 chunk yield 文本片段

        用于 AI Reviewer 报告流式渲染——用户不再盯着死等，
        模型边生成边看到内容。空 delta chunk（role 首块 / usage 尾块）跳过。
        """
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
        stream = client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            text = getattr(delta, "content", None)
            if text:
                yield text


# ===== 配置加载 =====

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "ai_providers.yaml"
_LOCAL_CONFIG_PATH = _CONFIG_PATH.parent / "ai_providers.local.yaml"
_CONFIG_CACHE: dict[str, Any] | None = None


def _deep_merge(base: dict, override: dict) -> dict:
    """递归深合并：override 覆盖 base，嵌套 dict 合并不整体替换"""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _load_yaml_config() -> dict[str, Any]:
    """加载 ai_providers.yaml（缓存）+ ai_providers.local.yaml 深合并覆盖

    两层配置（G15）：
    - 主配置 ai_providers.yaml：git 跟踪，api_key 直填占位符（sk-xxx 模板），
      api_key_env 作兜底（公开仓库不落真 key）
    - local 配置 ai_providers.local.yaml：gitignored，直填真实 api_key 深合并
      覆盖占位符（铲屎官偏好：conf 里直接配 key，仓库只留模板）
    """
    global _CONFIG_CACHE
    if _CONFIG_CACHE is None:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            _CONFIG_CACHE = yaml.safe_load(f) or {}
        if _LOCAL_CONFIG_PATH.exists():
            with open(_LOCAL_CONFIG_PATH, encoding="utf-8") as f:
                local_cfg = yaml.safe_load(f) or {}
            _CONFIG_CACHE = _deep_merge(_CONFIG_CACHE, local_cfg)
    return _CONFIG_CACHE


def load_provider(name: str | None = None, model: str | None = None) -> LLMProvider:
    """按配置加载 provider

    Args:
        name: provider 名（None 取 default_provider，default 不存在时取第一个）
        model: provider 下的 model id（None 取 default_model 或第一个 model）

    Returns:
        LLMProvider 实例

    Raises:
        KeyError: provider 名不存在 / model 不存在
        RuntimeError: apiKey 未配置（既无 api_key 直填也无 api_key_env 环境变量）
        NotImplementedError: openai SDK 未装 / 未知 protocol

    支持两种 yaml 格式：
    - 新格式（多 model）：providers.<name>.models.<model_id> map 结构
    - 老格式（单 model）：providers.<name>.model 顶层字段（向后兼容）

    apiKey 两种配置方式（主路径 = 直填 api_key）：
    - api_key: sk-xxx（直填，AI SDK 风格，优先；真实 key 写 local.yaml 不入库）
    - api_key_env: ENV_NAME（兜底，走环境变量，key 不入库）
    """
    cfg = _load_yaml_config()
    if name is None:
        name = get_default_provider_name()
    providers = cfg.get("providers", {})
    if name not in providers:
        raise KeyError(f"未知 provider: {name}；可用: {list(providers.keys())}")

    p = providers[name]
    api_key = _resolve_api_key(p, name)
    if not api_key:
        api_key_env = p.get("api_key_env", f"{name.upper()}_API_KEY")
        raise RuntimeError(
            f"Provider {name} 的 apiKey 未配置。"
            f"请在 ai_providers.local.yaml 写 api_key: <真实 key>（不入库），"
            f"或 export {api_key_env}=<真实 key> 后重试。"
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


def _is_placeholder_key(value: str) -> bool:
    """判断 api_key 值是否是占位符（sk-xxx 之类的模板占位，而非真 key）

    入库模板 ai_providers.yaml 直填 api_key 时用的是占位符；识别它才能让
    load_provider 继续回退 env / local.yaml 兜底，而不是把 "sk-xxx" 当真 key 用。
    """
    stripped = str(value).strip()
    if not stripped:
        return True
    low = stripped.lower()
    return low.startswith(("sk-xxx", "sk-your", "sk-abc"))


def _resolve_api_key(provider_cfg: dict, name: str) -> str:
    """解析 apiKey：直填 api_key 优先，否则回退 api_key_env 环境变量

    主路径 = 直填 api_key（铲屎官偏好：conf 里直接配 key）。
    直填的是占位符（sk-xxx）时视为未配置，回退 api_key_env（若提供），
    两条都空则由 load_provider 报明确的"未配置"错误。

    api_key_env 是兜底（私有 key 不入库写法），不再是推荐主路径。
    """
    # 1. 直填 api_key（主路径；占位符视为未配置，静默放行）
    direct = provider_cfg.get("api_key", "")
    if direct and not _is_placeholder_key(direct):
        return direct
    # 2. 回退 api_key_env 环境变量（兜底）
    api_key_env = provider_cfg.get("api_key_env", f"{name.upper()}_API_KEY")
    # 值校验（LL-049 现场复现防护）：api_key_env 是环境变量的名字，
    # 不是 key 本身。填成 sk-xxx 说明把 key 填错了字段，当场指出而不是
    # 生成 "export sk-xxx=sk-xxx" 这种误导报错。
    if str(api_key_env).startswith("sk-"):
        raise RuntimeError(
            f"Provider {name} 的 api_key_env 值 '{api_key_env[:12]}...' 看起来像 key 本身。"
            f"api_key_env 填的是环境变量的名字（如 EULER_Y_API_KEY）；"
            f"要直填 key 请用 api_key 字段（建议写在 ai_providers.local.yaml，不入库）。"
        )
    return os.environ.get(api_key_env, "")


def get_default_provider_name() -> str:
    """取 default_provider；指向不存在的 provider 时兜底取第一个

    铲屎官场景：yaml 里 default_provider: csi 但 csi provider 已删
    → 不应 KeyError，应兜底到第一个可用 provider。
    """
    cfg = _load_yaml_config()
    providers = cfg.get("providers", {})
    default = cfg.get("default_provider")
    if default and default in providers:
        return default
    if providers:
        return next(iter(providers))
    raise KeyError("ai_providers.yaml 未配置任何 provider")


def list_providers() -> list[dict]:
    """枚举所有 provider 和 model（页面展示 / 模型切换用）

    Returns:
        [{"name": "euler-y", "display_name": "csi",
          "models": ["GLM-5.3-Flash", "GLM-5.3", ...],
          "default_model": "GLM-5.3-Flash | None"}, ...]

    老格式顶层 model 字段也归一到 models 列表里。
    """
    cfg = _load_yaml_config()
    providers = cfg.get("providers", {})
    result = []
    for name, p in providers.items():
        models_map = p.get("models")
        if models_map is not None:
            models = list(models_map.keys())
            default_model = p.get("default_model")
        else:
            # 老格式：顶层 model
            models = [p["model"]] if "model" in p else []
            default_model = models[0] if models else None
        result.append({
            "name": name,
            "display_name": p.get("name", name),
            "models": models,
            "default_model": default_model,
        })
    return result


def get_prompt_section(section: str) -> str:
    """获取 yaml 中的 prompt 段（plan_generator / reviewer）"""
    cfg = _load_yaml_config()
    section_data = cfg.get(section, {})
    return section_data.get("system_prompt", "")
