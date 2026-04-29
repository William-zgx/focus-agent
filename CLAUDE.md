
# CLAUDE.md

> Behavioral and workflow guidelines to reduce common coding mistakes, enforce quality, and anchor agent behavior.  
> Bias: cautious over fast, verifiable over speculative.

---

## 1. Design Philosophy

**Principles:**

- **Simplicity first:** only make necessary changes, avoid over-engineering.  
- **Root-cause oriented:** address the underlying cause, not superficial fixes.  
- **Minimal impact:** restrict changes to the relevant parts; do not break existing functionality.

---

## 2. Workflow

**Plan → Execute → Verify → Learn**

| Step | Description |
|------|-------------|
| **Plan** | Clarify goals, constraints, and assumptions. Break tasks into verifiable steps. Ask if uncertain. |
| **Execute** | Follow the 'minimal change' principle. Implement step by step. Maintain style, dependencies, and architecture. |
| **Verify** | Each change must have clear verification. Prefer automated tests; otherwise, provide temporary checks. |
| **Learn** | Record lessons, edge cases, and potential pitfalls. Update processes to reduce repeated mistakes. |

---

## 3. Delegation Strategy

- Delegate tasks whenever possible.  
- Run independent tasks concurrently.  
- Synchronize at critical steps to ensure consistent state and data.

---

## 4. Code Quality Standards

- **Minimal code:** implement only what is required.  
- **Consistency:** follow existing style and conventions.  
- **Verifiable:** every feature must have testable output or checks.  
- **Maintainable:** comment only where necessary; avoid redundant abstraction.  
- **Surgical changes:** modify only relevant code; clean up your own temporary artifacts; do not touch unrelated legacy code.

---

## 5. Git Guidelines

- Restrict read/write permissions to prevent accidental main branch changes.  
- Small, focused commits with messages directly tied to the change.  
- Do not combine unrelated changes in one commit.  
- Use task-level branches; merge only after verification.

---

## 6. Output Format Rules

- **Clear and structured:** code, logs, and documentation should be readable and reusable.  
- **Verifiable:** outputs must be automatically or manually checkable.  
- **Minimal necessary information:** avoid duplication or redundancy.  
- **Annotate dependencies and assumptions:** specify environment, inputs, and preconditions.

---

## 7. Example Execution

**Task:** Fix boundary error in function X  

| Step | Verify |
|------|--------|
| Write tests covering boundary values | Tests fail initially |
| Fix function X | Tests pass |
| Clean up temporary variables introduced | No residual artifacts |
| Commit code | Commit message clearly describes the change |