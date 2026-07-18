"""
Evaluator 的测试：纯逻辑，直接构造「已执行」的 Candidate（手填 compiled/correct/
instr_count），验证过滤、排序、选优、进步判定、反馈内容。

跑法（项目根目录下）：
    python tests/test_evaluator.py
    pytest tests/
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import Evaluator, better                            # noqa: E402
from contracts import Candidate                                 # noqa: E402


def _done(passes, *, correct=True, instr=None, compiled=True, origin="llm",
          error=None, time_ms=1.0):
    """构造一个已执行的候选。"""
    c = Candidate(id=f"c#{'+'.join(passes) or 'base'}", source_program="src",
                  passes=passes, origin=origin)
    c.compiled = compiled
    c.correct = correct
    c.instr_count = instr
    c.exec_time_ms = time_ms
    c.error = error
    return c


def test_ranks_viable_by_instr_count_and_picks_best():
    results = [
        _done(["a"], instr=90),
        _done(["b"], instr=70),      # 最优
        _done(["c"], instr=80),
    ]
    out = Evaluator().run({"results": results})
    assert out["best"].passes == ["b"]
    assert [c.instr_count for c in out["ranking"]] == [70, 80, 90]


def test_filters_out_incorrect_and_uncompiled():
    """功能不通过、编译失败的候选一律出局，不进排名。"""
    good = _done(["a"], instr=100)
    wrong = _done(["b"], correct=False, instr=50)          # 更快但错 → 作废
    broken = _done(["c"], compiled=False, correct=False, instr=None, error="boom")
    out = Evaluator().run({"results": [good, wrong, broken]})
    assert out["ranking"] == [good]
    assert out["best"] is good
    assert wrong in out["rejected"] and broken in out["rejected"]
    assert len(out["rejected"]) == 2


def test_no_viable_gives_none_and_converged():
    out = Evaluator().run({"results": [_done(["x"], correct=False, instr=10)]})
    assert out["best"] is None
    assert out["converged"] is True
    assert "没有任何候选通过正确性" in out["feedback"]


def test_ranks_only_by_instr_not_time():
    """time_ms 更小但 instr 更大的不应排前面（time 会抖，不参与排名）。"""
    slow_few = _done(["a"], instr=60, time_ms=99.0)
    fast_many = _done(["b"], instr=90, time_ms=0.1)
    out = Evaluator().run({"results": [fast_many, slow_few]})
    assert out["best"].passes == ["a"]           # 按 instr=60 胜出，无视 time


def test_tie_break_prefers_fewer_passes():
    a = _done(["x", "y"], instr=50)
    b = _done(["z"], instr=50)                    # 同指令数、pass 更少 → 更优
    out = Evaluator().run({"results": [a, b]})
    assert out["best"] is b


def test_improved_vs_previous_best():
    """这轮最优刷新了历史最优 → improved=True、未收敛。"""
    prev = _done(["old"], instr=800, origin="agent")
    out = Evaluator().run({"results": [_done(["new"], instr=708)], "best": prev})
    assert out["improved"] is True
    assert out["converged"] is False


def test_no_improvement_is_converged():
    """这轮最优没打过历史最优 → 收敛。"""
    prev = _done(["old"], instr=700, origin="agent")
    out = Evaluator().run({"results": [_done(["new"], instr=708)], "best": prev})
    assert out["improved"] is False
    assert out["converged"] is True


def test_better_helper():
    a = _done(["a"], instr=100)
    b = _done(["b"], instr=200)
    assert better(a, b) is True
    assert better(b, a) is False
    assert better(a, None) is True               # 还没有最优时，任何可用候选都更优
    assert better(None, a) is False


def test_feedback_mentions_baseline_and_failures():
    baseline = _done([], instr=807, origin="baseline")
    winner = _done(["licm"], instr=708)
    broken = _done(["bad"], compiled=False, correct=False, error="UnknownPassError")
    fb = Evaluator().run({"results": [baseline, winner, broken]})["feedback"]
    assert "708" in fb and "807" in fb           # 最优与基线都在
    assert "编译失败" in fb and "bad" in fb.replace("'", "")   # 失败原因摘要


def test_feedback_flags_no_gain_over_baseline():
    baseline = _done([], instr=100, origin="baseline")
    nogain = _done(["dce"], instr=100)           # 正确但相对基线零收益
    fb = Evaluator().run({"results": [baseline, nogain]})["feedback"]
    assert "没有收益" in fb


def test_does_not_mutate_candidates():
    c = _done(["a"], instr=50)
    snapshot = c.to_dict()
    Evaluator().run({"results": [c]})
    assert c.to_dict() == snapshot


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
