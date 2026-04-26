# 当前上下文窗口

更新时间：2026-04-26

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

上下文用量由 `src/focus_agent/context_usage.py` 计算。它复用 `assemble_context()`、`ContextBudget` 和 `apply_prompt_budget_guard()` 的口径：

1. 从当前 `AgentState` 组装 prompt 背景。
2. 加入最近消息和可选 `draft_message`。
3. 经过 prompt budget guard 后估算 `used_tokens`。
4. 用 `ContextBudget.prompt_token_limit` 计算剩余额度和状态。

默认 `ContextBudget.prompt_token_limit` 是 `128000`。当前 tokenizer 默认仍是 `chars_fallback` 近似模式；如果线程状态已经携带模型或 tokenizer 配置，会随 budget 一起进入估算。

## API

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
  "token_limit": 128000,
  "remaining_tokens": 24000,
  "used_ratio": 0.8125,
  "status": "warm",
  "prompt_chars": 416000,
  "prompt_budget_chars": 512000,
  "tokenizer_mode": "chars_fallback",
  "last_compacted_at": "2026-04-26T01:30:00+00:00"
}
```

`status` 取值是 `ok | warm | hot | over | compacting | error`。

## 压缩行为

压缩是非破坏式的：完整原始 messages 仍保留在状态和历史里，系统只更新 prompt 使用的 `rolling_summary` 和 `context_compaction` metadata。

压缩摘要优先保留：

- 当前目标和用户约束
- pinned facts
- 分支身份
- imported findings 和 branch-local findings
- 上一版 rolling summary 的关键信息
- 最近 8 条对话

写入的 `context_compaction` metadata 包含触发原因、源消息数量、压缩前 prompt token/char 估算、`last_compacted_at` 和 `non_destructive=true`。

merged branch 是只读分支，手动压缩会返回 403，不允许改写状态。

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

同一线程在没有新增 human/assistant 消息时，后台自动压缩不会反复写入，避免 metadata 抖动。

## 前端与 SDK

Web App 在 `MessageComposer` 中使用 Context Meter 展示当前线程的 `context_usage`，并通过草稿预览保持估算接近用户下一次真实发送。

`frontend-sdk` 暴露：

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
