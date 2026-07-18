"""Agent 能"动手"的工具层。

上层（Agent / Executor / Evaluator）不直接碰 lang 和 optimizer，一切动作都从
这里走。所以这一层有三条纪律，每个工具都得守：

  1. 统一签名 `f(inp: dict) -> dict`。吃字典、吐字典，两头都能直接 json.dump
     进 runs/ —— 一次调用的输入输出存下来就是一条可复现的记录。
  2. 工具内部不许把异常冒泡出去。编译错、运行错都 catch 住，如实填进返回值的
     error 字段。工具崩了会把整个 Agent 循环带崩，那是最糟的失败模式。
  3. 只报事实，不做判断。编译成没成、结果对不对、跑了多少指令——如实返回。
     "哪个方案更好"是 Evaluator 的活，工具不排序、不打分。

工具之间互不调用（build 不会顺手帮你 run）。串联是 Executor 的职责。
"""
from .bench import run_bench
from .build import build
from .registry import TOOLS, UnknownToolError, available_tools, call_tool
from .run import run_tests
from .save import save_result

__all__ = [
    "build",
    "run_tests",
    "run_bench",
    "save_result",
    "call_tool",
    "available_tools",
    "TOOLS",
    "UnknownToolError",
]
