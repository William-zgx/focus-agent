# Focus Agent Agent 能力路线图

更新时间：2026-04-21

这份文档只保留 Agent 能力侧的当前状态、代码入口和下一步优先级，不再堆叠已经过期的分阶段实施草案。

## 1. 当前状态总览

| 模块 | 当前状态 | 主要入口 | 下一步 |
|------|----------|----------|--------|
| Plan-Act-Reflect | 已落地并默认开启 | `src/focus_agent/engine/graph_builder.py` | 优化 replan 质量、接模型角色分工 |
| Memory | 读写闭环已接图 | `src/focus_agent/engine/graph_builder.py` `src/focus_agent/memory/` | 提升写入质量、冲突处理、promotion 规则 |
| Context Engineering | 一期已落地 | `src/focus_agent/core/context_policy.py` | tokenizer 精算、语义压缩、长观察外置 |
| Tool Runtime | 并行/缓存/降级基础已落地 | `src/focus_agent/capabilities/tool_runtime.py` | 更强参数校验、取消/超时策略 |
| Eval | 基线已落地 | `tests/eval/` | 扩数据集、补 CI 门禁、接更多能力专项 |
| Observability | trajectory 入 Postgres 已落地 | `src/focus_agent/observability/trajectory.py` | 查询/导出 CLI、浏览器链路验证、OTel |
| Model Routing | 未落地 | 方案位 | planner / executor / reflect 分工 |
| Autonomy | 未落地 | 方案位 | 技能自选、分支建议、风险感知工作流 |

## 2. 已完成进展

### 2.1 Plan-Act-Reflect

- 已接入 `bootstrap -> retrieve_memory -> assemble_context -> plan -> agent_loop/tool_executor -> reflect -> summarize_turn` 主链
- 默认开启，可通过配置关闭
- 失败时可退化回原有 ReAct 主路径，不阻塞主回答
- 已有对应回归与专项测试，见 `tests/eval/test_plan_act_reflect.py`

### 2.2 Memory 读写闭环

- 读取链路已在 turn 前执行：`retrieve_memory`
- 提取/写入链路已在 turn 末端接图：`extract_memories -> write_memories`
- 现有 `MemoryExtractor / MemoryWriter / MemoryPolicy` 已进入运行主路径
- 当前重点不再是“接图”，而是继续提升记忆质量、冲突消解、作用域隔离和 merge promotion 规则

### 2.3 Context Engineering 一期

- 已有确定性 prompt 预算与工具观察裁剪
- 长工具输出不会整包回灌到模型
- 已有针对长历史和长观察污染的回归样本
- 当前仍使用字符近似 token 预算，尚未引入 tokenizer 精算或语义压缩

### 2.4 Tool Runtime 基础

- 工具运行时已支持并行安全分组
- 已支持基于 scope 的缓存与重复调用复用
- 已支持 fallback 分组和 runtime metadata 回灌
- trajectory / eval 已能读取 `cache_hit`、`fallback_used`、`parallel_batch_size`

### 2.5 Eval 与 Observability 基线

- `tests/eval/` 已具备 smoke、judge、metrics、报告聚合能力
- 生产路径已使用统一 trajectory schema，避免 eval 与线上记录漂移
- `DATABASE_URI` 存在时会初始化 Postgres trajectory 记录器并落库

## 3. 仍需继续收口的点

### 3.1 Memory

当前已经不是“有没有写入链路”的问题，而是“写得准不准、什么时候该提升、哪些内容不该泄露作用域”：

- 继续强化 branch / root thread / project 之间的作用域约束
- 补更系统的 memory eval 样本
- 明确 merge 后哪些 branch 结论应该 promotion 到主线长期记忆
- 继续优化去重、冲突合并和安全渲染

### 3.2 Context Engineering

当前一期能解决最明显的 prompt 污染问题，但还没到最终形态：

- 用 tokenizer 替代字符近似 token 预算
- 对长历史做语义压缩，而不是只靠确定性裁剪
- 把超长观察更系统地转成 artifact / 引用，而不是单纯截断

### 3.3 Observability

trajectory 已经“能写”，但还不够“能用”：

- 补 Postgres trajectory 查询/导出 CLI
- 把失败 turn 转 replay dataset 的链路接起来
- 浏览器侧和更长时运行链路补验证
- OpenTelemetry / span 级 tracing 仍未完成

### 3.4 Tool Runtime

基础运行时已经成型，后续主要是补完工程细节：

- 更强的参数校验
- 更明确的 side-effect tool 串行边界
- 取消/超时/重试等运行时控制
- 更细粒度的 capability bias，而不只是简单工具收窄

## 4. 当前优先级

建议按下面顺序推进：

1. **Observability 收口**
   - 先补 trajectory 查询/导出和 replay 闭环
2. **Model Routing**
   - 把 planner / executor / reflect 的模型分工接进现有图
3. **Memory 质量**
   - 扩 eval、补冲突与 promotion 策略
4. **Context Engineering 二期**
   - tokenizer 精算 + 语义压缩
5. **Autonomy**
   - 技能自选、分支建议

## 5. 推荐验证口径

每次动到 Agent 主路径，至少关注下面几类回归：

- `tests/eval/test_plan_act_reflect.py`
- `tests/eval/test_context_budget.py`
- `tests/test_memory_pipeline.py`
- `tests/test_tool_runtime.py`
- `tests/test_trajectory_observability.py`
- `tests/test_runtime_backend_selection.py`

如果改动影响运行主链，再补一轮：

- `make ci-test`
- `uv run python -m tests.eval --suite smoke --concurrency 1`

## 6. 文档维护原则

- 本文只保留“现状、进展、下一步”
- 详细设计方案和长篇伪代码不再长期保留在这份路线图里
- 当某项能力从“方案位”进入主路径时，先更新这里的状态表，再决定是否需要单独设计文档
