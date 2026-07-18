"""优化 pass 集合。

每个 pass 都是 `f(instrs: list) -> list` 的纯函数：吃一段三地址码，
吐一段新的三地址码，不原地修改输入（同一段基线 IR 要反复跑不同的 pass
组合做对比，原地改会污染基线）。registry 按名字把它们串起来。
"""
from .const_fold import const_fold
from .dce import dce
from .licm import licm
from .registry import PASSES, UnknownPassError, apply_passes, available_passes

__all__ = [
    "const_fold",
    "dce",
    "licm",
    "apply_passes",
    "available_passes",
    "PASSES",
    "UnknownPassError",
]
