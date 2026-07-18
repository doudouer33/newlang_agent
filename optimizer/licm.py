"""
循环不变量外提（LICM, loop-invariant code motion）。

规则一句话：**循环体里某条指令，它读的东西每轮都一样、算出来的结果也每轮
一样，就把它提到循环外算一次。** 循环跑 N 轮，就省下 N-1 次重复计算 ——
这正是 README 里说的"循环密集负载"上最直观的收益来源。

    while (i < n) {
        s = s + k * n;      // k、n 循环里都不变 → k*n 每轮都算同一个值
        i = i + 1;
    }
        ↓  把 `t = k * n` 提到循环外
    t = k * n;              // 只算一次
    while (i < n) {
        s = s + t;
        i = i + 1;
    }

================= 怎么在"没有 CFG"的前提下做 =================
README 明确刻意不建 CFG / 支配树。好在 IRBuilder 生成的循环形状是**固定套路**：

     lo  L_top:                    ← while 的入口标签
         <算 cond>
         if not cond goto L_end
         <循环体……>
     hi  goto L_top                ← 唯一的**回跳**（backward jump），就是它标识出循环

于是"找循环"退化成"找回跳"：一条 jump/jump_if_false，其目标标签的下标 < 它
自己的下标，[目标标签, 回跳] 这段区间就是一个循环。if 只会**向前**跳
（跳到 L_else / L_end），永远不会产生回跳，所以"回跳 ⟺ while 的循环边"成立，
不会把 if 误判成循环。

================= 什么指令能提、为什么这么提是安全的 =================
一条指令 (op, dst, s1, s2) 满足以下**全部**条件才外提：

  1. op 是**纯标量运算**（copy / add / sub / mul / 比较），无副作用、不访存。
     - 排除 div：除零会抛异常。若循环一轮都没进（cond 一上来就假），把 div
       提到循环外就凭空执行了一次，可能触发本不该发生的除零崩溃。其余纯运算
       多算一次顶多浪费、绝不改变结果，所以只有 div 需要排除。
     - 排除 load_idx / store_idx / newarray：涉及内存，循环里别处可能改数组。
     - 排除 print / 控制流：有副作用 / 是循环结构本身。

  2. dst 是**编译器临时变量**（t0/t1/…）。IRBuilder 的临时变量在整个程序里
     **只被赋值一次、且总是先赋值后使用**（它就是某个子表达式的结果，紧跟着
     被同一个基本块里的下一条指令消费）。这个"单赋值 + 先定义后使用"的性质是
     外提安全的关键：
       - 单赋值 → 提到循环外不会覆盖掉别处对同名变量的赋值；
       - 定义和使用同在一个基本块 → 不存在"某轮没执行到 def、却读到了它"的路径，
         所以就算把它提到循环外无条件执行，也没有哪次读取会看出差别。
     防御性地再查一遍"全程只定义一次"，手写 IR 里若有同名重复赋值就不动它。

  3. 它读的每个变量都是**循环不变量**：在循环体里从没被改过（不在 modified 集合），
     或者是本轮已决定外提的另一个临时变量（外提后它也变成循环外的量了）。
     用不动点迭代：t0 提出去后，"只依赖 t0 的 t1"下一轮也够格外提，链式提净。

外提位置：插在循环入口标签**之前**（相当于经典 LICM 的 preheader），每轮一次
变成进入循环前一次。嵌套循环时，对**外层**循环整段区间做不变量分析：既不变于
外层、又不变于内层的指令会被直接提到最外层标签前（提得越远、省得越多）；只不变
于内层的，则由内层区间那一轮把它提到内外层之间。pass 级不动点保证提到位。
"""
import re
from collections import Counter

from lang.ir import ARITH_OPS, CMP_OPS, defs, uses


# 纯、不抛异常的标量运算：提到循环外多执行一次也绝不改变程序结果。
# div 从 ARITH_OPS 里摘掉（除零会抛），理由见模块注释。
HOISTABLE_OPS = (ARITH_OPS | CMP_OPS | {"copy"}) - {"div"}

_JUMP_OPS = {"jump", "jump_if_false"}

# 编译器临时变量：t 后面跟纯数字（t0, t1, …）。用户变量不长这样。
_TEMP_RE = re.compile(r"t\d+")


def _is_temp(name):
    return isinstance(name, str) and _TEMP_RE.fullmatch(name) is not None


def _label_index(instrs):
    """标签名 → 指令下标。跳转类指令把 label 放在 dst 槽。"""
    return {instr[1]: i for i, instr in enumerate(instrs) if instr[0] == "label"}


def _def_counts(instrs):
    """每个变量在整段 IR 里被 def 了几次（用来确认临时变量确是单赋值）。"""
    c = Counter()
    for instr in instrs:
        for d in defs(instr):
            c[d] += 1
    return c


def _find_loops(instrs, labels):
    """找出所有循环区间 (lo, hi)：lo=入口标签下标，hi=回跳下标，lo < hi。

    回跳 = 目标标签在自己**之前**的跳转。按 lo 升序返回（外层在前），这样对
    嵌套循环先按外层大区间做分析，双重不变量能一次提到最外层。
    """
    loops = []
    for hi, instr in enumerate(instrs):
        op, target = instr[0], instr[1]
        if op in _JUMP_OPS:
            lo = labels.get(target)
            if lo is not None and lo < hi:
                loops.append((lo, hi))
    loops.sort()
    return loops


def _hoistable_in_region(instrs, lo, hi, def_counts):
    """区间 (lo, hi) 内可外提指令的下标列表（保持原顺序）。"""
    body = range(lo + 1, hi)          # 去掉 lo 处的标签和 hi 处的回跳

    # 循环体里被改过的变量 —— 它们随轮次变化，是"变量"而非"不变量"。
    modified = set()
    for k in body:
        modified |= defs(instrs[k])

    chosen = set()                    # 已决定外提的指令下标
    invariant = set()                 # 外提后变成循环外量的临时变量名

    # 不动点：提出去一个临时变量，依赖它的下一条可能随之够格，反复扫到不再变化。
    changed = True
    while changed:
        changed = False
        for k in body:
            if k in chosen:
                continue
            op, dst, _s1, _s2 = instrs[k]
            if op not in HOISTABLE_OPS:
                continue
            if not _is_temp(dst) or def_counts[dst] != 1:
                continue
            # 读的每个变量要么循环里没被改过，要么是已外提的临时变量。
            used = uses(instrs[k])
            if any(u in modified and u not in invariant for u in used):
                continue
            chosen.add(k)
            invariant.add(dst)
            changed = True

    return [k for k in body if k in chosen]


def _licm_once(instrs):
    """扫一趟：找第一个有可外提指令的循环，把那些指令提到它的入口标签前。"""
    labels = _label_index(instrs)
    def_counts = _def_counts(instrs)

    for lo, hi in _find_loops(instrs, labels):
        hoist_idx = _hoistable_in_region(instrs, lo, hi, def_counts)
        if not hoist_idx:
            continue

        hoist_set = set(hoist_idx)
        hoisted = [instrs[k] for k in hoist_idx]      # 保持原相对顺序（先定义后使用）
        out = []
        for i, instr in enumerate(instrs):
            if i == lo:
                out.extend(hoisted)                    # preheader：插在入口标签之前
            if i in hoist_set:
                continue                               # 从原位置移走
            out.append(instr)
        return out

    return instrs


def licm(instrs: list) -> list:
    """输入一段 IR，返回把循环不变量外提后的新 IR（纯函数，不原地修改输入）。

    用不动点：每提出一条，其上游可能变成新的不变量，且嵌套循环要一层层往外提，
    所以反复跑到 IR 不再变化。和 dce 一样，正确性一眼可查、不建 CFG。
    """
    current = list(instrs)
    while True:
        nxt = _licm_once(current)
        if nxt == current:
            return nxt
        current = nxt
