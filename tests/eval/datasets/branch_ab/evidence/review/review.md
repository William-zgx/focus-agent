# Grading-defect review of `tasks.jsonl`

I reviewed all 8 tasks for the six defect classes and fixed the ones I could
reliably reproduce. `tasks.orig.jsonl` is left untouched; all edits are in
`tasks.jsonl`. Every fix keeps the task id, category, language, and item counts
(5 main_constraint + 2 detour_detail + 3 must_not_include per task).

Verification is in `check_answers.py`: for every task it holds one hand-written
CORRECT final answer and one hand-written WRONG answer that adopts the rejected
material, then asserts the correct answer matches every `must_include` and no
`must_not_include`, and the wrong answer matches a `must_not_include` or fails a
`must_include`. It also asserts every regex compiles and no forbidden word
(分支 / 支线 / branch / fork / 分叉 / merge / 合并) appears in any user message.
Final run: **all 8 tasks pass**.

## Changes

### False pass (too-broad `must_include` that a wrong answer could satisfy)

1. **rev-zh-03 `dd-2`** — `["trace_id", "强校验"]` → `["强校验"]`.
   `trace_id` is already a main-line requirement (main_turn 3), so an answer that
   kept `trace_id` but never adopted the detour's "改为强校验" decision would
   falsely satisfy this detour gate. Requiring the detour-specific term `强校验`
   makes the item actually test fidelity to the side investigation.

2. **rev-zh-02 `mc-3`** — `["手工旁路", "旁路"]` → `["手工旁路", "手动旁路"]`.
   The bare word `旁路` ("bypass") also matches a wrong answer such as
   "取消旁路 / 拆除旁路", so it could not distinguish "keep the manual bypass"
   from its opposite. The compound terms `手工旁路` / `手动旁路` identify the
   retained requirement.

3. **rev-en-02 `mc-3`** — `["10%", "10\s*percent"]` → `["10\s*%\s*(of\s+)?traffic", "10\s*percent\s*(of\s+)?traffic"]`.
   Bare `10%` would match an *unrelated* 10% (e.g. a wrong answer talking about
   10% cost savings), passing the item without ever stating the shadow-rollout
   traffic split. Anchoring the percentage to `traffic` makes the gate specific.

### False fail (a correct phrasing the regex would miss)

4. **rev-zh-04 `mc-2`** — added `"1\\.2\\s*万"` to `["12000", "12,?000"]`.
   A Chinese reviewer may render 12000 as `1.2 万`; the original only accepted the
   raw/千分位 digits. (Mirrors the 万/0000 pairing already present in rev-zh-01/02.)

5. **rev-en-01 `mc-3`** — added `"24\\s*h\\b"` for the `24h` shorthand.

6. **rev-en-01 `dd-2`** — `["strict\s*mode"]` → `["strict\s*-?\s*mode"]`
   for the hyphenated `strict-mode`.

7. **rev-en-02 `mc-2`** — `["6\s*hours?", "6\s*hrs?"]` → hyphen-tolerant
   `["6\s*-?\s*hours?", "6\s*-?\s*hrs?"]` so the natural compound
   "6-hour refresh" matches.

8. **rev-en-04 `mc-1` / `mc-2` / `mc-3` / `dd-1`** — added `-?` so the natural
   hyphenated compounds match: `30-minute`, `180-day`, `15-minute`, `90-day`.
   (The original `\s*` patterns only matched the space-separated forms, e.g.
   "30 minutes", and would fail a correct "30-minute unsubscribe processing".)

### False contamination in the other direction (`must_not_include` missing the rejected phrasing)

9. **rev-en-02 `mn-1`** — `"12\s*hours?"` → `"12\s*-?\s*hours?"` so a wrong
   answer phrased as "12-hour feature refresh" is still flagged.

10. **rev-en-04 `mn-1`** — `["365\s*days?", "4\s*hours?"]` → hyphen-tolerant
    `["365\s*-?\s*days?", "4\s*-?\s*hours?"]` so "365-day window" / "4-hour
    batches" are still caught.

## Checked and left as-is

- **No numeric substring collisions** between a `must_not_include` figure and a
  kept fact (e.g. no rejected "180" inside a kept "1800", no rejected number
  appearing in a `must_include` value). Each rejection figure (`30 秒`, `8 小时`,
  `8 万`/`30 万`, `16 小时`, `900 rps`/`1500 ms`, `8 GB`/`12 hours`,
  `2.6 m/s`/`500 ms`, `365 days`/`4 hours`) is disjoint from the kept numbers.
- **Rejected names/codes** (`DriftGuard`, `Overpress-X`, `TurboPay`,
  `ShiftOptix`, `SwiftMesh`, `QuikScore-Lite`, `NavBoost-X`, `ReSpark`, and the
  error codes) are all distinctive tokens, not common words a correct answer
  would use.
- **Every detour is clearly settled** in the user's own words ("定了，…",
  "Decision: …"), and each rejected option is explicitly rejected by the user,
  so no detour- or rejection-role edits were needed.
- **No world-knowledge answerability**: all facts (products, thresholds, codes)
  exist only in the conversation.
- All detour_detail items correspond to decisions the return turn should carry
  forward, so none were demoted to the rubric.
