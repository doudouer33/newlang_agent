# 第四阶段：项目收尾与最终验收路线图

> 项目：大模型智能体驱动的新语言编译与优化系统
>
> 目标：在不扩张语言和优化器范围的前提下，完成四档对比实验、统一报告、可复现验证和最终文档，使项目达到 README 定义的结项标准。
>
> 用法：严格按 `P4-0` 到 `P4-7` 的顺序执行。每个子阶段通过验收后再进入下一个。

---

## 1. 当前基线

### 1.1 已完成

- [x] 阶段一：语言前端、AST、三地址码 IR、VM、工具链。
- [x] 阶段一：`const_fold`、`dce`、`licm` 三个优化 Pass。
- [x] 阶段二：DeepSeek 封装、OptimizerAgent、Executor、Evaluator、Planner 和多轮编排。
- [x] 阶段三：对 3 个 Pass 的 16 种非重复排列组合进行穷举。
- [x] 阶段三：建立 baseline 与穷举最优结果的对比基准。
- [x] 已有两个严格收益样例：`licm_demo` 和 `dead_code`。
- [x] 已有 `runs/*_benchmark.json` 实验产物。
- [x] 已冻结四档实验配置和统一结果 schema。
- [x] 已采集 LLM 调用次数、token、耗时和成功/失败事件。
- [x] 已采集 VM 峰值内存，并提供详细编排结果。
- [x] 当前全量测试 132 项通过。

### 1.2 当前缺口

- [ ] 尚无 `baseline / llm_only / agent_min / agent_full` 四档完整对比。
- [ ] 尚无 `benchmark/report.py`。
- [ ] 尚无由正式实验 JSON 自动生成的最终报告。

### 1.3 当前已知基准结果

| 程序 | baseline 指令数 | Oracle 指令数 | 收益 | 最优 Pass |
|---|---:|---:|---:|---|
| `basic` | 11 | 11 | 0.00% | 无严格收益 |
| `branch` | 16 | 16 | 0.00% | 无严格收益 |
| `loop_sum` | 76 | 76 | 0.00% | 无严格收益 |
| `array_dot` | 158 | 158 | 0.00% | 无严格收益 |
| `licm_demo` | 807 | 708 | 12.27% | `licm` |
| `dead_code` | 8 | 6 | 25.00% | `dce` |

---

## 2. 收尾范围和锁定决策

### 2.1 本阶段要做

1. 恢复并验证开发环境。
2. 锁定四档实验协议。
3. 补齐性能和 LLM 成本指标。
4. 实现四档矩阵实验。
5. 实现确定性报告生成器。
6. 补齐测试。
7. 执行真实 LLM 正式实验。
8. 完成最终文档和仓库封板。

### 2.2 本阶段不做

- 不新增语言语法、AST 节点、IR 指令或 VM 能力。
- 不新增 `peephole`、copy propagation 或 CSE 等 Pass。
- 不实现“LLM 生成整门语言”的新链路。
- 不新增 `design.txt` 或 `report.txt` Prompt。
- 不让 LLM 撰写或编造最终实验结论。
- 不为了得到更好结果而临时修改样例、Pass 或评估口径。

### 2.3 全程不变的评估原则

1. **先过正确性，再比性能。** `compiled=False` 或 `correct=False` 的候选不得进入性能排名。
2. **动态指令数是主指标。** 优化候选仍按指令数选优。
3. **运行时间是辅助指标。** 取中位数，不用毫秒级噪声改写主结论。
4. **Oracle 只是理论最优参考线。** 不把穷举收益写成 LLM 或 Agent 的收益。
5. **实验协议在 P4-1 结束后冻结。** 后续发现结果不理想也不更改样例和口径。
6. **所有结论都必须可追溯到 JSON 原始记录。**

### 2.4 当前 LLM 链路：已经实现了什么

LLM 部分不是阶段四从零开始实现。当前真实链路是：

```text
.env / 环境变量
    ↓
llm/client.py
    ├── LLMClient             统一抽象接口
    ├── DeepSeekClient        真实 API，OpenAI 兼容 SDK
    ├── StubLLMClient         离线测试替身
    ├── load_prompt()         读取 Prompt 文件
    └── complete_json()       强制返回 JSON 对象
    ↓
llm/prompts/optimize.txt
    ↓
agents/optimizer_agent.py
    ↓
Candidate(passes=..., origin="llm")
```

已有能力：

- [x] 从 `DEEPSEEK_API_KEY` 或 `.env` 读取密钥。
- [x] 使用 OpenAI 兼容 Chat Completions 接口调用 DeepSeek。
- [x] 使用 JSON mode 约束模型输出。
- [x] 对 Markdown 代码围栏和非法 JSON 做解析收口。
- [x] 没有 API key 时仍可构造 client，真正调用时才报错。
- [x] 可用 Stub LLM 在无网络环境测试 Agent。
- [x] 已有一个真正被系统使用的 `optimize.txt` Prompt。

阶段四没有重写这套封装；P4-2 已在它之上增加隔离的调用记录、token、耗时、
停止原因和错误数据，并让结构化请求默认关闭 thinking。

### 2.5 当前 Agent 分工：已经实现了什么

| 模块 | 当前输入 | 当前输出 | 真实职责 |
|---|---|---|---|
| `Planner` | context | `available_passes`、`n` | 当前是确定性规划器，不调用 LLM |
| `OptimizerAgent` | 程序、baseline IR、Pass 列表、上轮反馈 | 未执行 Candidate 列表 | 唯一调用 LLM 生成优化组合的 Agent |
| `Executor` | Candidate 列表 | 回填指标的 Candidate 列表 | 唯一通过 Tool Router 执行 build/test/bench 的 Agent |
| `Evaluator` | 执行结果、历史最优 | 排名、最优、淘汰列表、反馈 | 先过正确性，再按指令数选优 |
| `orchestrate()` | 程序、LLM、轮数和候选数 | 历史最优、每轮历史 | 串联四个 Agent、回传反馈、收敛停止并落盘 |

`Candidate` 是当前 Agent 之间的共享契约，保存程序、Pass 组合、来源、正确性、
指令数、耗时、峰值内存和错误。

### 2.6 当前多轮编排的真实流程

```text
context = {
    program,
    source,
    expected,
    history=[],
    best=None,
    feedback=None,
}

每一轮：
    Planner.run(context)
        ↓ 可用 Pass + 候选数
    OptimizerAgent.run(context + plan)
        ↓ LLM 生成并清洗 Pass 组合
    baseline 锚点 + LLM Candidates
        ↓
    Executor.run()
        ↓ build → run_tests → run_bench
    Evaluator.run()
        ↓ 正确性过滤 → 指令数排名
    写入 history
        ↓
    更新 best 和 feedback
        ↓
    如果本轮没有刷新历史最优，收敛停止
```

这条链现在已经能运行。P4-2 已将过程数据补齐；下一步 P4-3 是把它包装成统一的
四档矩阵实验入口。

### 2.7 LLM 和 Agent 在阶段四的具体缺口

- [x] `DeepSeekClient.complete_json()` 已保留 API usage，可报告 token。
- [x] client 已保存每次 LLM 调用耗时和成功/失败状态。
- [x] `OptimizerAgent` 已结构化记录原始候选数、接受数和清洗拒绝原因。
- [ ] `orchestrate()` 只有通用 `max_rounds` 和 `n_candidates`，还没有映射成四档实验配置。
- [ ] `orchestrate()` 落盘结构没有 config、trial、模型、token、环境和停止原因。
- [ ] `Candidate.origin="agent"` 当前没有在编排中实际使用，不能依靠 origin 生成四档报告。
- [x] LLM 候选全部失败或无收益时，详细编排结果会标明 `used_baseline_fallback=true`。
- [ ] 每轮候选 ID 目前可重复；正式记录需要通过 `run_id + trial + round + candidate` 唯一定位。

---

## 3. 总体实施顺序

| 顺序 | 子阶段 | 核心产物 | 依赖 |
|---:|---|---|---|
| 0 | P4-0 环境与现有基线验收 | 已有 `.venv` 的环境校验和基线验收记录 | 无 |
| 1 | P4-1 实验协议与数据结构（已完成） | `benchmark/configs.py`、`benchmark/schema.py` | P4-0 |
| 2 | P4-2 指标采集（已完成） | LLM telemetry、内存指标、编排元数据 | P4-1 |
| 3 | P4-3 四档矩阵实验 | `benchmark/matrix.py` | P4-1、P4-2 |
| 4 | P4-4 报告生成器 | `benchmark/report.py` | P4-3 |
| 5 | P4-5 完整测试 | 新增测试集 | P4-2、P4-3、P4-4 |
| 6 | P4-6 正式实验 | `runs/final_matrix.json`、`docs/final_report.md` | P4-5 |
| 7 | P4-7 文档和仓库封板 | 最终 README、周报、干净仓库 | P4-6 |

---

## 4. P4-0：环境与现有基线验收

### 4.1 目标

先证明现有代码没有被后续收尾工作的问题干扰。本阶段只处理环境和基线，不修改实验逻辑。

### 4.2 操作步骤

- [x] P4-0.1 确认使用 Python 3。
- [x] P4-0.2 确认并激活项目中已有的 `.venv` 虚拟环境。
- [x] P4-0.3 安装 `requirements.txt`。
- [x] P4-0.4 运行全部现有测试。
- [x] P4-0.5 运行一次不落盘的快速 benchmark。
- [x] P4-0.6 核对两个严格收益样例的指令数。
- [x] P4-0.7 记录 Python 和关键依赖版本。

### 4.3 命令

```bash
test -x .venv/bin/python
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
python -m benchmark.runner --repeat 1 --no-save
python --version
python -m pip freeze
```

### 4.4 预期结果

- 现有测试全部通过。
- 6 个当前样例的 baseline 和优化候选都正确。
- `licm_demo` 的 Oracle 指令数为 708。
- `dead_code` 的 Oracle 指令数为 6。

### 4.5 异常处理

- 如果是缺包或 Python 环境问题，修复环境后重跑。
- 如果是旧测试失败，先修复回归，不进入 P4-1。
- 如果指令数改变，先确认是否存在未预期的代码修改。

### 4.6 完成判定

- [x] 全部旧测试通过。
- [x] 快速 benchmark 通过。
- [x] 已记录环境版本。
- [x] 没有通过修改语言或 Pass 来规避失败。

### 4.7 验收记录（2026-09-14）

```text
Python: 3.11.15
lark: 1.3.1
openai: 2.46.0
pytest: 9.1.1

测试：98 passed in 2.54s
benchmark：6/6 baseline 和 Oracle 候选正确
严格收益：2/6
licm_demo：807 -> 708，减少 99（12.27%）
dead_code：8 -> 6，减少 2（25.00%）
```

P4-0 已完成，下一步进入 P4-1。

---

## 5. P4-1：锁定实验协议与数据结构

### 5.1 目标

把四档实验的差异写成代码中可验证的配置，避免 runner 里散落大量 `if config == ...`。同时定义统一的实验 JSON schema。

### 5.2 新增文件

```text
benchmark/configs.py
benchmark/schema.py
tests/test_configs.py
tests/test_schema.py
```

### 5.3 正式样例集

正式矩阵固定使用 5 个程序：

| 程序 | 保留理由 |
|---|---|
| `branch` | 覆盖分支与比较 |
| `loop_sum` | 覆盖无严格收益的基础循环 |
| `array_dot` | 覆盖数组与多段循环 |
| `licm_demo` | 覆盖 LICM 的严格收益 |
| `dead_code` | 覆盖 DCE 的严格收益 |

`basic` 保留在仓库中，用于快速编译链冒烟测试，不进入正式四档矩阵。

### 5.4 四档配置与 Oracle

| 名称 | LLM 调用 | 每轮候选 | 最大轮数 | 反馈 | 用途 |
|---|---:|---:|---:|:---:|---|
| `baseline` | 0 | 0 | 0 | 否 | 无优化锚点 |
| `llm_only` | 1 | 1 | 1 | 否 | 测量一次 LLM 直接决策 |
| `agent_min` | 1 | 3 | 1 | 否 | 测量单轮多候选和自动评测 |
| `agent_full` | 最多 3 | 每轮 3 | 最多 3 | 是 | 测量多轮反馈和自动收敛 |
| `oracle` | 0 | 16 | 1 | 否 | 穷举理论最优参考线 |

约束：

- `llm_only` 只允许一个候选，避免它与 `agent_min` 的“多候选评估”重叠。
- `agent_min` 使用 Planner、OptimizerAgent、Executor 和 Evaluator，但只跑一轮。
- `agent_full` 使用现有 orchestrator，允许上一轮反馈进入下一轮 Prompt。
- `oracle` 复用当前 `benchmark.runner` 的穷举逻辑。
- 不用 `Candidate.origin` 表示实验档位；实验记录单独保存 `config`。

### 5.5 建议配置结构

```python
@dataclass(frozen=True)
class ExperimentConfig:
    name: str
    use_llm: bool
    n_candidates: int
    max_rounds: int
    use_feedback: bool
    exhaustive: bool = False
```

### 5.6 统一实验记录

每次“程序 × 配置 × trial”至少保存：

```text
run_id
program
config
trial
passes
compiled
correct
output
instr_count
time_ms
peak_memory_kb
rounds
candidate_count
llm_calls
prompt_tokens
completion_tokens
total_tokens
llm_latency_ms
errors
baseline_instr_count
oracle_instr_count
saved_instructions
reduction_percent
oracle_hit
oracle_gap_percent
```

顶层实验对象至少保存：

```text
schema_version
generated_at
experiment
environment
configs
samples
trials
records
summary
```

### 5.7 指标定义

```text
saved_instructions = baseline_instr_count - config_instr_count

reduction_percent =
    saved_instructions / baseline_instr_count * 100

oracle_hit =
    correct and config_instr_count == oracle_instr_count

oracle_gap_percent =
    (config_instr_count - oracle_instr_count) / oracle_instr_count * 100
```

正确性不通过时，收益、Oracle 命中和 Oracle gap 必须为 `null`，不能填 0。

### 5.8 完成判定

- [x] 四档配置和 Oracle 都是显式配置对象。
- [x] 正式样例数固定为 5。
- [x] 每个配置的 LLM 调用次数、候选数和轮数可被测试验证。
- [x] schema 能序列化和反序列化。
- [x] 已为旧版 benchmark JSON 定义兼容或拒绝策略。
- [x] 协议冻结，后续不再根据结果改口径。

### 5.9 验收记录（2026-09-14）

- 新增：`benchmark/configs.py`
- 新增：`benchmark/schema.py`
- 新增：`tests/test_configs.py`
- 新增：`tests/test_schema.py`
- 正式样例：`branch / loop_sum / array_dot / licm_demo / dead_code`
- 系统档位：`baseline / llm_only / agent_min / agent_full`
- 参考档位：`oracle`
- 矩阵 `schema_version=2`
- 旧版阶段三 `schema_version=1`：明确拒绝，不静默转换
- P4-1 新增测试：22 项通过
- 全量回归：120 项通过（2.71s）
- Python compileall：通过
- `git diff --check`：通过

P4-1 已完成，下一步进入 P4-2。

---

## 6. P4-2：补齐指标采集

### 6.1 目标

在不破坏现有接口和测试的前提下，补齐 README 对比表所需的内存、迭代轮数和 token 开销。

### 6.2 修改范围

```text
llm/client.py
agents/orchestrator.py
tools/bench.py
agents/executor.py
contracts.py                  # 只在确实需要候选级字段时修改
tests/test_llm.py
tests/test_orchestrator.py
tests/test_tools.py
```

### 6.3 LLM 接口的改造边界

不改变“输入 Prompt，输出 `dict`”的主接口。不将 OpenAI SDK 的 response 对象直接泄露给 Agent。改造后的边界为：

```text
DeepSeekClient
    ├── complete_json(...) -> dict       # 保持兼容
    ├── usage_events -> list[dict]       # 只读调用事件
    └── drain_usage() -> list[dict]      # 按 trial 取出并清空
```

`drain_usage()` 很重要：四档矩阵会复用或重建 client，每个 trial 必须只汇总自己的调用，不能把上一个程序的 token 累加进来。

### 6.4 LLM telemetry 字段

保持 `complete_json()` 仍返回解析后的 `dict`，避免修改所有 Agent 接口。可在 client 中增加可读取的调用事件列表，例如：

```text
model
temperature
max_tokens
thinking
started_at
latency_ms
prompt_tokens
completion_tokens
reasoning_tokens
total_tokens
finish_reason
success
error_type
error
```

实现要求：

- [x] 每次调用成功或失败都留下事件。
- [x] 从 API `usage` 读取 token；供应商不返回时保存 `null`。
- [x] 记录调用耗时。
- [x] 不记录 API key。
- [x] 不记录请求头。
- [x] Stub LLM 可注入伪造 usage，供离线测试。
- [x] baseline 和 oracle 的配置不调用 LLM。
- [x] 结构化优化请求默认关闭 thinking，避免思考 token 耗尽预算后没有最终 JSON；
  可显式开启或沿用供应商默认值。

### 6.5 OptimizerAgent 需要增加的实验记录

`OptimizerAgent.run()` 保持返回 `candidates`，同时增加不影响旧调用方的元数据：

```python
{
    "candidates": [...],
    "raw_candidate_count": 3,
    "accepted_candidate_count": 2,
    "rejected_items": [
        {"item": ..., "reason": "unknown_pass"}
    ],
    "error": None,
}
```

至少区分：

- 不是对象或数组。
- `passes` 不是数组。
- 包含未注册 Pass。
- 清洗后为空组合。
- 与前面候选重复。
- 超过 `n_candidates` 限制。

这些是实验错误和清洗统计，不改变 Candidate 的执行语义。

### 6.6 编排元数据

`orchestrate()` 现在返回 `(best, history)`。扩展时优先保留这个外部行为，可通过新函数或可选返回对象提供更完整数据。需记录：

- 实际轮数。
- 每轮候选数。
- 每轮通过和淘汰数。
- 历史最优何时刷新。
- 是因为收敛、达到轮数上限，还是 LLM 失败而停止。
- 每轮 LLM 调用事件。

建议新增一个详细结果入口，而不直接破坏旧返回值：

```python
def orchestrate_detailed(...) -> dict:
    return {
        "best": ...,
        "history": ...,
        "stop_reason": ...,
        "rounds": ...,
        "candidate_count": ...,
        "llm_usage": ...,
        "used_baseline_fallback": ...,
    }
```

原有 `orchestrate()` 可调用这个函数，仍只返回 `(best, history)`，保持现有测试和外部调用兼容。

### 6.7 内存指标

在 `run_bench` 返回值中增加：

```text
peak_memory_kb
```

建议使用标准库 `tracemalloc` 量取单次 VM 运行的 Python 峰值分配。内存测量应与时间测量分开，避免 `tracemalloc` 改变计时结果。

约束：

- 内存只是辅助指标，不用于 Evaluator 排名。
- 失败时返回 `None`，不返回 0。
- 原有 `instr_count`、`time_ms` 和 `error` 字段保持兼容。

### 6.8 完成判定

- [x] 旧 Agent 和工具测试仍通过。
- [x] 成功和失败 LLM 调用都能采集 telemetry。
- [x] token 缺失时不会崩溃。
- [x] 每个 trial 只汇总自己的 LLM 调用，不与前一个 trial 串数。
- [x] OptimizerAgent 能记录原始候选数、接受数和清洗拒绝原因。
- [x] 详细编排结果包含停止原因、轮数、候选数和 baseline 保底标记。
- [x] 原有 `orchestrate()` 的 `(best, history)` 返回行为保持兼容。
- [x] `run_bench` 可返回非负内存峰值。
- [x] 指令数仍是 Evaluator 唯一性能排名信号。
- [x] 任何落盘结果中都没有 API key。

### 6.9 验收记录（2026-09-14）

- `DeepSeekClient` 和 `StubLLMClient` 均支持 `usage_events` 与 `drain_usage()`。
- 真实 DeepSeek 最小请求成功：模型 `deepseek-v4-flash`，82 prompt tokens、
  27 completion tokens、109 total tokens，调用耗时 3349.337 ms。
- 真实 Agent 首轮验证发现 V4 默认 thinking 会将 4096 completion tokens 全部用于
  推理并返回空正文；客户端随后改为结构化任务默认禁用 thinking，并记录
  `thinking`、`reasoning_tokens` 与 `finish_reason` 以便诊断。
- 修正后真实单轮 Agent 验证成功：`dead_code` 由 DeepSeek 选择
  `[const_fold, dce]`，正确性通过，动态指令数从 baseline 的 8 降至 6；本轮
  619 prompt tokens、38 completion tokens、657 total tokens，耗时 2062.555 ms，
  未触发 baseline 保底。
- `OptimizerAgent` 已返回 `raw_candidate_count`、`accepted_candidate_count`
  和带原因的 `rejected_items`。
- 新增 `orchestrate_detailed()`；旧 `orchestrate()` 返回接口保持不变。
- 详细编排结果已包含停止原因、轮数、总候选数、LLM 候选数、逐轮 usage、
  usage 汇总和 baseline 保底标记。
- `run_bench` 已在独立 VM 执行中使用 `tracemalloc` 采集
  `peak_memory_kb`，Evaluator 仍只按指令数排名。
- Candidate、Executor 和阶段三 benchmark 已贯通内存字段。
- 全量回归：132 项通过（2.66s）。
- benchmark 回归：6/6 正确，2/6 严格收益。
- Python compileall、`git diff --check` 和密钥模式扫描均通过。

P4-2 已完成，下一步进入 P4-3。

---

## 7. P4-3：实现四档矩阵实验

### 7.1 目标

把现有 Oracle runner 和 Agent 编排能力接到同一个实验入口，对固定样例和固定配置产生统一 JSON。

### 7.2 新增文件

```text
benchmark/matrix.py
tests/test_matrix.py
```

### 7.3 单个程序的执行流程

```text
读取源码和 // expect
    ↓
运行 baseline
    ↓
运行 oracle
    ↓
运行 llm_only
    ↓
运行 agent_min
    ↓
运行 agent_full
    ↓
按正确性过滤
    ↓
计算相对 baseline 的收益
    ↓
计算 Oracle 命中与 gap
    ↓
汇总 trial 并落盘
```

### 7.4 四档与 Oracle 的具体编排方式

为了避免把实验逻辑塞进现有 Agent，由 `benchmark/matrix.py` 担任实验层编排器。建议统一入口：

```python
def run_profile(
    program: str,
    source: str,
    expected: list[int],
    config: ExperimentConfig,
    *,
    trial: int,
    llm=None,
    bench_repeat: int = 5,
) -> dict:
    ...
```

#### `baseline`

```text
Candidate(passes=[], origin="baseline")
    → Executor
    → 正确性 + 指令数 + 时间 + 内存
    → llm_calls=0, rounds=0
```

不构造 DeepSeek client，无 API key 也能运行。

#### `llm_only`

```text
Planner.run() 取得可用 Pass
    → OptimizerAgent(n_candidates=1) 调用 LLM 一次
    → Executor 执行唯一 LLM 候选
    → 与已测 baseline 比较
    → 无反馈、无第二轮
```

记录 LLM 候选本身是否可行。如果系统最终选择 baseline 保底，必须同时记录 `used_baseline_fallback=true`。

#### `agent_min`

```text
Planner.run()
    → OptimizerAgent(n_candidates=3) 调用 LLM 一次
    → baseline 锚点 + 最多 3 个 LLM 候选
    → Executor 统一执行
    → Evaluator 过滤、排名和选优
    → 结束，不回传反馈
```

可复用 `orchestrate_detailed(max_rounds=1, n_candidates=3)`，但记录中要明确它是单轮配置。

#### `agent_full`

```text
orchestrate_detailed(max_rounds=3, n_candidates=3)
    → 第 1 轮：生成、执行、评估
    → Evaluator feedback 写回 context
    → 第 2/3 轮：携带反馈重新生成
    → 未刷新历史最优时提前收敛
    → 输出历史最优和完整轮次记录
```

如果第二轮就收敛，实际轮数记录为 2，不强行跑满 3 轮。

#### `oracle`

```text
pass_combinations()
    → baseline + 15 个非空 Pass 组合
    → 全部 build/test/bench
    → 过滤不正确候选
    → 按指令数、Pass 数量、名称稳定选优
```

Oracle 应复用或提取 `benchmark/runner.py` 现有能力，不复制一套选优逻辑。

### 7.5 Agent 结果与保底结果的区分

每个 LLM/Agent 档位同时保存：

```text
proposed_best              # LLM/Agent 自己提出的最佳可行候选
selected_best              # 包含 baseline 保底后的系统最终选择
used_baseline_fallback     # selected_best 是否回退到 baseline
```

这能防止出现以下误导性结论：LLM 提出了错误或无收益候选，系统因 baseline 保底而没有变慢，报告却宣称“Agent 成功优化”。

### 7.6 重复口径

区分两类“重复”：

- `trials`：完整系统实验重复次数。正式实验建议为 3。
- `bench_repeat`：同一已选候选的 VM 重复运行次数。正式实验建议为 5，时间取中位数。

不要把 `bench_repeat=5` 写成“Agent 实验重复了 5 次”。

### 7.7 CLI 设计

建议支持：

```text
--samples
--configs
--trials
--bench-repeat
--model
--temperature
--no-save
--output
```

快速离线冒烟：

```bash
python3 -m benchmark.matrix \
  --samples licm_demo dead_code \
  --configs baseline oracle \
  --trials 1 \
  --bench-repeat 1 \
  --no-save
```

完整结构测试通过注入 Stub LLM 完成，不在单元测试中访问网络。

### 7.8 异常和失败要求

- 一个配置失败不能终止整场实验。
- 一个样例失败不能阻止其他样例。
- LLM 非法 JSON、空候选、非法 Pass、编译失败和输出错误都必须落到记录中。
- 正确性失败的结果不计算为性能收益。
- 即使没有可行 LLM 候选，baseline 也必须保留为锚点。

### 7.9 环境信息

每场矩阵实验顶层保存：

- Python 版本。
- 操作系统和平台。
- Git commit hash。
- Git 工作区是否 dirty。
- 注册的 Pass 及其顺序。
- 模型名称、temperature 和 max tokens。
- 样例列表。
- 四档配置的完整参数。
- trials 和 bench repeat。

### 7.10 完成判定

- [ ] baseline 和 oracle 可在无 API key 时运行。
- [ ] 四档可通过同一 CLI 运行。
- [ ] `llm_only` 真实只有一次 LLM 调用和一个 LLM 候选。
- [ ] `agent_min` 真实只跑一轮，但可评测多个候选。
- [ ] `agent_full` 能把 Evaluator 反馈传到下一轮并正确记录收敛。
- [ ] LLM/Agent 提案结果与 baseline 保底后的系统结果被分开保存。
- [ ] Stub LLM 可完成全矩阵离线测试。
- [ ] 结果包含 trial 原始记录，而不只是汇总值。
- [ ] 每个配置失败时都有明确错误。
- [ ] 同一输入和 Stub 返回能产生结构相同的 JSON。

---

## 8. P4-4：实现统一报告生成器

### 8.1 目标

从矩阵 JSON 确定性生成 Markdown 报告。报告生成器只进行校验、统计和格式化，不调用 LLM。

### 8.2 新增文件

```text
benchmark/report.py
tests/test_report.py
```

### 8.3 CLI 设计

```bash
python3 -m benchmark.report \
  runs/final_matrix.json \
  --output docs/final_report.md
```

建议支持：

```text
input                         # 必填，矩阵 JSON
--output                      # 可选，不给时输出到 stdout
--title                       # 可选报告标题
--strict                      # schema 不符时直接失败
```

### 8.4 报告固定结构

1. 项目与实验目标。
2. 实验环境。
3. 四档配置定义。
4. 样例集和覆盖能力。
5. 正确性结果。
6. 每个程序的四档指令数对比。
7. 相对 baseline 的收益。
8. 运行时间中位数和内存峰值。
9. Oracle 命中率和 Oracle gap。
10. LLM 调用次数、token 和调用耗时。
11. Agent 实际迭代轮数。
12. 最优 Pass 组合。
13. 失败和淘汰原因摘要。
14. 结论。
15. 局限性和未来工作。

### 8.5 报告表格

至少包含三类表：

#### 表 A：每程序性能对比

```text
程序 | 配置 | 正确率 | 指令数 | 降低比例 | 时间 | 内存 | 最优 Pass
```

#### 表 B：Agent 搜索质量

```text
程序 | 配置 | Oracle 指令数 | Agent 指令数 | 是否命中 | gap
```

#### 表 C：LLM 成本

```text
配置 | 调用次数 | Prompt tokens | Completion tokens | Total tokens | LLM 耗时 | 轮数
```

### 8.6 输出规则

- 缺失的可选指标显示 `—`，不显示 0。
- 百分比固定保留两位小数。
- 时间和内存单位必须写在表头。
- 每个结论必须可从记录计算，不得写入主观推测。
- 如果 `agent_full` 没有优于 `llm_only`，必须如实显示。
- 相同 JSON 必须生成完全相同的报告正文。

### 8.7 完成判定

- [ ] 可从离线 fixture JSON 生成完整 Markdown。
- [ ] 相同输入的报告内容确定。
- [ ] 不依赖 API key 或网络。
- [ ] 无效 JSON 和不兼容 schema 有清晰报错。
- [ ] 表格数据可逐项追溯到输入 JSON。

---

## 9. P4-5：补齐完整测试

### 9.1 目标

使新增的配置、指标、矩阵和报告全部可在无网络、无 API key 环境中验证。

### 9.2 建议测试文件

```text
tests/test_configs.py
tests/test_schema.py
tests/test_metrics.py
tests/test_matrix.py
tests/test_report.py
```

### 9.3 配置测试

- [ ] `baseline` 不调用 LLM。
- [ ] `llm_only` 只调用一次 LLM，只执行一个 LLM 候选。
- [ ] `agent_min` 仅运行一轮，且允许多候选。
- [ ] `agent_full` 能把反馈传入下一轮。
- [ ] `agent_full` 能在收敛时提前停止。
- [ ] `oracle` 不调用 LLM 且穷举 16 种配置。

### 9.4 指标测试

- [ ] Stub LLM 的 token 能正确汇总。
- [ ] LLM usage 缺失时保存 `None`。
- [ ] LLM 异常时仍记录调用次数和耗时。
- [ ] 指令数在多次执行中一致。
- [ ] 时间取中位数。
- [ ] 内存峰值为非负数。
- [ ] 正确性失败时不生成伪收益。

### 9.5 错误路径测试

- [ ] LLM 返回非法 JSON。
- [ ] LLM 返回空候选。
- [ ] LLM 返回未注册 Pass。
- [ ] 候选编译失败。
- [ ] 候选运行时异常。
- [ ] 候选输出与 expected 不同。
- [ ] 某配置失败后其他配置继续运行。
- [ ] 某样例失败后其他样例继续运行。

这些错误用 Stub 和假工具验证即可，不需要为了报告人为伪造真实实验失败。

### 9.6 报告测试

- [ ] 成功记录能生成完整表格。
- [ ] 失败记录能生成失败摘要。
- [ ] 缺失指标显示 `—`。
- [ ] 百分比和中位数计算正确。
- [ ] 报告不将 Oracle 写成 Agent 结果。
- [ ] 相同 fixture 产生相同正文。

### 9.7 端到端测试

用 Stub LLM 运行：

```text
固定样例
  → 四档 + Oracle
  → 统一 JSON
  → Markdown 报告
```

这条测试必须离线、快速、可重复。

### 9.8 验收命令

```bash
python3 -m pytest -q
python3 -m benchmark.runner --repeat 1 --no-save
python3 -m benchmark.matrix \
  --samples licm_demo dead_code \
  --configs baseline oracle \
  --trials 1 \
  --bench-repeat 1 \
  --no-save
```

### 9.9 完成判定

- [ ] 全部旧测试通过。
- [ ] 全部新测试通过。
- [ ] 测试不访问真实 LLM API。
- [ ] 测试不在 `runs/` 留下临时文件。
- [ ] 运行前后 Git 工作区状态一致。

---

## 10. P4-6：执行正式实验

### 10.1 目标

在已冻结的代码、样例和配置上执行真实 DeepSeek 实验，保存原始结果并生成最终报告。

### 10.2 实验前检查

- [ ] 所有测试通过。
- [ ] 工作区没有未预期修改。
- [ ] 模型名称已固定。
- [ ] temperature 已固定为 0 或模型支持的最低值。
- [ ] `DEEPSEEK_API_KEY` 已通过环境变量或 `.env` 提供。
- [ ] `.env` 没有被 Git 跟踪。
- [ ] 正式样例仍是冻结的 5 个。
- [ ] 正式配置参数与 P4-1 一致。

### 10.3 建议正式命令

```bash
source .venv/bin/activate

python3 -m pytest -q

python3 -m benchmark.matrix \
  --samples branch loop_sum array_dot licm_demo dead_code \
  --configs baseline llm_only agent_min agent_full oracle \
  --trials 3 \
  --bench-repeat 5 \
  --temperature 0 \
  --output runs/final_matrix.json

python3 -m benchmark.report \
  runs/final_matrix.json \
  --output docs/final_report.md
```

### 10.4 正式产物

```text
runs/final_matrix.json
docs/final_report.md
```

可以同时保留时间戳原始文件，但 `final_matrix.json` 必须是报告使用的唯一正式输入。

### 10.5 `.gitignore` 处理

当前 `runs/*` 默认被忽略。正式结果需要单独放行，例如：

```gitignore
runs/*
!runs/.gitkeep
!runs/*_benchmark.json
!runs/final_matrix.json
```

不要放开整个 `runs/` 目录，避免把调试记录全部提交。

### 10.6 结果核对

- [ ] baseline 正确率为 100%。
- [ ] Oracle 的 `licm_demo` 和 `dead_code` 结果与阶段三基准一致。
- [ ] 每个 LLM 档都有 3 次 trial 记录。
- [ ] token、调用次数和轮数可相互核对。
- [ ] 每个失败记录都有原因。
- [ ] 报告表格与 JSON 数字一致。
- [ ] 报告没有将无收益写成有收益。

### 10.7 关于可复现性的表述

真实 LLM 服务存在非确定性，所以项目应声明：

- 可复现的是实验脚本、输入、评估口径和报告生成过程。
- 历史 LLM 输出通过原始 JSON 保留，可重新分析和生成报告。
- 重新调用远程模型可能产生不同候选，不承诺逐 token 完全一致。

### 10.8 完成判定

- [ ] `runs/final_matrix.json` 存在且 schema 校验通过。
- [ ] `docs/final_report.md` 由正式 JSON 生成。
- [ ] 报告可在无网络情况下从 JSON 重新生成。
- [ ] 所有正式输入、配置、环境和结果均可追溯。

---

## 11. P4-7：文档与仓库封板

### 11.1 目标

使 README、代码、实验文件和最终报告完全一致，并从一个干净环境验证最终交付链路。

### 11.2 README 最终更新

- [ ] 目录树只包含真实存在的文件。
- [ ] 标记阶段三和阶段四已完成。
- [ ] 增加四档配置的准确定义。
- [ ] 增加环境安装命令。
- [ ] 增加快速冒烟命令。
- [ ] 增加完整矩阵命令。
- [ ] 增加报告生成命令。
- [ ] 用正式实验数据替换阶段性占位表格。
- [ ] 链接 `runs/final_matrix.json` 和 `docs/final_report.md`。
- [ ] 写明已实现范围和未实现范围。

### 11.3 最终报告必须回答的问题

1. 三个优化 Pass 本身能否在保持正确性的同时降低指令数？
2. 单次 LLM 能否选中有收益的 Pass？
3. 单轮多候选 Agent 是否比单次 LLM 更容易找到好方案？
4. 多轮反馈 Agent 是否比单轮 Agent 更好？
5. LLM 和 Agent 的结果距离 Oracle 有多远？
6. 更多候选和多轮反馈增加了多少 token、时间和迭代次数？
7. 哪些程序没有收益，原因是什么？
8. 只有 3 个 Pass 时，Agent 方法的必要性受到哪些限制？

### 11.4 文档产物

```text
README.md
docs/final_report.md
docs/weekly/<阶段四日期>.md
docs/goal/phase4-project-completion-plan.md
```

### 11.5 依赖和命令复现

如果需要严格锁定正式实验依赖，新增：

```text
requirements-lock.txt
```

README 中同时保留：

- `requirements.txt`：日常安装。
- `requirements-lock.txt`：重建正式实验环境。

### 11.6 最终验收命令

```bash
git status --short
python3 -m pytest -q
python3 -m benchmark.runner --repeat 1 --no-save
python3 -m benchmark.report \
  runs/final_matrix.json \
  --output /tmp/newlang-final-report.md
diff -u docs/final_report.md /tmp/newlang-final-report.md
```

如果有条件，再在新 clone 或另一套干净的 Python 环境中执行一遍。当前工作目录始终复用已有 `.venv`，不重新创建。

### 11.7 安全与仓库检查

- [ ] `.env` 未提交。
- [ ] API key 未出现在源码、测试、JSON 和 Markdown 中。
- [ ] `.venv` 未提交。
- [ ] 临时实验日志未提交。
- [ ] 正式实验 JSON 和最终报告已提交。
- [ ] README 不再声称存在实际不存在的模块。

### 11.8 完成判定

- [ ] 全部测试通过。
- [ ] 报告可从正式 JSON 无差异重新生成。
- [ ] README 的每条命令都可复制执行。
- [ ] 所有最终交付物齐全。
- [ ] Git 工作区干净。
- [ ] 项目可标记为“阶段四完成 / 项目结项”。

---

## 12. 建议的分步提交

为了方便回滚和审查，每个子阶段独立提交：

| 子阶段 | 建议 commit 主题 |
|---|---|
| P4-0 | `chore: verify phase 3 baseline environment` |
| P4-1 | `feat: define final experiment configs and schema` |
| P4-2 | `feat: collect benchmark and llm telemetry` |
| P4-3 | `feat: add four-profile benchmark matrix` |
| P4-4 | `feat: generate final benchmark report` |
| P4-5 | `test: cover final experiment and reporting pipeline` |
| P4-6 | `data: add final experiment results and report` |
| P4-7 | `docs: finalize project documentation` |

只有在对应子阶段的“完成判定”全部满足后，才进行该次提交。

---

## 13. 最终交付清单

### 代码

- [x] `benchmark/configs.py`
- [x] `benchmark/schema.py`
- [ ] `benchmark/matrix.py`
- [ ] `benchmark/report.py`
- [x] LLM telemetry 实现
- [x] benchmark 内存指标实现
- [x] orchestrator 实验元数据实现

### 测试

- [x] 配置测试
- [x] schema 测试
- [x] telemetry 测试
- [ ] 矩阵测试
- [ ] 报告测试
- [ ] 错误路径测试
- [ ] 离线端到端测试

### 数据与报告

- [ ] `runs/final_matrix.json`
- [ ] `docs/final_report.md`
- [ ] 阶段四周报

### 文档与复现

- [ ] README 与实际代码对齐
- [ ] 安装命令可执行
- [ ] 快速验证命令可执行
- [ ] 完整实验命令可执行
- [ ] 报告可离线重新生成
- [ ] 正式实验依赖版本可追溯

---

## 14. 项目结项的唯一判定口径

以下条件必须同时满足：

1. 从源码到 AST、IR、VM 和优化结果的链路可运行。
2. baseline、llm_only、agent_min、agent_full 和 Oracle 可通过同一实验入口执行。
3. 所有性能对比都建立在正确性通过的前提上。
4. 指令数、时间、内存、轮数和 token 都有明确记录。
5. Agent 结果可与 baseline 和 Oracle 同时比较。
6. 正式 JSON 可以离线生成同样的最终 Markdown 报告。
7. 全部测试在干净环境通过。
8. README 的目录、命令、数据和实际仓库一致。
9. 正式结果、最终报告和阶段四周报已提交。
10. 仓库中没有 API key 或不应提交的运行产物。

全部满足后，可在 README 中将阶段四标记为完成，并将项目状态改为“已结项”。
