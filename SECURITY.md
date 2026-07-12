# Security Policy

## Supported Versions

Focus Agent is still evolving quickly, so security fixes are most likely to land on the latest development line first.

Until a formal version support policy is published, please assume:

- the latest version in the default branch is the primary supported line
- older snapshots may not receive backported security fixes

## Reporting a Vulnerability

Please do not open a public GitHub issue for suspected security vulnerabilities.

Instead, report suspected vulnerabilities privately by email:

`zgx62313@163.com`

When reporting a vulnerability, please use a descriptive subject line such as `Focus Agent security report` and include enough detail for maintainers to reproduce and assess the issue safely.

Please avoid sharing exploit details publicly until maintainers have had a reasonable opportunity to investigate and release a fix or mitigation.

When reporting a vulnerability, please include:

- a clear description of the issue
- the affected component or file paths
- steps to reproduce, if available
- impact assessment
- any proof-of-concept details needed to validate the issue
- suggested mitigations, if you have them

Examples of relevant areas in this repository include:

- authentication and token handling
- persisted user status and session revocation
- cookie-authenticated mutation and CSRF handling
- thread ownership enforcement
- governance trajectory ownership enforcement
- outbound URL fetching and SSRF protection
- streaming output that may expose unintended data
- persistence and storage boundaries
- unsafe defaults in configuration or example code
- frontend SDK parsing or trust assumptions

## Response Expectations

Maintainers should aim to:

- acknowledge receipt within 5 business days
- reproduce and assess the report
- decide whether the issue requires immediate mitigation
- prepare a fix and coordinate disclosure timing when appropriate

## Disclosure Guidance

Please avoid public disclosure until maintainers have had a reasonable opportunity to investigate and address the issue.

## Hardening Notes for Maintainers

Before public release, maintainers should review:

- default secrets and development-only auth settings
- whether demo token issuance should remain enabled by default
- local config and environment variable handling
- dependency update posture
- artifact writing paths and filesystem assumptions
- any examples that could be mistaken for production-ready security defaults

Runtime startup now fails fast when `AUTH_ENABLED=true` and an explicitly
configured `AUTH_JWT_SECRET` or active JWT key is shorter than 32 characters or
contains placeholder text such as `change`, `example`, or `replace`. Production
and other non-development environments still require a configured signing key,
issuer, enabled auth, disabled demo tokens, rate limiting, Secure auth cookies,
and `AUTH_COOKIE_SAMESITE` set to `lax` or `strict`.

Every protected principal request decodes the presented access token and then
looks up the persisted user again. The request is rejected when that user is no
longer active, even if the JWT has not expired. Disabling a user also revokes
that user's unrevoked refresh sessions. Access tokens remain cryptographically
stateless, but a disabled user cannot use one to pass the protected-request
authorization boundary.

Cookie-authenticated `POST`, `PUT`, `PATCH`, and `DELETE` requests are subject to
CSRF checks. When supplied, browser Fetch Metadata, `Origin`, and `Referer` must
all describe the same origin; cross-site metadata fails closed even when a
double-submit token matches. In non-development environments, a request with no
browser origin metadata must send the same non-empty value in the
`focus_agent_csrf` cookie and the `X-CSRF-Token` header. A valid Bearer
credential is exempt because it does not rely on ambient cookie authority; an
invalid Bearer value cannot be used to bypass checks when auth cookies are also
present. Development/local/test/CI retain the legacy no-metadata cookie request
for compatibility.

Trajectory-backed governance list and report surfaces are owner-scoped by
default. Global trajectory reads require an active persisted admin or an active
principal granted `governance:read:global` or
`governance:trajectories:read:global`; request query parameters do not widen an
unprivileged caller's owner scope.

The normal `web_fetch` HTTPX transport resolves each initial URL and redirect
hop before connecting. Every returned address must be public; mixed
public/private answers are rejected. The request then connects to one of those
validated IP addresses while preserving the original HTTP `Host` authority and
TLS SNI name. Redirect targets repeat both domain-policy and DNS checks. This
binding prevents a second DNS lookup at connect time from turning validation
into a DNS-rebinding or private-network SSRF bypass. These controls belong to
`web_fetch`; arbitrary network-enabled sandbox programs do not automatically
inherit them.

SQLite is the default local checkpoint/store format. Legacy pickle-backed
checkpoints remain a compatibility and migration path only: they are loaded
only when the checkpoint file is owned by the current user and, by default,
when a matching `<checkpoint>.sig` HMAC-SHA256 signature generated with
`FOCUS_AGENT_CHECKPOINT_HMAC_KEY` is present. To read legacy unsigned local
checkpoints during a controlled rollback or migration, set
`FOCUS_AGENT_CHECKPOINT_VERIFY_SIGNATURE=false` temporarily, then re-enable
verification after the state has been migrated or rewritten.
