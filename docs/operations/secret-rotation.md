# Secret Rotation

Focus Agent now has a `SecretProvider` abstraction with `env` as the default provider and stubs for Vault and AWS Secrets Manager.

## Environment Provider

1. Set `FOCUS_AGENT_SECRET_PROVIDER=env`.
2. Rotate provider keys by writing the new environment value in the deployment platform.
3. Restart or drain the API process so new SDK clients pick up the value.
4. Verify `/readyz` and a provider smoke request before removing the old key.

## JWT Secret

Use a dual-secret rollout when production supports it:

1. Add the new signing secret as the active signer.
2. Keep the old secret accepted for verification until all old tokens expire.
3. Remove the old verifier after the token TTL window.

## Database Password

Use blue/green credentials:

1. Create the new DB role or password.
2. Deploy with the new `DATABASE_URI`.
3. Verify migrations and readiness.
4. Revoke the old credential after all old pods drain.
