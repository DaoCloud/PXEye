# PXEye application code

Read with the repository [AGENTS.md](../../AGENTS.md). Design context is in
[docs/design](../../docs/design/README.md): the
[design specification](../../docs/design/whole-rack-operations.md) for the platform level and
the [frontend design](../../docs/design/frontend/README.md) for the pages, which also holds the
menu and wording rules.

## Protected paths

Installation and device discovery are the main line of the product. These files change only
to fix a defect in installation or discovery, in a commit that says so:

- `installation/`
- `services/tasks.py`, `services/execution.py`, `services/onboarding.py`
- `services/boot_transport.py`, `services/boot_media.py`, `services/site_boot_network.py`
- `services/discovery.py`, `services/site_explorer.py`, `services/device_identity.py`
- `web/pages/onboarding.js`

A new feature reads what these modules expose and does not edit them. It also leaves the
behaviour of `services/equipment.py`, `services/addresses.py` and `services/resources.py`
unchanged: device management, planning and installation are built on them.

## Adding a feature

- Put it in new files: one service module, one page script, one test module.
- Shared files (`bootstrap.py`, `api/`, `persistence/store.py`, `web/shared/`, `web/live.html`,
  `clients/`) only gain a registration: a route, a page script, a table, a hook call.
- Put a preview behind a site switch that is off by default. With it off, the navigation, the
  API and the existing pages behave as before.
- Read-only first. A write to Core or a BMC needs its own review, a named object and effect in
  the confirmation, and a refusal when the device has an installation task in progress.
- New persistent data gets a new table. Do not rename, remove or repurpose an existing field,
  and do not change what is written to Core: an older image must still open the database.

## Keeping the design current

The [design specification](../../docs/design/whole-rack-operations.md) and the
[frontend design](../../docs/design/frontend/README.md) say what whole-rack operations should
do. They are the target, not a record of what exists: the pages in this package are still the
first-version pages, which the [archived documents](../../docs/archive/README.md) describe.

In the same commit as a change that:

- implements a page or an operation of the design: build it as the `spec` of that page under
  `docs/design/frontend/pages/` says; when the implementation has to differ, change the `spec`
  first and regenerate `page-spec.zh-CN.md`;
- shows the design cannot be met, or finds that Core provides something different, at a new
  version or a new kind of site: update the design specification, in both languages;
- changes the menu, a page name or a fixed term: update `docs/design/frontend/README` in both
  languages and the navigation section of the design specification.

A change that does none of these leaves the documents alone. Say in the hand-off which
document was updated, or that none applied.

## Naming

- One feature, one name: `services/<feature>.py`, `/api/<feature-with-hyphens>`,
  `web/pages/<feature>.js`, `tests/unit/test_<feature>.py`.
- In a page script, top-level functions and constants start with the feature name in camel
  case, and `data-live` actions and DOM ids start with it in kebab case. Top-level names are
  global across page scripts and `npm run check:structure` rejects duplicates.
- Register each page and each action with a literal string.

## Data from NICo Core

- Field names and structures come from the Core deployed at a site, read with
  `tools/core-survey.py`, not from memory or from online documentation.
- A page states only what was read. An absent report is unknown, not healthy.
- Record which fields were verified on a real site in the `spec` of the page that uses them. The
  verified fields of the first-version pages are in the
  [archived data contract](../../docs/archive/rack-operations-v1/design/rack-operations-data-contract.md).
- Test against a capture from a real site, not hand-written Core responses:
  `PYTHONPATH=src python3 tools/core-replay.py check <capture.json>`. Captures are made with
  `tools/core-capture.py` ([archived field survey guide](../../docs/archive/rack-operations-v1/field-survey/README.md)) and contain site data: never add one to
  the repository. An `UNRECORDED` request means the code needs data the capture lacks; say so
  instead of inventing a response.

## Checks before a commit

```bash
make syntax lint PYTHON=.venv/bin/python
npm run format:check
npm run check:structure
.venv/bin/python -m unittest tests.unit.test_<feature>
```
