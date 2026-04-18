---
name: security-review
description: Audit code, configuration, and workflows for security risks with a findings-first review standard.
triggers: security-review:, security:
when_to_use: The task touches auth or access control, Sensitive data or storage boundaries are involved, A release or major change needs security-focused review
recommended_tools: git_status, git_diff, read_file, search_code, git_log
prompt_mode: synthesize
---

# Security Review

Review the change or subsystem with a security-first lens.

## Focus Areas

- authentication and token handling
- authorization and thread ownership checks
- unsafe defaults in config or example files
- filesystem write locations and artifact boundaries
- prompt or streaming paths that may expose unintended data
- dependency and integration trust assumptions

## Workflow

1. Ground the review:
   - inspect `git_status` and `git_diff`
   - read the relevant files in full when the patch alone is not enough
2. Check for concrete security risks:
   - missing auth or ownership validation
   - secrets or sensitive defaults committed to tracked files
   - injection or unsafe command construction
   - over-broad filesystem access
   - trust assumptions between frontend, API, and model/tool layers
3. Evaluate mitigations:
   - what already protects the system
   - what is still missing
   - what should block release versus what can follow later

## Output

- findings first, ordered by severity
- exact file references when possible
- residual risk or test gaps after the findings

If no material issue is found, say so explicitly and mention the main areas you checked.
