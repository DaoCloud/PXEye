# PXEye documentation

Read with the repository [AGENTS.md](../AGENTS.md).

## Where a document goes

| Content | Location |
| --- | --- |
| Why something is built the way it is, scope, rules, data contracts | `docs/design/` |
| How to use one menu page | `docs/user-guide/`, one document per page |
| Deployment, builds, field procedures | `docs/` |
| Rules for AI collaborators | `AGENTS.md` in the directory they apply to |

The index of each directory lists every document in it. Add, rename or remove a document and
its index row in the same commit, and keep every relative link working.

## Naming and language

- Lowercase English words joined by hyphens, starting with the topic. No product prefix, date
  or version number. Documents on one topic share a prefix.
- Every document is a pair: `<name>.md` in English and `<name>.zh-CN.md` in Simplified Chinese,
  with the same structure, commands, paths and API names, each linking to the other and to
  its index.

## Documents that track the product

- [design/rack-operations-requirements](design/rack-operations-requirements.md) holds the target
  capabilities and, per functional area, the implementation status. It is the single place where
  that status is maintained; other documents link to it and do not restate it.
- [design/rack-operations](design/rack-operations.md) holds the pages, rules and plan of the
  current stage.
- [design/rack-operations-data-contract](design/rack-operations-data-contract.md) holds the Core
  interfaces and fields, with verification marks.

A design change is reflected in these documents in the commit that makes it.

## Content

- A design document states the current conclusion. Replace what is superseded instead of
  appending dated sections; history belongs in Git.
- Separate what is implemented, what was verified and how, and what is only planned. Do not
  describe a rendered example as a result observed on hardware.
- No site addresses, serial numbers, credentials, personal names, raw site responses or
  captures made with `tools/core-capture.py`. Use
  placeholders such as `<namespace>` and `<machine ID>`.
- Screenshots use authored data with a stated source.
