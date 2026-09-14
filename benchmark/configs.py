"""阶段四的四档实验配置和 Oracle 参考档。

这里把实验协议作为单一事实源，matrix runner、报告和测试都从这里读取，
不在各处重复编写配置分支。

四个系统档位：
  - baseline：无优化、无 LLM。
  - llm_only：一次 LLM、一个候选、无反馈。
  - agent_min：一次 LLM、最多三个候选、单轮评测。
  - agent_full：最多三轮，每轮最多三个候选，携带上轮反馈。

oracle 不是第五个系统档位。它穷举当前三个 Pass 的 baseline 加 15 个非空排列，
只用作理论最优参考线。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from types import MappingProxyType


# 正式四档矩阵固定为 5 个程序，basic 只保留为快速冒烟样例。
FORMAL_SAMPLES = (
    "branch",
    "loop_sum",
    "array_dot",
    "licm_demo",
    "dead_code",
)

SYSTEM_CONFIG_NAMES = ("baseline", "llm_only", "agent_min", "agent_full")
REFERENCE_CONFIG_NAME = "oracle"


@dataclass(frozen=True)
class ExperimentConfig:
    """一个不可变的实验档位。

    n_candidates 对 LLM 档表示每轮最多生成数；对 oracle 表示当前冻结协议下
    需要测量的全部配置数（包含 baseline）。
    """

    name: str
    use_llm: bool
    n_candidates: int
    max_rounds: int
    use_feedback: bool
    exhaustive: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("config name 不能为空")
        if self.n_candidates < 0:
            raise ValueError("n_candidates 不能为负数")
        if self.max_rounds < 0:
            raise ValueError("max_rounds 不能为负数")
        if self.use_feedback and (not self.use_llm or self.max_rounds < 2):
            raise ValueError("反馈配置必须使用 LLM 且至少允许两轮")
        if self.exhaustive and self.use_llm:
            raise ValueError("oracle 穷举档不得调用 LLM")
        if self.use_llm and (self.n_candidates < 1 or self.max_rounds < 1):
            raise ValueError("LLM 档至少需要一个候选和一轮")

    def to_dict(self) -> dict:
        return asdict(self)


CONFIGS = MappingProxyType({
    "baseline": ExperimentConfig(
        name="baseline",
        use_llm=False,
        n_candidates=0,
        max_rounds=0,
        use_feedback=False,
        description="不应用任何 Pass，不调用 LLM，作为所有对比的锚点。",
    ),
    "llm_only": ExperimentConfig(
        name="llm_only",
        use_llm=True,
        n_candidates=1,
        max_rounds=1,
        use_feedback=False,
        description="只调用一次 LLM 并执行一个候选，不迭代。",
    ),
    "agent_min": ExperimentConfig(
        name="agent_min",
        use_llm=True,
        n_candidates=3,
        max_rounds=1,
        use_feedback=False,
        description="单轮生成最多三个候选，由 Executor 和 Evaluator 实测选优。",
    ),
    "agent_full": ExperimentConfig(
        name="agent_full",
        use_llm=True,
        n_candidates=3,
        max_rounds=3,
        use_feedback=True,
        description="最多运行三轮，将 Evaluator 反馈回传给下一轮 LLM。",
    ),
    "oracle": ExperimentConfig(
        name="oracle",
        use_llm=False,
        n_candidates=16,
        max_rounds=1,
        use_feedback=False,
        exhaustive=True,
        description="穷举当前三个 Pass 的 16 种配置，作为理论最优参考线。",
    ),
})

CONFIG_NAMES = SYSTEM_CONFIG_NAMES + (REFERENCE_CONFIG_NAME,)


def get_config(name: str) -> ExperimentConfig:
    """按名称返回冻结配置；未知名称显式报错。"""
    try:
        return CONFIGS[name]
    except KeyError:
        choices = ", ".join(CONFIG_NAMES)
        raise ValueError(f"未知实验配置 {name!r}；可用配置：{choices}") from None


def serialize_configs(names=CONFIG_NAMES) -> list[dict]:
    """按稳定顺序返回可直接写入实验 JSON 的配置列表。"""
    return [get_config(name).to_dict() for name in names]
