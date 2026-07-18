"""build：源码 → 可执行 IR。

流水线，次序不能错：

    source ──Lark──► 解析树 ──ASTBuilder──► AST ──build_ir──► 原始 IR
                                                                │
                                              apply_passes(passes, ·)
                                                                ▼
                                                            优化后 IR（产物）

apply_passes 插在"原始 IR 已生成、还没交给 VM"这个点上，这是整个系统里唯一
做优化的地方。build 本身**一行优化逻辑都没有**，它只做编排：想换优化策略，
改的是 passes 列表，不是这个文件。

★ passes=[] 就是 baseline。baseline 和优化档共用这同一条路径，唯一的差别是
  passes 列表的内容。不给 baseline 开小灶，两边才可比 —— 否则"优化带来的收益"
  里会混进"两条代码路径本来就不同"的噪声。
"""
import os

from lark import Lark

from lang.ir import build_ir
from lang.transformer import ASTBuilder
from optimizer.registry import apply_passes

_GRAMMAR_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "lang", "grammar.lark",
)

# 建 Lark 解析器要读文法、算分析表，比较慢；Agent 会反复调 build（同一段源码
# 配不同的 passes 组合），所以解析器建一次就缓存住。
_parser = None


def _get_parser():
    global _parser
    if _parser is None:
        with open(_GRAMMAR_PATH, encoding="utf-8") as f:
            grammar = f.read()
        _parser = Lark(grammar, start="start")     # earley：直接吃左递归表达式文法
    return _parser


def build(inp: dict) -> dict:
    """{"source": str, "passes": list[str]} -> {"ok", "bytecode", "error"}

    bytecode 就是优化后的 IR 指令列表（定长 4 元组 (op, dst, src1, src2)），
    VM 能直接执行的形态。字段名沿用 "bytecode" 是为了和上层的叫法一致。

    失败（语法错、未知 pass、…）时 ok=False、bytecode=None、error 是人能看懂的
    一句话。不抛异常。
    """
    source = inp.get("source", "")
    passes = inp.get("passes", []) or []

    try:
        tree = _get_parser().parse(source)
        ast = ASTBuilder().transform(tree)
        instrs = build_ir(ast)                     # 原始 IR（baseline 形态）
        bytecode = apply_passes(passes, instrs)    # 优化的唯一入口
    except Exception as e:
        # 解析错误、未知 pass、pass 内部炸了——都算编译失败，如实上报。
        return {"ok": False, "bytecode": None, "error": f"{type(e).__name__}: {e}"}

    return {"ok": True, "bytecode": bytecode, "error": ""}
