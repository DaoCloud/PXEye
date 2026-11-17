# Grace ARM64 boot materials

**English** · [简体中文](arm64-materials.zh-CN.md) · [Documentation](README.md)

Grace hosts need ARM64 iPXE, Scout boot files and a target ARM64 OS. An x86 control plane cannot provide executable x86 boot files to Grace. BlueField BFB is a separate DPU input.

## Rebuild from main

On a Linux x86_64 machine with local Docker, build prerequisites and a public Core CA, follow [source builds](source-build.md):

```bash
export REGISTRY=registry.example:5000
export SCOUT_CA_FILE=/private/core-ca.crt
export INCLUDE_ARM64_MATERIALS=1
make images
```

This rebuilds Core, x86 Boot, Grace ARM64 Scout/rootfs/UEFI and PXEye from one frozen set of main revisions. libredfish must match Core's pinned main commit. `make nico-boot-arm64` rebuilds ARM alone, but each independent invocation freezes main again: do not mix different Core revisions.

ARM stages prepare the cross toolchain, compile Scout's Debian package, assemble rootfs/UEFI with mkosi, then inspect final files. QEMU interprets ARM userspace. A privileged build container registers its own temporary binfmt entry and removes that entry on exit. It neither controls physical hosts nor runs GPU tests.

Inspection checks ARM64 EFI/ELF, exact embedded Scout binary hashes, 64 KiB page compatibility, CA, Scout version, configured packages and key kernel-module ABIs. These checks do not prove a real Grace boot.

Module checks examine installed files under `/usr/lib/modules/` or `/lib/modules/`; DKMS build copies are excluded. When [resuming a failed full build](source-build.md), a completed ARM assembly can be retained if its assembly recipe is unchanged. Retained checkpoints are hash-checked and final content inspection runs again. For older builds without an assembly checkpoint, the recovery records current file hashes with `checkpoint_origin=post-failure-recovery`; these are recovery-time hashes, not hashes recorded by the original assembly.

## Outputs

The command prints `ARM64_MATERIALS_DIR`; `build-lock.json` records its path and sources under `arm64_materials`:

```text
outputs_/source-builds/<run-id>/arm64-materials/
├── ipxe.efi
├── golan.efi
├── scout.efi
├── scout.squashfs
├── BUILD-INFO.json
├── ROOTFS-PACKAGES.json
└── MATERIAL-RECIPE.json
```

The first four files boot the host. `BUILD-INFO.json` records source and inspection results, `ROOTFS-PACKAGES.json` lists installed packages, and `MATERIAL-RECIPE.json` locks sizes and hashes for the six delivered files. These JSON documents are project audit records, not NICo host-ingestion fields.

## Offline packaging

Update Chart image references from the successful complete build lock, then use that build's output:

```bash
export REGISTRY_INSECURE=true
export SOURCE_BUILD_LOCK=/absolute/path/to/build-lock.json
export ARM64_MATERIALS_DIR=/absolute/path/to/arm64-materials
make arm64-materials
make cache-images
make bundles
```

`make arm64-materials` validates and publishes the material image; it does not compile or archive. `make bundles` remains the final archive entrypoint. A generated recipe takes precedence over the historical `recipe-e703.json`. With `SOURCE_BUILD_LOCK`, all six hashes must match its ARM records and ARM/Core/libredfish revisions must agree.

The final Chart adds a `boot-artifacts-aarch64` init container to copy files into NICo PXE's `/forge-boot-artifacts/blobs/internal/aarch64`, served under `/public/blobs/internal/aarch64/`. This amd64 container carries AArch64 payloads for the x86 control plane. Retain its ENTRYPOINT without overriding command/args. No separate HTTP server is needed.

Inspect archived `manifests/source-build-lock.json`, `manifests/materials.json` and `manifests/images-lock.json`. Stage durations are recorded in the source build lock, `outputs_/logs/delivery/<run-id>/timings.json` and archive `progress.json`.

Import the target ARM64 OS ISO separately; its extracted kernel/initrd are distinct from Scout. The external-DHCP generic small boot ISO currently targets x86. Grace requires compatible ARM64 media or native network boot. This entrypoint does not produce DPU BFB/firmware or a standalone ARM APT repository.

See NVIDIA's [container/boot material builds](https://docs.nvidia.com/infra-controller/documentation/getting-started/building-nico-containers) and [Bootable Artifacts](https://docs.nvidia.com/infra-controller/documentation/reference/development/bootable-artifacts).
