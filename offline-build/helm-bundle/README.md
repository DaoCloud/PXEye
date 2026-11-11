# One-command PXEye / NICo Helm offline build

**English** · [简体中文](README.zh-CN.md)

This entry point converts the existing verified `kind=nico-materials` delivery into a relok8s delivery. It reuses 23 locked Core images, two PXEye images and prepared Charts, builds the selected material images, and produces one archive with inventories. After hash verification, each OCI archive is extracted once; the existing importer’s dir-transport approach accepts both OCI and Docker v2 manifests without changing digests, including CoreDNS. It does not need the deployment site's Registry, namespace, IP addresses or gateway.

## 1. Check the builder

Goal: use Linux x86_64, Python3.11+/PyYAML, a working Docker daemon and Helm3. Run all commands in the same Bash terminal on the builder. The example uses an existing checkout at `/srv/PXEye` and extracted materials at `/srv/nico-input/materials-bundle`.

Run:

```bash
bash
set -euo pipefail
export REPO=/srv/PXEye
export MATERIALS=/srv/nico-input/materials-bundle
export BUILD_WORK=/srv/nico-build
cd "$REPO"
uname -m
python3 -c 'import sys,yaml; assert sys.version_info >= (3,11); print(sys.version); print(yaml.__version__)'
docker version --format '{{.Server.Version}}'
helm version --short
mkdir -p "$BUILD_WORK"
```

Verify:

```bash
test -r "$MATERIALS/bundle.json"
test -r "$MATERIALS/manifests/file-inventory.json"
df -h "$BUILD_WORK"
python3 "$REPO/offline-build/helm-bundle/build.py" --help
```

Use the generic materials bundle, not a raw upstream tree or a site-specific bundle. Required free space is four times the extracted materials size plus2GiB, and twice the input size plus2GiB free in the local Unix-socket Docker storage. On first use, the script downloads relok8s0.5.4 and verifies its fixed release SHA256, and prepares a digest-pinned Registry image. An air-gapped builder must cache that Registry image and set `tools.relok8s` to an existing0.5.4 executable. The temporary anonymous HTTP build Registry listens only on a random127.0.0.1 port. No daemon configuration is changed.

## 2. Create the configuration once

Goal: edit local paths and material switches only. Existing configuration is never overwritten.

Run:

```bash
export CONFIG="$BUILD_WORK/helm-build.json"
python3 "$REPO/offline-build/helm-bundle/build.py" \
  --write-config "$CONFIG" \
  --materials-bundle "$MATERIALS" \
  --output-root "$BUILD_WORK/output"
```

Verify:

```bash
cat "$CONFIG"
python3 "$REPO/offline-build/helm-bundle/build.py" --config "$CONFIG" --plan
```

`materials_bundle` selects the verified input; `output_root`/`bundle_id` select output naming. `include.aarch64`, `include.bfb` and `include.apt` default to true. `tools` selects Docker, Helm and optionally an existing relok8s binary; null enables fixed-version tool preparation. File hashes come from the input inventory, and tool versions from `toolchain-lock.json`. Native x86_64 boot artifacts keep their existing locked image/loading path. Materials list both /payload and versioned PVC paths. The original x86_64 image is verified by image/layer digests; loose x86 files are not treated as verified contents of that image. No duplicate loose x86_64 payload, Ubuntu ISO, GPU software or DPF enablement is added.

## 3. Build with one command

Goal: verify inputs, start an isolated build Registry, import images, build data images, render five Charts/six modes, save relok8s intermediates, inventory and archive the complete delivery, and read every archived file back. No Kubernetes API or deployment is used.

Run:

```bash
python3 "$REPO/offline-build/helm-bundle/build.py" --config "$CONFIG"
```

For a fixed output version and a terminal log, use this group instead:

```bash
export VERSION="$(date -u +%Y%m%dT%H%M%SZ)"
export OUTPUT="$BUILD_WORK/output/$VERSION"
python3 "$REPO/offline-build/helm-bundle/build.py" \
  --config "$CONFIG" --version "$VERSION" \
  2>&1 | tee "$BUILD_WORK/build-$VERSION.log"
```

Verify after the fixed-version group:

```bash
test -r "$OUTPUT/build-result.json"
cat "$OUTPUT/build-result.json"
ls -lh "$OUTPUT/bundle.tar.gz"
```

Success prints `HELM_BUILD_COMPLETE <absolute output>`. Build sources must be committed. Only task-related source paths are checked; unrelated changes are preserved. Existing versions are not overwritten. The temporary Registry and per-run Docker tags are cleaned up on exit; successful builds remove Registry data/contexts and retain logs. Failures retain `.building-*` evidence; fix the cause and use a new version. No global Docker prune or deletion of previous deliveries occurs.

## 4. Verify the delivery

Goal: independently verify the compressed artifact and extracted directory.

Run:

```bash
cd "$OUTPUT"
sha256sum -c SHA256SUMS
python3 bundle/tools/verify.py bundle
export UNPACK="$OUTPUT-unpacked"
test ! -e "$UNPACK"
mkdir "$UNPACK"
tar -xzf bundle.tar.gz -C "$UNPACK"
```

Verify:

```bash
export BUNDLE_ID="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["bundle_id"])' "$CONFIG")"
python3 "$UNPACK/$BUNDLE_ID/tools/verify.py" "$UNPACK/$BUNDLE_ID"
cat "$UNPACK/$BUNDLE_ID/bundle.json"
```

Output layout:

```text
<output_root>/<version>/
  bundle.tar.gz
  SHA256SUMS
  build-result.json
  logs/                         # image/Registry/material build logs
  *-relok8s.log
  render/                       # validation evidence, not deployment inputs
  bundle/
    bundle.json
    charts/                     # pxeye/cert-manager/platform/core/materials
    relocation/                 # five real Chart intermediate bundles
    profiles/install-plan.json
    profiles/site-values.example.yaml
    manifests/file-inventory.json
    manifests/images-lock.json
    manifests/materials.json
    manifests/toolchain-lock.json
    manifests/build-report.json
    tools/helm
    tools/relok8s
    tools/verify.py
    tools/onsite/               # onsite import, OCI publication, frozen recipe and Helm phases
    docs/README.md
    docs/README.zh-CN.md
    docs/relok8s-LICENSE
```

The archive contains only `bundle/` contents, under `bundle_id` after extraction. Original OCI archives and loose material copies are not shipped again. Materials live in images, whose bytes live in the relok8s intermediates. Images shared by several real Charts may occur in multiple intermediates; cross-package deduplication is not claimed.

## 5. Build success boundaries

Goal: distinguish a complete transport artifact from a verified site installation.

Run:

```bash
python3 -m json.tool "$OUTPUT/bundle/bundle.json"
python3 -m json.tool "$OUTPUT/bundle/manifests/build-report.json"
```

Verify:

```bash
python3 - "$OUTPUT/bundle/bundle.json" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
assert d['kind']=='pxeye-nico-helm'
assert d['requires_site_configuration'] is True
assert d['multi_phase_oci_ui_ready'] is False
print('RELOK8S_DELIVERY_READY; ONSITE/UI_ADAPTER_PENDING')
PY
```

The onsite relocation→Helm OCI publication→PXEye multi-phase OCI adapter is a separate, unfinished integration. The new bundle explicitly declares `requires_site_configuration=true` and `multi_phase_oci_ui_ready=false`. Do not feed it to the old FieldBundles scanner or old OCI import commands: a relok8s intermediate is not `nico-amd64.oci.tar`. Generated Charts have render evidence only, not cold-install/upgrade/network validation. Validation addresses are not site configuration. Existing pinned e703 compatibility changes remain. No cluster/hardware/DHCP/certificate/database changes or regression/GPU workloads are performed.

References: [relok8s v0.5.4 source](https://github.com/vmware-tanzu/asset-relocation-tool-for-kubernetes/tree/v0.5.4), [Helm OCI](https://helm.sh/docs/v3/topics/registries/), [NVIDIA reference installation](https://docs.nvidia.com/infra-controller/documentation/getting-started/installation-options/reference-installation).

## Onsite helper

[Step-three scripts](../onsite/README.md) now provide relocation, Helm OCI publication, a frozen full-recipe upload compatible with existing PXEye, and ordered Helm CLI phases. Existing archives can use the small exported helper kit; new builds include tools/onsite. Automatic multi-phase OCI catalog ingestion in UI remains unimplemented. These scripts have not yet passed end-to-end fireseed deployment acceptance.
