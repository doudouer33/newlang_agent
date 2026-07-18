"""多智能体（C 组）。每个 Agent 只做一件事，通过共享 context 串联。

已实现：
  - BaseAgent      统一「输入→处理→产物」三段式基类
  - OptimizerAgent 调 LLM 产出未执行的优化候选（案例 B）
  - Executor       唯一碰工具链，build→run_tests→run_bench 回填 Candidate
  - Evaluator      过正确性→按 instr_count 排序→选最优→回传反馈
  - Planner        最小固定流程：定可用 pass 集合与候选数
  - orchestrate    多轮编排闭环（系统的心脏）

阶段二至此收口。
"""
from .base import BaseAgent
from .evaluator import Evaluator, better
from .executor import Executor
from .optimizer_agent import OptimizerAgent
from .orchestrator import orchestrate
from .planner import Planner

__all__ = [
    "BaseAgent", "OptimizerAgent", "Executor", "Evaluator", "better",
    "Planner", "orchestrate",
]
