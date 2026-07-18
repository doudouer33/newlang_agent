"""
死代码消除（DCE, dead code elimination）。

规则：一条指令 **def 了某个变量，但那个变量之后再也不会被读** → 整条删掉。
判断建立在 ir.uses() / ir.defs() 上，不重新发明。

================= 不能删的指令 =================
有副作用或影响控制流的指令一律保留，哪怕它们不 def 任何变量：

    print           输出，是程序的可观测行为
    store_idx       写数组，是副作用（注意它 def 的是"数组"这个变量，
                    但删掉它会丢掉一次写入，所以不能按普通 def 处理）
    label           跳转目标
    jump / jump_if_false    控制流

保守优先：拿不准的一律保留。宁可少删，不能删错。

================= 循环怎么办（这里有个坑）=================
朴素规则"看它**之后**的指令有没有读这个变量"在有回跳（backward jump）的
代码上是**错的**。看 loop_sum.nl 的基线 IR：

     3  L0_while:
     4      t0 = i <= n      ← i 在这里被读
     ...
     8      t2 = i + 1
     9      i = t2           ← i 在这里被写；它"之后"（10~12）没人读 i
    10      goto L0_while    ← 但这条回跳会让 4 号指令再次执行！
    11  L1_endwhile:
    12      print sum

按"只看之后"的规则，第 9 条会被判成死代码删掉，接着第 8 条也变死代码，
循环变量再也不自增 —— **死循环**。这不是保守不保守的问题，是编译错误。

所以"i 之后可能执行到的指令"不等于"下标 > i 的指令"。这里用一个**后缀区间
近似**来算它，仍然只做线性扫描，不建 CFG / 基本块 / 支配树：

    起始 start = i + 1；
    若区间 [start, n) 里存在一条跳转，其目标标签的下标 k < start，
    说明从 i 之后还能绕回到更早的位置，就把 start 降到 k；重复到不动点。

start 只减不增，所以必然收敛。区间 [start, n) 是"可能在 i 之后执行的指令"
的一个超集 —— 超集意味着我们可能把某些其实已死的指令判活（少删），
但绝不会把活的判死（删错）。方向是对的。

================= 为什么用不动点迭代 =================
删掉一条指令会让它的上游变成新的死代码（`t2 = i + 1` 只被 `i = t2` 读，
后者一删，前者也死了）。所以整趟扫描反复跑，直到 IR 不再变化为止。
（另一种写法是从后往前扫一遍、边扫边维护活跃变量集合；这里选不动点，
因为它和上面的"后缀区间"近似组合起来更直白，正确性一眼可查。）
"""
from lang.ir import uses, defs


# 有副作用 / 控制流的指令：无论 def 了什么都不删
SIDE_EFFECT_OPS = {"print", "store_idx", "label", "jump", "jump_if_false"}

_JUMP_OPS = {"jump", "jump_if_false"}


def _label_index(instrs):
    """标签名 → 指令下标。跳转类指令把 label 放在 dst 槽。"""
    return {instr[1]: i for i, instr in enumerate(instrs) if instr[0] == "label"}


def _uses_after(instrs, i, labels):
    """可能在第 i 条之后执行的指令所读取的变量集合（超集近似，见模块注释）。"""
    n = len(instrs)
    start = i + 1

    # 不动点：区间里出现回跳，就把区间往前扩。
    changed = True
    while changed:
        changed = False
        for j in range(start, n):
            op, target = instrs[j][0], instrs[j][1]
            if op in _JUMP_OPS:
                k = labels.get(target)
                if k is not None and k < start:
                    start = k          # 能绕回到 k，k 之后的指令都可能重跑
                    changed = True
                    break

    live = set()
    for j in range(start, n):
        live |= uses(instrs[j])
    return live


def _dce_once(instrs):
    """扫一趟，删掉这一趟能确定的死指令。"""
    labels = _label_index(instrs)
    kept = []

    for i, instr in enumerate(instrs):
        if instr[0] in SIDE_EFFECT_OPS:
            kept.append(instr)                  # 副作用 / 控制流：保留
            continue

        written = defs(instr)
        if not written:
            kept.append(instr)                  # 既无副作用也不 def：保守保留
            continue

        if written & _uses_after(instrs, i, labels):
            kept.append(instr)                  # 写的变量之后还要读：活的
        # else: 死代码，丢弃

    return kept


def dce(instrs: list) -> list:
    """输入一段 IR，返回消除死代码后的新 IR（纯函数，不原地修改输入）。"""
    current = list(instrs)
    while True:
        nxt = _dce_once(current)
        if nxt == current:                      # 不动点：这一趟没删掉任何东西
            return nxt
        current = nxt
