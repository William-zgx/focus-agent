# Auth / Access / Account 操作与边界

更新时间：2026-05-16

本文是 Focus Agent 当前认证、访问控制和普通账号自助页面的 canonical 文档。管理员用户治理见 [admin-console.md](admin-console.md)，部署侧生产安全配置见 [docker-deployment.md](docker-deployment.md)。

## 1. Web 入口

认证相关页面由 `apps/web/src/app/router.tsx` 挂在 `/app` basepath 下：

- `/app/auth/login`：用户名密码登录、`Demo 登录`、Bearer Token 登录；已登录时展示账号入口。
- `/app/auth/register`：自助注册用户名密码账号。
- `/app/account/profile`：查看当前 principal、用户资料、租户、状态和角色。
- `/app/account/security`：修改当前用户密码，或从当前会话退出。
- `/app/account/sessions`：查看当前用户 refresh sessions，并撤销非当前会话。

所有非 `/app/auth/*` 页面都通过 `AuthGate` 保护。未登录访问受保护页面时会跳转到 `/app/auth/login?return_to=...`，登录成功后回到原目标。账号切换没有单独 switcher，当前路径是退出后再用用户名密码、Demo 登录或 Bearer Token 重新登录。

## 2. API 与 SDK

认证 API 位于 `src/focus_agent/api/routers/auth_models.py`：

```text
POST /v1/auth/demo-token
POST /v1/auth/register
POST /v1/auth/login
POST /v1/auth/refresh
POST /v1/auth/logout
POST /v1/auth/change-password
GET  /v1/auth/sessions
POST /v1/auth/sessions/{session_id}/revoke
GET  /v1/auth/me
```

Frontend SDK 对应 `frontend-sdk/src/client/auth.ts` 和 `frontend-sdk/src/types/auth.ts`，公共方法包括 `register()`、`login()`、`logout()`、`refresh()`、`changePassword()`、`listMySessions()`、`revokeSession()`、`createDemoToken()` 和 `getPrincipal()`。

`/v1/auth/me` 是 Web App 判断当前 principal、持久化用户、角色、权限和 `is_admin` 的主入口。被禁用用户会被拒绝继续进入应用。

## 3. 访问控制边界

- `Principal.user_id` 是 conversation、thread、context、branch 和 merge 的 ownership 主键。
- `tenant_id` 当前是 principal metadata 和后续多租户扩展字段，不能替代 ownership。
- `scope` 表达 token 能力声明，但不能单独授予 admin 权限，也不能绕过资源 owner 校验。
- 管理员身份来自持久化用户角色和权限；Admin 细节由 [admin-console.md](admin-console.md) 维护。
- `AUTH_ENABLED=false` 只适合本地调试，此时 anonymous principal 仍不是 admin。
- 自助注册创建 active `member`，不会自动成为 admin。
- 本地/开发环境可以通过第一个非匿名用户或 `AUTH_BOOTSTRAP_ADMIN_USER_IDS` bootstrap admin；生产数据库必须显式授予管理员。

## 4. Token 与 Session 语义

- 用户名密码登录和自助注册会返回 access token、refresh token，并写入 auth cookies。
- `Demo 登录` 调用 `/v1/auth/demo-token` 后按 Bearer Token 登录处理；它不会创建 refresh session。
- `logout()` 会撤销 refresh session、清除 auth cookies，并移除 Web App 本地保存的 token。
- Access token 和 demo token 是无状态 token；已经复制出的 token 在过期或 key rotation 前仍可能被再次使用。
- `refresh()` 优先使用请求体中的 refresh token，否则读取 refresh cookie。
- 当前用户只能撤销自己的 session；管理员撤销其他用户 session 的流程属于 Admin Console。
- 修改密码需要当前密码和新密码；管理员 reset password 走 `/v1/admin/users/{user_id}/password`。

## 5. 生产配置原则

生产或预发环境必须关闭 demo token，并使用显式签发策略：

- `AUTH_ENABLED=true`
- `AUTH_DEMO_TOKENS_ENABLED=false`
- `AUTH_JWT_SECRET` 或 `AUTH_JWT_KEYS` 使用非开发密钥，且每个 active secret 至少 32 字符
- `AUTH_JWT_ISSUER` 与签发方一致
- 可选设置 `AUTH_JWT_AUDIENCE`
- `AUTH_ACCESS_TOKEN_TTL_SECONDS` 使用短窗口
- `RATE_LIMIT_ENABLED=true`

JWT key rotation 支持 `AUTH_JWT_KEY_ID` / `AUTH_JWT_KEYS`、`AUTH_JWT_SECRETS` 或 `AUTH_JWT_JWKS`。只要配置 key set，当前 `kid` 必须匹配 active key；错误 `kid` 不会 fallback 到其他 secret。非 development/local/test/ci 环境会在 `Settings.from_env()` 和 API lifespan 阶段 fail-fast：缺少签名密钥、使用开发默认密钥、active secret 少于 32 字符、关闭 auth、开启 demo token、关闭 rate limit、缺少 issuer 或 TTL 非法都会阻止启动。

## 6. 推荐验证

影响认证 API、token 生命周期、用户状态或 ownership 语义时：

```bash
uv run pytest tests/test_auth.py tests/test_auth_accounts_api.py tests/test_user_service.py tests/test_auth_ownership.py tests/test_config_security.py
make contract-check
```

影响 Web 登录页、账号页、route protection 或 SDK 类型时：

```bash
uv run pytest tests/test_web_app_scaffold.py
make sdk-check
make web-check
make web-build
```

真实浏览器检查应覆盖：未登录保护路由跳转、Demo 登录、用户名密码登录、自助注册后登录、Bearer Token 登录、侧栏退出、`/app/account/security` 修改密码、`/app/account/sessions` 撤销非当前会话，以及退出后重新登录完成账号切换。
