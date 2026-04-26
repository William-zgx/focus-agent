# P4-P7 多 Agent 协同开发技术文档

## Summary

P0-P3 已完成生产安全 fail-fast、API router 拆分、default tools 拆分、发布门禁口径、`AgentState` 分域 helper、`BranchService` facade 内部解耦。P4-P7 转向契约自动化、发布门禁一键化、可观测闭环、Auth / Access Model 产品化、Memory / Context 质量评测。

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
- Auth / Access Model 支持可选 `AUTH_JWT_AUDIENCE`，生产 JWT 分发可明确 issuer/audience/TTL。
- Memory / Context 质量先以 deterministic probe 落地，覆盖 required markers、forbidden stale markers、最大上下文长度。

## 默认验证命令

```bash
make contract-check
make release-gate RELEASE_GATE_ARGS="--dry-run --only lint,ci-test"
.venv/bin/pytest tests/test_contract_checks.py tests/test_release_gate.py tests/test_observability_release_health.py tests/test_memory_context_eval.py tests/test_auth.py tests/test_config_security.py
```

完整发布前运行：

```bash
make release-gate
```
