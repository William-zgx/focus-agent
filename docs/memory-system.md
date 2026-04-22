# Focus Agent 记忆系统设计

更新时间：2026-04-22

本文把当前仓库里已经落地的记忆系统设计统一整理成一个入口文档，重点回答下面几个问题：

1. 记忆系统现在由哪些模块组成。
2. 一条记忆从“被发现”到“被写入”再到“被取回并喂给模型”会经过哪些阶段。
3. 分支、本地主线、用户偏好、项目事实之间的语义边界是什么。
4. 后续继续优化时，应该沿着哪些稳定接口演进，而不是重新发明一套并行机制。

## 1. 设计目标

当前记忆系统不是一个“通用知识库”，而是一套围绕 Agent 主路径服务的**执行记忆层**。它的目标是：

- 让长任务中的稳定信息不会被短期对话噪音淹没
- 让分支里验证出来的结论可以安全地回流主线
- 让不同 prompt mode 下，模型只看到当前真的有价值的那部分记忆
- 让显式 memory 工具与自动记忆链路遵守同一套语义规则

当前默认设计明确保持以下边界：

- 不引入向量库或 embedding 检索
- 不增加第二个“专门总结记忆”的模型
- 不改变现有 HTTP API / 前端 SDK / Web UI contract
- 不把 memory 设计成脱离 graph 主路径的平行系统

## 2. 核心组成

### 2.1 数据模型

核心模型定义在 `src/focus_agent/memory/models.py`：

- `MemoryKind`
  - `user_preference`
  - `user_profile`
  - `project_fact`
  - `turn_summary`
  - `branch_finding`
  - `imported_conclusion`
- `MemoryScope`
  - `user`
  - `root_thread`
  - `branch`
  - `project`
  - `skill`
- `MemoryVisibility`
  - `private`
  - `promotable`
  - `shared`

持久化对象分两类：

- `MemoryWriteRequest`
  - 写入前的结构化意图
- `MemoryRecord`
  - store 中的 durable 记录

两者都保留：

- `content`
- `summary`
- `tags`
- `evidence_refs`
- `source_thread_id`
- `source_branch_id`
- `root_thread_id`
- `user_id`
- `confidence`
- `importance`
- `promoted_to_main`
- `semantic_key`

这意味着当前系统已经把“文本内容”和“审计上下文”作为一等公民，而不是只存一条裸字符串。

### 2.2 Namespace 设计

namespace 定义在 `src/focus_agent/storage/namespaces.py`，是当前系统最重要的稳定边界之一：

- 用户画像：`("user", user_id, "profile")`
- 主线程 durable memory：`("conversation", root_thread_id, "main")`
- 主线程 episodic memory：`("conversation", root_thread_id, "episodic")`
- 主线程 semantic memory：`("conversation", root_thread_id, "semantic")`
- 分支本地 memory：`("conversation", root_thread_id, "branch", branch_id, "local_memory")`
- 分支 promotion 审计：`("conversation", root_thread_id, "branch", branch_id, "promoted_memory")`
- 项目级 memory：`("project", project_id, "memory")`
- skill 级 memory：`("skill", skill_id, "memory")`

当前实现里，namespace 不是“存储细节”，而是决定记忆权限、检索范围、promotion 行为和 prompt 呈现的核心语义层。

## 3. 主路径生命周期

当前 Agent 主路径中的 memory 生命周期固定为：

1. `retrieve_memory`
2. `assemble_context`
3. `agent_loop`
4. `extract_memories`
5. `write_memories`

对应入口在 `src/focus_agent/engine/graph_builder.py`。

### 3.1 检索阶段

`retrieve_memory` 负责从 `MemoryRetriever` 取回当前 turn 可能相关的 durable memory。

当前检索 query 不再只依赖最后一句用户输入，而是组合：

- `latest user query`
- `active_goal`
- `task_brief`
- 当前 `plan step goal`
- `PromptMode.SYNTHESIZE` 下最多少量 imported findings

检索之后会经过三层处理：

- rerank
- semantic / resolution 去重
- prompt-mode 过滤与 section budget

### 3.2 Prompt 注入阶段

`assemble_context` 不直接把 raw hits 喂给模型，而是消费：

- `retrieved_memories`
- `memory_prompt_block`

`memory_prompt_block` 由 `render_memory_block()` 生成，并通过 `<memory-context>` fence 注入 prompt。当前 memory block 已按区块组织：

- User preferences and profile
- Project facts
- Approved findings already safe to rely on
- Branch-local findings pending upstream approval
- Recent episodic context
- Other retrieved memories

这一步的目标不是“多给模型内容”，而是把 durable context 以更容易被模型使用的结构喂进去。

### 3.3 抽取阶段

`extract_memories` 在 turn 完成后调用 `MemoryExtractor.extract_from_turn()`。

当前 extractor 只负责**结构化抽取意图**，不直接决定一定写入什么 durable record。它现在的边界是：

- `user_preference`
  - 只从明确偏好表达里抽
  - 任务请求不应误判为偏好
- `user_profile`
  - 只从稳定自我描述里抽
- `project_fact`
  - 只从明显项目约定/规则/默认值里抽
- `branch_finding`
  - 只从显式 `branch_local_findings` 抽
  - 不从普通 AI 回答文本猜 finding
- `turn_summary`
  - 偏 episodic
  - 过滤低信号 ack/noise

### 3.4 写入阶段

`write_memories` 调用 `MemoryWriter.persist_records()`，由 `MemoryPolicy` 决定是否允许写入。

写入不再是简单 append，而是经过：

- policy 检查
- existing record 查找
- fingerprint / semantic key / resolution key 对齐
- merge / replace / skip

这让“写记忆”从单纯落盘升级成了有治理语义的 upsert。

## 4. 检索与排序设计

### 4.1 MemoryRetriever

`MemoryRetriever` 当前承担四件事：

1. 选择 candidate namespaces
2. 执行 namespace 级检索
3. 根据 query 与 prompt mode 重排
4. 按 resolution key 去重

### 4.2 去重语义

去重由 `dedupe.py` 里的三层键支撑：

- `fingerprint`
  - 严格等价写入
- `semantic_key`
  - 语义相同但可能跨 namespace / 跨 promotion
- `resolution_key`
  - 用于“同主题应该只保留一个最终值”的场景

目前最关键的 resolution 规则有：

- 同主题 `user_preference` 只保留最新有效值
- branch-local finding 与 promoted main finding 检索时应优先主线版本

### 4.3 PromptMode 感知

`MemoryPolicy.filter_bundle_for_prompt()` 现在已经按 `PromptMode` 做 section priority 和 section budget：

- `SYNTHESIZE`
  - 优先 `user / project / approved`
  - 禁止未 promotion 的 `branch_finding`
- `BRANCH_REVIEW`
  - 优先 `branch-local findings`
  - 允许少量 approved/main finding 作为对照
- `EXECUTE`
  - 更偏向 `user / project / approved`
- `EXPLORE`
  - 保留更多 `approved + branch` 混合上下文

这意味着“同一套记忆”在不同模式下不是简单裁剪，而是**有不同阅读视角**。

## 5. 写入与冲突治理

### 5.1 MemoryWriter

`MemoryWriter` 当前负责：

- `write_records`
- `persist_records`
- `write_turn_summary`
- `write_branch_findings`
- `write_imported_conclusion`
- `promote_branch_findings`

其中真正的治理发生在 `_upsert_record()` 和 `_find_existing_record()`。

### 5.2 现有冲突规则

当前已经明确的规则包括：

- 同主题 `user_preference`
  - 新值覆盖旧值
- `project_fact`
  - 只有出现显式纠正语义且主题重叠时才替换
- `turn_summary`
  - 默认保持私有、episodic、低优先级
  - 不参与 durable fact 冲突竞争
- `branch_finding`
  - branch-local 与 promoted-main 在检索层面做 semantic 对齐

### 5.3 为什么不直接把所有东西都 merge

因为当前设计不是为了“最大化保留信息”，而是为了控制 prompt 污染和长期语义漂移。

如果把：

- 旧偏好
- 新偏好
- branch-local finding
- promoted finding
- 临时总结

全都一股脑地 merge，最终只会把记忆层重新变成另一条无边界对话历史。

## 6. 分支与主线的 promotion 语义

这是当前记忆系统里最关键的一条业务规则。

### 6.1 branch-local 与 main durable memory 的边界

当前分支 memory 分成两层：

- branch-local findings
  - 仅属于分支
  - 供 branch review 与 branch exploration 使用
- root main durable memory
  - 只有被批准后才进入

### 6.2 进入主线的门槛

当前 `branch -> main` durable memory promotion 已经收紧为：

- 只有 `merge_importable=True` 的 finding 才允许进入主线 durable memory
- nested parent merge 不得污染 root main durable memory
- target 为 `ROOT_THREAD` 时才允许把 branch findings 真正 promotion 到 root main durable memory

### 6.3 审计信息

主线 promotion 现在会保留：

- `promoted_to_main`
- `source_branch_id`
- `source_thread_id`
- `root_thread_id`
- `tags`

并且已经有一份 branch promoted memory audit namespace，用来记录分支层面的 promotion 轨迹。

这让主线 durable memory 不再只是“一个结论文本”，而是带来源、带路径、带 promotion 语义的可追溯记录。

## 7. 显式 Memory Tools 与自动记忆的一致性

当前仓库里有三类显式 memory tool：

- `memory_save`
- `memory_search`
- `memory_forget`

现在这三者已经不再绕开自动记忆系统的语义。

### 7.1 `memory_save`

当前行为：

- 按 `kind + scope` 推导默认 `visibility`
- 按 `kind + scope` 推导默认 namespace
- 通过 `MemoryWriter` 的 upsert / dedupe / replace 语义保存

意味着显式保存一条用户偏好，不会和自动记忆走两套互相矛盾的规则。

### 7.2 `memory_search`

当前行为：

- 不再直接裸调 `store.search`
- 复用 `MemoryRetriever` 的 query / rerank / dedupe 逻辑

意味着显式检索看到的结果顺序和 agent 自己在 turn 内部看到的 durable memory 更一致。

### 7.3 `memory_forget`

当前仍是按 id 删除，但 namespace 选择会先走默认 namespace 解析，再逐个查找。

当前这一层还算保守，后续可以继续增强成：

- soft delete
- audit trail
- resolution-key 级 forget

但本轮没有改成 destructive-first 以外的行为。

## 8. 与 State / Prompt / Merge 的接口

当前记忆系统与 graph 的接口已经很明确：

- `retrieved_memories`
  - 当前 turn 的 durable retrieval snapshot
- `memory_prompt_block`
  - 注入模型前的 memory 渲染结果
- `memory_write_requests`
  - 待写入 memory 的结构化队列
- `memory_write_result`
  - 本轮写入结果
- `branch_local_findings`
  - 分支局部 finding
- `imported_findings`
  - 已批准导入的 finding
- `merge_queue`
  - 向后兼容的 imported branch payload

这几个字段在 `core/state.py` 里已经被明确标成：

- 谁写
- 谁读
- 是否允许 merge-import

所以后续继续优化时，优先沿这些字段扩展，不要另起一套平行 state wire。

## 9. 当前测试与回归面

当前和记忆系统直接相关的回归面已经包括：

- `tests/test_memory_models.py`
- `tests/test_memory_pipeline.py`
- `tests/test_memory_retriever.py`
- `tests/test_memory_extractor.py`
- `tests/test_memory_namespace.py`
- `tests/test_context_policy.py`
- `tests/test_branch_conclusion_policy.py`
- `tests/test_default_tools.py`
- `tests/eval/test_memory_suite.py`
- `tests/eval/datasets/memory.jsonl`

这意味着当前记忆设计已经不仅有单元测试，还有行为级 regression suite。

## 10. 后续优化建议

基于当前实现，后续继续优化应优先沿下面几条线推进：

1. **promotion 元数据继续结构化**
   - 现在 `merge mode / target` 主要体现在 tags
   - 下一步可以提升成更显式、可检索的 memory 元字段
2. **memory_forget 审计化**
   - 当前删除还偏直接
   - 后续适合做 soft delete / audit trail
3. **long observation -> artifact 化**
   - 继续减少 prompt 污染
4. **memory retrieval query 再细化**
   - 当前已经组合了 `active_goal / task_brief / current_step`
   - 后续可按 scene / branch role 再细化
5. **branch / merge / memory 语义对齐**
   - 继续减少“线程状态已导入，但 durable memory 还没进入主线”这类灰区

## 11. 文件导航

如果要继续沿当前设计扩展，优先从下面这些文件入手：

- `src/focus_agent/engine/graph_builder.py`
- `src/focus_agent/core/state.py`
- `src/focus_agent/core/context_policy.py`
- `src/focus_agent/memory/models.py`
- `src/focus_agent/memory/retriever.py`
- `src/focus_agent/memory/policy.py`
- `src/focus_agent/memory/writer.py`
- `src/focus_agent/memory/extractor.py`
- `src/focus_agent/services/branches.py`
- `src/focus_agent/capabilities/default_tools.py`

这套文件基本就是当前记忆系统的完整骨架。
