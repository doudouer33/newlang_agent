"""
阶段一入口：把整条链跑通并打印每一步的中间产物，
方便你亲眼看到 源码 → 解析树 → AST → 三地址码 IR → 执行结果 → 指令数。

用法：
    python main.py            # 跑 lang/samples 下的全部样例
    python main.py basic      # 只跑某个样例（文件名去掉 .nl）
    python main.py --quiet    # 只看结果和指令数，不打印中间产物
"""
import os
import re
import sys

from lark import Lark

from lang.transformer import ASTBuilder
from lang.ir import build_ir, format_ir
from lang.vm import VM

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES_DIR = os.path.join(HERE, "lang", "samples")

# 样例按"从简到繁"排；每个样例源码里用 `// expect: ...` 标注预期输出，
# 由下面的 parse_expected 读出来自动核对，不用人肉对答案。
SAMPLE_ORDER = ["basic", "branch", "loop_sum", "array_dot", "licm_demo"]


def load_parser():
    grammar_path = os.path.join(HERE, "lang", "grammar.lark")
    with open(grammar_path, encoding="utf-8") as f:
        grammar = f.read()
    # earley 解析器能直接处理这种带左递归的表达式文法
    return Lark(grammar, start="start")


def parse_expected(source):
    """从源码注释 `// expect: 7, 9, 16` 里读出预期输出；没写就返回 None。"""
    m = re.search(r"//\s*expect:\s*(.+)", source)
    if not m:
        return None
    return [int(x) for x in m.group(1).split(",")]


def run_sample(parser, name, verbose=True):
    path = os.path.join(SAMPLES_DIR, name + ".nl")
    with open(path, encoding="utf-8") as f:
        source = f.read()

    print("\n" + "=" * 60)
    print(f"### 样例：{name}.nl")
    print("=" * 60)

    if verbose:
        print("\n=== 1. 源码 ===")
        print(source)

    tree = parser.parse(source)
    if verbose:
        print("=== 2. Lark 解析树 ===")
        print(tree.pretty())

    ast = ASTBuilder().transform(tree)
    if verbose:
        print("=== 3. AST（transformer 翻译后）===")
        for stmt in ast.statements:
            print("  ", stmt)

    code = build_ir(ast)
    if verbose:
        print("\n=== 4. 三地址码 IR ===")
        print(format_ir(code))

    print("\n=== 5. 执行结果 ===")
    vm = VM()
    output = vm.run(code)

    print(f"\n=== 6. 指标：IR 共 {len(code)} 条指令，"
          f"实际执行 {vm.instr_count} 条 ===")

    expected = parse_expected(source)
    if expected is None:
        print("    （该样例未标注 expect，跳过核对）")
        return True
    ok = output == expected
    mark = "✅ 正确" if ok else "❌ 错误"
    print(f"=== 7. 核对：预期 {expected}，实际 {output} → {mark} ===")
    return ok


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    verbose = "--quiet" not in sys.argv

    parser = load_parser()
    names = args if args else SAMPLE_ORDER

    results = {name: run_sample(parser, name, verbose) for name in names}

    print("\n" + "=" * 60)
    print("### 汇总")
    for name, ok in results.items():
        print(f"  {'✅' if ok else '❌'}  {name}.nl")
    print("=" * 60)
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
