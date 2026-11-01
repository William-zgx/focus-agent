# 分支工作流 A/B 实验：进度（2026-11-01 更新）

目标：用配对实验证明（或证伪）“分支工作流在长任务上比线性对话结果更好”。
线性组：主线、岔开的问题、回到主线全部发在一个线程。分支组：岔开的问题在
fork 出的子分支里做，合并提案经批准后导入主线，再在主线回答。只给“回到主线”
这一轮的回答打分。

## 已完成
- `scripts/branch_ab/run_experiment.py`：每个 (任务, 组, 重复) 独立进程 + 独立临时状态目录；
  记录每次模型调用的完整输入。关闭分支推荐、branch decision、委派、联网搜索、embedding。
- `scripts/branch_ab/score.py`：正则检查（must_include / must_not_include）+ 盲评 LLM 评委
  （只看用户消息与最终回答，不知道组别）。
- `scripts/branch_ab/analyze.py`：按 (任务, 重复) 配对；差值、任务级聚类 bootstrap 95% CI、
  符号检验、pass^1 / pass^k。
- 可用模型（2026-10-31 实测）：`deepseek:deepseek-v4-pro`、`moonshot:kimi-k2.6`、
  `openai:deepseek-v4-pro` 可用；OpenRouter key 已过期；`mimo:mimo-v2.5-pro` 报不支持的模型。
- 用 `dev-task.jsonl`（1 个手写任务）跑通全链路，n=1，不作结论。

## 试跑观察（待验证的假设，未改代码）
- 合并提案把用户在分支里已拍板的决定写成“仅为分支内待批准结论、尚未验证”；
  主线回答因此拒绝给最终建议（评委 2/5），线性组直接给出正确答案（5/5）。
- 同一导入结论在主线 prompt 中出现三次：`Approved branch conclusions` 区块、
  `<memory-context>`（confidence 显示 0.00）、导入结论 system 消息。

### 2026-11-01：任务集已冻结，基线配置定稿
- 任务集：`tests/eval/datasets/branch_ab/tasks.jsonl`，32 题，sha256 见同目录 README。
- 首次基线（DeepSeek V4 Pro 官方）中止：余额耗尽，43/72 次 429，结果作废，
  见 `reports/branch_ab/baseline-deepseek-v4-pro/ABORTED.md`。
- 被测模型改为 `relay:opensource/deepseek_v4_1_flash`（devbox 网关 Super Relay，
  catalog 在 `reports/branch_ab/models.relay.toml`，环境变量见 `/tmp/branch-ab-relay-env.sh`）。
- 两组相同的运行配置（`run_experiment.py::_isolated_env`）：
  - 关闭全部工具（`scripts/branch_ab/tools.disabled.toml`）：题目事实都在对话里，
    工具只会带来噪声（空工作区检索、无关网页触发回答门）。
  - `FOCUS_AGENT_SKILLS_ENABLED=false`；`MODEL_REQUEST_TIMEOUT_SECONDS=600`（网关约 20 tok/s）。
  - 每轮发送前、fork 前、生成合并提案前，等待后台任务（压缩、标题）清空。
- 评分口径：
  - pass^k 只看评委（overall >= 4 且未采用被否决的材料）；正则污染只作诊断，
    因为“X 已被排除”这种正确说法也会命中。
  - 合并门拒绝用户已批准的导入时，记为 `product_failure`，评为 overall=1、未交付，
    保留在配对里；429、超时等基础设施错误记为 `error`，重跑时自动重试。

- 评委（用户 2026-11-01 指定）：
  - 主评委：开发机网关的 DeepSeek V4.1 Flash（`relay:opensource/deepseek_v4_1_flash`）。
    它和被测模型相同，可能偏好自己的写法；两组答案出自同一模型，配对差值受影响较小。
  - 交叉评委：Claude Sonnet 5.5，经网关 Anthropic `/v1/messages`
    （`anthropic-gw:group/claude-sonnet-5-5-sg-first`，需 `x-claude-model-scope: cli`）。
  - 结论只在两位评委的配对差值方向一致时成立；报告两者的一致率。
  - 冒烟（3 条）：rubric_rate 两者一致；Sonnet 的 overall 更严（全部 rubric 满足仍给 3，
    理由是措辞偏弱），DeepSeek 给 4/5。pass^k 依赖 overall>=4 的阈值，所以按评委分别报告，
    不混用。

## 产品发现（基线前，已有直接证据）
- **合并门会拒绝用户已批准的结论。** `res-en-04` 分支组：子分支最后一轮是
  “Recap the final decision in full — provider, plan version, price, SLA …”，
  `build_tool_intent_plan` 因 “price / SLA” 等字样判为 `live_web_research`，
  执行合约要求 `web_search`；工具不可用，合约 `blocked`，`answer_verification.status=blocked`；
  `services/branches/merge.py::_merge_import_blocked_reason` 只看子线程最后一轮的这个状态，
  于是拒绝导入（`Merge import blocked by answer verification gate: blocked`）。
  线性组没有这道门，同题正常完成。
  - 门检查的是“最后一轮的工具合约是否满足”，不是“结论是否成立”；结论全部来自用户陈述。
  - 用真实路由扫描 32 题的全部用户消息：主线/岔路/回归共 288 条，
    其中 execution 63、live_web_research 11、workspace_lookup 12；
    最后一条岔路消息被判 live_web_research 的有 `res-en-02`、`res-en-04`，基线中预计这两题分支组被拒。
  - 证据：运行记录的 `child_gate_state` 字段（子线程的 answer_verification / execution_contract / plan_meta）。
- **分支组最终回答丢掉岔路里定下的细节（基线中期，127 次正常运行）。**
  岔路细节召回率（正则，按最终回答）：分支组 0.66，线性组 0.98；
  审查类 0.06 对 0.87，调试类 0.48 对 1.00，研究、写作两类两组相近。主线约束 0.87 对 0.89。
  丢失发生在作答阶段，不在合并阶段：合并材料和最终作答输入里约 98–99% 的细节都在。
  例：`rev-zh-01__branch__r0.json` 第 10 次调用，输入里三处写明 QuorumSync 与 2 秒预警，
  回答仍按岔路前的主线续写（“未收到方案文档……”），没有提到这两项。
  导入结论在最终输入里出现三次：系统提示的“Approved branch conclusions”，`<memory-context>`
  （confidence 0.00），以及回到主线前的“Imported conclusion from branch”系统消息；
  岔路的原始对话一条都不在。
  测量脚本与报告：`reports/branch_ab/ds-work/inspect/`（DeepSeek 执行者编写，主要数字已由 lead 独立重算）。
- **合并提案 JSON 无效时静默降级。** `rev-en-03__branch__r0.json`：提案输出含未转义引号，解析失败；
  系统改用分支最后一条回复的约 220 字截断片段作为 summary 并导入，未报任何错误。
- 计划器的“可用工具”总带 `run_skill_entrypoint`：`capabilities/tool_registry.py` 无条件注册，
  不受工具 catalog 控制。两组都受影响，导致计划 → 反思 → 重新规划的额外调用。

## 下一步
1. 基线：32 题 × 2 组 × 3 次 = 192 次，`reports/branch_ab/baseline-relay-deepseek-v4.1-flash`。
2. Kimi K2.6 盲评 + 配对分析（`--by category --by language`）。
3. 按失败分类排优先级修复（候选：合并门、合并提案把已拍板决定写成未验证、导入结论注入三次），
   同一任务集复测。

## 运行命令
```bash
. /tmp/branch-ab-relay-env.sh
OUT=reports/branch_ab/baseline-relay-deepseek-v4.1-flash
.venv/bin/python scripts/branch_ab/run_experiment.py --tasks tests/eval/datasets/branch_ab/tasks.jsonl \
  --model relay:opensource/deepseek_v4_1_flash --repeats 3 --workers 12 --out $OUT
# 主评委：开发机网关的 DeepSeek（需先 source relay env）
.venv/bin/python scripts/branch_ab/score.py --tasks tests/eval/datasets/branch_ab/tasks.jsonl \
  --runs $OUT --judge relay:opensource/deepseek_v4_1_flash
# 交叉评委：Claude Sonnet 5.5（同样需要 relay env）
.venv/bin/python scripts/branch_ab/score.py --tasks tests/eval/datasets/branch_ab/tasks.jsonl \
  --runs $OUT --judge anthropic-gw:group/claude-sonnet-5-5-sg-first
for f in $OUT/scores.*.jsonl; do .venv/bin/python scripts/branch_ab/analyze.py $f --by category --by language; done
```
重跑同一命令会跳过已完成（ok / product_failure）的运行，只重试基础设施错误。
