"""
Transformer：Lark 解析树 → 自定义 AST。

机制没变：**grammar.lark 里每个 `-> 别名`（以及每个规则名）对应这里
一个同名方法**，本次扩展只是"按新增语法补方法"，一条一条机械对应。

Lark 自底向上调用这些方法：叶子节点先被处理，返回值自动
作为上层方法的 items 传入。所以每个方法拿到的 items，
里面已经是"下层处理完的结果"（即你自己的 AST 节点），
而不是原始 Lark 节点。
"""
from lark import Transformer
from .ast_nodes import (
    Num, Var, BinOp, ArrayNew, Index,
    Assign, IndexAssign, Print, If, While, Program,
)


class ASTBuilder(Transformer):
    # ---- start：整个程序 ----
    def start(self, items):
        return Program(statements=list(items))

    # ---- 语句 ----
    def assign(self, items):
        # items = [Token(NAME), 表达式节点]
        # `let x = e;` 和 `x = e;` 共用这个别名：本语言没有作用域概念，
        # 声明和再赋值在 IR 上是同一件事（写一个变量名），不必区分。
        return Assign(name=str(items[0]), value=items[1])

    def assign_idx(self, items):
        # items = [Token(NAME), 下标表达式, 值表达式]  ← a[i] = v;
        return IndexAssign(array=str(items[0]), index=items[1], value=items[2])

    def print_stmt(self, items):
        return Print(value=items[0])

    def block(self, items):
        # block 直接返回"语句列表"，让 If/While 拿到的就是 list
        return list(items)

    def if_stmt(self, items):
        # items = [cond, then_block]  或  [cond, then_block, else_block]
        cond, then_body = items[0], items[1]
        else_body = items[2] if len(items) > 2 else []
        return If(cond=cond, then_body=then_body, else_body=else_body)

    def while_stmt(self, items):
        # items = [cond, body_block]
        return While(cond=items[0], body=items[1])

    # ---- 表达式：算术 ----
    def add(self, items):
        return BinOp("+", items[0], items[1])

    def sub(self, items):
        return BinOp("-", items[0], items[1])

    def mul(self, items):
        return BinOp("*", items[0], items[1])

    def div(self, items):
        return BinOp("/", items[0], items[1])

    # ---- 表达式：比较（和算术共用 BinOp 节点）----
    def lt(self, items):
        return BinOp("<", items[0], items[1])

    def gt(self, items):
        return BinOp(">", items[0], items[1])

    def le(self, items):
        return BinOp("<=", items[0], items[1])

    def ge(self, items):
        return BinOp(">=", items[0], items[1])

    def eq(self, items):
        return BinOp("==", items[0], items[1])

    def ne(self, items):
        return BinOp("!=", items[0], items[1])

    # ---- 原子 ----
    def number(self, items):
        # items = [Token(NUMBER)]，Token 是字符串，转成 int
        return Num(int(items[0]))

    def var(self, items):
        return Var(str(items[0]))

    def array_new(self, items):
        # items = [长度表达式]  ← array(n)
        return ArrayNew(size=items[0])

    def index(self, items):
        # items = [Token(NAME), 下标表达式]  ← a[i]
        return Index(array=str(items[0]), index=items[1])
