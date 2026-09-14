"""可复现的基准实验与阶段四矩阵实验契约。"""

from .configs import (
    CONFIG_NAMES,
    CONFIGS,
    FORMAL_SAMPLES,
    REFERENCE_CONFIG_NAME,
    SYSTEM_CONFIG_NAMES,
    ExperimentConfig,
    get_config,
    serialize_configs,
)
from .schema import (
    MATRIX_SCHEMA_VERSION,
    ExperimentRecord,
    MatrixReport,
    compute_comparison,
)

__all__ = [
    "CONFIG_NAMES",
    "CONFIGS",
    "FORMAL_SAMPLES",
    "REFERENCE_CONFIG_NAME",
    "SYSTEM_CONFIG_NAMES",
    "ExperimentConfig",
    "ExperimentRecord",
    "MATRIX_SCHEMA_VERSION",
    "MatrixReport",
    "compute_comparison",
    "get_config",
    "serialize_configs",
]
