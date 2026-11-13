# Test Layout

Use the following directories for new tests instead of adding more root-level
`test_*.py` files:

- `unit/<domain>/`: isolated behavior tests with external services replaced by
  fakes or test doubles. Mirror the owning domain, not necessarily every source
  file.
- `integration/<domain>/`: tests that cross API, persistence, runtime, or other
  process-internal boundaries. Live external services require an explicit test
  environment.
- `frontend/`: Node-based regressions spanning the Web app and frontend SDK.
- `contracts/`: versioned API and SDK contract snapshots.
- `eval/`: evaluation suites, datasets, and framework tests.
- `fixtures/`: shared fixtures and fixture servers.

Keep reusable helpers in non-collected support modules or the nearest
`conftest.py`; do not duplicate a test in both its legacy and domain locations.
Tests that construct `ChatService` should use the non-autouse
`chat_service_factory` fixture from `tests/conftest.py` so owned background
workers are closed and shutdown failures are reported at teardown.
Root-level tests are legacy inventory and should move only with their relevant
behavior changes or a focused test-layout migration. Update explicit paths in
`Makefile`, package scripts, CI, and contributor documentation when moving a
test.
