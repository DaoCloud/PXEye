# Build an offline delivery

**English** · [简体中文](BUILD.zh-CN.md)

This is the supported build path for the PXEye/NICo offline delivery. It
creates one verified delivery for PXEye, NICo Core and their required Helm
dependencies. Onsite import and installation are a separate step; see
[onsite deployment](onsite/README.md).

## Prerequisites

Run on a Linux amd64 builder with Docker, a local containerd content store
available through `ctr`, Helm 3, Python 3.11+ with PyYAML, and enough free
space for the Registry cache and the final archive. Commit the PXEye source
before `make images`; that target deliberately refuses a dirty tree.

`make images` generates a tag from the version, Shanghai time and source commit. Set the
build Registry once for this shell. It must contain images reachable by the
builder and accept pushed images.

```bash
cd /path/to/PXEye
export REGISTRY=127.0.0.1:1027
export REGISTRY_INSECURE=true
```

Use the real Registry host and TLS setting for the build environment. The
default `REGISTRY_INSECURE=true` is for an HTTP Registry.

## Build

Build and push PXEye first:

```bash
make images
```

Manually set the parent Chart's `image` field to the complete successful
`PUBLISHED_PXEYE_IMAGE` output, for example
`127.0.0.1:1027/pxeye:0.22.16-202611131820-03c8d4c`:

```bash
vi charts/pxeye/values.yaml
git diff -- charts/pxeye/values.yaml
git add charts/pxeye/values.yaml
git commit -m "chore(chart): update PXEye image"
make cache-images
make bundles
```

`make images` builds and pushes a `<version>-<YYYYMMDDHHmm>-<7-character commit>`
tag without reading or updating the Chart image reference. The full source
commit is recorded in image metadata. Rebuilding the same commit in the same
minute refuses to overwrite an existing local tag. After manually updating
and committing the Chart, `make cache-images` renders that parent Chart, obtains the
complete image closure, and caches missing images in `REGISTRY`. `make bundles`
uses that cached Registry content, vendors the locked child Charts under the
PXEye parent, runs relocation once, and verifies the archive by reading it
back. With ARM enabled, it also builds or reuses the content-addressed ARM
material image from the validated local payload.

To include the optional ARM64 boot payload, set both variables before the last
two commands:

```bash
export INCLUDE_ARM64_MATERIALS=1
export ARM64_MATERIALS_DIR=/absolute/path/to/boot/aarch64
make cache-images
make bundles
```

The ARM directory must directly contain `BUILD-INFO.json`,
`ROOTFS-PACKAGES.json`, `golan.efi`, `ipxe.efi`, `scout.efi`, and
`scout.squashfs`. The build verifies those files and packages them in an
immutable material image consumed by the NICo PXE init container; they are not
delivered as loose onsite files.

## Outputs and handoff

With the default configuration, generated state stays under the ignored
`outputs_/` directory:

```text
outputs_/
├── build-config.json                  # created once; preserves stage settings
├── chart-sources.json                  # locked upstream child-Chart sources
├── generated/resolved-images.txt      # parent-Chart image closure
├── cache/registry-exports/            # resumable build cache, not handoff data
└── output/bundle-<version>/
    ├── bundle.tar.gz                  # main offline delivery
    ├── onsite-tools.tar.gz            # small one-command onsite runner kit
    ├── SHA256SUMS                     # checksums for both archives
    └── build-result.json              # version, image/chart counts and digests
```

`SHA256SUMS` is optional build/transfer evidence; the one-command onsite
runner does not consume it. The runner accepts only the `bundle.tar.gz` path
and verifies the delivery's immutable internal file inventory after extraction.
If the field transfer process requires an explicit check, run:

```bash
cd outputs_/output/bundle-<version>
sha256sum -c SHA256SUMS
python3 -m json.tool build-result.json
```

After extraction, `bundle.tar.gz` has one `<bundle-id>/` root containing:

```text
bundle.json                         # delivery identity and parent Chart metadata
charts/pxeye.tgz                    # PXEye parent Chart with locked dependencies
relocation/pxeye.tar                # relok8s intermediate image transport
manifests/                          # image, material, toolchain and file locks
profiles/install-plan.json          # ordered Helm phases
tools/                              # Helm, relok8s, verifier and onsite helpers
docs/                               # delivery documentation and licenses
```

The current profile covers PXEye/NICo Core and required cert-manager, platform
and Vault dependencies, plus optional ARM64 boot material. It does not include
REST, Temporal, Keycloak, DPF services or an operating-system ISO.

The onsite runner uses the bundled PXEye Chart to connect PXEye to the same-namespace Core client Secrets and
in-cluster API. Therefore, after a PXEye source change, publish a new PXEye image with `make images` before running
`make bundles`. It does not put physical DNS/PXE/NTP endpoints or a HostInband network into the delivery.

The first install requires an empty `nico-system` namespace apart from Kubernetes-generated default objects. It rejects
residual PVCs, Secrets, Services and other namespaced resources rather than adopting them. A legacy four-release NICo
installation needs an explicit migration or a clean `nico-system`; it is not adopted by this bundle. The initial
control-plane-only delivery also keeps `nico-dhcp` at zero replicas: real DNS/NTP/PXE/VIP values and explicit DHCP
enablement are a later site-network action.
