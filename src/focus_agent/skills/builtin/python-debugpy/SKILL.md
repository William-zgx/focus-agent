---
name: python-debugpy
description: Debug Python code with pdb, breakpoint(), debugpy, or remote-pdb when logs and tracebacks are not enough.
triggers: python-debugpy:, debug-python:, pdb:, debugpy:
when_to_use: Python tests fail without enough local state, Need to step through a function or inspect locals, A long-running Python process needs attach-style debugging, Post-mortem inspection would clarify an exception
recommended_tools: search_code, read_file, apply_patch, run_workspace_command, git_status, git_diff
capability_requirements: Python debugging, breakpoint management, test reproduction, process inspection
prompt_mode: execute
---
# Python Debugging

Use this after you have the smallest reproducible command or code path. Start with the least invasive debugger that exposes the missing state.

## Tool Choice

- `breakpoint()` + pdb: local source edit is safe and fastest.
- `python -m pdb`: launch without source edits.
- `pytest --pdb`: inspect locals at a failing test frame.
- `debugpy`: attach a DAP client to a long-running or threaded process.
- `remote-pdb`: get a terminal-friendly pdb prompt in a headless process.

## pdb Essentials

- stepping: `n`, `s`, `r`, `c`
- stack: `w`, `u`, `d`
- source: `l`, `ll`
- values: `p expr`, `pp expr`, `display expr`
- breakpoints: `b file:line`, `b func`, `cl N`
- mutate or explore: `!stmt`, `interact`
- quit: `q`

## Recipes

Temporary local breakpoint:

```python
result = compute(value)
breakpoint()
return result
```

Launch under pdb:

```bash
python -m pdb path/to/app.py arg1 arg2
```

Debug a focused pytest case:

```bash
python -m pytest tests/path/to/test_file.py::test_name --pdb -p no:xdist
python -m pytest tests/path/to/test_file.py --showlocals --tb=long
```

Post-mortem:

```python
import pdb
import sys

try:
    run_the_thing()
except Exception:
    pdb.post_mortem(sys.exc_info()[2])
```

debugpy attach:

```python
import debugpy

debugpy.listen(("127.0.0.1", 5678))
debugpy.wait_for_client()
debugpy.breakpoint()
```

```bash
python -m debugpy --listen 127.0.0.1:5678 --wait-for-client path/to/app.py
python -m debugpy --listen 127.0.0.1:5678 --pid <pid>
```

remote-pdb:

```python
from remote_pdb import set_trace

set_trace(host="127.0.0.1", port=4444)
```

```bash
nc 127.0.0.1 4444
```

## Pitfalls

- Disable parallel test workers for interactive pdb sessions.
- `PYTHONBREAKPOINT=0` disables `breakpoint()`.
- `breakpoint()` in CI or non-TTY contexts can hang.
- `debugpy.listen()` does not wait unless paired with `wait_for_client()`.
- pdb does not automatically follow forks or multiprocessing children.

## Verification

- First breakpoint hits in the expected frame.
- `w` shows the intended call path.
- The focused failing command passes after the fix.
- No debugger hooks remain:

```bash
rg -n 'breakpoint\(\)|set_trace\(|debugpy\.listen|remote_pdb' --type py
```
