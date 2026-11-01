# Review of tasks.jsonl — grading-defect fixes

All 8 tasks were reviewed against the six defect classes. Seven regex-level
defects were found and fixed across 4 tasks; the other 4 tasks were checked and
left unchanged. No `main_turns`/`detour_turns`/`return_turn` text, rubric, id,
category, language, or item counts were modified.

## Changes

### wri-zh-02 (internal maintenance email)

1. **`must_not_include.four_hour`** — `4\s*小?时` → `(?<!\d)4\s*小时`
   - **Defect 1 (false contamination).** The optional `小` meant the pattern
     also matched a bare `4时`, which appears inside a correct time like
     `14时00分`. A correct answer rendering the window in 时/分 notation would
     have been flagged as contaminated. Requiring `小时` keeps the rejected
     "4 小时" window while no longer matching clock times; the digit lookbehind
     also prevents matching `24小时` (e.g. "24 小时支持").

2. **`must_include.window`** — added `14\s*时\s*00\s*分\s*[-–—~至到]\s*17\s*时\s*00\s*分`
3. **`must_include.restore`** — added `17\s*时\s*30\s*分`
   - **Defect 3 (false fail).** The original colon-only regexes would have
     missed a correct answer that writes the window as `14时00分 至 17时00分`
     and `17时30分前恢复`. The colon forms are retained as alternatives.

### wri-zh-03 (job posting)

4. **`must_include.salary`** — `22\s*[-–—~至到]\s*32` → `22\s*[kK]?\s*[-–—~至到]\s*32\s*[kK]?`
   - **Defect 3 (false fail).** The original only matched `22–32` with no `K`
     between `22` and the dash, so a correct answer writing `22K–32K` (K on both
     bounds) was missed. Now `22–32K` and `22K–32K` both pass.

### wri-en-02 (internal outage email)

5. **`must_not_include.four_hour`** — `4\s*[- ]?hour` → `(?<!\d)4\s*[- ]?hour`
   - **Defect 1 (false contamination).** `4-hour` is a substring of `24-hour`,
     so a correct answer mentioning "24-hour support" would have been flagged.
     The digit lookbehind narrows the match to the standalone rejected
     "4-hour" window.

### wri-en-03 (job posting)

6. **`must_include.salary`** — added `,000` and `to` alternatives:
   `\$?\s*125\s*(?:[kK]|,\s*000)?\s*(?:to|[-–—~])\s*\$?\s*165\s*(?:[kK]|,\s*000)?`
   - **Defect 3 (false fail).** The original matched only the `k` form with a
     dash, missing `$125,000 to $165,000` (the "k vs ,000" and "to" phrasings).

7. **`must_include.bonus`** — removed the bare `10\s*%` alternative; replaced
   with a bonus-anchored pattern:
   `10\s*%\s*(?:(?:annual|yearly|performance(?:[\s-]*based)?)\s*)?bonus`
   - **Defect 2 (false pass).** The bare `10\s*%` would have matched an
     unrelated "10%" in a wrong answer (e.g. "10% discount"), letting a wrong
     answer satisfy the bonus item. The item now requires `bonus` and still
     accepts "10% performance bonus", "10% annual bonus", "10% performance-based
     bonus", and "10% bonus".

8. **`must_not_include.competitive`** — `competitive` →
   `competitive\s*(?:salary|pay|compensation|remuneration|wage)` and
   `(?:salary|pay|compensation|remuneration|wage)\b[^.!?\n]{0,30}competitive`
   - **Defect 1 (false contamination).** A correct answer may legitimately say
     "competitive benefits" while still listing the real salary range; the old
     pattern would have flagged it. The new patterns only flag `competitive`
     when it describes salary/compensation (the usage legal vetoed), e.g.
     "Salary: competitive" or "competitive compensation".

## Checked and found OK (no changes)

- **wri-zh-01, wri-zh-04, wri-en-01, wri-en-04** — must_include/must_not_include
  regexes are specific, name-only rejection patterns are distinctive, and no
  number-overlap or common-word issues were found.
- **Detour settlement (defect 5)** — every task has an explicit
  "定了 / Decision" turn and the rejected options are clearly rejected
  (trademark, budget, schedule, panel test, legal) in the user's own words.
- **World knowledge (defect 6)** — all kept facts (dates, versions, names,
  salaries, venues) are fictional and only derivable from the conversation.
- **Forbidden words** — no user message contains 分支/支线/branch/fork/分叉/merge/合并.
- **Item counts** — unchanged (main_constraint 3–5, detour_detail 2–4,
  must_not_include 1–3).

## Verification

`check_answers.py` contains one hand-written correct and one hand-written wrong
answer per task and asserts: the correct answer passes every `must_include`
and no `must_not_include`; the wrong answer hits at least one `must_not_include`
(or fails a `must_include`); every regex compiles; and no forbidden word appears
in user messages. It also includes targeted regression checks for each fix above
(e.g. "14时00分" not flagged, "24-hour support" not flagged, "competitive
benefits" not flagged, "Salary: competitive" flagged). All checks pass.
