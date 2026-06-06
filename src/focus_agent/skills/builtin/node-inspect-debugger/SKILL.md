---
name: node-inspect-debugger
description: Debug Node.js with --inspect, node inspect, and Chrome DevTools Protocol when console output is not enough.
triggers: node-inspect-debugger:, debug-node:, node-inspect:, cdp-debug:
when_to_use: A Node or TypeScript test fails without enough intermediate state, Need to inspect closure or local scope at a breakpoint, A running Node process needs attach-style debugging, Need a heap snapshot or CPU profile
recommended_tools: search_code, read_file, apply_patch, run_workspace_command, git_status, git_diff
capability_requirements: Node debugging, inspector protocol, breakpoint management, test reproduction
prompt_mode: execute
---
# Node Inspect Debugger

Use this when `console.log` would require too much patching or cannot reach the state you need. Prefer the built-in `node inspect` REPL first; use CDP automation only for repeated breakpointing or profiling.

## Start or Attach

Start paused:

```bash
node --inspect-brk path/to/app.js
node --inspect-brk --enable-source-maps path/to/app.js
```

Attach:

```bash
node inspect -p <pid>
```

Enable inspector on an already-running process:

```bash
kill -SIGUSR1 <pid>
node inspect -p <pid>
```

Use an explicit localhost port when several processes are inspectable:

```bash
node --inspect-brk=127.0.0.1:9230 path/to/app.js
node inspect 127.0.0.1:9230
```

## REPL Commands

- stepping: `c`, `n`, `s`, `o`, `pause`
- breakpoints: `sb('file.js', 42)`, `sb(42)`, `sb('functionName')`, `cb('file.js', 42)`
- inspection: `bt`, `list(5)`, `watch('expr')`, `exec expr`
- scoped REPL: `repl`
- lifecycle: `restart`, `kill`, `.exit`

Inside `repl`, inspect locals, closure variables, `this`, promises, and module state. Press `Ctrl+C` to return to `debug>`.

## TypeScript and Tests

Pass inspect flags to Node and let the project loader handle the source:

```bash
node --inspect-brk --import tsx path/to/app.ts
node --inspect-brk -r ts-node/register path/to/app.ts
```

Run one test target at a time:

```bash
node --inspect-brk ./node_modules/vitest/vitest.mjs run --no-file-parallelism path/to/test.ts
node --inspect-brk ./node_modules/.bin/jest --runInBand path/to/test.ts
```

Disable worker pools for interactive sessions so breakpoints land in the expected process.

## CDP and Profiling

Use Chrome DevTools Protocol for scripted breakpoint setup, CPU profiles, or heap snapshots. Install the project-approved CDP client, start the target with `--inspect-brk`, connect to the inspector port, collect the specific evidence, then remove any temporary profiling code or artifacts.

## Pitfalls

- `--inspect` starts the inspector but does not pause; use `--inspect-brk` when early code matters.
- Default port `9229` collides easily.
- Source maps may not match CLI breakpoints; verify the paused source before trusting line numbers.
- Parent inspect flags do not automatically debug child processes unless passed through.
- Binding to `0.0.0.0` exposes code execution. Prefer `127.0.0.1`.
- If you quit while paused, the target may stay paused. Continue or kill it deliberately.

## Verification

- `/json/list` shows the expected target.
- First breakpoint hits in the expected source.
- `exec process.pid` matches the process you intended to debug.
- The final fix is verified by the focused failing command, then by the relevant broader check.
