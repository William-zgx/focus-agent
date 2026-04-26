# P4-P35 多 Agent 协同开发技术文档

## Summary

P0-P3 已完成生产安全 fail-fast、API router 拆分、default tools 拆分、发布门禁口径、`AgentState` 分域 helper、`BranchService` facade 内部解耦。P4-P7 转向契约自动化、发布门禁一键化、可观测闭环、Auth / Access Model 产品化、Memory / Context 质量评测。P8-P10 把这些能力推进到真实回归闭环：Memory / Context 样本扩容、Auth ownership 运行时边界、release-health 真实部署信号 fail-closed。P11-P13 固化可审计发布证据包、真实样本 candidate 流水线、repository/service ownership audit。P14-P16 接到日常发布与线上回归流程：证据包留存、candidate promotion review、ownership audit export。P17-P26 完成发布证据、长期质量、ownership audit、Postgres 运维、可观测告警、Agent governance、Context quality、Tool Runtime 和 SDK/E2E drift guard。

P27-P35 已完成首轮执行：CI provider binding、nightly regression ops、production smoke、Auth token lifecycle、Postgres ops、Observability Alert Sink / OTel、Memory Review Console、Agent Governance Quality Dashboard 和 Docs/Ops Pack 都有可执行命令、机器可读 report、专项测试和文档状态。真实外部平台仍可继续增强，但本轮已不再停留在方案层。

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
- frontend SDK contract snapshot 还覆盖 `frontend-sdk/src/index.ts` barrel exports，以及 `apps/web/src` 对 `@focus-agent/web-sdk` 的导入清单，避免 SDK 类型/API 已变但 Web/E2E 入口未同步。
- Tool Runtime policy：runtime validator 失败会以 `validation_error` 返回，不进入 tool invoke / fallback；read-only timeout 与 upstream cancellation 不走 fallback、不写 cache；`side_effect=true` 的 tool 即使标注 `parallel_safe` 也会串行执行，并保留 side-effect runtime metadata。
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
- P14 将 release evidence 固化为发布制品：manifest 继续保留兼容结构，同时增加发布留存、失败摘要和生产 release id 约束。
- P15 在 candidate JSONL 与 golden baseline 之间加入显式 promotion review，默认只产出 review / promoted 文件，不自动污染金集。
- P16 将 ownership audit event 转为 trajectory / observability 兼容的导出结构，便于后续接入统一审计 sink。
- P17 release evidence 增加 artifact storage、release approval、retention 与存储校验字段；production evidence 缺 approved approval 会 fail closed。
- P18 Memory Regression Dashboard 支持 candidate / reviewed / promoted / golden 趋势报告、promotion history 与污染样本告警。
- P19 Ownership Audit Dashboard 支持 allow / deny 聚合、deny reason、resource/action/principal 维度统计与 deny trend export。
- P20 Postgres 运维验证可作为 release-health 输入，缺少迁移验证证据、失败状态或 errors 会阻断发布健康检查。
- P21 可观测告警规则报告可作为 release-health 输入，缺 executable rule coverage、firing alerts 或 failed status 会阻断发布健康检查。
- P22 Agent governance 补充真实子任务质量、成本画像、critic gate 与 review queue 的 observe-first 契约。
- P23 Context quality 增加 compaction semantic recall / precision / grounding / quality / drift 指标，并接入 Memory / Context trend report。
- P24 Tool Runtime 增加 validator 失败短路、取消/超时不走 fallback、side-effect tool 串行执行与 runtime metadata。
- P25 Autonomy 默认 observe-first：技能自选、分支建议与高风险 workflow 只输出建议、证据和风险边界。
- P26 Contract check 增加 frontend SDK barrel exports 与 Web App `@focus-agent/web-sdk` 实际导入面快照，补 SDK/E2E drift 防线。
- P27 CI Provider Binding：新增 GitHub Actions release gate workflow、protected environment 绑定、CI release gate/evidence Make targets、Buildkite/generic CI 文档命令和 artifact retention 示例。
- P28 Nightly Regression Ops：新增 nightly GitHub workflow、`make nightly-regression`、`reports/nightly/latest.json`，聚合 memory eval、trend、trajectory replay、alert 和 candidate review summary；缺核心 memory artifacts 会 fail closed。
- P29 Production E2E / Load Smoke：新增 `make production-smoke` 和 `reports/release-gate/production-smoke.json`，dry-run / live 都覆盖 API、SDK、Web、graph、安全和 rate-limit smoke。
- P30 Auth Token Lifecycle 已补生产 token lifecycle 文档和回归：issuer、audience、TTL、secret rotation、expired/wrong issuer/wrong audience/missing audience、demo token 生产禁用、`tenant_id` / `scope` 不绕过 ownership。
- P31 Postgres Ops：新增 `make postgres-ops`、`reports/release-gate/postgres-ops.json` 和 release-health 读取逻辑；report schema 固定包含 `status`、`passed`、`command`、`checks`、`errors`、`artifacts`。
- P32 Observability Alert Sink / OTel：新增 `make otel-smoke`、`reports/release-gate/otel-smoke.json`；alert、production smoke、Postgres ops、OTel smoke 均可接入 release-health 和 evidence pack。
- P33 Memory Review Console：nightly report 暴露 candidate queue、pending / promoted case id、review summary 和 `golden_write=disabled` 边界，继续禁止自动写 golden dataset。
- P34 Agent Governance Quality Dashboard：新增 `make agent-governance-report` 和 `reports/agent-governance/latest.json`，聚合 delegation、critic、review queue、cost/token/tool-call 质量信号。
- P35 Docs / Ops Pack：release checklist、observability runbook、CI 文档、roadmap、deep research、memory/governance docs 已同步 dry-run 与 production 示例。
- Memory / Context 质量先以 deterministic probe 落地，覆盖 required markers、forbidden stale markers、最大上下文长度。

## 默认验证命令

```bash
make contract-check
uv run pytest tests/test_contract_checks.py tests/test_tool_runtime.py
make release-gate RELEASE_GATE_ARGS="--dry-run --only lint,ci-test"
.venv/bin/pytest tests/test_contract_checks.py tests/test_release_gate.py tests/test_release_evidence.py tests/test_observability_release_health.py tests/test_memory_context_eval.py tests/test_auth.py tests/test_config_security.py tests/test_auth_ownership.py tests/test_release_health_check.py tests/test_nightly_regression.py tests/test_production_smoke.py tests/test_postgres_ops.py tests/test_otel_smoke.py tests/test_agent_governance_report.py
uv run ruff check src/focus_agent/auth.py src/focus_agent/config.py tests/test_auth.py tests/test_config_security.py tests/test_auth_ownership.py
make nightly-regression
make production-smoke PRODUCTION_SMOKE_ARGS="--dry-run --base-url https://focus-agent.example.com"
make postgres-ops POSTGRES_OPS_ARGS="--dry-run"
make otel-smoke OTEL_SMOKE_ARGS="--dry-run --endpoint http://otel-collector:4318"
make agent-governance-report
```

## P27-P35 执行矩阵

本轮采用多 Agent 分区实现，合并顺序为 CI Provider -> Nightly Regression -> Production E2E -> Auth Lifecycle -> Postgres Ops -> Observability Sink -> Memory Review -> Governance Dashboard -> Docs -> Reviewer -> Verifier。

| 优先级 | 方向 | Agent 责任 | 主要产物 |
|---|---|---|---|
| P27 | CI Provider Binding | Release Agent 将 evidence pack storage / approval 绑定到 CI | `.github/workflows/release-gate.yml`、`make ci-release-gate`、`make ci-release-evidence`、CI 文档 |
| P28 | Nightly Regression Ops | Memory / Observability Agent 接 trend、alert、eval replay 到 nightly | `.github/workflows/nightly-regression.yml`、`reports/nightly/latest.json`、candidate summary |
| P29 | Production E2E / Load Smoke | SDK / E2E Agent 固化生产 smoke report | `scripts/production_smoke.py`、API/SDK/Web/graph/security/rate-limit categories |
| P30 | Auth Token Lifecycle | Auth Agent 收口生产 JWT 生命周期 | issuer/audience/TTL/rotation docs、focused tests |
| P31 | Postgres Backup / Restore / Retention | Postgres Ops Agent 固化 ops report schema | `scripts/postgres_ops.py`、release-health ingestion、runbook 命令 |
| P32 | Observability Alert Sink / OTel | Observability Agent 接 alert/OTel smoke | `scripts/otel_smoke.py`、release-health/evidence ingestion |
| P33 | Memory Review Console | Memory Review Agent 产品化 candidate review summary | nightly `memory_review`、`candidate_outputs`、golden-write disabled |
| P34 | Governance Quality Dashboard | Governance Agent 聚合治理质量趋势 | `scripts/agent_governance_report.py`、`reports/agent-governance/latest.json` |
| P35 | Docs / Ops Pack | Docs Agent 同步发布/运维/路线图文档 | release checklist、observability runbook、CI docs、deep research 状态表 |

完整发布前运行：

```bash
make release-gate
make release-evidence RELEASE_EVIDENCE_ARGS="--release-id <release-id> --approval-id <approval-id> --approval-status approved --readyz-json reports/release-gate/readyz.json --trajectory-stats-json reports/release-gate/trajectory-stats.json --replay-comparisons-json reports/release-gate/replay-comparisons.json --alert-report-json reports/release-gate/alert-report.json --postgres-migration-report-json reports/release-gate/postgres-migration.json --production-smoke-report-json reports/release-gate/production-smoke.json --postgres-ops-report-json reports/release-gate/postgres-ops.json --otel-smoke-report-json reports/release-gate/otel-smoke.json --eval-report-json reports/release-gate/eval-smoke.json --baseline-eval-report-json reports/release-gate/baseline-eval-smoke.json"
```

## 后续真实环境增强

- Postgres ops 当前已固化 report schema 和 dry-run / fail-closed 边界，真实 `pg_dump` / `pg_restore` round-trip、RPO/RTO 和 retention cleanup 仍应接到部署平台。
- OTel smoke 当前可验证 endpoint/config/report contract，真实 collector round-trip 需要部署侧提供 collector 凭证和 trace 查询能力。
- Production smoke 当前提供轻量 HTTP 探针和分类报告，后续可以把 typed SDK stream、真实 graph turn 和更细 rate-limit 压测接入同一 JSON schema。
