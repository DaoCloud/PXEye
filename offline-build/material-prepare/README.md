# Step 1: prepare NICo / PXEye offline materials

**English** · [简体中文](README.zh-CN.md)

This directory sits alongside `../helm-bundle/`. Run one script with one user configuration. It checks all inputs, imports explicitly selected images, builds material images, verifies their payloads, patches pinned raw Charts and writes the configuration consumed by step 2. It never uses Kubernetes or running-cluster image discovery.

The maintained `recipe-e703.json` selects 11 Core/dependency images, one PXEye UI image and one bootstrap/tool image. Optional ARM64 Scout, APT and BFB images are built here. REST, Temporal, Keycloak, a standalone DNS resolver, DPF services and Ubuntu ISOs are outside this profile. Existing NICo executable images are imported, not recompiled.

## 1. Configure

Goal: use a Linux amd64 builder with Python 3.11+/PyYAML, local Docker and Helm 3. Assume the repository is `/srv/PXEye`. Raw Charts and payloads must already be available; no previous generic bundle is required.

Commands:

```bash
mkdir -p /srv/nico-build
cp /srv/PXEye/offline-build/material-prepare/build-config.example.json /srv/nico-build/build-config.json
${EDITOR:-vi} /srv/nico-build/build-config.json
```

Confirmation:

```bash
python3 /srv/PXEye/offline-build/material-prepare/build.py --config /srv/nico-build/build-config.json --plan
```

Set `input_root`, three archive paths (absolute or relative to input_root), `output_root`, `cache_directory`, `package_output_root`, material switches and tools. Keep artifacts outside the repository and input tree. `recipe-e703.json` resolves from the script directory when not beside the configuration. The user does not edit per-file hashes or supply onsite addresses, namespaces or credentials.

The default sources are pinned archives, explicitly reusable for migration. Ordinary images can use digest-pinned `registry` sources; this extension requires separate validation. Bootstrap tools must remain archive-sourced. This is not a generic NICo source compiler.

## 2. Prepare with one command

Goal: complete every preparation operation without manually starting a Registry or building/exporting images.

Command:

```bash
python3 /srv/PXEye/offline-build/material-prepare/build.py --config /srv/nico-build/build-config.json
```

Confirmation:

```bash
ls /srv/nico-build/prepared/*.result.json
```

Success prints `MATERIAL_PREPARE_COMPLETE` and `HELM_BUILD_CONFIG`. Inputs and output OCI blobs are hashed; material files are verified inside the resulting images. The completed directory is renamed atomically. Failure retains `.building-*` and logs. Existing valid output is fully checked and reused. Material cache keys include content, publisher, platform, base digest and build instructions, not release dates. The current material base is the pinned bootstrap image containing Python and skopeo; it is not a minimal base.

A per-run loopback Registry is stopped on exit. Only this run's image tags are removed; Docker build caches may remain. No persistent Registry, global prune or cluster mutation is performed.

## 3. Outputs and step 2

Goal: hand over a complete, independent prepared directory.

```text
/srv/nico-build/
  build-config.json
  cache/materials/<content-hash>/
  prepared/
    <input-and-implementation-id>/
      prepared.json
      images/layout/
      deployment/charts/
      deployment/patches/
      tools/helm
      manifests/images-lock.json
      manifests/materials.json
      manifests/files.json
      reports/sources.json
      reports/timings.json
      logs/
    <id>.helm-build.json
    <id>.result.json
  output/<package-version>/
    bundle.tar.gz
    SHA256SUMS
    build-result.json
    bundle/
```

Command (use the actual configuration path printed by preparation):

```bash
python3 /srv/PXEye/offline-build/helm-bundle/build.py --config /srv/nico-build/prepared/ACTUAL-ID.helm-build.json
```

Confirmation:

```bash
ls /srv/nico-build/output/*/build-result.json
```

For `nico-prepared` inputs, step 2 imports the existing images, renders and packages Charts with relok8s; it performs no material image builds. A temporary Registry and the pinned relok8s tool are still needed. The input can move to another packaging machine without its preparation cache or containers; adjust local paths in the generated step-2 configuration. Material switches must match the prepared input. Final archive creation belongs to [step 2](../helm-bundle/README.md).
