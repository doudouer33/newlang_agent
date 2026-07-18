"""
optimizer 的最小测试集：手工构造输入 IR、手工写出期望 IR、断言相等。

跑法（项目根目录下）：
    python tests/test_optimizer.py        # 不依赖 pytest，直接跑
    pytest tests/                         # 装了 pytest 也能跑（函数名是 test_*）

指令格式：定长 4 元组 (op, dst, src1, src2)。src 槽里 int 是字面量、str 是变量名。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lang.vm import VM                                          # noqa: E402
from optimizer import apply_passes, const_fold, dce, licm       # noqa: E402
from optimizer.registry import UnknownPassError                 # noqa: E402


# ==================================================================
# const_fold
# ==================================================================

def test_fold_two_constants():
    """两个 src 都是字面量 → 编译期算出来，换成 copy。"""
    ir = [("mul", "t0", 2, 3)]
    assert const_fold(ir) == [("copy", "t0", 6, None)]


def test_no_fold_when_operand_is_variable():
    """只要有一个 src 是变量（str），就原样保留。"""
    ir = [
        ("add", "t0", 1, "x"),
        ("add", "t1", "x", "y"),
    ]
    assert const_fold(ir) == ir


def test_no_fold_on_division_by_zero():
    """除零不折叠：留给运行时炸，编译期不替程序做决定。"""
    ir = [("div", "t0", 8, 0)]
    assert const_fold(ir) == ir


def test_fold_division_matches_vm_floor_semantics():
    """折叠 div 必须和 VM 的 `//` 一致，否则优化改变了程序语义。"""
    assert const_fold([("div", "t0", 7, 2)]) == [("copy", "t0", 3, None)]
    assert const_fold([("div", "t0", -7, 2)]) == [("copy", "t0", -4, None)]


def test_fold_comparison_to_one_or_zero():
    """比较类也折叠，结果用 1/0 表示（和 VM 的 int(a < b) 一致）。"""
    ir = [("lt", "t0", 1, 2), ("eq", "t1", 3, 4)]
    assert const_fold(ir) == [
        ("copy", "t0", 1, None),
        ("copy", "t1", 0, None),
    ]


def test_other_instructions_untouched():
    """print / 控制流 / 数组指令一律原样保留。"""
    ir = [
        ("label", "L0", None, None),
        ("print", None, "x", None),
        ("jump_if_false", "L1", "t0", None),
        ("store_idx", "arr", 0, 5),
    ]
    assert const_fold(ir) == ir


def test_const_fold_does_not_mutate_input():
    """纯函数：不原地修改传进来的 IR（下游要拿同一段基线跑多次对比）。"""
    ir = [("add", "t0", 1, 2)]
    snapshot = list(ir)
    const_fold(ir)
    assert ir == snapshot


# ==================================================================
# dce
# ==================================================================

def test_dce_removes_dead_variable():
    """dead 之后再没被读过 → 整条删掉。"""
    ir = [
        ("copy", "dead", 1, None),
        ("print", None, "x", None),
    ]
    assert dce(ir) == [("print", None, "x", None)]


def test_dce_keeps_print():
    """print 有副作用（可观测输出），永远保留 —— 它也不 def 任何变量。"""
    ir = [("print", None, "x", None)]
    assert dce(ir) == ir


def test_dce_keeps_variable_used_later():
    """被后续指令读到的变量必须留着。"""
    ir = [
        ("copy", "x", 1, None),
        ("print", None, "x", None),
    ]
    assert dce(ir) == ir


def test_dce_keeps_side_effects_and_control_flow():
    """store_idx（写数组）、label、jump 一律保留。"""
    ir = [
        ("newarray", "arr", 3, None),
        ("store_idx", "arr", 0, 5),
        ("label", "L0", None, None),
        ("jump", "L0", None, None),
    ]
    assert dce(ir) == ir


def test_dce_iterates_to_fixed_point():
    """删掉 `y = t0` 会让上游的 `t0 = 1 + 2` 也变成死代码，要连锁删干净。"""
    ir = [
        ("add", "t0", 1, 2),
        ("copy", "y", "t0", None),
        ("print", None, "x", None),
    ]
    assert dce(ir) == [("print", None, "x", None)]


def test_dce_does_not_break_loops():
    """回跳（backward jump）陷阱：循环变量只在**自增之前**被读。

    `i = t2`（下标 9）之后没有任何指令读 i，但 10 号的 goto 会绕回去让 4 号
    重新读 i。朴素的"只看之后"规则会删掉 9、进而删掉 8，循环变量不再自增
    → 死循环。这里断言它们被保留，并真的跑 VM 验证结果还是 55。
    """
    ir = [
        ("copy", "n", 10, None),                 # 0
        ("copy", "i", 1, None),                  # 1
        ("copy", "sum", 0, None),                # 2
        ("label", "L0_while", None, None),       # 3
        ("le", "t0", "i", "n"),                  # 4   t0 = i <= n
        ("jump_if_false", "L1_endwhile", "t0", None),   # 5
        ("add", "t1", "sum", "i"),               # 6
        ("copy", "sum", "t1", None),             # 7
        ("add", "t2", "i", 1),                   # 8
        ("copy", "i", "t2", None),               # 9   ← 之后没人读 i，但不能删
        ("jump", "L0_while", None, None),        # 10
        ("label", "L1_endwhile", None, None),    # 11
        ("print", None, "sum", None),            # 12
    ]
    assert dce(ir) == ir
    assert VM().run(dce(ir)) == [55]


def test_dce_does_not_mutate_input():
    ir = [("copy", "dead", 1, None), ("print", None, "x", None)]
    snapshot = list(ir)
    dce(ir)
    assert ir == snapshot


# ==================================================================
# licm（循环不变量外提）
# ==================================================================

def test_licm_hoists_invariant_out_of_loop():
    """k*n 在循环里不变 → `t1 = k * n` 提到入口标签之前，循环体里不再有它。"""
    ir = [
        ("copy", "n", 100, None),
        ("copy", "k", 3, None),
        ("copy", "s", 0, None),
        ("copy", "i", 0, None),
        ("label", "L0", None, None),
        ("lt", "t0", "i", "n"),
        ("jump_if_false", "L1", "t0", None),
        ("mul", "t1", "k", "n"),                 # 循环不变量：k、n 都没变
        ("add", "t2", "s", "t1"),
        ("copy", "s", "t2", None),
        ("add", "t3", "i", 1),
        ("copy", "i", "t3", None),
        ("jump", "L0", None, None),
        ("label", "L1", None, None),
        ("print", None, "s", None),
    ]
    assert licm(ir) == [
        ("copy", "n", 100, None),
        ("copy", "k", 3, None),
        ("copy", "s", 0, None),
        ("copy", "i", 0, None),
        ("mul", "t1", "k", "n"),                 # ← 提到循环入口标签之前（preheader）
        ("label", "L0", None, None),
        ("lt", "t0", "i", "n"),
        ("jump_if_false", "L1", "t0", None),
        ("add", "t2", "s", "t1"),                # 循环体里 mul 没了，其余不动
        ("copy", "s", "t2", None),
        ("add", "t3", "i", 1),
        ("copy", "i", "t3", None),
        ("jump", "L0", None, None),
        ("label", "L1", None, None),
        ("print", None, "s", None),
    ]


def test_licm_preserves_result_and_cuts_instr_count():
    """铁律：先过正确性。外提后结果不变（30000），执行指令数明显下降。"""
    ir = [
        ("copy", "n", 100, None),
        ("copy", "k", 3, None),
        ("copy", "s", 0, None),
        ("copy", "i", 0, None),
        ("label", "L0", None, None),
        ("lt", "t0", "i", "n"),
        ("jump_if_false", "L1", "t0", None),
        ("mul", "t1", "k", "n"),
        ("add", "t2", "s", "t1"),
        ("copy", "s", "t2", None),
        ("add", "t3", "i", 1),
        ("copy", "i", "t3", None),
        ("jump", "L0", None, None),
        ("label", "L1", None, None),
        ("print", None, "s", None),
    ]
    base_vm, opt_vm = VM(), VM()
    assert base_vm.run(ir) == opt_vm.run(licm(ir)) == [30000]
    assert opt_vm.instr_count < base_vm.instr_count      # 每轮少算一次 mul


def test_licm_leaves_variant_code_untouched():
    """循环体里每条都依赖循环变量 i（loop_sum 的形状）→ 无可外提，恒等变换。"""
    ir = [
        ("copy", "n", 10, None),
        ("copy", "i", 1, None),
        ("copy", "sum", 0, None),
        ("label", "L0_while", None, None),
        ("le", "t0", "i", "n"),
        ("jump_if_false", "L1_endwhile", "t0", None),
        ("add", "t1", "sum", "i"),
        ("copy", "sum", "t1", None),
        ("add", "t2", "i", 1),
        ("copy", "i", "t2", None),
        ("jump", "L0_while", None, None),
        ("label", "L1_endwhile", None, None),
        ("print", None, "sum", None),
    ]
    assert licm(ir) == ir
    assert VM().run(licm(ir)) == [55]


def test_licm_does_not_hoist_division():
    """div 不外提：循环若一轮没进，提到外面就凭空执行、可能触发本不该有的除零。"""
    ir = [
        ("copy", "a", 10, None),
        ("copy", "b", 2, None),
        ("copy", "i", 0, None),
        ("copy", "n", 3, None),
        ("label", "L0", None, None),
        ("lt", "t0", "i", "n"),
        ("jump_if_false", "L1", "t0", None),
        ("div", "t1", "a", "b"),                 # 不变量，但 div 一律留在原地
        ("add", "t2", "i", 1),
        ("copy", "i", "t2", None),
        ("jump", "L0", None, None),
        ("label", "L1", None, None),
    ]
    assert licm(ir) == ir


def test_licm_hoists_chained_invariants_together():
    """t1=k*n 提出去后，只依赖 t1 的 t2=t1+1 也随之够格 → 一趟里链式提净。"""
    ir = [
        ("copy", "k", 3, None),
        ("copy", "n", 4, None),
        ("copy", "s", 0, None),
        ("copy", "i", 0, None),
        ("label", "L0", None, None),
        ("lt", "t0", "i", "n"),
        ("jump_if_false", "L1", "t0", None),
        ("mul", "t1", "k", "n"),                 # 不变量
        ("add", "t2", "t1", 1),                  # 依赖 t1，也不变
        ("add", "t3", "s", "t2"),                # 依赖 s（变），留在循环里
        ("copy", "s", "t3", None),
        ("add", "t4", "i", 1),
        ("copy", "i", "t4", None),
        ("jump", "L0", None, None),
        ("label", "L1", None, None),
        ("print", None, "s", None),
    ]
    out = licm(ir)
    # t1、t2 都被提到 L0 标签之前，且保持先后顺序；t3 仍在循环体内。
    label_pos = out.index(("label", "L0", None, None))
    hoisted = out[:label_pos]
    assert ("mul", "t1", "k", "n") in hoisted
    assert ("add", "t2", "t1", 1) in hoisted
    assert hoisted.index(("mul", "t1", "k", "n")) < hoisted.index(("add", "t2", "t1", 1))
    assert ("add", "t3", "s", "t2") in out[label_pos:]     # 依赖变量的没提
    assert VM().run(ir) == VM().run(out) == [52]           # (k*n+1)=13，累加 4 轮 → 52


def test_licm_hoists_from_inner_loop_only_when_variant_in_outer():
    """嵌套：p*q 对内外层都不变 → 提到最外层；p*q+i 只对内层不变 → 提到两层之间。"""
    ir = [
        ("copy", "p", 5, None),
        ("copy", "q", 6, None),
        ("copy", "n", 2, None),
        ("copy", "m", 2, None),
        ("copy", "acc", 0, None),
        ("copy", "i", 0, None),
        ("label", "Louter", None, None),
        ("lt", "t0", "i", "n"),
        ("jump_if_false", "Eouter", "t0", None),
        ("copy", "j", 0, None),
        ("label", "Linner", None, None),
        ("lt", "t1", "j", "m"),
        ("jump_if_false", "Einner", "t1", None),
        ("mul", "t2", "p", "q"),                 # 内外层都不变
        ("add", "t3", "t2", "i"),                # 只对内层不变（用了外层变量 i）
        ("add", "t4", "acc", "t3"),
        ("copy", "acc", "t4", None),
        ("add", "t5", "j", 1),
        ("copy", "j", "t5", None),
        ("jump", "Linner", None, None),
        ("label", "Einner", None, None),
        ("add", "t6", "i", 1),
        ("copy", "i", "t6", None),
        ("jump", "Louter", None, None),
        ("label", "Eouter", None, None),
        ("print", None, "acc", None),
    ]
    out = licm(ir)
    pos_pq = out.index(("mul", "t2", "p", "q"))
    pos_outer = out.index(("label", "Louter", None, None))
    pos_pqi = out.index(("add", "t3", "t2", "i"))
    pos_inner = out.index(("label", "Linner", None, None))
    assert pos_pq < pos_outer                              # p*q 提到最外层之前
    assert pos_outer < pos_pqi < pos_inner                 # p*q+i 落在两层标签之间
    assert VM().run(ir) == VM().run(out) == [122]


def test_licm_does_not_mutate_input():
    ir = [
        ("copy", "k", 3, None),
        ("copy", "n", 4, None),
        ("copy", "i", 0, None),
        ("label", "L0", None, None),
        ("lt", "t0", "i", "n"),
        ("jump_if_false", "L1", "t0", None),
        ("mul", "t1", "k", "n"),
        ("add", "t2", "i", 1),
        ("copy", "i", "t2", None),
        ("jump", "L0", None, None),
        ("label", "L1", None, None),
    ]
    snapshot = list(ir)
    licm(ir)
    assert ir == snapshot


# ==================================================================
# registry
# ==================================================================

def test_apply_passes_chains_const_fold_into_dce():
    """核心串联测试：const_fold 制造出的死代码，随后的 dce 要能清掉。

    `t0 = 2 * 3` 折叠成 `t0 = 6` 之后，t0 仍然被 `x = t0` 读着；但 x 自己
    没人读，于是 x 死 → t0 也死 → 两条一起没了，只剩 print。
    """
    ir = [
        ("mul", "t0", 2, 3),
        ("copy", "x", "t0", None),
        ("print", None, "y", None),
    ]
    assert apply_passes(["const_fold", "dce"], ir) == [("print", None, "y", None)]


def test_apply_passes_is_ordered():
    """顺序是有意义的：单独跑 const_fold 不会删任何指令。"""
    ir = [
        ("mul", "t0", 2, 3),
        ("copy", "x", "t0", None),
        ("print", None, "y", None),
    ]
    assert apply_passes(["const_fold"], ir) == [
        ("copy", "t0", 6, None),
        ("copy", "x", "t0", None),
        ("print", None, "y", None),
    ]
    assert apply_passes([], ir) == ir            # 空流水线 = 恒等变换


def test_apply_passes_rejects_unknown_pass():
    """没注册的名字要清楚报错，不能静默跳过。"""
    try:
        apply_passes(["const_fold", "no_such_pass"], [("print", None, "x", None)])
    except UnknownPassError as e:
        assert "no_such_pass" in str(e)          # 报错要指明是哪个名字
        assert "const_fold" in str(e)            # 并列出已注册的
    else:
        raise AssertionError("未注册的 pass 名字应该报错")


def test_apply_passes_does_not_mutate_input():
    ir = [("mul", "t0", 2, 3), ("print", None, "y", None)]
    snapshot = list(ir)
    apply_passes(["const_fold", "dce"], ir)
    assert ir == snapshot


# ==================================================================
# 不装 pytest 也能跑
# ==================================================================

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
