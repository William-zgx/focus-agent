# 决策模型配置：合并与真实场景验收

## 版本与边界

- 工作分支：`codex/decision-model-routing`。
- 功能提交：`fadd162`；合并 `origin/main` 的 `556098d` 后，合并提交为 `921d0d7`。
- 远端最新代码包含上下文压缩、线程安全、分支交互修复。唯一文本冲突是 `tests/contracts/frontend_sdk.json`，根据合并后代码重新生成，未丢弃任一方字段。
- 验证使用当前工作树源码；原工作区、现有服务和默认模型配置未改动。
- 原始本机证据目录：`/tmp/focus-decision-validation-svi8wv3s`。该目录包含 JSON、日志和截图，不随源码分发；不包含 API Key。

## 真实应用链路

使用真实 Chrome 149、隔离 API、独立 SQLite/checkpoint/artifact/workspace；主聊天模型为 `deepseek:deepseek-v4-pro`，推荐主模型为 `codiv:openjev-0.1`，备用模型为 DeepSeek。API 使用正式 `create_app`，没有模型响应 fixture。

| 场景 | 证据与结果 |
| --- | --- |
| 多轮约束与压缩 | `context-browser/context-ui.json`：15 步通过。两周方案中保留 8 万元预算、敏感数据限制、E-930 证据编号；压缩前后原始消息保持一致，压缩后能够回忆约束。 |
| 父子分支隔离 | 同一真实浏览器场景：子分支预算改为 9 万元后，刷新回到主线仍为 8 万元；验证了分叉、刷新与移动布局。 |
| 工具长结果回读 | `tool-browser/context-ui.json`：4 步通过。读取 300 行非敏感文件，再通过真实 tool call ID 和 offset 用 `artifact_read` 回读中段，返回未在用户提示中透露的随机校验码。 |
| 决策链路实际调用 | `live-events.json`：主线程共 11 个推荐事件，其中 9 次实际调用 System One；均保持继续当前话题，未误创建分支。此阶段为 `shadow`。 |
| 建议与确认 | `live-suggest.json`、`live-suggest-assertions.json`：退款幂等背景下，日志归档、文学比较、旅行交通三个新话题均由 System One 生成待确认建议。确认前子分支数为 0，确认后为 1，父线程正确。 |

三个建议场景在运行前固定输入，没有使用“另开分支”等会绕过语义模型的显式措辞；本地规则评分预检均为 `continue_current`，真实最终事件均记录 `protocol=system_one`。置信度分别为 0.9571、0.9764、0.9694。它们证明本次协议与业务链路可用，不代表任意话题都能达到相同准确率。

真实浏览器复现入口：

```bash
# 先启动配置了真实 provider 的隔离 API，并构建当前版本 Web。
python scripts/context_ui_smoke.py \
  --app-url http://127.0.0.1:PORT/app/ \
  --health-url http://127.0.0.1:PORT/healthz \
  --chrome-path /path/to/chrome \
  --model deepseek:deepseek-v4-pro \
  --out-dir /path/to/evidence/context-browser
# 增加 --tool-observation-workspace /path/to/isolated/workspace 运行工具回读场景。
```

## 固定样本与双向备用

可复现工具为 `scripts/decision_model_eval.py`，数据为 `tests/eval/datasets/branch_decision_models.json`：18 个标准案例覆盖中文/英文/混合追问、纠正、短句歧义、引用指令、无历史、子题与兄弟话题；另有 2 个故障注入案例。该层使用真实 provider、真实 `BranchDecisionService`，graph 与治理仓库为内存实现，不把它当成真实分支创建证据；真正的 API 分支创建见上一节。

| 结果 | DeepSeek | Codiv / OpenJev |
| --- | --- | --- |
| 标准案例 | 18 | 18 |
| 规则直接处理 | 11 | 11 |
| 实际语义请求 | 7：6 成功、1 超时 | 7：全部成功 |
| 成功请求原始动作匹配 | 6/6 | 6/7 |
| 最终业务动作匹配 | 18/18，含超时保守继续 | 18/18，含拓扑修正 |
| 成功模型调用耗时中位数 | 6.136 秒 | 0.413 秒 |

这不是 18 次独立模型判断的正确率，也不是生产性能承诺。OpenJev 的一项原始输出把已有分支上的新题判为 child，现有业务拓扑规则修正为 sibling。DeepSeek 的超时案例原本就应继续，因此最终动作匹配不能掩盖请求失败。

故障注入仅将主模型 endpoint 指向本地不可连接端口，不伪造备用响应：

- Codiv → DeepSeek：主请求连接失败，真实备用返回 0.95，生成待确认分支动作。
- DeepSeek → Codiv：主请求连接失败，真实备用成功返回，但 confidence=0.7703，低于 0.9，最终保守继续。**备用调用恢复成功，语义建议漏报一次**；未降低门槛把它改为通过。

最终数据：`decision-model-eval-final.json`；逐案例记录：`decision-model-progress.jsonl`。建议保留可选配置并先用 `shadow` 观察，不能据此开启默认自动分支。

验收数据来自 `decision-model-eval-with-openai.json` 的完整运行（18 个标准案例 × 2 个模型，加 2 个备用案例，共 38 次案例执行）。`decision-model-eval-final.json` 仅修正汇总统计，没有再次调用模型。此前的诊断运行缺少可选依赖 `langchain-openai`，且 Codiv 故障注入未生效，因此不作为双向备用验收证据；补齐依赖并修正注入后才完整重跑。预期标签未根据模型返回结果调整。复现 DeepSeek 聊天协议需要安装项目的 `openai` 可选依赖。

```bash
PYTHONPATH=src python scripts/decision_model_eval.py \
  --local-env-file /path/to/local.env \
  --model-catalog /path/to/models.toml \
  --codiv-key-file /path/to/codiv-api-key \
  --output /path/to/evidence/decision-model-eval.json \
  --progress-log /path/to/evidence/decision-model-progress.jsonl
```

该脚本输出测量报告；退出成功表示报告生成完成，不表示所有语义预期通过。密钥只从本地配置读取，不写入命令或报告。

## 前端与浏览器

- 合并后的 Node 前端回归：**64/64**。
- SDK TypeScript、Web TypeScript 与生产构建、Android local runtime smoke 通过；依赖来自当前 lockfile 的独立离线安装。
- `fixture-browser/result.json`：普通发送、失败、取消、分支确认执行、审计分支及切换等 9 项通过。
- `admin-browser/result.json`：协议保存往返、默认/助手/聊天池隔离、动态主备策略与中文文案、非法聊天默认模型 HTTP 400 均通过。
- `dismiss-browser/result.json`：点击“继续当前分支”持久化为 `dismissed`，没有调用 execute。
- 上述三个浏览器目录使用本地确定性 `ModelFixture`，只证明交互与 HTTP 契约，不计入真实模型质量样本。
- 本机 Chrome 起初缺中文字体；使用已有 `HeiTi.ttf` 和 Fontconfig 后刷新已存线程，未重跑模型。`context-browser/main-desktop-fonts.png` 与 `main-mobile-fonts.png` 中文可读，390×844 下无横向溢出。

## 自动化回归

- 标准 CI 环境（`FOCUS_AGENT_LOCAL_ENV_FILE=/tmp/focus-agent-ci-missing.env`）全量 pytest：**2404 passed、17 skipped、1 warning**。
- 当前树与纯 `origin/main` 的离线 `tests/eval`：各 **131 passed**；这些已计入全量结果，不重复累加。
- 合并后的协议、分类器与模型注册表重点检查：**54 passed**；API/SDK 契约与快照一致。

一次按模块重排的定向运行暴露了既有测试隔离问题：先执行模拟 `tiktoken` 不可用的 context usage 测试，会在进程级 LRU cache 中遗留失败结果；随后极小预算 Eval 使用字符 fallback，最终请求估算为 450/400，于是安全预算 guard 正确阻止模型调用。当前树与纯主线都可按同样顺序复现；清缓存后为 373/400，单独运行及标准全量顺序通过。没有降低运行时预算保护，也没有将该顺序依赖误报为决策模型回归。独立归档复现证据：`/tmp/focus-agent-ci-repro.s8nXLo`。

## 限制

- SQLite 与本地浏览器验证不替代 PostgreSQL、真实 Android 设备或生产负载测试。
- 本轮未改变生产配置、未部署、未推送远端。
- Provider 的 confidence 不是经过本项目校准的正确率；独立的 `0.9` 决策门槛仍应结合实际对话样本观察。
