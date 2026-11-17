# Unified source build

**English** · [简体中文](source-build.zh-CN.md) · [Documentation](README.md)

`make images` builds and publishes Core, x86_64 Scout/Boot and PXEye from the three maintained `main` branches. libredfish is a compiled Core/Scout dependency, not a separately deployed image.

## Prerequisites

Use a Linux x86_64 builder with local Docker/BuildKit, Git, Make, OpenSSL and Python 3.11+. Allow access to GitHub, container registries, Rust and Ubuntu/Debian package sources, and provide enough compilation/material storage. Configure an HTTP Registry in the Docker daemon's `insecure-registries` first.

PXEye must have a clean working tree whose HEAD equals remote `DaoCloud/PXEye/main`. Merge features and push `main` in each repository before building:

| Repository | Build contents |
| --- | --- |
| `DaoCloud/PXEye` | PXEye and generic UEFI media for external DHCP |
| `SSmallMonster/infra-controller` | Core services, matching CLI, Scout and Boot materials |
| `SSmallMonster/libredfish` | Redfish Rust library used by Core/Scout |

Core's `Cargo.toml` and `Cargo.lock` must pin libredfish to the full library `main` commit resolved for this build. A direct fork Git dependency or `[patch."https://github.com/NVIDIA/libredfish.git"]` override is supported. Old revisions, local `path` overrides and unsynchronized lock files stop the build; the script never edits dependencies or falls back to feature branches.

Prepare Linux amd64 `bin/helm` and `bin/grpcurl`. The unified build extracts `nico-admin-cli` from its newly built Core image instead of using an old local CLI. The PXEye-only shortcut still requires all three prepared tools; see [runtime tools](../bin/README.md).

Provide the target NICo Core's **public CA PEM** for Scout to trust Core; do not include private keys. This is separate from skipping BMC self-signed certificate checks. Boot materials apply to environments trusting that CA.

## Commands

```bash
export REGISTRY=registry.example:5000
export SCOUT_CA_FILE=/private/core-ca.crt
make images
```

Each invocation freezes all three full `main` commits before dependency checks and compilation, ignoring sibling third-party checkouts. Core uses its own Docker recipes and `cargo make build-release-container-services`. Scout uses that same Core commit. Boot uses the upstream mkosi/iPXE tasks and production CA input to package the new Scout. mkosi runs in a local `--privileged` build container; these commands do not access Kubernetes or physical servers.

| Command | Purpose |
| --- | --- |
| `make nico-sources` | Freeze sources and validate libredfish dependency without compilation |
| `make nico-core` | Build Core, including libredfish, API, PXE, DHCP, DNS, BMC proxy and matching CLI binaries |
| `make libredfish` | Compile the library in Core's locked workspace without a deployment image |
| `make nico-scout` | Compile the x86_64 Scout binary without a full boot system |
| `make nico-boot` | Build Core, Scout, x86_64 boot files and a Boot image; requires `SCOUT_CA_FILE` |
| `make images` | Build and push Core, Boot and PXEye; requires `REGISTRY` and `SCOUT_CA_FILE` |
| `make image` / `make pxeye-images` | Build locally / build and push PXEye only, using the current clean commit and local tools; no Core/libredfish fetch |
| `make source-build-help` | Show build-script arguments |

Source-build targets other than `images` push images only when `REGISTRY` is supplied. Every invocation freezes a fresh source set. Use one `make images` invocation for a matching Core/Scout/Boot/PXEye set; do not combine artifacts from separate invocations.

This entry point builds **x86_64 control-plane and x86_64 target-host materials only**. Grace ARM64 Scout/iPXE and DPU BFB files require separate preparation and version records.

## Outputs and offline delivery

```text
outputs_/source-builds/<UTC-time>-<run-ID>/
├── build-lock.json          # status, three commits, dependency, image refs/digests, file SHA256
├── build.log                # executed commands, output and exit codes
├── scout-ca.crt             # public CA snapshot for this build
├── Dockerfile.boot          # generated Boot recipe
└── sources/
    ├── pxeye/              # frozen PXEye main; bin/ gets the matching CLI
    ├── core/               # frozen Core main; artifacts in target/ and pxe/static/
    └── libredfish/          # frozen library main; Cargo fetches this exact dependency commit
```

Use only a lock with `status: complete`. Failure preserves logs, source and any partially published images, with status `failed`; it never falls back to old images. Core/Boot tags include the source commit and unique run ID; PXEye adds its application version. Deploy using each lock entry's `immutable_reference`.

**Building does not update Charts, create an offline archive or deploy.** Update PXEye, Core-service and Boot references in the delivery Chart/build configuration from the lock, then follow [offline delivery](../offline-build/BUILD.md) with `make cache-images` and `make bundles`. Multiple Core services can share the integrated image while retaining their individual commands. The Boot image contains `/x86_64` and `/apt` for the PXE material init container. Retain its default command, or explicitly use `sh -ec 'cp -r /x86_64 /apt /forge-boot-artifacts/blobs/internal/'`; include `/apt`. The existing packager does not consume this lock automatically; unchanged Charts still package old versions. Prepare ISO and other external materials through the delivery checklist.

## Synchronize Chart inputs after a build

Image builds and Chart selection are separate. `make bundles` renders configured references; it never searches the Registry for the newest tag. Use one successful `build-lock.json`:

| Input file | Field | Build result |
| --- | --- | --- |
| `charts/pxeye/values.yaml` | `image` | Complete `images.pxeye.immutable_reference` |
| `deploy/offline-core/values/core.yaml` | `global.image.repository` / `tag` | Split `images.core.reference` into repository and unique tag; API, migrations, DHCP, DNS, hardware health and SSH console inherit this image |
| Same file | `nico-bmc-proxy.image.repository` / `tag` | Same Core image, replacing the old explicit image |
| Same file | `nico-pxe.image.repository` / `tag` | Same Core image, replacing the old explicit image |
| Same file | x86 Boot entry's `image` in `nico-pxe.bootArtifactContainers` | `images.boot-artifacts-x86_64.immutable_reference`; copy both `/x86_64` and `/apt` |

The current Core Chart concatenates `repository:tag`; it does not support a separate `digest` field. Use the build's unique tag and compare the archived image digest with the build lock. Adding a `digest` ignored by the template does not pin the image. Edit the repository inputs above; generated parent Charts place Core settings under `nicoCore` and do not need a second manual edit. Updating images does not enable disabled optional services.

Chart templates have a separate source pin in `offline-build/helm-bundle/chart-sources.json`: `core.url`, `core.sha256` and `core.subdirectory`. Image-only updates can retain validated templates. Template upgrades require a fixed Core commit's source archive, its SHA256, and compatibility review of `deploy/offline-core/patches/` and service arguments. Do not select a moving `main` URL or infer source identity from the unchanged Chart `version: 0.1.1`. If the work directory's `build-config.json` selects custom `helm_bundle.chart_sources`, update that referenced file too.

Commit the release inputs, then run:

```bash
make cache-images
make bundles
```

Check that `outputs_/generated/resolved-images.txt` contains this build's PXEye/Core/Boot references, then inspect output `build-result.json`, archived `manifests/images-lock.json` and the relocated parent Chart. Image digests should match the source build lock. Retain that lock beside the delivery; it is not automatically archived. Editing generated caches or historical `materials-lock.json` is not an upgrade procedure.

See [Grace ARM64 boot materials](arm64-materials.md) for generation, recipe pins and packaging switches.

## Why independent source directories

The directories are independent Git repositories under ignored `outputs_`, not source vendored into PXEye. The build lock records exact cross-repository commits; Cargo's lock records the compiled dependency.

A Git submodule instead commits a child repository URL and fixed commit pointer into its parent. It requires `git clone --recurse-submodules` / `git submodule update --init`, and dependency updates also change the parent's pointer. It fits tightly coupled parent/child source. Independent directories suit separately maintained forks and build caches here; directory and branch names alone cannot establish artifact versions.

The two forks are not registered as PXEye submodules. Core retains its own mkosi/iPXE submodules, initialized at their pinned commits.

See NVIDIA [container builds](https://docs.nvidia.com/infra-controller/documentation/getting-started/building-nico-containers) and [bootable artifacts](https://docs.nvidia.com/infra-controller/documentation/reference/development/bootable-artifacts); the frozen fork source determines the actual tasks.

Source-build stage and command durations are recorded in `build-lock.json` under `timings` and `commands`, including failed commands and exit codes.

If Docker Hub is unreachable, set `BUILD_IMAGE_MIRROR=m.daocloud.io`. The builder rewrites Docker Hub `FROM` addresses only, retaining pinned digests and recording both recipes and the mapping. It does not change host Docker or cluster settings; package downloads inside the Dockerfile still require connectivity.
