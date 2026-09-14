"""运行阶段四固定样例 × 四档系统 + Oracle 的统一矩阵实验。

这个模块只负责编排实验：baseline/Oracle 复用 benchmark.runner 的测量与选优，
三个 LLM 档复用 agents.orchestrator 的真实闭环。所有路径最终写成 schema v2 的
``program × config × trial`` 原始记录；单个样例或配置失败只进入 errors，不中断矩阵。

快速离线冒烟（不需要 API key）：
    python -m benchmark.matrix --samples licm_demo dead_code \
        --configs baseline oracle --trials 1 --bench-repeat 1 --no-save
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import uuid
from datetime import datetime

from agents import Executor, orchestrate_detailed
from contracts import Candidate
from llm import DeepSeekClient
from llm.client import DEFAULT_MODEL
from optimizer import available_passes
from tools import save_result

from .configs import (
    CONFIG_NAMES,
    FORMAL_SAMPLES,
    ExperimentConfig,
    get_config,
    serialize_configs,
)
from .runner import load_sample, measure_candidate, pass_combinations, select_best
from .schema import ExperimentRecord, MatrixReport


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _candidate_snapshot(candidate: Candidate) -> dict:
    """把 Candidate 归一成矩阵内部的紧凑候选记录，不重复保存整份源码。"""
    return {
        "id": candidate.id,
        "passes": list(candidate.passes),
        "origin": candidate.origin,
        "compiled": candidate.compiled,
        "correct": candidate.correct,
        "output": candidate.output,
        "instr_count": candidate.instr_count,
        "time_ms": candidate.exec_time_ms,
        "peak_memory_kb": candidate.peak_memory_kb,
        "error": candidate.error,
    }


def _row_snapshot(row: dict, *, candidate_id: str, origin: str) -> dict:
    """把 benchmark.runner 的测量行归一成与 Agent 候选相同的形状。"""
    return {
        "id": candidate_id,
        "passes": list(row.get("passes") or []),
        "origin": origin,
        "compiled": bool(row.get("compiled")),
        "correct": bool(row.get("correct")),
        "output": row.get("output"),
        "instr_count": row.get("instr_count"),
        "time_ms": row.get("time_ms"),
        "peak_memory_kb": row.get("peak_memory_kb"),
        "error": row.get("error") or None,
    }


def _candidate_dict_snapshot(candidate: dict) -> dict:
    """压缩 orchestrator 历史里的 Candidate dict，并统一 time_ms 字段名。"""
    return {
        "id": candidate.get("id"),
        "passes": list(candidate.get("passes") or []),
        "origin": candidate.get("origin"),
        "compiled": bool(candidate.get("compiled")),
        "correct": bool(candidate.get("correct")),
        "output": candidate.get("output"),
        "instr_count": candidate.get("instr_count"),
        "time_ms": candidate.get("time_ms", candidate.get("exec_time_ms")),
        "peak_memory_kb": candidate.get("peak_memory_kb"),
        "error": candidate.get("error"),
    }


def _record_from_selected(
    *,
    record_id: str,
    program: str,
    config: ExperimentConfig,
    trial: int,
    selected: dict | None,
    **extra,
) -> ExperimentRecord:
    """用 selected_best 的事实指标构造一条 schema 记录。"""
    selected = selected if selected and selected.get("correct") else None
    values = {
        "run_id": record_id,
        "program": program,
        "config": config.name,
        "trial": trial,
        "selected_best": selected,
    }
    if selected is not None:
        values.update({
            "passes": list(selected["passes"]),
            "compiled": bool(selected["compiled"]),
            "correct": bool(selected["correct"]),
            "output": selected.get("output"),
            "instr_count": selected.get("instr_count"),
            "time_ms": selected.get("time_ms"),
            "peak_memory_kb": selected.get("peak_memory_kb"),
        })
    values.update(extra)
    return ExperimentRecord(**values)


def _error_record(
    record_id: str,
    program: str,
    config: ExperimentConfig,
    trial: int,
    error: Exception | str,
) -> ExperimentRecord:
    message = str(error) if isinstance(error, str) else (
        f"{type(error).__name__}: {error}"
    )
    return ExperimentRecord(
        run_id=record_id,
        program=program,
        config=config.name,
        trial=trial,
        errors=[message],
        stop_reason="error",
    )


def _stable_best(snapshots: list[dict]) -> dict | None:
    viable = [
        item for item in snapshots
        if item.get("compiled") and item.get("correct")
        and item.get("instr_count") is not None
    ]
    if not viable:
        return None
    return min(
        viable,
        key=lambda item: (
            item["instr_count"], len(item.get("passes") or []), item.get("id", "")
        ),
    )


def _dedupe_strings(items) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def _run_baseline(
    program: str,
    source: str,
    expected: list[int],
    config: ExperimentConfig,
    trial: int,
    bench_repeat: int,
    record_id: str,
) -> ExperimentRecord:
    candidate = Candidate(
        id=f"{record_id}:c1",
        source_program=source,
        passes=[],
        origin="baseline",
    )
    Executor().run({
        "candidates": [candidate],
        "expected": expected,
        "repeat": bench_repeat,
    })
    snapshot = _candidate_snapshot(candidate)
    errors = [candidate.error] if candidate.error else []
    return _record_from_selected(
        record_id=record_id,
        program=program,
        config=config,
        trial=trial,
        selected=snapshot,
        candidate_count=1,
        candidate_results=[snapshot],
        errors=errors,
        stop_reason="completed" if candidate.is_viable() else "error",
    )


def _run_oracle(
    program: str,
    source: str,
    expected: list[int],
    config: ExperimentConfig,
    trial: int,
    bench_repeat: int,
    record_id: str,
) -> ExperimentRecord:
    measured = [
        measure_candidate(source, expected, combo, bench_repeat)
        for combo in pass_combinations()
    ]
    snapshots = [
        _row_snapshot(
            row,
            candidate_id=f"{record_id}:c{index}",
            origin="baseline" if not row["passes"] else "oracle",
        )
        for index, row in enumerate(measured, start=1)
    ]
    selected_row = select_best(measured)
    selected = None
    if selected_row is not None:
        selected_index = next(
            index for index, row in enumerate(measured) if row is selected_row
        )
        selected = snapshots[selected_index]
    errors = [
        f"候选 {item['passes']}：{item['error']}"
        for item in snapshots if item.get("error")
    ]
    return _record_from_selected(
        record_id=record_id,
        program=program,
        config=config,
        trial=trial,
        selected=selected,
        rounds=1,
        candidate_count=len(snapshots),
        candidate_results=snapshots,
        errors=errors,
        stop_reason="completed" if selected is not None else "error",
    )


def _run_llm_profile(
    program: str,
    source: str,
    expected: list[int],
    config: ExperimentConfig,
    trial: int,
    llm,
    bench_repeat: int,
    record_id: str,
) -> ExperimentRecord:
    detail = orchestrate_detailed(
        program,
        source,
        llm=llm,
        max_rounds=config.max_rounds,
        n_candidates=config.n_candidates,
        expected=expected,
        repeat=bench_repeat,
        save=False,
        candidate_id_prefix=record_id,
    )

    candidate_results = []
    round_history = []
    errors = []
    for round_item in detail["history"]:
        normalized_round = dict(round_item)
        normalized_round["best"] = (
            _candidate_dict_snapshot(round_item["best"])
            if round_item.get("best") else None
        )
        normalized_round["ranking"] = [
            _candidate_dict_snapshot(item) for item in round_item["ranking"]
        ]
        normalized_round["rejected"] = [
            _candidate_dict_snapshot(item) for item in round_item["rejected"]
        ]
        round_history.append(normalized_round)
        candidates = normalized_round["ranking"] + normalized_round["rejected"]
        candidate_results.extend(candidates)
        if round_item.get("opt_error"):
            errors.append(round_item["opt_error"])
        for rejected in round_item.get("rejected_items", []):
            errors.append(
                "LLM 候选清洗："
                + json.dumps(rejected, ensure_ascii=False, sort_keys=True)
            )
        for candidate in normalized_round["rejected"]:
            reason = candidate.get("error") or "输出与期望不符"
            errors.append(f"候选 {candidate.get('passes', [])}：{reason}")

    proposed = _stable_best([
        item for item in candidate_results if item.get("origin") != "baseline"
    ])
    selected = (
        _candidate_snapshot(detail["best"]) if detail.get("best") else None
    )
    usage = detail["llm_usage_summary"]
    return _record_from_selected(
        record_id=record_id,
        program=program,
        config=config,
        trial=trial,
        selected=selected,
        proposed_best=proposed,
        used_baseline_fallback=detail["used_baseline_fallback"],
        stop_reason=detail["stop_reason"],
        rounds=detail["rounds"],
        candidate_count=detail["candidate_count"],
        llm_candidate_count=detail["llm_candidate_count"],
        llm_calls=usage["llm_calls"],
        prompt_tokens=usage["prompt_tokens"],
        completion_tokens=usage["completion_tokens"],
        reasoning_tokens=usage["reasoning_tokens"],
        total_tokens=usage["total_tokens"],
        llm_latency_ms=usage["llm_latency_ms"],
        candidate_results=candidate_results,
        round_history=round_history,
        llm_usage=detail["llm_usage"],
        errors=_dedupe_strings(errors),
    )


def run_profile(
    program: str,
    source: str,
    expected: list[int],
    config: ExperimentConfig,
    *,
    trial: int,
    llm=None,
    bench_repeat: int = 5,
    run_id: str | None = None,
) -> dict:
    """运行一个 ``program × config × trial``，返回 JSON 友好的原始记录。

    baseline 与 oracle 永远不会构造 LLM client。运行期异常被收口到 ``errors``；
    参数错误仍显式抛出，让调用方尽早修正实验协议。
    """
    if not isinstance(config, ExperimentConfig):
        raise TypeError("config 必须是 ExperimentConfig")
    if config.name not in CONFIG_NAMES:
        raise ValueError(f"未知实验配置：{config.name!r}")
    if config != get_config(config.name):
        raise ValueError(f"config 必须使用冻结配置：{config.name!r}")
    if not isinstance(trial, int) or isinstance(trial, bool) or trial < 1:
        raise ValueError("trial 必须是大于等于 1 的整数")
    if (
        not isinstance(bench_repeat, int)
        or isinstance(bench_repeat, bool)
        or bench_repeat < 1
    ):
        raise ValueError("bench_repeat 必须是大于等于 1 的整数")
    if config.use_llm and llm is None:
        llm = DeepSeekClient()

    record_id = run_id or f"{program}:{config.name}:t{trial}"
    try:
        if config.name == "baseline":
            record = _run_baseline(
                program, source, expected, config, trial, bench_repeat, record_id
            )
        elif config.exhaustive:
            record = _run_oracle(
                program, source, expected, config, trial, bench_repeat, record_id
            )
        else:
            record = _run_llm_profile(
                program, source, expected, config, trial, llm,
                bench_repeat, record_id,
            )
    except Exception as exc:  # 单配置失败必须落盘，不能中断矩阵。
        record = _error_record(record_id, program, config, trial, exc)
    return record.to_dict()


def _git_value(*args):
    try:
        return subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def collect_environment() -> dict:
    """采集可复现所需环境，不因当前目录不是 Git 仓库而失败。"""
    commit = _git_value("rev-parse", "HEAD")
    status = _git_value("status", "--porcelain")
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "git_commit": commit,
        "git_dirty": None if status is None else bool(status),
    }


def _summary(records: list[ExperimentRecord]) -> dict:
    return {
        "record_count": len(records),
        "correct_records": sum(record.correct for record in records),
        "failed_records": sum(not record.correct for record in records),
        "records_with_errors": sum(bool(record.errors) for record in records),
        "baseline_fallbacks": sum(
            record.used_baseline_fallback for record in records
        ),
        "llm_calls": sum(record.llm_calls for record in records),
        "total_tokens": (
            None
            if any(record.total_tokens is None for record in records)
            else sum(record.total_tokens for record in records)
        ),
    }


def _save_matrix(data: dict, output: str | None) -> str:
    if output:
        path = os.path.abspath(output)
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        text = json.dumps(data, ensure_ascii=False, indent=2)
        with open(path, "w", encoding="utf-8") as file:
            file.write(text)
        return path

    saved = save_result({"data": data, "name": "matrix"})
    if not saved.get("ok"):
        raise RuntimeError(f"保存矩阵失败：{saved.get('error')}")
    return saved["path"]


def run_matrix(
    samples=None,
    configs=None,
    *,
    trials: int = 3,
    bench_repeat: int = 5,
    model: str | None = None,
    temperature: float | None = 0.0,
    max_tokens: int = 1024,
    llm=None,
    llm_factory=None,
    save: bool = True,
    output: str | None = None,
    matrix_id: str | None = None,
    generated_at: str | None = None,
):
    """运行矩阵并返回 ``(report_dict, saved_path)``。

    ``llm`` 适合注入一个可复用 Stub；``llm_factory`` 会为每条 LLM 记录创建新实例。
    二者均不提供时才构造真实 DeepSeekClient。即便只选择 LLM 档，baseline 和
    Oracle 仍会作为隐藏锚点各执行一次，但最终 records 只包含 ``configs`` 所选档。
    """
    if not isinstance(trials, int) or isinstance(trials, bool) or trials < 1:
        raise ValueError("trials 必须是大于等于 1 的整数")
    if (
        not isinstance(bench_repeat, int)
        or isinstance(bench_repeat, bool)
        or bench_repeat < 1
    ):
        raise ValueError("bench_repeat 必须是大于等于 1 的整数")
    if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens < 1:
        raise ValueError("max_tokens 必须是大于等于 1 的整数")
    if llm is not None and llm_factory is not None:
        raise ValueError("llm 和 llm_factory 只能提供一个")
    if output and not save:
        raise ValueError("--output 与 --no-save 不能同时使用")

    model = model or os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL)

    sample_names = tuple(FORMAL_SAMPLES if samples is None else samples)
    config_names = tuple(CONFIG_NAMES if configs is None else configs)
    if not sample_names or len(sample_names) != len(set(sample_names)):
        raise ValueError("samples 不能为空或重复")
    if not config_names or len(config_names) != len(set(config_names)):
        raise ValueError("configs 不能为空或重复")
    selected_configs = [get_config(name) for name in config_names]

    matrix_id = matrix_id or (
        datetime.now().astimezone().strftime("matrix-%Y%m%dT%H%M%S-")
        + uuid.uuid4().hex[:8]
    )
    generated_at = generated_at or datetime.now().astimezone().isoformat(
        timespec="seconds"
    )
    records: list[ExperimentRecord] = []
    baseline_config = get_config("baseline")
    oracle_config = get_config("oracle")

    for program in sample_names:
        try:
            _, source, expected = load_sample(program)
        except Exception as exc:
            for trial in range(1, trials + 1):
                for config in selected_configs:
                    records.append(_error_record(
                        f"{matrix_id}:{program}:{config.name}:t{trial}",
                        program, config, trial, exc,
                    ))
            continue

        for trial in range(1, trials + 1):
            cache = {}
            for anchor in (baseline_config, oracle_config):
                anchor_id = f"{matrix_id}:{program}:{anchor.name}:t{trial}"
                cache[anchor.name] = run_profile(
                    program,
                    source,
                    expected,
                    anchor,
                    trial=trial,
                    bench_repeat=bench_repeat,
                    run_id=anchor_id,
                )

            baseline = ExperimentRecord.from_dict(cache["baseline"])
            oracle = ExperimentRecord.from_dict(cache["oracle"])
            baseline_count = baseline.instr_count if baseline.correct else None
            oracle_count = oracle.instr_count if oracle.correct else None

            for config in selected_configs:
                if config.name in cache:
                    raw = cache[config.name]
                else:
                    profile_id = f"{matrix_id}:{program}:{config.name}:t{trial}"
                    try:
                        profile_llm = llm
                        if llm_factory is not None:
                            profile_llm = llm_factory()
                        if profile_llm is None:
                            profile_llm = DeepSeekClient(
                                model=model,
                                temperature=temperature,
                                max_tokens=max_tokens,
                            )
                        raw = run_profile(
                            program,
                            source,
                            expected,
                            config,
                            trial=trial,
                            llm=profile_llm,
                            bench_repeat=bench_repeat,
                            run_id=profile_id,
                        )
                    except Exception as exc:
                        raw = _error_record(
                            profile_id, program, config, trial, exc
                        ).to_dict()

                record = ExperimentRecord.from_dict(raw)
                record.set_comparison(
                    baseline_instr_count=baseline_count,
                    oracle_instr_count=oracle_count,
                )
                records.append(record)

    report_obj = MatrixReport(
        generated_at=generated_at,
        experiment={
            "name": "four_profile_matrix",
            "matrix_id": matrix_id,
            "selection_metric": "instr_count",
            "registered_passes": list(available_passes()),
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "bench_repeat": bench_repeat,
        },
        environment=collect_environment(),
        configs=serialize_configs(config_names),
        samples=list(sample_names),
        trials=trials,
        records=records,
        summary=_summary(records),
    )
    report = report_obj.to_dict()
    saved_path = _save_matrix(report, output) if save else None
    return report, saved_path


def format_summary(report: dict) -> str:
    summary = report["summary"]
    return (
        f"矩阵完成：{summary['correct_records']}/{summary['record_count']} 条记录正确，"
        f"LLM 调用 {summary['llm_calls']} 次，baseline 保底 "
        f"{summary['baseline_fallbacks']} 次。"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="运行阶段四四档 + Oracle 矩阵实验")
    parser.add_argument("--samples", nargs="+", help="样例名（不含 .nl）")
    parser.add_argument("--configs", nargs="+", choices=CONFIG_NAMES)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--bench-repeat", type=int, default=5)
    parser.add_argument(
        "--model",
        default=None,
        help=f"DeepSeek 模型（默认读取 DEEPSEEK_MODEL，否则 {DEFAULT_MODEL}）",
    )
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--output", help="将 JSON 写到指定路径")
    args = parser.parse_args(argv)

    try:
        report, path = run_matrix(
            samples=args.samples,
            configs=args.configs,
            trials=args.trials,
            bench_repeat=args.bench_repeat,
            model=args.model,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            save=not args.no_save,
            output=args.output,
        )
    except (TypeError, ValueError, RuntimeError, OSError) as exc:
        print(f"matrix 失败：{exc}", file=sys.stderr)
        return 1

    print(format_summary(report))
    if path:
        print(f"完整结果：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
