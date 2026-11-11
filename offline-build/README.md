# Part 1: how I build NICo offline materials

**English** · [简体中文](README.zh-CN.md)

Onsite entry point for the three-step workflow: [Step 3: one-config deployment and recovery](onsite/README.md).
I perform these steps on a Linux build machine. Building locks materials and versions without knowing the target Registry, IPs, gateway or Kubernetes details. Onsite initialization and deployment are covered in [Part 2](CONFIGURE.md). The pinned profile contains NICo e703126e4, official Charts and compatibility patches for one Podman Kind node and single-replica Core, without REST/Temporal/Keycloak. It assembles existing images; it does not compile NICo or build PXEye images.

The preferred flow is [step 1: prepare materials with one script](material-prepare/README.md), followed by [step 2: Helm/relok8s packaging](helm-bundle/README.md). Step 1 generates the packaging configuration and does not require the legacy generic bundle described below. The schema4 flow remains available for historical artifacts.

## Step 1: I check the build machine

Goal: confirm the host, dependencies and available storage before building. All commands run as root in the same Bash terminal on the build machine, initially from any directory. The three input paths must contain prepared materials. Set the same environment variables before this section to override the default paths.

Run:

```bash
bash
set -euo pipefail
export BUILD_WORK="${BUILD_WORK:-/srv/nico-build}"
export SOURCE_BUNDLE="${SOURCE_BUNDLE:-/srv/nico-input/base-bundle}"
export UI_ARCHIVE="${UI_ARCHIVE:-/srv/nico-input/pxeye-ui.oci.tar}"
export BOOTSTRAP_ARCHIVE="${BOOTSTRAP_ARCHIVE:-/srv/nico-input/pxeye-bootstrap.oci.tar}"
hostname
uname -m
python3 -c 'import sys,yaml; assert sys.version_info >= (3,11); print(sys.version); print("PyYAML",yaml.__version__)'
git --version
helm version --short
patch --version | head -1
```

Confirm:

```bash
test -d "$SOURCE_BUNDLE"
test -f "$UI_ARCHIVE"
test -f "$BOOTSTRAP_ARCHIVE"
mkdir -p "$BUILD_WORK"
df -h "$BUILD_WORK"
df -i "$BUILD_WORK"
```

I need Linux, Python3.11+/PyYAML, Git, Helm3 and GNU patch. Default materials are about16GiB. The build requires twice the selected input size plus2GiB free; extraction in step6 needs another full material directory. No Kubernetes/Registry access, kubeconfig, Docker socket or credentials are required.

## Step 2: I obtain the toolkit and record its version

Goal: use the standalone Git directory and record its real source revision. BUILD_WORK/PXEye must be new; never overwrite another checkout. Run in the same shell.

Run:

```bash
test ! -e "$BUILD_WORK/PXEye"
git clone --branch main https://github.com/DaoCloud/PXEye.git "$BUILD_WORK/PXEye"
export KIT="$BUILD_WORK/PXEye/deliverables/nico-offline-build"
cd "$KIT"
```

Confirm:

```bash
git -C "$BUILD_WORK/PXEye" rev-parse HEAD
cat "$KIT/source-revision.txt"
test -r "$KIT/build.py"
test -r "$KIT/materials-lock.json"
python3 "$KIT/build.py" --help
```

The toolkit can also be copied as a complete directory; set KIT to its absolute path in that case. source-revision.txt pins the scripts/templates export commit, which may differ from the Git delivery commit containing that export.

## Step 3: I create a small path-and-options configuration

Goal: maintain16 configuration lines without copying per-file hashes or site settings. Keep it outside the toolkit and reuse it for subsequent builds. The command refuses to overwrite an existing configuration.

Run:

```bash
export CONFIG="$BUILD_WORK/build-config.json"
python3 "$KIT/build.py" --write-config "$CONFIG" \
  --source-bundle "$SOURCE_BUNDLE" \
  --output-root "$BUILD_WORK/output" \
  --ui-archive "$UI_ARCHIVE" \
  --bootstrap-archive "$BOOTSTRAP_ARCHIVE"
```

Confirm:

```bash
cat "$CONFIG"
python3 - "$KIT" <<'PY'
import json,sys
from pathlib import Path
lock=json.loads((Path(sys.argv[1])/'materials-lock.json').read_text())
print('材料配方：',lock['profile'])
print('固定镜像：',json.dumps(lock['images'],ensure_ascii=False))
PY
```

I edit only build.source_bundle, build.output_root, package.bundle_id, package.ui_archive, package.bootstrap_archive and the include flags. include.dpu defaults to true for DPF/DOCA/BFB materials; this is independent of the fixed Core23-image archive. include.history defaults to false, excluding72 historical source backups. Enable it only for provenance.

The separate machine-managed materials-lock.json holds file lists, sizes, SHA256, image tags/digests and template lists. Ordinary builds do not edit the lock. The next step lists all selected files. FILE-PLAN.txt is generated reference output; it does not need copying from elsewhere. Equal source/target paths preserve the relative layout and do not duplicate a file.

## Step 4: I inspect the plan and inputs

Goal: see exactly what will be delivered and detect missing inputs before a long build. Run in the same terminal.

Run:

```bash
python3 "$KIT/build.py" --config "$CONFIG" --plan > "$BUILD_WORK/FILE-PLAN.txt"
cat "$BUILD_WORK/FILE-PLAN.txt"
python3 "$KIT/build.py" --config "$CONFIG" --check-inputs
```

Confirm:

```bash
tail -1 "$BUILD_WORK/FILE-PLAN.txt"
```

The default plan reports inputs=50 generated=52 bundle_files=102, with no source/ backups. Enabling history selects122 inputs and174 final files; disabling dpu removes22 material files. macOS ._ sidecars, Ubuntu ISOs and extra GPU software are excluded. INPUTS_READY covers selected input existence/sizes, mandatory hashes and toolkit lists. The build still validates every input SHA and OCI blob/closure. Original Registry references are read from extra archives by locked digest; I do not have to supply those historical addresses.

## Step 5: I build a new version

Goal: create new output without changing source materials, previous bundles or running services. Run in the same terminal.

Run:

```bash
export VERSION="$(date -u +%Y%m%dT%H%M%SZ)"
export OUTPUT="$BUILD_WORK/output/$VERSION"
python3 "$KIT/build.py" --config "$CONFIG" --version "$VERSION" \
  2>&1 | tee "$BUILD_WORK/build-$VERSION.log"
```

Confirm:

```bash
test -f "$OUTPUT/build-result.json"
python3 -m json.tool "$OUTPUT/build-result.json"
ls -lh "$OUTPUT/bundle.tar.gz"
```

I require BUILD_COMPLETE. Stages are input checks, OCI verification, material copying, four real Helm renders, complete directory verification, ARCHIVE, HASH_ARCHIVE and VERIFY_ARCHIVE_CONTENTS. Files may stop growing while hashing/readback runs; I do not restart an active build. Failures retain a .building-* directory; inspect the cause and use a new version after fixing it. Temporary validation inputs never become an installable recipe: materials have recipe_ready=false and no deployment/deployment.json. No cluster resources are modified.

## Step 6: I independently verify and extract

Goal: verify the compressed delivery, full inventory and extracted toolkit rather than trusting a completion message. Run in the same terminal.

Run:

```bash
cd "$OUTPUT"
sha256sum -c SHA256SUMS
python3 bundle/tools/verify-bundle.py bundle
export UNPACK="$OUTPUT-unpacked"
test ! -e "$UNPACK"
mkdir -p "$UNPACK"
tar -xzf "$OUTPUT/bundle.tar.gz" -C "$UNPACK"
export BUNDLE_ID="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["package"]["bundle_id"])' "$CONFIG")"
export MATERIALS="$UNPACK/$BUNDLE_ID"
```

Confirm:

```bash
python3 "$MATERIALS/tools/verify-bundle.py" "$MATERIALS"
python3 "$MATERIALS/deployment-kit/configure.py" --help
find "$MATERIALS" -maxdepth 2 -type d | sort
```

I require bundle.tar.gz: OK, two BUNDLE_VERIFIED messages and the onsite initializer help. The default has102 final files; inventory lists101 because it excludes itself. These checks verify delivery integrity, not a cold-cluster install or physical DHCP/Relay/HTTP Boot.

## Step 7: I record the delivery and handoff

Goal: retain the version, checksums and paths so the next user does not have to guess them. Run in the same terminal.

Run:

```bash
cat "$OUTPUT/SHA256SUMS"
cat "$OUTPUT/build-result.json"
du -sh "$OUTPUT/bundle" "$OUTPUT/bundle.tar.gz" "$MATERIALS"
```

Confirm:

```bash
test -r "$MATERIALS/docs/CONFIGURE.zh-CN.md"
test -r "$MATERIALS/config/site-config.example.json"
```

Passwords, kubeconfigs, runtime databases and Vault recovery materials are excluded. source/ appears only when include.history=true; archived UI sources are not executed. The running application comes from the locked PXEye image.

```text
<BUILD_WORK>/
├── PXEye/deliverables/nico-offline-build/
├── build-config.json
├── FILE-PLAN.txt
├── build-<VERSION>.log
└── output/
    ├── <VERSION>/
    │   ├── bundle/
    │   ├── bundle.tar.gz
    │   ├── SHA256SUMS
    │   └── build-result.json
    └── <VERSION>-unpacked/<BUNDLE_ID>/
        ├── bundle.json
        ├── config/site-config.example.json
        ├── deployment/charts/
        ├── deployment/patches/
        ├── deployment-kit/
        ├── images/
        ├── manifests/
        ├── tools/
        ├── docs/CONFIGURE.zh-CN.md
        ├── docs/CONFIGURE.md
        ├── boot/
        ├── dpu/
        └── http/
```

## Material updates and existing large bundles

Ordinary builds skip this section. After changing selected materials, maintainers can generate a separate, reviewable lock update rather than hand-copying hashes or overwriting the shipped lock.

Run:

```bash
python3 "$KIT/refresh-lock.py" --config "$CONFIG" \
  --output "$BUILD_WORK/materials-lock.updated.json"
diff -u "$KIT/materials-lock.json" "$BUILD_WORK/materials-lock.updated.json"
```

diff exits1 when differences exist; this is expected. Review/replace the lock in the maintained source, commit it, then export a new toolkit. Unselected optional records retain their existing locks; unknown files are never silently discovered. Changed fixed Core images or raw Charts require a new reviewed compatibility profile, not a hash-only override.

A supported previous complete Core builder bundle can be reused with the new configure.py without rebuilding the original archive. On the same filesystem, initialization hard-links large materials and writes only new site files. Reassemble a compressed delivery only when it must include the new tools; do not recompile images. Registry/IP/gateway changes need a new site initialization directory; see [Part 2](CONFIGURE.md).

Reference: [NVIDIA Machine-a-Tron deployment](https://docs.nvidia.com/infra-controller/documentation/reference/development/machine-a-tron-deployment). The delivery format is project-specific, not an official NVIDIA package format; capabilities follow the pinned e703 source and recipe.
