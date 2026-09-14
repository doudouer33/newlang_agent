"""run_bench：执行 IR，测量指令数、时间和峰值 Python 内存。

三个指标的地位**不一样**，别混着用：

  instr_count —— VM 实际执行的指令条数（label 不计）。**确定性的**：同一段 IR
      跑一万遍都是同一个数，不受机器负载、Python 版本、有没有开浏览器影响。
      所以它是优化收益的**主要对比信号**，也是唯一能写进断言的那个。
      注意它是动态计数：循环体里一条指令跑 100 轮就计 100 次，反映的是真实
      工作量，不是代码行数。

  time_ms —— 墙钟时间，**仅供参考**。会抖（GC、调度、缓存），同一段 IR 前后两次
      能差出百分之几十。它的用处是发现"指令数降了但时间反而涨了"这类异常，
      不能拿来给两个差不多的方案排名次。

  peak_memory_kb —— tracemalloc 观测到的单次 VM 运行峰值 Python 分配。为避免
      tracemalloc 干扰计时，它在时间测量全部结束后单独再跑一次，也只作参考。

工具只把这些数如实报出来。怎么用、谁更优，是 Evaluator 的事。
"""
import contextlib
import io
import statistics
import time
import tracemalloc

from lang.vm import VM


def run_bench(inp: dict) -> dict:
    """返回动态指令数、时间中位数、峰值 Python 内存和错误。

    repeat 默认 1。给了 >1 就跑那么多遍、time_ms 取中位数（中位数比均值抗离群
    值，一次 GC 停顿不至于毁掉整轮测量）；instr_count 每遍都一样，取最后一遍。
    更正经的多轮/预热策略留给上层的 benchmark runner，这里只做最省事的那档。

    失败时三个指标都给 None——不填 0，0 会被上层误读成"零指令、零内存、
    快得飞起"，那是最糟糕的一种谎报。
    """
    bytecode = inp.get("bytecode")
    repeat = inp.get("repeat", 1)
    if repeat is None:
        repeat = 1

    if bytecode is None:
        return {
            "instr_count": None,
            "time_ms": None,
            "peak_memory_kb": None,
            "error": "没有 bytecode 可执行",
        }
    if not isinstance(repeat, int) or isinstance(repeat, bool) or repeat < 1:
        return {
            "instr_count": None,
            "time_ms": None,
            "peak_memory_kb": None,
            "error": "repeat 必须是大于等于 1 的整数",
        }

    times = []
    instr_count = None
    peak_memory_kb = None
    try:
        for _ in range(repeat):
            vm = VM()
            # print 走 stdout 是真实 I/O，几百次能占掉大头时间，量的就不是 IR 的
            # 工作量而是终端速度了。丢进 StringIO，让计时只反映解释器本身。
            with contextlib.redirect_stdout(io.StringIO()):
                start = time.perf_counter()
                vm.run(bytecode)
                elapsed = time.perf_counter() - start
            times.append(elapsed * 1000.0)
            instr_count = vm.instr_count

        # 内存测量与上面的计时完全分开。若调用方已经启用 tracemalloc，不擅自
        # 关闭它；只重置峰值并读取本次 VM 运行后的峰值。
        tracing_before = tracemalloc.is_tracing()
        if not tracing_before:
            tracemalloc.start()
        tracemalloc.reset_peak()
        try:
            memory_vm = VM()
            with contextlib.redirect_stdout(io.StringIO()):
                memory_vm.run(bytecode)
            _, peak_bytes = tracemalloc.get_traced_memory()
            peak_memory_kb = peak_bytes / 1024.0
        finally:
            if not tracing_before:
                tracemalloc.stop()
    except Exception as e:
        return {
            "instr_count": None,
            "time_ms": None,
            "peak_memory_kb": None,
            "error": f"{type(e).__name__}: {e}",
        }

    return {
        "instr_count": instr_count,
        "time_ms": statistics.median(times),
        "peak_memory_kb": peak_memory_kb,
        "error": "",
    }
