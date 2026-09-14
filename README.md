# 大模型智能体驱动的新语言编译与优化系统

## 项目目标

做一个"会设计、会优化、会测试"的新语言编译系统。核心不是传统编译器，而是**用 LLM + Agent 驱动编译系统的设计、优化与测试闭环**。

一句话理解当前已经落地的链路：

> 人工实现并固定小语言、AST / IR 和编译工具链 → LLM 阅读源码与 baseline IR、提出
> Pass 组合 → Agent 编译、测试、评估并反馈 → 跟 baseline 和 Oracle 对比收益。

项目设想包含“造语言”和“用语言 + 优化”两部分；当前仓库已经实现的是人工构建的
可信语言地基，以及 LLM 参与的优化闭环和对比实验。LLM 生成整门语言仍是未实现的
扩展方向，不属于当前结项范围。

系统角色分工一句话：**LLM 负责"想"，Agent 负责"管"，工具链负责"真跑"。**

> **核心认知（避免走偏）：这个项目的价值不是"造一门能力很强的语言"，而是"Agent 能不能自动在 IR 上做闭环优化，并用真实 benchmark 证明收益"。**
>
> 语言只是一个**足够小、足够可控的实验场**。真正被优化、被比较、被证明有收益的，是"同一个程序、同一套 IR，优化做得好不好"。正因如此，**语言能力（IR）要固定下来当作实验的锚点**——只有锁死"语言能力"这个变量，才能干净地测量"优化"这个变量。把这个项目理解成"造语言"会觉得没意义；理解成"用自造小语言当实验台，研究 LLM+Agent 能否自动优化代码"，意义才立得住。这正是标题里"编译系统与**优化系统**"那个"优化"二字的分量。

---

## 系统架构

```
输入：固定样例源码 / baseline IR / 优化约束
        │
   ┌────┴─────┐     ┌──────────┐     ┌──────────────┐
   │  LLM 层  │ →   │ Agent 层 │ →   │  工具链层    │
   │ 读取IR   │     │ Planner  │     │ Build/Run    │
   │ Pass候选 │     │ Optimizer│     │ Bench/Save   │
   └──────────┘     │ Executor │     └──────────────┘
                    │ Evaluator│
                    └──────────┘
        │
   候选方案 → 编译运行 → 测试评估 → 保留最优 / 失败回传
```

---

## 目录结构

```
newlang-agent/
├── lang/                      # A组：语言与前端（采用 Lark，见下方说明）
│   ├── grammar.lark           # 文法定义（Lark 直接执行，非纯文档）
│   ├── ast_nodes.py           # AST 节点定义（dataclass，很短）
│   ├── transformer.py         # Lark 解析树 → 自定义 AST（机械映射，替代手写 parser）
│   ├── ir.py                  # AST → 三地址码 IR（★ 优化的地基，要动脑）
│   ├── vm.py                  # 三地址码解释器（含指令计数，运行时间/指令数靠它）
│   └── samples/               # 6 个样例程序（正式矩阵使用其中固定 5 个）
│
├── optimizer/                 # 优化 passes（基线故意不做这些）
│   ├── const_fold.py          # 常量折叠
│   ├── dce.py                 # 死代码消除
│   ├── licm.py                # 循环不变量外提
│   └── registry.py            # pass 注册表，Agent 按名字组合
│
├── llm/                       # B组：LLM 封装
│   ├── client.py              # 统一调用入口，强制 JSON 输出（DeepSeek，走 OpenAI 兼容 SDK）
│   └── prompts/               # 当前已落地的 Prompt 模板
│       └── optimize.txt       # 优化候选生成
│
├── agents/                    # C组：多智能体
│   ├── base.py                # Agent 基类
│   ├── planner.py
│   ├── optimizer_agent.py
│   ├── executor.py
│   ├── evaluator.py
│   └── orchestrator.py        # 编排循环（核心）
│
├── tools/                     # 工具链（Agent 唯一能"动手"的地方）
│   ├── registry.py            # Tool Router
│   ├── build.py               # build(): 源码 → 字节码
│   ├── run.py                 # run_tests(): 执行 + 对结果
│   ├── bench.py               # run_bench(): 指令数 + 计时 + 峰值 Python 内存
│   └── save.py                # save_result(): 落盘
│
├── benchmark/                 # D组：对比实验
│   ├── configs.py             # 阶段四固定样例与四档 + Oracle 实验协议
│   ├── schema.py              # 阶段四矩阵实验的统一记录格式
│   ├── matrix.py              # 四档 + Oracle、多 trial 统一实验入口
│   ├── report.py              # schema v2 JSON → 确定性 Markdown 报告
│   └── runner.py              # 跑 baseline 与穷举优化档的可复现对比
│
├── runs/                      # 所有实验产物（日志 / 结果 / JSON），按时间戳
└── main.py                    # 入口
```

上面只列出当前已落地的目录和文件。目录结构直接对应四组分工（A/B/C/D），
每个文件夹就是一个组的交付边界。四档配置、统一数据契约、矩阵 runner 和报告
生成器均已落地；正式 DeepSeek 多 trial 数据与最终报告文件将在 P4-6 生成。

---

## lang 目录设计决策（前端）

### 为什么用 Lark，而不是手写 lexer/parser

前端（词法 + 语法）不是本项目的核心卖点，核心是上层的"LLM + Agent 优化闭环"。手写 lexer/parser 最容易出 bug、对本项目又最没价值，因此**用 Lark 直接吃 EBNF 文法生成 parser**，把精力省给 ir/vm 和 Agent 闭环。

用 Lark 还有一个契合方案的好处：**grammar 文件从"文档"变成"真被执行的东西"**。手写 parser 时，`grammar.ebnf` 只是给人看的说明，LLM 改了它 parser 不会变；用 Lark 时，LLM 生成/修改 `grammar.lark` → 直接喂给 Lark → parser 立刻变。案例 A 那条"LLM 设计语言"的闭环才真正闭上。

Lark 纯 Python、`pip install lark` 即可，无 Java 依赖（比 ANTLR 友好）。若担心零依赖，PLY 或纯手写也行，代价是失去"grammar 即 parser"这个好处。**注意：Lark 是外部依赖，最终运行环境需能安装。**

### Lark 三个核心概念（一次搞懂）

1. **写文法（grammar.lark）**：声明式描述语言，每条规则用 `-> 名字` 起别名。
2. **Lark 自动出解析树**：`Lark(grammar).parse(源码)` 两行搞定词法+语法，替代手写 lexer/parser。
3. **Transformer 翻译成自定义 AST（transformer.py）**：文法里每个 `-> 名字` 对应一个同名方法，Lark **自底向上**调用（叶子先处理，返回值自动喂给上层），把 Lark 的框架化解析树翻译成自己干净、类型正确的 AST。

> Transformer 的定位：它是**机械映射**，照着 grammar 和 AST 定义做对应，几乎无设计含量。它被 grammar 和 AST 决定，自己没有独立设计空间。

### IR 设计原则（★ 最该花心思的地方）

IR 是整个项目里**最稳定的一层**，也是优化能施展的地基。设计要点：

- **要低层、通用，而不是高层、专用。** 反例：把矩阵运算做成一条 `MATMUL` 黑盒指令——那样"快不快"取决于 vm 里的库实现，Agent 无从优化，优化空间被藏进 vm。正解：矩阵乘法在编译期**展开成三重循环 + 标量指令**，变成一大片可被 LICM / 循环变换 / 常量折叠优化的 IR。
- **用三地址码，不用栈式字节码。** 栈式 IR 的中间值没有名字（只是"栈上某个位置"），写优化 pass 时要在隐式栈数据流里反推"这个 ADD 吃的是哪两个值、结果又流向谁"。三地址码给每个中间值一个显式名字（t0/t1/…），数据流直接写在指令里：常量折叠只需看 src 槽是不是字面量，DCE 只需看 dst 之后有没有被读，LICM 只需看 src 是不是循环不变量——全是局部判断。**IR 服务于优化，这就是选它的唯一理由。**
- **刻意不做**：SSA / phi、完整 CFG / 支配树、寄存器分配。控制流只用"标签 + 跳转"的线性指令序列。够 pass 用即可。
- **必须有控制流和数组访问**，否则 optimizer 目录里的 pass（尤其 licm）没有用武之地：

```
稳定地基（指令统一是定长 4 元组 (op, dst, src1, src2)，空槽填 None）：
  copy                              变量赋值
  add / sub / mul / div             标量算术
  lt / gt / le / ge / eq / ne       比较（结果 1/0）
  print
  label / jump / jump_if_false      控制流 ← 有它才有循环，有循环才有优化空间
  newarray / load_idx / store_idx   数组按下标读写 ← 让矩阵能展开成循环
```

src 槽里 `int` 是字面量常量、`str` 是变量名；跳转类指令把 label 放在 dst 槽，于是"dst = 不被读的槽、src = 被读的槽"这条规律对所有指令成立——`ir.uses()` / `ir.defs()` 两个辅助函数就是靠它统一实现的，所有数据流类 pass 都直接复用。

- **矩阵/卷积是"负载"，不是"指令"。** 它们放进 `samples/` 当计算密集的试金石负载，靠编译器降解成循环 IR。选它们是因为计算量大、优化收益直观（对照案例 B 的 Baseline:100 / 候选B:78）；太简单的负载（如 `1+2+3`）优化前后都是噪声，看不出收益。

### 分层：什么在变，什么稳定

```
grammar        →  变得最频繁（表面语法、关键字）
transformer    →  跟着 grammar 变，但机械（加规则加方法）
AST 节点        →  只在"能力"变化时才加
IR 指令集       →  只在"能力"变化时才加  ← 最稳定，先定 IR 再定语言
VM             →  跟着 IR 指令集变
```

- 表面语法变（`let` vs `var`、`print` vs `show`）：只动 grammar + transformer，IR/VM 不动。
- 计算能力变（新增矩阵、循环、函数）：才需往下传导到 AST/IR/VM，这是"真扩展"，需人介入（案例 A 里"学生检查 AST/IR 是否好实现"就是查这个）。
- 实操建议：**先定 IR（vm 支持哪些底层操作），再定语言**。语言表面随便设计，transformer 负责把任何表面语法都翻译到这套固定 IR。

### LLM 在 lang 目录的边界

| 环节 | 阶段一（现在） | 阶段二以后 |
|------|--------------|-----------|
| grammar / AST / IR | **人手写**（可信地基，验证一切） | LLM 出草案（案例 A），人审查修订 |
| transformer | **人手写** | 可作为"LLM 生成 grammar+AST"的**附带产物**一起生成 |

- 阶段一一切手写，原因：transformer/ir/vm 是验证链路的可信地基，若地基是未验证的 LLM 产物，出错时分不清是谁的锅。
- transformer **不是 LLM 的独立主战场**——它没有设计含量、也不在优化闭环里，永远是配角，不值得单独投入让 LLM"设计"。LLM 在本项目的主场是**设计草案**（案例 A）和**优化候选**（案例 B）。

### 阶段一起步顺序（务实）

1. 先定一个能算出数的最小程序，如 `let x = 1 + 2 * 3; print x;`，目标越小越好。
2. grammar.lark 只写这个子集，够 transformer 对齐即可。
3. 按链路逐个实现并单独验证：Lark 解析出树 → transformer 建 AST（打印看结构）→ ir 生成字节码（打印）→ vm 执行 + 计数。
4. 写 2~3 个 samples，每个配 expected，手动对答案。
5. **完全不碰 optimizer**——基线 build 故意生成朴素字节码、不做优化，这样阶段三对比表才有收益空间。

---

## 关键模块设计

### 1. 数据契约（最重要）

Agent 之间不传自然语言，只传结构化对象。定义一个贯穿全程的 `Candidate`：

```python
@dataclass
class Candidate:
    id: str
    source_program: str       # 哪个样例程序
    passes: list[str]         # 应用了哪些优化 pass，如 ["const_fold","dce"]
    origin: str               # "baseline" / "llm" / "agent"
    # 执行后填充：
    compiled: bool = False
    correct: bool = False     # 功能是否通过
    exec_time_ms: float = None
    peak_memory_kb: float = None
    instr_count: int = None
    error: str = None
```

所有 Agent 的输入输出都围绕这个对象转，日志就是一堆 Candidate 的 JSON，调试和复现都简单。**实现见顶层 `contracts.py`**——它不属于任何子包，是 agents/tools/benchmark 之间的共享契约，放顶层谁都能 import 且不产生循环依赖。

### 2. Agent 基类：统一"输入 → 处理 → 产物"三段式

```python
class BaseAgent:
    def __init__(self, llm=None, tools=None):
        self.llm = llm
        self.tools = tools

    def run(self, context: dict) -> dict:
        raise NotImplementedError
```

`context` 是一个共享字典，在编排循环里逐 Agent 传递、逐步填充。

### 3. 四个 Agent，各自只做一件事

| Agent | 输入 | 输出 | 职责 |
|-------|------|------|------|
| **Planner** | 需求 / 约束 | 步骤计划 | 决定跑哪些样例、每个跑几轮、用哪些 pass 组合当候选（最小版可为固定流程，不一定真调 LLM） |
| **OptimizerAgent** | 程序 + IR | 候选列表 | 调 `optimize.txt`，让 LLM 产出优化候选（pass 组合或参数），输出一批未执行的 Candidate |
| **Executor** | 候选 + 工具 | 日志 + 结果 | 唯一碰工具链的 Agent，依次调 `build → run_tests → run_bench` 回填结果，不判断好坏 |
| **Evaluator** | 日志 + 指标 | 排名 + 结论 | 过滤 `correct=False`，按指标排序选最优，把"失败原因 + 下一轮建议"回传给 Planner |

### 4. 编排循环（系统的心脏）

```python
def orchestrate(program, max_rounds=3):
    context = {"program": program, "history": [], "best": None}
    planner, opt, exe, eva = Planner(), OptimizerAgent(llm), Executor(tools), Evaluator()

    for round in range(max_rounds):
        plan = planner.run(context)                    # 决定这轮做什么
        candidates = opt.run({**context, **plan})      # LLM 生成候选
        results = exe.run({"candidates": candidates})  # 真实编译 + 测试 + bench
        verdict = eva.run({"results": results})        # 过正确性 → 排序 → 选最优

        context["history"].append(verdict)
        if verdict["best"] and better(verdict["best"], context["best"]):
            context["best"] = verdict["best"]
        if verdict.get("converged"):                   # 没有更优了就停
            break
    return context["best"], context["history"]
```

原有 `orchestrate()` 保持简洁的 `(best, history)` 返回值；阶段四新增的
`orchestrate_detailed()` 在同一条编排链上额外返回停止原因、实际轮数、执行候选数、
逐轮 LLM usage、token/调用耗时汇总和 baseline 保底标记。LLM client 保持
`complete_json() -> dict` 接口不变，并通过 `usage_events` / `drain_usage()`
为每个实验 trial 提供隔离的调用记录。`DeepSeekClient` 使用
`deepseek-v4-flash`，针对这个结构化候选任务默认关闭 thinking；可传
`thinking=True` 显式启用，或传 `thinking=None` 沿用服务端默认行为。

### 5. 工具链：Agent 与"真实执行"之间的唯一通道

每个工具统一签名 `(input_dict) -> output_dict`，`tools/registry.py` 里的 Tool Router 按名字分发（`call_tool(name, inp)`，名字没注册就抛 `UnknownToolError`）。当前共实现四个工具：

```python
def build(inp):       # {"source": str, "passes": list[str]}
                      #   -> {"ok": bool, "bytecode": [...]|None, "error": str}
def run_tests(inp):   # {"bytecode", "expected"}
                      #   -> {"correct": bool, "output": ..., "error": str}
def run_bench(inp):   # {"bytecode", "repeat"?: int}
                      #   -> {"instr_count", "time_ms", "peak_memory_kb", "error"}
def save_result(inp): # {"data": dict, "name"?: str}
                      #   -> {"ok": bool, "path": str, "error": str}   # 落盘到 runs/<时间戳>_<name>.json
```

工具层的三条纪律：**① 统一 dict 进 / dict 出**（两头都能直接 `json.dump` 进 `runs/`，一次调用即一条可复现记录）；**② 内部不许崩**——编译错、运行错都 catch 住、如实填进 `error` 字段，不让异常冒泡；**③ 只报事实、不做判断**（编译成没成、结果对不对、跑了多少指令），好坏排序留给 Evaluator。工具之间互不调用，串联由 Executor 负责。

关于 `build` 的编排：源码 →（Lark + transformer）→ AST →（ir）→ 原始 IR → `apply_passes(passes, 原始IR)` → 优化后 IR（即 `bytecode`）。**`apply_passes` 是唯一做优化的地方，`build` 自身一行优化逻辑都没有。** `passes=[]` 就是 baseline：baseline 和优化档共用这同一条路径，唯一差别是 `passes` 列表——不给 baseline 开小灶，两边才干净可比。

关于 `run_bench` 的三个指标：`instr_count` 是**确定性的**（同一段 IR 恒定，label 不计），
是优化收益的**主要对比信号**、也是唯一能写进断言的那个；`time_ms` 会抖
（GC / 调度 / 缓存），**仅作参考**；`peak_memory_kb` 由 `tracemalloc` 在独立的
VM 执行中测量，同样只作参考。Evaluator 仍然只按正确性和指令数排名。

> **关键点：基线版本的 `build`（`passes=[]`）生成朴素字节码，不做任何优化。** 基线越朴素，优化档的收益越明显，对比表才有内容。

### 6. Benchmark Runner：生成对比矩阵

第三周的最小可复现实验已经实现：固定运行原有 5 个样例和新增的
`dead_code`，对每个程序比较 baseline 与当前全部 pass 排列中的最优结果。
每个候选先通过正确性检查，再按动态指令数选择最优；完整候选与环境信息会保存到
`runs/*_benchmark.json`。

```bash
python -m benchmark.runner --repeat 5
```

当前结果：

| 程序 | baseline 指令数 | 优化后指令数 | 减少 | 收益 | 最优 Pass |
|---|---:|---:|---:|---:|---|
| `basic` | 11 | 11 | 0 | 0.00% | `const_fold` |
| `branch` | 16 | 16 | 0 | 0.00% | `const_fold` |
| `loop_sum` | 76 | 76 | 0 | 0.00% | `const_fold` |
| `array_dot` | 158 | 158 | 0 | 0.00% | `const_fold` |
| `licm_demo` | 807 | 708 | 99 | 12.27% | `licm` |
| `dead_code` | 8 | 6 | 2 | 25.00% | `dce` |

六个程序的 baseline 与最优候选全部通过正确性测试，其中两个程序获得严格收益，
达到阶段三“至少证明 1~2 个程序在正确性不变前提下获得明确收益”的最低标准。

阶段四的统一矩阵 runner 也已经实现。快速验证 baseline + Oracle 不需要 API key：

```bash
python -m benchmark.matrix \
  --samples licm_demo dead_code \
  --configs baseline oracle \
  --trials 1 \
  --bench-repeat 1 \
  --no-save
```

不指定 `--samples` / `--configs` 时运行固定 5 个正式样例与四档系统 + Oracle。
真实 LLM 档使用 DeepSeek；完整正式实验留到 P4-6 执行。每条 schema v2 记录保留
trial、候选明细、轮次历史、LLM usage、提案最佳与 baseline 保底后的最终选择。

已有矩阵 JSON 后，可完全离线、确定性地生成 Markdown 报告：

```bash
python -m benchmark.report \
  runs/final_matrix.json \
  --output docs/final_report.md \
  --strict
```

报告对多 trial 指标取中位数，对 LLM 调用与 token 取总量；缺失指标显示 `—`。
Agent 搜索质量使用 `proposed_best`，系统性能使用含 baseline 保底的 `selected_best`，
避免把保底结果误报为 Agent 自己找到的优化。

P4-5 的配置、指标、错误路径、报告和离线端到端测试均不访问真实 LLM：

```bash
.venv/bin/python -m pytest -q
```

当前全量回归为 160 项通过；测试运行前后不会在 `runs/` 留下临时文件。

- `baseline`：不应用 Pass、不调用 LLM，是所有对比的锚点
- `llm_only`：只调用一次 LLM、只执行一个 LLM 候选，不迭代
- `agent_min`：单轮生成并实测最多三个候选，由 Evaluator 自动选优
- `agent_full`：每轮最多三个候选、最多三轮，将 Evaluator 反馈传入下一轮
- `oracle`：穷举当前 16 种 Pass 配置，只作为理论最优参考线，不算第五个系统档

阶段四正式矩阵固定使用 `branch / loop_sum / array_dot / licm_demo / dead_code`
五个程序；`basic` 保留为快速编译链冒烟样例。配置的单一事实源见
`benchmark/configs.py`，矩阵 JSON 契约见 `benchmark/schema.py`。

---

## 评测设计

新语言没有外部 benchmark，因此对比本质是"**自己跟自己比**"，但被结构化成一张有说服力的对照矩阵。

**对比矩阵：同一批固定样例程序 × 四档系统。**

| 指标 | baseline | llm_only | agent_min | agent_full |
|------|----------|----------|-----------|------------|
| 正确性 | ✓ | | | |
| 运行时间 | | | | |
| 指令数 | | | | |
| 内存占用 | | | | |
| 迭代轮数 | | | | |
| token 开销 | | | | |

**收益 = 优化档相对基线快了多少 / 省了多少。**

铁律：**先过正确性，再比性能。** 候选再快，功能测试不通过一律作废。

评测三要素：

1. **固定样例程序集**（3~5 个）——一旦定下就不动，保证可复现。
2. **优化前 vs 优化后的自身对比**——同一程序基线跑一遍、闭环优化后再跑一遍，差值即收益。
3. **功能正确性门槛**——所有对比都建立在结果正确的前提上。

---

## 分阶段推进

每个阶段都有可交付产物，任一阶段停下都有能跑的东西。

| 阶段 | 涉及模块 | 成功标准 |
|------|----------|----------|
| **阶段一** 最小语言 + 最小编译链 | `lang/`（grammar.lark + transformer + ir + vm）+ `optimizer/`（const_fold + dce + **licm** + registry）+ `tools/`（build/run/bench/save + Tool Router）✅ | 至少一组样例程序能从源码走到 AST/IR 并跑出结果；工具链端到端可复现（见 `tests/test_tools.py`） |
| **阶段二** 接入 LLM 与最小 Agent 闭环 | `contracts.py` + `llm/`（DeepSeek）+ `agents/`（base/planner/optimizer_agent/executor/evaluator/orchestrator 全五个）✅ | 跑通"生成候选 → 运行测试 → 输出结果"最小闭环；**已达成并超出**：做到多轮迭代 + 反馈回传 + 自动收敛 + 落盘（licm_demo 2 轮收敛，最优 `[licm]` 708 vs 基线 807） |
| **阶段三** 形成优化闭环，进入对比实验 | `optimizer/` + `benchmark/` | 至少证明 1~2 个程序在正确性不变前提下获得明确收益 |
| **阶段四** 补齐测试与报告 | `benchmark/report.py` + `runs/` | 统一报告模板 + 可复现实验脚本 |

> 如果时间紧，只做前 3 个阶段也可以；但至少要有一个能运行的对比实验。

---

## 小组分工

| 组别 | 负责 | 交付产物 |
|------|------|----------|
| **A 组** 语言与前端 | grammar.lark、transformer、样例程序 | grammar.lark、AST/IR 定义、transformer、样例集 |
| **B 组** LLM 封装与优化候选 | DeepSeek 调用封装、优化 Prompt、结构化输出 | `llm/client.py`、`optimize.txt`、结构化输出规范 |
| **C 组** Agent 与工具 | Planner / Executor、工具调用 | Agent 角色表、工具接口、编排循环 |
| **D 组** 测试与报告 | benchmark、对比表、最终报告 | 对比实验表、统一报告模板 |

每组都要有可交付产物：文档、脚本、样例、日志、结果。最后用一个整合周把四组内容接成闭环。

---

## 最终交付清单

- 语言说明 / grammar
- 优化候选 Prompt 模板
- Agent 设计说明
- 工具脚本
- benchmark 结果
- 最终报告

**验收标准：** 能不能跑通、有没有对比实验、能不能说明为什么这样设计。

---
