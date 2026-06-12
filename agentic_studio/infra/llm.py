"""模型解析 —— 把 "provider:model" 解析成 deepagents 可用的 model。

deepagents `model=` 接受 str（走 langchain init_chat_model）或 BaseChatModel 实例。
- anthropic / openai / google 等：直接返回 str，交给 init_chat_model。
- **deepseek**：走 OpenAI 兼容端点（DeepSeek API 与 OpenAI 兼容），用 langchain-openai 的
  ChatOpenAI + base_url，**无需额外依赖**，返回实例。

⚠️ 架构 §2.5-D：DeepSeek 属"国产模型"路线，deepagents 重 harness 对其工具调用/结构化输出
稳定性的依赖是已知风险。`deepseek-chat`(V3) 支持 function calling；`deepseek-reasoner`(R1)
工具调用支持弱，不建议跑 agentic loop。
"""

from __future__ import annotations

import os
from typing import Any

DEEPSEEK_DEFAULT_BASE = "https://api.deepseek.com"


def resolve_model(spec: str, *, temperature: float = 0.0) -> Any:
    """spec 形如 'deepseek:deepseek-chat' / 'anthropic:claude-...' / 'openai:gpt-...'。"""
    provider, _, name = spec.partition(":")
    provider = provider.lower()

    if provider == "deepseek":
        from langchain_openai import ChatOpenAI

        key = os.environ.get("DEEPSEEK_API_KEY")
        return ChatOpenAI(
            model=name or "deepseek-chat",
            base_url=os.environ.get("DEEPSEEK_BASE_URL", DEEPSEEK_DEFAULT_BASE),
            api_key=key,
            temperature=temperature,
        )

    # 其余 provider 交给 deepagents / init_chat_model
    return spec


def get_chat_model(spec: str, *, temperature: float = 0.3) -> Any:
    """总是返回可直接 .ainvoke 的 chat model（workflow 编排器用，非 deepagents 路径）。

    deepseek → ChatOpenAI 实例；其余 → init_chat_model(spec)。
    """
    m = resolve_model(spec, temperature=temperature)
    if isinstance(m, str):
        from langchain.chat_models import init_chat_model

        return init_chat_model(m, temperature=temperature)
    return m
