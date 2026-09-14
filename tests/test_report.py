"""schema v2 JSON → Markdown 报告测试；只使用内存 fixture，不调用网络。"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmark.configs import serialize_configs  # noqa: E402
from benchmark.report import (  # noqa: E402
    ReportError,
    generate_report,
    load_matrix_report,
    main,
)
from benchmark.schema import ExperimentRecord, MatrixReport  # noqa: E402


CONFIGS = ("baseline", "llm_only", "agent_min", "agent_full", "oracle")


def _snapshot(passes, instr_count, origin):
    return {
        "id": f"{origin}:{'+'.join(passes) or 'baseline'}",
        "passes": passes,
        "origin": origin,
        "compiled": True,
        "correct": True,
        "output": [30000],
        "instr_count": instr_count,
        "time_ms": 1.0,
        "peak_memory_kb": 12.0,
        "error": None,
    }


def _record(config, trial):
    settings = {
        "baseline": {
            "passes": [], "instr": 807, "time": None, "memory": None,
            "calls": 0, "prompt": 0, "completion": 0, "total": 0,
            "latency": 0.0, "rounds": 0, "fallback": False,
            "proposed": None, "stop": "completed",
        },
        "llm_only": {
            "passes": [], "instr": 807, "time": 2.0 if trial == 1 else 4.0,
            "memory": 10.0 if trial == 1 else 14.0,
            "calls": 1, "prompt": 10, "completion": 2, "total": 12,
            "latency": 100.0, "rounds": 1, "fallback": True,
            "proposed": _snapshot(["dce"], 807, "llm"), "stop": "max_rounds",
        },
        "agent_min": {
            "passes": ["licm"], "instr": 708,
            "time": 1.0 if trial == 1 else 3.0,
            "memory": 9.0 if trial == 1 else 11.0,
            "calls": 1, "prompt": 20, "completion": 4, "total": 24,
            "latency": 120.0, "rounds": 1, "fallback": False,
            "proposed": _snapshot(["licm"], 708, "llm"), "stop": "max_rounds",
        },
        "agent_full": {
            "passes": ["licm"], "instr": 708,
            "time": 1.2 if trial == 1 else 1.4,
            "memory": 8.0 if trial == 1 else 10.0,
            "calls": 2, "prompt": 40, "completion": 8, "total": 48,
            "latency": 200.0, "rounds": 2, "fallback": False,
            "proposed": _snapshot(["licm"], 708, "llm"), "stop": "converged",
        },
        "oracle": {
            "passes": ["licm"], "instr": 708, "time": 0.9, "memory": 8.0,
            "calls": 0, "prompt": 0, "completion": 0, "total": 0,
            "latency": 0.0, "rounds": 1, "fallback": False,
            "proposed": None, "stop": "completed",
        },
    }[config]
    selected_origin = "baseline" if not settings["passes"] else (
        "oracle" if config == "oracle" else "llm"
    )
    selected = _snapshot(settings["passes"], settings["instr"], selected_origin)
    errors = ["unknown_pass"] if config == "llm_only" and trial == 2 else []
    record = ExperimentRecord(
        run_id=f"fixture:licm_demo:{config}:t{trial}",
        program="licm_demo",
        config=config,
        trial=trial,
        passes=list(settings["passes"]),
        compiled=True,
        correct=True,
        output=[30000],
        instr_count=settings["instr"],
        time_ms=settings["time"],
        peak_memory_kb=settings["memory"],
        rounds=settings["rounds"],
        candidate_count=1,
        llm_calls=settings["calls"],
        prompt_tokens=settings["prompt"],
        completion_tokens=settings["completion"],
        reasoning_tokens=0,
        total_tokens=settings["total"],
        llm_latency_ms=settings["latency"],
        errors=errors,
        proposed_best=settings["proposed"],
        selected_best=selected,
        used_baseline_fallback=settings["fallback"],
        stop_reason=settings["stop"],
        llm_candidate_count=settings["calls"],
        candidate_results=[selected],
    )
    record.set_comparison(baseline_instr_count=807, oracle_instr_count=708)
    return record


def _fixture():
    records = [
        _record(config, trial)
        for trial in (1, 2)
        for config in CONFIGS
    ]
    return MatrixReport(
        generated_at="2026-09-14T12:00:00+08:00",
        experiment={
            "name": "four_profile_matrix",
            "matrix_id": "fixture",
            "selection_metric": "instr_count",
            "registered_passes": ["const_fold", "dce", "licm"],
            "model": "stub",
            "temperature": 0.0,
            "max_tokens": 1024,
            "bench_repeat": 5,
        },
        environment={
            "python": "3.11.15",
            "platform": "Linux-test",
            "git_commit": "abc123",
            "git_dirty": False,
        },
        configs=serialize_configs(CONFIGS),
        samples=["licm_demo"],
        trials=2,
        records=records,
        summary={"record_count": len(records)},
    )


def test_generates_all_fixed_sections_and_required_tables():
    text = generate_report(_fixture(), strict=True)
    for number in range(1, 16):
        assert f"## {number}." in text
    assert "每程序性能对比（表 A）" in text
    assert "Agent 提案搜索质量（表 B）" in text
    assert "LLM 成本（表 C）" in text
    assert "时间中位数 (ms)" in text
    assert "内存峰值中位数 (KB)" in text


def test_medians_percentages_and_token_totals_are_correct():
    text = generate_report(_fixture())
    assert (
        "| licm_demo | llm_only | 100.00% | 807 | 0.00% | 3.000 | 12.00 | （无） |"
        in text
    )
    assert "| licm_demo | agent_full | 807 | 708 | 99 | 12.27% |" in text
    assert "| llm_only | 2 | 20 | 4 | 24 | 200.000 | 1 |" in text
    assert "| agent_full | 4 | 80 | 16 | 96 | 400.000 | 2 |" in text


def test_missing_optional_metrics_render_as_dash_not_zero():
    text = generate_report(_fixture())
    assert "| licm_demo | baseline | — | — |" in text


def test_search_quality_uses_proposal_not_baseline_fallback():
    text = generate_report(_fixture())
    assert (
        "| licm_demo | llm_only | 708 | 807 | 0.00% | 13.98% | 100.00% |"
        in text
    )
    section = text.split("## 9.", 1)[1].split("## 10.", 1)[0]
    assert "| oracle |" not in section


def test_failure_summary_and_honest_agent_comparison_are_present():
    text = generate_report(_fixture())
    assert "| llm_only | 1 | unknown_pass |" in text
    assert "`agent_full` 相对 `llm_only`：1 个程序更优、0 个持平、0 个更差" in text


def test_same_fixture_generates_identical_text():
    data = _fixture().to_dict()
    assert generate_report(data) == generate_report(data)


def test_invalid_json_has_clear_error():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "broken.json")
        with open(path, "w", encoding="utf-8") as file:
            file.write("{not json")
        try:
            load_matrix_report(path)
        except ReportError as exc:
            assert "合法 JSON" in str(exc)
            assert "第 1 行" in str(exc)
        else:
            raise AssertionError("无效 JSON 应被拒绝")


def test_incompatible_schema_has_clear_error():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "old.json")
        with open(path, "w", encoding="utf-8") as file:
            json.dump({"schema_version": 1}, file)
        try:
            load_matrix_report(path)
        except ReportError as exc:
            assert "schema" in str(exc)
            assert "2" in str(exc)
        else:
            raise AssertionError("旧 schema 应被拒绝")


def test_strict_mode_rejects_incomplete_matrix():
    data = _fixture().to_dict()
    data["records"].pop()
    try:
        generate_report(data, strict=True)
    except ReportError as exc:
        assert "不完整" in str(exc)
        assert "缺少记录" in str(exc)
    else:
        raise AssertionError("严格模式应拒绝缺记录的矩阵")


def test_strict_mode_rejects_tampered_comparison():
    data = _fixture().to_dict()
    data["records"][0]["reduction_percent"] = 99.99
    try:
        generate_report(data, strict=True)
    except ReportError as exc:
        assert "收益字段" in str(exc)
    else:
        raise AssertionError("严格模式应拒绝被篡改的派生指标")


def test_cli_writes_requested_title_and_valid_markdown():
    with tempfile.TemporaryDirectory() as directory:
        input_path = os.path.join(directory, "matrix.json")
        output_path = os.path.join(directory, "report.md")
        with open(input_path, "w", encoding="utf-8") as file:
            json.dump(_fixture().to_dict(), file, ensure_ascii=False)
        code = main([
            input_path,
            "--output", output_path,
            "--title", "测试报告",
            "--strict",
        ])
        assert code == 0
        with open(output_path, encoding="utf-8") as file:
            text = file.read()
        assert text.startswith("# 测试报告\n")
        assert text.endswith("\n")


def main_tests():
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
    raise SystemExit(main_tests())
