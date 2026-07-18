"""
Planner：决定「这一轮做什么」。

README 角色表：输入需求/约束，输出步骤计划。并特别注明——**最小版可为固定流程，
不一定真调 LLM**。这里就是那个最小版：不调模型，只把 OptimizerAgent 这一轮需要的
配置（可用哪些 pass、要几个候选）整理好，放进 plan 交给编排循环。

它存在的意义是把「跑什么」这个决策**单独成块**：以后要加「先跑哪个样例、每个跑
几轮、按反馈收窄 pass 空间」这类策略，都往这里加，OptimizerAgent 不用动。
"""
from __future__ import annotations

from optimizer.registry import available_passes

from .base import BaseAgent


class Planner(BaseAgent):
    def __init__(self, llm=None, tools=None, n_candidates: int = 3):
        super().__init__(llm, tools)
        self.n_candidates = n_candidates

    def run(self, context: dict) -> dict:
        # 固定流程：锁定可用 pass 集合（LLM 只能在这里面选），定好候选个数。
        return {
            "available_passes": list(available_passes()),
            "n": context.get("n", self.n_candidates),
        }
