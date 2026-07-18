"""save_result：把一次运行的记录落盘到 runs/。

存在的理由是**复现**：Agent 跑完一轮，源码、passes 组合、正确性、指令数全在
一个 dict 里，写成 JSON 存下来，事后能一条条翻出来核对"当时到底是怎么跑的"。

它不关心 data 里装的是什么，也不看内容好坏——只负责写文件。
"""
import json
import os
from datetime import datetime

_RUNS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "runs",
)


def _safe(name: str) -> str:
    """文件名片段只留安全字符：name 是上层传进来的，可能带 / 或 .. ——
    那会把文件写到 runs/ 外面去。"""
    cleaned = "".join(c if (c.isalnum() or c in "-_") else "_" for c in name)
    return cleaned.strip("_") or "result"


def save_result(inp: dict) -> dict:
    """{"data": dict, "name"?: str} -> {"ok", "path", "error"}

    写成 runs/<时间戳>_<name>.json。runs/ 不存在就建。同一秒内重复调用会撞名，
    撞了就往后加 _1 / _2 —— 宁可多一个文件，也不能悄悄覆盖掉上一条记录。
    """
    data = inp.get("data")
    name = _safe(str(inp.get("name") or "result"))

    try:
        # 先序列化成字符串、成功了再落盘。若换成 json.dump(data, f) 直接往打开的
        # 文件流里边写边序列化，data 里混进不可序列化的东西时，json 会先把前半截
        # 字节写进文件、再抛 TypeError —— 于是磁盘上留下一个半截的坏文件，而工具
        # 却报了 ok=False。序列化和写文件分两步，失败就根本不碰磁盘。
        # ensure_ascii=False：源码和报错里有中文，存成 \uXXXX 就没法直接读了
        text = json.dumps(data, ensure_ascii=False, indent=2)

        os.makedirs(_RUNS_DIR, exist_ok=True)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(_RUNS_DIR, f"{stamp}_{name}.json")
        n = 0
        while os.path.exists(path):
            n += 1
            path = os.path.join(_RUNS_DIR, f"{stamp}_{name}_{n}.json")

        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception as e:
        # data 里混进不可序列化的东西（TypeError）、目录没权限（OSError）…
        return {"ok": False, "path": "", "error": f"{type(e).__name__}: {e}"}

    return {"ok": True, "path": path, "error": ""}
