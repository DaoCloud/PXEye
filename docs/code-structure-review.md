# Code structure review and implementation

**English** · [简体中文](code-structure-review.zh-CN.md) · [Documentation](README.md)

## Scope

The initial static review examined the `0.20.3` source on 2026-11-07. After authorization, the findings were addressed in the `0.21.0` package. This covers PXEye only; upstream NICo, NVKE and provider repositories are outside the change.

The initial snapshot had 32 runtime Python files and nine global frontend scripts. Its largest modules were `server.py` (1,094 lines), `executor.py` (1,062), `resources.py` (984) and `equipment.py` (956). These are historical measurements, not current paths or runtime failure evidence. No finding was established as the cause of an earlier physical installation failure.

## Findings and delivered changes

| Priority | Historical finding | Delivered change and current source |
| --- | --- | --- |
| P1 | List reads exported CSV through a shared `machines.tmp` file. | [Atomic text/JSON writer](../src/pxeye/common.py) uses unique exclusive temporary files, flush/fsync, replacement and cleanup. [Resource refresh](../src/pxeye/services/resources.py) owns export and missing-plan seeding; device GETs no longer do these writes. |
| P2 | Scripts captured and replaced dialog/page functions; listeners and legacy views overlapped. | [UI runtime](../src/pxeye/web/shared/ui_runtime.js) registers one owner per page/action, delegates events and controls polling. Named helpers and lifecycle hooks replace function capture. Old duplicate page renderers and discovery polling are removed. |
| P2 | Transport and planning services constructed each other; common contracts lived in large services. | [Clients](../src/pxeye/clients/core.py) separate Core/Redfish/SSH/process transport. Common helpers and [Machine contracts](../src/pxeye/domain/machines.py) are independent. [Bootstrap](../src/pxeye/bootstrap.py) injects resources, plans and profiles into the execution facade. |
| P2 | Constructors repeated schema/legacy setup; projections repeatedly scanned operations. | [Store](../src/pxeye/persistence/store.py) centralizes schema and version recording, with path-keyed wrappers and per-operation connections. Legacy profile import is explicit at bootstrap. [Device projection](../src/pxeye/services/device_view.py) owns list composition; address snapshots load proofs, plans and operation records once. |
| P2 | HTTP composition owned task recovery, scheduling and locking. | [Task coordinator](../src/pxeye/services/tasks.py) owns those operations; [HTTP transport](../src/pxeye/api/http.py), queries and commands are separate modules. Application retains thin compatibility forwards. |
| P2 | Failures lacked safe, consistent diagnostic context. | [Error translation](../src/pxeye/api/errors.py) returns codes and request IDs for GET/POST/uploads; logs preserve stack locations without raw exception messages, arguments or credential contents. |
| P3 | Runtime, optional validation and site tools shared the root; frontend code was dense. | [Package metadata](../pyproject.toml), `src/pxeye/`, `tests/unit/`, `tools/` and [deployment skeleton](../deploy/kubernetes.yaml) establish boundaries. Python/JS/CSS/HTML are formatted; 12 superseded topology base declarations are removed without moving remaining rules or media blocks. |

## Runtime and compatibility

```text
src/pxeye/
├── __main__.py, bootstrap.py
├── api/             # HTTP, authentication, queries, commands, errors
├── clients/         # Core, Redfish, SSH, bounded processes
├── domain/          # resource, identity and input contracts
├── persistence/     # SQLite schema and repositories
├── services/        # operations, projections and task coordination
├── installation/    # generation, disk policy, boot and acceptance
└── web/             # shared UI runtime, pages and static assets
```

Install the Python package to obtain `pxeye` and `pxeye-sync-certificates`. The Dockerfile installs the same package; wheel data includes UI files and the standalone installation scripts. Existing HTTP routes, config/secrets/data/material mounts and task serialization remain in use. The default static directory is packaged `pxeye/web`; `CONSOLE_STATIC` can still override it. The new local refresh endpoint is documented in [Architecture](architecture.md).

The refactor does not redesign installation state transitions, serial/MAC checks, frozen revisions, signed installer events, disk scope, device reservations, boot handoff, acceptance or uncertain-write recovery. No task/plan table or data directory was deleted. Replacement still requires backups and the normal single-executor update procedure.

## Verification and limits

Completed: Python syntax and Ruff checks; JavaScript syntax; static registration audit (11 scripts, eight page renderers, 124 unique actions and no duplicate top-level names); formatting checks; package/module import and console-entry inspection without starting services; wheel build and content inspection; bilingual documentation, local-link and public-file scope checks.

Regression suites, browser workflows, container builds, deployment, database migration against live data and physical installation were not run. Existing screenshots remain the authored reference views; they were not recaptured as part of this refactor. Static and package checks establish source/build coherence, not a new end-to-end compatibility certification.

## Follow-up boundaries

Some capability services still use function-local imports and direct SQL. The execution facade retains installer composition; it is not a pure transport client. Frontend pages still share globals with explicit loading order. File exports and SQLite commits are separate operations, and multi-call Core observations are not atomic. Further repository/query extraction or an ES-module migration should be a scoped follow-up, not a claim already achieved here.
