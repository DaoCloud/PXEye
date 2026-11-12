# NICo / PXEye offline delivery

**English** · [简体中文](README.zh-CN.md)

Run one builder script with one `build-config.json`. It exports local containerd images, prepares pinned Charts, and builds and verifies the offline delivery. Onsite deployment still runs on the fireseed host.

## Build

Run the following sections in order: publish PXEye, cache the locked Chart image
closure, then build the delivery. All commands run from the PXEye checkout:

```bash
cd ~/pxeye-build/PXEye
```

## Publish PXEye

Before caching Chart images or building a delivery, publish the exact PXEye
reference declared by `charts/pxeye/values.yaml`:

```bash
REGISTRY=127.0.0.1:1027 REGISTRY_INSECURE=true make images
```

`make images` requires the Chart image host to equal `REGISTRY` and uses the
Chart's explicit tag. If that local tag already exists, it is reused and its
OCI revision is reported; otherwise the normal clean-tree image build runs.
It never rewrites Chart values. For an HTTP Registry, configure the Docker
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

The build verifies the pinned file checksums, creates a content-addressed
material image, and makes the Core PXE service publish it through the existing
boot-artifact path. Use the same two variables with `make cache-images` when
preparing a Registry for an ARM-enabled build.

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

Registry OCI exports and bundle staging are cached under `cache/registry-exports/`; final delivery files always go to `output/bundle-<version>/` at the build work-directory root.

Read-only validation of local images, roles, Chart sources and delivery input:

```bash
python3 ./PXEye/offline-build/delivery.py --config ./build-config.json --plan
```

| Internal stage | Purpose | Delivery/cache |
| --- | --- | --- |
| cache seed (inside `make bundles`) | Render the parent Chart and export its exact local containerd image closure only when it changed | `offline-images/` |
| package | Verify the cached closure, vendor locked child Charts under the PXEye parent, use the configured Registry, run relok8s once, and produce the delivery | `cache/registry-exports/`, `charts/`, `bundle-staging/`, `output/` |

| Step | Purpose | Input | Output |
| --- | --- | --- | --- |
| [Internal image export](material-prepare/README.md) | Export listed local containerd images | Image list | `offline-images/` |
| [Internal packaging](helm-bundle/README.md) | Prepare the PXEye parent/dependencies, relocate one image closure and verify | Exported images and Chart sources | Three delivery files |
| [Onsite deployment](onsite/README.md) | Unpack, import images/Charts, install through Helm in order | Three delivery files and site configuration | PXEye, NICo Core and dependencies |

## Configuration and state management

- Configure contents/versions during building; configure Registry, namespace, networking, storage and authentication onsite. The default namespace is `nico-system`.
- Scripts manage image imports, and project Helm Charts manage Kubernetes resources.
- Recovery reuses verified materials and completed stages with the same configuration. Progress records are associated with their inputs; changed inputs require a separate version or work directory.
- Package verification, Helm readiness and physical provisioning acceptance are separate outcomes.

## Requirements and paths

Builder: Linux amd64, Python 3.11+/PyYAML, local Docker, Helm 3 and sufficient space. Fully offline builds require cached locked tools and base images.

Fireseed: Linux amd64, Python 3.11+/PyYAML, kubectl, an available cluster/Registry and working node image pulls. Helm and relok8s are delivered in the bundle.

```text
/srv/PXEye/offline-build/
  build-config.example.json  # shared build configuration
  delivery.py           # unified builder entry
  material-prepare/     # legacy explicit-image exporter
  helm-bundle/          # chart-sources.json
  onsite/               # run.py + run-config.example.json

/srv/nico-build/        # builder configuration, prepared data, caches and delivery
/srv/nico/              # onsite delivery files, tools, configuration and records
```

The pinned e703 profile covers single-node Core/PXEye, without REST/Temporal/Keycloak, DPF services or Ubuntu ISOs. It does not discover current running images. Step one only exports images. Step two wraps optional binary materials as images; existing prepared / nico-materials inputs remain compatible. Material HTTP readiness does not establish consumer URLs or physical connectivity.

Compatibility-format maintenance is documented in [legacy material preparation](legacy-materials.md) and [legacy deployment configuration](CONFIGURE.md). Those input formats and entry points are separate from this workflow.
