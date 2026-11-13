# NICo / PXEye offline delivery

**English** · [简体中文](README.zh-CN.md)

The supported workflow uses one `build-config.json` and three ordered Make
targets: publish PXEye, cache the parent-Chart image closure, then build the
delivery. The final target exports exactly that closure from the configured
Registry, relocates it once, and verifies the offline delivery. Onsite
deployment still runs on the fireseed host.

For the concise, copyable build sequence, delivery files and extracted bundle
layout, see [Build an offline delivery](BUILD.md).

## Build

Run the following sections in order: publish PXEye, cache the locked Chart image
closure, then build the delivery. All commands run from the PXEye checkout:

```bash
cd ~/pxeye-build/PXEye
```

## Publish PXEye

Before caching Chart images or building a delivery, build and publish PXEye:

```bash
REGISTRY=127.0.0.1:1027 REGISTRY_INSECURE=true make images
```

`make images` builds committed, clean source and pushes
`REGISTRY/pxeye:<version>-<YYYYMMDDHHmm>-<7-character commit>`, using Asia/Shanghai
time and recording the full commit in image metadata. It refuses to overwrite
an existing local tag for the same commit and minute. It does not read or update
the Chart image reference. Manually set `image` in `charts/pxeye/values.yaml` to
the successful `PUBLISHED_PXEYE_IMAGE` output and commit the change before
caching or packaging; see [the build guide](BUILD.md) for commands.
For an HTTP Registry, configure the Docker
daemon to trust that Registry as insecure; Docker has no per-push TLS override.

## Optional ARM64 boot materials

ARM64 boot files are disabled by default; the default build does not inspect an
ARM source directory. To package the locked Grace/ARM64 boot files, explicitly
enable them and point at the directory that directly contains
`BUILD-INFO.json`, `ROOTFS-PACKAGES.json`, `golan.efi`, `ipxe.efi`,
`scout.efi`, and `scout.squashfs`:

```bash
REGISTRY=127.0.0.1:1027 REGISTRY_INSECURE=true \
  INCLUDE_ARM64_MATERIALS=1 \
  ARM64_MATERIALS_DIR=/absolute/path/to/boot/aarch64 \
  make bundles
```

The build verifies the pinned file checksums, creates a linux/amd64,
content-addressed material image, and makes the Core PXE service publish it
through the existing boot-artifact path. Its identity includes the payload,
base manifest, initializer and rendered image definition, so a changed image
contract cannot reuse a previous tag. Use the same two variables with `make
cache-images` when preparing a Registry for an ARM-enabled build.

## Image cache

After PXEye is published, cache the parent-Chart closure in the same Registry:

```bash
REGISTRY=127.0.0.1:1027 REGISTRY_INSECURE=true \
  make cache-images
```

The command does not read `images.txt`. It renders the PXEye parent and locked child Charts, pulls only missing images from their original public references, and pushes them to `REGISTRY`. Third-party and NICo images retain their repository path and tag while their registry host changes; the PXEye image becomes `REGISTRY/pxeye:<tag>`. It does not create a bundle or deploy Kubernetes.

## Build delivery

After the Registry is ready, create the offline delivery:

```bash
REGISTRY=127.0.0.1:1027 REGISTRY_INSECURE=true make bundles
```

`make bundles` creates configuration and resumable build state under the
repository's ignored `outputs_/` directory. It renders the parent Chart, reads
only the configured Registry, then packages and verifies the delivery. It
defaults to `outputs_/build-config.json` and creates
`outputs_/output/bundle-<PXEye version>-<Asia/Shanghai timestamp>/`, such as
`bundle-0.22.16-202611121650`. Override only when needed, for example
`BUNDLE_VERSION=release-1`.

After each Registry pull, the builder verifies the selected amd64 content graph
in containerd. If an old local image record has dangling content, it fetches
that image's content once from the same Registry and validates again; it never
deletes image tags or Kubernetes resources.
Registry-input images live in a deterministic, build-private containerd
namespace named `pxeye-offline-<closure-id>`, rather than `k8s.io`; the cache
is retained for retry and never participates in runtime workload image state.

Registry OCI exports and bundle staging are cached under `cache/registry-exports/`; final delivery files always go to `output/bundle-<version>/` at the build work-directory root.

| Internal stage | Purpose | Delivery/cache |
| --- | --- | --- |
| registry input | Render the parent Chart, pull its exact image closure from `REGISTRY`, then create an isolated OCI export | `cache/registry-exports/` |
| package | Vendor locked child Charts under the PXEye parent, run relok8s once, and verify the final delivery | `bundle-staging/`, `output/` |

The legacy [explicit-image exporter](material-prepare/README.md) and
[schema-1 packager](helm-bundle/README.md) remain for compatibility only; they
are not steps in this workflow. The onsite handoff starts at
[onsite deployment](onsite/README.md).

## Configuration and state management

- Build configuration defines contents and versions. The onsite runner accepts only the delivery archive and always deploys to `nico-system`. Physical boot endpoints, the HostInband network and provisioning policy are subsequent PXEye site settings; they must never be Kubernetes Service ClusterIPs.
- Scripts manage image imports, and project Helm Charts manage Kubernetes resources.
- Recovery reuses completed stages for the same archive. Extraction and runtime-state paths are derived from the archive name; use a different archive name for changed input.
- Package verification, Helm readiness and physical provisioning acceptance are separate outcomes.

## Requirements and paths

Builder: Linux amd64, Python 3.11+/PyYAML, local Docker, a local containerd
content store accessible with `ctr`, Helm 3 and sufficient space. ARM material
construction rejects another host architecture before Docker mutates local or
Registry state. Fully offline builds require cached locked tools and base images.

Fireseed: Linux amd64, Python 3.11+/PyYAML, kubectl, an available cluster/Registry and working node image pulls. Helm and relok8s are delivered in the bundle.

```text
/srv/PXEye/offline-build/
  build-config.example.json  # shared build configuration
  delivery.py           # unified builder entry
  material-prepare/     # legacy explicit-image exporter
  helm-bundle/          # chart-sources.json
  onsite/               # run.py; its only input is --archive

/srv/nico-build/        # builder configuration, prepared data, caches and delivery
/srv/nico/              # onsite delivery files, runner, derived extraction and runtime records
```

The pinned e703 profile covers single-node Core/PXEye, without REST/Temporal/Keycloak, DPF services or Ubuntu ISOs. It does not discover current running images. Step one only exports images. Step two wraps optional binary materials as images; existing prepared / nico-materials inputs remain compatible. Material HTTP readiness does not establish consumer URLs or physical connectivity.

Compatibility-format maintenance is documented in [legacy material preparation](legacy-materials.md) and [legacy deployment configuration](CONFIGURE.md). Those input formats and entry points are separate from this workflow.
