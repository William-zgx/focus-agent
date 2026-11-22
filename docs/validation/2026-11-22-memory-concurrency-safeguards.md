# Memory Concurrency Safeguards Validation — 2026-11-22

## Scope

This slice follows the abandoned keyless fallback experiment. That fallback was
not shipped: a bounded text-overlap candidate list cannot prove identity or
ambiguity across the complete record set.

The implemented scope is limited to revision-aware mutation, tombstone-safe
embedding completion, retrieval cleanup, and API forget wiring.

## Implemented safeguards

- `update_record_if_current` uses the canonical `updated_at` column as its
  compare-and-swap token. `STALE`, `PROTECTED`, and `MISSING` are distinct.
- MemoryService retries stale merges up to three times with a fresh read. A
  stale-then-forgotten retry cannot create a replacement UUID and resurrect the
  old content. A first-write `UniqueViolation` is retried as a merge.
- Synchronous and queued embedding updates use field-scoped status updates with
  an expected-fingerprint guard. Legacy NULL fingerprints remain embeddable and
  retrievable: retrieval compares against the same derived fingerprint used when
  the document was written, so legacy rows are not accidentally filtered out.
- The parent-row `FOR SHARE` guard prevents late vector insertion after forget.
  Payload aliases preserve that fingerprint guard.
- Embedding retrieval documents are published only after the guarded database
  write. Zvec hits are accepted only when the document fingerprint matches the
  current canonical record, preventing an older completion from ranking as the
  current revision.
- Protected cleanup covers both the relational vector and retrieval document.
  Cleanup failures propagate to the durable worker for retry instead of being
  silently acknowledged. Stale results also raise for a fresh read/retry.
- Legacy repository call shapes have bounded compatibility fallbacks; the
  production Postgres methods are asserted directly. Status-only bookkeeping no
  longer advances the semantic `updated_at` CAS token.
- `POST /v1/memory/{memory_id}/forget` now passes the runtime retrieval index,
  so API forget removes the index document as well as the canonical content.

## Local evidence

- Full Python suite: **2554 passed, 15 skipped**.
- Architecture, compatibility, and API/SDK contract gates: passed.
- Strict Ruff and `git diff --check`: passed.
- Concurrency-specific tests cover stale retry, stale-then-forget identity,
  unique-violation retry, protected cleanup, stale/protected distinction, NULL
  fingerprints, payload aliases, and API retrieval deletion.

## Real-Postgres gate

`tests/test_postgres_memory_mutation_real.py` uses isolated schemas and covers:

- `APPLIED` / `STALE` / `PROTECTED` mutation outcomes;
- stale vector rejection without replacing the current vector, including the
  payload-based alias;
- NULL-fingerprint embedding and ready status;
- forget during synchronous embedding, with no surviving vector or retrieval
  document and a direct protected-upsert error;
- libpq-compatible `options` encoding for isolated schemas.

The local machine has no usable PostgreSQL binaries and denies Docker socket
access, so these four tests are skipped locally. Browser Smoke uses the pinned
`pgvector/pgvector:0.8.0-pg16-bookworm` service and sets
`FOCUS_AGENT_REQUIRE_REAL_POSTGRES=1`, which turns a missing URI into a failure
rather than a skip. The application itself still runs with embeddings disabled.

Real-Postgres evidence is therefore a **remote required gate**, not a local
success claim.

## Explicit non-goals and remaining work

- No generic keyless identity resolver is claimed. A correct resolver needs a
  stable identity contract, not a small text-overlap sample.
- Concurrent first writes with different content under one semantic key still
  need a dedicated uniqueness/transaction design. The new merge CAS does not
  create that constraint.
- Legacy/custom repository fallbacks preserve compatibility; revision safety is
  guaranteed by the production Postgres implementation, not asserted for every
  third-party adapter.
- Retrieval documents written by older versions without a fingerprint are
  legacy data and require separate migration evaluation.
- No human recovery-pilot work is included. The existing pilot protocol remains
  unapproved and unexecuted.
