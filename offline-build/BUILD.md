# Build an offline delivery

**English** · [简体中文](BUILD.zh-CN.md)

This is the supported build path for the PXEye/NICo offline delivery. It
creates one verified delivery for PXEye, NICo Core and their required Helm
dependencies. Onsite import and installation are a separate step; see
[onsite deployment](onsite/README.md).

## Prerequisites

Run on a Linux amd64 builder with Docker, Helm 3, Python 3.11+ and enough free
space for the Registry cache and the final archive. Commit the PXEye source
before `make images`; that target deliberately refuses a dirty tree.

The PXEye image reference is fixed by `charts/pxeye/values.yaml`. Set the
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

Run the three commands in order:

```bash
make images
make cache-images
make bundles
```

`make images` builds or reuses, then pushes the exact PXEye image declared by
the parent Chart. `make cache-images` renders that parent Chart, obtains the
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
├── generated/resolved-images.txt      # parent-Chart image closure
├── cache/registry-exports/            # resumable build cache, not handoff data
└── output/bundle-<version>/
    ├── bundle.tar.gz                  # main offline delivery
    ├── onsite-tools.tar.gz            # small one-command onsite runner kit
    ├── SHA256SUMS                     # checksums for both archives
    └── build-result.json              # version, image/chart counts and digests
```

Verify the three files before copying them to the fireseed host. Keep their
filenames unchanged: the onsite runner matches `bundle.tar.gz` against
`SHA256SUMS`.

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

Onsite restore assumes the target already uses the single parent-Chart release.
A legacy four-release NICo installation needs an explicit migration or a clean
namespace; it is not adopted by this bundle.
