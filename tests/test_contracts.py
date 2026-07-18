"""
Candidate 数据契约的测试：字段默认值、round-trip、校验、可用性判定。

跑法（项目根目录下）：
    python tests/test_contracts.py     # 不依赖 pytest
    pytest tests/                       # 装了 pytest 也能跑
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contracts import Candidate                                  # noqa: E402


def test_new_candidate_has_unfilled_defaults():
    """刚生成、还没跑：执行类字段是默认的未填状态。"""
    c = Candidate(id="x", source_program="loop_sum", passes=["dce"], origin="llm")
    assert c.compiled is False
    assert c.correct is False
    assert c.exec_time_ms is None
    assert c.instr_count is None
    assert c.error is None


def test_baseline_has_empty_passes():
    """baseline = 不加任何 pass。"""
    c = Candidate(id="b", source_program="loop_sum", passes=[], origin="baseline")
    assert c.passes == []


def test_invalid_origin_rejected():
    """origin 只能是 baseline/llm/agent，别的要报错。"""
    try:
        Candidate(id="x", source_program="p", passes=[], origin="human")
    except ValueError as e:
        assert "origin" in str(e)
    else:
        raise AssertionError("非法 origin 应该报错")


def test_round_trip_dict():
    """to_dict → from_dict 原样还原，日志落盘再读回不丢信息。"""
    c = Candidate(
        id="loop_sum#dce", source_program="loop_sum", passes=["const_fold", "dce"],
        origin="agent", compiled=True, correct=True, exec_time_ms=1.5, instr_count=42,
    )
    assert Candidate.from_dict(c.to_dict()) == c


def test_from_dict_ignores_extra_and_fills_missing():
    """读旧日志时：多余字段忽略，缺失字段用默认补齐。"""
    c = Candidate.from_dict({
        "id": "x", "source_program": "p", "passes": [], "origin": "baseline",
        "legacy_field": 123,          # 多余，应被忽略
        # 没有 instr_count 等执行字段，应用默认值
    })
    assert c.instr_count is None
    assert c.origin == "baseline"


def test_is_viable_needs_compiled_and_correct():
    """能进性能对比的前提：编译成功且功能正确。"""
    c = Candidate(id="x", source_program="p", passes=[], origin="baseline")
    assert c.is_viable() is False
    c.compiled = True
    assert c.is_viable() is False        # 编译过但没过正确性，仍不可比
    c.correct = True
    assert c.is_viable() is True


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
