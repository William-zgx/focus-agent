# Focus Agent 技术架构现状与优化路线

## 一、项目概览

**Focus Agent** 是一个 Python AI 应用框架，核心特点是支持分支对话、实时流响应、访问控制和轻量级 Web UI。项目采用**单体应用 + 前后端分离**架构，Python 后端（FastAPI + LangGraph）+ React 前端 + TypeScript SDK。

### 项目规模
- **Python 代码**：70+ 个文件（包含新增中间件层）
- **后端框架**：FastAPI + LangGraph + LangChain
- **前端框架**：React 19 + Vite + Tailwind CSS 4
- **包管理**：pnpm（前端）+ Python 3.11+（后端）
- **测试**：pytest（后端）+ 单元测试 27+ 个文件

---

## 二、当前架构评价

### 2.1 核心优势

| 方面 | 评价 | 说明 |
|------|------|------|
| **设计理念** | ⭐⭐⭐⭐⭐ | 独特的分支对话设计，解决长对话中的上下文混乱问题 |
| **代码组织** | ⭐⭐⭐⭐ | 模块化清晰，关注点分离好（api/services/core/engine/skills/security） |
| **开发体验** | ⭐⭐⭐⭐ | 完整的本地开发支持（热重载、demo token、多模型适配） |
| **前后端解耦** | ⭐⭐⭐⭐ | TypeScript SDK + REST API 设计良好，前端已集成 Zustand + React Query |
| **文档质量** | ⭐⭐⭐⭐ | README 清晰，快速开始文档完善 |
| **可扩展性** | ⭐⭐⭐⭐ | 技能插件系统、工具注册表设计合理 |
| **安全机制** | ⭐⭐⭐ | JWT 认证实现稳定，但缺少网络层防护 |

### 2.2 原有问题与改进现状

#### A. 安全性（✅ 已改进）

**原问题**：缺少 CORS、速率限制、请求追踪

**实现方案**：
- ✅ **CORS 中间件** - 可配置的跨域资源共享（`CORS_ALLOWED_ORIGINS`）
- ✅ **滑动窗口限流** - 无外部依赖的内存限流器，聊天路由限速更严格
- ✅ **请求 ID 追踪** - 每个请求自动生成或保留客户端传入的 `X-Request-ID`
- ✅ **统一错误响应** - 标准信封格式 `{code, message, data, request_id}`

**新增配置**（在 `.env.example` 中）：
```env
CORS_ALLOWED_ORIGINS=http://localhost:5173,https://app.example.com
CORS_ALLOW_CREDENTIALS=true
RATE_LIMIT_ENABLED=true
RATE_LIMIT_PER_MINUTE=60
RATE_LIMIT_CHAT_PER_MINUTE=20
```

**关键文件**：
- `src/focus_agent/security/rate_limit.py` - 限流核心（线程安全）
- `src/focus_agent/api/middleware.py` - CORS + 请求 ID + 限流中间件
- `src/focus_agent/api/errors.py` - 统一异常处理和响应格式

#### B. 可观测性（部分改进）

**原问题**：缺少结构化日志、请求追踪、指标收集

**实现方案**：
- ✅ **请求级别日志** - 每个请求记录 `request_id`, `path`, `status`, `duration_ms`
- ⏳ **分布式追踪** - 中间件预留了 `request.state.request_id`，可集成 OpenTelemetry/Jaeger
- ⏳ **性能指标** - 中间件已记录响应时间，可集成 Prometheus

#### C. 前端性能（✅ 已改进）

**原问题**：无代码分割策略，首屏加载缓慢

**实现方案**：
- ✅ **Bundle 分割** - 在 `vite.config.ts` 中配置手动 chunks：
  - `react-vendor.js` - React + ReactDOM
  - `router.js` - TanStack Router
  - `query.js` - TanStack Query + DevTools
  - `state.js` - Zustand
  - `app.js` - 应用代码

**预期收益**：首屏 -40%，路由加载 -60%

#### D. 架构层面（未改进，需产品决策）

1. **数据持久化分层** - LangGraph checkpoint 与应用数据混在一起
2. **API 标准化** - 缺少分页、过滤、排序规范（可在需要时增量添加）
3. **前端状态管理文档** - Zustand + React Query 已集成，缺少使用指南

---

## 三、实施完成清单

### 第一阶段（✅ 已完成）- 安全加固

| 任务 | 状态 | 文件 |
|------|------|------|
| 添加 CORS 中间件 | ✅ | `src/focus_agent/api/middleware.py` |
| 实现滑动窗口限流 | ✅ | `src/focus_agent/security/rate_limit.py` |
| 请求 ID 追踪 | ✅ | `src/focus_agent/api/middleware.py` |
| 统一错误响应格式 | ✅ | `src/focus_agent/api/errors.py` |
| 更新 Settings 配置 | ✅ | `src/focus_agent/config.py` |
| 中间件测试覆盖 | ✅ | `tests/test_api_middleware.py` |

### 第二阶段（⏳ 待做）- 质量提升

| 任务 | 优先级 | 说明 |
|------|--------|------|
| 前端状态管理文档 | 中 | 补充 Zustand + React Query 最佳实践指南 |
| 单元测试扩充 | 中 | 补充关键业务逻辑的测试（目前 27 个测试文件） |
| 集成测试 | 低 | API 端到端测试（需 test database） |

### 第三阶段（⏳ 进行中）- 运维就绪

| 任务 | 状态 | 说明 |
|------|------|------|
| OpenTelemetry 集成 | ⏳ 待做 | 生产环境决策 |
| Docker 容器化（基础版） | ✅ 已完成 | 提供多阶段 `Dockerfile`、`compose.yaml`、`/data` volume 持久化 |
| CI/CD 增强 | ⏳ 待做 | 已有基础 `.github/workflows/ci.yml` |

---

## 四、架构分层详解

### 后端架构

```
FastAPI App
├── 中间件层（新增）
│   ├── RequestIdMiddleware     - 请求追踪
│   ├── RateLimitMiddleware    - 流量控制
│   └── CORSMiddleware         - 跨域资源
├── 异常处理器（新增）
│   ├── HTTPException          - 业务错误
│   ├── ValidationError        - 参数验证
│   └── UnhandledException     - 500 错误
├── API 层（routes）
│   ├── /healthz               - 健康检查
│   ├── /v1/auth/*             - 认证相关
│   ├── /v1/conversations/*    - 对话管理
│   ├── /v1/chat/*             - 聊天服务
│   └── /v1/branches/*         - 分支管理
├── 服务层（services）
│   ├── ChatService            - 聊天逻辑
│   ├── BranchService          - 分支操作
│   └── ...
├── 核心层（core）
│   ├── branching.py           - 分支模型
│   ├── context_policy.py      - 上下文管理
│   └── types.py               - 共享类型
├── 引擎层（engine）
│   └── runtime.py             - LangGraph 运行时
└── 安全层（security）
    ├── tokens.py              - JWT 认证
    └── rate_limit.py          - 流量限流（新增）
```

### 前端架构

```
Vite App
├── src/
│   ├── app/                   - 全局组件
│   ├── pages/                 - 页面级组件
│   ├── features/              - 功能模块
│   ├── entities/              - 业务实体
│   ├── shared/                - 共享工具
│   └── main.tsx               - 入口
├── vite.config.ts             - 构建配置（新增 chunk 分割）
└── tsconfig.json              - TypeScript 配置

Bundle 分割（生成在 dist/assets/）
├── react-vendor-xxx.js        - React 生态
├── router-xxx.js              - 路由框架
├── query-xxx.js               - 数据获取
├── state-xxx.js               - 状态管理
└── app-xxx.js                 - 应用代码
```

---

## 五、部署与运维指南

### 本地开发启动

```bash
# 1. 创建虚拟环境并安装依赖
python -m venv .venv
.venv/Scripts/pip install -e '.[openai,dev]'

# 2. 安装前端依赖
pnpm install

# 3. 启动（前后端热重载）
make serve          # 或 ./scripts/serve-dev.sh
```

访问：
- **API**：http://127.0.0.1:8000
- **Web 应用**：http://127.0.0.1:5173/app
- **API 文档**：http://127.0.0.1:8000/docs

### 生产部署

```bash
# 1. 构建前端
pnpm web:build

# 2. 启动 API（前端静态文件由 FastAPI 服务）
API_RELOAD=0 focus-agent-api
```

**重要配置**（`.env`）：
```env
# 安全设置
AUTH_DEMO_TOKENS_ENABLED=false
AUTH_JWT_SECRET=<strong-random-secret>
CORS_ALLOWED_ORIGINS=https://app.example.com

# 限流（共享环境必需）
RATE_LIMIT_ENABLED=true
RATE_LIMIT_PER_MINUTE=60
RATE_LIMIT_CHAT_PER_MINUTE=20

# 可选：数据库后端
DATABASE_URI=postgresql://user:pass@localhost/focus_agent
```

### Docker / Compose 部署

当前仓库已提供基础容器化部署路径：

- `Dockerfile` 通过多阶段构建生成 `apps/web/dist`，最终镜像直接运行 `focus-agent-api`
- `compose.yaml` 默认将仓库内 `./.focus_agent` 挂到容器 `/data`，让本地 Docker 与非容器运行共享模型目录、凭证文件和持久化状态；如需隔离，可改用 named volume
- 容器默认以 `API_HOST=0.0.0.0`、`API_RELOAD=0` 启动，并开启 demo token 自举以匹配内置 Web 应用的本地体验；若用于共享环境，需显式设置 `FOCUS_AGENT_AUTH_DEMO_TOKENS_ENABLED=false`

```bash
export OPENAI_API_KEY=replace-me
export FOCUS_AGENT_AUTH_JWT_SECRET=<strong-random-secret>
docker compose up --build
```

可选配置：

- `FOCUS_AGENT_MODEL=openai:gpt-4.1-mini`
- `FOCUS_AGENT_DATABASE_URI=postgresql://user:pass@host:5432/db?sslmode=disable`

说明：

- 不设置 `FOCUS_AGENT_DATABASE_URI` 时，当前容器仍走本地持久化基线：branch 元数据保存在 `/data/branches.sqlite3`，LangGraph checkpoint/store 保存在 `/data/langgraph-*.pkl`
- 设置 `FOCUS_AGENT_DATABASE_URI` 后，当前只会把 LangGraph checkpoint/store 切到 Postgres；branch repository 仍然使用 SQLite。这与路线图中的 `Postgres 仓储` 后续项保持一致

---

## 六、监控与告警指标

建议在生产环境监控以下关键指标：

| 指标 | 目标 | 工具 |
|------|------|------|
| API 响应时间 | P95 < 200ms | 从日志中提取 `duration_ms` |
| 错误率 | < 0.1% | 计数 `status_code >= 500` |
| 限流触发率 | < 5% | 计数 `status_code == 429` |
| 认证失败率 | < 1% | 计数 `status_code == 401` |
| 前端首屏时间 | < 2s | 浏览器性能 API |
| 聊天流完成率 | > 99% | 监控 `/v1/chat/turns/stream` 完成 |

---

## 七、已知限制与未来优化

### 当前限制

1. **限流实现**
   - 基于内存，不支持分布式部署
   - 改进：可替换为 Redis 后端（保持同样的 `RateLimiter` 接口）

2. **持久化层**
   - 分支元数据用 SQLite（本地默认 `.focus_agent/branches.sqlite3`，容器默认 `/data/branches.sqlite3`）
   - 对话历史依赖 LangGraph checkpoint；即使设置 `DATABASE_URI`，当前也只切换 checkpoint/store，不切换 branch repository
   - 改进：分离成专用的数据层，支持多种后端，并补齐 Postgres branch repository

3. **错误恢复**
   - 流式响应中断没有重试机制
   - 改进：实现分块编码，支持断点续传

### 下一步优化方向

**优先级排序**（按产品价值）：

1. **🔴 高优先级**
   - 前端状态管理文档与示例
   - 生产环境部署指南（含 Docker）
   - 负载测试与性能基准

2. **🟡 中优先级**
   - 数据库迁移脚本与备份策略
   - OpenTelemetry 集成（分布式追踪）
   - WebSocket 长连接优化（替代 SSE）

3. **🟢 低优先级**
   - GraphQL API 层（可选）
   - 缓存层（Redis）
   - 消息队列（用于异步任务）

---

## 八、开发者指南

### 添加新的 API 端点

1. 在 `src/focus_agent/api/contracts.py` 定义请求/响应模型
2. 在 `src/focus_agent/api/main.py` 的 `create_app()` 中添加路由
3. 利用 `Depends(get_current_principal)` 进行认证检查
4. 错误通过 `HTTPException` 抛出，会自动被格式化

### 使用新的请求 ID 追踪

```python
# 在任何地方可以获取当前请求的 ID
@app.get("/v1/example")
def example(request: Request):
    request_id = request.state.request_id  # 自动生成或从客户端读取
    # 用于日志关联、问题追踪等
    return {"request_id": request_id}
```

### 前端集成示例

```typescript
// 使用 React Query 获取数据
const { data, isLoading } = useQuery({
  queryKey: ['conversations'],
  queryFn: () => api.get('/v1/conversations'),
  staleTime: 30000,
});

// 自动附加 Authorization header 和 request ID
const api = axiosInstance.create({
  baseURL: '/v1',
  headers: {
    'X-Request-ID': generateId(), // 可选：关联客户端生成的 ID
  },
});
```

---

## 九、文件导航

**架构相关文件**：
- 本文件：`docs/architecture.md` - 最新架构说明
- 快速开始：`README.md`
- 安全策略：`SECURITY.md`
- 贡献指南：`CONTRIBUTING.md`

**核心代码**：
- 后端入口：`src/focus_agent/api/main.py`
- 配置管理：`src/focus_agent/config.py`
- 中间件层：`src/focus_agent/api/middleware.py`
- 安全模块：`src/focus_agent/security/`

**测试**：
- API 中间件测试：`tests/test_api_middleware.py`
- 全部测试：`tests/`

**部署**：
- GitHub Actions：`.github/workflows/ci.yml`
- 启动脚本：`scripts/serve-dev.sh`, `scripts/serve-prod.sh`

---

## 十、版本更新记录

### v1.1.0 (2026-04-18) - 安全加固版

✅ **新增功能**：
- CORS 中间件与可配置源列表
- 滑动窗口限流器（线程安全，无外部依赖）
- 请求 ID 自动追踪与日志关联
- 统一错误响应信封格式
- Vite bundle 分割优化

✅ **测试覆盖**：
- 新增 `tests/test_api_middleware.py` 覆盖所有中间件功能

⚙️ **配置变更**：
- `.env.example` 新增 `CORS_*` 和 `RATE_LIMIT_*` 选项
- 默认行为不变（CORS 空、限流关闭），确保向后兼容

---

## 常见问题 (FAQ)

**Q: 限流会影响正常用户吗？**
A: 默认禁用。开启时，普通 API 每分钟 60 次，聊天 API 每分钟 20 次，足以覆盖典型用户场景。

**Q: CORS 配置如何在本地和生产间切换？**
A: 在 `.focus_agent/local.env`（本地）或 `.env`（生产）中设置不同的 `CORS_ALLOWED_ORIGINS`。

**Q: 如何自定义错误响应格式？**
A: 修改 `src/focus_agent/api/errors.py` 中的 `_build_envelope()` 函数。

**Q: 前端如何获取和使用 request ID？**
A: 从响应头 `X-Request-ID` 读取，用于前端日志关联和问题追踪。

---

**最后更新**：2026-04-18 | **维护者**：Focus Agent 团队
