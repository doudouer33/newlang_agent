"""run_tests：执行 IR，跟期望输出对答案。

这个工具服务于那条铁律——**先过正确性，再比性能**。上层拿 correct 做第一道
过滤：correct=False 的方案，指令数再低也直接出局（把程序改错了当然快）。

它只回答"跑出来是不是 expected"，不回答"这个方案好不好"。
"""
import contextlib
import io

from lang.vm import VM


def run_tests(inp: dict) -> dict:
    """{"bytecode": IR, "expected": 期望输出} -> {"correct", "output", "error"}

    运行期异常（死循环触发步数上限、读未定义变量、数组越界、除零…）一律 catch，
    correct=False + error 说明原因，output 尽力给出崩之前已经打出来的部分。
    """
    bytecode = inp.get("bytecode")
    expected = inp.get("expected")

    if bytecode is None:
        return {"correct": False, "output": None, "error": "没有 bytecode 可执行"}

    vm = VM()
    try:
        # VM 每条 print 都会往 stdout 打一份。工具是给 Agent 调的，不是给人看的，
        # 这些输出会淹掉上层日志；真正的结果在 vm.output 里，stdout 丢掉即可。
        with contextlib.redirect_stdout(io.StringIO()):
            output = vm.run(bytecode)
    except Exception as e:
        return {
            "correct": False,
            "output": list(vm.output),      # 崩之前打出来的部分，便于定位
            "error": f"{type(e).__name__}: {e}",
        }

    return {"correct": output == expected, "output": output, "error": ""}
