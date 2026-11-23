# PXEye documentation

Read with the repository [AGENTS.md](../AGENTS.md).

## Where a document goes

| Content | Location |
| --- | --- |
| The target design: what is to be built and why, the flow, modules, resources, rules | `docs/design/`: the design specification and `figures/` |
| The page design: clickable pages and the description of every page | `docs/design/frontend/` |
| What the existing code does: features and boundaries, architecture | `docs/features*.md`, `docs/architecture*.md` |
| How to use one menu page of the existing code | `docs/user-guide/`, one document per page |
| Deployment, builds, field procedures | `docs/` |
| Superseded documents | `docs/archive/`, one directory per archived batch |
| Rules for AI collaborators | `AGENTS.md` in the directory they apply to |

The index of each directory lists every document in it. Add, rename or remove a document and
its index row in the same commit, and keep every relative link working.

## Naming and language

- Lowercase English words joined by hyphens, starting with the topic. No product prefix, date
  or version number. Documents on one topic share a prefix.
- Every document is a pair: `<name>.md` in English and `<name>.zh-CN.md` in Simplified Chinese,
  with the same structure, commands, paths and API names, each linking to the other and to
  its index.
- The interface is in Simplified Chinese, and so is the frontend design. Its generated page
  descriptions (`design/frontend/page-spec.zh-CN.md`) exist in Simplified Chinese only. English
  documents quote menu and page names in Chinese and add an English gloss where they first
  appear.

## Design documents

The design under `docs/design/` is the target, not a record of what exists. Its
[index](design/README.md) says what each part holds. Each piece of content has one source:

- [design/whole-rack-operations](design/whole-rack-operations.md) holds the platform level:
  architecture, the flow, modules, resources, rules. A change to the menu, the flow, a module
  or a gate updates it in both languages in the commit that makes the change.
- [design/frontend](design/frontend/README.md) holds the page level. The description of a
  page is the `spec` of its script under `design/frontend/pages/`, next to the code that
  renders the page. Change a page and its `spec` together, then regenerate
  `page-spec.zh-CN.md` with `node docs/design/frontend/tools/build-spec.mjs`. Never edit the
  generated file.
- Menu and wording rules are in `design/frontend/README`. The design specification does not
  restate page details, and the frontend design does not restate the platform design.
- Figures are generated from the sources in `design/figures/`. Change the source, regenerate
  the image, commit both.

## Archiving

A design that is superseded is archived, not deleted and not left in place:

- Move it to `docs/archive/<batch>/` with `git mv`, keeping its relative structure.
- Add the archive note under the title of each document, in its own language, and add the
  batch to [archive/README](archive/README.md) with the reason and what is still useful.
- Rewrite the relative links the move affects, and check that every relative link in the
  repository still resolves.
- Do not update archived documents afterwards. What still holds is written into a current
  document.

## Content

- A design document states the current conclusion. Replace what is superseded instead of
  appending dated sections; history belongs in Git.
- Separate what is implemented, what was verified and how, and what is only planned. Do not
  describe a rendered example as a result observed on hardware. The frontend design uses
  authored sample data and says so.
- No site addresses, serial numbers, credentials, personal names, raw site responses or
  captures made with `tools/core-capture.py`. Use
  placeholders such as `<namespace>` and `<machine ID>`.
- Test plans, simulation plans and site records are not design documents and do not go into
  this repository.
- Screenshots use authored data with a stated source.
