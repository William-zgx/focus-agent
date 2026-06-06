---
name: rest-graphql-debug
description: Debug REST and GraphQL APIs by isolating connectivity, TLS, auth, request shape, response parsing, and semantics.
triggers: rest-graphql-debug:, api-debug:, rest-debug:, graphql-debug:
when_to_use: An API returns an unexpected status or body, Authentication or authorization fails, A request works manually but fails in code, GraphQL returns errors behind HTTP 200, Pagination rate limits or webhooks need diagnosis
recommended_tools: search_code, read_file, run_workspace_command, apply_patch, web_search, web_fetch, git_status, git_diff
capability_requirements: HTTP debugging, API contract analysis, auth troubleshooting, regression testing
prompt_mode: execute
---
# REST and GraphQL Debugging

Isolate the failing layer before changing code. A 200 can carry bad data; a 500 can be caused by one malformed field.

## Layer Order

1. Connectivity: can the host be reached?
2. Timeout shape: connect-slow or read-slow?
3. TLS: valid certificate and trusted chain?
4. Auth: credential present, correct, unexpired, and scoped?
5. Request format: method, headers, body, query params, content type.
6. Response parsing: content type and body shape match client assumptions.
7. Semantics: parsed data means what the code assumes.

## Quick Repro

REST:

```bash
curl -v https://api.example.com/users/1
curl -sI https://api.example.com/health
curl -X POST https://api.example.com/users \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"name":"test","email":"test@example.com"}'
```

GraphQL:

```bash
curl -X POST https://api.example.com/graphql \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"query":"{ user(id: 1) { name email } }"}'
```

GraphQL often returns HTTP 200 with an `errors` field. Always inspect both `data` and `errors`.

Python repro:

```python
resp = requests.get(url, headers=headers, timeout=(3.05, 30))
print(resp.status_code, dict(resp.headers))
print(resp.text[:500])
```

## Checks

- Connectivity and timing: use DNS lookup plus curl timing fields to separate DNS, connect, TLS, and server latency.
- TLS: inspect certificate dates, issuer, subject, and hostname match. Use insecure TLS only for ad-hoc diagnosis.
- Auth: verify header presence, scheme, expiry, environment, scopes, allowlists, and clock skew.
- Request shape: compare method, URL, headers, query params, and body byte-for-byte with a known-good request.
- Response parsing: check `Content-Type` before `.json()`, and handle HTML, empty bodies, charset issues, and schema drift.
- Semantics: confirm IDs, statuses, timestamps, pagination, and domain meanings match client assumptions.

## Status Playbook

- `401`: missing, malformed, expired, or wrong-scheme credentials.
- `403`: authenticated but not allowed; check scopes, owner, allowlist, or browser CORS.
- `404`: wrong URL, missing resource, wrong version, or wrong environment.
- `409`: duplicate create, stale `ETag`, or concurrent modification.
- `422`: valid request envelope with invalid fields; read the error body.
- `429`: respect `Retry-After` and rate-limit headers; use backoff with jitter.
- `5xx`: capture request ID, timestamp, endpoint, payload shape, and retry behavior before escalating.

## Security

- Never log full tokens, cookies, or API keys.
- Read credentials from environment variables or an approved secret store.
- Redact auth headers in repro output.
- Check for credentials in URLs, PII in errors, production stack traces, internal hostnames, and tokens echoed in bodies.

## Regression Test Shape

Add the smallest test that proves the contract:

```python
def test_get_user_contract(api_client):
    resp = api_client.get("/users/1")
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        body = resp.json()
        assert isinstance(body["id"], int)
        assert isinstance(body["email"], str)
```

## Report Format

```text
Finding: POST /api/v1/users returns 422
Request ID: req_abc123
Expected: 201 with created user
Actual: missing required field email
Root cause: client sends name only
Fix: include email in the JSON payload and cover it with a regression test
```
