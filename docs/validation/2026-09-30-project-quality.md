# 项目质量与真实浏览器验收（2026-09-30）

历史记录：后续修复与最终门禁结果见 [2026-10-03 MR 收口报告](2026-10-03-mr-quality.md)。以下结果保留当时状态，不作为最新未修复清单。

## 结论与边界

本轮对当前工作区执行了后端全量测试、源码与契约门禁、SDK/Web/Android Web 检查、生产依赖审计，以及真实 Chrome 的多轮模型任务。发现并修复了上下文压缩的真实 LangGraph 状态更新错误、暂停中断保护、前端 Promise 错误处理和中文无工具指令路由问题；补齐对应回归。

**不是全量发布认证。** CSS 预算、未改动的 Python 格式基线仍有欠账；PostgreSQL、Docker 安全隔离、Android 原生设备和部分真实多 Agent 工作流未在此环境验证。`ready=true` 和局部绿色测试不能替代这些证据。

- 源码基线：`718be87`，验收对象包含此前文档与上下文优化的未提交改动；不是只验证 HEAD。
- 原有端口 8000 服务未修改。验收另起 API `127.0.0.1:18000`、Web `127.0.0.1:15173`，独立 SQLite/checkpoint/store/artifact 路径。
- Chrome：Google Chrome for Testing `149.0.7827.55`，原生 CDP。没有新增 Playwright/Puppeteer 依赖。
- 模型：验收实例使用 `deepseek:deepseek-v4-pro`，真实远端调用；没有修改项目默认模型配置。
- 主证据目录：`/tmp/focus-agent-quality-20260930.sF1Gs0`；后端门禁日志：`/tmp/focus-agent-acceptance.ESBrF5`。临时目录可能清理，命令与测试留在仓库。
- 成功浏览器报告、中文截图和后端最终日志另保存到仓库本地 `reports/project-quality/2026-09-30/`（gitignored，不随源码分发）；没有删除验收数据库或用户数据。
- 验收结束后停止仅本轮创建的 18000/15173 临时服务；原有 8000 服务未停止。后端修复另经只读独立 Agent 审查，未发现有直接证据的新增问题。

## 自动化结果

| 检查 | 本轮证据 | 判断 |
|---|---|---|
| 后端全量 pytest | 首次 2331 passed / 7 failed / 17 skipped；修复后全量 2340 passed / 2 failed / 17 skipped | 最后两个失败是新增测试将实际 `direct_answer` 错写为 `direct_writing`；修正断言后该文件 4/4 通过。没有再宣称一次不存在的全量全绿输出 |
| 实际编译图回归 | `tests/test_context_compaction_graph.py` 4 passed | 完成图手动压缩、原始消息不变、等待中断拒绝压缩、resume 保留、无工具指令路由 |
| 工具结果与执行层回归 | `test_tool_observation_retrieval.py`、`test_tool_result_hooks.py`、`test_harness_tools.py`、`test_harness_middleware.py`，22 passed | 大结果原文回读与执行结果整理的行为证据；不等于真实模型工具调用验收 |
| Python lint | `make lint-strict` 通过 | 无新增 lint 错误 |
| Python 格式 | 39 个改动/新增 Python 文件通过；全仓仍有 51 个未改动文件不满足格式基线 | 全仓 `make format-check` 不能标绿；没有扩张为无关批量格式重写 |
| API/SDK 契约 | `make contract-check` 通过；重新导出 OpenAPI/生成 SDK 后与验收前文件 `cmp` 一致 | 新增 context usage 字段同步契约快照；159 paths / 169 operations，未新增路由。工作区含有意生成文件改动，因此未把相对 HEAD 的 `git diff` 当作生成漂移 |
| Architecture | `make architecture-gate`，`issue_count=0` | tool execution 的结果构造移入已有 hooks，未放宽 800 行门槛 |
| Compatibility | `make compat-gate` 通过 | 既有 169 项兼容库存，无新增回归 |
| SDK | 类型检查、构建、transport 检查通过 | SDK 表面与流传输检查通过 |
| Web | 类型检查、构建通过，437 modules；lint/format 326 files 通过 | 不代替 CSS 专项预算 |
| 流与页面回归 | `node --test tests/test_thread_stream_frontend_regressions.mjs`，61/61 | 包含压缩失败无 unhandled rejection 的实际 handler 回归 |
| Web bundle | JS 1,085,694 / 1,250,000 B，CSS 433,077 / 575,000 B | 最大 JS 452,621 B，最大 CSS 365,029 B；预算通过 |
| CSS governance | 无 `!important` 和硬编码 hex 检查通过；LOC 19,235 / 19,057，模块 65 / 64 | 既有提交 `a926d97` 的问答表单样式导致预算超额，本轮没有 CSS 源文件变更；没有放宽预算 |
| Python 安装一致性 | `uv pip check`，76 packages compatible | 仅依赖兼容性，不是 Python 漏洞审计 |
| npm 生产依赖审计 | 初始 critical=1；修补并实际安装后 `pnpm audit --prod --json` exit 0、critical/high=0 | 审计时点证据，不是项目安全认证 |
| Android local runtime | runtime smoke、8 个桥接/安全用例、Web debug 构建（401 modules）通过 | 未验证原生 Gradle、模拟器或真机 |
| Diff whitespace | `git diff --check` 通过 | 保留原有工作区改动 |

后端原始输出保存在 `pytest-final.log`、`context-graph-final.log`；全量仍有 17 个 skip，本轮没有将其计为通过，也没有推断全部 skip 的原因。

## 真实 Chrome + 真实 provider 的复杂任务

可复用脚本：[`scripts/context_ui_smoke.py`](../../scripts/context_ui_smoke.py)。该脚本通过页面输入框、模型选择、发送、压缩和分叉按钮操作，不直接替代 UI 提交业务请求。

`context-browser-final/context-ui.json`：`status=passed`、`mode=real_provider`、`response_fixture_used=false`；**15 个步骤、10 个真实模型回合**。记录的各步 browser errors、console errors、failed fetches 均为空。

1. 新建会话，通过 UI 选择 Deepseek 并关闭思考模式。
2. 主线七轮制定“方案设计 Agent 两周验证计划”，保留预算 8 万、禁止上传敏感数据、证据 `E-930`，讨论候选方案、量化指标、阶段计划和分支/刷新验收标准。
3. 输入大草稿使当前按钮显现，**不发送草稿**；点击手动压缩后清空草稿。断言压缩前后完整原始 messages 相等、摘要与压缩时间落盘。
4. 压缩后真实模型回忆预算、限制和证据。
5. 页面分叉，在子分支改预算为 9 万，真实回复 JSON `{"budget_wan":9}`。
6. 返回主线并刷新，再问真实模型，回复 JSON `{"budget_wan":8,"evidence":"E-930"}`，确认未受子分支污染。
7. 切换 390×844 视口，页面 scroll width=390，输入框存在。

这是一个具体任务的事实保持证据，不是任意长任务的无损语义压缩证明。已有图内摘要可能使手动压缩没有额外收益；`no_gain` 不能报告为 token 节省。长草稿只用于触发既有 UI 阈值，不代表完成了 128k 满窗压力测试。

### 单独的 fixture / 故障注入

- `context-browser-fault-verified/context-ui.json`：真实 Chrome，在 SDK 初始化前注入 compact HTTP 409。页面显示 `QA injected busy thread`，没有未处理异常。标记 `mode=injected_compact_error`、`response_fixture_used=true`、`provider_used=false`，不混入真实模型回合计数。
- `scripts/ask_user_question_ui_smoke.py`：真实 Chrome 的表单、多选、Other 输入与单次 resume 通过。线程中断和 resume 返回是合成 fixture，不声称真实 provider 主动提出问题或真实工具审批完成。
- 首次默认 Qwen provider 返回 429，另一 OpenRouter 模型返回 502 空响应；保留失败日志，切换可用模型后才取得真实模型验收证据。这些不是成功回合。

### 补充结论工作流与页面巡检

修补依赖并重启 Vite 后，现有 `scripts/ui_smoke_test.py` 使用同一真实 Deepseek 模型完成聊天、分叉、点击生成结论入口并进入 `/review`，退出码 0。证据：`ui-smoke-final.log`。这证明审查入口工作流，不单独证明 proposal 内容质量、审批与合并的全部业务规则均已浏览器验证。

另以真实 Chrome 只读巡检 15 个路由：当前线程、笔记、任务、角色、治理、记忆、Agent Team、配置、用户、审计、个人资料、安全、会话、observability overview 和 trajectory。前 13 个路由未记录浏览器异常、console error 或失败 fetch；两个 observability 路由因轨迹存储未启用而请求返回 503，不能标为通过。所有桌面视口宽度 1440，scroll width 未超出 1440。页面能够加载不等于其全部增删改、授权和任务执行已验收。

最初远端缺中文字体，截图存在方框。临时下载官方 Noto Sans CJK SC 到验收目录，通过独立 `FONTCONFIG_FILE` 启动 Chrome 后补拍，确认中文可读；未修改系统或产品字体配置。`route-browser/routes.json` 与 `route-00.png` / `main-mobile-cjk.png` 是实际新依赖环境的巡检/中文截图证据；该只读巡检不计入真实模型回合数。

## 本轮修复

| 根因 | 最小修改 | 验证 |
|---|---|---|
| 手动压缩对真实编译图写入不存在的 `context_compaction` 节点，HTTP 500 | `update_state` 不传虚构节点，由 LangGraph 按实际图游标更新 | 实际 production compiled graph 测试 + 浏览器压缩 |
| 对等待用户/审批的 checkpoint 更新会清除 pending interrupt | 新鲜快照存在 interrupts 时，拒绝压缩并返回 409，不改动 checkpoint | 动态 interrupt 图，验证中断不变且 `Command(resume=...)` 可继续 |
| 前端 compact mutation 被拒绝后出现 unhandled rejection | handler 捕获 rejection，继续使用已有 mutation error UI | Node handler 回归 + Chrome 409 注入 |
| “不调用工具 / 不调用任何工具”未被既有指令标记识别 | 在原标记集合增加两种中文表达 | 分类回归 + 真实模型压缩后回忆 |
| 工具执行文件超过架构行数限制 | 结果构造移动到已有 `tool_result_hooks.py`，不新增架构层 | 22 个相关用例 + architecture gate |
| 新 context usage 字段与快照不一致、旧预算 eval 未计算输出/工具额度 | 更新生成契约快照；显式配置 tiny-budget fixture 和实际需要的额度 | contract gate + 后端全量/相关回归 |
| seroval 1.5.2 生产依赖 critical 漏洞 | 仅更新兼容 lock resolution 为 1.5.3，执行 frozen 安装 | 实际依赖图、生产审计、Web build/check/bundle、61 回归 |

seroval 修复对应 [GHSA-mv8w-475r-vwqw / CVE-2026-59940](https://github.com/lxsmnsyc/seroval/security/advisories/GHSA-mv8w-475r-vwqw)。没有升级 TanStack 主版本、添加 override 或改动 manifest。

## 尚不能通过的门槛与下一步

| 项目 | 直接证据 / 限制 | 后续必要验证 |
|---|---|---|
| CSS budget、历史 Python 格式 | 上述两项基线门禁失败 | 单独收敛样式共享/经评审的预算变更；独立格式清理，不冒充本轮已修复 |
| 历史处理卡终态误导 | 中文补拍截图 `route-browser/main-mobile-cjk.png`：已 answered 且非 streaming，卡片仍显示“处理中 1” | 修复 transcript/activity 状态映射；不能将该状态归因于 trajectory disabled。本轮记录而未扩张修改流状态契约 |
| PostgreSQL / observability | 本环境无 PostgreSQL 可执行服务；readyz 为本地 fallback | 使用实际 PostgreSQL 跑 canonical observability 场景、持久化和并发门禁 |
| embedding / Zvec / trajectory | 验收进程明确报告 embedding unavailable、Zvec fallback、trajectory disabled | 配齐依赖后验证真实检索与轨迹，不用本地 fallback 证明这些能力 |
| Docker sandbox | Docker wrapper 的实际二进制缺失 | 实际 Docker fail-closed、隔离与取消测试；Chrome 的 `--no-sandbox` 不是产品沙箱证据 |
| Android native | JDK 11，缺 SDK/adb；CI 要求 JDK 21 | 原生 debug 构建、设备/模拟器、secure storage 和生命周期验收 |
| 真实 Agent Team v2 | 现有 real UI smoke 入口未实现真实执行；本轮没有启动真实多 Agent mission | 配齐 readiness 依赖并取得任务、证据、revision 的真实执行结果 |
| API graceful exit | 独立验收 API 收到 SIGTERM 后未退出，即使 active connections/jobs 为 0；只对该隔离进程强制停止以换载源码 | 已有信号注册路径需专门验证；原有 8000 进程未触碰，不声称优雅退出已修复 |
| 大工具原文回读 | 已有自动化运行时/作用域用例通过，未做真实模型浏览器工具分页任务 | 实际 provider 的大输出→引用→分页读回任务 |
| 可访问性与视觉差异 | 本轮截图与移动布局检查，不是 axe 审计或视觉 diff | 独立 a11y/键盘流程和稳定字体环境的视觉回归 |

处理卡的直接调用路径：[`message-transcript-builder.ts`](../../apps/web/src/entities/messages/message-transcript-builder.ts) 从历史 `turn_metadata.execution_contract` 构造步骤，将 `not_required` 等未识别状态映射为 `pending`；[`message-list-tool-activity-card.tsx`](../../apps/web/src/entities/messages/message-list-tool-activity-card.tsx) 把 pending 计入 running 并显示“处理中”。当前 transcript 构建未结合线程终态，持久化 `missing_required_tools` 或修复标记也可能保留 running。应区分历史诊断与当前活动，基于明确终态收口，而非简单将所有未知步骤改为成功。

## 复现

在独立配置的 API/Web 环境中运行（不要指向未经确认的生产数据）：

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest -q tests/test_context_compaction_graph.py
make lint-strict contract-check architecture-gate compat-gate
pnpm web:check
pnpm web:build
pnpm --filter @focus-agent/web-app bundle:check
pnpm exec node --test tests/test_thread_stream_frontend_regressions.mjs
pnpm audit --prod --json
.venv/bin/python scripts/context_ui_smoke.py \
  --chrome-path /path/to/chrome \
  --app-url http://127.0.0.1:15173/app/ \
  --health-url http://127.0.0.1:18000/healthz \
  --model deepseek:deepseek-v4-pro \
  --out-dir reports/context-browser
```

`--fault-injection-only --resume-thread-path /app/c/<root>/t/<thread>` 仅验证 HTTP 409 UI；`--resume-thread-path` 的真实模式复用已有测试会话，**不是从零执行七轮的完整证据**。脚本创建的会话是验收数据，不要与用户正式会话混用。

相关规范：[Validation Runbook](../validation-runbook.md)、[Context Window](../context-window.md)、[Frontend Visual System](../frontend-visual-system.md)、[Android](../android.md)。
