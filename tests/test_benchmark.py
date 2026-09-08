"""阶段三 benchmark runner 的离线、可复现测试。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmark.runner import (  # noqa: E402
    DEFAULT_SAMPLES,
    format_markdown,
    pass_combinations,
    run_benchmark,
)


def test_default_set_contains_existing_five_and_new_gain_sample():
    assert DEFAULT_SAMPLES == (
        "basic", "branch", "loop_sum", "array_dot", "licm_demo", "dead_code"
    )


def test_pass_combinations_include_baseline_and_all_unique_orders():
    combos = pass_combinations(["const_fold", "dce", "licm"])
    assert combos[0] == ()
    assert len(combos) == 16
    assert len(set(combos)) == len(combos)
    assert ("licm", "dce") in combos and ("dce", "licm") in combos


def test_benchmark_finds_two_strict_improvements_and_preserves_correctness():
    report, path = run_benchmark(repeat=1, save=False)
    assert path is None
    assert report["summary"]["program_count"] == 6
    assert report["summary"]["correct_baselines"] == 6
    assert report["summary"]["correct_optimized"] == 6
    assert report["summary"]["programs_improved"] >= 2

    by_name = {p["program"]: p for p in report["programs"]}
    assert by_name["licm_demo"]["comparison"]["improved"] is True
    assert by_name["dead_code"]["comparison"]["improved"] is True
    assert all(p["baseline"]["correct"] for p in report["programs"])
    assert all(p["optimized"]["correct"] for p in report["programs"])

    table = format_markdown(report)
    assert "baseline 指令数" in table
    assert "`licm_demo`" in table and "`dead_code`" in table


def test_benchmark_can_persist_complete_json():
    report, path = run_benchmark(["dead_code"], repeat=1, save=True)
    try:
        assert path and os.path.isfile(path)
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
        assert saved["experiment"]["name"] == "baseline_vs_optimized"
        assert saved["programs"][0]["program"] == "dead_code"
        assert len(saved["programs"][0]["candidates"]) == 16
        assert saved["programs"][0]["comparison"]["improved"] is True
    finally:
        if path and os.path.exists(path):
            os.remove(path)
