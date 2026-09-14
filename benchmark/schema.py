"""阶段四四档矩阵实验的统一数据契约。

阶段三 benchmark.runner 使用 schema version 1，表示 baseline 与穷举最优对比。
本文件使用 version 2，表示“四档系统 + Oracle × 多 trial”矩阵。两者含义不同，
所以读取时明确拒绝版本不匹配，不猜测、不静默转换。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any

from .configs import CONFIG_NAMES


MATRIX_SCHEMA_VERSION = 2


def _known_fields(cls, data: dict) -> dict:
    """读取同版本记录时忽略多余字段，便于向后增加可选项。"""
    names = {item.name for item in fields(cls)}
    return {key: value for key, value in data.items() if key in names}


def compute_comparison(
    *,
    correct: bool,
    instr_count: int | None,
    baseline_instr_count: int | None,
    oracle_instr_count: int | None,
) -> dict:
    """计算单条记录相对 baseline 和 Oracle 的可比指标。

    正确性不通过、缺失指令数或分母为零时，对应比较值为 None，避免用 0
    伪装成“无收益”或“零差距”。
    """
    result = {
        "saved_instructions": None,
        "reduction_percent": None,
        "oracle_hit": None,
        "oracle_gap_percent": None,
    }
    if not correct or instr_count is None:
        return result

    if baseline_instr_count is not None and baseline_instr_count > 0:
        saved = baseline_instr_count - instr_count
        result["saved_instructions"] = saved
        result["reduction_percent"] = round(saved / baseline_instr_count * 100, 2)

    if oracle_instr_count is not None and oracle_instr_count > 0:
        result["oracle_hit"] = instr_count == oracle_instr_count
        result["oracle_gap_percent"] = round(
            (instr_count - oracle_instr_count) / oracle_instr_count * 100, 2
        )

    return result


@dataclass
class ExperimentRecord:
    """一次“程序 × 配置 × trial”的原始记录。"""

    run_id: str
    program: str
    config: str
    trial: int

    passes: list[str] = field(default_factory=list)
    compiled: bool = False
    correct: bool = False
    output: list[int] | None = None
    instr_count: int | None = None
    time_ms: float | None = None
    peak_memory_kb: float | None = None

    rounds: int = 0
    candidate_count: int = 0
    llm_calls: int = 0
    prompt_tokens: int | None = 0
    completion_tokens: int | None = 0
    total_tokens: int | None = 0
    llm_latency_ms: float | None = 0.0
    errors: list[str] = field(default_factory=list)

    baseline_instr_count: int | None = None
    oracle_instr_count: int | None = None
    saved_instructions: int | None = None
    reduction_percent: float | None = None
    oracle_hit: bool | None = None
    oracle_gap_percent: float | None = None

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id 不能为空")
        if not self.program:
            raise ValueError("program 不能为空")
        if self.config not in CONFIG_NAMES:
            raise ValueError(f"未知实验配置：{self.config!r}")
        if self.trial < 1:
            raise ValueError("trial 从 1 开始")
        if self.correct and not self.compiled:
            raise ValueError("correct=True 时 compiled 必须为 True")
        if any(not isinstance(name, str) for name in self.passes):
            raise ValueError("passes 必须是字符串列表")
        if any(not isinstance(error, str) for error in self.errors):
            raise ValueError("errors 必须是字符串列表")

        nonnegative = {
            "instr_count": self.instr_count,
            "time_ms": self.time_ms,
            "peak_memory_kb": self.peak_memory_kb,
            "rounds": self.rounds,
            "candidate_count": self.candidate_count,
            "llm_calls": self.llm_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "llm_latency_ms": self.llm_latency_ms,
            "baseline_instr_count": self.baseline_instr_count,
            "oracle_instr_count": self.oracle_instr_count,
        }
        for name, value in nonnegative.items():
            if value is not None and value < 0:
                raise ValueError(f"{name} 不能为负数")

        comparison_values = (
            self.saved_instructions,
            self.reduction_percent,
            self.oracle_hit,
            self.oracle_gap_percent,
        )
        if not self.correct and any(value is not None for value in comparison_values):
            raise ValueError("正确性不通过时不得填写收益或 Oracle 比较")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ExperimentRecord":
        if not isinstance(data, dict):
            raise ValueError("实验记录必须是 JSON 对象")
        return cls(**_known_fields(cls, data))

    def set_comparison(
        self,
        *,
        baseline_instr_count: int | None,
        oracle_instr_count: int | None,
    ) -> None:
        """回填比较锚点和衍生指标。"""
        self.baseline_instr_count = baseline_instr_count
        self.oracle_instr_count = oracle_instr_count
        comparison = compute_comparison(
            correct=self.correct,
            instr_count=self.instr_count,
            baseline_instr_count=baseline_instr_count,
            oracle_instr_count=oracle_instr_count,
        )
        for name, value in comparison.items():
            setattr(self, name, value)
        self.__post_init__()


@dataclass
class MatrixReport:
    """一场完整四档矩阵实验的顶层对象。"""

    generated_at: str
    experiment: dict[str, Any]
    environment: dict[str, Any]
    configs: list[dict]
    samples: list[str]
    trials: int
    records: list[ExperimentRecord] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    schema_version: int = MATRIX_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MATRIX_SCHEMA_VERSION:
            raise ValueError(
                f"不支持 schema_version={self.schema_version}；"
                f"矩阵实验要求 {MATRIX_SCHEMA_VERSION}"
            )
        if not self.generated_at:
            raise ValueError("generated_at 不能为空")
        if self.trials < 1:
            raise ValueError("trials 必须大于等于 1")
        if not self.samples:
            raise ValueError("samples 不能为空")
        if len(self.samples) != len(set(self.samples)):
            raise ValueError("samples 不能重复")
        if not self.configs:
            raise ValueError("configs 不能为空")

        config_names = []
        for config in self.configs:
            if not isinstance(config, dict) or config.get("name") not in CONFIG_NAMES:
                raise ValueError("configs 包含未知或无效配置")
            config_names.append(config["name"])
        if len(config_names) != len(set(config_names)):
            raise ValueError("configs 不能重复")

        for record in self.records:
            if not isinstance(record, ExperimentRecord):
                raise ValueError("records 必须包含 ExperimentRecord")
            if record.program not in self.samples:
                raise ValueError(f"记录程序不在 samples 中：{record.program!r}")
            if record.config not in config_names:
                raise ValueError(f"记录配置不在 configs 中：{record.config!r}")
            if record.trial > self.trials:
                raise ValueError(
                    f"记录 trial={record.trial} 超过实验 trials={self.trials}"
                )

    def to_dict(self) -> dict:
        # schema_version 放在最前，人直接打开 JSON 时可立即看到。
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "experiment": self.experiment,
            "environment": self.environment,
            "configs": self.configs,
            "samples": self.samples,
            "trials": self.trials,
            "records": [record.to_dict() for record in self.records],
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MatrixReport":
        if not isinstance(data, dict):
            raise ValueError("矩阵报告必须是 JSON 对象")
        version = data.get("schema_version")
        if version != MATRIX_SCHEMA_VERSION:
            raise ValueError(
                f"不支持 schema_version={version!r}；"
                f"矩阵实验要求 {MATRIX_SCHEMA_VERSION}"
            )

        known = _known_fields(cls, data)
        raw_records = known.get("records", [])
        if not isinstance(raw_records, list):
            raise ValueError("records 必须是列表")
        known["records"] = [
            item if isinstance(item, ExperimentRecord) else ExperimentRecord.from_dict(item)
            for item in raw_records
        ]
        return cls(**known)
