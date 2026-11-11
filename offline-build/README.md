# Part 1: build the NICo offline installation bundle

**English** · [简体中文](README.zh-CN.md)

This document covers build inputs, the explicit file list, construction, verification and output layout. Deployment from the finished bundle is a separate document, generated at `docs/INSTALL.md` inside that bundle.

The supported recipe is NICo Core e703126e4 with the upstream nico-0.1.1 and cert-manager-v1.17.1 Charts, reviewed compatibility patches and platform prerequisites. It assembles existing images/materials; it does not compile NICo or build PXEye images. The recipe targets an existing Podman Kind cluster and single-replica Core, without REST/Temporal/Keycloak.

## 1. Build toolkit and prerequisites

**Goal:** copy the entire exported toolkit to `/srv/nico-build-kit` on the build machine. Run all commands in Bash there. The toolkit carries its templates and helpers; no original PXEye checkout is needed. Large inputs remain at the paths in the configuration.

```text
/srv/nico-build-kit/
├── README.md / README.zh-CN.md
├── build.py
├── build-config.json
├── build-config.example.json
├── source-revision.txt
├── FILE-PLAN.txt
├── deploy/
│   ├── bootstrap-kubernetes.yaml
│   ├── nico-cluster-permissions.yaml
│   ├── nico-platform/
│   └── offline-core/
└── tools/
    ├── import-oci-bundle.py
    └── offline-field/
```

The repository's maintenance entry points are this directory's `build.py`, `export.py` and `build-config.example.json`. The exporter reads a fixed Git commit; templates retain their existing repository paths as their single source. The old `tools/build-nico-offline-bundle.py` only forwards to this implementation.

**Commands — build machine:**

```bash
bash
set -euo pipefail
cd /srv/nico-build-kit
python3 --version
python3 -c 'import yaml; print("PyYAML", yaml.__version__)'
command -v patch helm
```

**Confirm:**

```bash
test -r build.py
test -r build-config.json
test -r source-revision.txt
python3 -m json.tool build-config.json >/dev/null
```

Requires Linux, Python3.11+/PyYAML, Helm3 and GNU patch. No Kubernetes/Registry access, Docker socket, skopeo, kubeconfig or login credentials are used by the builder. The space gate estimates twice the input size plus2GiB.

## 2. Configuration and exact contents

**Goal:** maintain one `build-config.json`. The file list has no wildcards and does not discover additional materials by scanning directories.

| Field | Meaning |
| --- | --- |
| `schema_version` | 2: explicit build plan |
| `build.source_bundle` | Pinned original charts, OCI and material root |
| `build.output_root` | Parent of new versioned output directories |
| `site` | Values used to generate the recipe: namespace, release, registry, Service IPs, HostInband; no passwords |
| `site.ui` / `site.bootstrap` | Additional OCI paths, original references, target tags and manifest digests |
| `files.base_image_manifests` | All23 original image references and manifest digests; extra images are declared by site |
| `files.inputs` | Each input's role, source root/path, final path, bytes and SHA256 |
| `files.generated` | Every generated file's final path |
| `files.repository` | 24 individually listed template/Chart/helper files shipped in the toolkit |
| `files.toolkit` | Sources and toolkit paths of the builder, bilingual documentation and example config |

`root=bundle` means relative to `build.source_bundle`. `root=site` is used by additional images; for example, `source=ui.archive` references `site.ui.archive`. Archive paths may be absolute or relative to the config file.

| Input group | Files | Handling / final location |
| --- | ---: | --- |
| 23-image base OCI collection | 1 | Copy unchanged to `images/nico-amd64.oci.tar` |
| UI and Vault bootstrap archives | 2 | Separate `images/pxeye-<tag>.oci.tar` files |
| Base image lock | 1 | Copy to `manifests/images-lock.json` |
| Raw upstream Charts | 2 | Copy cert-manager; patch and repackage NICo |
| Helm / nico-admin-cli | 2 | Copy executable binaries to `tools/` |
| Scout/iPXE materials | 20 | `boot/`, including x86_64/aarch64 |
| DPF/DOCA materials | 20 | `dpu/dpf-v26.4.0/`, including Charts, 3 OCIs and dpfctl |
| BlueField BFB and checksum | 2 | `http/nico/dpu/...` |
| Historical source/binary snapshots | 72 | `source/`, provenance rather than a maintained PXEye source tree |
| **Total inputs** | **122** | Verify sizes and checksums when used |
| **Generated files** | **28** | Recipe, values, platform Chart, Deployment/RBAC, config, helpers, deployment guide and manifests |
| **Total bundle files** | **150** | Inventory lists149 entries, excluding itself |

The base OCI retains its23 locked images, including historical material; deployment references come from the recipe. Eight macOS `._` sidecar files are excluded. Ubuntu installer ISOs and additional GPU/application packages are absent from this list. To include ordinary additional materials, explicitly add supported `boot/`, `dpu/`, `http/` or `source/` entries with matching source/target paths, bytes and SHA256. The eight core input roles and fixed generated paths follow recipe constraints.

Input-file SHA256 differs from image manifest digest. A patched Chart's final SHA256 also differs from its raw input: final hashes are in the recipe/file inventory.

**Commands — same Bash:**

```bash
python3 - <<'PY'
import json
from pathlib import Path
c=json.loads(Path('build-config.json').read_text())
print('Base materials:',c['build']['source_bundle'])
print('Output parent:',c['build']['output_root'])
print('UI archive:',c['site']['ui']['archive'])
print('Bootstrap archive:',c['site']['bootstrap']['archive'])
PY
python3 build.py --config build-config.json --plan | tee /tmp/nico-build-plan.txt
```

**Confirm:**

```bash
tail -1 /tmp/nico-build-plan.txt
```

The default plan reports `PLAN_COMPLETE inputs=122 generated=28 bundle_files=150`. Planning lists every source/action/final path without reading large input contents or building. Counts reflect edits to the material list.

## 3. Build and verify

**Goal:** use only declared inputs and compare all actual outputs to the declared plan.

**Commands — build machine, `/srv/nico-build-kit`, same Bash:**

```bash
VERSION="$(date -u +%Y%m%dT%H%M%SZ)"
OUTPUT_ROOT="$(python3 -c 'import json; print(json.load(open("build-config.json"))["build"]["output_root"])')"
OUTPUT="$OUTPUT_ROOT/$VERSION"
python3 build.py --config build-config.json --version "$VERSION"
```

The version is UTC. The source commit comes from `source-revision.txt`. Outputs must be new and outside the input/toolkit directories. Failures retain a `.building-*` directory; diagnose before trying a new version.

**Confirm — retain `OUTPUT` in the same Bash:**

```bash
cd "$OUTPUT"
sha256sum -c SHA256SUMS
python3 bundle/tools/verify-bundle.py bundle
python3 -m json.tool build-result.json
ls -lh bundle.tar.gz
```

Expect `BUILD_COMPLETE`, `bundle.tar.gz: OK` and `BUNDLE_VERIFIED`. Stages include `VERIFY_DECLARED_INPUTS`, `VERIFY_INPUT_OCI`, `COPY_VERIFIED_MATERIALS`, `ARCHIVE`, `HASH_ARCHIVE` and `VERIFY_ARCHIVE_CONTENTS`. The archive does not grow while hashing or reading it back.

Gates cover pinned raw Chart/OCI hashes, amd64 OCI blobs/closure, input sizes/checksums, all24 repository dependencies, four real Helm renders,13 single replicas, certificate CN/service identity, locked images, DNS/PXE/NTP consistency, exact output list and per-file tar readback. The reviewed importer and compatibility templates contain the previous field fixes.

## 4. Products and extracted layout

**Goal:** distinguish the toolkit, the unpacked materials and compressed delivery.

```text
<build.output_root>/<VERSION>/
├── bundle/
├── bundle.tar.gz
├── SHA256SUMS
└── build-result.json
```

The archive's top-level directory is `site.bundle_id`:

```text
<site.bundle_id>/
├── bundle.json
├── config/
│   ├── runtime.json
│   └── deployment-settings.json
├── deployment/
│   ├── deployment.json
│   ├── pxeye-bootstrap.yaml
│   ├── nico-cluster-permissions.yaml
│   ├── nico-target-namespace-rbac.yaml
│   ├── charts/
│   │   ├── cert-manager-v1.17.1.tgz
│   │   ├── nico-0.1.1.tgz
│   │   └── pxeye-nico-platform-0.1.0.tgz
│   ├── values/       # cert-manager/platform/vault/core
│   └── patches/      # migration/Core/platform/Service-IP fixes
├── images/
│   ├── nico-amd64.oci.tar
│   └── pxeye-<tag>.oci.tar  # two archives
├── manifests/
│   ├── images-lock.json
│   ├── deployment-images-lock.json
│   ├── materials-input-lock.json
│   ├── build-file-plan.json
│   ├── build-report.json
│   └── file-inventory.json
├── tools/
│   ├── helm
│   ├── nico-admin-cli
│   ├── import-oci-bundle.py
│   ├── import-pxeye-images.py
│   ├── prepare-auth.py
│   ├── deployment-client.py
│   ├── verify-core.py
│   └── verify-bundle.py
├── docs/INSTALL.md
├── boot/             # 20 declared files
├── dpu/              # 20
├── http/             # 2
└── source/           # 72 historical materials
```

`FILE-PLAN.txt` and `files.inputs/generated` name all150 files individually. `build-report.json` records rendering and source provenance; `build-file-plan.json` captures the selected inputs/output rules; `file-inventory.json` contains final hashes. Runtime credentials, kubeconfig, databases and Vault recovery materials are not collected from a running site.

**Commands — same Bash; reserve space for another complete directory:**

```bash
UNPACK="$OUTPUT-unpacked"
test ! -e "$UNPACK"
mkdir -p "$UNPACK"
tar -xzf "$OUTPUT/bundle.tar.gz" -C "$UNPACK"
BUNDLE_ID="$(python3 -c 'import json; print(json.load(open("/srv/nico-build-kit/build-config.json"))["site"]["bundle_id"])')"
```

**Confirm:**

```bash
python3 "$UNPACK/$BUNDLE_ID/tools/verify-bundle.py" "$UNPACK/$BUNDLE_ID"
find "$UNPACK/$BUNDLE_ID" -maxdepth 2 -type d | sort
```

## 5. Validation boundary

The earlier `1c732234` version built and verified a complete17GiB directory and12.16GiB archive. That evidence applies to the earlier layout. This version adds an explicit file plan and standalone toolkit, and drops eight sidecars; new sizes come from the new `build-result.json`.

Package validation and fresh-cluster installation are separate results. This pinned Core recipe does not certify ARM installation, full DPU management, external DHCP/PXE reachability or production HA merely because ARM/DPU materials are retained.


Reference: [NVIDIA Machine-a-Tron deployment](https://docs.nvidia.com/infra-controller/documentation/reference/development/machine-a-tron-deployment). The recipe follows pinned e703 sources and reviewed fixes, rather than assuming compatibility with the latest online version.
