# Grading-defect review of `tasks.jsonl`

Adversarial review of the 8 debugging tasks. Each task's grading fields
(`must_include`, `must_not_include`) were checked against a hand-written,
realistic CORRECT final answer and a hand-written WRONG answer that uses the
rejected material (see `check_answers.py`). Two false-fail defects were found
and fixed; everything else was verified clean.

## Changes made

### 1. `dbg-zh-03` — `mc-date` (11月5日前上线): missing 「号」 variant
- **Defect:** false fail. A correct Chinese answer that phrases the deadline as
  「11 月 5 号前上线」 (very common colloquial form) matched none of the
  existing alternatives (`11月5日`, `11.5`), so a correct answer would fail this
  `must_include` item. The sibling task `dbg-zh-02` already carries the `日`/`号`/`.`
  triple; this task was missing `号`.
- **Fix:** added the alternative `"11\\s*月\\s*5\\s*号"`.

### 2. `dbg-zh-02` — `mc-p99` (P99 不超过 250ms): missing 「毫秒」 variant
- **Defect:** false fail. A correct Chinese answer that renders the unit as
  「250 毫秒」 instead of 「250ms」 (e.g. 「P99 不超过 250 毫秒」) matched neither
  `P99.{0,8}250\s*ms` nor `250\s*ms.{0,8}P99`. `dbg-zh-01`'s `mc-p99` already
  has a `毫秒` alternative; this one did not.
- **Fix:** added the alternative `"P99.{0,8}250\\s*毫秒"`.

## Verified clean (no change needed)

- **False contamination (all 8 `must_not_include` items):** every
  `must_not_include` regex is a specific rejected value/code (e.g. `3000ms`,
  `LK-3300`, `40%`, `60MB`, `7 days`, `8192`, …). None is a common word and none
  overlaps with a kept fact or a required `must_include` value, so a correct
  final answer that drops the rejected hypotheses is never flagged. (A correct
  answer has no reason to restate the rejected values, so narrowing was
  unnecessary.)
- **False pass (all `must_include` items):** the specific error codes
  (`NX-4471`, `SLT-9021`, `FPR-1009`, `AGV-DLK-55`, `BP-SEAT-77`, `TLMT-3310`,
  `PRC-8830`, `MMX-CRASH-19`) and identifier/formula details anchor every
  `must_include`, so a wrong answer using the rejected material still fails at
  least one `must_include` (and also trips a `must_not_include`).
- **False fail (remaining `must_include` items):** date formats carry
  `日`/`号`/`.` alternatives where relevant; English dates carry `Nov 8`/
  `November 8`/`Grand Finals`; percentages and P99/P95 latencies accept the
  natural renderings used in the turns.
- **Detours settle the decision:** every task's user messages explicitly reject
  the relaxed value (e.g. 「锁超时改回 500ms 了」, "Timeout is back to 40ms",
  "Buffer is back to 5MB") and the misread code, and settle the root cause/fix
  ("定了，就用这个方案" / "Decision: we go with this").
- **No world-knowledge answers:** all error codes, modules, and fixes are
  fictional and only exist in the conversation.
- **Forbidden words:** none of `分支 支线 branch fork 分叉 merge 合并` appears in
  any user message.
- **Counts preserved:** every task still has 5 `main_constraint` items, 3–4
  `detour_detail` items, and 2 `must_not_include` items (only regex alternatives
  were added, no items added/removed).

## Verification

`check_answers.py` (run with `python3 -I check_answers.py`) asserts, for all 8
tasks: every regex compiles; every hand-written correct answer matches all
`must_include` and no `must_not_include`; every hand-written wrong answer is
caught; and no forbidden word appears in user messages. It prints a per-task
summary and exits non-zero on any failure. Result: **All checks passed.**
