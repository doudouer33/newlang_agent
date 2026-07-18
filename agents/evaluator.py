"""
Evaluator：过正确性 → 排序 → 选最优 → 回传反馈。

README 角色表：输入「日志 + 指标」，输出「排名 + 结论」。它是唯一「判断好坏」
的 Agent（Executor 只报事实，这里才排名）。三步：

  1. 过滤：铁律「先过正确性，再比性能」。compiled=False 或 correct=False 的候选
     一律出局（把程序改错了，指令数再低也作废）——用 Candidate.is_viable()。
  2. 排序：按 instr_count 升序。**只按 instr_count**，不按 time_ms —— time_ms 会
     抖（GC/调度/缓存），拿它排名会把测量噪声当成收益。并列时偏好 pass 更少的
     （更简单），再按 id 稳定排序。
  3. 结论：选出本轮最优；对比传入的「历史最优」判断这轮有没有进步（improved）；
     把最优、基线、失败原因打包成一段 feedback 字符串，回传给下一轮 OptimizerAgent
     当 context["feedback"]，形成闭环。

纯逻辑，无 LLM、无工具。
"""
from __future__ import annotations

from .base import BaseAgent


def better(a, b) -> bool:
    """a 是否严格优于 b（指令数更少）。a 必须可用；b 为 None 视为「还没有最优」。"""
    if a is None or a.instr_count is None:
        return False
    if b is None or b.instr_count is None:
        return True
    return a.instr_count < b.instr_count


def _sort_key(cand):
    # instr_count 为 None 的可用候选（极少见）排到最后；其次偏好 pass 少、id 稳定。
    ic = cand.instr_count if cand.instr_count is not None else float("inf")
    return (ic, len(cand.passes), cand.id)


class Evaluator(BaseAgent):
    def run(self, context: dict) -> dict:
        results = context.get("results", [])
        prev_best = context.get("best")            # 跨轮的历史最优（orchestrator 维护）

        viable = [c for c in results if c.is_viable()]
        rejected = [c for c in results if not c.is_viable()]
        ranking = sorted(viable, key=_sort_key)
        best = ranking[0] if ranking else None

        improved = better(best, prev_best)
        baseline = next((c for c in results if c.origin == "baseline"), None)

        return {
            "best": best,
            "ranking": ranking,
            "rejected": rejected,
            "improved": improved,
            # 这一轮没能刷新历史最优就算收敛（orchestrator 据此决定停不停）。
            "converged": not improved,
            "feedback": self._feedback(best, baseline, viable, rejected),
        }

    def _feedback(self, best, baseline, viable, rejected):
        """把本轮结论压成一段给下一轮 LLM 看的反馈：最优、基线、失败原因、建议。"""
        lines = []
        if best is not None:
            lines.append(f"本轮最优：{best.passes}，指令数 {best.instr_count}。")
        else:
            lines.append("本轮没有任何候选通过正确性，无最优。")

        if baseline is not None and baseline.instr_count is not None:
            lines.append(f"基线（无优化）指令数 {baseline.instr_count}。")
            if best is not None and best.instr_count >= baseline.instr_count:
                lines.append("最优候选相对基线没有收益——建议换 pass 组合或调整顺序。")

        lines.append(f"通过正确性的候选 {len(viable)} 个，被淘汰 {len(rejected)} 个。")

        # 淘汰原因摘要（最多列几条，够 LLM 避坑即可）。
        for c in rejected[:5]:
            if not c.compiled:
                lines.append(f"  淘汰 {c.passes}：编译失败（{c.error}）。")
            elif not c.correct:
                why = c.error or "输出与期望不符"
                lines.append(f"  淘汰 {c.passes}：功能不通过（{why}）。")

        return "\n".join(lines)
