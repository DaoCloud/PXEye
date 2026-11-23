# Archived documents

**English** · [简体中文](README.zh-CN.md) · [Documentation](../README.md)

Documents that have been superseded and are no longer maintained. An archived document is kept as it was when archived, with two changes only: an archive note at the top, and relative links updated to the new location. These are not the current design; do not build new features from them.

## Rules

- One directory per archived batch, keeping the original relative structure inside it.
- Archived documents are not updated. To reuse something that still holds, write it into a current document instead of editing the archive.
- Archives are not deleted. The history is also in Git.

## rack-operations-v1 (archived 2026-11-23)

The first design of the rack operations line: eight pages under “设备管理” (servers, switches, power shelves, alerts, cabling, discovery diagnostics, racks, operation records). It is superseded by the design for GB200 / GB300 whole racks; see the current [design documents](../design/README.md).

Why it was archived: the new design changes the menu, the page breakdown and the way operations work, so the page ownership and rules in these documents no longer apply.

What is still useful:

- The application code on this branch still has the first-version pages. Until the new design is implemented, these documents still describe what the existing code does.
- The Core interfaces and fields marked “verified” in the data contract are facts read on a real site. They do not depend on the page design and remain a reference when implementing the new pages.
- The field survey tools (`tools/site-survey.sh`, `tools/core-survey.py`, `tools/core-capture.py`, `tools/core-replay.py`) are still in the repository; the capture and replay method has not changed.

| Document | English | 简体中文 | Content |
| --- | --- | --- | --- |
| Rack operations: capability requirements | [Read](rack-operations-v1/design/rack-operations-requirements.md) | [阅读](rack-operations-v1/design/rack-operations-requirements.zh-CN.md) | Target capabilities and per-area implementation status |
| Rack operations: scope and status | [Read](rack-operations-v1/design/rack-operations.md) | [阅读](rack-operations-v1/design/rack-operations.zh-CN.md) | Scope, rules and stages of the eight read-only pages |
| Rack operations: rules for operations | [Read](rack-operations-v1/design/rack-operations-actions.md) | [阅读](rack-operations-v1/design/rack-operations-actions.zh-CN.md) | Operation catalogue, operations that need RMS, preview and audit rules |
| Rack operations: NICo data contract | [Read](rack-operations-v1/design/rack-operations-data-contract.md) | [阅读](rack-operations-v1/design/rack-operations-data-contract.zh-CN.md) | Core interfaces and fields used by each page, with verification marks |
| Interaction rules | [Read](rack-operations-v1/design/interaction-rules.md) | [阅读](rack-operations-v1/design/interaction-rules.zh-CN.md) | Rules for page ownership, wording, states and dangerous operations |
| Code structure review | [Read](rack-operations-v1/design/code-structure-review.md) | [阅读](rack-operations-v1/design/code-structure-review.zh-CN.md) | Historical static findings and completed adjustments |
| Documentation references | [Read](rack-operations-v1/design/documentation-references.md) | [阅读](rack-operations-v1/design/documentation-references.zh-CN.md) | Projects the documentation structure was modelled on |
| Field survey guide (with seven page documents) | [Read](rack-operations-v1/field-survey/README.md) | [阅读](rack-operations-v1/field-survey/README.zh-CN.md) | Commands and interfaces to run at a site for each page, and how to check them |
