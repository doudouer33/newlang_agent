"""
OptimizerAgent 的测试：全部离线，用 StubLLMClient 喂预置的 LLM 输出。

重点验证「清洗」这一步 —— LLM 草案不可信，落成 Candidate 前必须过校验：
未注册的 pass 名要丢、空组合要丢、重复要去、数量要截断；产出的 Candidate 必须
是 origin="llm" 的未执行状态。

跑法（项目根目录下）：
    python tests/test_agents.py
    pytest tests/
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import OptimizerAgent                               # noqa: E402
from contracts import Candidate                                 # noqa: E402
from llm import StubLLMClient                                   # noqa: E402

# 一段真能编译的源码，让 _render_ir 走通真实工具链
SRC = "let n = 100;\nlet k = 3;\nlet s = 0;\nlet i = 0;\nwhile (i < n) { s = s + k * n; i = i + 1; }\nprint s;\n"


def _agent(llm_response):
    return OptimizerAgent(llm=StubLLMClient(llm_response))


def test_produces_llm_candidates():
    """正常路径：三个合法候选 → 三个 origin='llm'、未执行的 Candidate。"""
    stub = {"candidates": [
        {"passes": ["licm", "const_fold", "dce"], "reason": "外提再清理"},
        {"passes": ["const_fold", "dce"], "reason": "折叠后删死代码"},
        {"passes": ["dce"], "reason": "只删死代码"},
    ]}
    out = _agent(stub).run({"program": "licm_demo", "source": SRC})
    cands = out["candidates"]
    assert len(cands) == 3
    assert all(isinstance(c, Candidate) for c in cands)
    assert all(c.origin == "llm" for c in cands)
    assert all(c.compiled is False and c.instr_count is None for c in cands)   # 未执行
    assert cands[0].passes == ["licm", "const_fold", "dce"]


def test_unknown_passes_are_filtered():
    """LLM 瞎编的 pass 名要被剔除，只保留注册过的。"""
    stub = {"candidates": [{"passes": ["bogus", "dce", "made_up"]}]}
    out = _agent(stub).run({"program": "p", "source": SRC})
    assert len(out["candidates"]) == 1
    assert out["candidates"][0].passes == ["dce"]              # 只剩合法的


def test_empty_combo_dropped():
    """全被过滤成空的候选（= baseline）不进 llm 档。"""
    stub = {"candidates": [{"passes": ["nope"]}, {"passes": []}]}
    out = _agent(stub).run({"program": "p", "source": SRC})
    assert out["candidates"] == []


def test_duplicate_pass_sequences_deduped():
    """同一 pass 序列只保留一个；顺序不同算不同候选。"""
    stub = {"candidates": [
        {"passes": ["const_fold", "dce"]},
        {"passes": ["const_fold", "dce"]},     # 重复 → 去掉
        {"passes": ["dce", "const_fold"]},     # 顺序不同 → 保留
    ]}
    out = _agent(stub).run({"program": "p", "source": SRC})
    seqs = [c.passes for c in out["candidates"]]
    assert seqs == [["const_fold", "dce"], ["dce", "const_fold"]]


def test_respects_candidate_limit():
    """最多返回 n 个候选。"""
    stub = {"candidates": [{"passes": ["dce"]}, {"passes": ["licm"]},
                           {"passes": ["const_fold"]}, {"passes": ["const_fold", "dce"]}]}
    out = _agent(stub).run({"program": "p", "source": SRC, "n": 2})
    assert len(out["candidates"]) == 2


def test_prompt_contains_ir_and_passes_and_feedback():
    """用 callable 桩拦下 prompt，验证 IR、可用 pass、反馈都进了 user 内容。"""
    captured = {}

    def fake(user, system, schema):
        captured["user"] = user
        captured["system"] = system
        return {"candidates": [{"passes": ["dce"]}]}

    OptimizerAgent(llm=StubLLMClient(fake)).run(
        {"program": "licm_demo", "source": SRC, "feedback": "上一轮 licm 没收益，换思路"}
    )
    user = captured["user"]
    assert "licm_demo" in user                    # 程序名
    assert "const_fold" in user and "licm" in user  # 可用 pass 列表
    assert "t1 = k * n" in user                   # 真实 IR 被编进 prompt
    assert "上一轮 licm 没收益" in user            # 反馈被带上
    assert "优化" in captured["system"]            # 系统提示来自 optimize.txt


def test_llm_error_returns_empty_not_raise():
    """LLM 失败要收口成空候选 + error，不能把异常抛给编排循环。"""
    from llm import LLMError

    def boom(user, system, schema):
        raise LLMError("模拟网络错")

    out = OptimizerAgent(llm=StubLLMClient(boom)).run({"program": "p", "source": SRC})
    assert out["candidates"] == []
    assert "模拟网络错" in out["error"]


def test_malformed_llm_output_tolerated():
    """LLM 返回缺 candidates 键 / 奇形怪状也不炸，尽力清洗。"""
    out = _agent({"garbage": 1}).run({"program": "p", "source": SRC})
    assert out["candidates"] == []
    # 直接给 pass 数组（没包 dict）也能认
    out2 = _agent({"candidates": [["dce", "licm"]]}).run({"program": "p", "source": SRC})
    assert out2["candidates"][0].passes == ["dce", "licm"]


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
