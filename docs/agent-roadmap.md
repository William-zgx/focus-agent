# Focus Agent — Agent 能力侧技术方案

> 本文档聚焦 **agent 本身的智能水平**：规划、记忆、工具使用、自省、评估。
> 工程化议题（CI/CD、CORS、前端状态管理等）见 [architecture.md](architecture.md)。

---

## 一、现状盘点（agent 维度）

源码参照：[graph_builder.py](../src/focus_agent/engine/graph_builder.py)、[default_tools.py](../src/focus_agent/capabilities/default_tools.py)、[state.py](../src/focus_agent/core/state.py)。

| 能力 | 当前实现 | 主要缺口 |
|---|---|---|
| **推理循环** | ReAct 单环：`agent_loop ↔ tool_executor`，最多 2 轮连续工具后强制收尾 | 无显式规划、无 reflection、无 replan |
| **上下文** | `assemble_context` 拼 summary/pinned/constraints/findings/skills + rolling_summary；`ContextBudget` 已有 prompt / tool observation 预算；模型调用前有确定性裁剪 | 语义压缩尚未落地；预算仍使用字符近似 token，而非 tokenizer 精算 |
| **记忆** | 三层命名空间（user/project/root_thread）+ retriever + scorer + dedupe + policy | 写入链路未闭环：`summarize_turn` 只更新 `rolling_summary`；`memory_write_requests` 字段留空；无冲突消解与衰减 |
| **工具** | 18 个内置工具；stream event；workspace 沙箱；SSRF 过滤；按 turn intent 收窄工具集 | 串行执行、无结果缓存、无前置参数校验、失败降级仍是基础兜底 |
| **分支/合并** | `merge_proposal` + `interrupt` HITL | 分支开/合靠人控；agent 不会主动建议 |
| **技能** | 注册表 + active/available block | 激活来自外部 `skill_hints`，agent 不自选 |
| **模型** | `create_chat_model` 多 provider | 不区分 planner/executor/critic；不做成本路由 |
| **评估** | `tests/eval/` smoke 套件、JSON/JSONL/HTML 报告、Eval CI 门禁与回归样本已落地；生产 trajectory schema 已与 eval 提取逻辑对齐 | Postgres trajectory 查询/导出、replay 数据集、线上失败样本采样仍待补齐 |

---

## 二、优化方案（按 agent 能力分层）

### A. 推理架构：Plan–Act–Reflect ✅ 已落地

> 状态：2026-04-19 落地。默认开启，通过 `Settings.plan_act_reflect_enabled` 关闭。

#### 图形态

```
bootstrap → retrieve_memory → assemble_context → plan → agent_loop
                                                          │
                                   ┌──────────────────────┤
                                   ↓                      ↓
                              tool_executor         (无 tool_calls)
                                   │                      │
                                   └─→ agent_loop     reflect
                                                     ╱      ╲
                                                 done       replan
                                                  ↓          ↓
                                            summarize_turn  plan (最多 1 次)
                                                  ↓
                                       maybe_interrupt_for_merge → END
```

代码入口：[graph_builder.py:build_graph](../src/focus_agent/engine/graph_builder.py)。

#### 触发策略（条件触发，不每轮 plan）

纯函数 [`_should_plan`](../src/focus_agent/engine/graph_builder.py)：
- **场景白名单**仅作为*许可*，不单独触发：`Settings.plan_scenes`（默认 `("long_dialog_research", "technical_deep_dive")`）。
- **触发条件**（满足其一即进入 plan 节点）：
  1. `task_brief` 长度 ≥ `plan_task_brief_min_chars`（默认 120）。
  2. scene 在白名单且 `task_brief` 含多步关键词（`然后 / 接着 / 之后 / 并且 / 对比 / 分析 / then / and then / compare / analyze / step by step`）。
  3. 已存在 plan 且 `plan_meta.replan_requested=True`（reflect 触发的重规划）。
- **未触发**时 plan 节点 passthrough，整图退化为原 ReAct 行为——这是保证既有单轮对话零额外成本的关键。

#### Plan 节点

- 模型：复用 `selected_model`（不做模型路由，等 §H 统一处理），`thinking_mode=""`，走 `model_for(...)`（不绑工具）。
- 输入：`task_brief + 工具名白名单（仅 names，不含 schema） + 上一次 reflection.missing`（重规划时）。
- System prompt 要求返回 JSON：
  ```json
  {"steps":[{"id":"s1","goal":"...","expected_tools":["search_code"]}],
   "success_criteria":"客观可判断的验收标准"}
  ```
- 解析失败或 `steps=[]`：记 `plan_meta.plan_skipped=True`，退化为无 plan 路径；不抛错。
- 写入 state：`plan / current_step_id=steps[0].id / reflection=None / plan_meta.plan_calls+=1`。

#### Plan 表示

见 [core/types.py](../src/focus_agent/core/types.py)：

```python
class PlanStep(StateModel):
    id: str                          # "s1", "s2" ...
    goal: str
    expected_tools: list[str] = []   # 建议，非强约束
    done: bool = False
    note: str = ""

class Plan(StateModel):
    steps: list[PlanStep]
    success_criteria: str = ""
    created_at_call: int = 0         # plan 生成时的 llm_calls，陈旧检测用
    replan_count: int = 0            # 硬上限 Settings.plan_max_replans（默认 1）
```

#### Act 节点

保持 `agent_loop` 不变。只在构造 prompt 时，把 `_format_plan_block(plan, current_step_id)` 追加到 system message：

```
## 当前计划
目标验收: ...
- ✓ [s1] 已完成步骤
- ➤ [s2] 当前步骤  (建议工具: search_code)
- • [s3] 待执行
完成当前步骤后，如仍需工具请继续调用；若已可给出最终答复，直接用自然语言回答。
```

保留 `_MAX_CONSECUTIVE_TOOL_CALL_ROUNDS=2` 作为工具轮兜底。

#### Reflect 节点

- 触发：`should_continue_after_act` 路由——last message 无 `tool_calls` 且 `plan` 存在时，走 `reflect` 而非 `summarize_turn`。
- 模型：同 `selected_model`；system prompt 要求返回 `{"status":"done"|"replan","reasoning":"...","missing":[]}`。
- 决策：
  - `status == "done"` 或 `plan.replan_count >= plan_max_replans` → 去 `summarize_turn`。
  - `status == "replan"` 且预算未耗尽 → `plan_meta.replan_requested=True`，回 `plan` 节点；plan 节点再次运行时 `replan_count+=1`。
- 解析失败：默认 `status=done`，绝不陷循环。

#### 上限与退化

- **最多 1 次 replan**：`Settings.plan_max_replans=1`。第二次 reflect 即使 replan 也会被强制改判为 done。
- **全链路 best-effort**：任何解析/调用失败都能退化到无 plan 的 ReAct，主路径不会被阻塞。
- **全局开关**：`Settings.plan_act_reflect_enabled=False` 时，plan/reflect 节点空穿、路由直通 `summarize_turn`。
- **环境变量**：`PLAN_ACT_REFLECT_ENABLED / PLAN_SCENES / PLAN_TASK_BRIEF_MIN_CHARS / PLAN_MAX_REPLANS`。

#### 观测

- `llm_calls` 自动包含 plan/reflect 的调用计数。
- `state.plan_meta`：`{plan_calls, reflect_calls, replan_requested, replanned, plan_skipped, reflect_forced_done}`。
- 评估框架已接入：`EvalCase.expected` 可加 `expected_plan_steps_min / expected_replan`（预留扩展）。

#### 验证

- 单元：`tests/eval/test_plan_act_reflect.py`（14 个用例）覆盖 `_should_plan` 分支、JSON 解析容错、happy path、replan-once、开关关闭。
- 回归：`tests/test_graph_builder.py` 既有用例保持 green——短对话自动退化为 ReAct。

### B. 工具层：并行、缓存、自描述

[graph_builder.py:362-369](../src/focus_agent/engine/graph_builder.py#L362-L369) 的 `tool_executor` 串行 `for` 循环。

1. **并行执行**：`asyncio.gather` 并发 side-effect-free 工具（read_file / search_code / web_fetch）。工具 metadata 加 `side_effect: bool`。
2. **结果缓存**：`(tool_name, args_hash)` thread 级 LRU；分支回放时显著降本。
3. **前置参数校验**：`@tool` 外包一层 pydantic 校验，错误直接产 `ToolMessage(error=...)`，不抛 500。
4. **失败降级**：把 `web_search` 里 Tavily→DuckDuckGo 的 fallback 模式抽成 `@with_fallback(chain=[...])` 装饰器。
5. **Capability card**：按 `task_brief` 关键词在 system prompt 前置高亮 3–5 个最相关工具，避免 18 个 schema 稀释注意力。

### C. 记忆子系统：写入闭环 + 冲突消解

**问题**：[state.py:109](../src/focus_agent/core/state.py#L109) 已留 `memory_write_requests`，`MemoryExtractor / MemoryWriter / MemoryRetriever / MemoryPolicy / MemoryWriteRequest` 也已经成型，但 `build_graph` 目前只有 `retrieve_memory → assemble_context` 读链路，写链路停在 `summarize_turn` 的 `rolling_summary`，没有把 turn 结果沉淀为可检索的长期记忆。

**原则**：
1. **闭环不替代上下文**：短期连续性仍由 `recent_messages` 与 `rolling_summary` 承担；长期记忆只保存跨 turn、跨分支或跨会话仍有价值的事实、偏好、结论与证据索引。
2. **先确定命名空间，再谈抽取**：所有候选必须落到 `RequestContext` 可解释的 user / root_thread / branch / project / skill 命名空间，避免“全局杂物箱”。
3. **写入晚于自省，读取早于规划**：读在 `retrieve_memory`，写在 `summarize_turn` 之后；Plan-Act-Reflect 未完成或仍需 replan 时不污染长期记忆。
4. **失败不阻塞主回答**：参考 Hermes `MemoryManager.sync_turn / queue_prefetch` 的思路，记忆写入是 post-turn 副作用；失败只记录观测，不改变用户已收到的回答。
5. **prompt 注入有边界**：记忆是历史背景，不是新用户输入；渲染时必须带隔离说明、长度预算和内容安全过滤。

**生命周期**：

```text
bootstrap_turn
  → retrieve_memory            # 读取 user/root_thread/branch/project/skill 命名空间
  → assemble_context           # 把 retrieved_memories 作为低优先级背景注入
  → plan → agent_loop ↔ tool_executor
  → reflect? → summarize_turn  # 形成稳定 turn 摘要
  → extract_memories           # 从最终 turn 轨迹提取 MemoryWriteRequest
  → write_memories             # policy + dedupe + conflict resolve + store.put
  → maybe_interrupt_for_merge
```

**第一版只补 `extract_memories / write_memories` 两个图节点**，复用现有 `MemoryExtractor.extract_from_turn()` 和 `MemoryWriter.write_records()`；后续再把抽取从规则增强为小模型。

### D. 上下文工程：token 预算硬约束 + 语义压缩

1. **Token 计费**：`tiktoken`/provider native counter 接入 `assemble_context` 末端；`while tokens > budget: drop_lowest_priority_block()`。优先级：`active_goal > pinned > constraints > summary > findings > available_skills > memory`。
2. **中段语义压缩**：`messages` 超阈值时，非最近 K 条且非工具链尾的中段，用小模型压成 `mid_summary` 替换。
3. **工具结果裁剪**：加 `observe` 节点；超 N 字的 `ToolMessage` 由小模型按 `current_step` 抽相关片段，原文落 `artifacts/` 备查。

### E. Agent 自主性：技能自选 + 分支自主决策

1. **技能自选**：`plan` 节点基于 skill 的 `description/triggers`（BM25 + 语义）产出 `active_skill_ids`，替代 [graph_builder.py:286-290](../src/focus_agent/engine/graph_builder.py#L286-L290) 外部 `skill_hints`。
2. **分支自主建议**：`reflect` 检测到"互斥假设需并行验证"或"子任务高风险"时产 `branch_proposal` 事件；前端提示用户是否开分支（最终决策仍人控）。

### F. 模型分工：planner / executor / critic 路由

- planner：Opus / Sonnet，低温、长上下文。
- executor（带工具）：Sonnet 为主；纯编辑/抽取降 Haiku。
- critic（reflect + extract_memories）：Haiku。

`model_registry.py` 之上新增 `role_router.py`：`create_chat_model_for_role(role, settings)`。
预期：P95 延迟 / 成本降 40–60%，规划质量反升（模型更聚焦）。

### G. 可观测性（agent 视角）

1. **Trajectory Postgres**：每 turn 落 `{thread_id, root_thread_id, branch_id, plan, steps:[{tool,args,obs,dur_ms}], reflection, metrics}` 到应用自有 Postgres 表；不复用 LangGraph 内部 checkpoint/store 表。
2. **指标**：`tool_call_per_turn` / `replan_rate` / `cache_hit_rate` / `fallback_rate` / `parallel_tool_calls` / `budget_overflow_events`。
3. **OpenTelemetry span**：图节点一个 span，tool call 一个 child span；可接 Langfuse / Arize。

### H. 评估框架（详见第四节）

---

## 二之二、各模块详细落地方案

### A. 推理架构：Plan–Act–Reflect（3 天工期）

#### A.1 数据结构扩展

**修改 `src/focus_agent/core/state.py`**：
```python
@dataclass
class PlanStep:
    """规划中的单步任务"""
    index: int
    goal: str                    # e.g. "搜索仓库中 assemble_context 的用途"
    approach: str                # e.g. "用 search_code 工具查找"
    estimated_tools: list[str]   # e.g. ["search_code", "read_file"]
    max_iterations: int = 3

@dataclass
class Reflection:
    """自省节点的输出"""
    status: Literal["done", "continue", "replan", "ask_user"]
    gaps: list[str]             # 未完成的步骤
    next_action: str            # 下一步具体行动
    reasoning: str              # 自省理由
    replan_triggered_by: str | None  # "max_iterations" / "tool_error" / "missing_info"

# 在 AgentState 中追加：
@dataclass
class AgentState:
    # ... 现有字段 ...
    plan: list[PlanStep] | None = None
    current_step_index: int = 0
    reflection: Reflection | None = None
    consecutive_tool_rounds: int = 0
```

#### A.2 LangGraph 节点实现

**新增 `src/focus_agent/engine/planner.py`**：
```python
async def plan_node(state: AgentState, runtime: AppRuntime) -> dict:
    """规划节点：输出任务分解计划"""
    if state.plan is not None and state.task_brief == state._last_plan_task_brief:
        # 复用已有计划
        return {"plan": state.plan}
    
    # 构造规划 prompt：只读上下文，系统 prompt 要求分步输出
    plan_prompt = f"""
    用户需求：{state.task_brief}
    当前的相关记忆/上下文：[...]
    
    分析需求，输出 JSON 格式的分步计划：
    {{
      "steps": [
        {{"goal": "搜索关键信息", "approach": "调用 search_code", "estimated_tools": ["search_code"]}},
        ...
      ],
      "estimated_total_tool_calls": 5,
      "reasoning": "..."
    }}
    """
    
    planner_model = runtime.model_for_role("planner")  # Opus/Sonnet，T=0.2
    response = await planner_model.ainvoke(plan_prompt)
    
    steps = parse_plan_response(response)
    return {
        "plan": steps,
        "_last_plan_task_brief": state.task_brief
    }
```

**修改 `src/focus_agent/engine/graph_builder.py`**：
```python
# 在 build_agent_graph() 中：
graph.add_node("plan", plan_node)
graph.add_node("act", agent_loop)  # 现有节点，稍微改动消费 state.plan[current_step_index]
graph.add_node("reflect", reflect_node)
graph.add_node("finalize", finalize_node)

# 路由逻辑：
graph.add_edge(START, "plan")
graph.add_edge("plan", "act")
graph.add_conditional_edges(
    "act",
    lambda s: "reflect" if s.consecutive_tool_rounds >= N else "act",
    {"reflect": "reflect", "act": "act"}
)
graph.add_conditional_edges(
    "reflect",
    lambda s: {
        "done": "finalize",
        "replan": "plan",
        "ask_user": "interrupt",
        "continue": "act"
    }[s.reflection.status],
    {"done": "finalize", "replan": "plan", "ask_user": "interrupt", "continue": "act"}
)
```

**新增 `src/focus_agent/engine/reflector.py`**：
```python
async def reflect_node(state: AgentState, runtime: AppRuntime) -> dict:
    """自省节点：评估进度，决定下一步"""
    # 小模型（Haiku）自省，成本低
    reflect_prompt = f"""
    任务：{state.task_brief}
    原计划第 {state.current_step_index} 步：{state.plan[state.current_step_index]}
    
    本轮对话历史 (last 10 turns):
    {format_messages(state.messages[-10:])}
    
    工具调用统计：{count_tool_calls(state)}
    
    问题：我是否完成了本步的目标？是否需要重新规划？
    
    JSON 输出：
    {{"status": "done|continue|replan|ask_user", "gaps": [...], "next_action": "...", "reasoning": "..."}}
    """
    
    critic_model = runtime.model_for_role("critic")  # Haiku，T=0
    response = await critic_model.ainvoke(reflect_prompt)
    reflection = parse_reflection_response(response)
    
    # 检测分支建议条件
    branch_proposal = None
    if "并行验证" in reflection.gaps or "互斥假设" in reflection.reasoning:
        branch_proposal = {
            "type": "parallel_branches",
            "reason": reflection.reasoning,
            "suggested_count": 2
        }
    
    return {
        "reflection": reflection,
        "consecutive_tool_rounds": state.consecutive_tool_rounds + 1,
        "branch_proposal": branch_proposal
    }
```

#### A.3 Agent 端点修改

修改 `src/focus_agent/engine/agent_loop` 节点，使其消费 `state.plan[current_step_index]`：
```python
async def agent_loop(...):
    # ... 现有逻辑 ...
    
    # 新增：从计划中提取当前子目标
    if state.plan and state.current_step_index < len(state.plan):
        current_step = state.plan[state.current_step_index]
        # 在 system prompt 中高亮当前子目标
        system_prompt += f"\n当前子目标（plan[{state.current_step_index}]）：{current_step.goal}"
        state.current_step_index += 1
    
    # 保留原有逻辑...
```

#### A.4 测试覆盖

在 `tests/test_agent_planning.py` 中：
```python
def test_plan_node_produces_steps():
    """验证规划节点产出步骤"""
    state = AgentState(task_brief="在仓库中找出使用 assemble_context 的地方")
    result = run_node(state, "plan", runtime)
    assert len(result["plan"]) >= 2
    assert all(hasattr(s, "goal") for s in result["plan"])

def test_reflect_triggers_replan_on_repeated_failure():
    """验证自省节点在反复失败后建议重规划"""
    # ... 构造失败场景 ...
    assert reflection.status == "replan"

def test_plan_act_reflect_full_cycle():
    """完整 Plan-Act-Reflect 循环"""
    # ... 验证从规划到自省的全路径 ...
```

---

### B. 工具层：并行、缓存、自描述（2 天工期）

#### B.1 工具元数据扩展

**修改 `src/focus_agent/capabilities/tool_registry.py`**：
```python
@dataclass
class ToolMetadata:
    """工具的丰富元数据"""
    name: str
    description: str
    side_effect: bool  # 是否修改系统状态（write_artifact: True, search_code: False）
    cacheable: bool    # 是否结果可缓存
    categories: list[str]  # ["read", "write", "analyze", "search"]
    estimated_cost_tokens: int  # 平均消耗 token 数
    estimated_latency_ms: int
    fallback_chain: list[str] | None = None  # e.g. web_search: ["tavily", "duckduckgo"]
```

#### B.2 工具缓存实现

**新增 `src/focus_agent/capabilities/tool_cache.py`**：
```python
from functools import lru_cache
import hashlib
import json

class ToolResultCache:
    """Thread-level LRU 缓存，分支回放时降本"""
    def __init__(self, max_size: int = 256):
        self._cache: dict[str, Any] = {}
        self._access_order = []
        self.max_size = max_size
    
    def key_for_call(self, tool_name: str, args: dict) -> str:
        """生成缓存 key（基于工具名和参数哈希）"""
        args_str = json.dumps(args, sort_keys=True)
        args_hash = hashlib.sha256(args_str.encode()).hexdigest()[:8]
        return f"{tool_name}:{args_hash}"
    
    def get(self, tool_name: str, args: dict) -> Any | None:
        key = self.key_for_call(tool_name, args)
        if key in self._cache:
            self._access_order.remove(key)
            self._access_order.append(key)
            return self._cache[key]
        return None
    
    def put(self, tool_name: str, args: dict, result: Any) -> None:
        key = self.key_for_call(tool_name, args)
        if key in self._cache:
            self._access_order.remove(key)
        self._cache[key] = result
        self._access_order.append(key)
        
        if len(self._cache) > self.max_size:
            lru_key = self._access_order.pop(0)
            del self._cache[lru_key]
```

#### B.3 工具并行执行

**修改 `src/focus_agent/engine/graph_builder.py` 的 `tool_executor`**：
```python
async def tool_executor(state: AgentState, runtime: AppRuntime) -> dict:
    """工具执行：支持并行、缓存、降级"""
    tool_calls = extract_tool_calls(state.messages[-1])
    
    # 分类：有副作用 vs 无副作用
    parallel_tools = []
    sequential_tools = []
    
    for tc in tool_calls:
        tool_meta = runtime.tool_registry.get_metadata(tc.name)
        if tool_meta.side_effect:
            sequential_tools.append(tc)
        else:
            parallel_tools.append(tc)
    
    results = []
    
    # 并行执行无副作用工具
    if parallel_tools:
        tasks = []
        for tc in parallel_tools:
            # 检查缓存
            cached = runtime.tool_cache.get(tc.name, tc.args)
            if cached is not None:
                results.append(ToolMessage(name=tc.name, content=cached))
                continue
            
            task = execute_tool_with_fallback(tc, runtime)
            tasks.append((tc, task))
        
        # 并发执行
        for tc, task in tasks:
            try:
                result = await asyncio.wait_for(task, timeout=30)
                results.append(ToolMessage(name=tc.name, content=result))
                runtime.tool_cache.put(tc.name, tc.args, result)
            except Exception as e:
                results.append(ToolMessage(name=tc.name, error=str(e)))
    
    # 串行执行有副作用工具
    for tc in sequential_tools:
        try:
            result = await execute_tool_single(tc, runtime)
            results.append(ToolMessage(name=tc.name, content=result))
        except Exception as e:
            results.append(ToolMessage(name=tc.name, error=str(e)))
    
    return {"messages": results}

async def execute_tool_with_fallback(tool_call, runtime):
    """执行工具，失败时尝试 fallback"""
    tool_meta = runtime.tool_registry.get_metadata(tool_call.name)
    
    try:
        return await execute_tool_single(tool_call, runtime)
    except Exception as e:
        if tool_meta.fallback_chain:
            for fallback_name in tool_meta.fallback_chain:
                try:
                    # 用 fallback 工具重新执行
                    fallback_call = copy(tool_call)
                    fallback_call.name = fallback_name
                    return await execute_tool_single(fallback_call, runtime)
                except Exception:
                    continue
        raise  # 所有 fallback 都失败了
```

#### B.4 能力卡片（Capability Card）

**新增 `src/focus_agent/capabilities/capability_card.py`**：
```python
class CapabilityCard:
    """根据任务关键词，选择 3-5 个最相关工具"""
    def __init__(self, runtime: AppRuntime):
        self.runtime = runtime
        # 预计算 BM25 索引
        self._build_bm25_index()
    
    def select_for_task(self, task_brief: str, k: int = 5) -> list[str]:
        """给定任务，返回 k 个最相关工具的名字"""
        # BM25 + 语义相似度（可选）
        scores = self._bm25.get_scores(task_brief)
        top_k_tools = sorted(scores, key=scores.get, reverse=True)[:k]
        return top_k_tools
    
    def format_for_prompt(self, task_brief: str) -> str:
        """生成可插入 system prompt 的文本"""
        tools = self.select_for_task(task_brief)
        text = "### 本次任务推荐工具\n\n"
        for tool in tools:
            meta = self.runtime.tool_registry.get_metadata(tool)
            text += f"- **{tool}**: {meta.description}\n"
        return text
```

**在 `agent_loop` 中使用**：
```python
async def agent_loop(state, runtime):
    # 获取能力卡片
    card = CapabilityCard(runtime).format_for_prompt(state.task_brief)
    
    system_prompt = f"""
    {BASE_SYSTEM_PROMPT}
    
    {card}
    
    其他可用工具（需要时可调用）：
    {list_all_tools_brief(runtime)}
    """
    # ...
```

#### B.5 测试覆盖

```python
def test_parallel_tools_execute_concurrently():
    """验证无副作用工具并行执行"""
    # ... 构造多个 read_file 调用 ...
    # 验证耗时 < 单个工具耗时 × 数量

def test_tool_cache_hit_returns_cached_result():
    """验证缓存命中"""
    # ...

def test_fallback_chain_activates_on_failure():
    """验证 fallback 触发"""
    # ...

def test_capability_card_highlights_relevant_tools():
    """验证能力卡片推荐相关工具"""
    # ...
```

---

### C. 记忆子系统：写入闭环 + 冲突消解（MVP 2 天，增强 3-5 天）

#### C.0 参考与当前约束

Hermes 的记忆体系提供的是“生命周期管理”参考，而不是可直接搬运的实现：

- `agent/memory_manager.py`：把内置记忆与一个外部 provider 统一到 `initialize / prefetch / sync_turn / queue_prefetch / shutdown` 生命周期，且 provider 失败不阻塞主流程。
- `agent/memory_provider.py`：把 `on_turn_start / on_session_end / on_pre_compress / on_memory_write / on_delegation` 做成可选 hook，说明记忆应挂在 turn 边界，而不是散落在业务代码里。
- `tools/memory_tool.py`：强调“冻结快照注入 prompt、实时写入落盘、内容安全扫描、原子写入、去重与容量限制”。
- `tests/run_agent/test_flush_memories_codex.py`：把 flush 记忆视为独立辅助任务，要求走正确模型/API 路径、执行工具调用、清理 flush 临时消息，并让 timeout 来自配置。

Focus Agent 的约束不同：主流程是 LangGraph `build_graph`，状态已包含 `memory_write_requests`，模块已有 `MemoryExtractor / MemoryWriter / MemoryRetriever / MemoryPolicy / MemoryWriteRequest`，命名空间来自 `RequestContext(user_id, root_thread_id, branch_id, project_id, skill_hints)`。因此本方案不新增 provider 抽象，先把现有组件接进图，形成可评估的最小闭环。

#### C.1 设计原则

1. **只记可复用事实，不记流水账**：本 turn 进度、已完成命令、临时 TODO 留在 transcript / trajectory / `rolling_summary`；只有用户偏好、项目稳定约束、分支审查结论、可复用证据索引进入长期记忆。
2. **显式 scope 优先于模型猜测**：`RequestContext` 能确定 scope 时直接写入；模型只能建议 `kind / content / importance / confidence`，不能绕过命名空间策略。
3. **branch 默认隔离，merge 后提升**：分支内发现先写 branch local memory；只有 merge review 通过或 `promoted_to_main=True` 的记录才能进入 conversation main。
4. **写入门槛高于读取门槛**：读取可以召回弱相关背景，由 scorer/rerank 控制；写入必须过 policy、去重、冲突和安全扫描。
5. **非阻塞且可回放**：写入发生在用户可见回答之后，失败不影响回答；每次提取/跳过/写入都要能被 eval 或 trajectory 复现。

#### C.2 生命周期节点

目标图形态：

```text
START
  → bootstrap_turn
  → retrieve_memory
  → assemble_context
  → plan
  → agent_loop ↔ tool_executor
  → reflect?
  → summarize_turn
  → extract_memories
  → write_memories
  → maybe_interrupt_for_merge
  → END
```

节点职责：

- `retrieve_memory`：已存在。继续由 `MemoryRetriever.retrieve_for_turn()` 根据 `MemoryPolicy.allowed_namespaces_for_read()` 读取 user / conversation main / branch local / root episodic / root semantic / project / skill 记忆。
- `assemble_context`：已存在。把 `retrieved_memories` 转为 `_memory_lines`，但后续要把 `memory_prompt_block` 改为带边界的背景块，明确“不是新用户输入”。
- `summarize_turn`：继续维护 `rolling_summary`，并作为抽取输入之一；它不是长期记忆写入的终点。
- `extract_memories`：新增图节点。调用现有 `MemoryExtractor.extract_from_turn(context, state)`，输出标准 `MemoryWriteRequest` 列表到 `memory_write_requests`，同时记录 `skipped_reasons`。
- `write_memories`：新增图节点。读取 `memory_write_requests`，执行 `MemoryPolicy.should_persist()`、同命名空间检索、fingerprint 去重、冲突合并，最后交给 `MemoryWriter.write_records()`。

#### C.3 提取触发

第一版用确定性触发，避免“每轮都让模型想要不要记”带来的成本和漂移：

| 触发来源 | 候选类型 | 默认 scope | 触发条件 |
|----------|----------|------------|----------|
| `pinned_facts` | `USER_PREFERENCE` | `USER` | 用户显式偏好、纠正、长期约束 |
| `active_goal` + `project_id` | `PROJECT_FACT` | `PROJECT` | 当前目标表达稳定项目约束，且不是一次性执行步骤 |
| `branch_local_findings` | `BRANCH_FINDING` | `BRANCH` | 分支产生带 evidence 的发现 |
| `summarize_turn` 输出 | `TURN_SUMMARY` | `ROOT_THREAD` | turn 已完成且摘要非空 |
| merge import | `IMPORTED_CONCLUSION` | `ROOT_THREAD` | merge review 接受分支结论 |

Plan-Act-Reflect 的写入门槛：

- `reflection.status == "replan"` 时不写长期记忆，只保留 `rolling_summary`。
- `reflection.status == "done"` 或未启用 Plan-Act-Reflect 且 `agent_loop` 已产出最终自然语言回答时，可以进入提取。
- 最后一条 assistant message 仍含 tool call、工具协议修复失败、或回答为空时，不进入提取。
- branch 正在 `awaiting_merge_review` 时，只写 branch local，不提升到 main。

增强版再加入小模型抽取，作为 `MemoryExtractor` 的可选策略：输入限定为最后 K 条消息、`rolling_summary`、plan/reflection、branch findings 和工具结果摘要；输出仍必须落成 `MemoryWriteRequest`，不得自定义 schema。

#### C.4 写入门槛

`MemoryPolicy.should_persist()` 从“content 非空”升级为分层门禁：

- **通用门槛**：`content.strip()` 非空；`summary` 可读；`importance >= 0.5`，低于阈值只进入 `rolling_summary`；内容长度在单条上限内，超长转 artifact/citation 引用。
- **user scope**：只允许 `USER_PREFERENCE / USER_PROFILE`；禁止写入分支结论、项目内部事实、临时任务状态。
- **project scope**：必须有 `context.project_id`；内容应是稳定约定、架构事实、配置选择或项目偏好，不写“刚刚跑了某个测试”。
- **root_thread scope**：允许 `TURN_SUMMARY / IMPORTED_CONCLUSION`；摘要应指向当前 root thread，不跨 conversation 泄露。
- **branch scope**：允许 `BRANCH_FINDING`，默认 `PROMOTABLE`；必须带 `source_branch_id` 和尽量带 `evidence_refs`。
- **skill scope**：MVP 不自动写，后续仅在用户明确要求沉淀技能或有专门 skill 生成流程时写。

写入结果应分为 `written / merged / skipped / failed` 四类，原因可被 eval 读取。`memory_write_requests` 保留“候选队列”语义，不把成功写入后的 store payload 反向塞回主状态。

#### C.5 去重与冲突消解

现有 `memory_fingerprint()` 和 `merge_duplicate_records()` 是基础，但需要明确使用顺序：

1. **同 namespace 搜索**：对每个候选先在 `record.namespace` 内用 `content/summary` 搜 top-k，不跨 namespace 去重。
2. **精确 fingerprint**：fingerprint 一致时视为同一记录，保留原 `memory_id`，合并 tags/evidence/confidence/importance/updated_at。
3. **近似重复**：fingerprint 不同但 `kind + scope + normalized summary` 高相似时，合并为一条，不并存。
4. **显式冲突**：同一用户偏好或同一项目决策出现互斥内容时，新记录只有在满足以下任一条件时替换旧记录：用户显式纠正；`importance` 明显更高；`confidence` 更高且证据更新；merge review 明确采纳。
5. **弱冲突**：不能确定互斥时不覆盖旧记忆，写入 `skipped_reasons=possible_conflict`，等待人工或后续 turn 明确。
6. **分支提升去重**：branch local 被 merge 到 main 后，main 中记录 `source_branch_id` 和 `promoted_to_main=True`；branch 本地记录不删除，避免破坏分支审计。

冲突消解先做确定性规则；LLM 判断只作为增强项，且必须输出“保留/替换/合并/跳过 + 理由”，不能直接写 store。

#### C.6 Scope 与 Namespace 策略

读取顺序沿用现有 `MemoryPolicy.allowed_namespaces_for_read()`，但需要把“可读”和“可写”拆开：

| Scope | Namespace | 读策略 | 写策略 |
|-------|-----------|--------|--------|
| user | `("user", user_id, "profile")` | 所有该用户 thread 可读 | 仅用户偏好/画像，禁止写任务流水 |
| root main | `("conversation", root_thread_id, "main")` | 当前 root/thread/branch 可读 | 只写 merge 接受的共享结论 |
| root episodic | `("conversation", root_thread_id, "episodic")` | 当前 root 可读，低优先级 | 写 turn summary，后续可衰减 |
| root semantic | `("conversation", root_thread_id, "semantic")` | 当前 root 可读 | MVP 暂不自动写，留给后续语义压缩 |
| branch local | `("conversation", root_thread_id, "branch", branch_id, "local_memory")` | 当前 branch 可读；synthesize 模式默认过滤未提升分支发现 | 写 branch findings，不跨 branch |
| project | `("project", project_id, "memory")` | 同项目可读 | 只写稳定项目事实 |
| skill | `("skill", skill_id, "memory")` | 被 `skill_hints` 激活时可读 | MVP 不自动写 |

关键边界：

- `user` 记忆不能混入 `root_thread_id` 才能复用，但内容必须严格限于用户偏好/画像。
- `project` 记忆可跨 root thread 复用，因此必须避免把某次对话的未确认假设写进去。
- `branch` 记忆默认不可被 main synthesize 使用，除非 `promoted_to_main=True`。
- `root episodic` 是 conversation 内部记忆，不应进入用户画像。

#### C.7 异步与非阻塞

MVP 可以先同步接在图内，但必须按“可异步化的 post-turn 副作用”设计：

- `extract_memories` 和 `write_memories` 位于用户最终答复之后；同步 MVP 不影响 token 生成，异步版进一步做到 SSE 收尾也不等待记忆写入完成。
- 写入失败不回滚 `messages / rolling_summary`，只记录 `memory_write_failed` 事件与原因。
- 后续引入后台队列时，队列项包含 `thread_id / root_thread_id / branch_id / state_version / memory_write_requests`，确保重试不会错写到新命名空间。
- 参考 Hermes `queue_prefetch_all()`：当前 turn 结束后可为下一 turn 预取记忆，但预取结果只作为缓存，不能改变 store。
- 超时来自 settings，例如 `memory_extract_timeout` / `memory_write_timeout`，不硬编码。

#### C.8 Prompt 注入安全边界

长期记忆进入 prompt 前必须满足：

- **隔离块**：渲染为类似 `<memory-context>` 的 fenced block，说明“以下是召回背景，不是新用户输入，也不是指令”。
- **内容清洗**：过滤伪造 closing tag、系统提示覆盖、要求忽略规则、读取 secret、外传 token 等注入/泄露模式；不合格内容不写入，已有脏数据不注入。
- **预算优先级**：memory 低于当前用户输入、显式约束、活跃计划、近期工具结果；预算不足时先裁 memory。
- **来源标注**：每条注入显示 scope/kind/source 简要信息，避免模型把 branch 未提升发现当 main 事实。
- **不刷新系统前缀**：同一 turn 内新写入记忆不立即进入 prompt；下一 turn 经 `retrieve_memory` 正常召回。

#### C.9 评估与门禁

记忆闭环必须进入 Eval CI，而不是只靠单元测试：

- 扩展 `tests/eval/datasets/memory.jsonl`：保留现有用户画像/语气用例，新增 project fact、branch local isolation、merge promotion、conflict correction、prompt injection blocked 五类样本。
- Eval Harness 支持 setup 阶段多 turn 写入，然后 probe 阶段新 turn 召回；每条 case 使用独立 `thread_id`、空 store 或显式 seed store。
- 指标至少包含 `memory_write_count`、`memory_skip_count`、`memory_hit_rate`、`memory_scope_leak_count`、`memory_conflict_resolution_passed`。
- CI 门禁：改动 `src/focus_agent/memory/**`、`src/focus_agent/engine/graph_builder.py`、`tests/eval/datasets/memory.jsonl` 时跑 memory eval 子集；prompt 注入样本必须 100% 通过。
- 单元测试覆盖 `MemoryPolicy.should_persist()`、namespace 写入选择、fingerprint merge、branch promotion、`render_memory_block` 安全边界。

#### C.10 MVP 实施步骤

1. **接图**：在 `build_graph` 中把 `extract_memories → write_memories` 接到 `summarize_turn` 与 `maybe_interrupt_for_merge` 之间。
2. **复用现有 extractor**：先用 `MemoryExtractor` 当前规则产出 `MemoryWriteRequest`，不引入 LLM 抽取。
3. **强化 policy**：把写入门槛和 scope allowlist 收进 `MemoryPolicy.should_persist()`。
4. **写入去重**：`MemoryWriter.write_records()` 写前搜索同 namespace，优先 fingerprint merge，记录 skip/merge 原因。
5. **安全渲染**：升级 `render_memory_block()`，加入 fenced block、来源标注、tag 清洗与注入模式拦截。
6. **补 eval**：扩展 `tests/eval/datasets/memory.jsonl`，让用户偏好、project fact、branch 隔离和 merge promotion 都可在 CI 里复现。
7. **再做异步**：MVP 稳定后把 extract/write 移到 post-response 队列，并加超时、重试和失败事件。

#### C.11 非目标

- 不引入 Hermes 的 provider/plugin 架构；Focus Agent 先保持单一 LangGraph store 与现有 memory 模块。
- 不做跨用户、跨项目的全局知识库。
- 不把所有 transcript 自动长期保存。
- 不在 MVP 做向量库迁移、复杂衰减任务或后台 compaction 服务。
- 不让模型直接选择任意 namespace 写入。
- 不把未 merge 的 branch finding 注入 main/synthesize prompt。

---

### D. 上下文工程：Token 预算硬约束 + 语义压缩 ✅ 一期已落地

> 状态：2026-04-20 落地一期。当前已实现确定性 prompt 预算硬约束、工具观察裁剪、workspace 工具选择收窄与回归样本；语义压缩仍保留为后续增强。

#### D.0 本轮落地策略与原则

本轮不引入 LLM 语义压缩，也不重写整体 prompt 架构；优先把已经可确定的问题做成稳定、可测、可回归的运行时策略。

**改动原则**

1. **确定性优先**：预算控制使用字符近似 token，不依赖额外模型总结，避免在压力场景里引入新的随机性。
2. **当前 turn 优先**：当前用户输入、显式约束、工具链尾部结果优先保留；旧 summary、retrieved memory、available skills 等低优先级块先被裁掉。
3. **硬预算要真的硬**：正常情况下保留当前输入与约束；极端小预算下允许对当前输入做头尾裁剪，也不能继续把超长 prompt 送进模型。
4. **工具观察先结构化裁剪**：`search_code` / `read_file` / web fetch / diff 等 JSON 结果优先保留 `path`、`line_number`、`start_line`、`end_line`、top snippets，再丢弃大段噪声字段。
5. **工具策略靠运行时收窄，而不只靠提示词**：直答 turn 绑定 0 个工具；workspace turn 禁用 web/write 工具；符号、函数、定义、调用、引用、位置类查询进一步收窄到 `search_code` / `read_file`，避免模型反复先 `list_files`。
6. **失败要可读兜底**：工具轮数耗尽后如果模型返回空内容或工具调用标记残留，优先用已有工具结果生成可读 fallback，而不是把空答案交给用户。

**关键实现节点**

- `ContextBudget` 增加 `prompt_token_limit`、`chars_per_token`、`tool_observation_token_limit`。
- `apply_prompt_budget_guard(...)` 在每次主模型调用、repair 调用、tool-free fallback 调用前统一执行。
- `trim_tool_observation(...)` 在 `tool_executor` 写入 `ToolMessage` 前执行，确保大观察不会整包回灌。
- `_tools_for_policy(...)` 从 turn intent 推导可绑定工具集，必要时把 workspace 工具进一步限定到代码搜索路径。
- `tests/eval/test_context_budget.py` 用确定性 fake model / fake tool 覆盖长历史直答与长工具输出污染问题。
- `tests/eval/datasets/smoke.jsonl` 增加长历史直答回归样本，并继续用 smoke eval 守住 no-tools / workspace-only / forbidden-web 行为。

**验证口径**

- `make ci-test`：221 passed
- `make lint`：passed
- `uv run python -m tests.eval --suite smoke --concurrency 1 --fail-if-regression`：7/7 passed，`forbidden_tool_violation_rate=0`

> 后续 D.1-D.4 保留原深化设计：其中“硬预算 + 工具观察裁剪”的确定性一期已按 D.0 落地；tokenizer 精算、LLM 语义压缩、独立 observe 节点和 artifact 化长观察仍是下一阶段候选。

#### D.1 后续深化：Token 精算与预算约束

**修改 `src/focus_agent/core/context_policy.py`**：
```python
from tiktoken import encoding_for_model

class ContextBudget:
    """硬约束 token 预算"""
    def __init__(self, max_tokens: int, model_name: str):
        self.max_tokens = max_tokens
        self.encoding = encoding_for_model(model_name)
        self.blocks = {}  # name -> (content, priority, tokens)
    
    def add_block(self, name: str, content: str, priority: int) -> bool:
        """添加上下文块，超过预算时返回 False"""
        tokens = len(self.encoding.encode(content))
        self.blocks[name] = (content, priority, tokens)
        return self.compute_total() <= self.max_tokens
    
    def compute_total(self) -> int:
        return sum(t for _, _, t in self.blocks.values())
    
    def prune_to_budget(self) -> dict:
        """丢弃低优先级块直到符合预算"""
        while self.compute_total() > self.max_tokens:
            # 找最低优先级的块
            min_name = min(
                self.blocks,
                key=lambda n: self.blocks[n][1]  # priority
            )
            del self.blocks[min_name]
        return self.blocks

async def assemble_context(state: AgentState, runtime: AppRuntime) -> dict:
    """组装上下文，硬约束 token 预算"""
    budget = ContextBudget(max_tokens=12000, model_name=state.selected_model)
    
    # 按优先级依次添加
    priority_order = [
        ("active_goal", 10, state.active_goal or ""),
        ("pinned_findings", 9, "\n".join(state.pinned_findings or [])),
        ("constraints", 8, state.constraints or ""),
        ("rolling_summary", 7, state.rolling_summary or ""),
        ("retrieved_memories", 6, format_memories(state.memories)),
        ("recent_messages", 5, format_messages(state.messages[-20:])),
        ("available_skills", 4, format_skills(state.available_skills)),
    ]
    
    for name, priority, content in priority_order:
        if content:
            budget.add_block(name, content, priority)
    
    # 强制修剪到预算
    blocks = budget.prune_to_budget()
    
    # 生成 system prompt + user 消息
    context = {
        "system": format_system_prompt(blocks),
        "messages": format_messages_for_model(state.messages, budget)
    }
    
    return context
```

#### D.2 后续深化：消息中段语义压缩

**新增 `src/focus_agent/core/message_compressor.py`**：
```python
async def compress_message_history(
    messages: list[BaseMessage],
    runtime: AppRuntime,
    preserve_last_k: int = 5
) -> list[BaseMessage]:
    """中段消息压缩：保留最后 K 条 + 头部，中段压成摘要"""
    if len(messages) <= preserve_last_k + 3:
        return messages
    
    # 保留：最后 K 条 + 工具链尾 + 头 2 条
    head = messages[:2]
    tail = messages[-preserve_last_k:]
    middle = messages[2:-preserve_last_k]
    
    # 找工具链边界（连续的 ToolMessage + ToolCall）
    tool_chain_start = None
    for i in range(len(middle) - 1, -1, -1):
        if isinstance(middle[i], ToolMessage):
            tool_chain_start = i
            break
    
    if tool_chain_start is not None:
        to_compress = middle[:tool_chain_start]
        tool_chain = middle[tool_chain_start:]
    else:
        to_compress = middle
        tool_chain = []
    
    # 压缩中段
    if len(to_compress) > 3:
        compress_prompt = f"""
        以下是对话的中段，请用一句话总结关键信息：
        
        {format_messages(to_compress)}
        
        输出：一句话摘要
        """
        compressor = runtime.model_for_role("critic")
        summary = await compressor.ainvoke(compress_prompt)
        compressed_msg = AIMessage(content=f"[压缩摘要] {summary}")
    else:
        compressed_msg = None
    
    # 重组
    result = head
    if compressed_msg:
        result.append(compressed_msg)
    result.extend(tool_chain)
    result.extend(tail)
    
    return result
```

#### D.3 后续深化：工具结果裁剪与 artifact 化

**新增 observe 节点**：
```python
async def observe_node(state: AgentState, runtime: AppRuntime) -> dict:
    """观察节点：裁剪超长工具结果"""
    tool_messages = [m for m in state.messages if isinstance(m, ToolMessage)]
    
    observed = []
    for tm in tool_messages:
        if len(tm.content) > 5000:
            # 太长，需要裁剪
            if state.current_step_index > 0:
                current_goal = state.plan[state.current_step_index - 1].goal
            else:
                current_goal = state.task_brief
            
            trim_prompt = f"""
            任务目标：{current_goal}
            工具输出（{len(tm.content)} 字）：
            {tm.content}
            
            从上面的输出中，提取与任务目标相关的部分（限 500 字）。
            """
            trimmer = runtime.model_for_role("critic")
            trimmed = await trimmer.ainvoke(trim_prompt)
            
            # 保存原文到 artifacts
            artifact_path = f"artifacts/tool_results/{tm.name}_{uuid4()}.txt"
            write_artifact(artifact_path, tm.content)
            
            tm_trimmed = ToolMessage(
                name=tm.name,
                content=f"{trimmed}\n\n[完整输出已保存到 {artifact_path}]",
                tool_call_id=tm.tool_call_id
            )
            observed.append(tm_trimmed)
        else:
            observed.append(tm)
    
    return {"messages": observed}
```

#### D.4 测试覆盖

```python
def test_context_budget_hard_limit():
    """验证 token 预算硬约束"""
    # ...

def test_prune_removes_lowest_priority_blocks():
    """验证修剪时移除低优先级块"""
    # ...

def test_message_compression_reduces_token_count():
    """验证压缩降低 token 数"""
    # ...

def test_observe_node_trims_long_results():
    """验证工具结果被裁剪"""
    # ...
```

---

### E. Agent 自主性：技能自选 + 分支自主决策（3 天工期）

#### E.1 技能自选

**修改 `plan_node`**：
```python
async def plan_node(state: AgentState, runtime: AppRuntime) -> dict:
    """规划节点：选择技能 + 分解任务"""
    # 1. 技能自选
    skill_selector = SkillSelector(runtime)
    active_skills = skill_selector.select_for_task(
        task_brief=state.task_brief,
        available_skills=runtime.skill_registry.list_available(),
        k=3
    )
    
    # 2. 拼接技能描述到 prompt
    skills_context = format_skills(active_skills)
    
    plan_prompt = f"""
    任务：{state.task_brief}
    
    可用的技能（已预选）：
    {skills_context}
    
    其他通用工具见列表...
    
    分步计划：...
    """
    # ... 后续同 A.2 ...
    
    return {
        "plan": steps,
        "active_skill_ids": [s.id for s in active_skills]
    }

# 新增 src/focus_agent/capabilities/skill_selector.py
class SkillSelector:
    def __init__(self, runtime):
        self._build_bm25_index(runtime.skill_registry.list_all())
    
    def select_for_task(self, task_brief, available_skills, k=3) -> list[Skill]:
        """基于 BM25 + 语义相似度选择 k 个技能"""
        scores = {}
        for skill in available_skills:
            text = f"{skill.description} {' '.join(skill.triggers)}"
            scores[skill.id] = self._bm25.get_score(task_brief, text)
        
        top_k = sorted(scores, key=scores.get, reverse=True)[:k]
        return [s for s in available_skills if s.id in top_k]
```

#### E.2 分支自主建议

**修改 `reflect_node`**：
```python
async def reflect_node(state: AgentState, runtime: AppRuntime) -> dict:
    """自省节点：评估并检测分支机会"""
    # ... 现有反射逻辑 ...
    
    # 分支检测
    branch_proposal = detect_branch_opportunity(
        state=state,
        reflection=reflection,
        runtime=runtime
    )
    
    return {
        "reflection": reflection,
        "branch_proposal": branch_proposal
    }

def detect_branch_opportunity(state, reflection, runtime) -> dict | None:
    """检测是否应建议用户开分支"""
    # 条件 1: 互斥假设
    if "互斥" in reflection.reasoning or "对比" in reflection.gaps:
        return {
            "type": "competing_hypotheses",
            "reason": "有多个互斥的方案，建议并行验证",
            "suggested_count": 2
        }
    
    # 条件 2: 高风险子任务
    if "高风险" in reflection.reasoning:
        return {
            "type": "high_risk_subtask",
            "reason": "该子任务存在很高的失败风险，建议在分支中验证",
            "suggested_count": 1
        }
    
    # 条件 3: 多条并行路径
    if state.current_step_index < len(state.plan) - 1:
        next_steps = state.plan[state.current_step_index:state.current_step_index+3]
        if len(next_steps) >= 2 and are_steps_independent(next_steps):
            return {
                "type": "parallel_steps",
                "reason": "后续步骤可并行执行，建议开分支",
                "suggested_count": len(next_steps)
            }
    
    return None
```

#### E.3 前端集成

修改 `chat_service` 的流中，当 `branch_proposal` 出现时发送事件：
```python
# 在 stream_message 中
if branch_proposal := state.branch_proposal:
    yield {
        "type": "branch_proposal",
        "proposal": branch_proposal,
        "message": "我检测到可能需要开分支，是否同意？"
    }
    # 等待用户决策 or 自动超时 30s
```

#### E.4 测试覆盖

```python
def test_skill_selector_picks_relevant_skills():
    """验证技能选择准确"""
    # ...

def test_branch_proposal_on_competing_hypotheses():
    """验证互斥假设时建议分支"""
    # ...

def test_branch_proposal_on_high_risk_subtask():
    """验证高风险时建议分支"""
    # ...
```

---

### F. 模型分工：Planner/Executor/Critic 路由（1 天工期）

#### F.1 角色路由实现

**新增 `src/focus_agent/model_router.py`**：
```python
class ModelRouter:
    """按 agent 角色选择合适的模型"""
    
    ROLE_CONFIGS = {
        "planner": {
            "model": "claude-opus-4-7",
            "temperature": 0.2,
            "max_tokens": 2000,
            "context_window_pct": 0.8,  # 用 80% 上下文
        },
        "executor": {
            "model": "claude-sonnet-4-6",
            "temperature": 0.5,
            "max_tokens": 4000,
            "context_window_pct": 0.7,
        },
        "critic": {
            "model": "claude-haiku-4-5",
            "temperature": 0.0,
            "max_tokens": 1000,
            "context_window_pct": 0.5,
        }
    }
    
    def create_chat_model_for_role(self, role: str, settings: Settings):
        """创建指定角色的模型"""
        config = self.ROLE_CONFIGS[role]
        model = create_chat_model(
            model_id=config["model"],
            temperature=config["temperature"],
            max_tokens=config["max_tokens"],
            settings=settings
        )
        return model
    
    def estimate_cost(
        self,
        role: str,
        input_tokens: int,
        output_tokens: int
    ) -> float:
        """估算成本"""
        model_id = self.ROLE_CONFIGS[role]["model"]
        # 使用内置价目表
        pricing = PROVIDER_PRICING[extract_provider(model_id)][model_id]
        return (
            input_tokens * pricing["input_per_1m"] / 1_000_000 +
            output_tokens * pricing["output_per_1m"] / 1_000_000
        )
```

**修改 `AppRuntime` 和 `AgentState`**：
```python
class AppRuntime:
    def __init__(self, ...):
        self.model_router = ModelRouter()
    
    def model_for_role(self, role: str) -> ChatModel:
        return self.model_router.create_chat_model_for_role(role, self.settings)

# 在 agent_loop 中使用：
executor_model = runtime.model_for_role("executor")
response = await executor_model.ainvoke(messages)
```

#### F.2 成本监测

**在 `AgentState` 中追踪**：
```python
@dataclass
class AgentState:
    # ... 现有字段 ...
    cost_breakdown: dict = field(default_factory=dict)  # {role: cost_usd}
    tokens_breakdown: dict = field(default_factory=dict)  # {role: {input, output}}
```

**在各节点中记录**：
```python
async def plan_node(state, runtime):
    # ... 规划逻辑 ...
    
    # 记录成本
    input_tokens = count_tokens(plan_prompt, model="claude-opus-4-7")
    output_tokens = count_tokens(response, model="claude-opus-4-7")
    cost = runtime.model_router.estimate_cost(
        "planner", input_tokens, output_tokens
    )
    
    state.cost_breakdown["planner"] = cost
    state.tokens_breakdown["planner"] = {
        "input": input_tokens,
        "output": output_tokens
    }
    
    return {...}
```

#### F.3 测试覆盖

```python
def test_model_router_selects_correct_model():
    """验证角色选择"""
    # ...

def test_cost_estimation_for_role():
    """验证成本估算"""
    # ...

def test_total_cost_breakdown():
    """验证总成本分解"""
    # ...
```

---

### G. 可观测性：Postgres Trajectory + 指标 + OpenTelemetry（2 天工期）

#### G.0 当前 PostgreSQL 持久化迭代进度（2026-04-21）

**已完成**

- **Postgres primary persistence 已接主路径**：`create_runtime` 在 `DATABASE_URI` 存在时切到 `postgres-primary`，统一初始化 LangGraph `PostgresSaver` / `PostgresStore`、`PostgresBranchRepository`、`ArtifactMetadataRepository`，以及可选的 `PostgresTrajectoryRepository`；未配置数据库时仍保留本地 fallback，运行时切换已收口在同一入口。
- **branch repo / schema 已落表**：`ensure_app_postgres_schema` 已管理 `focus_schema_migrations`，并创建 `focus_conversations`、`focus_thread_access`、`focus_branches`、`focus_artifacts` 及常用索引；`PostgresBranchRepository` 已覆盖分支、会话、thread access、归档/命名/merge proposal/merge decision 等核心读写。
- **artifact metadata 已入库**：artifact 元数据通过 `ArtifactMetadataRepository` 写入 `focus_artifacts`，支持 upsert / list / get；当前策略保持“元数据进 Postgres、正文留文件系统”，避免把大文件正文直接塞进数据库。
- **迁移 CLI 已可用**：`focus-agent-migrate-local-state` 已支持 `--dry-run`、`--report-path`、`--checkpoint-mode latest-stable`、`--artifact-scan`，可迁移 SQLite app state、LangGraph store/checkpoints，并显式初始化 Postgres trajectory schema；迁移报告和重复执行语义已有测试覆盖。
- **测试/守护已补齐到可回归水平**：当前已具备 runtime backend selection、Postgres schema / branch repo、artifact metadata、migration CLI、trajectory repository 的单测覆盖；本地本轮验证通过 `tests/test_runtime_backend_selection.py`、`tests/test_postgres_branch_repository.py`、`tests/test_migrate_local_state.py`、`tests/test_trajectory_observability.py`、`tests/test_repository.py`，共 13 个相关用例；`tests/test_ui_smoke_script.py` 也已通过。smoke eval 数据集、JSON/HTML 报告和 CI 门禁已在，但仍主要承担行为回归守护，不等同于 Postgres 迁移验收。
- **已补一轮真实 PostgreSQL 主路径 smoke**：使用干净验证库执行 `focus-agent-migrate-local-state` 导入本地 `.focus_agent`，随后以 `DATABASE_URI` 启动真实 API，完成 demo-token、会话列表、创建会话、`/v1/chat/turns`、`/v1/branches/fork`、`/v1/branches/tree` 一整条请求链；数据库侧确认 `focus_conversations` / `focus_thread_access` / `focus_branches` / `focus_trajectory_turns` 增长，本地 fallback 的 `branches.sqlite3` 与 `langgraph-*.pkl` mtime 未变化。

**未完成 / 后续项**

- **trajectory 查询/导出链路仍未补完**：当前已能写入 Postgres trajectory 表，但查询、导出、失败 turn 转 replay dataset 的 CLI 还没接上。
- **迁移 CLI 暂不回灌历史 trajectory**：该工具目前只建 trajectory schema，不生成历史 turn 记录；历史观测数据迁移仍是后续项。
- **OpenTelemetry 仍停留在方案位**：表结构和指标落库先行，图节点/span 级 tracing 还没有按本节方案完整接入。
- **Postgres 验证仍缺浏览器与导出链路**：本轮已补过真实数据库 + 模型配置的 API 级 smoke，但浏览器侧链路、trajectory 查询/导出、以及更长时运行场景仍需要继续在主线环境里覆盖。
- **持久化运维项待补**：retention、备份恢复、清理策略，以及更细粒度的 artifact 归属字段仍放在后续迭代。

#### G.1 Trajectory 记录

**已采用 Postgres 方案**：生产侧 `src/focus_agent/observability/trajectory.py` 定义 `TrajectoryStep` / `TurnTrajectoryRecord`，并把 eval 原有 “`AIMessage.tool_calls` + `ToolMessage` 配对”抽取逻辑迁到生产模块，避免 eval 与线上记录漂移。

**新增应用自有表，不混用 LangGraph 内部表**：
```sql
CREATE TABLE IF NOT EXISTS focus_trajectory_turns (
  id UUID PRIMARY KEY,
  schema_version INT NOT NULL DEFAULT 1,
  kind TEXT NOT NULL,
  status TEXT NOT NULL,
  thread_id TEXT NOT NULL,
  root_thread_id TEXT NOT NULL,
  parent_thread_id TEXT,
  branch_id TEXT,
  branch_role TEXT,
  user_id_hash TEXT NOT NULL,
  scene TEXT NOT NULL,
  turn_index INT,
  task_brief TEXT,
  user_message TEXT,
  answer TEXT,
  selected_model TEXT,
  selected_thinking_mode TEXT,
  plan JSONB,
  reflection JSONB,
  plan_meta JSONB NOT NULL DEFAULT '{}'::jsonb,
  metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  error TEXT,
  started_at TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS focus_trajectory_steps (
  id BIGSERIAL PRIMARY KEY,
  turn_id UUID NOT NULL REFERENCES focus_trajectory_turns(id) ON DELETE CASCADE,
  step_index INT NOT NULL,
  tool TEXT NOT NULL,
  args JSONB NOT NULL DEFAULT '{}'::jsonb,
  observation TEXT NOT NULL DEFAULT '',
  observation_truncated BOOLEAN NOT NULL DEFAULT false,
  duration_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
  error TEXT,
  cache_hit BOOLEAN NOT NULL DEFAULT false,
  fallback_used BOOLEAN NOT NULL DEFAULT false,
  fallback_group TEXT,
  parallel_batch_size INT,
  runtime JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (turn_id, step_index)
);
```

接入原则：

- `DATABASE_URI` 存在时初始化 `PostgresTrajectoryRepository`；不存在时 recorder 为 no-op，不提供 JSONL fallback。
- `_run_invoke` 与 `_astream_result` 只在 turn 收口处写完整记录，不按流式 chunk 写。
- 写入失败只记录 warning，不影响用户可见回答。
- `user_id` 默认 hash 后入库；不存完整 system prompt、assembled context 或未截断 observation。

#### G.2 指标计算

首版每条 turn 写入 `metrics JSONB`：`latency_ms`、`tool_calls`、`llm_calls`、`input_tokens`、`output_tokens`、`cache_hits`、`fallback_uses`、`parallel_tool_calls`。后续再加 Postgres 查询/导出 CLI，把失败 turn 转成 eval replay 样本。

#### G.3 OpenTelemetry 集成

**修改 `src/focus_agent/engine/graph_builder.py`**：
```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

async def plan_node(state, runtime):
    with tracer.start_as_current_span("agent:plan") as span:
        span.set_attribute("task_brief", state.task_brief[:100])
        span.set_attribute("plan_step_count", len(state.plan or []))
        
        # ... 规划逻辑 ...
        
        span.set_attribute("status", "completed")

async def agent_loop(state, runtime):
    with tracer.start_as_current_span("agent:act") as span:
        span.set_attribute("step_index", state.current_step_index)
        
        for tool_call in tool_calls:
            with tracer.start_as_current_span("tool:execute", attributes={
                "tool_name": tool_call.name,
                "cache_hit": is_cached
            }) as child_span:
                result = await execute_tool(tool_call)
                child_span.set_attribute("error", result.error is not None)
                child_span.set_attribute("duration_ms", duration)
```

#### G.4 测试覆盖

```python
def test_trajectory_records_all_fields():
    """验证 Postgres trajectory 记录完整"""
    # ...

def test_metrics_computed_correctly():
    """验证指标计算准确"""
    # ...

def test_otel_spans_nested_correctly():
    """验证 OpenTelemetry span 嵌套关系"""
    # ...
```

---

## 三、优先级与工作量

| 序 | 项 | 价值 | 工作量 | 依赖 |
|---|---|---|---|---|
| 1 | H. 评估框架 | 极高 | 3d | — |
| 2 | C. 记忆写入闭环 | 极高 | 2d | writer/dedupe 已有 |
| 3 | D. token 预算 + 工具结果裁剪 | 高 | 2d | — |
| 4 | A. plan / reflect 节点 | 高 | 3d | 建议 H 先行 |
| 5 | B. 工具并行 + 缓存 | 中高 | 2d | — |
| 6 | F. 模型角色路由 | 中高 | 1d | A |
| 7 | G. trajectory 查询/导出 + OTel 收尾 | 中 | 2d | Postgres 主持久化已接入 |
| 8 | E. 技能自选 + 分支自主 | 中 | 3d | A |

**推荐顺序**：H → C → D → A → F → B → G → E。原因：先建尺子（H），再做最便宜的大提升（C），随后结构改造（A/D），最后收尾优化（B/F/G/E）。

---

## 四、评估框架详细落地（H 项）

评估是 agent 工程的"地基"。没有它，前述所有改动都是凭感觉。本节给出完整实现方案。

### 4.1 目标

1. **防回归**：任何改动（模型、prompt、图结构）在合并前必须证明核心任务成功率不下降。
2. **驱动优化**：通过分层指标（success / efficiency / cost）定位到具体能力瓶颈。
3. **在线复盘**：把生产环境失败 trajectory 持续喂回评测集，形成闭环。

### 4.2 目录结构

```
tests/eval/
├── __init__.py
├── README.md                          # 使用说明 + 如何新增用例
├── datasets/
│   ├── golden_tasks.jsonl             # 人工标注的黄金集（20–50 条起步）
│   ├── regression_traj.jsonl          # 从生产/历史 trajectory 抽的失败案例
│   └── memory_probes.jsonl            # 专测记忆能力的探针集
├── judges/
│   ├── __init__.py
│   ├── rule_judge.py                  # 规则校验（文件是否写入、工具是否调用等）
│   ├── llm_judge.py                   # LLM-as-judge（答案语义正确性）
│   └── trajectory_judge.py            # 轨迹效率评分
├── metrics/
│   ├── __init__.py
│   ├── success.py                     # task_success / pass@k
│   ├── efficiency.py                  # tool_calls / tokens / latency
│   ├── memory.py                      # memory_hit_rate / memory_utility
│   └── adherence.py                   # plan_adherence
├── runner/
│   ├── __init__.py
│   ├── harness.py                     # 跑单条用例的 harness
│   ├── parallel.py                    # 并发执行 + 进度条
│   └── replay.py                      # 从 trajectory 回放
├── reports/
│   ├── __init__.py
│   ├── html.py                        # 生成 HTML 报告
│   └── markdown.py                    # 生成 PR 评论用 markdown
└── conftest.py                        # pytest fixture：隔离 store/checkpointer
```

### 4.3 数据集 schema

#### 4.3.1 `golden_tasks.jsonl`（核心）

```json
{
  "id": "gt_001_file_search",
  "tags": ["workspace", "search_code", "basic"],
  "scene": "workspace",
  "skill_hints": ["code_reader"],
  "input": {
    "user_message": "在仓库里找出所有使用了 `assemble_context` 的地方，列出 file:line。",
    "initial_state": {}
  },
  "expected": {
    "answer_contains_any": ["graph_builder.py", "context_policy.py"],
    "must_call_tools_any_order": ["search_code"],
    "must_not_call_tools": ["web_search", "web_fetch"],
    "max_tool_calls": 3,
    "max_llm_calls": 4
  },
  "judge": {
    "rule": true,
    "llm": {
      "enabled": true,
      "rubric": "答案必须给出至少两处 file:line 且与实际文件一致。"
    }
  }
}
```

字段说明：
- `scene / skill_hints`：注入 `RequestContext`，对齐生产运行时。
- `expected.answer_contains_any`：弱约束，规则判 pass 的兜底。
- `must_call_tools_any_order / must_not_call_tools`：行为约束，比语义更稳定。
- `max_tool_calls / max_llm_calls`：效率上限，超即 fail。
- `judge.rule / judge.llm`：双 judge，只要其中 `required_pass` 失败整条用例 fail。

#### 4.3.2 `regression_traj.jsonl`

从线上 JSONL trajectory（见 G 项）抽取失败样本，格式同上，但增：
```json
"origin": {
  "thread_id": "...",
  "captured_at": "2026-04-18T...",
  "failure_mode": "replanned_3_times_then_gave_up"
}
```
**采样规则**：人工 thumb-down + `replan_rate>2` + `budget_overflow_events>0` 的 turn。

#### 4.3.3 `memory_probes.jsonl`（记忆专项）

每条包含 **setup turns** 和 **probe turn**：
```json
{
  "id": "mem_001_user_pref",
  "setup": [
    {"user": "我是 Go 后端工程师，不熟 React。"},
    {"user": "别在回答里用 emoji。"}
  ],
  "probe": {
    "user": "介绍一下这个前端项目的状态管理。",
    "expected": {
      "answer_must_reference": ["Go", "类比后端"],
      "answer_must_not_contain_regex": "[\\p{Emoji}]"
    }
  }
}
```
专测 C 项的记忆闭环是否生效：setup 写入记忆，probe 验证后续 turn 能否召回并遵守。

### 4.4 Judge 设计

#### rule_judge（快速、稳定、无成本）
- 字符串包含 / 正则 / tool trace 断言。
- 所有 `must_*` 约束。
- 必须通过，否则整条 fail（不走 LLM）。

#### llm_judge（语义层、可配模型）
- 使用 **小模型（Haiku 级）** 给 pass/fail + reasoning。
- 输入：rubric + user_message + agent_answer + 工具调用摘要。
- 输出：
  ```json
  {"verdict": "pass" | "fail", "confidence": 0.0-1.0, "reasoning": "..."}
  ```
- **低置信（<0.7）自动升级**到大模型复判，避免假阳/假阴。
- Prompt 模板必须带 few-shot 正反例，防止 judge 本身漂移（参考 Anthropic / OpenAI 发布的 judge best practice）。

#### trajectory_judge（效率）
- 给定 `actual_tool_sequence` 与 `optimal_tool_sequence`（可选人工标），计算编辑距离 / 召回。
- 无 optimal 标注时退化为"是否超过 `max_tool_calls`"的布尔判断。

### 4.5 指标体系

| 层 | 指标 | 公式 / 说明 | 目标 |
|---|---|---|---|
| 效果 | `task_success` | rule + llm 双通过率 | ≥ 基线 |
| 效果 | `pass@k` | k 次独立重跑至少一次通过 | 稳健性 |
| 效率 | `avg_tool_calls` | 工具调用数均值 | ↓ |
| 效率 | `avg_llm_calls` | LLM 调用次数 | ↓ |
| 效率 | `avg_input_tokens` / `avg_output_tokens` | 按 provider counter 计 | ↓ |
| 效率 | `p95_latency_ms` | 端到端 | ↓ |
| 成本 | `avg_cost_usd` | tokens × 单价（内置价目表） | ↓ |
| 记忆 | `memory_hit_rate` | 被引用记忆数 / 检索次数 | ↑ |
| 记忆 | `memory_utility` | 开/关记忆的 success delta | > 0 |
| 规划 | `plan_adherence` | 最终答案覆盖的 plan.steps 比例 | ↑ |
| 规划 | `replan_rate` | replan 次数 / turn | 稳定 |
| 行为 | `forbidden_tool_violation_rate` | 触发 must_not_call 的比例 | → 0 |

### 4.6 Runner / Harness

核心 API：
```python
# tests/eval/runner/harness.py
@dataclass
class EvalCase:
    id: str
    input: dict
    expected: dict
    judge: dict

@dataclass
class EvalResult:
    case_id: str
    passed: bool
    rule_verdict: dict
    llm_verdict: dict | None
    metrics: dict            # tool_calls, tokens, latency, cost
    trajectory: list[dict]   # 与 G 项 JSONL 同 schema
    error: str | None = None

def run_case(case: EvalCase, *, runtime) -> EvalResult: ...
def run_suite(
    cases: Iterable[EvalCase],
    *,
    runtime,
    concurrency: int = 4,
    seed: int = 0,
) -> list[EvalResult]: ...
```

要点：
- **隔离**：每条用例独立 thread_id + 全新 in-memory checkpointer + 空 store（除非用例明确声明需要预置记忆）。
- **固定 seed**：模型 temperature 设 0；web_search 走 recorded fixtures（见 4.8）。
- **并发**：`asyncio.gather` + `Semaphore`；默认 4，CI 可压到 8。
- **超时**：单条硬超时 120s；超时计 fail 而非挂起。
- **重试**：provider 5xx 自动重试 2 次；用例逻辑 fail **不**重试。

### 4.7 CLI 与 pytest 双入口

```bash
# 本地快跑（子集 + 并发 2）
uv run python -m tests.eval --suite smoke --concurrency 2

# 全量跑 + HTML 报告
uv run python -m tests.eval --suite all --report-html reports/eval.html

# 从 trajectory 回放
uv run python -m tests.eval replay --from artifacts/trajectories/2026-04-18.jsonl

# pytest 集成（把 golden_tasks 作为参数化 case）
uv run pytest tests/eval/test_golden_suite.py -k smoke
```

### 4.8 外部依赖与复现性

- **LLM 调用**：评测期间允许真实调；同时支持 `EVAL_CACHE_DIR` 缓存响应（按 `(model, messages_hash)`），二次跑离线复现。
- **Web 工具**：`web_search / web_fetch` 在评测模式下走 VCR-style fixture（`tests/eval/fixtures/http/`），首跑录制、后续回放。避免网络抖动污染指标。
- **时间/随机**：`current_utc_time` 在评测 runtime 里 freeze 到固定时间戳。

### 4.9 CI 集成与门控

`.github/workflows/eval.yml`：
```yaml
on:
  pull_request:
    paths:
      - 'src/focus_agent/engine/**'
      - 'src/focus_agent/capabilities/**'
      - 'src/focus_agent/memory/**'
      - 'src/focus_agent/core/**'
      - 'src/focus_agent/prompts.py'

jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: make install
      - run: uv run python -m tests.eval --suite smoke --baseline main --fail-if-regression
      - uses: actions/upload-artifact@v4
        with: { name: eval-report, path: reports/eval.html }
      - run: uv run python -m tests.eval.reports.markdown >> $GITHUB_STEP_SUMMARY
```

**门控规则**（`--fail-if-regression`）：
- `task_success` 下降 > 2 个百分点 → 阻断。
- `forbidden_tool_violation_rate` 出现新违规 → 阻断。
- `avg_cost_usd` 上升 > 20% 且 `task_success` 未提升 → warning（不阻断，PR 评论提醒）。
- 基线 = `main` 分支最新一次 eval 快照（存 `eval-baselines/` 或 artifacts）。

### 4.10 报告

Markdown（贴 PR 评论）：
```
## Eval Summary — smoke (42 cases)

|                          | main   | PR     | Δ     |
|--------------------------|--------|--------|-------|
| task_success             | 0.857  | 0.881  | +2.4% |
| avg_tool_calls           | 3.12   | 2.78   | -10.9%|
| avg_cost_usd             | 0.041  | 0.039  | -4.9% |
| memory_hit_rate          | 0.00   | 0.63   | NEW   |
| forbidden_tool_violation | 0      | 0      | —     |

**Regressions**: none
**New failures**: gt_014_merge_review
```
HTML：每条用例点开可看完整 trajectory（用户消息 / plan / 每步工具调用 / reflection / 最终答案 / judge 理由）。

### 4.11 数据集维护与反馈闭环

1. **新功能 PR 要求**：新增 agent 能力必须带 ≥ 3 条 golden case 覆盖该能力。
2. **线上失败归集**：生产 trajectory 中被用户 thumb-down 或触发 `ask_user` 兜底的条目，每周脚本导出到 `datasets/regression_traj.jsonl`，人工审核后进评测集。
3. **数据集版本化**：`datasets/` 打 git tag（如 `eval-v0.2`），报告里标注用的版本，便于纵向比较。
4. **标注工具**：简易 CLI `python -m tests.eval.annotate <trajectory_file>`，交互式录入 expected 字段，降低人工成本。

### 4.12 实施里程碑（3 天交付 MVP）

| 天 | 产出 |
|---|---|
| D1 上午 | 目录骨架、`EvalCase/EvalResult` 数据结构、conftest、10 条 golden case 起步 |
| D1 下午 | `rule_judge` + harness 单条跑通；pytest 参数化跑通 |
| D2 上午 | `llm_judge` + 低置信升级复判；完善到 25 条 golden case |
| D2 下午 | 指标计算 + Markdown 报告；本地 baseline 快照 |
| D3 上午 | HTML 报告 + 并发 runner + HTTP fixture 回放 |
| D3 下午 | CI workflow + 回归门控；文档 README |

MVP 合并后作为后续所有 agent 改动的基础设施；C/D/A 等项改动必须配套扩充评测集。

---

## 五、与现有架构的契合度

- LangGraph `StateGraph` 支持增量加节点；`plan / reflect / extract / write_memory` 皆纯增量。
- `AgentState` 已预留 `memory_write_requests / context_budget / active_skill_ids`——骨架已在，本方案把它血肉化。
- `PromptMode`（EXPLORE / BRANCH_REVIEW）可扩展为 `PLAN / ACT / REFLECT` 三态，复用现有装配器。
- 评测框架完全独立于运行时，无侵入；可先于任何能力改动单独落地。
