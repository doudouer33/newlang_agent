"""
数据契约：贯穿全程的 Candidate。

README「关键模块设计 · 数据契约」的落地：**Agent 之间不传自然语言，只传
结构化对象**。一个 Candidate 就是「某个样例程序 + 某套优化 pass 组合」这一个
候选方案，从生成 → 编译 → 测试 → 评估，一路被逐字段填充。

为什么放在项目顶层而不是某个子包里：Candidate 不属于 llm / agents / tools /
benchmark 里的任何一个 —— 它是它们之间**共享**的契约（OptimizerAgent 产出它、
Executor 用工具链回填它、Evaluator 排序它、benchmark 汇总它）。放顶层，谁都能
`from contracts import Candidate`，且不会造成子包互相 import 的环。

日志即「一堆 Candidate 的 JSON」：to_dict / from_dict 让每个候选都能原样落盘到
runs/ 再读回来，调试和复现都只跟这一个结构打交道。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


# origin 的合法取值：候选是谁产生的。对比实验按它分档（baseline vs 优化档）。
ORIGINS = ("baseline", "llm", "agent")


@dataclass
class Candidate:
    """一个待评估的优化候选。

    前四个字段在**生成时**就确定（要跑哪个程序、用哪套 pass、谁生成的）；
    其余字段在**执行后**由 Executor 依次回填，未跑时保持默认值（None / False）。
    """

    id: str                       # 候选唯一标识，方便日志里定位（如 "loop_sum#cf+dce"）
    source_program: str           # 哪个样例程序（源码文本，或样例名，由上层约定）
    passes: list[str]             # 应用的优化 pass 列表，如 ["const_fold", "dce"]；[] 即 baseline
    origin: str                   # "baseline" / "llm" / "agent"

    # ---- 执行后回填 ----
    compiled: bool = False        # build 是否成功（语法/pass 都没炸）
    correct: bool = False         # 功能测试是否通过（铁律：先过这个再比性能）
    exec_time_ms: float | None = None   # 运行耗时（会抖，仅参考）
    instr_count: int | None = None      # 执行指令数（确定性，收益主对比信号）
    error: str | None = None      # 任一环节的失败原因，一句人能看懂的话

    def __post_init__(self):
        if self.origin not in ORIGINS:
            raise ValueError(f"origin 必须是 {ORIGINS} 之一，收到 {self.origin!r}")

    # ---- 落盘 / 读回：日志就是一堆 Candidate 的 JSON ----
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Candidate":
        """从 dict 还原；忽略多余字段，缺失字段用默认值补齐，方便读旧日志。"""
        fields = cls.__dataclass_fields__
        known = {k: v for k, v in data.items() if k in fields}
        return cls(**known)

    def is_viable(self) -> bool:
        """能进入性能对比的前提：编译成功且功能正确。Evaluator 用它做第一道过滤。"""
        return self.compiled and self.correct
