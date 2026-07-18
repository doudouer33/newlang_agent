"""
常量折叠（constant folding）。

思路一句话：**一条指令的两个 src 槽都是字面量（int）时，编译期就把结果算出来，
整条指令换成 `copy`。** 三地址码把操作数直接写在指令里，所以这个判断是纯局部的
——只看这一条指令，不需要任何数据流分析。

    ("mul", "t0", 2, 3, )   →   ("copy", "t0", 6, None)
    ("add", "t1", 1, "x")   →   原样保留（"x" 是变量，编译期不知道值）

边界（重要）：
  - div 除数为 0 时**不折叠**，原样保留，交给运行时去炸。编译期不能替程序
    决定"这里一定会崩"——这条指令可能根本执行不到（在 if 的死分支里）。
  - 折叠 div 用 `//`（向下取整），和 VM 的 `_val(s1) // _val(s2)` 完全一致。
    折叠出来的常量必须和运行时算出来的一模一样，否则优化就改变了程序语义。
  - 比较类（lt/gt/…）同样折叠，结果用 1/0 表示，和 VM 的 `int(a < b)` 一致。

**刻意不做**：常量传播。本 pass 只看单条指令的 src 槽，不会把
`t0 = 6` 的 6 代进后面用到 t0 的指令里。所以 `t0 = 2 * 3; t1 = t0 + 1`
只折掉第一条，t1 那条留着。常量传播是另一个 pass 的活（后面可以加），
把它混进来会让这个 pass 不再是"纯局部"的，也不好讲清楚。
"""
from lang.ir import ARITH_OPS, CMP_OPS


# 每个可折叠操作码 → 它在编译期的求值函数。
# 这些语义必须和 lang/vm.py 里的实现逐条对应（尤其是 div 的 // 和比较的 int()）。
_FOLD = {
    "add": lambda a, b: a + b,
    "sub": lambda a, b: a - b,
    "mul": lambda a, b: a * b,
    "div": lambda a, b: a // b,          # 整数除法，与 VM 一致
    "lt": lambda a, b: int(a < b),
    "gt": lambda a, b: int(a > b),
    "le": lambda a, b: int(a <= b),
    "ge": lambda a, b: int(a >= b),
    "eq": lambda a, b: int(a == b),
    "ne": lambda a, b: int(a != b),
}

# 自检：别让 ir.py 加了新算术/比较指令而这里忘记跟进。
assert (ARITH_OPS | CMP_OPS) == set(_FOLD), "折叠表和 ir.py 的操作码对不上"


def _is_const(slot):
    """src 槽里 int 是字面量常量、str 是变量名——这是区分二者的唯一依据。"""
    return isinstance(slot, int)


def const_fold(instrs: list) -> list:
    """输入一段 IR，返回折叠后的新 IR（纯函数，不原地修改输入）。"""
    out = []
    for instr in instrs:
        op, dst, s1, s2 = instr

        if op in _FOLD and _is_const(s1) and _is_const(s2):
            if op == "div" and s2 == 0:
                out.append(instr)            # 除零：不折叠，留给运行时
            else:
                out.append(("copy", dst, _FOLD[op](s1, s2), None))
        else:
            out.append(instr)                # 其他指令一律原样保留

    return out
