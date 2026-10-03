# Agent 能力补全实施规划

日期：2026-09-28；源码基线：`718be87`。状态：**计划，功能实施尚未开始**。

入口：[调研](research.md) / [设计草案](design.md) / [当前能力地图](../../architecture/agent-capability-map.md) / [项目路线图](../../roadmap.md)。

## 1. 本轮交付与边界

本轮只校准现有文档并建立后续调研、设计、实施规划；不改业务代码、默认配置、数据库、运行服务或模型路由，不把下面任务标记为已经完成。

文档目标：当前说明与源码一致；未来能力明确标注计划状态；每个改进项具有现状依据、依赖和可执行的验收标准。

## 2. 先修复会使验收失真的问题

这些是前轮审查发现的可靠性问题。实施时先针对当前代码复现，再做最小修复；旧审查记录不能替代修复后验证。

| ID | 问题与依据 | 最小范围 | 完成条件 |
| --- | --- | --- | --- |
| B01 | [线程状态读取](../../../src/focus_agent/services/chat/threads.py) 的 `_safe_get_values` 可在 owner 校验前触发 imported-record 回填 | 将有副作用的回填放在合法访问之后，检查同一共享入口的受影响调用者 | 跨 owner 请求被拒绝，且拒绝前 graph/state/repository 均无写入；合法 owner 的回填行为保留 |
| B02 | [生命周期信号处理](../../../src/focus_agent/runtime/lifecycle.py) 与 Uvicorn 退出处理的组合存在阻塞退出风险 | 明确信号的单一控制方，保留必要清理 hook | 在隔离子进程中发送 SIGTERM，限定时间内退出并执行清理；hook 单测通过不能替代进程测试 |
| B03 | [readiness](../../../src/focus_agent/api/route_utils/readiness.py) 中 fallback 的非空值不能证明 fallback 后端可用 | 区分配置意图、实际连接/查询可用与降级状态 | 主检索不可用且 fallback 也不可用时不得报告可用；fallback 真可用时按既有契约准确报告降级 |
| B04 | [环境 judge](../../../src/focus_agent/eval/judges/environment_judge.py) 可从缺失 final state 回退到 initial state | 区分前置条件与执行后断言；缺失证据不能自动满足结果断言 | 未执行操作/空 final state 不再通过“已完成环境变更”断言；确属初始条件的检查仍可显式表达 |
| B05 | eval 的 acceptance 声明和真实用量/费用未形成完整门禁 | 接通声明到判定；区分未知与零值，区分 fake harness 和真实 provider 质量 | 一个不满足 acceptance 的样例必失败；缺 usage 时标记 unknown/incomplete，不能报告零成本质量通过 |
| B06 | [Web 前端](../../../apps/web/src) 的 audit-only 操作边界与 handoff 过程反馈不完整 | 只读界面统一约束写操作；handoff 展示待处理/失败状态 | audit-only 不发起写请求；handoff 立即可见且成功/失败/重试不产生重复条目；后端仍独立授权 |
| B07 | 独立 SDK 相关测试可能读取陈旧 dist；[Makefile](../../../Makefile) 的目标依赖与 CI 顺序不同 | 明确构建前置或测试入口依赖，不修改生成产物掩盖问题 | 清洁 checkout 及存在旧 dist 的环境均先构建当前 SDK，再执行同一目标测试 |
| B08 | 某次本地部署使用临时 unit 且未配置自动重启，不能代表生产恢复保障 | 选择并记录实际维护的部署剖面；核对 restart policy、构建阶段、退出与恢复职责 | 在目标部署剖面执行一次受控崩溃/重启验证并保存结果；不把其他机器或临时进程的观察泛化为仓库默认 |

B01 是恢复/外部写入前置；B02/B08 支撑进程恢复；B03/B04/B05 支撑可信质量证据。B06/B07 可在不冲突的独立工作面并行处理。

## 3. 分阶段任务

优先级表示建议实施顺序，不表示已获得修改生产环境或购买外部服务的授权。工期与负责人在实施时按实际任务量确定，不给未经验证的时间承诺。

### 阶段 A：可靠完成一个任务

| ID | 交付 | 依赖 | 验收场景 | 对应文档 |
| --- | --- | --- | --- | --- |
| A1 / C01 | 首个普通 run 的 PostgreSQL 持久执行剖面，复用 `focus_background_jobs` 和现有 worker，连接 checkpoint/claim token；Team v19 jobs 保留其 session/task 作用域 | B01、B02、B08 | run→background job→attempt/checkpoint 的关联重启后仍可解析；checkpoint 后终止进程可恢复；重复提交不创建重复逻辑任务；过期 claim 不能提交任务持久状态，外部副作用另按 A2 核对 | architecture、runtime-outcomes、部署文档 |
| A2 / C01 | 持久 follow-up、审批/用户回复按所属执行路径恢复 | A1 | 重启不丢 follow-up；同一审批只创建一个 canonical resume job，重试 attempt 关联原 job；reject、取消、过期、superseded revision 均不能继续原写操作；外部调用超时且结果未知时进入核对状态，不盲目重放或宣称 exactly-once | Agent Team workbench / rollout |
| A3 / C04 | 真实 runner 的调用次数/时间预算，子任务共享父预算；费用未知状态 | 当前 runner 接线；恢复路径依赖 A1 | 第二次模型调用超过额度时在调用前停止；并行子任务不能突破父预算；恢复不能重置预算；缺费用数据不计作零 | agent-role-routing、agent-evaluation |
| A4 / C02 | 首个实施任务验收器：代码变更的行为证据与最终状态 | B04、B05；修复重试依赖 A3 | 模型声称修好但测试失败/缺失时不能 verified；针对性修复通过后才完成；旧版本测试结果不能验收新修改 | runtime-outcomes、validation-runbook |

阶段退出标准：用户交付一个小型代码任务，执行能受控中断/恢复，结果有对应证据；缺条件时明确阻塞，而不是虚假完成。审批、模型和外部副作用失败各有一次对应的负向验证。

### 阶段 B：扩展实际操作与成果交付

| ID | 交付 | 依赖/选择 | 验收场景 | 对应文档 |
| --- | --- | --- | --- | --- |
| B9 / C03 | 首个受控 browser adapter 或业务连接器 | 产品选择其一；A2/A3/A4 与 B01 的权限边界 | 仅可访问授权对象；完成一次实际页面/业务操作并回读；凭据不会进入模型输出/生成代码环境；不可信页面不能扩大权限 | tool-skill-design、sandbox-execution |
| B10 / C03 | 必要的图片/附件输入和授权 artifact 下载 | 按首个用例选择类型，不一次支持所有格式 | 输入被模型正确接收或明确拒绝不支持类型；越权下载失败；用户能取回对应成果而非仅获得服务器路径 | streaming-contract、SDK、前端说明 |

阶段退出标准：完成一个离开纯文本聊天的真实任务，并把用户可访问、可验证的成果交付出来。

### 阶段 C：可测量的长期改进

| ID | 交付 | 依赖 | 验收场景 | 对应文档 |
| --- | --- | --- | --- | --- |
| C8 / C05 | 有限多 Agent 执行—整合—返工闭环，接通已有 revision/attempt | 阶段 A；无需等待所有外部工具 | 独立子任务能执行并提交证据；失败只返工受影响任务；取消旧 revision 后不得把旧结果合入新 revision | agent-team-workbench、agent-role-routing |
| C9 / C06 | 重要偏好/规则的来源、修订与撤销 | 确认保留/删除政策 | A→B 更新可追溯、可撤销；检索/embedding 使用当前有效版本；forget/delete 不被异步写入复活 | memory-system-v2、retrieval-zvec |
| C10 / C07 | 任务级反馈→候选用例→审核→before/after replay | B04/B05；复用现有 trajectory/promotion | 一条负反馈可追到原任务、候选、回放结果与处理决定；拒绝候选不会改变线上行为 | agent-evaluation、observability-runbook |
| C11 / C05/C07 | 同任务集的单/多 Agent 与模型配置对照 | C8、C10；先建立真实 provider 基线 | 记录质量、误报完成、干预、耗时、用量；只有有实际收益的场景启用协作 | capability map、roadmap |

阶段退出标准：至少一个真实失败进入可重放回归；协作和记忆改进可以用相同验收口径对比，而不是仅统计工具调用或角色数量。

## 4. 验证规则

- 每项先建立对应失败模式的最小检查，再实现，再运行受影响检查；公共契约变化另加 API/SDK 契约验证。
- fake model 用于确定性测试调用顺序、恢复、预算和评测器；真实 provider 用于任务完成质量，两种报告明确分开。
- 环境断言读取操作后的真实目标状态；缺证据、跳过检查和未知成本不伪装成通过。
- 记录任务是否完成、是否错误宣称完成、用户干预次数、恢复结果、耗时和已知用量；比较模型/协作时固定任务集、预算与验收器版本。
- 质量阈值在建立基线后设定；本计划不虚构通过率或收益目标。
- 仅执行对应阶段需要的故障注入、浏览器、迁移或负载检查，不把全量测试作为每个小改动的默认门槛。

## 5. 文档同步与维护

| 文档组 | 本轮核对重点 | 后续变化触发 |
| --- | --- | --- |
| 根 README、project-overview、docs/README、roadmap | 定位、源码基线、现状与计划分层，消除无证据的全面验证承诺 | 能力启用/成熟度变化 |
| architecture、capability map、context、runtime/streaming | 实际主路径、持久化与恢复差别、默认 flag、完成语义 | A1–A4、B10 |
| memory、retrieval、tool/skill、sandbox、role routing | 已有能力与未接通部分、fallback、预算、工具边界 | A3、B9、C8–C9 |
| Agent Team、branch、admin、productivity、Android、前端/SDK | UI 与执行能力分离、只读边界、不同运行剖面的能力差异 | A2、B06、B10、C8 |
| quick-start、development、部署、auth/security、observability、eval、release/rollback | 命令与依赖、证据可信范围、生产集成前置，不把检查入口当验证结果 | B01–B08、各阶段验收 |
| multi_agent_refactor 历史文档 | 保留当时记录并明确 historical；跳转当前专题 | 不回写历史结论为当前验收 |

运行时使用的内置/本地 Skill 提示词、生成的 OpenAPI/SDK 类型、JSON baseline 和历史 release 报告不作为普通说明文档重写：改变它们会影响运行行为或伪造历史证据。发现其中问题应另立对应实现任务。

文档验证至少检查 Markdown 本地链接/锚点、配置名/路径/命令和中英文关键事实一致性；运行现有相关文档测试。文档测试通过不代表本规划中的运行时能力已实现。

## 6. 开始实施前需要确定的选择

- 选择阶段 B 的首个场景及可用账号/测试环境。
- 确认可恢复剖面的数据库范围与部署环境；当前建议先 PostgreSQL。
- 确认费用硬上限策略与记忆修订保留/删除政策。
- 各阶段按对应验收完成后，才把 canonical 文档中的状态从计划改为已实现/已验证；未通过的项目保持未完成。
