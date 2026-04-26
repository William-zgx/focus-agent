# P4-P13 多 Agent 协同开发技术文档

## Summary

P0-P3 已完成生产安全 fail-fast、API router 拆分、default tools 拆分、发布门禁口径、`AgentState` 分域 helper、`BranchService` facade 内部解耦。P4-P7 转向契约自动化、发布门禁一键化、可观测闭环、Auth / Access Model 产品化、Memory / Context 质量评测。P8-P10 把这些能力推进到真实回归闭环：Memory / Context 样本扩容、Auth ownership 运行时边界、release-health 真实部署信号 fail-closed。P11-P13 继续把闭环固化为可审计发布证据包、真实样本 candidate 流水线、repository/service ownership audit。

## Agent 分工

| Agent | 责任 | 主要产物 |
|---|---|---|
| Orchestrator / Integrator | 拆任务、控制合并顺序、处理冲突、维护验证矩阵 | 集成分支、最终验证报告 |
| Contract Agent | 防止 API / SDK / stream event 漂移 | `scripts/check_contracts.py`、`tests/contracts/*.json`、contract tests |
| Release Gate Agent | 一键执行发布门禁并输出机器可读报告 | `make release-gate`、`reports/release-gate/latest.json` |
| Observability Agent | 将 readiness、metrics、trajectory replay 转为发布健康信号 | release-health signals、observability runbook |
| Auth Agent | 把安全启动基线升级为生产访问模型 | JWT issuer/audience/TTL 策略、ownership 文档与测试 |
| Memory / Context Eval Agent | 将记忆与上下文质量转为可评测指标 | memory/context probes、eval/replay 指标 |
| Reviewer / Verifier | 只读审查与验证 | 兼容性审查、验证矩阵结果 |

## 当前落地

- `make contract-check` 校验 FastAPI route snapshot 与 frontend SDK contract snapshot。
- `make release-gate` 按固定顺序执行 lint、ci-test、SDK/Web check/build、UI smoke、observability smoke、eval smoke，并写入 JSON 报告。
- observability release-health signals 覆盖 runtime readiness、trajectory recorder、chat failure rate、tool fallback spike、eval replay regression。
- P7 memory/context probes 覆盖事实保真、关键事实召回、无关记忆污染、冲突记忆标记、compaction 后可回答率和 artifact refs。
- P8 memory/context regression probes 扩展到 failed replay、compaction 错答、冲突记忆误用、artifact refs 丢失和无关 memory 污染等 15+ deterministic 小样本。
- P8 支持从 trajectory export / replay report JSON 转换失败样本为可复现 memory-context case，全流程无外部 LLM 依赖。
- P9 Auth / Access Model 明确 `user_id` 是 ownership 主键；`tenant_id` 只是隔离扩展字段，`scopes` 只表达能力授权，跨 principal thread/context/branch/merge 访问必须拒绝。
- P9 生产 JWT 分发文档覆盖 issuer、audience、TTL、secret rotation 与 demo token 禁用策略。
- P10 release-health 支持 `local` / `live` / `production` 模式；production 缺少 readyz、trajectory stats、replay comparison 或 eval report 时直接 fail closed。
- P10 支持 baseline eval report comparison，eval regression、replay failed、trajectory recorder unavailable 都会阻断 release-health。
- P11 新增 `make release-evidence`，生产发布证据包写入 `reports/release-gate/<release-id>/manifest.json`，包含 readyz、trajectory stats、replay comparison、eval report、baseline eval report、release-health report 与命令摘要；production pack 缺 baseline 或其他 required artifact 会 fail closed。
- P12 `scripts/memory_context_eval.py` 支持从 trajectory export、replay report、memory-context report 导入 candidate JSONL，并在进入 golden baseline 前完成脱敏、去重、分桶和 baseline 标记。
- P13 新增 ownership audit helper，并把 thread ownership 校验接入 repository 层；allow / deny 事件记录 principal、resource type、resource id、action、decision、reason、request id。
- Memory / Context 质量先以 deterministic probe 落地，覆盖 required markers、forbidden stale markers、最大上下文长度。

## 默认验证命令

```bash
make contract-check
make release-gate RELEASE_GATE_ARGS="--dry-run --only lint,ci-test"
.venv/bin/pytest tests/test_contract_checks.py tests/test_release_gate.py tests/test_release_evidence.py tests/test_observability_release_health.py tests/test_memory_context_eval.py tests/test_auth.py tests/test_config_security.py tests/test_auth_ownership.py tests/test_release_health_check.py
```

## 下一轮建议

P11-P13 已经把生产发布证据、真实样本导入与 ownership audit 补到首轮可用。下一轮不建议继续做大规模拆文件，优先把这些闭环接到更真实的日常发布与线上回归流程：

| 优先级 | 方向 | Agent 责任 | 主要产物 |
|---|---|---|---|
| P14 | Evidence Pack CI / Storage Integration | Release Agent 将 `release-evidence` 接入实际发布任务，固定 artifact 留存位置与 release id 生成规则 | CI 示例、证据包保留策略、失败摘要模板 |
| P15 | Candidate Promotion Review | Memory / Context Eval Agent 将 candidate JSONL 引入人工确认与 golden promotion 流程 | candidate review checklist、promotion diff、样本污染保护 |
| P16 | Ownership Audit Export | Auth / Observability Agent 将 repository audit event 输出到 trajectory 或统一审计 sink | audit export adapter、查询说明、跨 principal deny dashboard |

完整发布前运行：

```bash
make release-gate
```
