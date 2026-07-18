"""多智能体（C 组）。每个 Agent 只做一件事，通过共享 context 串联。

已实现：
  - BaseAgent      统一「输入→处理→产物」三段式基类
  - OptimizerAgent 调 LLM 产出未执行的优化候选（案例 B）
  - Executor       唯一碰工具链，build→run_tests→run_bench 回填 Candidate

待实现：Planner / Evaluator / orchestrator。
"""
from .base import BaseAgent
from .executor import Executor
from .optimizer_agent import OptimizerAgent

__all__ = ["BaseAgent", "OptimizerAgent", "Executor"]
