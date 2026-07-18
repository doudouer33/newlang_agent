"""
编排循环：系统的心脏。

README「关键模块设计 · 编排循环」。把四个 Agent 串成一个多轮闭环，每轮：

    Planner    → 决定这轮的配置（可用 pass、候选数）
    Optimizer  → LLM 生成一批未执行的候选
    Executor   → 每个候选真编译、真测、真计时，回填 Candidate
    Evaluator  → 过正确性 → 按指令数排序 → 选最优 → 给反馈

轮与轮之间靠共享 context 传递：Evaluator 的 feedback 喂回下一轮 OptimizerAgent，
形成「生成→执行→评估→再生成」的优化闭环。

三个编排上的决定（都体现 README 的设计意图）：
  - **每轮注入一个 baseline 候选（passes=[]）当锚点**：让排名和反馈始终有「不优化
    会怎样」作参照，最优也永远有个保底（baseline 一定正确，只是慢）。
  - **收敛即停**：某一轮的最优没能刷新历史最优（Evaluator 的 converged），就停 ——
    再问 LLM 也问不出更好的了。
  - **落盘到 runs/**：整轮历史（每轮最优、排名、淘汰原因、反馈）写成一个 JSON，
    经 save_result 工具存下来，事后可复现。
"""
from __future__ import annotations

from contracts import Candidate
from llm import default_client
from tools.registry import call_tool

from .evaluator import Evaluator, better
from .executor import Executor
from .optimizer_agent import OptimizerAgent
from .planner import Planner


def _baseline(program: str, source: str) -> Candidate:
    """一个未执行的 baseline 候选：不加任何 pass。每轮新建一个。"""
    return Candidate(id=f"{program}#baseline", source_program=source,
                     passes=[], origin="baseline")


def orchestrate(
    program: str,
    source: str,
    *,
    llm=None,
    max_rounds: int = 3,
    n_candidates: int = 3,
    expected=None,
    repeat: int = 3,
    save: bool = True,
    tools=call_tool,
):
    """对一个程序跑完整优化闭环，返回 (最优候选, 历史)。

    llm 默认真调 DeepSeek；测试可传 StubLLMClient 走离线。expected 不给就由
    Executor 从源码 `// expect:` 注释读。
    """
    llm = llm or default_client()
    planner = Planner(n_candidates=n_candidates)
    optimizer = OptimizerAgent(llm=llm, n_candidates=n_candidates)
    executor = Executor(tools=tools)
    evaluator = Evaluator()

    context = {
        "program": program, "source": source, "expected": expected,
        "history": [], "best": None, "feedback": None,
    }

    for r in range(max_rounds):
        plan = planner.run(context)
        opt_out = optimizer.run({**context, **plan})

        # baseline 锚点 + LLM 候选，一起交给 Executor 真跑。
        batch = [_baseline(program, source)] + opt_out["candidates"]
        exe_out = executor.run(
            {"candidates": batch, "expected": expected, "repeat": repeat})
        verdict = evaluator.run(
            {"results": exe_out["results"], "best": context["best"]})

        context["history"].append({
            "round": r,
            "best": verdict["best"].to_dict() if verdict["best"] else None,
            "ranking": [c.to_dict() for c in verdict["ranking"]],
            "rejected": [c.to_dict() for c in verdict["rejected"]],
            "feedback": verdict["feedback"],
            "opt_error": opt_out.get("error"),
        })

        if better(verdict["best"], context["best"]):
            context["best"] = verdict["best"]
        context["feedback"] = verdict["feedback"]     # 喂回下一轮 OptimizerAgent

        if verdict["converged"]:                       # 这轮没更优 → 停
            break

    if save:
        _persist(program, context, tools)

    return context["best"], context["history"]


def _persist(program, context, tools):
    """整轮实验写成一个 JSON 落到 runs/，用于复现。"""
    best = context["best"]
    data = {
        "program": program,
        "best": best.to_dict() if best else None,
        "rounds": context["history"],
    }
    return tools("save_result", {"data": data, "name": program})
