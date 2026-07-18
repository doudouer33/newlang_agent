"""LLM 封装（B 组）。统一调用入口 + 强制 JSON 输出。

供应商为 DeepSeek（走 OpenAI 兼容 SDK）。上层只依赖 `LLMClient` 抽象和
`complete_json` 这一个方法，换供应商只改这个包，不动 Agent。
"""
from .client import (
    DeepSeekClient,
    LLMClient,
    LLMError,
    StubLLMClient,
    default_client,
    load_dotenv,
)

__all__ = [
    "LLMClient",
    "DeepSeekClient",
    "StubLLMClient",
    "LLMError",
    "default_client",
    "load_dotenv",
]
