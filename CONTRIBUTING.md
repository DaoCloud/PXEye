# Contributing to PXEye

**English** · [简体中文](CONTRIBUTING.zh-CN.md)

Contributions should start with the operator scenario, the relevant NICo resource and the hardware or network conditions needed to reproduce it. Read the [architecture](docs/architecture.md) and [feature boundaries](docs/features.md) before changing a workflow.

## Design principles

- Separate saved plans from hardware execution.
- Distinguish native NICo resources, PXEye composition and site networking.
- Resolve per-device identity; do not turn one site's IP, interface, disk path or OEM exception into a universal default.
- Record whether non-idempotent writes were sent. Read back uncertain results instead of replaying them blindly.
- Present decision-relevant information and a concrete recovery path for failures.

## Change workflow

1. Describe the problem, target NICo revision and current behavior.
2. Reproduce with an authorized environment or an isolated fixture.
3. Make the smallest coherent change and update both documentation languages.
4. Check Python/JavaScript syntax; perform only the validation authorized for that environment. Hardware writes require designated devices and an explicit impact scope.
5. Describe the final behavior, verification evidence and remaining limitations in the change request.

Prepare local tooling before editing:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
npm ci --ignore-scripts
make syntax lint PYTHON=.venv/bin/python
npm run format:check
npm run check:structure
make wheel PYTHON=.venv/bin/python
```

Python requires 3.11 or newer. Runtime code is under `src/pxeye/`; optional unit sources are under `tests/unit/`. Formatting uses Ruff and the pinned Prettier dependency. The `pxeye` and `pxeye-sync-certificates` entry points are installed with the package. `pxeye --help` and `pxeye --version` do not start services. With no arguments, `pxeye` reads the configured site and credentials and performs startup recovery; importing modules alone does not start services.

Use `make syntax` for static syntax checks. `make test` is the optional unit-test entry point; it does not establish hardware compatibility. Do not start regressions or hardware workflows automatically where project or operator instructions exclude them.

Separate fixture rendering, deployment health, hardware actions and full OS acceptance in reports. Include the actual image/Core versions and required API or device capabilities. Never report a rendered success state as an executed installation.

## Documentation

Every public Markdown page has an English `.md` and a Simplified Chinese `.zh-CN.md` version with language links. Keep commands, paths, API names and behavior consistent, and update the [documentation index](docs/README.md). Use only authored, attributed view data in public screenshots; capture instructions are in the [reference scenario](docs/reference-cluster.md).

## Files excluded from contributions

Do not submit credentials, private keys, operational certificates, production manifests, real hardware inventories, SQLite data, raw SOL output, installer user-data or third-party binaries. Check newly added fixtures and images as well as source files. PXEye uses [Apache-2.0](LICENSE); dependencies retain their own licenses.
