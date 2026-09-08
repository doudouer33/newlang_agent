"""运行固定样例集的 baseline / 优化档对比实验。

优化档会穷举当前已注册 pass 的所有非重复排列，并在正确性通过的候选中按
``指令数 → pass 数量 → pass 名称``选择最优。这样第三阶段的基准实验不依赖
外部 API，任何人都能复现；LLM + Agent 负责从同一个候选空间中智能挑选组合，
后续四档实验可以复用这里的测量和报告格式。

用法：
    python -m benchmark.runner
    python -m benchmark.runner --repeat 5
    python -m benchmark.runner --samples licm_demo dead_code
"""
from __future__ import annotations

import argparse
import itertools
import os
import platform
import sys
from datetime import datetime

from main import parse_expected
from optimizer import available_passes
from tools import build, run_bench, run_tests, save_result


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES_DIR = os.path.join(ROOT, "lang", "samples")

# 老师要求固定 3~5 个程序；本轮保留已有 5 个，并新增 dead_code 作为第二个
# 能稳定展示收益的案例，所以这里共跑 6 个。
DEFAULT_SAMPLES = (
    "basic",
    "branch",
    "loop_sum",
    "array_dot",
    "licm_demo",
    "dead_code",
)


def pass_combinations(names=None):
    """返回 baseline + 所有不重复 pass 排列，顺序稳定、结果可复现。"""
    names = tuple(sorted(names or available_passes()))
    return [()] + [
        combo
        for size in range(1, len(names) + 1)
        for combo in itertools.permutations(names, size)
    ]


def _load_sample(name: str):
    path = os.path.join(SAMPLES_DIR, name + ".nl")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"找不到样例：{path}")
    with open(path, encoding="utf-8") as f:
        source = f.read()
    expected = parse_expected(source)
    if expected is None:
        raise ValueError(f"样例 {name}.nl 没有 // expect: 注释，无法验证正确性")
    return path, source, expected


def _measure(source: str, expected: list[int], passes: tuple[str, ...], repeat: int):
    """编译、验证、测量一个候选；所有失败都进入结果，不中断整场实验。"""
    row = {
        "passes": list(passes),
        "compiled": False,
        "correct": False,
        "output": None,
        "instr_count": None,
        "time_ms": None,
        "error": "",
    }

    built = build({"source": source, "passes": list(passes)})
    if not built.get("ok"):
        row["error"] = built.get("error") or "编译失败"
        return row
    row["compiled"] = True

    tested = run_tests({"bytecode": built["bytecode"], "expected": expected})
    row["correct"] = bool(tested.get("correct"))
    row["output"] = tested.get("output")
    if tested.get("error"):
        row["error"] = tested["error"]

    bench = run_bench({"bytecode": built["bytecode"], "repeat": repeat})
    row["instr_count"] = bench.get("instr_count")
    row["time_ms"] = bench.get("time_ms")
    if bench.get("error") and not row["error"]:
        row["error"] = bench["error"]
    return row


def _viable(row):
    return row["compiled"] and row["correct"] and row["instr_count"] is not None


def _best_optimized(candidates):
    viable = [row for row in candidates if row["passes"] and _viable(row)]
    if not viable:
        return None
    return min(
        viable,
        key=lambda row: (row["instr_count"], len(row["passes"]), row["passes"]),
    )


def _comparison(baseline, optimized):
    if not _viable(baseline) or optimized is None:
        return {"saved_instructions": None, "reduction_percent": None, "improved": False}
    saved = baseline["instr_count"] - optimized["instr_count"]
    percent = saved / baseline["instr_count"] * 100 if baseline["instr_count"] else 0.0
    return {
        "saved_instructions": saved,
        "reduction_percent": round(percent, 2),
        "improved": saved > 0,
    }


def run_benchmark(samples=None, *, repeat: int = 5, save: bool = True):
    """运行完整实验，返回 ``(report, saved_path)``。"""
    if repeat < 1:
        raise ValueError("repeat 必须大于等于 1")

    sample_names = tuple(samples or DEFAULT_SAMPLES)
    combos = pass_combinations()
    programs = []

    for name in sample_names:
        path, source, expected = _load_sample(name)
        candidates = [_measure(source, expected, combo, repeat) for combo in combos]
        baseline = candidates[0]
        optimized = _best_optimized(candidates)
        programs.append({
            "program": name,
            "source_path": os.path.relpath(path, ROOT),
            "expected": expected,
            "baseline": baseline,
            "optimized": optimized,
            "comparison": _comparison(baseline, optimized),
            "candidates": candidates,
        })

    report = {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "experiment": {
            "name": "baseline_vs_optimized",
            "selection_metric": "instr_count",
            "repeat": repeat,
            "registered_passes": list(available_passes()),
            "candidate_count_per_program": len(combos),
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "summary": {
            "program_count": len(programs),
            "correct_baselines": sum(_viable(p["baseline"]) for p in programs),
            "correct_optimized": sum(p["optimized"] is not None for p in programs),
            "programs_improved": sum(p["comparison"]["improved"] for p in programs),
        },
        "programs": programs,
    }

    saved_path = None
    if save:
        saved = save_result({"data": report, "name": "benchmark"})
        if not saved.get("ok"):
            raise RuntimeError(f"保存 benchmark 失败：{saved.get('error')}")
        saved_path = saved["path"]
    return report, saved_path


def format_markdown(report: dict) -> str:
    """把报告摘要渲染成可直接粘贴到周报的 Markdown 表格。"""
    lines = [
        "| 程序 | baseline 指令数 | 优化后指令数 | 减少 | 收益 | 最优 Pass | 正确性 |",
        "|---|---:|---:|---:|---:|---|:---:|",
    ]
    for item in report["programs"]:
        base = item["baseline"]
        opt = item["optimized"]
        cmp = item["comparison"]
        opt_count = opt["instr_count"] if opt else None
        passes = ", ".join(opt["passes"]) if opt else "—"
        correct = "✓" if _viable(base) and opt is not None and opt["correct"] else "✗"
        reduction = (
            f"{cmp['reduction_percent']:.2f}%"
            if cmp["reduction_percent"] is not None
            else "—"
        )
        lines.append(
            f"| `{item['program']}` | {base['instr_count']} | {opt_count} | "
            f"{cmp['saved_instructions']} | {reduction} | `{passes}` | {correct} |"
        )
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="运行 baseline / 优化档对比实验")
    parser.add_argument("--repeat", type=int, default=5, help="每个候选的重复测量次数")
    parser.add_argument("--samples", nargs="+", help="只运行指定样例（不含 .nl）")
    parser.add_argument("--no-save", action="store_true", help="只打印，不写入 runs/")
    args = parser.parse_args(argv)

    try:
        report, path = run_benchmark(
            args.samples, repeat=args.repeat, save=not args.no_save
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"benchmark 失败：{exc}", file=sys.stderr)
        return 1

    print(format_markdown(report))
    print(
        f"\n汇总：{report['summary']['programs_improved']}/"
        f"{report['summary']['program_count']} 个程序获得严格收益。"
    )
    if path:
        print(f"完整结果：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
