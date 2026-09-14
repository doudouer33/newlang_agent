"""阶段四离线端到端：Stub LLM → 五配置矩阵 → schema JSON → Markdown。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmark.configs import CONFIG_NAMES  # noqa: E402
from benchmark.matrix import run_matrix  # noqa: E402
from benchmark.report import generate_report  # noqa: E402
from benchmark.schema import MATRIX_SCHEMA_VERSION, MatrixReport  # noqa: E402
from llm import StubLLMClient  # noqa: E402


def test_offline_matrix_to_markdown_end_to_end():
    llm = StubLLMClient(
        {
            "candidates": [
                {"passes": ["const_fold", "dce"]},
                {"passes": ["licm"]},
                {"passes": ["dce"]},
            ]
        },
        usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    )
    matrix, path = run_matrix(
        samples=["dead_code"],
        configs=CONFIG_NAMES,
        trials=1,
        bench_repeat=1,
        model="stub",
        llm=llm,
        save=False,
        matrix_id="offline-e2e",
        generated_at="2026-09-14T12:00:00+08:00",
    )

    # 真正走一遍 JSON 序列化/反序列化边界，再交给严格报告生成器。
    serialized = json.dumps(matrix, ensure_ascii=False)
    restored = json.loads(serialized)
    validated = MatrixReport.from_dict(restored)
    markdown = generate_report(validated, title="离线端到端报告", strict=True)

    assert path is None
    assert matrix["schema_version"] == MATRIX_SCHEMA_VERSION
    assert len(matrix["records"]) == len(CONFIG_NAMES)
    assert matrix["summary"]["correct_records"] == len(CONFIG_NAMES)
    assert matrix["summary"]["llm_calls"] == 4
    assert markdown.startswith("# 离线端到端报告\n")
    assert "## 6. 每程序性能对比（表 A）" in markdown
    assert "## 9. Agent 提案搜索质量（表 B）" in markdown
    assert "## 10. LLM 成本（表 C）" in markdown
    assert "| dead_code | agent_full |" in markdown
    assert "| dead_code | oracle |" in markdown


def main():
    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ✅ {name}")
        except Exception as exc:
            failed += 1
            print(f"  ❌ {name}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
