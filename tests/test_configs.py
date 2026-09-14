"""阶段四固定样例和五种实验配置的协议测试。"""
import json
import os
import sys
from dataclasses import FrozenInstanceError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmark.configs import (  # noqa: E402
    CONFIG_NAMES,
    CONFIGS,
    FORMAL_SAMPLES,
    REFERENCE_CONFIG_NAME,
    SYSTEM_CONFIG_NAMES,
    ExperimentConfig,
    get_config,
    serialize_configs,
)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_formal_samples_are_fixed_to_five_existing_programs():
    assert FORMAL_SAMPLES == (
        "branch", "loop_sum", "array_dot", "licm_demo", "dead_code"
    )
    assert len(FORMAL_SAMPLES) == 5
    assert "basic" not in FORMAL_SAMPLES
    for name in FORMAL_SAMPLES:
        assert os.path.isfile(os.path.join(ROOT, "lang", "samples", name + ".nl"))


def test_config_names_separate_four_system_profiles_from_oracle():
    assert SYSTEM_CONFIG_NAMES == (
        "baseline", "llm_only", "agent_min", "agent_full"
    )
    assert REFERENCE_CONFIG_NAME == "oracle"
    assert CONFIG_NAMES == SYSTEM_CONFIG_NAMES + ("oracle",)
    assert tuple(CONFIGS) == CONFIG_NAMES


def test_baseline_contract():
    config = get_config("baseline")
    assert config.use_llm is False
    assert config.n_candidates == 0
    assert config.max_rounds == 0
    assert config.use_feedback is False
    assert config.exhaustive is False


def test_llm_only_contract():
    config = get_config("llm_only")
    assert config.use_llm is True
    assert config.n_candidates == 1
    assert config.max_rounds == 1
    assert config.use_feedback is False


def test_agent_min_contract():
    config = get_config("agent_min")
    assert config.use_llm is True
    assert config.n_candidates == 3
    assert config.max_rounds == 1
    assert config.use_feedback is False


def test_agent_full_contract():
    config = get_config("agent_full")
    assert config.use_llm is True
    assert config.n_candidates == 3
    assert config.max_rounds == 3
    assert config.use_feedback is True


def test_oracle_contract_is_exhaustive_without_llm():
    config = get_config("oracle")
    assert config.use_llm is False
    assert config.n_candidates == 16
    assert config.max_rounds == 1
    assert config.use_feedback is False
    assert config.exhaustive is True


def test_configs_are_frozen():
    config = get_config("baseline")
    try:
        config.max_rounds = 99
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("实验配置必须不可变")

    try:
        CONFIGS["baseline"] = get_config("oracle")
    except TypeError:
        pass
    else:
        raise AssertionError("配置注册表必须不可变")


def test_invalid_config_name_is_explicit():
    try:
        get_config("unknown")
    except ValueError as exc:
        assert "unknown" in str(exc)
        assert "baseline" in str(exc)
    else:
        raise AssertionError("未知配置应该报错")


def test_invalid_custom_config_is_rejected():
    invalid_kwargs = [
        dict(name="x", use_llm=True, n_candidates=0, max_rounds=1,
             use_feedback=False),
        dict(name="x", use_llm=False, n_candidates=1, max_rounds=1,
             use_feedback=True),
        dict(name="x", use_llm=True, n_candidates=1, max_rounds=1,
             use_feedback=False, exhaustive=True),
    ]
    for kwargs in invalid_kwargs:
        try:
            ExperimentConfig(**kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError(f"非法配置未被拒绝：{kwargs}")


def test_serialize_configs_is_stable_and_json_safe():
    serialized = serialize_configs()
    assert [item["name"] for item in serialized] == list(CONFIG_NAMES)
    assert json.loads(json.dumps(serialized, ensure_ascii=False)) == serialized


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
