"""
orchestrator + Planner 的测试：离线（StubLLMClient 出候选 + 真实工具链执行）。

验证多轮闭环的编排逻辑：baseline 锚点、按指令数选最优、收敛即停、max_rounds 上限、
反馈跨轮回传、落盘。

跑法（项目根目录下）：
    python tests/test_orchestrator.py
    pytest tests/
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import Planner, orchestrate                         # noqa: E402
from llm import StubLLMClient                                   # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_RUNS = os.path.join(_ROOT, "runs")


def _sample(name):
    with open(os.path.join(_ROOT, "lang", "samples", name), encoding="utf-8") as f:
        return f.read()


def _stub(passes_list):
    """一个每轮都返回同一批候选的桩。"""
    return StubLLMClient({"candidates": [{"passes": p} for p in passes_list]})


# ==================================================================
# Planner
# ==================================================================

def test_planner_returns_available_passes_and_n():
    plan = Planner(n_candidates=4).run({})
    assert "licm" in plan["available_passes"]
    assert plan["n"] == 4
    assert Planner().run({"n": 2})["n"] == 2       # context 覆盖默认


# ==================================================================
# orchestrate
# ==================================================================

def test_picks_best_and_converges():
    """licm_demo：LLM 每轮给 [licm]，最优 708（<基线 807），第二轮无更优即停。"""
    src = _sample("licm_demo.nl")
    best, history = orchestrate("licm_demo", src, llm=_stub([["licm"]]),
                                max_rounds=3, save=False)
    assert best.passes == ["licm"]
    assert best.instr_count == 708
    assert len(history) == 2                        # 第1轮进步、第2轮收敛→停
    assert history[0]["best"]["instr_count"] == 708


def test_baseline_wins_when_no_candidate_improves():
    """候选相对基线零收益时，最优回落到 baseline（并列偏好 pass 更少）。"""
    src = _sample("loop_sum.nl")
    best, _ = orchestrate("loop_sum", src, llm=_stub([["const_fold"]]),
                          max_rounds=3, save=False)
    assert best.origin == "baseline"
    assert best.passes == []


def test_max_rounds_caps_iterations():
    src = _sample("licm_demo.nl")
    _, history = orchestrate("licm_demo", src, llm=_stub([["licm"]]),
                             max_rounds=1, save=False)
    assert len(history) == 1                         # 上限 1 轮，不管收没收敛


def test_feedback_threaded_into_next_round():
    """上一轮 Evaluator 的反馈要出现在下一轮 OptimizerAgent 的 prompt 里。"""
    users = []

    def fake(user, system, schema):
        users.append(user)
        return {"candidates": [{"passes": ["licm"]}]}

    orchestrate("licm_demo", _sample("licm_demo.nl"), llm=StubLLMClient(fake),
                max_rounds=2, save=False)
    assert len(users) == 2
    assert "本轮最优" not in users[0]                # 第0轮没有反馈
    assert "本轮最优" in users[1]                    # 第1轮带上了第0轮的反馈


def test_history_records_baseline_and_winner():
    src = _sample("licm_demo.nl")
    _, history = orchestrate("licm_demo", src, llm=_stub([["licm"]]),
                             max_rounds=1, save=False)
    ranking = history[0]["ranking"]
    origins = {r["origin"] for r in ranking}
    assert "baseline" in origins and "llm" in origins    # 锚点和候选都在排名里


def test_persists_run_to_disk():
    """save=True 时把整轮实验写成 runs/*.json；测完清理掉。"""
    src = _sample("licm_demo.nl")
    before = set(os.listdir(_RUNS)) if os.path.isdir(_RUNS) else set()
    orchestrate("licm_demo", src, llm=_stub([["licm"]]), max_rounds=1, save=True)
    after = set(os.listdir(_RUNS))
    new = [f for f in (after - before) if f.endswith(".json")]
    try:
        assert len(new) == 1
        with open(os.path.join(_RUNS, new[0]), encoding="utf-8") as f:
            data = json.load(f)
        assert data["program"] == "licm_demo"
        assert data["best"]["passes"] == ["licm"]
        assert len(data["rounds"]) == 1
    finally:
        for f in new:                               # 不把测试产物留在 runs/
            os.remove(os.path.join(_RUNS, f))


def main():
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ✅ {name}")
        except AssertionError as e:
            failed += 1
            print(f"  ❌ {name}: {e or 'assertion failed'}")
    print(f"\n{len(tests) - failed}/{len(tests)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
