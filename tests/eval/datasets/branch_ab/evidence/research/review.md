# Review of tasks.jsonl — grading-defect fixes

I reviewed all 8 tasks adversarially (false contamination, false pass, false fail,
detour settlement, world-knowledge answerability, forbidden words) and fixed 4 kinds
of defects. Everything else was verified clean and left untouched. Verification is in
`check_answers.py`, which holds one realistic CORRECT final answer and one WRONG
(contaminated) answer per task and asserts the grading rules behave correctly.

## Changes

### 1. `res-zh-03` — `mc-commercial` (false fail)
- **Before:** `["可商用", "商用授权", "授权.{0,4}商用"]`
- **After:** `["可商用", "可以商用", "商用授权", "授权.{0,6}商用"]`
- **Why:** the main-turn phrasing "授权要完整、可以商用" is the most likely thing a
  correct answer quotes. `可商用` requires 可/商 to be adjacent, so it misses
  "可以商用"; and `授权.{0,4}商用` only allows ≤4 chars between 授权 and 商用, while
  "授权完整、可以商用" has 5 ("完整、可以"). A correct answer re-stating the constraint
  verbatim would have failed this item.

### 2. `res-en-03` — `mc-pci-l1` (false pass)
- **Before:** `["PCI\\s*DSS\\s*Level\\s*1", "PCI\\s*DSS"]`
- **After:** `["PCI[-\\s]*DSS\\s*Level\\s*1", "Level\\s*1\\s*PCI"]`
- **Why:** the loose `PCI\s*DSS` alternative matched *any* PCI DSS mention, including
  the rejected "PCI DSS Level 2" (PayVane), so a wrong answer that carried over the
  rejected certification level would still pass this main-constraint item. It also
  wouldn't match the common hyphenated "PCI-DSS". The item now requires Level 1
  (the actual constraint) while tolerating hyphenation and word order
  ("Level 1 PCI DSS").

### 3. English tasks — missing `k` thousands forms (false fail)
Correct answers can legitimately write compact thousands ("132k events/sec",
"$20.4k/month"), which the original `,000`-only regexes missed; the same gap let
contaminated answers slip past `must_not_include`. Added `k` alternatives:

- `res-en-01`: `mc-eps-120k` +`120\s*k`; `dd-eps-132k` +`132\s*k`; `mni-eps-180k` +`180\s*k`
- `res-en-02`: `mc-clauses-500k` +`500\s*k`; `mc-budget-140k` +`140\s*k`;
  `dd-price-132k` +`132\s*k`; `dd-volume-560k` +`560\s*k`;
  `mni-price-89k` +`89\s*k`; `mni-scraped-8400` +`8\.4\s*k`
- `res-en-04`: `mc-budget-22k` +`22\s*k`; `dd-price-20400` +`20\.4\s*k`;
  `mni-price-14500` +`14\.5\s*k`

### 4. `res-zh-01` — `mc-domestic` (false fail)
- **Before:** `["境内", "不出海"]`
- **After:** `["境内", "不出海", "不出境"]`
- **Why:** "数据不出境" is the standard Chinese way to state the data-residency
  constraint; a correct answer that normalizes "不能出海" to "不出境" without also
  writing "境内" would have missed. Added the variant (no false-pass risk: it is
  specific to the residency constraint).

## Checked and found clean (no change)

- **False contamination by number collision:** every `must_not_include` number was
  compared against all kept facts (constraint + chosen numbers, in both `,000`/`万`
  and now `k` forms). No rejected number is a substring of a kept number (e.g. the
  "180 inside 1800" case does not occur), and none uses a common word or a vendor name.
- **Detour settlement:** in every task the user settles the decision in their own
  words ("定了，就用…" / "Decision: …") and explicitly rejects the tempting option
  ("基本不能碰了" / "…is out"), so the rejected material is genuinely rejected.
- **World knowledge:** all graded facts (vendor names, prices, metrics, ticket IDs)
  are conversation-specific; none are answerable without the dialogue.
- **Forbidden words:** no user message (main_turns, detour_turns, return_turn)
  contains 分支 / 支线 / branch / fork / 分叉 / merge / 合并 (asserted in the script).

## Verification

`check_answers.py` (run with `python3 -I check_answers.py`) confirms, for all 8 tasks:

- every regex compiles under `re.IGNORECASE`;
- no forbidden word appears in any user message;
- each hand-written CORRECT answer matches **all** `must_include` and **no**
  `must_not_include`;
- each hand-written WRONG answer matches ≥1 `must_not_include` (contaminated).

Result: `ALL 8 TASKS PASS.`
