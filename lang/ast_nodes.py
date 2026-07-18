"""
AST 节点定义。

全是 dataclass，很短。这些是"干净的、你自己的"节点，
transformer.py 负责把 Lark 的解析树翻译成这些节点，
ir.py 再遍历这些节点生成三地址码 IR。

本阶段新增的能力（if/else、while、比较、数组）在这里各对应
一个节点；表达式类节点全部"有值"，语句类节点全部"无值"。
"""
from dataclasses import dataclass, field


# ---- 表达式节点（求值后产生一个值）----

@dataclass
class Num:
    value: int


@dataclass
class Var:
    name: str


@dataclass
class BinOp:
    # 算术："+" "-" "*" "/"
    # 比较："<" ">" "<=" ">=" "==" "!="
    # 算术和比较共用一个节点：它们在 IR 里同样是 (op, dst, src1, src2)，
    # 没必要分成两种节点。
    op: str
    left: object
    right: object


@dataclass
class ArrayNew:
    """array(n) —— 新建长度为 n 的零数组。"""
    size: object     # 表达式节点


@dataclass
class Index:
    """a[i] —— 按下标读。"""
    array: str
    index: object    # 表达式节点


# ---- 语句节点（执行后无值）----

@dataclass
class Assign:
    name: str
    value: object    # 表达式节点


@dataclass
class IndexAssign:
    """a[i] = v —— 按下标写。"""
    array: str
    index: object    # 表达式节点
    value: object    # 表达式节点


@dataclass
class Print:
    value: object    # 表达式节点


@dataclass
class If:
    cond: object          # 表达式节点
    then_body: list       # 语句列表
    else_body: list = field(default_factory=list)   # 没有 else 时为空


@dataclass
class While:
    cond: object          # 表达式节点
    body: list            # 语句列表


@dataclass
class Program:
    statements: list
