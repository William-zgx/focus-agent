# MR 修复与质量验证（2026-10-03）

本次收口覆盖上下文优化、真实浏览器验收发现的问题及项目文档校准。基线为 `718be87`，提交分支为 `fix/context-quality-completion`；[9 月 30 日报告](2026-09-30-project-quality.md) 保留历史结果。

提交期间主线合入 `81f7a6f`（MR #2）；本分支已合入并保留其线程权限、readiness、Eval 证据、handoff 和运维修复。下表最终自动化结果对应合并后的代码，不沿用合并前结果。MR：[#3](https://github.com/William-zgx/focus-agent/pull/3)。

## 修复范围

- 统一实际模型请求预算（消息、工具 schema、输出预留），保护必需上下文并在超限时阻止调用；确定性增量压缩保留原始消息和结构化事实。
- 子分支不继承父摘要；近期消息以身份/稳定 ID 匹配，避免同文祖先消息重新进入本地上下文。无 ID 恢复副本回退到游标隔离后的本地序列。
- 大工具结果保存到 ArtifactStore，通过线程作用域内的 `tool-observation://` 分页回读；workspace lookup 暴露只读 `artifact_read`，不开放其他 artifact 或写工具。
- 显式 `read_file(...)` / `artifact_read(...)` 指令不再错误地优先选择 `search_code`；普通定义检索仍优先搜索。
- DeepSeek 支持思考的模型在 UI 明确关闭思考、catalog 未提供关闭配置时，发送 `thinking.type=disabled`；已有 catalog 参数和 reasoning 消息适配继续保留。
- 手动压缩使用实际编译图状态更新，待处理 interrupt 拒绝压缩；前端显示压缩错误而不产生 unhandled rejection。
- Uvicorn 保持信号所有权；应用 lifespan 只注册关闭 hook，修复独立 API 收到 SIGTERM 不退出。
- 历史处理卡的未决步骤显示“历史状态未知”，保留已知成功/失败；当前问答/审批 interrupt 不视为结束。
- 问答表单复用审批卡基础样式，移除被覆盖的重复声明；CSS 回到原预算，不增加行数/模块门槛。resize 控件纳入独立具名区域，主内容 landmark 保持顶层。
- seroval 仅更新兼容 lock resolution 到 1.5.3；Python 格式基线独立提交，不混淆行为修复。

## 证据与复现

本轮原始日志、JSON、截图在 `/tmp/focus-agent-mr-20261003.1e1lIW`。它是本机临时证据目录，不随源码分发；测试和浏览器脚本保留在仓库。报告中的本地 fallback 不能证明 PostgreSQL 或真实多 Agent 生产路径。

| 检查 | 最终结果 / 证据 |
|---|---|
| `make ci` / 后端全量 pytest（禁用本地 env bootstrap） | 整体 exit 0；2376 passed、17 skipped、1 warning，117.26 秒；`ci-merged.log`。skip 不计为通过 |
| 严格 Ruff / 全仓格式 | 通过；855 个 Python 文件格式通过，`format-merged.log` |
| API/SDK contract | 快照一致，159 paths / 169 operations；新增诊断字段已同步 |
| Architecture / compatibility | 无新增回归；兼容库存仍为 169 项，不增加 baseline |
| SDK/Web | typecheck、transport、全范围 lint/format、生产构建通过；`ci-merged.log` |
| Node 前端回归 | 63/63，包括历史/暂停状态与 compact rejection |
| CSS governance | 19,057 / 19,057 行，64 / 64 模块，`!important=0`；预算未放宽 |
| Web bundle | JS 1,086,958 / 1,250,000 B；CSS 431,343 / 575,000 B；最大 JS 453,885 / 550,000 B |
| npm 生产依赖审计 | `pnpm audit --prod --json` 全等级 0；`pnpm-audit.json` |
| Python 安装一致性 | `uv pip check`：76 packages compatible |
| Android local runtime | `pnpm android:runtime:smoke` 通过，不等于原生设备验收 |
| API 真实退出 | 隔离 API 多次 SIGTERM 正常退出，最终进程日志含 Application shutdown complete；原有 8000 进程未触碰 |
| 文档 / diff | 新增及改动 Markdown 的本地链接无缺失；`git diff --check` 通过 |

此前失败均保留在临时日志中；最终 pytest 是修复后的完整运行，而不是用局部通过推断全量绿色。工具 schema 新增 109 个估算 token 后，两项极小预算 eval fixture 从 600 调至 709，保持原消息额度与 180/260 的 observation 额度，不调整运行时预算或放宽污染断言。

### 真实浏览器

使用 Chrome for Testing 149.0.7827.55、已有原生 CDP 工具和真实 `deepseek:deepseek-v4-pro`。没有新增 Playwright/Puppeteer 或 axe 运行时依赖，未修改默认模型配置。验收 API/Web 使用独立 18000/15173 端口和 SQLite/checkpoint/artifact 路径，验收后正常停止；原有 8000 服务不变。

上下文复杂任务通过页面输入、发送、压缩、分叉及刷新验证：主线预算 8 万、禁止敏感数据、证据 E-930；子支预算改 9 万后主线仍应保持 8 万。长草稿只用于显现压缩按钮，不发送，也不代表满窗压力测试。具体任务通过不代表任意长历史无损。

工具分页任务创建 300 行非敏感资料，随机校验码位于长输出中间。模型先 `read_file`，再按实际工具调用 ID 通过 `artifact_read` 回读指定页并报告码；断言真实调用参数、成功工具结果和最终回答，不向提示泄漏答案。

最终报告：`context-browser-verified/context-ui.json` 为 passed，15 步、10 个真实模型回合；`tool-browser-complete/context-ui.json` 为 passed，4 步、2 个真实模型回合。两者 `response_fixture_used=false`，步骤中浏览器异常、console error 和失败 fetch 均为空。前者保留压缩前后原始消息相等断言，并通过刷新后的主/子预算隔离与 390×844 无横向溢出检查；中文桌面/移动截图已人工查看。UI 代码块包含语言/复制按钮文字，脚本从实际可见文本中提取 JSON 对象再断言，而非依赖固定 markdown 包装。

合入 `81f7a6f` 后，复用已保存线程再次通过真实模型压缩、回忆、子支改值、返回主线及移动布局：`context-browser-merged/context-ui.json`，passed、8 步、3 个新增模型回合。此轮验证运行的是合并后 API/Web，不把前一版本截图当作合并后证据。

```bash
# 先运行隔离 API/Web；workspace 必须与该 API 的 WORKSPACE_ROOT 相同。
.venv/bin/python scripts/context_ui_smoke.py \
  --app-url http://127.0.0.1:15173/app/ \
  --health-url http://127.0.0.1:18000/healthz \
  --model deepseek:deepseek-v4-pro \
  --tool-observation-workspace /path/to/isolated/workspace \
  --out-dir reports/context-tool-readback
# 删除 --tool-observation-workspace 即运行多轮压缩/分支场景。
```

问答表单 smoke 和 compact HTTP 409 故障注入使用合成响应，不计入真实模型回合。三页 axe-core 4.13.0（会话、笔记、治理）修复后均无已确认 violation；`color-contrast` 为 incomplete，不能据此声明 WCAG 合规。

合并后的生产 Web 构建另通过 `scripts/review_fixes_browser_smoke.py`：普通发送、失败、取消、branch handoff、audit-only 按钮与后端拒绝、分支切换均通过，见 `review-browser-merged/result.json`。它使用真实 Chrome、隔离 API 与确定性模型 fixture，不声称是真实 provider 质量评测。

## 保留边界

- Context preview 是估算；后续 plan/steer/AgentDefinition 等控制块由最终实际请求 guard 检查，不保证 preview 与最终模型 prompt 逐字相同。
- 本地没有可用 PostgreSQL、实际 Docker binary、Android SDK/adb，JDK 为 11；GitHub CI 的 PostgreSQL smoke 和 JDK 21 原生构建提供独立证据，不替代设备测试、Docker Agent 沙箱隔离或生产负载 drain。
- embedding unavailable、Zvec fallback、trajectory disabled 的本地状态不能证明真实检索、轨迹持久化或 Agent Team v2 真实执行。
- 生产依赖审计是时点检查，`uv pip check` 只验证依赖一致性，不是项目安全认证。
- 历史文档中标明的 audit-only Branch Action 控件、handoff optimistic entry 缺口已由主线 `81f7a6f` 修复并合入：audit-only 动作保留诊断且禁用确认/继续当前分支按钮，handoff 与普通发送共用 optimistic entry 初始化；这两项修复归属主线，不归属本次上下文收口。
