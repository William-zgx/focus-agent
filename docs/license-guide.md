# License Guide

This document records the licensing decision for the repository and preserves the reasoning that led to it.

## Current Status

The repository now includes a root-level `LICENSE` file and is released under the MIT License.

This guide is informational only and is not legal advice.

## Final Decision

The project uses `MIT`.

Why this was selected:

- it keeps adoption friction low for developers and companies
- it matches the lightweight starter-project positioning of this repository
- it keeps redistribution and integration simple for downstream users

## Recommended Decision Path

Before choosing a license for a similar project, align on these questions:

- Do you want the project to be easy for companies to adopt with minimal restrictions?
- Do you want modifications to remain open when people redistribute the code?
- Do you want network-hosted derivatives to share source changes as well?
- Do you plan to offer a commercial or dual-license model later?
- Are there third-party dependencies, assets, or examples that introduce license constraints?

## Common Choices

### MIT

Choose MIT if you want:

- maximum simplicity
- broad commercial adoption
- minimal obligations for downstream users

Tradeoff:

- downstream users can modify and redistribute the code with very few requirements

Best fit when:

- the goal is fast adoption and low friction

### Apache-2.0

Choose Apache-2.0 if you want:

- a permissive license similar to MIT
- an explicit patent grant
- better enterprise comfort in some organizations

Tradeoff:

- slightly more text and process overhead than MIT

Best fit when:

- you want permissive licensing but prefer clearer patent language

### MPL-2.0

Choose MPL-2.0 if you want:

- a middle ground between permissive and copyleft
- file-level sharing obligations for modified files

Tradeoff:

- more obligations than MIT or Apache-2.0
- less familiar than MIT for some developer audiences

Best fit when:

- you want to encourage sharing of improvements without applying strong copyleft to the whole combined work

### AGPL-3.0

Choose AGPL-3.0 if you want:

- strong copyleft
- source-sharing obligations that also apply to network-hosted use cases

Tradeoff:

- many companies will avoid adopting it
- significantly stronger obligations for downstream users

Best fit when:

- you want hosted derivatives to publish their modifications as well

## Alternative Licenses Considered

For a developer-facing agent skeleton, the most common alternatives were:

1. `MIT` for maximum simplicity
2. `Apache-2.0` if explicit patent language is important

If the goal were to keep improvements closer to the public codebase, `MPL-2.0` would be the more fitting choice.

## Release Checklist

Before making the repository public, maintainers should:

- ensure documentation consistently references that license
- verify that bundled assets and examples are compatible with the chosen license
- confirm there is no confidential or third-party internal content in docs or examples
- update contribution language in [`CONTRIBUTING.md`](../CONTRIBUTING.md) if needed

## Optional Follow-Up Files

After selecting a license, you may also want to add:

- `NOTICE` if required by the chosen license or your organization
- copyright headers if your legal process requires them
- a short "License" section in [`README.md`](../README.md)
- organization-specific CLA or DCO guidance if contributions need extra legal workflow

## Maintainer Template

Once a decision is made, the repository can be updated with a short README note such as:

```text
## License

This project is licensed under the Apache License 2.0. See the LICENSE file for details.
```

Or:

```text
## License

This project is licensed under the MIT License. See the LICENSE file for details.
```
