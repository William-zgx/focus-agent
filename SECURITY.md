# Security Policy

## Supported Versions

Focus Agent is still evolving quickly, so security fixes are most likely to land on the latest development line first.

Until a formal version support policy is published, please assume:

- the latest version in the default branch is the primary supported line
- older snapshots may not receive backported security fixes

## Reporting a Vulnerability

Please do not open a public GitHub issue for suspected security vulnerabilities.

Instead, report suspected vulnerabilities privately by email:

`zgx62313@163.com`

When reporting a vulnerability, please use a descriptive subject line such as `Focus Agent security report` and include enough detail for maintainers to reproduce and assess the issue safely.

Please avoid sharing exploit details publicly until maintainers have had a reasonable opportunity to investigate and release a fix or mitigation.

When reporting a vulnerability, please include:

- a clear description of the issue
- the affected component or file paths
- steps to reproduce, if available
- impact assessment
- any proof-of-concept details needed to validate the issue
- suggested mitigations, if you have them

Examples of relevant areas in this repository include:

- authentication and token handling
- thread ownership enforcement
- streaming output that may expose unintended data
- persistence and storage boundaries
- unsafe defaults in configuration or example code
- frontend SDK parsing or trust assumptions

## Response Expectations

Maintainers should aim to:

- acknowledge receipt within 5 business days
- reproduce and assess the report
- decide whether the issue requires immediate mitigation
- prepare a fix and coordinate disclosure timing when appropriate

## Disclosure Guidance

Please avoid public disclosure until maintainers have had a reasonable opportunity to investigate and address the issue.

## Hardening Notes for Maintainers

Before public release, maintainers should review:

- default secrets and development-only auth settings
- whether demo token issuance should remain enabled by default
- local config and environment variable handling
- dependency update posture
- artifact writing paths and filesystem assumptions
- any examples that could be mistaken for production-ready security defaults
