"""
Pass 注册表 + 顺序调度器。

注意它**不是**一个 pass：它不碰 IR，只做两件事
  1. 名字 → pass 函数 的查找表；
  2. 按给定顺序把一段 IR 串着喂过去（前一个的输出 = 后一个的输入）。

为什么要有它：优化的**顺序**本身是个变量（先折叠再 DCE，和只跑 DCE，
收益完全不同），benchmark 要能按名字组合出不同的 pass 流水线来对比。
把"跑哪些 pass、按什么顺序"变成一个字符串列表，才能让上层（阶段二的 Agent）
去搜索这个组合空间，而不用改代码。

所有 pass 的签名统一为 `f(instrs: list) -> list`（纯函数，不改输入），
所以调度就是一行 `ir = f(ir)` 的折叠，不需要任何特判。

新增 pass（peephole / licm / …）：在 PASSES 里加一行即可，调度逻辑不用动。
"""
from .const_fold import const_fold
from .dce import dce
from .licm import licm


class UnknownPassError(ValueError):
    """pass_names 里出现了没注册的名字。"""


# 名字 → pass 函数。新增 pass 就在这里加一行。
PASSES = {
    "const_fold": const_fold,
    "dce": dce,
    "licm": licm,
    # "peephole": peephole,      # 待实现
}


def available_passes() -> list:
    """已注册的 pass 名字（排序后，方便打印和报错）。"""
    return sorted(PASSES)


def get_pass(name: str):
    """按名字取 pass 函数；没注册就报清楚是哪个名字错了。"""
    try:
        return PASSES[name]
    except KeyError:
        raise UnknownPassError(
            f"未注册的优化 pass: {name!r}；已注册的有: {available_passes()}"
        ) from None


def apply_passes(pass_names: list, instrs: list) -> list:
    """按 pass_names 的顺序依次跑各个 pass，返回最终 IR。

    先把所有名字校验一遍再开跑：宁可一条 pass 都不跑就报错，也不要跑了一半
    才发现第三个名字拼错了 —— 那样调用方拿到的是一段"优化了一半"的 IR。
    """
    for name in pass_names:
        get_pass(name)

    result = list(instrs)                 # 不原地修改调用方的 IR
    for name in pass_names:
        result = get_pass(name)(result)
    return result
