# Part 1: build reusable NICo offline materials

**English** · [简体中文](README.zh-CN.md)

Builds lock materials and versions without knowing the target Registry, IPs, gateway, Kubernetes context or node names. See [Part 2](CONFIGURE.md) for onsite initialization and deployment. The default namespace is `nico-system`, applied consistently during initialization.

The pinned profile contains NICo e703126e4, official nico-0.1.1/cert-manager-v1.17.1 Charts and reviewed compatibility patches: one Podman Kind node, single-replica Core, without REST/Temporal/Keycloak. This tool assembles existing images; it does not compile NICo or build PXEye images.

## 1. Prepare the toolkit and dependencies

Goal: use the Git repository's standalone directory or copy the entire toolkit to `/srv/nico-build-kit`. All build commands below run in Bash on the build machine, from that toolkit directory. A Git checkout's `deliverables/nico-offline-build` also works; `/srv` is optional.

Run:

```bash
bash
set -euo pipefail
cd /srv/nico-build-kit
python3 -c 'import sys,yaml; assert sys.version_info >= (3,11); print(sys.version); print("PyYAML",yaml.__version__)'
command -v helm
command -v patch
cp -n build-config.example.json build-config.json
vi build-config.json
```

Confirm:

```bash
python3 -m json.tool build-config.json >/dev/null
python3 -c 'import json; c=json.load(open("build-config.json")); assert c["schema_version"]==3 and "site" not in c; print(c["build"]); print(c["package"])'
```

Dependencies: Linux, Python3.11+/PyYAML, Helm3 and GNU patch. No cluster, Registry, kubeconfig, Docker socket or login credentials are used. Free-space checks require twice the input size plus 2GiB. Configuration can live anywhere outside Git; a specially named site directory is not required.

## 2. Declare inputs and inspect the complete plan

Goal: configure only information available on the build machine, with no site or cluster network settings.

| Field | Build input |
| --- | --- |
| `schema_version` | `3`: reusable materials |
| `build.source_bundle` | Locked source materials with raw Charts, 23-image OCI archive, boot and DPU files |
| `build.output_root` | Output parent; each version gets a new directory |
| `package.bundle_id` | Materials identity, independent of a deployment site |
| `package.ui`, `package.bootstrap` | Archive path, tag and manifest digest; source references are read from the archive by digest |
| `files.inputs` | Explicit source, role, target, bytes and SHA256 for every file; no globs |
| `files.base_image_manifests` | All 23 original image references and manifest digests |
| `files.repository`, `files.toolkit` | Individually listed templates, tools and documentation |
| `files.generated` | Every generated output path |

`root=bundle` reads relative to `build.source_bundle`; `root=package` reads the UI/bootstrap archive paths. Archive paths may be absolute or relative to the configuration file. Update tags/digests together with the archive sizes/file SHA256 in `files.inputs`. An archive's historical Registry reference records provenance; it does not select the deployment Registry.

The default plan contains122 inputs:3 OCI archives, the image lock,2 raw Charts, Helm/CLI,20 boot files,20 DPF/DOCA files,2 BFB files and72 historical materials. Eight macOS `._` sidecars, Ubuntu installation ISOs and extra GPU software are excluded. The NICo Chart is patched; other materials are copied against their locks. New files are never silently discovered and included.

Run:

```bash
python3 build.py --config build-config.json --plan > FILE-PLAN.current.txt
cat FILE-PLAN.current.txt
```

Confirm:

```bash
tail -1 FILE-PLAN.current.txt
```

The last line reports actual input/generated/total counts and input bytes; the default is122 inputs,50 generated files and172 final files. `--plan` checks lists and toolkit dependencies without reading large inputs or building. `FILE-PLAN.txt` is reproducible reference output, not another required input.

## 3. Build and verify

Goal: produce versioned materials independent of any deployment site. Validation addresses must never become an installable recipe.

Run in the same build-machine Bash and toolkit directory:

```bash
VERSION="$(date -u +%Y%m%dT%H%M%SZ)"
OUTPUT_ROOT="$(python3 -c 'import json; print(json.load(open("build-config.json"))["build"]["output_root"])')"
OUTPUT="$OUTPUT_ROOT/$VERSION"
python3 build.py --config build-config.json --version "$VERSION"
```

Confirm:

```bash
cd "$OUTPUT"
sha256sum -c SHA256SUMS
python3 bundle/tools/verify-bundle.py bundle
python3 -m json.tool build-result.json
ls -lh bundle.tar.gz
```

Require `BUILD_COMPLETE`, `bundle.tar.gz: OK` and `BUNDLE_VERIFIED`. Checks cover input hashes, OCI blobs/closure, four real Helm renders,13 single-replica workloads, certificate/service consistency, exact output paths and a per-file archive readback. Transient documentation-only values validate template composition. The delivery contains no `deployment/deployment.json` and has `recipe_ready=false`; initialize it onsite before using the UI.

The version directory must be new and outside source/toolkit directories. Failures retain `.building-*` for diagnosis; use a new version after resolving the cause. Hashing and archive readback may run without file growth.

## 4. Output and extracted layout

Goal: distinguish the toolkit, reusable materials and site-generated output.

```text
<build.output_root>/<VERSION>/
├── bundle/
├── bundle.tar.gz
├── SHA256SUMS
└── build-result.json

<package.bundle_id>/
├── bundle.json                   # kind=nico-materials; recipe_ready=false
├── config/site-config.example.json
├── deployment/
│   ├── charts/                   # 3 prepared Charts
│   └── patches/                  # 4 recorded patches
├── deployment-kit/
│   ├── configure.py
│   ├── generic.py
│   ├── build.py
│   ├── site-config.example.json
│   ├── deploy/
│   └── tools/
├── images/                       # original23-image OCI plus2 PXEye archives
├── manifests/                    # locks, plan, report and full file inventory
├── tools/                        # Helm, CLI and verifier
├── docs/CONFIGURE.md
├── docs/CONFIGURE.zh-CN.md
├── boot/
├── dpu/
├── http/
└── source/
```

Run in the same shell with `OUTPUT` retained; extraction needs additional space:

```bash
UNPACK="$OUTPUT-unpacked"
test ! -e "$UNPACK"
mkdir -p "$UNPACK"
tar -xzf "$OUTPUT/bundle.tar.gz" -C "$UNPACK"
find "$UNPACK" -mindepth 1 -maxdepth 1 -type d
```

Confirm:

```bash
MATERIALS="$(find "$UNPACK" -mindepth 1 -maxdepth 1 -type d)"
python3 "$MATERIALS/tools/verify-bundle.py" "$MATERIALS"
python3 "$MATERIALS/deployment-kit/configure.py" --help
```

`--plan` and the final `manifests/file-inventory.json` list every file. Passwords, kubeconfigs, runtime databases and Vault recovery materials are excluded.

## 5. Reuse an existing large bundle

Goal: avoid rebuilding large archives when only site addresses change.

The onsite tool accepts a complete Core bundle produced by the previous `1c732234` builder. Preserve its original `bundle.tar.gz` and checksums; use its extracted `bundle/` with the new `configure.py`. See [Part 2](CONFIGURE.md). Arbitrary raw/old directories without the supported build report and complete inventory are rejected.

Initialization verifies the materials, hard-links large files into a new directory on the same filesystem and regenerates only small configuration/tools/inventory. It does not compile, download, copy or recompress large images. Hard-link failure stops the operation instead of falling back to large copies. Edit configuration only; treat linked image/boot materials as immutable. Pods mount them read-only.

A single new `bundle.tar.gz` that includes the new initialization tools must be reassembled with schema3; existing image bytes are still reused. Changed image versions/material digests also require a new build. Changed onsite Registry/IP/gateway settings need only a new site initialization, not another large archive.

This change updates the tools. The previous12.16GiB build is not evidence that schema3 has been fully rebuilt or cold-installed. Physical DHCP/Relay/HTTP Boot, ARM/DPU and production HA require separate validation.

Reference: [NVIDIA Machine-a-Tron deployment](https://docs.nvidia.com/infra-controller/documentation/reference/development/machine-a-tron-deployment). Capabilities follow the pinned e703 source and recipe.
