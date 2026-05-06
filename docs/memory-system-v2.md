# Focus Agent Memory System v2

更新时间：2026-05-06

本文是 PostgreSQL canonical memory 架构的系统设计文档。它描述当前仓库中的真实实现，而不是未来设想。旧版 `docs/memory-system.md` 仍可作为演进背景阅读；本文件重点整理 v2 后的设计边界、数据模型、运行时链路、审计治理和后续风险。

## 1. 定位

Memory v2 是 Agent graph 主路径内的执行记忆层，用于把对后续 turn 有价值的信息保存为可检索、可审计、可治理的 durable memory。它不是通用知识库，也不是脱离 agent 的独立知识服务。

核心定位：

- 保存用户偏好、用户画像、项目事实、turn summary、分支 finding、已导入结论等长期或半长期上下文。
- 在 turn 开始前检索可见 memory，渲染为 `<memory-context>`，再进入 context assembly 和模型调用。
- 在稳定 turn 结束后做保守启发式抽取，经 `MemoryPolicy` 和 `MemoryService` 写入 canonical store。
- 分支和多 agent 产生的候选默认隔离，只有 merge/promotion 语义确认后才进入主线可依赖 memory。
- PostgreSQL 独立业务表是生产 canonical storage；LangGraph Store 保留给 checkpoint/graph 兼容路径和本地 fallback。

当前明确不做：

- 不引入 mandatory vector database。
- 不依赖 embedding retrieval。
- 不增加专用 memory summarizer model。
- 不把 Markdown snapshot 当运行时事实源。
- 不提供普通 HTTP create/update memory；HTTP surface 目前是 list/detail/audit/candidates/forget。
- 不改变 Agent Team / Mission Runner 公共 API、UI、任务模型。

## 2. 架构总览

```mermaid
flowchart TD
    User["User turn"] --> Graph["LangGraph turn"]
    Graph --> Retrieve["retrieve_memory"]
    Retrieve --> RepoSearch["MemoryRepository.search"]
    RepoSearch --> Postgres["focus_memories"]
    Retrieve --> Plan["MemoryRetrievalPlan"]
    Retrieve --> Block["render_memory_block"]
    Block --> Assemble["assemble_context"]
    Assemble --> Model["agent_loop / tool loop"]
    Model --> Summary["summarize_turn"]
    Summary --> Extract["extract_memories"]
    Extract --> Requests["MemoryWriteRequest[]"]
    Requests --> Writer["MemoryWriter.persist_records"]
    Writer --> Service["MemoryService"]
    Service --> Policy["MemoryPolicy"]
    Service --> Audit["focus_memory_audit_events"]
    Service --> Memories["focus_memories"]
    Service --> Tombstones["focus_memory_tombstones"]
    Model --> Tools["memory_save / memory_search / memory_forget"]
    Tools --> Service
    Tools --> RepoSearch
    Branch["Branch / subagent finding"] --> Candidates["focus_memory_candidates"]
    Branch --> Curator["MemoryCurator"]
    Curator --> Memories
```

主要模块：

| 文件 | 责任 |
| --- | --- |
| `src/focus_agent/memory/models.py` | Pydantic memory 数据模型、状态枚举、写入决策、检索计划。 |
| `src/focus_agent/memory/service.py` | repository-backed 写入治理、upsert、冲突、脱敏、forget、audit。 |
| `src/focus_agent/repositories/memory_repository.py` | canonical memory repository protocol。 |
| `src/focus_agent/repositories/postgres_memory_repository.py` | PostgreSQL 实现，读写 `focus_memories` 等业务表。 |
| `src/focus_agent/repositories/postgres_schema.py` | schema v8，创建 memory/audit/tombstone/candidate 表和索引。 |
| `src/focus_agent/memory/retriever.py` | namespace 选择、query 构造、repository search、rerank、dedupe、retrieval plan。 |
| `src/focus_agent/memory/policy.py` | 自动写入准入、读取 namespace、PromptMode 过滤和 section budget。 |
| `src/focus_agent/memory/writer.py` | graph 写入适配器；Postgres 模式委托 `MemoryService`，local fallback 保留 legacy store。 |
| `src/focus_agent/memory/extractor.py` | 稳定 turn 后的启发式候选抽取。 |
| `src/focus_agent/memory/assembler.py` | `<memory-context>` 渲染和 prompt injection guard。 |
| `src/focus_agent/memory/curator.py` | branch finding promotion 前的冲突检查和候选治理。 |
| `src/focus_agent/capabilities/default_tool_modules/memory.py` | agent-visible `memory_save/search/forget` tools。 |
| `src/focus_agent/api/routers/memory.py` | memory console 用 HTTP list/detail/audit/candidates/forget surface。 |
| `src/focus_agent/migrate_local_state.py` | legacy LangGraph Store memory backfill 到 `focus_memories`。 |

## 3. 数据模型

所有 core memory model 都继承 `MemoryModel`，并使用 `extra="forbid"`。这和 repository 的 `data_json` round-trip 配合，避免持久化 payload 静默漂移。

### 3.1 MemoryKind

| kind | 语义 | 当前写入来源 |
| --- | --- | --- |
| `user_preference` | 用户输出偏好、语言、称呼、回答风格。 | 启发式抽取、`memory_save`。 |
| `user_profile` | 用户稳定自我描述，例如身份、习惯、熟悉程度。 | 启发式抽取、`memory_save`。 |
| `project_fact` | 项目规则、约定、默认配置、架构事实。 | `active_goal` 启发式抽取、`memory_save`。 |
| `turn_summary` | 最近 turn 的 episodic 摘要。 | 稳定 turn 后自动抽取。 |
| `branch_finding` | 分支内验证出的结论。 | `branch_local_findings`、branch promotion。 |
| `imported_conclusion` | merge/import 后写入主线的结论。 | Branch merge/import workflow。 |
| `artifact` | artifact 长期记忆预留类型。 | 枚举和 API surface 已有，自动链路尚未大规模使用。 |
| `citation` | citation 长期记忆预留类型。 | 枚举和 API surface 已有，自动链路尚未大规模使用。 |
| `tool_observation` | tool observation 长期记忆预留类型。 | 枚举和 API surface 已有，自动链路尚未大规模使用。 |

### 3.2 Scope、Visibility、Status

`MemoryScope` 决定归属边界：

- `user`：用户级 profile namespace。
- `root_thread`：根线程级 conversation main / episodic / semantic namespace。
- `branch`：分支级 local memory。
- `project`：项目级 memory。
- `skill`：skill 级 memory。

`MemoryVisibility` 决定依赖强度：

- `private`：默认私有或低优先级，例如 `turn_summary`。
- `promotable`：可以被 promotion，但还不是主线 approved memory。
- `shared`：可以在对应作用域中作为稳定背景使用。

`MemoryStatus` 决定生命周期：

- `active`：可检索、可注入 prompt。
- `conflict`：被写入治理标记为冲突，不参与默认检索。
- `needs_review`：候选或治理状态，等待人工/merge 决策。
- `forgotten`：soft forget 后状态，带 tombstone。
- `discarded`：候选或治理状态，表示不进入主线。

### 3.3 Durable Record

`MemoryRecord` 是 durable record，关键字段包括：

- `memory_id`
- `kind/scope/visibility/status`
- `namespace`
- `content/summary`
- `tags/evidence_refs`
- `source_thread_id/source_branch_id/root_thread_id/user_id`
- `confidence/importance`
- `promoted_to_main`
- `fingerprint/semantic_key`
- `created_at/updated_at/deleted_at`

`content` 保留事实内容，`summary` 优先用于 prompt、检索和控制台展示。`fingerprint` 用于物理等价去重，`semantic_key` 用于同主题合并和冲突判断。

### 3.4 Write Decision、Audit、Candidate、Retrieval Plan

`MemoryWriteDecision` 是统一写入结果：

- `accepted`
- `merged`
- `skipped`
- `conflict`
- `requires_review`
- `forgotten`
- `failed`

它包含 `memory_id`、`audit_id`、`tombstone_id`、`action`、`reason` 和 `redacted_payload`。

`MemoryAuditEvent` 是 append-only 审计事件。当前写入、policy skip、merge、possible conflict、forget 都会通过 repository 记录 audit。

`MemoryCandidate` 是多 agent / branch 待审记忆候选。当前表、repository、API、Web 列表已存在；默认 graph 主路径还没有把所有 subagent candidate 全量接入 promotion board。

`MemoryRetrievalPlan` 记录一次 retrieval 的 query、namespaces、filters、prompt-visible selected memory ids、budget reason 和 source。它会写入 `AgentState.memory_retrieval_plan`。

## 4. PostgreSQL Canonical Storage

Schema v8 创建四张 memory 表：

| 表 | 用途 |
| --- | --- |
| `focus_memories` | canonical durable memory。 |
| `focus_memory_audit_events` | append-only audit trail。 |
| `focus_memory_tombstones` | soft forget tombstone。 |
| `focus_memory_candidates` | multi-agent / branch candidate board。 |

```mermaid
erDiagram
    focus_memories {
        text memory_id PK
        text_array namespace
        text kind
        text scope
        text visibility
        text status
        text user_id
        text root_thread_id
        text source_thread_id
        text source_branch_id
        text semantic_key
        text fingerprint
        float confidence
        float importance
        text summary
        text content
        boolean promoted_to_main
        timestamptz created_at
        timestamptz updated_at
        timestamptz deleted_at
        jsonb data_json
    }
    focus_memory_audit_events {
        text event_id PK
        text action
        text decision
        text memory_id
        text candidate_id
        text actor
        text reason
        text_array namespace
        jsonb data_json
    }
    focus_memory_tombstones {
        text tombstone_id PK
        text memory_id UK
        text_array namespace
        text semantic_key
        text fingerprint
        text actor
        text reason
        jsonb data_json
    }
    focus_memory_candidates {
        text candidate_id PK
        text status
        text agent_id
        text task_id
        text branch_id
        text root_thread_id
        text user_id
        text_array evidence_refs
        jsonb data_json
    }
```

`focus_memories.data_json` 保存完整 Pydantic payload；索引列用于过滤、排序、检索和运营查询。这样既保留模型 round-trip，又避免把所有业务查询压在不透明 JSONB 上。

重要索引：

- `(namespace, status, updated_at DESC)`
- `(kind, scope, visibility)`
- `(user_id, updated_at DESC)`
- `(root_thread_id, updated_at DESC)`
- `(source_branch_id, updated_at DESC)`
- partial unique `(namespace, fingerprint)` where not forgotten/deleted
- `semantic_key`
- `GIN to_tsvector('simple', summary || content)`

当前检索是 PostgreSQL FTS + `ILIKE` fallback。`AGENT_MEMORY_POSTGRES_TRIGRAM_ENABLED` 已作为配置位存在，但 `pg_trgm` 不是当前启动硬依赖。

## 5. Runtime Backend

```mermaid
flowchart TD
    Settings["Settings"] --> HasDb{"DATABASE_URI set?"}
    HasDb -- "yes" --> Pg["PostgresSaver + PostgresStore + PostgresMemoryRepository"]
    HasDb -- "no" --> Local["PersistentInMemorySaver + PersistentInMemoryStore"]
    Pg --> Runtime["AppRuntime"]
    Local --> Runtime
    Runtime --> Retriever["MemoryRetriever(store, repository?)"]
    Runtime --> Writer["MemoryWriter(store, repository?)"]
    Runtime --> Tools["Tool registry memory tools"]
    Runtime --> API["Memory API"]
    Retriever --> RepoPath{"repository available?"}
    RepoPath -- "yes" --> Canonical["focus_memories"]
    RepoPath -- "no" --> Legacy["LangGraph Store fallback"]
```

真实选择逻辑：

- 有 `DATABASE_URI`：初始化 `PostgresMemoryRepository`，并注入 retriever/writer/tool registry/API。
- 无 `DATABASE_URI`：`runtime.memory_repository=None`，memory 走 legacy LangGraph Store fallback。
- readiness 会在 Postgres 模式下检查 `memory_repository`，本地模式下标记 `local_fallback`。

配置项：

| 配置 | 默认 | 当前真实含义 |
| --- | --- | --- |
| `AGENT_MEMORY_BACKEND` | `postgres` | 已解析，但 runtime 选择目前仍主要由 `DATABASE_URI` 决定。 |
| `AGENT_MEMORY_READ_SOURCE` | `postgres` | 已解析，当前 retriever 是 repository 优先、无 repository 时 legacy fallback。 |
| `AGENT_MEMORY_EXTRACTOR_MODE` | `heuristic` | `off` 会关闭自动抽取。 |
| `AGENT_MEMORY_POSTGRES_TRIGRAM_ENABLED` | `false` | 预留/可选增强配置位。 |
| `AGENT_MEMORY_APPROVAL_FOR_SHARED_WRITES` | `false` | 预留审批策略配置位；完整审批应继续接入 tool approval/governance。 |
| `AGENT_MEMORY_CURATOR_ENABLED` | `false` | 是否启用 branch promotion curator。 |
| `AGENT_MEMORY_AUTO_PROMOTE_ON_MERGE` | `true` | curator enabled 时是否自动写入无冲突候选。 |

## 6. Namespace 与隔离

Namespace 是权限、检索、promotion、审计的第一层边界。它不是简单存储路径。

| Namespace helper | 语义 |
| --- | --- |
| `user_profile_namespace(user_id)` | 用户偏好/画像。 |
| `conversation_main_namespace(root_thread_id)` | 主线可依赖 memory。 |
| `root_thread_episodic_namespace(root_thread_id)` | turn summary 等 episodic context。 |
| `root_thread_semantic_namespace(root_thread_id)` | 语义 namespace，目前读取纳入候选，自动写入较少。 |
| `branch_local_memory_namespace(root_thread_id, branch_id)` | 分支本地 finding。 |
| `branch_promoted_memory_namespace(root_thread_id, branch_id)` | promotion 审计辅助 namespace。 |
| `project_memory_namespace(project_id)` | 项目事实。 |
| `skill_memory_namespace(skill_id)` | skill memory。 |

读取范围由 `MemoryPolicy.allowed_namespaces_for_read()` 决定：

```mermaid
flowchart TD
    Context["RequestContext"] --> Base["root main + root semantic + root episodic + user profile"]
    Context --> HasBranch{"branch_id?"}
    Context --> HasProject{"project_id?"}
    Context --> SkillHints{"skill_hints?"}
    HasBranch -- "yes" --> BranchLocal["branch local memory"]
    HasProject -- "yes" --> Project["project memory"]
    SkillHints -- "yes" --> Skill["skill memory"]
    Base --> Candidates["read namespaces"]
    BranchLocal --> Candidates
    Project --> Candidates
    Skill --> Candidates
```

写入 namespace 由 `MemoryWriteRequest.namespace` 明确携带，再由 `MemoryPolicy.should_persist()` 校验。显式 tool 写入可绕过自动链路 policy，但仍进入 `MemoryService`、dedupe、audit 和 redaction。

## 7. Turn 生命周期

```mermaid
sequenceDiagram
    participant User
    participant Graph
    participant Retriever as MemoryRetriever
    participant Policy as MemoryPolicy
    participant Model
    participant Extractor as MemoryExtractor
    participant Writer as MemoryWriter
    participant Service as MemoryService
    participant Repo as PostgresMemoryRepository

    User->>Graph: message
    Graph->>Retriever: retrieve_for_turn(context,state,query,prompt_mode)
    Retriever->>Repo: search(namespace, query)
    Retriever->>Policy: filter_bundle_for_prompt()
    Retriever-->>Graph: RetrievedMemoryBundle + MemoryRetrievalPlan
    Graph->>Model: assembled_context with memory block
    Model-->>Graph: final answer / tools / findings
    Graph->>Extractor: extract_from_turn()
    Extractor-->>Graph: MemoryWriteRequest[]
    Graph->>Writer: persist_records()
    Writer->>Service: persist_records()
    Service->>Policy: should_persist()
    Service->>Repo: find_existing / upsert_record
    Service->>Repo: append_audit_event
```

Graph 节点顺序：

```text
bootstrap_turn
-> retrieve_memory
-> assemble_context
-> plan_and_reflect / agent_loop / tool loop
-> summarize_turn
-> extract_memories
-> write_memories
-> maybe_interrupt_for_merge
```

`retrieve_memory` 写入：

- `retrieved_memories`
- `memory_prompt_block`
- `memory_retrieval_plan`
- `prompt_mode`

`extract_memories` 只在稳定 turn 后运行。稳定条件包括：不是 reflection replan，有 messages，最后一条 AIMessage 不带未完成 tool calls，且存在 final assistant 文本。

`write_memories` 调用 `MemoryWriter.persist_records()`。Postgres 模式下 writer 委托 `MemoryService.persist_records()`；local fallback 模式下保留 legacy store upsert。

## 8. 检索与 Prompt 注入

`MemoryRetriever` 不只使用最后一句 user query。它会组合：

- 当前 user query。
- `active_goal`。
- `task_brief`。
- 当前 plan step goal。
- `PromptMode.SYNTHESIZE` 下最多前两条 imported findings。

组合 query 截断到 240 字符。

检索流程：

```mermaid
flowchart TD
    Query["build retrieval query"] --> Namespaces["allowed namespaces"]
    Namespaces --> Search["repository.search per namespace"]
    Search --> Hits["MemorySearchHit[]"]
    Hits --> Rerank["score_memory_hit"]
    Rerank --> Dedupe["memory_resolution_key dedupe"]
    Dedupe --> PromptPolicy["PromptMode filter + section budget"]
    PromptPolicy --> Plan["MemoryRetrievalPlan selected_memory_ids"]
    PromptPolicy --> Render["render_memory_block"]
```

Prompt 过滤：

- 默认只保留 `status=active` 且 `deleted_at is None`。
- `SYNTHESIZE` 隐藏未 promoted branch-local finding。
- `PromptMode` 决定 user/project/approved/branch/episodic/other 的 section priority 和 section budget。
- `MemoryRetrievalPlan.selected_memory_ids` 记录 policy/filter/budget 后真正进入 prompt 的 memory ids。

`render_memory_block()` 会输出 `<memory-context>` fenced block。`sanitize_memory_text()` 会移除伪造 `<memory-context>` 标签，并过滤常见 prompt injection / secret exfiltration 片段。Memory 是 recalled background context，不是 system/developer/user 指令，不能覆盖当前指令层级。

## 9. 写入治理

### 9.1 自动写入

自动写入入口是 `MemoryWriter.persist_records()`。

```mermaid
flowchart TD
    Request["MemoryWriteRequest"] --> Persist["MemoryWriter.persist_records"]
    Persist --> Service["MemoryService.persist_records"]
    Service --> Policy["MemoryPolicy.should_persist"]
    Policy -- "reject" --> Skip["MemoryWriteDecision skipped + audit"]
    Policy -- "allow" --> Upsert["MemoryService.upsert_request"]
    Upsert --> Existing["repository.find_existing"]
    Existing -- "none" --> Accepted["accepted / written"]
    Existing -- "duplicate" --> Merged["merged"]
    Existing -- "possible conflict" --> Conflict["conflict"]
    Accepted --> Repo["focus_memories"]
    Merged --> Repo
    Conflict --> Repo
    Accepted --> Audit["focus_memory_audit_events"]
    Merged --> Audit
    Conflict --> Audit
    Skip --> Audit
```

`MemoryPolicy.should_persist()` 当前约束：

- `content` 和 `summary` 不能为空。
- `importance >= 0.5`。
- `content` 不超过 4000 字符。
- turn 必须稳定。
- user scope 只允许 `user_preference/user_profile` 写入当前 user profile namespace。
- project scope 只允许 `project_fact` 写入当前 project namespace。
- root thread scope 只允许 `turn_summary/imported_conclusion` 写入 root episodic 或 conversation main。
- branch scope 只允许 `branch_finding` 写入当前 branch local memory。

### 9.2 直接写入 Helper

`MemoryWriter.write_records()` 和 `MemoryService.write_records()` 是直接写入 helper。它们不执行 `MemoryPolicy.should_persist()`，但仍会进入 `MemoryService.upsert_request()`，因此保留 redaction、dedupe、merge/conflict 和 audit。

当前直接写入主要用于系统已明确授权的路径：

- turn summary 的 writer helper。
- branch local finding 写入。
- imported conclusion 写入。
- branch finding promotion。

这些路径的前置治理来自 branch/merge/runtime 语义，而不是自动抽取 policy gate。新增产品路径若需要写 shared/root/project memory，应优先走 `persist_records()` 或在调用 `write_records()` 前明确完成权限、审批和 promotion 判断。

### 9.3 显式写入

`memory_save` 是显式 tool 能力。它不经过自动链路的 `persist_records()` policy gate，但 repository 模式下仍调用 `MemoryService.upsert_request()`，因此仍有：

- redaction
- find_existing
- merge/conflict
- audit
- canonical repository write

在 graph 执行路径中，`graph_tool_executor_node` 会先调用 `authorize_memory_tool_args()` 绑定当前 `RequestContext`：

- 未传 `user_id/root_thread_id` 时自动使用当前 context。
- 传入不匹配的 `user_id/root_thread_id` 会返回结构化 ToolMessage error，工具不会执行。
- 显式 `namespace` 只允许当前 user profile、当前 root main/episodic、当前 branch local/promoted、当前 project namespace。
- 无 `project_id` 时不搜索或写入 `project/default`；skill namespace 暂不开放给显式 memory tools。

直接调用 tool 的 legacy/local 测试路径仍保留旧参数形态；生产 graph path 以 runtime context 为准。

### 9.4 去重、合并与冲突

匹配依据：

- `memory_fingerprint()`
- `memory_semantic_key()`
- normalized summary/content
- `memory_resolution_key()`

用户偏好同主题倾向 latest wins。项目事实如果同 semantic key 但缺少纠正信号或文本重叠，可能被标记为 `conflict`，避免静默覆盖。

### 9.5 敏感内容脱敏

`MemoryService` 在写入前会对 `content` 和 `summary` 做基础敏感扫描：

- OpenAI/Slack 风格 token 片段。
- `api key`、`token`、`secret`、`password` 等键值片段。
- email address。

命中后替换为 `[redacted]`，并添加 `redacted` tag。Audit 和 `MemoryWriteDecision.redacted_payload` 只记录脱敏 payload。

## 10. Forget 与 Tombstone

`memory_forget` 和 `POST /v1/memory/{memory_id}/forget` 都走 `MemoryService.forget()`。

```mermaid
flowchart TD
    Forget["forget request"] --> Service["MemoryService.forget"]
    Service --> Existing["repository.get_record"]
    Service --> RepoForget["repository.forget_record"]
    RepoForget --> Mark["focus_memories.status=forgotten + deleted_at"]
    RepoForget --> Tombstone["focus_memory_tombstones"]
    Service --> Audit["focus_memory_audit_events"]
    Service --> Decision["MemoryWriteDecision forgotten/skipped"]
```

Forget 是 tombstone + payload erasure：

- `focus_memories.status` 改为 `forgotten`。
- `deleted_at` 置为当前时间。
- `content` 清空，`summary` 变为 `[forgotten]`，`data_json.content/summary/status/deleted_at` 同步更新。
- `focus_memory_tombstones` 写 tombstone。
- audit event 记录 actor/reason/tombstone id，并回填 existing record 的 user/thread/branch metadata。

默认 list/search 不返回 forgotten memory；显式 `status=forgotten` 列表可以看到 tombstone 状态，但 API/SDK/Web 不展示旧正文，`payload_redacted=true`。

## 11. Branch、Promotion 与 Candidate

分支 finding 默认不污染主线。

```mermaid
flowchart LR
    BranchTurn["branch turn"] --> LocalFinding["branch_local_findings"]
    LocalFinding --> BranchMemory["branch local memory"]
    BranchMemory --> Merge{"merge/import approved?"}
    Merge -- "no" --> Stay["stay branch-local"]
    Merge -- "yes" --> Importable{"merge_importable?"}
    Importable -- "no" --> NotPromoted["not promoted"]
    Importable -- "yes" --> Curator{"MemoryCurator enabled?"}
    Curator -- "no" --> Promote["write shared root_thread memory"]
    Curator -- "yes" --> Conflict{"semantic conflict?"}
    Conflict -- "yes" --> Review["needs_review"]
    Conflict -- "no" --> Auto{"auto_promote?"}
    Auto -- "yes" --> Promote
    Auto -- "no" --> DecisionOnly["decision only"]
    Promote --> Main["conversation main memory"]
```

`MemoryCurator` 会在 conversation main namespace 中搜索 existing memory。冲突条件包括：

- semantic key 相同但 summary 不同。
- existing branch finding 与 candidate 文本重叠但归一化内容不同。

`focus_memory_candidates` 是多 agent / branch candidate board。当前 repository、API、SDK、Web 已支持 candidate list 和 status update repository 方法；更完整的 subagent candidate promotion flow 仍是后续扩展点。

## 12. Explicit Memory Tools

三个 agent-visible tools：

| Tool | Side effect | Parallel safe | Postgres 行为 |
| --- | --- | --- | --- |
| `memory_save` | yes | no | `MemoryService.upsert_request` + audit。 |
| `memory_search` | no | yes | `MemoryRetriever(repository=...)` search/rerank/dedupe。 |
| `memory_forget` | yes | no | `MemoryService.forget` + tombstone + audit。 |

```mermaid
sequenceDiagram
    participant Model
    participant Tool
    participant Service as MemoryService
    participant Retriever as MemoryRetriever
    participant Repo as PostgresMemoryRepository

    Model->>Tool: memory_save(content, kind, scope)
    Tool->>Service: upsert_request(actor=memory_save_tool)
    Service->>Repo: find_existing + upsert_record + audit
    Tool-->>Model: JSON memory_id/action

    Model->>Tool: memory_search(query)
    Tool->>Retriever: _search_namespace + rerank + dedupe
    Retriever->>Repo: search
    Tool-->>Model: JSON results

    Model->>Tool: memory_forget(memory_id)
    Tool->>Service: forget(actor=memory_forget_tool)
    Service->>Repo: status=forgotten + tombstone + audit
    Tool-->>Model: JSON deleted/namespace
```

Local fallback 下，这些 tools 保留 legacy LangGraph Store path。

重要边界：

- graph path 的 `memory_save/search/forget` 参数由当前 `RequestContext` 绑定，不允许模型自由跨 user/root/namespace。
- `memory_search` 默认读取当前 user profile 和当前 root main/episodic；只有 context 有 `branch_id/project_id` 时才加入当前 branch/project namespace。
- local fallback 的 `memory_forget` 仍是 store delete，没有 Postgres tombstone；生产 canonical 行为以 Postgres 为准。

## 13. API、SDK 与 Web Console

HTTP surface：

- `GET /v1/memory`
- `GET /v1/memory/{memory_id}`
- `GET /v1/memory/audit`
- `GET /v1/memory/{memory_id}/audit`
- `POST /v1/memory/{memory_id}/forget`
- `GET /v1/memory/candidates`

SDK helpers：

- `listMemoryRecords()`
- `getMemoryRecord()`
- `listMemoryAuditEvents()`
- `listMemoryRecordAuditEvents()`
- `forgetMemoryRecord()`
- `listMemoryCandidates()`

Web surface：

- `/agent/memory`
- records list
- record detail
- audit list
- candidates list
- kind/status/visibility/root thread filters
- forget action

重要边界：

- HTTP/API 是审计和治理 surface，不是普通 memory create/update REST resource。
- `memory_save/search/forget` 仍是 agent tool surface。
- local fallback 时 API list 类 endpoint 返回 `available=false`，forget 返回 503。
- auth enabled 时，普通 principal 只能列出自己的 `user_id` memory；显式查询其他 `user_id` 会返回 403。
- detail、record audit 和 forget 会先按 `memory_id` 读取 record，再校验 user/thread/branch/project ownership；不属于当前 principal 的 record 对外表现为 404。
- global memory/audit/candidate/forget 使用持久化 `AuthContext` role permissions：`memory:read`、`memory:audit`、`memory:forget`。仅 bearer token scope 不授予全局 memory 视图。
- `MemoryRecordResponse.payload_redacted=true` 表示正文不可用；forgotten record 返回 `content=""`、`summary="[forgotten]"`。

## 14. Migration

`focus-agent-migrate-local-state` 增加了 `focus-memories` step。

```mermaid
flowchart TD
    Local["local LangGraph Store pickle"] --> Scan["scan LocalStoreItemRecord"]
    Scan --> Parse["legacy payload parser"]
    Parse --> Valid{"recognized MemoryKind and content?"}
    Valid -- "no" --> Skip["skipped reason"]
    Valid -- "yes" --> Record["MemoryRecord"]
    Record --> Fingerprint["fingerprint / semantic_key"]
    Fingerprint --> Repo["PostgresMemoryRepository.upsert_record"]
    Repo --> Report["migration report"]
```

迁移特性：

- deterministic legacy id：没有 explicit `memory_id` 时用 namespace + key 生成稳定 id。
- 幂等：重复迁移走 `upsert_record`。
- dry-run 只解析和计数，不写 Postgres。
- schema v9 会幂等清理历史 forgotten rows，把遗留 `content/summary/data_json` 正文替换为空正文和 `[forgotten]` 摘要。
- tombstone 防回填仍需在更完整 dual read/backfill 阶段继续补强。

## 15. Observability 与 AgentState

Memory 相关 AgentState 字段：

| 字段 | 语义 |
| --- | --- |
| `retrieved_memories` | 当前 turn 检索快照。 |
| `memory_prompt_block` | 当前 turn 注入模型的 memory block。 |
| `memory_retrieval_plan` | 检索 query、namespaces、filters、prompt-visible selected ids、source。 |
| `memory_write_requests` | 自动抽取后的临时写入队列。 |
| `memory_write_result` | 写入 outcome；repository 模式包含 decisions。 |
| `memory_curator_decision` | branch promotion curator 的 legacy mirror。 |
| `branch_local_findings` | 分支内 finding 输入。 |
| `imported_findings` | 主线导入 finding。 |
| `rolling_summary` | context 连续性摘要，不是 durable memory。 |

`governance_records` 是更通用的治理/观测 envelope。Memory v2 已把 retrieval plan 和 write decisions 结构化，但还有进一步把 memory metrics/API 投影完全 record-first 的空间。

## 16. 测试覆盖

关键测试：

- `tests/test_memory_models.py`
- `tests/test_memory_pipeline.py`
- `tests/test_memory_retriever.py`
- `tests/test_memory_extractor.py`
- `tests/test_memory_namespace.py`
- `tests/test_memory_service.py`
- `tests/test_memory_api.py`
- `tests/test_postgres_memory_repository.py`
- `tests/test_default_tools.py`
- `tests/test_runtime_backend_selection.py`
- `tests/test_migrate_local_state.py`
- `tests/eval/test_memory_suite.py`
- `scripts/memory_context_eval.py`

覆盖主题：

- Pydantic model default 和 `extra=forbid`。
- fingerprint、semantic key、resolution key。
- repository upsert/search/list/forget/audit/candidates。
- service redaction、merge、conflict、tombstone、policy skip decision。
- retriever repository 优先、CJK matched terms、prompt-visible retrieval plan。
- writer/tool runtime Postgres path 和 local fallback。
- runtime 在 Postgres/local 模式下的组件注入。
- legacy store memory backfill。
- memory eval suite 和 context eval trend。

## 17. 编码规范检查结论

当前服务端实现总体符合仓库风格：

- 手写 SQL 使用参数绑定；动态 SQL 只拼接受控字段集合。
- repository protocol 和 Postgres implementation 分离。
- service 层负责业务决策，repository 层负责持久化。
- core memory models 禁止 extra 字段。
- API contract model 与 SDK snapshot 已进入 contract check。
- 无新增宽泛 `except Exception` 出现在 core service/repository/API router。

已在 v2 检查中收敛的点：

- 删除了无效的 `bypass_policy` 参数。
- `forget_record()` 返回真实 tombstone id。
- `MemoryWriteDecision` 包含 `tombstone_id`。
- `list_records(status="forgotten")` 可审计 forgotten records。
- forget audit 未传 namespace 时记录真实 record namespace。
- `update_candidate_status()` 改为按 candidate id 精确读取。
- retrieval plan 记录 policy filter 后真正 prompt-visible 的 selected memory ids。
- Web visibility filter 改为 `private/promotable/shared`。
- Memory API 接入持久化 role permissions 和 user/thread/branch/project ownership，避免普通 principal 通过 detail/audit/candidate/forget 读取或遗忘其他用户的 memory。
- Memory tools 在 graph path 绑定 `RequestContext`，拒绝跨 user/root/namespace 参数。
- Forget 默认擦除 `focus_memories` 拆列和 `data_json` 中的正文；API/SDK/Web 用 `payload_redacted` 展示 tombstone 状态。
- `focus-agent-migrate-local-state` 报告中的 database URI 改为脱敏输出，legacy store 非 dict payload 也不会因 `dict(value)` 崩溃。
- `MemoryCurator` 的 skipped 统计保留非 promotable candidate，不再在冲突检测前丢失 skip reason。

## 18. 当前风险与后续演进

### 18.1 API 权限边界

Memory API 已接入持久化角色权限和 thread/branch ownership；后续还应继续收敛更细的权限模型：

- project membership 尚未实现；当前 project memory 普通视图仍保守依赖 `user_id`，无 owner 的 project memory 仅 admin 可见。
- audit/candidate list 已有 user filter，后续可以继续扩展为 thread/branch ownership filter，减少历史缺失 `user_id` 数据被跳过。
- forget 跨 namespace、shared memory 或 project memory 应接 approval / admin 权限。

### 18.2 配置语义

`AGENT_MEMORY_BACKEND` 和 `AGENT_MEMORY_READ_SOURCE` 已被解析，但 runtime 实际选择仍由 `DATABASE_URI` 决定。后续应把它们正式接线：

- `AGENT_MEMORY_BACKEND=postgres` 且无 `DATABASE_URI` 时是否启动失败。
- `AGENT_MEMORY_BACKEND=local` 时是否允许强制 local fallback。
- `AGENT_MEMORY_READ_SOURCE=dual` 的对比报告和 metrics。

### 18.3 Search Quality

当前 PostgreSQL FTS + `ILIKE` 对关键词明确的 memory 够用，但同义改写、隐式事实、长距离抽象能力有限。后续可以优先做：

- query expansion。
- semantic key 改进。
- scene-aware rerank。
- 可选 trigram。
- 可选 embedding，但 namespace/read policy 必须仍是第一层权限边界。

### 18.4 Candidate Promotion

`focus_memory_candidates` 已存在，但 subagent candidate 到 lead review/promotion 的完整闭环还没有完全产品化。后续应补：

- candidate submit path。
- lead review API。
- accepted/rejected/discarded 状态转换。
- promotion audit。
- Web candidate board 操作。

### 18.5 Sensitive Memory Governance

当前 sensitive scan 是基础正则。后续应补：

- 更完整的 secret detector。
- shared write approval。
- raw evidence refs 与 redacted summary 分离。
- trajectory/governance 中只保留脱敏 payload。

### 18.6 Local Fallback

Local fallback 是开发/测试便利路径，不应作为生产长期 memory 事实源。后续应在 readiness 和文档里继续强调：

- Postgres 是 production canonical。
- local fallback 可用于裸跑、单测、离线迁移。
- migration/backfill 完成后应尽量避免 dual truth 长期存在。

## 19. 文件导航

后端核心：

- `src/focus_agent/memory/models.py`
- `src/focus_agent/memory/service.py`
- `src/focus_agent/memory/retriever.py`
- `src/focus_agent/memory/writer.py`
- `src/focus_agent/memory/policy.py`
- `src/focus_agent/memory/extractor.py`
- `src/focus_agent/memory/assembler.py`
- `src/focus_agent/memory/curator.py`
- `src/focus_agent/repositories/memory_repository.py`
- `src/focus_agent/repositories/postgres_memory_repository.py`
- `src/focus_agent/repositories/postgres_schema.py`

运行时与 graph：

- `src/focus_agent/engine/runtime.py`
- `src/focus_agent/engine/graph_memory_nodes.py`
- `src/focus_agent/core/state.py`
- `src/focus_agent/services/branch_memory_promotion.py`

工具、API、SDK、Web：

- `src/focus_agent/capabilities/default_tool_modules/memory.py`
- `src/focus_agent/api/routers/memory.py`
- `src/focus_agent/api/contract_models/memory.py`
- `frontend-sdk/src/client/memory.ts`
- `frontend-sdk/src/types/memory.ts`
- `apps/web/src/pages/memory/memory-console-page.tsx`

迁移与评估：

- `src/focus_agent/migrate_local_state.py`
- `tests/test_memory_service.py`
- `tests/test_postgres_memory_repository.py`
- `tests/test_memory_retriever.py`
- `tests/test_memory_pipeline.py`
- `tests/test_default_tools.py`
- `tests/test_runtime_backend_selection.py`
- `tests/test_migrate_local_state.py`
- `tests/eval/test_memory_suite.py`
- `scripts/memory_context_eval.py`
