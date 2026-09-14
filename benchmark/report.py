"""把阶段四 schema v2 矩阵 JSON 确定性渲染成 Markdown 报告。

报告生成器不导入 LLM，也不运行 benchmark；同一输入与标题始终产生完全相同正文。

用法：
    python -m benchmark.report runs/final_matrix.json \
        --output docs/final_report.md
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import Counter, defaultdict

from .schema import MatrixReport, compute_comparison


DEFAULT_TITLE = "大模型智能体驱动的新语言编译与优化系统：实验报告"

_SAMPLE_CAPABILITIES = {
    "basic": "基础算术与输出冒烟",
    "branch": "条件分支",
    "loop_sum": "标量循环与累加",
    "array_dot": "数组访问与循环",
    "licm_demo": "循环不变量外提收益",
    "dead_code": "死代码消除收益",
}


class ReportError(ValueError):
    """输入 JSON 无法安全生成报告。"""


def _coerce_report(value, *, strict: bool = False) -> MatrixReport:
    if isinstance(value, MatrixReport):
        report = value
    else:
        try:
            report = MatrixReport.from_dict(value)
        except (TypeError, ValueError) as exc:
            raise ReportError(f"矩阵 schema 校验失败：{exc}") from exc
    if strict:
        _validate_complete(report)
    return report


def load_matrix_report(path: str, *, strict: bool = False) -> MatrixReport:
    """读取并校验矩阵 JSON；文件、JSON 和 schema 错误均转成清晰的 ReportError。"""
    try:
        with open(path, encoding="utf-8") as file:
            data = json.load(file)
    except OSError as exc:
        raise ReportError(f"无法读取矩阵 JSON：{exc}") from exc
    except json.JSONDecodeError as exc:
        raise ReportError(
            f"矩阵文件不是合法 JSON：第 {exc.lineno} 行第 {exc.colno} 列：{exc.msg}"
        ) from exc
    return _coerce_report(data, strict=strict)


def _validate_complete(report: MatrixReport) -> None:
    """严格模式要求每个 program/config/trial 恰好有一条记录且派生值一致。"""
    config_names = [item["name"] for item in report.configs]
    expected = {
        (program, config, trial)
        for program in report.samples
        for config in config_names
        for trial in range(1, report.trials + 1)
    }
    actual_items = [
        (record.program, record.config, record.trial) for record in report.records
    ]
    actual = set(actual_items)
    duplicates = sorted(
        item for item, count in Counter(actual_items).items() if count > 1
    )
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if duplicates or missing or unexpected:
        details = []
        if duplicates:
            details.append(f"重复记录 {duplicates}")
        if missing:
            details.append(f"缺少记录 {missing}")
        if unexpected:
            details.append(f"越界记录 {unexpected}")
        raise ReportError("严格模式矩阵不完整：" + "；".join(details))

    for record in report.records:
        expected_comparison = compute_comparison(
            correct=record.correct,
            instr_count=record.instr_count,
            baseline_instr_count=record.baseline_instr_count,
            oracle_instr_count=record.oracle_instr_count,
        )
        actual_comparison = {
            "saved_instructions": record.saved_instructions,
            "reduction_percent": record.reduction_percent,
            "oracle_hit": record.oracle_hit,
            "oracle_gap_percent": record.oracle_gap_percent,
        }
        if actual_comparison != expected_comparison:
            raise ReportError(
                f"记录 {record.run_id!r} 的收益字段与原始指标不一致"
            )


def _groups(report: MatrixReport):
    grouped = defaultdict(list)
    for record in report.records:
        grouped[(record.program, record.config)].append(record)
    for records in grouped.values():
        records.sort(key=lambda item: (item.trial, item.run_id))
    return grouped


def _median(values):
    clean = [value for value in values if value is not None]
    return statistics.median(clean) if clean else None


def _metric(records, name, *, correct_only=True):
    return _median(
        getattr(record, name)
        for record in records
        if not correct_only or record.correct
    )


def _sum_metric(records, name):
    if not records:
        return None
    values = [getattr(record, name) for record in records]
    # 有 LLM 调用却缺 usage 时，不能把缺失值当成零成本。
    if any(
        value is None and record.llm_calls > 0
        for value, record in zip(values, records)
    ):
        return None
    return sum(value or 0 for value in values)


def _rate(numerator: int, denominator: int):
    return numerator / denominator * 100 if denominator else None


def _modal_passes(records):
    combinations = [tuple(record.passes) for record in records if record.correct]
    if not combinations:
        return None
    counts = Counter(combinations)
    return min(counts, key=lambda combo: (-counts[combo], len(combo), combo))


def _fmt_number(value, digits=2):
    if value is None:
        return "—"
    if isinstance(value, int) or (isinstance(value, float) and value.is_integer()):
        return str(int(value))
    return f"{value:.{digits}f}"


def _fmt_fixed(value, digits=2):
    return "—" if value is None else f"{value:.{digits}f}"


def _fmt_percent(value):
    return "—" if value is None else f"{value:.2f}%"


def _fmt_passes(passes):
    if passes is None:
        return "—"
    if not passes:
        return "（无）"
    return " → ".join(passes)


def _display(value):
    return "—" if value is None or value == "" else value


def _escape(value):
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def _table(headers, rows):
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    lines.extend(
        "| " + " | ".join(_escape(value) for value in row) + " |"
        for row in rows
    )
    return "\n".join(lines)


def _correctness_rows(report, grouped):
    rows = []
    for config in (item["name"] for item in report.configs):
        records = [
            record for program in report.samples
            for record in grouped.get((program, config), [])
        ]
        correct = sum(record.correct for record in records)
        rows.append([
            config,
            str(correct),
            str(len(records)),
            _fmt_percent(_rate(correct, len(records))),
            str(sum(bool(record.errors) for record in records)),
        ])
    return rows


def _performance_rows(report, grouped):
    rows = []
    for program in report.samples:
        for config in (item["name"] for item in report.configs):
            records = grouped.get((program, config), [])
            correct = sum(record.correct for record in records)
            rows.append([
                program,
                config,
                _fmt_percent(_rate(correct, len(records))),
                _fmt_number(_metric(records, "instr_count")),
                _fmt_percent(_metric(records, "reduction_percent")),
                _fmt_fixed(_metric(records, "time_ms"), 3),
                _fmt_fixed(_metric(records, "peak_memory_kb"), 2),
                _fmt_passes(_modal_passes(records)),
            ])
    return rows


def _benefit_rows(report, grouped):
    rows = []
    for program in report.samples:
        for config in (item["name"] for item in report.configs):
            records = grouped.get((program, config), [])
            rows.append([
                program,
                config,
                _fmt_number(_metric(records, "baseline_instr_count")),
                _fmt_number(_metric(records, "instr_count")),
                _fmt_number(_metric(records, "saved_instructions")),
                _fmt_percent(_metric(records, "reduction_percent")),
            ])
    return rows


def _runtime_rows(report, grouped):
    rows = []
    for program in report.samples:
        for config in (item["name"] for item in report.configs):
            records = grouped.get((program, config), [])
            rows.append([
                program,
                config,
                _fmt_fixed(_metric(records, "time_ms"), 3),
                _fmt_fixed(_metric(records, "peak_memory_kb"), 2),
            ])
    return rows


def _search_rows(report, grouped):
    rows = []
    agent_configs = [
        item["name"] for item in report.configs
        if item["name"] not in ("baseline", "oracle")
    ]
    for program in report.samples:
        for config in agent_configs:
            records = grouped.get((program, config), [])
            oracle_values = []
            proposed_values = []
            gaps = []
            hits = []
            for record in records:
                oracle = record.oracle_instr_count
                proposed = (
                    record.proposed_best.get("instr_count")
                    if record.proposed_best else None
                )
                if oracle is not None:
                    oracle_values.append(oracle)
                if proposed is not None:
                    proposed_values.append(proposed)
                if oracle is not None and oracle > 0 and proposed is not None:
                    hits.append(proposed == oracle)
                    gaps.append((proposed - oracle) / oracle * 100)
            fallback_count = sum(record.used_baseline_fallback for record in records)
            rows.append([
                program,
                config,
                _fmt_number(_median(oracle_values)),
                _fmt_number(_median(proposed_values)),
                _fmt_percent(_rate(sum(hits), len(hits))) if hits else "—",
                _fmt_percent(_median(gaps)),
                _fmt_percent(_rate(fallback_count, len(records))),
            ])
    return rows


def _cost_rows(report, grouped):
    rows = []
    for config in (item["name"] for item in report.configs):
        records = [
            record for program in report.samples
            for record in grouped.get((program, config), [])
        ]
        rows.append([
            config,
            str(sum(record.llm_calls for record in records)),
            _fmt_number(_sum_metric(records, "prompt_tokens")),
            _fmt_number(_sum_metric(records, "completion_tokens")),
            _fmt_number(_sum_metric(records, "total_tokens")),
            _fmt_fixed(_sum_metric(records, "llm_latency_ms"), 3),
            _fmt_number(_metric(records, "rounds", correct_only=False)),
        ])
    return rows


def _iteration_rows(report, grouped):
    rows = []
    for config in (item["name"] for item in report.configs):
        records = [
            record for program in report.samples
            for record in grouped.get((program, config), [])
        ]
        stop_counts = Counter(record.stop_reason or "未记录" for record in records)
        stops = "；".join(
            f"{name}={count}" for name, count in sorted(stop_counts.items())
        ) or "—"
        rounds = [record.rounds for record in records]
        fallback_count = sum(record.used_baseline_fallback for record in records)
        rows.append([
            config,
            _fmt_number(_median(rounds)),
            _fmt_number(max(rounds) if rounds else None),
            stops,
            _fmt_percent(_rate(fallback_count, len(records))),
        ])
    return rows


def _pass_rows(report, grouped):
    rows = []
    for program in report.samples:
        for config in (item["name"] for item in report.configs):
            records = grouped.get((program, config), [])
            counts = Counter(tuple(record.passes) for record in records if record.correct)
            distribution = "；".join(
                f"{_fmt_passes(combo)} × {count}"
                for combo, count in sorted(
                    counts.items(), key=lambda item: (-item[1], len(item[0]), item[0])
                )
            ) or "—"
            rows.append([
                program,
                config,
                _fmt_passes(_modal_passes(records)),
                distribution,
            ])
    return rows


def _failure_rows(report):
    counts = Counter(
        (record.config, error)
        for record in report.records
        for error in record.errors
    )
    return [
        [config, str(count), error]
        for (config, error), count in sorted(
            counts.items(), key=lambda item: (item[0][0], item[0][1])
        )
    ]


def _conclusion(report, grouped):
    lines = []
    total = len(report.records)
    correct = sum(record.correct for record in report.records)
    lines.append(
        f"- 共记录 {total} 个 program/config/trial，正确性通过 {correct} 个"
        f"（{_fmt_percent(_rate(correct, total))}）。"
    )

    config_names = [item["name"] for item in report.configs]
    comparable = better = equal = worse = 0
    if "llm_only" in config_names and "agent_full" in config_names:
        for program in report.samples:
            llm_value = _metric(grouped.get((program, "llm_only"), []), "instr_count")
            full_value = _metric(grouped.get((program, "agent_full"), []), "instr_count")
            if llm_value is None or full_value is None:
                continue
            comparable += 1
            if full_value < llm_value:
                better += 1
            elif full_value == llm_value:
                equal += 1
            else:
                worse += 1
        lines.append(
            f"- `agent_full` 相对 `llm_only`：{better} 个程序更优、{equal} 个持平、"
            f"{worse} 个更差；可比较程序 {comparable} 个。"
        )

    for config in config_names:
        if config in ("baseline", "oracle"):
            continue
        records = [
            record for record in report.records
            if record.config == config and record.oracle_hit is not None
        ]
        hits = sum(bool(record.oracle_hit) for record in records)
        lines.append(
            f"- `{config}` 的系统最终选择命中 Oracle：{hits}/{len(records)}"
            f"（{_fmt_percent(_rate(hits, len(records)))}）。"
        )
    return "\n".join(lines)


def generate_report(
    value,
    *,
    title: str = DEFAULT_TITLE,
    strict: bool = False,
) -> str:
    """从 MatrixReport 或 dict 生成确定性 Markdown 正文。"""
    report = _coerce_report(value, strict=strict)
    grouped = _groups(report)
    environment = report.environment
    experiment = report.experiment

    config_rows = [[
        item.get("name", "—"),
        "是" if item.get("use_llm") else "否",
        str(item.get("n_candidates", "—")),
        str(item.get("max_rounds", "—")),
        "是" if item.get("use_feedback") else "否",
        item.get("description") or "—",
    ] for item in report.configs]
    sample_rows = [[
        sample,
        _SAMPLE_CAPABILITIES.get(sample, "未声明"),
        str(sum(record.program == sample for record in report.records)),
    ] for sample in report.samples]
    failure_rows = _failure_rows(report)

    sections = [
        f"# {title}",
        "## 1. 项目与实验目标\n\n"
        "在固定语言、IR、样例和优化 Pass 的前提下，对 baseline、LLM/Agent 配置与 "
        "Oracle 进行可复现比较。正确性是性能比较的前置条件，动态指令数是主指标。",
        "## 2. 实验环境\n\n" + _table(
            ["字段", "值"],
            [
                ["生成时间", report.generated_at],
                ["Python", _display(environment.get("python"))],
                ["平台", _display(environment.get("platform"))],
                ["Git commit", _display(environment.get("git_commit"))],
                ["Git dirty", _display(environment.get("git_dirty"))],
                ["模型", _display(experiment.get("model"))],
                ["temperature", _display(experiment.get("temperature"))],
                ["max tokens", _display(experiment.get("max_tokens"))],
                ["bench repeat", _display(experiment.get("bench_repeat"))],
                ["trials", report.trials],
                ["注册 Pass", ", ".join(experiment.get("registered_passes") or []) or "—"],
            ],
        ),
        "## 3. 配置定义\n\n" + _table(
            ["配置", "使用 LLM", "每轮候选上限", "最大轮数", "反馈", "定义"],
            config_rows,
        ),
        "## 4. 样例集和覆盖能力\n\n" + _table(
            ["样例", "覆盖能力", "原始记录数"], sample_rows
        ),
        "## 5. 正确性结果\n\n" + _table(
            ["配置", "正确记录", "记录总数", "正确率", "含错误/清洗事件记录"],
            _correctness_rows(report, grouped),
        ),
        "## 6. 每程序性能对比（表 A）\n\n" + _table(
            [
                "程序", "配置", "正确率", "指令数（中位数）", "降低比例",
                "时间中位数 (ms)", "内存峰值中位数 (KB)", "最优 Pass",
            ],
            _performance_rows(report, grouped),
        ),
        "## 7. 相对 baseline 的收益\n\n" + _table(
            ["程序", "配置", "baseline 指令数", "配置指令数", "减少指令", "降低比例"],
            _benefit_rows(report, grouped),
        ),
        "## 8. 运行时间和内存\n\n"
        "时间和 Python 峰值分配是辅助指标，不参与候选排名。\n\n" + _table(
            ["程序", "配置", "时间中位数 (ms)", "内存峰值中位数 (KB)"],
            _runtime_rows(report, grouped),
        ),
        "## 9. Agent 提案搜索质量（表 B）\n\n"
        "本表使用 `proposed_best`，不把 baseline 保底当成 Agent 自己找到的结果。\n\n"
        + _table(
            [
                "程序", "配置", "Oracle 指令数", "提案指令数", "提案命中率",
                "提案 gap", "baseline 保底率",
            ],
            _search_rows(report, grouped),
        ),
        "## 10. LLM 成本（表 C）\n\n" + _table(
            [
                "配置", "调用次数", "Prompt tokens", "Completion tokens",
                "Total tokens", "LLM 耗时合计 (ms)", "实际轮数中位数",
            ],
            _cost_rows(report, grouped),
        ),
        "## 11. Agent 实际迭代轮数\n\n" + _table(
            ["配置", "轮数中位数", "最大轮数", "停止原因", "baseline 保底率"],
            _iteration_rows(report, grouped),
        ),
        "## 12. 最优 Pass 组合\n\n" + _table(
            ["程序", "配置", "最常选择", "各 trial 分布"],
            _pass_rows(report, grouped),
        ),
        "## 13. 失败和淘汰原因摘要\n\n" + (
            _table(["配置", "次数", "原因"], failure_rows)
            if failure_rows else "未记录失败或清洗淘汰原因。"
        ),
        "## 14. 结论\n\n" + _conclusion(report, grouped),
        "## 15. 局限性和未来工作\n\n"
        "- 实验只覆盖报告列出的固定样例与已注册 Pass，结论不外推到其他程序。\n"
        "- 动态指令数是自定义 VM 的主指标，不等同于生产机器码性能。\n"
        "- 墙钟时间和 `tracemalloc` 峰值受 Python 运行环境影响，仅作为辅助指标。\n"
        "- LLM 结果只代表报告中的模型、参数和 trial；增加 trial 可进一步评估稳定性。",
    ]
    return "\n\n".join(sections) + "\n"


# 语义清晰的兼容别名，供调用方按“渲染 Markdown”理解这个纯函数。
render_markdown = generate_report


def write_report(text: str, output: str) -> str:
    path = os.path.abspath(output)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as file:
            file.write(text)
    except OSError as exc:
        raise ReportError(f"无法写入 Markdown 报告：{exc}") from exc
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="从 schema v2 矩阵生成 Markdown 报告")
    parser.add_argument("input", help="矩阵 JSON 文件")
    parser.add_argument("--output", help="输出 Markdown；省略时写到 stdout")
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--strict", action="store_true", help="要求完整矩阵且校验派生值")
    args = parser.parse_args(argv)

    try:
        report = load_matrix_report(args.input, strict=args.strict)
        text = generate_report(report, title=args.title, strict=args.strict)
        if args.output:
            path = write_report(text, args.output)
            print(f"报告已生成：{path}")
        else:
            print(text, end="")
    except ReportError as exc:
        print(f"report 失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
