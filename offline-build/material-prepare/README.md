# Step 1: prepare offline materials

**English** · [简体中文](README.zh-CN.md) · [Overview](../README.md)

**Goal: produce an independent prepared directory. Run on the builder.** No Kubernetes access, deployment or site addresses are needed.

## Stages

| Stage | Action | Key point |
| --- | --- | --- |
| Verify inputs | Check locked archives, Charts and payload hashes | Explicit versions; no running-cluster image discovery |
| Prepare images | Import Core, PXEye and tooling images | 13 input images in the current recipe |
| Build materials | Build optional ARM64 Scout, APT and BFB images | 16 total with all options; reuse valid caches |
| Validate | Patch Charts, verify OCI and material payloads | No NICo recompilation; native x86 payload validation is limited to image layers |
| Publish | Write inventories, provenance, logs and step-2 configuration | Copy the complete next command from terminal output |

## Configure once, run one script

Goal: select original inputs, outputs and material switches. See [requirements](../README.md#requirements-and-paths). The repository is `/srv/PXEye`. Run preparation commands only once:

```bash
mkdir -p /srv/nico-build
test ! -e /srv/nico-build/build-config.json &&
cp /srv/PXEye/offline-build/material-prepare/build-config.example.json /srv/nico-build/build-config.json &&
${EDITOR:-vi} /srv/nico-build/build-config.json
```

Maintain only `build-config.json`:

| Setting | Meaning |
| --- | --- |
| input_root / archives | Original Charts/payloads root and three image archive paths |
| output_root / cache_directory | Separate prepared output and cache, outside source/input trees |
| package_output_root | Step-2 delivery output root |
| include | ARM64 Scout, APT and BFB switches |
| recipe / tools | Maintained locked recipe and local tools; provide cached relok8s for offline packaging |

Command:

```bash
python3 /srv/PXEye/offline-build/material-prepare/build.py --config /srv/nico-build/build-config.json
```

Confirmation: `MATERIAL_PREPARE_COMPLETE`, `HELM_BUILD_CONFIG` and `NEXT_COMMAND`. Execute the complete command after `NEXT_COMMAND` to enter [step 2](../helm-bundle/README.md). Do not create another packaging configuration manually.

## Outputs and recovery

```text
output_root/
  <id>/
    prepared.json
    images/layout/
    deployment/
    tools/helm
    manifests/            # image lock, material files, complete inventory
    reports/              # sources and timings
    logs/
  <id>.helm-build.json
  <id>.result.json
```

Fix failures and rerun the original command. Staging/logs remain; valid material caches or complete prepared output are verified and reused. This step does not use the stage-journal format of steps 2–3 and does not create the final delivery archive.

The prepared directory can move independently to another packaging machine. Adjust local paths in the generated configuration; material switches must match. See the [overview](../README.md) for profile boundaries. Generic NICo source compilation is not supported.
