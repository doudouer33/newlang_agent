"""
Executor：唯一「动手」的 Agent —— 把未执行的候选真编译、真测、真计时。

README 角色表：输入「候选 + 工具」，输出「日志 + 结果」。它是 Agent 与真实执行
之间的唯一通道，依次调 build → run_tests → run_bench 把结果**回填**进 Candidate，
**不判断好坏**（谁更优是 Evaluator 的事）。

每个候选走同一条流水线：
  build      源码 + passes → bytecode。失败（语法错/未知 pass/pass 内部炸）→
             compiled=False，记 error，后面不用跑了。
  run_tests  bytecode + expected → correct。铁律「先过正确性」的判定就在这里，
             但 Executor 只**记录** correct，不因为它是 False 就丢掉候选。
  run_bench  bytecode → instr_count（确定性，主信号）+ time_ms（仅参考）。
             只要编译过就量 —— 哪怕功能不对，程序也真跑了，指令数是事实。

纪律对齐：所有工具都经 Tool Router（call_tool）分发，Executor 不直接 import 具体
工具函数；工具内部失败走返回值的 error 字段、不抛异常，Executor 如实抄进 Candidate。
"""
from __future__ import annotations

import re

from tools.registry import call_tool

from .base import BaseAgent

# 从源码注释 `// expect: 7, 9, 16` 读期望输出；和 main.py 同一约定。
_EXPECT_RE = re.compile(r"//\s*expect:\s*(.+)")


def _parse_expected(source):
    if not isinstance(source, str):
        return None
    m = _EXPECT_RE.search(source)
    if not m:
        return None
    try:
        return [int(x) for x in m.group(1).split(",")]
    except ValueError:
        return None


class Executor(BaseAgent):
    def __init__(self, llm=None, tools=None):
        # tools 是 Tool Router：一个 (name, inp)->dict 的可调用。默认用真的 call_tool；
        # 测试可注入假的来断言「调了哪些工具、按什么顺序」。
        super().__init__(llm, tools or call_tool)

    def run(self, context: dict) -> dict:
        candidates = context.get("candidates", [])
        ctx_expected = context.get("expected")     # 整轮共用的期望输出（可选）
        repeat = context.get("repeat", 1)
        do_save = context.get("save", False)

        saved = []
        for cand in candidates:
            self._execute(cand, ctx_expected, repeat)
            if do_save:
                res = self.tools("save_result",
                                 {"data": cand.to_dict(), "name": cand.id})
                if res.get("ok"):
                    saved.append(res["path"])

        # 只回结果，不排序、不过滤 —— 那是 Evaluator 的活。
        out = {"results": candidates}
        if do_save:
            out["saved"] = saved
        return out

    def _execute(self, cand, ctx_expected, repeat):
        # 1) 编译。source_program 存的是源码文本；passes=[] 就是 baseline。
        built = self.tools("build",
                           {"source": cand.source_program, "passes": cand.passes})
        if not built.get("ok"):
            cand.compiled = False
            cand.correct = False
            cand.error = built.get("error") or "编译失败"
            return
        cand.compiled = True
        bytecode = built["bytecode"]

        # 2) 正确性。期望输出优先取整轮 context 给的；没有就从源码 `// expect:` 读。
        expected = ctx_expected if ctx_expected is not None else _parse_expected(
            cand.source_program)
        if expected is None:
            # 无从判定正确性：如实说明，不假装通过。correct 保持 False。
            cand.correct = False
            cand.error = "未提供期望输出，正确性未判定"
        else:
            tested = self.tools("run_tests",
                               {"bytecode": bytecode, "expected": expected})
            cand.correct = bool(tested.get("correct"))
            if tested.get("error"):
                cand.error = tested["error"]        # 运行期异常（死循环/越界/除零…）

        # 3) 计时 + 数指令。编译过就量，哪怕功能不对（程序照样真跑了）。
        bench = self.tools("run_bench", {"bytecode": bytecode, "repeat": repeat})
        cand.instr_count = bench.get("instr_count")
        cand.exec_time_ms = bench.get("time_ms")
        if bench.get("error") and not cand.error:
            cand.error = bench["error"]
