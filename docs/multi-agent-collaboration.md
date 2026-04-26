# P4-P10 多 Agent 协同开发技术文档

## Summary

P0-P3 已完成生产安全 fail-fast、API router 拆分、default tools 拆分、发布门禁口径、`AgentState` 分域 helper、`BranchService` facade 内部解耦。P4-P7 转向契约自动化、发布门禁一键化、可观测闭环、Auth / Access Model 产品化、Memory / Context 质量评测。P8-P10 继续把这些能力推进到真实回归闭环：Memory / Context 样本扩容、Auth ownership 运行时边界、release-health 真实部署信号 fail-closed。

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
- Memory / Context 质量先以 deterministic probe 落地，覆盖 required markers、forbidden stale markers、最大上下文长度。

## 默认验证命令

```bash
make contract-check
make release-gate RELEASE_GATE_ARGS="--dry-run --only lint,ci-test"
.venv/bin/pytest tests/test_contract_checks.py tests/test_release_gate.py tests/test_observability_release_health.py tests/test_memory_context_eval.py tests/test_auth.py tests/test_config_security.py tests/test_auth_ownership.py tests/test_release_health_check.py
```

## 下一轮建议

P8-P10 已经把质量评测、访问边界和 release-health fail-closed 补到首轮可用。下一轮不建议继续做大规模拆文件，优先把这些门禁接成真实生产闭环：

| 优先级 | 方向 | Agent 责任 | 主要产物 |
|---|---|---|---|
| P11 | Production Release Evidence Pack | Release / Observability Agent 采集真实 `/readyz`、trajectory stats、replay comparison、baseline eval report，并生成可审计发布证据包 | `reports/release-gate/<release-id>/`、生产 release-health 示例命令、证据包 schema |
| P12 | Memory / Context 真实样本流水线 | Memory / Context Eval Agent 将 trajectory export、replay report、线上 memory/context 样本脱敏、去重、分桶并纳入 baseline | 样本导入脚本、baseline 管理文档、真实 regression fixture |
| P13 | Ownership Persistence & Audit | Auth Agent 将 `user_id` ownership 语义下沉到持久化数据、repository/service 校验和审计记录 | ownership metadata 策略、audit log tests、跨 principal 回归矩阵 |

完整发布前运行：

```bash
make release-gate
```
