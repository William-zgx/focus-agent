## Summary

Describe the change in a few concise bullets.

## Why This Change

Explain the problem, motivation, or context for the change.

## What Changed

- 

## Validation

List the checks you ran, for example:

- `make ci`
- `make sdk-check && make sdk-build`
- `make web-check && make web-build`
- `make ui-smoke`

If you did not run validation, explain why.

## API / Contract Impact

Call out any changes to:

- HTTP routes
- request or response schemas
- SSE event names or payloads
- branch lifecycle behavior
- auth or ownership behavior
- frontend SDK types
- trajectory observability, replay, or promotion behavior

If none, say so.

## Documentation Impact

Describe any documentation updates included in this PR, or explain why none were needed.

## Checklist

- [ ] The change is scoped and does not include unrelated edits
- [ ] Tests were added or updated when behavior changed
- [ ] Docs were updated when user-facing behavior changed
- [ ] Secrets, tokens, and private endpoints were not committed
- [ ] Breaking changes are clearly described
