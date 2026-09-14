# 大模型智能体驱动的新语言编译与优化系统：实验报告

## 1. 项目与实验目标

在固定语言、IR、样例和优化 Pass 的前提下，对 baseline、LLM/Agent 配置与 Oracle 进行可复现比较。正确性是性能比较的前置条件，动态指令数是主指标。

## 2. 实验环境

| 字段 | 值 |
|---|---|
| 生成时间 | 2026-09-14T22:24:31+08:00 |
| Python | 3.11.15 |
| 平台 | Linux-6.6.87.2-microsoft-standard-WSL2-x86_64-with-glibc2.35 |
| Git commit | c0d719c97e6136f418347899b94c2249c0077a89 |
| Git dirty | False |
| 模型 | deepseek-v4-flash |
| temperature | 0.0 |
| max tokens | 1024 |
| bench repeat | 5 |
| trials | 3 |
| 注册 Pass | const_fold, dce, licm |

## 3. 配置定义

| 配置 | 使用 LLM | 每轮候选上限 | 最大轮数 | 反馈 | 定义 |
|---|---|---|---|---|---|
| baseline | 否 | 0 | 0 | 否 | 不应用任何 Pass，不调用 LLM，作为所有对比的锚点。 |
| llm_only | 是 | 1 | 1 | 否 | 只调用一次 LLM 并执行一个候选，不迭代。 |
| agent_min | 是 | 3 | 1 | 否 | 单轮生成最多三个候选，由 Executor 和 Evaluator 实测选优。 |
| agent_full | 是 | 3 | 3 | 是 | 最多运行三轮，将 Evaluator 反馈回传给下一轮 LLM。 |
| oracle | 否 | 16 | 1 | 否 | 穷举当前三个 Pass 的 16 种配置，作为理论最优参考线。 |

## 4. 样例集和覆盖能力

| 样例 | 覆盖能力 | 原始记录数 |
|---|---|---|
| branch | 条件分支 | 15 |
| loop_sum | 标量循环与累加 | 15 |
| array_dot | 数组访问与循环 | 15 |
| licm_demo | 循环不变量外提收益 | 15 |
| dead_code | 死代码消除收益 | 15 |

## 5. 正确性结果

| 配置 | 正确记录 | 记录总数 | 正确率 | 含错误/清洗事件记录 |
|---|---|---|---|---|
| baseline | 15 | 15 | 100.00% | 0 |
| llm_only | 15 | 15 | 100.00% | 0 |
| agent_min | 15 | 15 | 100.00% | 6 |
| agent_full | 15 | 15 | 100.00% | 6 |
| oracle | 15 | 15 | 100.00% | 0 |

## 6. 每程序性能对比（表 A）

| 程序 | 配置 | 正确率 | 指令数（中位数） | 降低比例 | 时间中位数 (ms) | 内存峰值中位数 (KB) | 最优 Pass |
|---|---|---|---|---|---|---|---|
| branch | baseline | 100.00% | 16 | 0.00% | 0.009 | 0.88 | （无） |
| branch | llm_only | 100.00% | 16 | 0.00% | 0.008 | 0.88 | （无） |
| branch | agent_min | 100.00% | 16 | 0.00% | 0.009 | 0.88 | （无） |
| branch | agent_full | 100.00% | 16 | 0.00% | 0.009 | 0.88 | （无） |
| branch | oracle | 100.00% | 16 | 0.00% | 0.009 | 0.88 | （无） |
| loop_sum | baseline | 100.00% | 76 | 0.00% | 0.030 | 0.80 | （无） |
| loop_sum | llm_only | 100.00% | 76 | 0.00% | 0.028 | 0.80 | （无） |
| loop_sum | agent_min | 100.00% | 76 | 0.00% | 0.048 | 0.80 | （无） |
| loop_sum | agent_full | 100.00% | 76 | 0.00% | 0.029 | 0.80 | （无） |
| loop_sum | oracle | 100.00% | 76 | 0.00% | 0.029 | 0.80 | （无） |
| array_dot | baseline | 100.00% | 158 | 0.00% | 0.063 | 1.95 | （无） |
| array_dot | llm_only | 100.00% | 158 | 0.00% | 0.059 | 1.95 | （无） |
| array_dot | agent_min | 100.00% | 158 | 0.00% | 0.069 | 1.95 | （无） |
| array_dot | agent_full | 100.00% | 158 | 0.00% | 0.062 | 1.95 | （无） |
| array_dot | oracle | 100.00% | 158 | 0.00% | 0.062 | 1.95 | （无） |
| licm_demo | baseline | 100.00% | 807 | 0.00% | 0.275 | 0.90 | （无） |
| licm_demo | llm_only | 100.00% | 708 | 12.27% | 0.254 | 0.90 | licm → const_fold → dce |
| licm_demo | agent_min | 100.00% | 708 | 12.27% | 0.315 | 0.90 | licm |
| licm_demo | agent_full | 100.00% | 708 | 12.27% | 0.252 | 0.90 | licm |
| licm_demo | oracle | 100.00% | 708 | 12.27% | 0.290 | 0.90 | licm |
| dead_code | baseline | 100.00% | 8 | 0.00% | 0.004 | 0.83 | （无） |
| dead_code | llm_only | 100.00% | 6 | 25.00% | 0.003 | 0.60 | const_fold → dce |
| dead_code | agent_min | 100.00% | 6 | 25.00% | 0.003 | 0.60 | dce |
| dead_code | agent_full | 100.00% | 6 | 25.00% | 0.003 | 0.60 | dce |
| dead_code | oracle | 100.00% | 6 | 25.00% | 0.003 | 0.60 | dce |

## 7. 相对 baseline 的收益

| 程序 | 配置 | baseline 指令数 | 配置指令数 | 减少指令 | 降低比例 |
|---|---|---|---|---|---|
| branch | baseline | 16 | 16 | 0 | 0.00% |
| branch | llm_only | 16 | 16 | 0 | 0.00% |
| branch | agent_min | 16 | 16 | 0 | 0.00% |
| branch | agent_full | 16 | 16 | 0 | 0.00% |
| branch | oracle | 16 | 16 | 0 | 0.00% |
| loop_sum | baseline | 76 | 76 | 0 | 0.00% |
| loop_sum | llm_only | 76 | 76 | 0 | 0.00% |
| loop_sum | agent_min | 76 | 76 | 0 | 0.00% |
| loop_sum | agent_full | 76 | 76 | 0 | 0.00% |
| loop_sum | oracle | 76 | 76 | 0 | 0.00% |
| array_dot | baseline | 158 | 158 | 0 | 0.00% |
| array_dot | llm_only | 158 | 158 | 0 | 0.00% |
| array_dot | agent_min | 158 | 158 | 0 | 0.00% |
| array_dot | agent_full | 158 | 158 | 0 | 0.00% |
| array_dot | oracle | 158 | 158 | 0 | 0.00% |
| licm_demo | baseline | 807 | 807 | 0 | 0.00% |
| licm_demo | llm_only | 807 | 708 | 99 | 12.27% |
| licm_demo | agent_min | 807 | 708 | 99 | 12.27% |
| licm_demo | agent_full | 807 | 708 | 99 | 12.27% |
| licm_demo | oracle | 807 | 708 | 99 | 12.27% |
| dead_code | baseline | 8 | 8 | 0 | 0.00% |
| dead_code | llm_only | 8 | 6 | 2 | 25.00% |
| dead_code | agent_min | 8 | 6 | 2 | 25.00% |
| dead_code | agent_full | 8 | 6 | 2 | 25.00% |
| dead_code | oracle | 8 | 6 | 2 | 25.00% |

## 8. 运行时间和内存

时间和 Python 峰值分配是辅助指标，不参与候选排名。

| 程序 | 配置 | 时间中位数 (ms) | 内存峰值中位数 (KB) |
|---|---|---|---|
| branch | baseline | 0.009 | 0.88 |
| branch | llm_only | 0.008 | 0.88 |
| branch | agent_min | 0.009 | 0.88 |
| branch | agent_full | 0.009 | 0.88 |
| branch | oracle | 0.009 | 0.88 |
| loop_sum | baseline | 0.030 | 0.80 |
| loop_sum | llm_only | 0.028 | 0.80 |
| loop_sum | agent_min | 0.048 | 0.80 |
| loop_sum | agent_full | 0.029 | 0.80 |
| loop_sum | oracle | 0.029 | 0.80 |
| array_dot | baseline | 0.063 | 1.95 |
| array_dot | llm_only | 0.059 | 1.95 |
| array_dot | agent_min | 0.069 | 1.95 |
| array_dot | agent_full | 0.062 | 1.95 |
| array_dot | oracle | 0.062 | 1.95 |
| licm_demo | baseline | 0.275 | 0.90 |
| licm_demo | llm_only | 0.254 | 0.90 |
| licm_demo | agent_min | 0.315 | 0.90 |
| licm_demo | agent_full | 0.252 | 0.90 |
| licm_demo | oracle | 0.290 | 0.90 |
| dead_code | baseline | 0.004 | 0.83 |
| dead_code | llm_only | 0.003 | 0.60 |
| dead_code | agent_min | 0.003 | 0.60 |
| dead_code | agent_full | 0.003 | 0.60 |
| dead_code | oracle | 0.003 | 0.60 |

## 9. Agent 提案搜索质量（表 B）

本表使用 `proposed_best`，不把 baseline 保底当成 Agent 自己找到的结果。

| 程序 | 配置 | Oracle 指令数 | 提案指令数 | 提案命中率 | 提案 gap | baseline 保底率 |
|---|---|---|---|---|---|---|
| branch | llm_only | 16 | 16 | 100.00% | 0.00% | 100.00% |
| branch | agent_min | 16 | 16 | 100.00% | 0.00% | 100.00% |
| branch | agent_full | 16 | 16 | 100.00% | 0.00% | 100.00% |
| loop_sum | llm_only | 76 | 76 | 100.00% | 0.00% | 100.00% |
| loop_sum | agent_min | 76 | 76 | 100.00% | 0.00% | 100.00% |
| loop_sum | agent_full | 76 | 76 | 100.00% | 0.00% | 100.00% |
| array_dot | llm_only | 158 | 158 | 100.00% | 0.00% | 100.00% |
| array_dot | agent_min | 158 | 158 | 100.00% | 0.00% | 100.00% |
| array_dot | agent_full | 158 | 158 | 100.00% | 0.00% | 100.00% |
| licm_demo | llm_only | 708 | 708 | 100.00% | 0.00% | 0.00% |
| licm_demo | agent_min | 708 | 708 | 100.00% | 0.00% | 33.33% |
| licm_demo | agent_full | 708 | 708 | 100.00% | 0.00% | 0.00% |
| dead_code | llm_only | 6 | 6 | 100.00% | 0.00% | 0.00% |
| dead_code | agent_min | 6 | 6 | 100.00% | 0.00% | 0.00% |
| dead_code | agent_full | 6 | 6 | 100.00% | 0.00% | 0.00% |

## 10. LLM 成本（表 C）

| 配置 | 调用次数 | Prompt tokens | Completion tokens | Total tokens | LLM 耗时合计 (ms) | 实际轮数中位数 |
|---|---|---|---|---|---|---|
| baseline | 0 | 0 | 0 | 0 | 0.000 | 0 |
| llm_only | 15 | 12309 | 831 | 13140 | 25435.312 | 1 |
| agent_min | 15 | — | — | — | 53407.751 | 1 |
| agent_full | 30 | 25485 | 3183 | 28668 | 74095.996 | 2 |
| oracle | 0 | 0 | 0 | 0 | 0.000 | 1 |

## 11. Agent 实际迭代轮数

| 配置 | 轮数中位数 | 最大轮数 | 停止原因 | baseline 保底率 |
|---|---|---|---|---|
| baseline | 0 | 0 | completed=15 | 0.00% |
| llm_only | 1 | 1 | max_rounds=15 | 60.00% |
| agent_min | 1 | 1 | llm_error=1；max_rounds=14 | 66.67% |
| agent_full | 2 | 2 | converged=15 | 60.00% |
| oracle | 1 | 1 | completed=15 | 0.00% |

## 12. 最优 Pass 组合

| 程序 | 配置 | 最常选择 | 各 trial 分布 |
|---|---|---|---|
| branch | baseline | （无） | （无） × 3 |
| branch | llm_only | （无） | （无） × 3 |
| branch | agent_min | （无） | （无） × 3 |
| branch | agent_full | （无） | （无） × 3 |
| branch | oracle | （无） | （无） × 3 |
| loop_sum | baseline | （无） | （无） × 3 |
| loop_sum | llm_only | （无） | （无） × 3 |
| loop_sum | agent_min | （无） | （无） × 3 |
| loop_sum | agent_full | （无） | （无） × 3 |
| loop_sum | oracle | （无） | （无） × 3 |
| array_dot | baseline | （无） | （无） × 3 |
| array_dot | llm_only | （无） | （无） × 3 |
| array_dot | agent_min | （无） | （无） × 3 |
| array_dot | agent_full | （无） | （无） × 3 |
| array_dot | oracle | （无） | （无） × 3 |
| licm_demo | baseline | （无） | （无） × 3 |
| licm_demo | llm_only | licm → const_fold → dce | licm → const_fold → dce × 3 |
| licm_demo | agent_min | licm | licm × 2；（无） × 1 |
| licm_demo | agent_full | licm | licm × 3 |
| licm_demo | oracle | licm | licm × 3 |
| dead_code | baseline | （无） | （无） × 3 |
| dead_code | llm_only | const_fold → dce | const_fold → dce × 3 |
| dead_code | agent_min | dce | dce × 3 |
| dead_code | agent_full | dce | dce × 3 |
| dead_code | oracle | dce | dce × 3 |

## 13. 失败和淘汰原因摘要

| 配置 | 次数 | 原因 |
|---|---|---|
| agent_full | 6 | LLM 候选清洗：{"item": "const_fold", "reason": "duplicate_pass"} |
| agent_full | 5 | LLM 候选清洗：{"item": "dce", "reason": "duplicate_pass"} |
| agent_full | 1 | LLM 候选清洗：{"item": {"passes": ["const_fold", "dce", "const_fold", "dce"], "reason": "反复折叠与清理以暴露更多常量"}, "reason": "duplicate_combination"} |
| agent_full | 2 | LLM 候选清洗：{"item": {"passes": ["const_fold", "dce", "const_fold", "dce"], "reason": "反复折叠与清理，消除分支和中间计算"}, "reason": "duplicate_combination"} |
| agent_full | 2 | LLM 候选清洗：{"item": {"passes": ["const_fold", "dce", "const_fold", "dce"], "reason": "反复折叠和删除，彻底清理常量传播后的死代码"}, "reason": "duplicate_combination"} |
| agent_full | 1 | LLM 候选清洗：{"item": {"passes": ["const_fold", "dce", "const_fold", "dce"], "reason": "反复折叠和删除，确保所有可折叠常量和死代码都被清理"}, "reason": "duplicate_combination"} |
| agent_full | 1 | LLM 候选清洗：{"item": {"passes": ["const_fold", "dce", "const_fold", "dce"], "reason": "反复折叠和清理，直到常量传播与死代码消除达到不动点"}, "reason": "duplicate_combination"} |
| agent_full | 1 | LLM 候选清洗：{"item": {"passes": ["const_fold", "dce", "const_fold"], "reason": "折叠常量后删除死代码，再折叠剩余常量表达式"}, "reason": "duplicate_combination"} |
| agent_min | 1 | DeepSeek 调用失败：APITimeoutError: Request timed out. |
| agent_min | 5 | LLM 候选清洗：{"item": "const_fold", "reason": "duplicate_pass"} |
| agent_min | 2 | LLM 候选清洗：{"item": "dce", "reason": "duplicate_pass"} |
| agent_min | 2 | LLM 候选清洗：{"item": {"passes": ["const_fold", "dce", "const_fold", "dce"], "reason": "反复折叠和清理，直到常量传播与死代码消除达到不动点"}, "reason": "duplicate_combination"} |
| agent_min | 3 | LLM 候选清洗：{"item": {"passes": ["const_fold", "dce", "const_fold"], "reason": "折叠常量后删除死代码，再折叠剩余常量表达式"}, "reason": "duplicate_combination"} |

## 14. 结论

- 共记录 75 个 program/config/trial，正确性通过 75 个（100.00%）。
- `agent_full` 相对 `llm_only`：0 个程序更优、5 个持平、0 个更差；可比较程序 5 个。
- `llm_only` 的系统最终选择命中 Oracle：15/15（100.00%）。
- `agent_min` 的系统最终选择命中 Oracle：14/15（93.33%）。
- `agent_full` 的系统最终选择命中 Oracle：15/15（100.00%）。

## 15. 局限性和未来工作

- 实验只覆盖报告列出的固定样例与已注册 Pass，结论不外推到其他程序。
- 动态指令数是自定义 VM 的主指标，不等同于生产机器码性能。
- 墙钟时间和 `tracemalloc` 峰值受 Python 运行环境影响，仅作为辅助指标。
- LLM 结果只代表报告中的模型、参数和 trial；增加 trial 可进一步评估稳定性。
