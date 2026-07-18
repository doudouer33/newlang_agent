"""tools/ 的端到端测试：源码进去，正确性 + 指令数出来。

跑法（项目根目录下）：
    python tests/test_tools.py        # 不依赖 pytest，直接跑
    pytest tests/                     # 装了 pytest 也能跑（函数名是 test_*）

这里测的不是某个函数的返回值，而是整条链：
    build(baseline) / build(优化档) → run_tests 对答案 → run_bench 量指令数

两条铁律在这里变成断言：
  1. 优化不能改变结果 —— 两个档的 output 必须一模一样；
  2. 优化要有收益 —— 优化档的 instr_count ≤ baseline。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import parse_expected                                     # noqa: E402
from tools import build, run_bench, run_tests, save_result          # noqa: E402
from tools.registry import UnknownToolError, call_tool              # noqa: E402

SAMPLES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "lang", "samples",
)

# 阶段三要比的两个档：baseline 是"什么都不做"，优化档是同一条 build 路径 + passes。
BASELINE = []
OPTIMIZED = ["const_fold", "dce"]

# 专门给 const_fold + dce 准备的最小程序（samples 里的四个都没有死代码，
# 跑出来 instr_count 打平，看不出收益）：
#   - `2 * 3 + 4` 是编译期常量  → const_fold 有活干
#   - `dead` 算完就再没人读它   → dce 整条删掉
# 期望输出只有 11，dead 不该影响任何可观测行为。
DEAD_CODE_SRC = """
let x = 2 * 3 + 4;
let dead = x * 100;
let y = x + 1;
print y;
"""
DEAD_CODE_EXPECTED = [11]


def _load_sample(name):
    """读一个样例，顺带从 `// expect:` 注释里取出期望输出。"""
    with open(os.path.join(SAMPLES_DIR, name + ".nl"), encoding="utf-8") as f:
        source = f.read()
    return source, parse_expected(source)


# ==================================================================
# build：baseline 和优化档共用同一条路径，差别只在 passes
# ==================================================================

def test_build_baseline_ok():
    source, _ = _load_sample("basic")
    out = build({"source": source, "passes": BASELINE})
    assert out["ok"] is True, out["error"]
    assert out["error"] == ""
    assert len(out["bytecode"]) > 0
    # IR 是定长 4 元组
    assert all(len(instr) == 4 for instr in out["bytecode"])


def test_build_optimized_ok():
    source, _ = _load_sample("basic")
    out = build({"source": source, "passes": OPTIMIZED})
    assert out["ok"] is True, out["error"]
    assert len(out["bytecode"]) > 0


def test_build_applies_passes_between_ir_and_vm():
    """passes 确实作用在 IR 上：优化档的 IR 必须和 baseline 不同。

    basic.nl 里 `1 + 2 * 3` 有编译期常量，const_fold 一定会动它。
    如果两段 IR 一模一样，说明 apply_passes 根本没接进去。
    """
    source, _ = _load_sample("basic")
    base = build({"source": source, "passes": BASELINE})["bytecode"]
    opt = build({"source": source, "passes": OPTIMIZED})["bytecode"]
    assert base != opt


def test_build_syntax_error_is_reported_not_raised():
    """编译错误必须落到 error 字段里，不能把异常扔出工具。"""
    out = build({"source": "let x = ;;;", "passes": BASELINE})
    assert out["ok"] is False
    assert out["bytecode"] is None
    assert out["error"]              # 有话说，不是空字符串


def test_build_unknown_pass_is_reported_not_raised():
    out = build({"source": "print 1;", "passes": ["没这个pass"]})
    assert out["ok"] is False
    assert out["bytecode"] is None
    assert "没这个pass" in out["error"]


# ==================================================================
# run_tests：正确性是第一道闸
# ==================================================================

def test_run_tests_correct_on_all_samples():
    """四个样例，baseline 和优化档都得跑出 `// expect:` 标的答案。"""
    for name in ["basic", "branch", "loop_sum", "array_dot"]:
        source, expected = _load_sample(name)
        for passes in [BASELINE, OPTIMIZED]:
            built = build({"source": source, "passes": passes})
            assert built["ok"], f"{name} 编译失败: {built['error']}"

            out = run_tests({"bytecode": built["bytecode"], "expected": expected})
            assert out["correct"] is True, f"{name}/{passes}: {out}"
            assert out["output"] == expected
            assert out["error"] == ""


def test_optimization_does_not_change_output():
    """★ 正确性底线：优化前后输出必须逐字节一致。

    这条比"结果等于 expected"更强 —— 万一 expected 本身标错了，这条仍然能抓住
    "优化改变了程序行为"。
    """
    for name in ["basic", "branch", "loop_sum", "array_dot"]:
        source, expected = _load_sample(name)
        base_bc = build({"source": source, "passes": BASELINE})["bytecode"]
        opt_bc = build({"source": source, "passes": OPTIMIZED})["bytecode"]

        base_out = run_tests({"bytecode": base_bc, "expected": expected})
        opt_out = run_tests({"bytecode": opt_bc, "expected": expected})
        assert base_out["output"] == opt_out["output"], name


def test_run_tests_wrong_answer_is_not_an_error():
    """答案不对 ≠ 跑崩了：correct=False，但 error 是空的（程序跑通了，只是结果不符）。
    工具只报事实，"这算不算失败"由上层判断。"""
    built = build({"source": "print 1;", "passes": BASELINE})
    out = run_tests({"bytecode": built["bytecode"], "expected": [999]})
    assert out["correct"] is False
    assert out["output"] == [1]
    assert out["error"] == ""


def test_run_tests_runtime_error_is_reported_not_raised():
    """读一个没赋值的变量 → VM 抛 KeyError → 必须变成 error 字段，不能冒泡。"""
    out = run_tests({"bytecode": [("print", None, "从未定义", None)], "expected": [1]})
    assert out["correct"] is False
    assert out["error"]


# ==================================================================
# run_bench：指令数是主要信号
# ==================================================================

def test_bench_returns_metrics():
    source, _ = _load_sample("loop_sum")
    built = build({"source": source, "passes": BASELINE})
    out = run_bench({"bytecode": built["bytecode"]})
    assert out["error"] == ""
    assert isinstance(out["instr_count"], int) and out["instr_count"] > 0
    assert isinstance(out["time_ms"], float) and out["time_ms"] >= 0.0


def test_bench_instr_count_is_deterministic():
    """同一段 IR 跑两遍，指令数必须一模一样 —— 它是能写进断言的那个指标。
    （time_ms 就不行，两遍必然不同，所以这里不碰它。）"""
    source, _ = _load_sample("array_dot")
    bc = build({"source": source, "passes": BASELINE})["bytecode"]
    a = run_bench({"bytecode": bc})["instr_count"]
    b = run_bench({"bytecode": bc, "repeat": 3})["instr_count"]
    assert a == b


def test_optimized_instr_count_not_worse_than_baseline():
    """★ 收益方向：优化档的指令数不能比 baseline 高。四个样例都得成立。"""
    for name in ["basic", "branch", "loop_sum", "array_dot"]:
        source, _ = _load_sample(name)
        base_bc = build({"source": source, "passes": BASELINE})["bytecode"]
        opt_bc = build({"source": source, "passes": OPTIMIZED})["bytecode"]

        base = run_bench({"bytecode": base_bc})["instr_count"]
        opt = run_bench({"bytecode": opt_bc})["instr_count"]
        assert opt <= base, f"{name}: 优化档 {opt} 反而比 baseline {base} 还多"


def test_dead_code_program_shows_real_savings():
    """★ 收益是真的：死变量 + 常量运算的程序上，指令数必须**严格下降**。

    只断言 `<=` 是不够的 —— 一个什么都不做的 apply_passes 也能满足 `<=`。
    这条测试保证优化确实干了活：dead 那两条（mul + copy）被 dce 删掉了。
    """
    base_bc = build({"source": DEAD_CODE_SRC, "passes": BASELINE})["bytecode"]
    opt_bc = build({"source": DEAD_CODE_SRC, "passes": OPTIMIZED})["bytecode"]

    base_run = run_tests({"bytecode": base_bc, "expected": DEAD_CODE_EXPECTED})
    opt_run = run_tests({"bytecode": opt_bc, "expected": DEAD_CODE_EXPECTED})
    assert base_run["correct"] and opt_run["correct"]      # 先过正确性
    assert base_run["output"] == opt_run["output"]         # 再看输出一致

    base = run_bench({"bytecode": base_bc})["instr_count"]
    opt = run_bench({"bytecode": opt_bc})["instr_count"]
    assert opt < base, f"优化档 {opt} 没能低于 baseline {base}，说明 pass 白跑了"


def test_bench_runtime_error_is_reported_not_raised():
    out = run_bench({"bytecode": [("div", "t0", 1, 0)]})
    assert out["error"]
    assert out["instr_count"] is None      # 不谎报成 0
    assert out["time_ms"] is None


# ==================================================================
# save_result：落盘能读回来
# ==================================================================

def test_save_result_writes_readable_json():
    data = {"passes": OPTIMIZED, "instr_count": 42, "note": "中文也要存得住"}
    out = save_result({"data": data, "name": "test_tools"})

    assert out["ok"] is True, out["error"]
    assert out["error"] == ""
    assert os.path.exists(out["path"])
    assert out["path"].endswith(".json")
    assert "runs" in out["path"]

    with open(out["path"], encoding="utf-8") as f:
        assert json.load(f) == data          # 原样读回来

    os.remove(out["path"])                   # 测试不留垃圾


def test_save_result_unserializable_data_is_reported_not_raised():
    """塞个不能 JSON 化的东西进去 → ok=False，不抛异常，且不留半截坏文件。

    历史上的 bug：save 边序列化边往打开的文件流里写，序列化到一半才炸，磁盘上
    就留下一个 `{\\n  "f": ` 的残缺文件。这里除了断言 ok=False，还断言 runs/ 里
    没有新增任何文件 —— 失败就根本不该碰磁盘。
    """
    runs_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runs"
    )
    before = set(os.listdir(runs_dir)) if os.path.isdir(runs_dir) else set()

    out = save_result({"data": {"f": lambda x: x}, "name": "bad"})
    assert out["ok"] is False
    assert out["error"]
    assert out["path"] == ""

    after = set(os.listdir(runs_dir)) if os.path.isdir(runs_dir) else set()
    leftover = after - before
    assert not leftover, f"序列化失败却留下了文件: {leftover}"


# ==================================================================
# Tool Router：查表 + 调用
# ==================================================================

def test_call_tool_dispatches():
    """走 Router 调 build，结果应该和直接调 build 一模一样。"""
    source, expected = _load_sample("loop_sum")
    inp = {"source": source, "passes": OPTIMIZED}

    routed = call_tool("build", inp)
    direct = build(inp)
    assert routed["ok"] is True
    assert routed["bytecode"] == direct["bytecode"]

    # 四个工具都得能从 Router 走通：build → run_tests → run_bench → save_result
    checked = call_tool("run_tests", {"bytecode": routed["bytecode"], "expected": expected})
    assert checked["correct"] is True

    metrics = call_tool("run_bench", {"bytecode": routed["bytecode"]})
    assert metrics["instr_count"] > 0

    saved = call_tool("save_result", {"data": {"ok": True}, "name": "router"})
    assert saved["ok"] is True
    os.remove(saved["path"])


def test_call_tool_unknown_name_raises():
    """名字没注册就得当场炸，且报清楚是哪个名字 —— 不能静默返回空。"""
    try:
        call_tool("不存在的工具", {})
    except UnknownToolError as e:
        assert "不存在的工具" in str(e)
    else:
        raise AssertionError("调用未注册的工具名，居然没抛 UnknownToolError")


# ==================================================================
# 不装 pytest 也能跑
# ==================================================================

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
