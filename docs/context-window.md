# 当前上下文窗口

更新时间：2026-10-03

Focus Agent 同时维护两类容易混淆但语义不同的统计：

| 字段 | 含义 | 展示位置 | 是否会随压缩下降 |
|------|------|----------|------------------|
| `token_usage` | 已经发生的模型调用累计消耗，来自 trajectory metrics 聚合 | 会话列表、分支树、toolbar token 统计 | 不会 |
| `context_usage` | 当前线程下一次请求会携带的背景信息窗口占用，来自 prompt 组装和预算 guard 估算 | 当前打开线程的发送栏 Context Meter | 可能会 |

`token_usage` 回答“这个会话历史上花了多少模型 token”。`context_usage` 回答“下一次发给模型的背景信息还有多少空间”。两者必须保持独立，不能在 API、分支树或 UI 文案里互相替代。

## 用户体验

当前打开线程的发送栏右下区域会显示一个 Codex 风格的圆形 Context Meter：

- 常态只显示环形占用，不挤占输入区域。
- hover 或 focus 后展示浮层：`背景信息窗口:`、已用百分比、剩余百分比、已用/总计标记数，以及自动压缩说明。
- `70%` 起浮层提示可手动压缩。
- `85%` 起展示“压缩背景信息”按钮。
- `92%` 起，或带上草稿后预计接近上限时，发送前会自动压缩。

中文 UI 用“标记”描述上下文窗口估算，避免和累计 `Tokens 消耗` 混淆。

## 后端口径

上下文用量由 `src/focus_agent/context_usage.py` 计算。预览和模型主调用共用 `build_context_request()` 的预算口径：

1. 从当前 `AgentState` 组装 prompt 背景。
2. 加入最近消息和可选 `draft_message`。
3. 从配置预算扣除工具定义占用和输出预留，得到可用于消息的 `input_token_limit`。
4. 分别记录裁剪前后的占用；`used_tokens` 是裁剪后的消息占用，`token_limit` 是可用于消息的额度。

默认 `ContextBudget.prompt_token_limit` 是 `128000`，`output_token_reserve` 是 `4096`。输出预留是预算空间，不是 provider 的 `max_tokens` 参数。tokenizer 默认是 `tokenizer_first`，无法解析时退回字符估计；显式 tokenizer 优先，否则使用所选模型标识。工具定义和 provider 消息包装的估计不等于服务端计费。

预览不是执行请求的精确重放：发送前按注册工具目录估计，运行时可能只绑定路由选出的子集，并增加计划、控制消息和工具结果。真正的主模型调用按最终工具集合重新执行预算检查。UI 明确显示这是发送前估算，不把裁剪后较低的占用伪装成“没有信息损失”。

历史摘要、检索记忆和可用技能目录在各个 prompt mode 都可按预算裁剪；必需规则、当前约束、用户请求和活动工具调用配对受到保护。若必需内容仍超限，返回 `required_context_overflow` 的 blocked 结果，不发起模型调用，也不继续提出工具确认。协议/技能修复会再次检查包含新增提示的请求预算。

## API

Conversation list and branch tree responses expose optional `token_usage` summaries so navigation surfaces can show historical spend without loading each thread.

`GET /v1/threads/{thread_id}` 返回的 `ThreadStateResponse` 会带可选 `context_usage`，用于首屏和每轮完成后的发送栏刷新。

预览当前线程上下文：

```http
POST /v1/threads/{thread_id}/context/preview
Content-Type: application/json

{"draft_message":"可选草稿内容"}
```

手动或系统触发压缩：

```http
POST /v1/threads/{thread_id}/context/compact
Content-Type: application/json

{"trigger":"manual"}
```

`trigger` 支持：

- `manual`
- `auto_pre_send`
- `auto_post_turn`

响应使用新的线程状态。`context_usage` 字段结构：

```json
{
  "used_tokens": 104000,
  "token_limit": 120000,
  "configured_token_limit": 128000,
  "input_token_limit": 120000,
  "pretrim_tokens": 110000,
  "posttrim_tokens": 104000,
  "tool_schema_tokens": 3904,
  "output_reserve_tokens": 4096,
  "trimmed": true,
  "required_overflow": false,
  "remaining_tokens": 16000,
  "used_ratio": 0.8667,
  "status": "hot",
  "prompt_chars": 416000,
  "prompt_budget_chars": 480000,
  "tokenizer_mode": "tokenizer_first",
  "counting_backend": "chars_fallback",
  "estimated": true,
  "last_compacted_at": "2026-04-26T01:30:00+00:00"
}
```

`status` 取值是 `ok | warm | hot | over | compacting | error`。

## 压缩行为

压缩是非破坏式的：完整原始 messages 仍保留在状态和历史里，系统只更新 prompt 使用的 `rolling_summary` 和 `context_compaction` metadata。

图内回合摘要与手动/后台压缩共用 `core/context_compaction.py`，不再各自截取尾部 4000 字符或头部 2600 字符。结构化快照包含：

- 当前目标和用户约束
- pinned facts
- 分支身份
- imported findings 和 branch-local findings
- 证据与产物引用
- 已离开近期窗口的历史摘录及消息位置

近期窗口默认最多 12 条消息、目标 16000 tokens，按完整轮次向前扩展边界，不能拆开工具调用与结果；一个长轮次可能超过近期目标，最终请求预算仍会另行检查。压缩游标与组装使用同一个窗口选择器，摘要不重复包含仍被保留的近期原文。

`context_compaction` 保存消息边界、历史摘录、源状态计数与压缩测量。手动/后台路径在线程 lease 内重读状态，再更新摘要；同样的消息数量不意味着约束、结论或产物没有变化。`no_gain` 表示此次没有降低测得的占用，不能把每次调用都报告成有效压缩。

这是确定性的结构化快照和有损历史摘录，不是 LLM 语义摘要，也不保证早期自然语言的每个细节都保留。长期重要的要求应进入结构化约束或 pinned facts；它不会自动把任意一句“撤回某要求”变成结构化状态修改。当前状态是事实来源，旧摘要不能覆盖当前约束。

完整 `rolling_summary` 用于恢复和检查；请求只读取 v2 metadata 的 `history_summary`，目标、约束和批准结论由独立结构化区块渲染，避免重复注入。

子分支的模型上下文优先使用本地消息；尚无本地请求时只保留父分支最后一次可见问答作为启动上下文。新建分支不继承父分支的滚动摘要和压缩游标，但保留显式继承的目标、约束和已批准结论。原始/UI 历史不因此删除。检索记忆与已渲染结论只有内容、来源分支和证据完全相同时才跨通道去重；未批准的分支记忆不能进入主线综合。

近期消息按对象身份或稳定消息 ID 与本地消息匹配，不以内容相等判断归属。恢复的无 ID 消息无法证明来源时，回退到 fork cursor 隔离后的本地消息序列；此时可能不保留较短的 recent 窗口，最终请求预算仍然生效。活动工具调用与结果保持配对。

记忆内部合并同源重复结论时保留全部证据引用；不同来源分支的同一句结论仍分别展示。分叉位置只在原始消息序列上解释，避免过滤控制消息后位置发生偏移。

merged branch 是只读分支，手动压缩会返回 403，不允许改写状态。

手动/后台压缩通过真实 LangGraph 的状态更新接口保存，不指定图中不存在的维护节点。若新鲜 checkpoint 正在等待用户回答或工具审批（存在 pending interrupts），压缩返回 409 并保留中断，避免状态更新清除可恢复的等待状态。发送前/后台自动压缩也遵守这一限制，不通过摘要维护绕过用户响应。

Web 的压缩 handler 捕获请求失败，使用既有 mutation error 展示错误，不产生未处理 Promise rejection。实际编译图与浏览器验收见 [2026-09-30 质量报告](validation/2026-09-30-project-quality.md)；真实模型具体任务回忆通过不代表任意长历史无损保留。

后续真实模型多轮与工具原文分页验收见 [2026-10-03 MR 质量报告](validation/2026-10-03-mr-quality.md)。`scripts/context_ui_smoke.py` 默认运行压缩/分支场景；使用 `--tool-observation-workspace` 切换为大文件读取与随机校验码回读，该路径必须对应隔离 API 的 `WORKSPACE_ROOT`。

## 自动压缩

自动压缩默认开启，可以通过环境变量回滚：

```bash
CONTEXT_AUTO_COMPACTION_ENABLED=true
CONTEXT_AUTO_COMPACTION_PRE_SEND_RATIO=0.92
CONTEXT_AUTO_COMPACTION_POST_TURN_RATIO=0.85
```

触发路径有两条：

- 发送前预检：非流式和流式 turn 进入 graph 之前都会尝试压缩。
- 回合后后台压缩：`chat.turn` 成功后异步调度，避免下一轮才发现上下文过大。

流式发送前触发自动压缩时，会通过 SSE 发出：

- `context.compaction.started`
- `context.compaction.completed`

同一线程在摘要覆盖边界和相关结构化状态都没有变化时，不重复写入。原先基于固定字符阈值、异步触发但不回写 graph 的 overflow 摘要路径已移除；有效压缩由上述持久化路径承担。

## 前端与 SDK

### 大工具结果回读

工具结果需要裁剪时，执行层先把原文保存到既有 ArtifactStore，再将简短观察和 `tool-observation://<tool>/<call>` 引用交给模型。可使用 `artifact_read(artifact_id=引用, offset=字符偏移, limit=字符数)` 分段读取；单次范围有上限，不需要重新执行产生结果的工具。

这些引用只在原线程的运行时作用域内解析，不跨父子线程共享，也不能通过 `.tool-observations` 普通产物路径绕过作用域。原文保存失败时显式标记 `observation_retrievable=false`，不承诺可读引用。`artifact_read` 的输出不递归产物化；请求较小的分页范围可以避免再次裁剪。此能力依赖运行时已注册产物工具和可信线程标识，不等于给通用 ArtifactStore 增加了用户级授权。

### 窗口展示

Web App 在 `MessageComposer` 中使用 Context Meter 展示当前线程的 `context_usage`，并通过草稿预览保持估算接近用户下一次真实发送。

`frontend-sdk` 暴露：

- `listConversations()` / `getBranchTree()` responses with optional `token_usage`
- `previewThreadContext(threadId, { draft_message })`
- `compactThreadContext(threadId, { trigger })`

Web hooks 位于 `apps/web/src/features/thread/use-thread-context.ts`：

- `usePreviewThreadContext(threadId)`
- `useCompactThreadContext(threadId)`

## 回归关注点

- `token_usage` 继续代表累计模型消耗，分支树和会话列表仍使用它。
- `context_usage` 只代表当前 prompt 背景窗口占用。
- preview 带草稿后用量应增加。
- manual compact 不删除 messages。
- merged branch compact 应被拒绝。
- Web Context Meter 的百分比、`k/M` 标记格式和 hover/focus 浮层应保持可读。

## Context Quality 回归指标

`scripts/memory_context_eval.py` 的 memory/context suite 会对压缩样本额外计算 semantic quality 指标，用来衡量 `rolling_summary` 和 `context_compaction` 是否保留了可回答性，而不是只看上下文长度是否下降。

压缩样本通过 case id、tags 或 `rolling_summary` marker 识别。报告中的新增字段包括：

- `context_compaction_semantic_recall`：压缩后回答是否仍召回 required facts
- `context_compaction_semantic_precision`：压缩后是否没有带入 forbidden facts 或 stale context markers
- `context_compaction_semantic_grounding`：压缩后 context 是否仍包含 required context markers 和 artifact refs
- `context_compaction_semantic_quality`：recall、precision、grounding、answerability 的均值
- `context_compaction_semantic_drift`：出现 required fact 丢失、context marker 丢失、污染或 stale marker 时记为 drift

Memory Regression Dashboard 的 trend JSON 会把这些指标按 `candidate/reviewed/promoted/golden` 阶段汇总，并在 drift 或 pollution 出现时写入 `pollution_alerts`。
