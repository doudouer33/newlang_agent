"""
Agent 基类：统一「输入 → 处理 → 产物」三段式。

README「关键模块设计 · Agent 基类」。每个 Agent 只做一件事，通过一个共享的
`context` 字典在编排循环里逐步传递、逐步填充：Planner 决定跑什么，OptimizerAgent
往里塞候选，Executor 回填执行结果，Evaluator 给出排名。

约定：
  - `llm`   —— 需要调模型的 Agent 才用（OptimizerAgent）；Planner/Executor/Evaluator 可为 None。
  - `tools` —— 唯一「动手」的通道；只有 Executor 真正依赖它。
  - `run(context)` 返回一个 dict，编排循环把它并进共享 context。
"""
from __future__ import annotations


class BaseAgent:
    def __init__(self, llm=None, tools=None):
        self.llm = llm
        self.tools = tools

    def run(self, context: dict) -> dict:
        raise NotImplementedError
