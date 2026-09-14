"""阶段四矩阵实验 schema、派生指标和 JSON 往返测试。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmark.configs import FORMAL_SAMPLES, serialize_configs  # noqa: E402
from benchmark.schema import (  # noqa: E402
    MATRIX_SCHEMA_VERSION,
    ExperimentRecord,
    MatrixReport,
    compute_comparison,
)


def _record(**overrides):
    values = {
        "run_id": "run-1:licm_demo:agent_full:1",
        "program": "licm_demo",
        "config": "agent_full",
        "trial": 1,
        "passes": ["licm"],
        "compiled": True,
        "correct": True,
        "output": [30000],
        "instr_count": 708,
        "time_ms": 1.25,
        "rounds": 2,
        "candidate_count": 6,
        "llm_calls": 2,
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
        "llm_latency_ms": 300.0,
    }
    values.update(overrides)
    return ExperimentRecord(**values)


def _report(records=None):
    return MatrixReport(
        generated_at="2026-09-14T12:00:00+08:00",
        experiment={"name": "four_profile_matrix"},
        environment={"python": "3.11.15"},
        configs=serialize_configs(),
        samples=list(FORMAL_SAMPLES),
        trials=3,
        records=list(records or []),
        summary={"record_count": len(records or [])},
    )


def test_record_defaults_are_json_friendly_and_not_shared():
    first = ExperimentRecord(
        run_id="r1", program="branch", config="baseline", trial=1
    )
    second = ExperimentRecord(
        run_id="r2", program="branch", config="baseline", trial=1
    )
    first.errors.append("x")
    first.passes.append("dce")
    assert second.errors == []
    assert second.passes == []
    assert json.loads(json.dumps(first.to_dict(), ensure_ascii=False)) == first.to_dict()


def test_record_round_trip_ignores_future_optional_fields():
    original = _record()
    data = original.to_dict()
    data["future_optional_field"] = "ignored"
    restored = ExperimentRecord.from_dict(data)
    assert restored == original


def test_comparison_metrics_for_correct_result():
    metrics = compute_comparison(
        correct=True,
        instr_count=708,
        baseline_instr_count=807,
        oracle_instr_count=708,
    )
    assert metrics == {
        "saved_instructions": 99,
        "reduction_percent": 12.27,
        "oracle_hit": True,
        "oracle_gap_percent": 0.0,
    }


def test_comparison_can_report_regression_and_oracle_gap():
    metrics = compute_comparison(
        correct=True,
        instr_count=12,
        baseline_instr_count=10,
        oracle_instr_count=8,
    )
    assert metrics["saved_instructions"] == -2
    assert metrics["reduction_percent"] == -20.0
    assert metrics["oracle_hit"] is False
    assert metrics["oracle_gap_percent"] == 50.0


def test_incorrect_result_has_no_comparison_metrics():
    metrics = compute_comparison(
        correct=False,
        instr_count=1,
        baseline_instr_count=807,
        oracle_instr_count=708,
    )
    assert all(value is None for value in metrics.values())


def test_zero_or_missing_anchor_has_no_fake_percentage():
    metrics = compute_comparison(
        correct=True,
        instr_count=0,
        baseline_instr_count=0,
        oracle_instr_count=None,
    )
    assert all(value is None for value in metrics.values())


def test_record_set_comparison_fills_anchors_and_metrics():
    record = _record()
    record.set_comparison(baseline_instr_count=807, oracle_instr_count=708)
    assert record.baseline_instr_count == 807
    assert record.oracle_instr_count == 708
    assert record.saved_instructions == 99
    assert record.reduction_percent == 12.27
    assert record.oracle_hit is True
    assert record.oracle_gap_percent == 0.0


def test_invalid_record_is_rejected():
    cases = [
        dict(run_id="", program="branch", config="baseline", trial=1),
        dict(run_id="r", program="", config="baseline", trial=1),
        dict(run_id="r", program="branch", config="unknown", trial=1),
        dict(run_id="r", program="branch", config="baseline", trial=0),
        dict(run_id="r", program="branch", config="baseline", trial=1,
             compiled=False, correct=True),
        dict(run_id="r", program="branch", config="baseline", trial=1,
             llm_calls=-1),
        dict(run_id="r", program="branch", config="baseline", trial=1,
             reduction_percent=0.0),
    ]
    for values in cases:
        try:
            ExperimentRecord(**values)
        except ValueError:
            pass
        else:
            raise AssertionError(f"非法记录未被拒绝：{values}")


def test_matrix_report_json_round_trip():
    record = _record()
    report = _report([record])
    dumped = json.dumps(report.to_dict(), ensure_ascii=False)
    restored = MatrixReport.from_dict(json.loads(dumped))
    assert restored == report
    assert restored.schema_version == MATRIX_SCHEMA_VERSION
    assert isinstance(restored.records[0], ExperimentRecord)


def test_matrix_report_rejects_phase_three_schema():
    old = {
        "schema_version": 1,
        "generated_at": "2026-09-08T00:00:00+08:00",
        "experiment": {"name": "baseline_vs_optimized"},
    }
    try:
        MatrixReport.from_dict(old)
    except ValueError as exc:
        assert "schema_version" in str(exc)
        assert str(MATRIX_SCHEMA_VERSION) in str(exc)
    else:
        raise AssertionError("阶段三 schema 不应被当成阶段四矩阵读取")


def test_matrix_report_checks_record_membership_and_trial():
    invalid_records = [
        _record(program="basic"),
        _record(config="agent_full", trial=4),
    ]
    for record in invalid_records:
        try:
            _report([record])
        except ValueError:
            pass
        else:
            raise AssertionError(f"越界记录未被拒绝：{record}")


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
