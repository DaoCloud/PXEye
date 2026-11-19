# PXEye application code

Read with the repository [AGENTS.md](../../AGENTS.md). Design context is in
[docs/design](../../docs/design/README.md); interface and wording rules are in
[interaction rules](../../docs/design/interaction-rules.md).

## Protected paths

Installation and device discovery are the main line of the product. These files change only
to fix a defect in installation or discovery, in a commit that says so:

- `installation/`
- `services/tasks.py`, `services/execution.py`, `services/onboarding.py`
- `services/boot_transport.py`, `services/boot_media.py`, `services/site_boot_network.py`
- `services/discovery.py`, `services/site_explorer.py`, `services/device_identity.py`
- `web/pages/onboarding.js`

A new feature reads what these modules expose. It does not edit them, and it does not change
the behaviour of `services/equipment.py` or `services/addresses.py`, which they depend on.

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

## Keeping the requirements current

[Capability requirements](../../docs/design/rack-operations-requirements.md) is the long-lived
record of what rack operations should do and what exists. Update the “Implementation status” of
the affected functional area, in both languages, in the same commit that:

- adds, changes or removes a feature in that area;
- shows a requirement cannot be met, or builds it differently from what it says;
- finds that Core provides something different, at a new version or a new kind of site;
- drops an item.

A change that does none of these leaves the document alone. Say in the hand-off which area was
updated, or that none applied.

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
- Record which fields were verified on a real site in the data contract of the feature.

## Checks before a commit

```bash
make syntax lint PYTHON=.venv/bin/python
npm run format:check
npm run check:structure
.venv/bin/python -m unittest tests.unit.test_<feature>
```
