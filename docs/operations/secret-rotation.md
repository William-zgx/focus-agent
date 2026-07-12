# Secret Rotation

Updated: 2026-07-12

Focus Agent now has a `SecretProvider` abstraction with `env` as the default provider and stubs for Vault and AWS Secrets Manager.

## Environment Provider

1. Set `FOCUS_AGENT_SECRET_PROVIDER=env`.
2. Rotate provider keys by writing the new environment value in the deployment platform.
3. Restart or drain the API process so new SDK clients pick up the value.
4. Verify `/readyz` and a provider smoke request before removing the old key.
5. Ensure logs, generated reports, shell history, and retained release artifacts
   contain no secret value before revoking the old credential.

## JWT Secret

Use the keyed dual-secret configuration for a no-downtime production rollout.
`AUTH_JWT_KEYS` may be JSON or `kid=secret` CSV, and
`AUTH_JWT_KEY_ID` selects the active signing key. Every active production JWT
secret must be at least 32 characters and must not use development, demo, or
placeholder values.

1. Add the new key to `AUTH_JWT_KEYS` while keeping the previous key active.
2. Set `AUTH_JWT_KEY_ID` to the new key id and deploy. New tokens carry the new
   `kid`; verification continues to accept active old-key tokens.
3. Verify login, refresh, and a protected request with a newly issued token.
   Also verify an old, unexpired token during the overlap window.
4. Wait for the maximum access-token lifetime and drain old pods before marking
   the old key inactive or removing it.
5. Revoke refresh sessions when the incident or rotation policy requires
   preventing further refreshes. Already issued access tokens remain valid
   until their TTL expires while their signing key and user stay active;
   disabling the user makes protected requests fail immediately.

Do not configure `AUTH_JWT_KEY_ID` to a missing or inactive key. In
non-development environments the runtime also requires authentication enabled,
demo tokens disabled, a non-empty issuer, secure cookies, and `SameSite=lax` or
`strict`; rotation must not bypass those startup guards.

## Local Pickle HMAC Key

SQLite is the default local checkpoint/store backend and does not use
`FOCUS_AGENT_CHECKPOINT_HMAC_KEY`. The key is required only when explicitly
using the legacy pickle backend with signature verification enabled.

Pickle files are signed with a single HMAC key; there is no dual-key verifier.
Rotating the key without rewriting the files makes the old checkpoint/store
unreadable and startup fails closed.

1. Stop every process that can write the local checkpoint/store files.
2. Back up the pickle files and their `.sig` files with owner and permission
   metadata intact.
3. Start an isolated process with the old key and signature verification
   enabled, then migrate the state to SQLite or otherwise rewrite it under the
   new key.
4. Verify restore and restart using the destination backend or new key.
5. Remove the old key only after the migrated/re-signed state has been checked.

Missing keys, missing or invalid signatures, owner mismatches, and corrupt
payloads must remain hard failures. Do not set
`FOCUS_AGENT_CHECKPOINT_VERIFY_SIGNATURE=false` as a normal rotation or
rollback step. If historical unsigned data must be recovered, use an approved
offline, isolated migration with no production credentials or network access,
then return to verified SQLite or signed-pickle operation.

## Database Password

Use blue/green credentials:

1. Create the new DB role or password.
2. Deploy with the new `DATABASE_URI`.
3. Verify migrations, connection-pool behavior, backup/restore checks, and
   `/readyz`.
4. Revoke the old credential after all old pods drain.

Do not use repo-local SQLite as a shared production database-password fallback.
Without `DATABASE_URI`, a raw local process now persists app state and
checkpoint/store data to local SQLite, but that state is process-host local and
does not provide shared production persistence.

## Post-Rotation Release Evidence

Treat the rotated deployment as a new evidence capture. Before running
production smoke, Postgres ops, OTel smoke, governance, or eval reporting,
export the complete identity:

```bash
export RELEASE_COMMIT_SHA="$(git rev-parse HEAD)"
export RELEASE_DEPLOYMENT_ID='<deployment-id>'
export RELEASE_DEPLOYMENT_VERSION='<deployment-version>'
export RELEASE_ENVIRONMENT='production'
```

The four values are required together. Report writers attach them as the
top-level `release_binding` and fail before writing a non-dry-run report when
the identity is partial. Every production evidence JSON also needs a
timezone-aware timestamp; the default freshness and collection-window limit is
21,600 seconds (6 hours).

Confirm `/readyz` reports the same deployment id in `deployment`, version in
`app_version`, and environment in `environment`. Build a new schema-v2 release
evidence manifest and verify `release_binding.status=passed` and
`evidence_validation.passed=true`. Never place the rotated secret itself in
release bindings, command arguments retained in reports, or uploaded
artifacts.
