"""阶段四指标专项测试：token 缺失、失败 telemetry 与 bench 中位数。"""
import importlib
import math
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmark.configs import get_config  # noqa: E402
from benchmark.matrix import run_profile  # noqa: E402
from benchmark.runner import load_sample  # noqa: E402
from benchmark.schema import compute_comparison  # noqa: E402
from llm import LLMError, StubLLMClient  # noqa: E402
from tools import build  # noqa: E402


def _sample(name):
    _, source, expected = load_sample(name)
    return source, expected


def test_stub_tokens_are_aggregated_into_profile_record():
    source, expected = _sample("dead_code")
    record = run_profile(
        "dead_code",
        source,
        expected,
        get_config("agent_full"),
        trial=1,
        llm=StubLLMClient(
            {"candidates": [{"passes": ["dce"]}]},
            usage={
                "prompt_tokens": 10,
                "completion_tokens": 2,
                "total_tokens": 12,
            },
        ),
        bench_repeat=1,
    )

    # 首轮找到 dce，第二轮同一方案不再刷新最优，因此共调用两次。
    assert record["llm_calls"] == 2
    assert record["prompt_tokens"] == 20
    assert record["completion_tokens"] == 4
    assert record["total_tokens"] == 24


def test_missing_llm_usage_stays_none_instead_of_fake_zero():
    source, expected = _sample("dead_code")
    record = run_profile(
        "dead_code",
        source,
        expected,
        get_config("llm_only"),
        trial=1,
        llm=StubLLMClient(
            {"candidates": [{"passes": ["dce"]}]},
            usage={
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
            },
        ),
        bench_repeat=1,
    )

    assert record["llm_calls"] == 1
    assert record["prompt_tokens"] is None
    assert record["completion_tokens"] is None
    assert record["total_tokens"] is None


def test_llm_failure_still_records_call_and_latency():
    def fail(user, system, schema):
        raise LLMError("模拟失败")

    source, expected = _sample("dead_code")
    record = run_profile(
        "dead_code",
        source,
        expected,
        get_config("llm_only"),
        trial=1,
        llm=StubLLMClient(fail),
        bench_repeat=1,
    )

    assert record["llm_calls"] == 1
    assert record["llm_latency_ms"] >= 0.0
    assert len(record["llm_usage"]) == 1
    assert record["llm_usage"][0]["success"] is False
    assert record["used_baseline_fallback"] is True
    assert any("模拟失败" in error for error in record["errors"])


def test_bench_time_is_median_of_repeats_and_instr_count_is_stable():
    bench_module = importlib.import_module("tools.bench")
    source, _ = _sample("dead_code")
    built = build({"source": source, "passes": []})
    assert built["ok"] is True

    # 三次人为耗时依次为 3ms、1ms、2ms，中位数必须是 2ms。
    clock = [0.0, 0.003, 1.0, 1.001, 2.0, 2.002]
    with patch.object(bench_module.time, "perf_counter", side_effect=clock):
        measured = bench_module.run_bench({
            "bytecode": built["bytecode"],
            "repeat": 3,
        })

    assert measured["error"] == ""
    assert math.isclose(measured["time_ms"], 2.0, rel_tol=0.0, abs_tol=1e-9)
    assert measured["instr_count"] == 8
    assert measured["peak_memory_kb"] >= 0.0


def test_incorrect_result_never_gets_fake_benefit():
    comparison = compute_comparison(
        correct=False,
        instr_count=1,
        baseline_instr_count=100,
        oracle_instr_count=1,
    )
    assert all(value is None for value in comparison.values())


def main():
    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ✅ {name}")
        except Exception as exc:
            failed += 1
            print(f"  ❌ {name}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
