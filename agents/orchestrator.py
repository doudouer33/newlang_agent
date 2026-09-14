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


def _baseline(candidate_id: str, source: str) -> Candidate:
    """一个未执行的 baseline 候选：不加任何 pass。每轮新建一个。"""
    return Candidate(id=candidate_id, source_program=source,
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
    candidate_id_prefix: str | None = None,
    tools=call_tool,
):
    """对一个程序跑完整优化闭环，返回 (最优候选, 历史)。

    llm 默认真调 DeepSeek；测试可传 StubLLMClient 走离线。expected 不给就由
    Executor 从源码 `// expect:` 注释读。
    """
    result = orchestrate_detailed(
        program,
        source,
        llm=llm,
        max_rounds=max_rounds,
        n_candidates=n_candidates,
        expected=expected,
        repeat=repeat,
        save=save,
        candidate_id_prefix=candidate_id_prefix,
        tools=tools,
    )
    return result["best"], result["history"]


def orchestrate_detailed(
    program: str,
    source: str,
    *,
    llm=None,
    max_rounds: int = 3,
    n_candidates: int = 3,
    expected=None,
    repeat: int = 3,
    save: bool = True,
    candidate_id_prefix: str | None = None,
    tools=call_tool,
):
    """运行优化闭环并返回阶段四实验需要的完整过程元数据。

    旧的 orchestrate() 是兼容包装器，仍只返回 (best, history)。这个详细入口
    额外返回停止原因、实际轮数、候选数、LLM usage 和 baseline 保底标记。
    """
    if max_rounds < 1:
        raise ValueError("max_rounds 必须大于等于 1")
    if n_candidates < 1:
        raise ValueError("n_candidates 必须大于等于 1")

    llm = llm or default_client()
    _drain_usage(llm)  # 清掉调用方可能留下的旧事件，保证本次实验隔离。
    planner = Planner(n_candidates=n_candidates)
    optimizer = OptimizerAgent(llm=llm, n_candidates=n_candidates)
    executor = Executor(tools=tools)
    evaluator = Evaluator()

    context = {
        "program": program, "source": source, "expected": expected,
        "history": [], "best": None, "feedback": None,
    }
    usage_events = []
    stop_reason = "max_rounds"
    last_optimizer_failed = False
    id_prefix = candidate_id_prefix or program

    for r in range(max_rounds):
        plan = planner.run(context)
        round_id_prefix = f"{id_prefix}:r{r + 1}"
        opt_out = optimizer.run({
            **context,
            **plan,
            "candidate_id_prefix": round_id_prefix,
        })
        round_usage = _drain_usage(llm)
        usage_events.extend(round_usage)
        last_optimizer_failed = bool(opt_out.get("error")) and not opt_out["candidates"]

        # baseline 锚点 + LLM 候选，一起交给 Executor 真跑。
        batch = [
            _baseline(f"{round_id_prefix}:baseline", source)
        ] + opt_out["candidates"]
        exe_out = executor.run(
            {"candidates": batch, "expected": expected, "repeat": repeat})
        verdict = evaluator.run(
            {"results": exe_out["results"], "best": context["best"]})

        context["history"].append({
            "round": r,
            "best": verdict["best"].to_dict() if verdict["best"] else None,
            "ranking": [c.to_dict() for c in verdict["ranking"]],
            "rejected": [c.to_dict() for c in verdict["rejected"]],
            "viable_count": len(verdict["ranking"]),
            "rejected_count": len(verdict["rejected"]),
            "improved": verdict["improved"],
            "converged": verdict["converged"],
            "feedback": verdict["feedback"],
            "opt_error": opt_out.get("error"),
            "raw_candidate_count": opt_out.get("raw_candidate_count", 0),
            "accepted_candidate_count": opt_out.get(
                "accepted_candidate_count", len(opt_out["candidates"])
            ),
            "rejected_items": opt_out.get("rejected_items", []),
            "llm_usage": round_usage,
        })

        if better(verdict["best"], context["best"]):
            context["best"] = verdict["best"]
        context["feedback"] = verdict["feedback"]     # 喂回下一轮 OptimizerAgent

        if verdict["converged"]:                       # 这轮没更优 → 停
            stop_reason = "llm_error" if last_optimizer_failed else "converged"
            break

    # max_rounds=1 且首轮 LLM 失败时，baseline 会首次刷新历史最优，Evaluator 不会
    # 判作 converged；此时真实停止原因仍应记为 LLM 失败，而不是伪装成正常到上限。
    if stop_reason == "max_rounds" and last_optimizer_failed:
        stop_reason = "llm_error"

    result = {
        "best": context["best"],
        "history": context["history"],
        "stop_reason": stop_reason,
        "rounds": len(context["history"]),
        "candidate_count": sum(
            len(item["ranking"]) + len(item["rejected"])
            for item in context["history"]
        ),
        "llm_candidate_count": sum(
            item["accepted_candidate_count"] for item in context["history"]
        ),
        "llm_usage": usage_events,
        "llm_usage_summary": _summarize_usage(usage_events),
        "used_baseline_fallback": (
            context["best"] is not None and context["best"].origin == "baseline"
        ),
    }

    if save:
        _persist(program, result, tools)

    return result


def _drain_usage(llm) -> list[dict]:
    """兼容没有 telemetry 能力的自定义 LLM client。"""
    drain = getattr(llm, "drain_usage", None)
    return drain() if callable(drain) else []


def _summarize_usage(events: list[dict]) -> dict:
    """汇总调用次数、token 和 LLM 耗时；任一 token 缺失则对应总量为 None。"""
    def total(name):
        values = [event.get(name) for event in events]
        if any(value is None for value in values):
            return None
        return sum(values)

    return {
        "llm_calls": len(events),
        "successful_calls": sum(bool(event.get("success")) for event in events),
        "failed_calls": sum(not bool(event.get("success")) for event in events),
        "prompt_tokens": total("prompt_tokens"),
        "completion_tokens": total("completion_tokens"),
        "reasoning_tokens": total("reasoning_tokens"),
        "total_tokens": total("total_tokens"),
        "llm_latency_ms": total("latency_ms"),
    }


def _persist(program, result, tools):
    """整轮实验写成一个 JSON 落到 runs/，用于复现。"""
    best = result["best"]
    data = {
        "program": program,
        "best": best.to_dict() if best else None,
        "rounds": result["history"],
        "stop_reason": result["stop_reason"],
        "round_count": result["rounds"],
        "candidate_count": result["candidate_count"],
        "llm_candidate_count": result["llm_candidate_count"],
        "llm_usage": result["llm_usage"],
        "llm_usage_summary": result["llm_usage_summary"],
        "used_baseline_fallback": result["used_baseline_fallback"],
    }
    return tools("save_result", {"data": data, "name": program})
