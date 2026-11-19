# Design documents

**English** · [简体中文](README.zh-CN.md) · [Documentation](../README.md)

Documents that explain why something is built the way it is and where it stops: product scope, system design, interaction rules, and the data contracts between pages and NICo. For how to use a page, see the [page guides](../user-guide/README.md); for deployment and builds, see the [documentation index](../README.md).

## Documents

| Document | English | 简体中文 | Question it answers |
| --- | --- | --- | --- |
| Features and boundaries | [Read](features.md) | [阅读](features.zh-CN.md) | What each feature maps to in NICo and how far it is supported |
| Architecture | [Read](architecture.md) | [阅读](architecture.zh-CN.md) | Runtime, module responsibilities, which system owns which data |
| Interaction rules | [Read](interaction-rules.md) | [阅读](interaction-rules.zh-CN.md) | How pages, wording, states and dangerous operations are designed |
| Rack operations: capability requirements | [Read](rack-operations-requirements.md) | [阅读](rack-operations-requirements.zh-CN.md) | The whole of the target capabilities: scope, lifecycle, ten functional areas |
| Rack operations: scope and status | [Read](rack-operations.md) | [阅读](rack-operations.zh-CN.md) | What the rack line of work does, does not do, and has reached |
| Rack operations: NICo data contract | [Read](rack-operations-data-contract.md) | [阅读](rack-operations-data-contract.zh-CN.md) | Which Core interface and field each page uses, and which were verified on a real site |
| Code structure review | [Read](code-structure-review.md) | [阅读](code-structure-review.zh-CN.md) | Historical static findings and the refactor delivered |
| Documentation references | [Read](documentation-references.md) | [阅读](documentation-references.zh-CN.md) | Which projects informed the documentation structure |

## Where each kind of content lives

| Content | Location | Notes |
| --- | --- | --- |
| Design documents | `docs/design/` | This directory. One document per topic, stating the current conclusion rather than a dated log |
| Interaction rules | `docs/design/interaction-rules*.md` | The single set of interface and wording rules |
| Page guides | `docs/user-guide/` | One per menu page, named after the menu entry |
| Deployment, builds, field procedures | `docs/` root | Step-by-step operational documents |
| Rules for AI collaborators | `AGENTS.md` in each directory | The root file covers repository workflow; `src/pxeye/AGENTS.md` covers code; `docs/AGENTS.md` covers documentation |
| Contribution process for people | `CONTRIBUTING*.md` | Commit, check and reporting expectations |
| Field records, review history, material with site data | Outside the repository | Not kept here |

## Naming

- File names are lowercase English words joined by hyphens and start with the topic, such as `rack-operations-data-contract.md`. No product prefix, date or version number.
- Each document is two files, `<name>.md` (English) and `<name>.zh-CN.md` (Simplified Chinese), with matching content and links to each other.
- Documents on one topic share a prefix, such as `rack-operations` and `rack-operations-data-contract`.
- In code, one feature has one name across the backend module, API path, frontend script, state and tests, such as `device_status.py`, `/api/device-status` and `device_status.js`.
- Documents contain no site addresses, serial numbers, credentials or personal names; examples use placeholders.
