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

## 初始试跑观察（历史记录，后续验证见下文）
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
  - 关闭 catalog 控制的工具（`scripts/branch_ab/tools.disabled.toml`）：题目事实都在对话里。
    `run_skill_entrypoint` 仍被 runtime 无条件注册，两组规划器均可见；不能把此配置称为完全无工具。
  - `FOCUS_AGENT_SKILLS_ENABLED=false`；`MODEL_REQUEST_TIMEOUT_SECONDS=600`（网关约 20 tok/s）。
  - 每轮发送前、fork 前、生成合并提案前，等待后台任务（压缩、标题）清空。
- 评分口径：
  - pass^k 只看评委（overall >= 4 且未采用被否决的材料）；正则污染只作诊断，
    因为“X 已被排除”这种正确说法也会命中。
  - 合并门拒绝用户已批准的导入时，记为 `product_failure`，评为 overall=1、未交付，
    保留在配对里；429、超时等基础设施错误记为 `error`，重跑时自动重试。

- 评委（用户 2026-11-01 指定）：
  - 主评委：开发机网关的 DeepSeek V4.1 Flash（`relay:opensource/deepseek_v4_1_flash`）。
    它和被测模型相同，存在自评偏差；两组都由同一模型作答不能保证偏差抵消，需独立交叉评分。
  - 交叉评委：Claude Sonnet 5.5，经网关 Anthropic `/v1/messages`
    （`anthropic-gw:group/claude-sonnet-5-5-sg-first`，需 `x-claude-model-scope: cli`）。
  - 结论只在两位评委的配对差值方向一致时成立；报告两者的一致率。
  - 冒烟（3 条）：rubric_rate 两者一致；Sonnet 的 overall 更严（全部 rubric 满足仍给 3，
    理由是措辞偏弱），DeepSeek 给 4/5。pass^k 依赖 overall>=4 的阈值，所以按评委分别报告，
    不混用。

## 基线结果（2026-11-01，192/192 次，186 ok + 6 product_failure）
被测：`relay:opensource/deepseek_v4_1_flash`，代码 `36e2cce`。配对 96 组（32 题 × 3 次）。
结论：**修复前的分支工作流显著差于线性对话**，两位评委方向一致。

| 指标 | 评委 | 线性 | 分支 | 差值 [95% CI] | 题目 好/差（32） | 符号检验 p |
|---|---|---|---|---|---|---|
| 总分 1–5 | Sonnet 5.5 | 3.52 | 2.83 | −0.69 [−0.99, −0.40] | 4/22 | 0.0005 |
| 总分 1–5 | DeepSeek | 4.13 | 3.26 | −0.87 [−1.24, −0.53] | 3/21 | 0.0003 |
| rubric 满足率 | Sonnet | 0.86 | 0.69 | −0.17 [−0.26, −0.09] | 2/23 | <0.001 |
| rubric 满足率 | DeepSeek | 0.87 | 0.69 | −0.18 [−0.27, −0.11] | 4/24 | 0.0002 |
| 采用被否决材料 | Sonnet | 0.00 | 0.05 | +0.05 [0.01, 0.10] | — | — |
| 岔路细节召回（正则） | — | 0.96 | 0.58 | −0.38 [−0.51, −0.26] | 0/21 | <0.001 |
| 输入 token | — | 62k | 50k | −19% | 29/3 | <0.001 |
| pass^1 / pass^3 | Sonnet | 0.57 / 0.31 | 0.30 / 0.19 | | | |
| pass^1 / pass^3 | DeepSeek | 0.68 / 0.47 | 0.39 / 0.22 | | | |

按类别：调试类差距最大（两评委总分差 −1.25 / −1.26），写作类无显著差异。
评委一致性（186 次正常运行）：总分 Pearson 0.83，完全一致 47%，相差 ≤1 分 94%；
pass 判定一致 85%；按题目的分支−线性差值方向 25/32 一致、1 题相反。
数据：`reports/branch_ab/baseline-relay-deepseek-v4.1-flash/`（scores.*.jsonl、analysis.*.json）。

## 失败归因与修复 1（2026-11-01）
- 提示词重放对照（64 条分支组最终作答提示词 × 4 变体 × 2 次；`reports/branch_ab/ds-work/ablate/`）：
  岔路细节召回 原样 0.62、仅去重 0.62（差 −0.005 [−0.05, 0.04]）、
  结论改为用户消息 + 确认 0.96（+0.34 [0.20, 0.49]）、放入岔路原文 0.99（上限）。
  Sonnet 盲评 V0→V2：总分 2.92→3.43（+0.51 [0.26, 0.81]），采用被否决材料 0.039→0，
  pass 0.34→0.49（+0.15 [0.04, 0.28]）。（`reports/branch_ab/ablation-judge/`）
- 修复提交 `f40ec6b`（分支 `codex/branch-import-as-user-turn`）：
  A. 导入通知在发给模型的消息里改写为用户确认的决定 + 简短确认（存储 / API / UI 不变）；
  B. 合并门只拒绝 `contradicted`。
- 复测：同一冻结任务集、同一配置，两组都重跑，输出 `reports/branch_ab/fix1-relay-deepseek-v4.1-flash/`。

## 基线中的产品发现（修复状态见前文）
- **合并门会拒绝用户已批准的结论。** `res-en-04` 分支组：子分支最后一轮是
  “Recap the final decision in full — provider, plan version, price, SLA …”，
  `build_tool_intent_plan` 因 “price / SLA” 等字样判为 `live_web_research`，
  执行合约要求 `web_search`；工具不可用，合约 `blocked`，`answer_verification.status=blocked`；
  `services/branches/merge.py::_merge_import_blocked_reason` 只看子线程最后一轮的这个状态，
  于是拒绝导入（`Merge import blocked by answer verification gate: blocked`）。
  线性组没有这道门，同题正常完成。
  - 门检查的是“最后一轮的工具合约是否满足”，不是“结论是否成立”；结论全部来自用户陈述。
  - 用真实路由扫描 32 题的全部用户消息：主线/岔路/回归共 280 条（88 / 160 / 32），
    其中 execution 63、live_web_research 11、workspace_lookup 12；
    最后一条岔路消息被判 live_web_research 的有 `res-en-02`、`res-en-04`，基线中这两题分支组的三次重复均被拒。
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

## 修复 1 完整复测（2026-11-01）

代码 `f40ec6b`（独立 worktree；本分支对应修复为 `1c4ed81`），同一任务集、模型和运行配置，
两组均重跑：**192/192 正常完成，0 次合并门拒绝，0 次基础设施错误**。
**两位评委各 192 条有效评分，0 条评分错误，共 96 组完整配对。** DeepSeek 首轮有 8 条超时，
仅对失败项以 2 并发补打，原先成功的 184 条评分逐条保持不变。首轮快照保存在本地
`scoring-attempts/deepseek-pass1.jsonl`；不能把评分进程退出成功等同于评分齐全。

两位评委均未检出修复后总体总分的显著差异；分支组均值仍略低。
**修复缩小了基线中的质量差距，但尚未证明分支更优、等效或非劣。**

| 指标 | 线性 | 分支 | 差值（分支 − 线性）[95% CI] |
|---|---|---|---|
| Sonnet 总分 1–5 | 3.677 | 3.552 | −0.125 [−0.333, +0.073] |
| DeepSeek 总分 1–5 | 4.208 | 4.073 | −0.135 [−0.438, +0.156] |
| Sonnet rubric 满足率（描述性） | 0.897 | 0.909 | +0.012 [−0.028, +0.054] |
| DeepSeek rubric 满足率（描述性） | 0.886 | 0.881 | −0.005 [−0.048, +0.039] |
| Sonnet 采用被否决材料 | 0.000 | 0.010 | +0.010 [0.000, +0.031] |
| DeepSeek 采用被否决材料 | 0.010 | 0.010 | 0.000 [−0.031, +0.031] |
| 岔路细节召回（逐运行比例均值） | 0.995 | 0.979 | −0.016 [−0.036, 0.000] |
| 全流程输入 token / 运行 | 62,729 | 50,280 | −12,449 [−16,579, −8,498] |
| 全流程输出 token / 运行 | 22,021 | 21,755 | −265 [−1,331, +760] |
| Sonnet pass^1 / pass^3 | 0.667 / 0.469 | 0.625 / 0.344 | — |
| DeepSeek pass^1 / pass^3 | 0.698 / 0.438 | 0.625 / 0.438 | — |

总分的任务级符号检验：Sonnet p=0.21，32 题中分支更好 8、较差 15、持平 9；
DeepSeek p=0.6776，更好 10、较差 13、持平 9。pass^1 的原始通过数分别为
Sonnet 线性 64/96、分支 60/96；DeepSeek 线性 67/96、分支 60/96。
pass^3 的原始任务数分别为 Sonnet 15/32、11/32；DeepSeek 14/32、14/32。

完整复测的评委一致性：总分 Pearson 0.710，完全同分 40.6%，相差不超过 1 分 95.8%，
通过判定一致率 88.0%；32 题配对差方向 22 题一致、2 题相反，其余为一位判断持平。
两位评委对总体结论一致，不表示每道题或每项 rubric 都一致。

按类别的总分差（分支 − 线性）如下；每类只有 8 题，属于探索性拆分，未做多重比较校正。

| 类别 | Sonnet 差值 [95% CI] | DeepSeek 差值 [95% CI] |
|---|---|---|
| 调试 | +0.167 [−0.042, +0.375] | +0.458 [+0.167, +0.792] |
| 研究 | −0.208 [−0.292, −0.083] | −0.417 [−0.750, −0.083] |
| 审查 | −0.167 [−0.833, +0.417] | −0.458 [−1.417, +0.333] |
| 写作 | −0.292 [−0.667, +0.167] | −0.125 [−0.417, +0.250] |

调试类方向转正，研究类仍有负向信号；不能用单一子组取代总体比较。
交付物判定仍偏弱：Sonnet 线性 92/96、分支 87/96；DeepSeek 线性 96/96、分支 91/96。
输入 token 约少 **19.8%**；token 统计包含捕获到的各阶段模型调用，不能直接换算为实际账单、
cache 费用或总耗时。写作类输入 token 差异区间跨 0，节省主要来自研究、调试和审查。
审查类正则召回为 0.917 对线性组 0.979。逐条抽查分支组的 4 个未命中项后发现：

- `rev-en-01` r0：答案写 `validation = strict`，未写正则要求的 `strict mode`，语义保留。
- `rev-zh-02` r0/r1：答案写 `45 min`，未写正则要求的 `45 分钟`，数值和单位保留。
- `rev-zh-01` r2：合并与最终作答输入都含 `2 秒`，答案只保留倒推提前量的方法，确实丢失具体数值。

冻结的正则和原始分数均未调整；人工核查只是独立诊断，不能回改评分来提高结果。
本地证据：`reports/branch_ab/ds-work/retest-failures/`，lead 已对照对应调用 33 / 10 / 10 / 10 复核。

Sonnet 的同轮分支−线性总分差，从基线 −0.688 变为 −0.125；跨轮的配对差值变化为
+0.5625 [95% CI +0.1771, +0.9479]。排除两道合并门失败题后，基线差仍为 −0.567，
修复后为 −0.122；改善不全由取消合并拒绝解释。DeepSeek 的总体配对差值从 −0.865 变为 −0.135，
跨轮变化为 +0.7292 [95% CI +0.3229, +1.1667]。此比较仍非随机分配修复版本的因果估计。

**评分结构诊断：** 评委偶尔拆分或新增 rubric 条目，`rubric_rate` 的分母并非固定，
应作为描述性指标。Sonnet 复测 2/192 条存在条目数不一致；排除相应配对后，94 组的总分差
为 −0.117 [−0.333, +0.085]。DeepSeek 复测 18/192 条存在条目数不一致，排除相应配对后，
81 组（30 题）总分差为 −0.173 [−0.519, +0.127]。两项敏感性检查均未检出总体显著差异；
条目数相等也不保证语义逐项对齐。基线中的条目数不一致为 Sonnet 0 条、DeepSeek 15 条。
完整双评委检查和复算脚本位于本地 `reports/branch_ab/compare_completed.py`，脚本拒绝不完整评分；
结果为 `comparison.completed.json`，两轮 384 次运行的文件指纹为 `runs-manifest.completed.json`。

**解释边界：** 未检出总分的总体显著差异，不等于证明等效或非劣；本实验未预设非劣界值。
也没有证据证明修复后分支质量优于线性。修复前后线性组也有波动，因此主结论使用同轮配对，
不能把分支组跨轮分数上涨全部归因于修复。合成任务的全部事实来自用户、catalog 控制的工具关闭，
结果仅覆盖此任务集、模型和运行配置；真实工具任务、多分支嵌套及更长会话需要额外验证。

结果保存在本地 `reports/branch_ab/fix1-relay-deepseek-v4.1-flash/`。
`reports/` 被 git 忽略，另一台机器需用下述命令重新运行；仓库中的表格不是原始轨迹的替代品。

## 下一步

1. 评分与总体分析已完成；保留两位评委各自的原始评分和基线，不追改 rubric 或冻结任务提高结果。
2. 按剩余失败归因选择最小改动，优先检查研究类的保留意见、审查类交付不足，以及提案 JSON 解析失败后的静默截断。
3. 后续比较先明确验收指标；若要主张非劣或等效，需预设界值与相应设计，不能事后用跨 0 区间认定。
4. 同一任务集用于回归，外推检验另行冻结新集合；重复开发使用过的集合不能充当独立验证集。

## 运行命令

从仓库根目录执行，先配置被测模型和评委所需的环境。模型 ID 必须存在于所用 catalog。
本次实验的 relay catalog 和网关认证属于本地配置，不随仓库提交；
`/tmp/branch-ab-relay-env.sh` 只是本机便利脚本，不是可移植前提。

```bash
# 选用自定义 catalog 时设置；认证变量按 catalog 中的 api_key_env 配置。
export BRANCH_AB_MODEL_CATALOG=/absolute/path/to/models.toml
OUT=reports/branch_ab/fix1-relay-deepseek-v4.1-flash
.venv/bin/python scripts/branch_ab/run_experiment.py --tasks tests/eval/datasets/branch_ab/tasks.jsonl \
  --model relay:opensource/deepseek_v4_1_flash --repeats 3 --workers 12 --out "$OUT"
# DeepSeek 主评委
.venv/bin/python scripts/branch_ab/score.py --tasks tests/eval/datasets/branch_ab/tasks.jsonl \
  --runs "$OUT" --judge relay:opensource/deepseek_v4_1_flash
# Sonnet 交叉评委：本机网关适配器读取 RELAY_API_KEY、RELAY_BASE_URL、SSL_CERT_FILE。
# 网关必须提供 Anthropic /v1/messages 与相应模型，按部署方式配置这些变量。
.venv/bin/python scripts/branch_ab/score.py --tasks tests/eval/datasets/branch_ab/tasks.jsonl \
  --runs "$OUT" --judge anthropic-gw:group/claude-sonnet-5-5-sg-first
# 每位评委分别分析，不能把多个评委的文件混入同一次分析。
for f in "$OUT"/scores.*.jsonl; do
  .venv/bin/python scripts/branch_ab/analyze.py "$f" --by category --by language
done
```

重跑 runner 跳过 `ok` / `product_failure`，只重试基础设施错误；评分脚本跳过成功评分。
不同模型、配置、代码版本或评分提示必须使用新的输出目录或评分文件，避免误用缓存。
基础设施重试会覆盖同名失败文件，需要保留失败轨迹时先归档。`pass^3` 仅在每题三次评分齐全时报告，
评分失败不能被当作缺失后直接宣称完整通过率。
