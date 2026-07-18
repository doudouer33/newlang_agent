"""
LLM 客户端的测试：全部离线，不联网、不需要真密钥。

- StubLLMClient：直接验证桩行为。
- DeepSeekClient：注入一个「鸭子类型」假客户端（有 .chat.completions.create），
  拦下请求参数做断言、返回预置内容 —— 既验证我们发的请求形状对（JSON 模式、
  带 "json" 指令、schema 塞进系统提示），也验证响应解析对。

跑法（项目根目录下）：
    python tests/test_llm.py
    pytest tests/
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm import DeepSeekClient, LLMError, StubLLMClient      # noqa: E402
from llm.client import _extract_json                          # noqa: E402


# ---- 一个假的 OpenAI 兼容客户端：记录请求、返回预置内容 ----
class _FakeClient:
    def __init__(self, content, capture):
        self._content = content
        self._capture = capture
        self.chat = types.SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self._capture.update(kwargs)              # 把请求参数抓出来供断言
        message = types.SimpleNamespace(content=self._content)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


# ==================================================================
# _extract_json
# ==================================================================

def test_extract_plain_json():
    assert _extract_json('{"passes": ["dce"]}') == {"passes": ["dce"]}


def test_extract_json_from_code_fence():
    """兜底：模型偶尔套了 ```json 围栏也能解析出来。"""
    text = '```json\n{"a": 1}\n```'
    assert _extract_json(text) == {"a": 1}


def test_extract_json_rejects_garbage():
    try:
        _extract_json("这不是 JSON")
    except LLMError as e:
        assert "JSON" in str(e)
    else:
        raise AssertionError("非法 JSON 应抛 LLMError")


def test_extract_json_rejects_non_object():
    """顶层必须是对象，不能是数组/标量。"""
    try:
        _extract_json("[1, 2, 3]")
    except LLMError:
        pass
    else:
        raise AssertionError("非对象 JSON 应抛 LLMError")


# ==================================================================
# StubLLMClient
# ==================================================================

def test_stub_returns_fixed_dict():
    stub = StubLLMClient({"passes": ["const_fold", "dce"]})
    assert stub.complete_json("随便") == {"passes": ["const_fold", "dce"]}


def test_stub_fixed_dict_is_copied():
    """返回的是浅拷贝，调用方改了不污染桩内部的预置值。"""
    stub = StubLLMClient({"passes": []})
    out = stub.complete_json("x")
    out["passes"].append("dce")
    assert stub.complete_json("x") == {"passes": []}


def test_stub_callable_sees_prompt():
    """callable 形式可按输入动态产出，也能拿来断言 prompt。"""
    stub = StubLLMClient(lambda user, system, schema: {"echo": user})
    assert stub.complete_json("hello") == {"echo": "hello"}


# ==================================================================
# DeepSeekClient（注入假客户端，离线）
# ==================================================================

def test_deepseek_sends_json_mode_and_parses():
    capture = {}
    fake = _FakeClient('{"passes": ["dce"]}', capture)
    client = DeepSeekClient(model="deepseek-v4-flash", client=fake)

    result = client.complete_json("给我一个候选", system="你是优化器")

    assert result == {"passes": ["dce"]}
    assert capture["model"] == "deepseek-v4-flash"
    assert capture["response_format"] == {"type": "json_object"}
    # 两条消息：system 在前、user 在后
    roles = [m["role"] for m in capture["messages"]]
    assert roles == ["system", "user"]
    # DeepSeek 的 JSON 模式要求 prompt 里出现 “json” 字样
    assert "json" in capture["messages"][0]["content"].lower()
    # 用户内容原样传进去
    assert capture["messages"][1]["content"] == "给我一个候选"


def test_deepseek_embeds_schema_into_system_prompt():
    capture = {}
    fake = _FakeClient('{"ok": true}', capture)
    client = DeepSeekClient(client=fake)

    client.complete_json("x", schema={"type": "object", "properties": {"passes": {}}})

    sys_content = capture["messages"][0]["content"]
    assert "schema" in sys_content and "passes" in sys_content


def test_deepseek_missing_key_errors_on_call_not_construction():
    """没有密钥时：构造不炸（方便导入/测试），只有真发请求才报清楚。"""
    # 显式清掉可能从 .env 加载进来的 key，构造一个没有注入 client 的实例
    client = DeepSeekClient(api_key="")            # 空 key
    client._api_key = ""                            # 确保不走 .env 兜底
    try:
        client.complete_json("x")
    except LLMError as e:
        assert "key" in str(e).lower() or "密钥" in str(e)
    else:
        raise AssertionError("缺密钥应在调用时抛 LLMError")


def main():
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ✅ {name}")
        except AssertionError as e:
            failed += 1
            print(f"  ❌ {name}: {e or 'assertion failed'}")
    print(f"\n{len(tests) - failed}/{len(tests)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
