"""
OptimizerAgent：调 LLM 产出一批「未执行的」优化候选。

README 角色表：输入「程序 + IR」，输出「候选列表」。它是 LLM 在本项目的主战场
之一（案例 B「优化候选生成」）。**它只负责想，不负责跑** —— 产出的每个 Candidate
都是 origin="llm"、只填了 passes、执行类字段全空，交给 Executor 去真编译真测。

处理流程：
  1. 用工具链把源码编译成 baseline IR，格式化后放进 prompt —— 让 LLM 看着真实
     的三地址码判断哪些 pass 用得上，而不是凭空猜。
  2. 把「程序 + IR + 可用 pass + 上一轮反馈」拼成 user prompt，配 optimize.txt 系统提示，
     调 llm.complete_json 拿回 {"candidates": [{"passes": [...], "reason": ...}, ...]}。
  3. **清洗**：只保留注册过的 pass 名（LLM 可能瞎编），按顺序去重，丢掉空组合
     （空 = baseline，不属于 llm 档），最多取 n 个。清洗后才包成 Candidate。

清洗这一步是「LLM 负责想、工具链负责真跑」这条纪律的体现：模型的输出一律当作
不可信草案，落到可执行的东西之前先过一遍校验。
"""
from __future__ import annotations

from contracts import Candidate
from llm import LLMError, load_prompt
from optimizer.registry import available_passes

from .base import BaseAgent


class OptimizerAgent(BaseAgent):
    def __init__(self, llm=None, tools=None, n_candidates: int = 3):
        super().__init__(llm, tools)
        self.n_candidates = n_candidates

    def run(self, context: dict) -> dict:
        program = context.get("program", "program")     # 样例名，用作标签和 id 前缀
        source = context.get("source")                  # 源码文本
        allowed = list(context.get("available_passes") or available_passes())
        feedback = context.get("feedback")              # 上一轮 Evaluator 的建议（可选）
        n = context.get("n", self.n_candidates)

        ir_text = self._render_ir(source)
        user = self._build_user(program, source, ir_text, allowed, feedback, n)

        try:
            data = self.llm.complete_json(user, system=load_prompt("optimize.txt"))
        except LLMError as e:
            # LLM 或解析失败：不抛，返回空候选 + 错误，让编排循环照常继续（这一轮无候选）。
            return {"candidates": [], "error": str(e)}

        candidates = self._to_candidates(program, source, data.get("candidates", []),
                                         set(allowed), n)
        return {"candidates": candidates}

    # ---- 把源码编译成 baseline IR 文本，喂给 LLM 当判断依据 ----
    def _render_ir(self, source):
        if not source:
            return "(未提供源码)"
        try:
            from lang.ir import format_ir
            from tools.build import build
            res = build({"source": source, "passes": []})       # passes=[] 即 baseline IR
            if not res.get("ok"):
                return f"(生成 IR 失败：{res.get('error')})"
            return format_ir(res["bytecode"])
        except Exception as e:                                    # IR 只是提示信息，拿不到也不致命
            return f"(生成 IR 失败：{type(e).__name__}: {e})"

    def _build_user(self, program, source, ir_text, allowed, feedback, n):
        parts = [
            f"程序名：{program}",
            f"可用的优化 pass：{allowed}",
            "",
            "源码：",
            source or "(未提供)",
            "",
            "编译出的 baseline 三地址码 IR：",
            ir_text,
        ]
        if feedback:
            parts += ["", "上一轮反馈（据此调整这轮候选）：", str(feedback)]
        parts += ["", f"请给出至多 {n} 个彼此不同的 pass 组合候选。"]
        return "\n".join(parts)

    # ---- 清洗 LLM 草案 → 一批 Candidate ----
    def _to_candidates(self, program, source, raw, allowed_set, n):
        seen = set()                     # 按 pass 序列去重（顺序敏感：[cf,dce] != [dce,cf]）
        out = []
        for item in raw:
            passes = self._clean_passes(item, allowed_set)
            if not passes:               # 空组合 = baseline，不放进 llm 档
                continue
            key = tuple(passes)
            if key in seen:
                continue
            seen.add(key)
            out.append(Candidate(
                id=f"{program}#llm:{'+'.join(passes)}",
                source_program=source if source is not None else program,
                passes=passes,
                origin="llm",
            ))
            if len(out) >= n:
                break
        return out

    @staticmethod
    def _clean_passes(item, allowed_set):
        """从一个候选草案里取出合法的 pass 序列：只留注册过的名字，保持顺序。"""
        if isinstance(item, dict):
            raw_passes = item.get("passes", [])
        elif isinstance(item, list):     # 容忍 LLM 直接给了个 pass 数组
            raw_passes = item
        else:
            return []
        if not isinstance(raw_passes, list):
            return []
        return [p for p in raw_passes if isinstance(p, str) and p in allowed_set]
