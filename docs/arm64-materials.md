# Grace ARM64 boot materials

**English** · [简体中文](arm64-materials.zh-CN.md) · [Documentation](README.md)

An x86 Kubernetes control plane does not make x86 boot programs executable on Grace. Grace needs ARM64 iPXE, a Scout boot system and an ARM64 target OS. BlueField DPU BFBs are separate materials, not Grace host boot files.

A fixed-recipe **validation, material-image and offline delivery workflow** exists. `make images` still builds x86 Boot only; producing updated Grace materials requires a separate build environment and artifact inspection.

## Input directory

`ARM64_MATERIALS_DIR` must be an absolute directory directly containing six regular files:

```text
/srv/nico-materials/aarch64/
├── ipxe.efi
├── golan.efi
├── scout.efi
├── scout.squashfs
├── BUILD-INFO.json
└── ROOTFS-PACKAGES.json
```

| File | Purpose |
| --- | --- |
| `ipxe.efi`, `golan.efi` | ARM64 UEFI network loader and NIC-specific variant |
| `scout.efi` | Scout boot kernel and loader |
| `scout.squashfs` | Scout root filesystem with `forge-scout`, `mlx-firmware-supervisor`, drivers and dependencies |
| `BUILD-INFO.json` | Build provenance, versions, architecture and boot-file sizes/hashes |
| `ROOTFS-PACKAGES.json` | Actual package names, versions and architectures exported from the final root filesystem |

The last two files are PXEye delivery audit records, not NICo's required host ingestion schema. Import the final ARM64 OS ISO separately and extract its kernel/initrd; Scout files do not replace them.

## Produce updated materials

1. **Freeze versions.** Use the same full `infra-controller` commit as Core and its Cargo/libredfish lock. Record Rust, mkosi/iPXE commits, base OS, kernel, NVIDIA driver and public CA. Renaming an old Scout does not update it.
2. **Prepare an ARM build environment.** Prefer native Linux ARM64. Cross-compilation and QEMU require additional handling of ARM packages, kernel-module compilation and mkosi execution. An x86 control host does not supply these automatically.
3. **Compile and assemble.** Source entry points are `package-scout-aarch64-release-local`, and `ipxe-aarch64`, `create-ephemeral-image-arm-host-ci`, `setup-apt-repo-arm64` in `pxe/Makefile.toml`. Assembly needs the previously generated Scout package. Explicitly supply `FORGE_CA_PATH` for production assembly instead of a developer CA. The combined `build-boot-artifacts-arm-host` also includes DPU work and has a source comment warning about local ARM limitations; it is not a validated PXEye one-command workflow.
4. **Inspect final content.** Verify AArch64 EFI and both Scout ELF programs, Grace's 64 KiB page compatibility, kernel/driver ABI, libraries, package completeness, Core CA and Secure Boot policy. Core's `scripts/check-aarch64-pagesize.sh` checks ELF compatibility. Passing content checks does not prove a real Grace boot.
5. **Generate records and update the recipe.** Generate the two JSON records from final artifacts, recording real SHA256 values, source revisions and inspection results. Update the six `group: aarch64` entries' `bytes` / `sha256` in `offline-build/material-prepare/recipe-e703.json`, retaining filenames, order and target paths. The historical `e703` recipe name does not assert that new files use that source revision. Review and commit before packaging.
6. **Validate delivery.** Package as below, then check complete PXE HTTP downloads, hashes and a real Grace UEFI → iPXE → Scout report, followed by ARM64 OS installation. Record content checks, Pod readiness and hardware installation separately.

These are material-production requirements and existing source entry points. The repository does not yet provide one ARM generation script covering all six steps. Successfully repackaging old files is not a new ARM compilation or hardware acceptance result.

## Include in an offline delivery

After preparing six files matching the committed recipe, run on the Linux x86_64 packaging host:

```bash
export REGISTRY=registry.example:5000
export REGISTRY_INSECURE=true
export INCLUDE_ARM64_MATERIALS=1
export ARM64_MATERIALS_DIR=/srv/nico-materials/aarch64
make arm64-materials
make cache-images
make bundles
```

This step **does not recompile Scout**. It checks all six sizes/SHA256 values, builds or reuses a content-addressed material image and records its digest. Its init container runs on the x86 control plane and carries ARM64 files: the container platform can be amd64 while its boot payload must be AArch64.

The final Chart automatically adds `boot-artifacts-aarch64` to `nicoCore.nico-pxe.bootArtifactContainers`. It verifies and copies files into `/forge-boot-artifacts/blobs/internal/aarch64`, served by NICo PXE at `/public/blobs/internal/aarch64/`. Retain the material image ENTRYPOINT without `command` / `args` overrides. No separate HTTP service is required.

Check delivered `manifests/materials.json`, `manifests/images-lock.json` and the final Chart's ARM init container. New files differing from the pinned recipe fail validation; setting environment variables does not approve arbitrary ARM payloads. This six-file path does not additionally deliver an ARM APT repository or DPU BFB; plan those separately when needed.

The generic external-DHCP small boot ISO builder is still x86_64. Grace requires compatible ARM64 boot media or a matching native network-boot path; do not reuse the x86 small ISO.

References: NVIDIA [container and boot-material builds](https://docs.nvidia.com/infra-controller/documentation/getting-started/building-nico-containers) and [Bootable Artifacts](https://docs.nvidia.com/infra-controller/documentation/reference/development/bootable-artifacts). BFB `BOOTSTRAP_CA_PATH` belongs to DPU provisioning, separate from host Scout `FORGE_CA_PATH`.

`make arm64-materials` validates and publishes existing files only; it does not compile Scout or produce an archive. Its record is `outputs_/generated/arm64-materials.json`. `make bundles` still verifies and reuses matching content. Stage durations are written to `outputs_/logs/delivery/<run-id>/timings.json`; archive substages are recorded in the corresponding `progress.json`.
