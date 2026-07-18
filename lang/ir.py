"""
IR：AST → 简版三地址码（TAC, Three-Address Code）。

================= 为什么从栈式字节码换成三地址码 =================
第一版 IR 是栈式的（PUSH/LOAD/ADD…）。栈式 IR 的致命问题是：
**中间值没有名字**，它们只是"栈上某个位置"。于是每写一个优化 pass，
都要先在隐式的栈数据流里反推"这个 ADD 吃的是哪两个值、结果又被谁吃掉"：

    PUSH 2      # 这个 2 到底喂给了哪条指令？要模拟栈才知道
    PUSH 3
    MUL         # 结果又流向哪里？还要继续模拟

而本项目的核心价值就是"能不能在 IR 上做自动优化并证明收益"，
IR 必须**对优化 pass 友好**。三地址码给每个中间值一个显式名字（t0/t1/…），
数据流直接写在指令里，一眼可读：

    t0 = 2 * 3        ("mul", "t0", 2, 3)
    x  = 1 + t0       ("add", "t1", 1, "t0") ; ("copy", "x", "t1", None)

于是：
  - 常量折叠：src1/src2 都是字面量 → 直接算出来，换成 copy
  - 死代码消除：某个 dst 之后再没被任何 src 读过 → 整条删掉
  - LICM：循环体内某条指令的 src 都是循环不变量 → 整条外提
这三件事在三地址码上都是"看一条指令的 dst/src"就能判断的局部操作，
在栈式 IR 上则要做栈模拟。这就是换 IR 的全部理由。

================= 刻意不做什么（课设复杂度上限） =================
  - 不做 SSA / phi 节点
  - 不做完整 CFG / 支配树
  - 不做寄存器分配
  - 控制流只用"标签 + 跳转"的线性指令序列，不建基本块图
够优化 pass 用即可，再往上是工业编译器的活。

===================== 指令格式 =====================
统一是**定长 4 元组** (op, dst, src1, src2)，用不到的槽填 None。
定长的好处：每个 pass 都能无脑 `op, dst, s1, s2 = instr` 解包，
不用对每种指令写不同的拆包逻辑。

操作数（src 槽）有两种：
  - int  → 字面量常量（三地址码允许常量直接当操作数，常量折叠靠它）
  - str  → 变量名或临时变量名（t0/t1/…）

指令表：
  ("copy",  dst, src, None)          dst = src
  ("add"/"sub"/"mul"/"div", dst, s1, s2)      算术
  ("lt"/"gt"/"le"/"ge"/"eq"/"ne", dst, s1, s2) 比较，结果 1/0
  ("print", None, src, None)         输出 src
  ("newarray", dst, size, None)      dst = 长度为 size 的零数组
  ("load_idx",  dst, arr, idx)       dst = arr[idx]
  ("store_idx", arr, idx, val)       arr[idx] = val
  ("label", name, None, None)        跳转目标（伪指令，运行时零开销）
  ("jump",  label, None, None)       无条件跳转
  ("jump_if_false", label, cond, None)   cond 为假（==0）则跳到 label

注意跳转类指令把 **label 放在 dst 槽**：dst 槽的语义是"不是被读取的值"，
src 槽的语义是"被读取的值"。这样 uses()/defs() 两个辅助函数就能统一实现，
所有数据流类的 pass（DCE、常量传播、LICM）都直接复用它们。

基线版本故意不做任何优化：生成最朴素的三地址码（比如每个赋值都多一条
copy），这样阶段三的优化档才有明显收益空间。
"""
from .ast_nodes import (
    Num, Var, BinOp, ArrayNew, Index,
    Assign, IndexAssign, Print, If, While, Program,
)


# AST 里的运算符 → IR 操作码
BINOP_TO_IR = {
    "+": "add", "-": "sub", "*": "mul", "/": "div",
    "<": "lt", ">": "gt", "<=": "le", ">=": "ge",
    "==": "eq", "!=": "ne",
}

ARITH_OPS = {"add", "sub", "mul", "div"}
CMP_OPS = {"lt", "gt", "le", "ge", "eq", "ne"}


class IRBuilder:
    def __init__(self):
        self.code = []
        self._tmp_n = 0
        self._label_n = 0

    # ---- 名字生成器：临时变量 t0,t1,… / 标签 L0,L1,… ----
    def new_tmp(self):
        name = f"t{self._tmp_n}"
        self._tmp_n += 1
        return name

    def new_label(self, hint):
        name = f"L{self._label_n}_{hint}"
        self._label_n += 1
        return name

    def emit(self, op, dst=None, src1=None, src2=None):
        self.code.append((op, dst, src1, src2))

    def build(self, program: Program):
        self.code = []
        self._tmp_n = 0
        self._label_n = 0
        for stmt in program.statements:
            self._stmt(stmt)
        return self.code

    # ---- 语句 ----
    def _stmt(self, node):
        if isinstance(node, Assign):
            src = self._expr(node.value)
            # 故意不做"直接把结果算进 node.name"的优化：先算到临时变量、
            # 再 copy 过去。基线越朴素，后面 copy propagation 的收益越好看。
            self.emit("copy", node.name, src)

        elif isinstance(node, IndexAssign):
            idx = self._expr(node.index)
            val = self._expr(node.value)
            self.emit("store_idx", node.array, idx, val)

        elif isinstance(node, Print):
            self.emit("print", None, self._expr(node.value))

        elif isinstance(node, If):
            # if (c) { A } else { B }
            #        jump_if_false -> L_else
            #        A
            #        jump -> L_end
            #   L_else:
            #        B
            #   L_end:
            cond = self._expr(node.cond)
            if node.else_body:
                l_else = self.new_label("else")
                l_end = self.new_label("endif")
                self.emit("jump_if_false", l_else, cond)
                for s in node.then_body:
                    self._stmt(s)
                self.emit("jump", l_end)
                self.emit("label", l_else)
                for s in node.else_body:
                    self._stmt(s)
                self.emit("label", l_end)
            else:
                l_end = self.new_label("endif")
                self.emit("jump_if_false", l_end, cond)
                for s in node.then_body:
                    self._stmt(s)
                self.emit("label", l_end)

        elif isinstance(node, While):
            #   L_top:
            #        <算 cond>
            #        jump_if_false -> L_end
            #        body
            #        jump -> L_top
            #   L_end:
            # 条件在循环内重算，所以"算 cond 的那几条指令"每轮都执行 ——
            # 这正是 LICM 之类的 pass 将来要动手的地方。
            l_top = self.new_label("while")
            l_end = self.new_label("endwhile")
            self.emit("label", l_top)
            cond = self._expr(node.cond)
            self.emit("jump_if_false", l_end, cond)
            for s in node.body:
                self._stmt(s)
            self.emit("jump", l_top)
            self.emit("label", l_end)

        else:
            raise TypeError(f"未知语句节点: {node}")

    # ---- 表达式：返回一个"操作数"（int 字面量 / 变量名 / 临时变量名）----
    def _expr(self, node):
        if isinstance(node, Num):
            return node.value                 # 常量直接当操作数，不占一条指令

        if isinstance(node, Var):
            return node.name                  # 变量名本身就是操作数

        if isinstance(node, BinOp):
            left = self._expr(node.left)
            right = self._expr(node.right)
            dst = self.new_tmp()
            self.emit(BINOP_TO_IR[node.op], dst, left, right)
            return dst

        if isinstance(node, ArrayNew):
            size = self._expr(node.size)
            dst = self.new_tmp()
            self.emit("newarray", dst, size)
            return dst

        if isinstance(node, Index):
            idx = self._expr(node.index)
            dst = self.new_tmp()
            self.emit("load_idx", dst, node.array, idx)
            return dst

        raise TypeError(f"未知表达式节点: {node}")


def build_ir(program: Program):
    return IRBuilder().build(program)


# ==================================================================
# 给优化 pass 用的辅助函数：一条指令"读了谁"、"写了谁"。
# 所有数据流分析（DCE / 常量传播 / LICM）都建立在这两个函数上，
# 所以把它们和 IR 定义放在一起 —— 换指令时只改这一处。
# ==================================================================

def uses(instr):
    """这条指令读取（use）的变量名集合。字面量常量不算。"""
    op, dst, s1, s2 = instr
    names = []
    if op in ("copy", "print", "newarray"):
        names = [s1]
    elif op in ARITH_OPS or op in CMP_OPS:
        names = [s1, s2]
    elif op == "load_idx":
        names = [s1, s2]              # arr, idx
    elif op == "store_idx":
        names = [dst, s1, s2]         # arr 也是被读的（原地改写）
    elif op == "jump_if_false":
        names = [s1]                  # cond
    # label / jump 不读任何变量
    return {n for n in names if isinstance(n, str)}


def defs(instr):
    """这条指令写入（def）的变量名集合。"""
    op, dst, _s1, _s2 = instr
    if op in ("copy", "newarray", "load_idx") or op in ARITH_OPS or op in CMP_OPS:
        return {dst}
    if op == "store_idx":
        return {dst}                  # 原地改写数组
    return set()                      # print / label / jump / jump_if_false


# ==================================================================
# 可读打印：每条指令一行，形如 `t0 = a * b`
# 验收要看"三地址码打印得可读"，所以这个函数属于 IR 的一部分。
# ==================================================================

_SYMBOL = {
    "add": "+", "sub": "-", "mul": "*", "div": "/",
    "lt": "<", "gt": ">", "le": "<=", "ge": ">=", "eq": "==", "ne": "!=",
}


def format_instr(instr):
    op, dst, s1, s2 = instr
    if op == "copy":
        return f"{dst} = {s1}"
    if op in _SYMBOL:
        return f"{dst} = {s1} {_SYMBOL[op]} {s2}"
    if op == "print":
        return f"print {s1}"
    if op == "newarray":
        return f"{dst} = array({s1})"
    if op == "load_idx":
        return f"{dst} = {s1}[{s2}]"
    if op == "store_idx":
        return f"{dst}[{s1}] = {s2}"
    if op == "label":
        return f"{dst}:"
    if op == "jump":
        return f"goto {dst}"
    if op == "jump_if_false":
        return f"if not {s1} goto {dst}"
    raise ValueError(f"未知指令: {op}")


def format_ir(code):
    """整段 IR 转成多行字符串（标签顶格，其余缩进）。"""
    lines = []
    for i, instr in enumerate(code):
        text = format_instr(instr)
        indent = "" if instr[0] == "label" else "    "
        lines.append(f"  {i:3}  {indent}{text}")
    return "\n".join(lines)
