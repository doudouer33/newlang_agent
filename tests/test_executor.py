"""
Executor 的测试。

主路径直接驱动**真实工具链**（build/run_tests/run_bench 全是本地纯计算，不联网），
这样测的是「候选真的被编译、被测、被计时」的端到端事实；另有一个注入的假 Router
用来断言「按 build→run_tests→run_bench 的顺序调工具」和落盘行为。

跑法（项目根目录下）：
    python tests/test_executor.py
    pytest tests/
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import Executor                                     # noqa: E402
from contracts import Candidate                                 # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)


def _sample(name):
    with open(os.path.join(_ROOT, "lang", "samples", name), encoding="utf-8") as f:
        return f.read()


LOOP_SUM = "let n=10; let i=1; let sum=0;\nwhile (i<=n){ sum=sum+i; i=i+1; }\nprint sum;  // expect: 55\n"


def _cand(source, passes, origin="llm"):
    return Candidate(id=f"t#{'+'.join(passes) or 'base'}",
                     source_program=source, passes=passes, origin=origin)


# ==================================================================
# 真实工具链
# ==================================================================

def test_fills_candidate_end_to_end():
    """baseline 候选跑通：编译成功、功能正确、指令数是正整数。"""
    cand = _cand(LOOP_SUM, [], origin="baseline")
    out = Executor().run({"candidates": [cand], "expected": [55]})
    assert out["results"][0] is cand              # 原地回填，返回同一个对象
    assert cand.compiled is True
    assert cand.correct is True
    assert isinstance(cand.instr_count, int) and cand.instr_count > 0
    assert cand.exec_time_ms is not None
    assert cand.error is None


def test_licm_candidate_beats_baseline_on_real_tools():
    """licm_demo：baseline 与 ['licm'] 都正确，且 licm 的指令数确实更低。"""
    src = _sample("licm_demo.nl")
    base = _cand(src, [], origin="baseline")
    opt = _cand(src, ["licm"])
    Executor().run({"candidates": [base, opt]})    # expected 从源码 // expect 读
    assert base.correct and opt.correct
    assert base.instr_count == 807
    assert opt.instr_count == 708
    assert opt.instr_count < base.instr_count


def test_expected_parsed_from_source_comment():
    """context 不给 expected 时，从源码 `// expect:` 注释读。"""
    cand = _cand(LOOP_SUM, ["const_fold", "dce"])
    Executor().run({"candidates": [cand]})         # 不传 expected
    assert cand.correct is True


def test_wrong_expected_records_incorrect_but_still_benches():
    """期望给错 → correct=False，但编译过、指令数照样量出来（Executor 只报事实）。"""
    cand = _cand(LOOP_SUM, [])
    Executor().run({"candidates": [cand], "expected": [999]})
    assert cand.compiled is True
    assert cand.correct is False
    assert isinstance(cand.instr_count, int)       # 仍然量了


def test_build_failure_recorded_not_raised():
    """未注册的 pass → 编译失败：compiled=False、记 error、不 bench、不抛异常。"""
    cand = _cand(LOOP_SUM, ["no_such_pass"])
    Executor().run({"candidates": [cand], "expected": [55]})
    assert cand.compiled is False
    assert cand.correct is False
    assert cand.instr_count is None
    assert cand.error and "no_such_pass" in cand.error


def test_missing_expected_marks_uncertain():
    """既无 context.expected、源码又没 expect 注释 → 正确性未判定，但仍编译+计时。"""
    no_expect = "let x = 1 + 2; print x;\n"
    cand = _cand(no_expect, [])
    Executor().run({"candidates": [cand]})
    assert cand.compiled is True
    assert cand.correct is False
    assert "未提供期望输出" in cand.error
    assert isinstance(cand.instr_count, int)


def test_does_not_sort_or_filter():
    """Executor 不排序不过滤：给几个就回几个，顺序不变。"""
    cands = [_cand(LOOP_SUM, []), _cand(LOOP_SUM, ["dce"]), _cand(LOOP_SUM, ["licm"])]
    out = Executor().run({"candidates": cands, "expected": [55]})
    assert out["results"] == cands                 # 同序、同数量


# ==================================================================
# 注入假 Router：断言工具调用顺序 + 落盘
# ==================================================================

class _FakeRouter:
    def __init__(self, returns):
        self.returns = returns
        self.calls = []

    def __call__(self, name, inp):
        self.calls.append(name)
        return self.returns[name]


def test_calls_tools_in_order():
    router = _FakeRouter({
        "build": {"ok": True, "bytecode": [("print", None, "x", None)], "error": ""},
        "run_tests": {"correct": True, "output": [1], "error": ""},
        "run_bench": {"instr_count": 5, "time_ms": 0.1, "error": ""},
    })
    cand = _cand(LOOP_SUM, ["dce"])
    Executor(tools=router).run({"candidates": [cand], "expected": [1]})
    assert router.calls == ["build", "run_tests", "run_bench"]
    assert cand.instr_count == 5 and cand.correct is True


def test_save_persists_when_requested():
    router = _FakeRouter({
        "build": {"ok": True, "bytecode": [], "error": ""},
        "run_tests": {"correct": True, "output": [], "error": ""},
        "run_bench": {"instr_count": 3, "time_ms": 0.1, "error": ""},
        "save_result": {"ok": True, "path": "runs/xxx.json", "error": ""},
    })
    cand = _cand(LOOP_SUM, [])
    out = Executor(tools=router).run({"candidates": [cand], "expected": [55], "save": True})
    assert "save_result" in router.calls
    assert out["saved"] == ["runs/xxx.json"]


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
