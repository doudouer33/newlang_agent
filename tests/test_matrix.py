"""阶段四矩阵 runner 测试：全程使用 Stub LLM，不访问网络。"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmark.configs import CONFIG_NAMES, ExperimentConfig, get_config  # noqa: E402
from benchmark.matrix import main, run_matrix, run_profile  # noqa: E402
from benchmark.runner import load_sample  # noqa: E402
from benchmark.schema import MATRIX_SCHEMA_VERSION, MatrixReport  # noqa: E402
from llm import LLMError, StubLLMClient  # noqa: E402


def _sample(name):
    _, source, expected = load_sample(name)
    return source, expected


def _stub(response=None, users=None):
    payload = response or {
        "candidates": [
            {"passes": ["licm"]},
            {"passes": ["dce"]},
            {"passes": ["const_fold"]},
        ]
    }
    if users is None:
        return StubLLMClient(
            payload,
            usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        )

    def respond(user, system, schema):
        users.append(user)
        return payload

    return StubLLMClient(
        respond,
        usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    )


def _records_by_config(report):
    return {record["config"]: record for record in report["records"]}


def _shape(value):
    """忽略测量值，只比较 JSON 的键、容器层级和标量类型。"""
    if isinstance(value, dict):
        return {key: _shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [_shape(item) for item in value]
    return type(value).__name__


def test_baseline_and_oracle_run_without_using_llm():
    class Bomb:
        def complete_json(self, *args, **kwargs):
            raise AssertionError("baseline/oracle 不应调用 LLM")

    source, expected = _sample("dead_code")
    baseline = run_profile(
        "dead_code", source, expected, get_config("baseline"),
        trial=1, llm=Bomb(), bench_repeat=1,
    )
    oracle = run_profile(
        "dead_code", source, expected, get_config("oracle"),
        trial=1, llm=Bomb(), bench_repeat=1,
    )

    assert baseline["correct"] is True
    assert baseline["instr_count"] == 8
    assert baseline["llm_calls"] == 0
    assert baseline["rounds"] == 0
    assert oracle["correct"] is True
    assert oracle["instr_count"] == 6
    assert oracle["candidate_count"] == 16
    assert oracle["llm_calls"] == 0


def test_run_profile_rejects_mutated_protocol_copy():
    source, expected = _sample("dead_code")
    altered = ExperimentConfig(
        name="baseline",
        use_llm=False,
        n_candidates=1,
        max_rounds=0,
        use_feedback=False,
    )
    try:
        run_profile(
            "dead_code", source, expected, altered, trial=1, bench_repeat=1
        )
    except ValueError as exc:
        assert "冻结配置" in str(exc)
    else:
        raise AssertionError("矩阵入口不应接受同名但被修改的实验协议")


def test_full_stub_matrix_has_expected_profile_semantics():
    users = []
    report, path = run_matrix(
        samples=["licm_demo"],
        configs=CONFIG_NAMES,
        trials=1,
        bench_repeat=1,
        llm=_stub(users=users),
        save=False,
        matrix_id="test-matrix",
        generated_at="2026-09-14T12:00:00+08:00",
        model="stub",
    )
    records = _records_by_config(report)

    assert path is None
    assert report["schema_version"] == MATRIX_SCHEMA_VERSION
    assert len(report["records"]) == 5
    assert records["llm_only"]["llm_calls"] == 1
    assert records["llm_only"]["llm_candidate_count"] == 1
    assert records["llm_only"]["rounds"] == 1
    assert records["agent_min"]["llm_calls"] == 1
    assert records["agent_min"]["llm_candidate_count"] == 3
    assert records["agent_min"]["rounds"] == 1
    assert records["agent_full"]["llm_calls"] == 2
    assert records["agent_full"]["llm_candidate_count"] == 6
    assert records["agent_full"]["rounds"] == 2
    assert records["agent_full"]["stop_reason"] == "converged"
    assert "上一轮反馈" not in users[-2]
    assert "上一轮反馈" in users[-1]
    assert report["summary"]["llm_calls"] == 4


def test_proposal_and_baseline_fallback_are_separate():
    source, expected = _sample("loop_sum")
    record = run_profile(
        "loop_sum",
        source,
        expected,
        get_config("llm_only"),
        trial=1,
        llm=_stub({"candidates": [{"passes": ["dce"]}]}),
        bench_repeat=1,
    )

    assert record["proposed_best"]["passes"] == ["dce"]
    assert record["selected_best"]["passes"] == []
    assert record["passes"] == []
    assert record["used_baseline_fallback"] is True


def test_invalid_llm_candidate_is_recorded_and_baseline_survives():
    source, expected = _sample("dead_code")
    record = run_profile(
        "dead_code",
        source,
        expected,
        get_config("agent_min"),
        trial=1,
        llm=_stub({"candidates": [{"passes": ["not_a_pass"]}]}),
        bench_repeat=1,
    )

    assert record["correct"] is True
    assert record["passes"] == []
    assert record["proposed_best"] is None
    assert record["used_baseline_fallback"] is True
    assert record["llm_calls"] == 1
    assert any("unknown_pass" in error for error in record["errors"])


def test_llm_failure_is_a_record_not_a_matrix_crash():
    def fail(user, system, schema):
        raise LLMError("模拟 API 失败")

    report, _ = run_matrix(
        samples=["dead_code"],
        configs=["baseline", "llm_only", "agent_min"],
        trials=1,
        bench_repeat=1,
        llm=StubLLMClient(fail),
        save=False,
    )
    records = _records_by_config(report)

    assert records["baseline"]["correct"] is True
    for name in ("llm_only", "agent_min"):
        assert records[name]["correct"] is True
        assert records[name]["stop_reason"] == "llm_error"
        assert records[name]["used_baseline_fallback"] is True
        assert any("模拟 API 失败" in error for error in records[name]["errors"])


def test_missing_sample_does_not_block_other_samples():
    report, _ = run_matrix(
        samples=["missing_sample", "dead_code"],
        configs=["baseline"],
        trials=1,
        bench_repeat=1,
        save=False,
    )
    by_program = {record["program"]: record for record in report["records"]}
    assert by_program["missing_sample"]["correct"] is False
    assert by_program["missing_sample"]["errors"]
    assert by_program["dead_code"]["correct"] is True


def test_trial_records_have_unique_candidate_ids_and_comparisons():
    report, _ = run_matrix(
        samples=["licm_demo"],
        configs=["agent_full"],
        trials=2,
        bench_repeat=1,
        llm=_stub(),
        save=False,
        matrix_id="unique-test",
    )
    ids = []
    for record in report["records"]:
        assert record["baseline_instr_count"] == 807
        assert record["oracle_instr_count"] == 708
        assert record["reduction_percent"] == 12.27
        assert record["oracle_hit"] is True
        ids.extend(item["id"] for item in record["candidate_results"])
    assert len(ids) == len(set(ids))


def test_stub_runs_have_same_json_structure():
    kwargs = dict(
        samples=["dead_code"],
        configs=CONFIG_NAMES,
        trials=1,
        bench_repeat=1,
        save=False,
        matrix_id="stable",
        generated_at="2026-09-14T12:00:00+08:00",
        model="stub",
    )
    first, _ = run_matrix(llm=_stub(), **kwargs)
    second, _ = run_matrix(llm=_stub(), **kwargs)
    assert _shape(first) == _shape(second)
    MatrixReport.from_dict(json.loads(json.dumps(first, ensure_ascii=False)))


def test_output_path_writes_valid_schema_v2_json():
    with tempfile.TemporaryDirectory() as directory:
        output = os.path.join(directory, "matrix.json")
        report, path = run_matrix(
            samples=["dead_code"],
            configs=["baseline", "oracle"],
            trials=1,
            bench_repeat=1,
            save=True,
            output=output,
        )
        assert path == os.path.abspath(output)
        with open(path, encoding="utf-8") as file:
            saved = json.load(file)
        assert saved == report
        assert saved["schema_version"] == MATRIX_SCHEMA_VERSION


def test_cli_runs_baseline_and_oracle_without_saving():
    code = main([
        "--samples", "dead_code",
        "--configs", "baseline", "oracle",
        "--trials", "1",
        "--bench-repeat", "1",
        "--no-save",
    ])
    assert code == 0


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
