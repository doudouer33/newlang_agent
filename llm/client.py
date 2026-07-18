"""
LLM 统一调用入口，强制 JSON 输出。

README「B 组 · LLM 封装」：给上层一个**只吐结构化对象**的口子。Agent 之间不传
自然语言，所以这里的核心方法 `complete_json` 一律返回一个 dict —— 模型再怎么啰嗦，
到 Agent 手里的都是干净的 JSON。

供应商：走 **OpenAI 兼容 SDK，指向 DeepSeek**（base_url = https://api.deepseek.com）。
DeepSeek 的 Chat Completions 接口与 OpenAI 同形，`response_format={"type":"json_object"}`
即 JSON 模式。默认模型 deepseek-v4-flash，均可用环境变量覆盖。

★ 密钥安全：绝不硬编码进源码。api_key 从参数或环境变量 `DEEPSEEK_API_KEY` 读取；
  仓库根目录的 `.env`（已 gitignore）会在导入时被自动加载进环境，方便本地直接跑。

两个实现：
  - DeepSeekClient：真调 DeepSeek。底层 OpenAI 客户端**懒构造**——没有密钥也能
    先把对象建出来，只有真发请求时才要密钥，这样导入、测试都不被密钥卡住。
  - StubLLMClient：离线桩。给定固定 dict 或一个 callable，不联网直接返回。
    测试用它，Planner 的「固定流程、不真调 LLM」最小版也用它。
"""
from __future__ import annotations

import copy
import json
import os
from abc import ABC, abstractmethod


# ---- 默认配置（均可用环境变量覆盖）----
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"


class LLMError(RuntimeError):
    """LLM 调用或输出解析失败。上层一律 catch 这个，不让底层异常裸奔。"""


def load_dotenv(path: str | None = None) -> None:
    """把仓库根目录 `.env` 里的 KEY=VALUE 灌进环境变量（不覆盖已存在的）。

    刻意手写、零依赖：只认最朴素的 `KEY=VALUE` 行，跳过空行和 `#` 注释，
    去掉值两侧成对的引号。不追求 dotenv 全部特性，够装个 API key 就行。
    """
    if path is None:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(os.path.dirname(here), ".env")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)          # 不覆盖：外部显式设的优先


# 导入本模块即尝试加载 .env，让本地开发「开箱即用」。
load_dotenv()


def _extract_json(text: str) -> dict:
    """把模型返回的文本解析成 dict。

    正常情况下 JSON 模式返回的就是纯 JSON；但为稳健起见，兜底剥掉可能的
    ```json ... ``` 代码围栏再解析。解析失败抛 LLMError，并带上原文片段便于排查。
    """
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1] if "\n" in raw else raw
        raw = raw.rsplit("```", 1)[0]
        if raw.lstrip().startswith("json"):
            raw = raw.lstrip()[4:]
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        snippet = text[:200].replace("\n", " ")
        raise LLMError(f"模型输出不是合法 JSON：{e}；原文开头：{snippet!r}") from e
    if not isinstance(obj, dict):
        raise LLMError(f"期望 JSON 对象，得到 {type(obj).__name__}")
    return obj


class LLMClient(ABC):
    """所有 LLM 客户端的统一接口：喂 prompt，吐一个 dict。"""

    @abstractmethod
    def complete_json(
        self, user: str, *, system: str | None = None, schema: dict | None = None
    ) -> dict:
        """给定用户内容（可选系统提示 / 期望 JSON schema），返回解析好的 dict。"""
        raise NotImplementedError


class DeepSeekClient(LLMClient):
    """真调 DeepSeek（OpenAI 兼容接口）。"""

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float | None = None,
        max_tokens: int = 4096,
        client=None,
    ):
        # 环境变量兜底，全部可覆盖。model/base_url 也读环境，方便换模型不改码。
        self.model = model or os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL)
        self.base_url = base_url or os.getenv("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL)
        self._api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.temperature = temperature
        self.max_tokens = max_tokens
        # 允许注入一个「鸭子类型」客户端（有 .chat.completions.create）——测试靠它离线。
        self._client = client

    def _get_client(self):
        """懒构造底层 OpenAI 客户端：第一次真发请求时才需要密钥。"""
        if self._client is None:
            if not self._api_key:
                raise LLMError(
                    "缺少 DeepSeek API key：设置环境变量 DEEPSEEK_API_KEY，"
                    "或在仓库根目录 .env 里写 DEEPSEEK_API_KEY=..."
                )
            try:
                from openai import OpenAI
            except ImportError as e:
                raise LLMError(
                    "未安装 openai 包：pip install openai（见 requirements.txt）"
                ) from e
            self._client = OpenAI(api_key=self._api_key, base_url=self.base_url)
        return self._client

    def complete_json(
        self, user: str, *, system: str | None = None, schema: dict | None = None
    ) -> dict:
        # DeepSeek 的 JSON 模式要求 prompt 里出现 “json” 字样，这里统一补一条系统指令；
        # 给了 schema 就把它也塞进系统提示，引导模型对齐字段（json_object 不强校验 schema）。
        directive = "只输出一个合法的 JSON 对象，不要任何多余文字或 Markdown 代码块。"
        if schema is not None:
            directive += "\n严格按以下 JSON schema 组织字段：\n" + json.dumps(
                schema, ensure_ascii=False
            )
        sys_prompt = directive if system is None else f"{system}\n\n{directive}"

        kwargs = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": self.max_tokens,
        }
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature

        try:
            resp = self._get_client().chat.completions.create(**kwargs)
        except LLMError:
            raise
        except Exception as e:                      # 网络错、鉴权错、限流……都收口成 LLMError
            raise LLMError(f"DeepSeek 调用失败：{type(e).__name__}: {e}") from e

        content = resp.choices[0].message.content
        if not content:
            raise LLMError("DeepSeek 返回空内容")
        return _extract_json(content)


class StubLLMClient(LLMClient):
    """离线桩：不联网，返回预置结果。测试与「不真调 LLM 的固定流程」都用它。

    - 传 dict：每次调用都返回它的浅拷贝；
    - 传 callable(user, system, schema) -> dict：按输入动态产出，可用来断言 prompt。
    """

    def __init__(self, response):
        self._response = response

    def complete_json(
        self, user: str, *, system: str | None = None, schema: dict | None = None
    ) -> dict:
        if callable(self._response):
            out = self._response(user, system, schema)
        else:
            out = copy.deepcopy(self._response)     # 深拷贝：调用方改嵌套结构不污染桩
        if not isinstance(out, dict):
            raise LLMError(f"Stub 应返回 dict，得到 {type(out).__name__}")
        return out


def default_client() -> LLMClient:
    """约定的默认客户端：真调 DeepSeek。上层要离线就自己换 StubLLMClient。"""
    return DeepSeekClient()
