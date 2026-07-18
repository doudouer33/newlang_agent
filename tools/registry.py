"""Tool Router：工具名 → 工具函数 的路由表 + 分发。

⚠️ 和 optimizer/registry.py 是**两回事**，别混：
      optimizer/registry.py  路由的是 pass（const_fold / dce / …），作用于 IR
      tools/registry.py（本文件）路由的是工具（build / run_tests / …），作用于世界

为什么 Agent 不直接 import build 然后调？因为 Agent 产出的是**文本**——它说
"我要 build"，说出来的是字符串,不是函数引用。总得有个地方把字符串翻译成调用，
就是这里。有了这张表，Agent 能做什么就是一件写死的事：表里有的才能调，
表外的一律报错。这是能力边界，也是安全边界。

分发逻辑薄得几乎没有（查表 + 调用），这正是"所有工具签名统一"换来的好处：
dict 进、dict 出，Router 不需要知道任何一个工具的参数长什么样，也就不需要为
新工具改一行代码 —— 加工具只在 TOOLS 里加一行。
"""
from .bench import run_bench
from .build import build
from .run import run_tests
from .save import save_result


class UnknownToolError(ValueError):
    """调了一个没注册的工具名。"""


# 工具名 → 工具函数。新增工具就在这里加一行（记得也在 __init__.py 导出）。
TOOLS = {
    "build": build,
    "run_tests": run_tests,
    "run_bench": run_bench,
    "save_result": save_result,
    # "profile": profile,        # 待实现
}


def available_tools() -> list:
    """已注册的工具名（排序后，方便打印和报错）。"""
    return sorted(TOOLS)


def call_tool(name: str, inp: dict) -> dict:
    """按名字分发：查表，用 inp 调它，原样返回它的返回值。

    名字没注册就抛 UnknownToolError，**不静默返回空 dict**：Agent 把工具名拼错了
    是它自己的 bug，得让它当场看到"叫 X 的工具不存在，能用的是这些"，才能改口
    重试。返回个空 dict，它只会以为工具跑了但什么也没发生，然后在错误的前提上
    继续往下推——那种错最难查。

    注意：这里只保证"工具被调到了"。工具**内部**的失败（编译错、运行错）不走异常，
    走返回值里的 error 字段——那是工具的正常输出，不是 Router 的事。
    """
    try:
        fn = TOOLS[name]
    except KeyError:
        raise UnknownToolError(
            f"未注册的工具: {name!r}；已注册的有: {available_tools()}"
        ) from None

    return fn(inp)
