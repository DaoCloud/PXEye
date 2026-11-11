# Step three: import and install a Helm offline delivery

[简体中文](README.zh-CN.md)

This helper consumes `kind=pxeye-nico-helm`, not the legacy multi-image OCI archive. It verifies/unpacks, relocates images with the bundled relok8s 0.5.4, publishes rewritten Charts with Helm OCI, freezes a complete deployment recipe and runs ordered Helm phases. It does not build images, change containerd, discover devices, call Redfish, or install a host OS. The current profile covers amd64 single-node Core, not REST.

This version has not yet passed end-to-end fireseed deployment acceptance. Helm completion is separate from strict Core mTLS, boot HTTP, physical DHCP/Relay and OS installation checks.

## 1. Prepare the helper

Goal: use Linux amd64, Python 3.11+ with PyYAML, kubectl and the binaries in the delivery. All fireseed commands use one Bash terminal. Paths/context/Registry/release below are examples; replace site values before execution.

Commands on the development checkout root (an existing delivery can use this small kit without rebuilding large images):

```bash
python3 offline-build/onsite/export.py --output /tmp/nico-onsite-tools
ls -lh /tmp/nico-onsite-tools.tar.gz /tmp/nico-onsite-tools.tar.gz.sha256
```

Copy those two files to the fireseed `/srv/nico/`. New deliveries include `tools/onsite/` directly.

Commands on the fireseed:

```bash
bash
set -euo pipefail
cd /srv/nico
sha256sum -c nico-onsite-tools.tar.gz.sha256
test ! -e /srv/nico/nico-onsite-tools
tar -xzf nico-onsite-tools.tar.gz

```

Confirm:

```bash
cd /srv/nico/nico-onsite-tools
sha256sum -c SHA256SUMS
cd /srv/nico
```

Python/PyYAML must already be installed; this script does not invoke pip at an air-gapped site.

## 2. Verify and unpack

Goal: verify the outer SHA and every delivered file, using a new extraction directory.

Commands:

```bash
bash /srv/nico/nico-onsite-tools/tools/prepare-bundle.sh
source /srv/nico/onsite/environment.sh
```

Confirm:

```bash
python3 -m json.tool "$BUNDLE/bundle.json"
test -f "$BUNDLE/profiles/install-plan.json"
```

The helper checks Python3.11+/PyYAML, verifies/unpacks the archive and writes KIT/BUNDLE/CONFIG/WORK, then prints `BUNDLE_READY`. The second command activates those variables in the current shell. A complete matching extraction is verified and reused; incomplete or mismatched output is never overwritten. Options: `--directory /srv/nico` and `--output /srv/nico/releases/field-import-02`. Source-checkout usage requires `--directory`. Unsafe paths, links, special files and duplicate members are rejected. Expansion is bounded by available space. Do not infer the version from archive size.

## 3. Create one site config

Goal: explicitly select the Kubernetes context, Registry and release identity. The following example restores existing releases/PVCs; replace the example Registry/context/prefix with the real site values.

Commands:

```bash
python3 "$KIT/onsite.py" write-config \
  --output "$CONFIG" \
  --bundle "$BUNDLE" \
  --work-directory "$WORK" \
  --context kind-fireseed \
  --namespace nico-system \
  --release-prefix previous-nico-release \
  --registry-url https://registry.example.invalid:443 \
  --restore
```

Confirm:

```bash
python3 -m json.tool "$CONFIG"
```

Use the actual protocol (`http://` is different from disabling HTTPS verification). A private CA can be configured with `--ca-file /absolute/path/ca.crt`; explicit Registry verification bypass uses `--skip-tls-verify`. For authentication, use `--docker-config-directory /absolute/path/docker-auth` containing an already authenticated `config.json`. No passwords on command lines. Harbor project/account provisioning is outside this helper.

Restore mode reads existing effective Helm values and DNS/PXE/NTP Service IPs, retaining credentials/network settings while selecting the imported image versions. It does not silently choose running images from a source cluster. Configuration/override-file changes require a new work directory, except that recovery backup evidence can be supplied later.

For a new site omit `--restore`, select a prefix and configure storage/network from the handover table. After setting DNS_IP, PXE_IP, NTP_IP, HOST_PREFIX and HOST_GATEWAY in the terminal:

```bash
python3 - "$CONFIG" <<'PY'
import json,os,sys
p=sys.argv[1]; c=json.load(open(p))
c['service_ips']={k:os.environ[v] for k,v in [('dns','DNS_IP'),('pxe','PXE_IP'),('ntp','NTP_IP')]}
c['host_network']={'name':'host_boot','prefix':os.environ['HOST_PREFIX'],'gateway':os.environ['HOST_GATEWAY'],'mtu':1500}
with open(p,'w') as f: json.dump(c,f,indent=2)
PY
```

Do not run this network update for restore unless intentionally replacing that plan. `publish_materials` defaults false; x86 boot artifacts retain the existing loading path. Enabling the materials HTTP service does not automatically configure Core/Scout ARM64/BFB consumer URLs or physical reachability.

### Cold backup for stopped backends

Goal: when old NICo workloads have already been removed, copy stopped Postgres/Vault volumes before restarting them. Only confirmed Kind hostPath/local PVs are supported; no workloads are stopped automatically.

Commands (replace the node with the confirmed Kind container/node):

```bash
python3 "$KIT/onsite.py" backup --config "$CONFIG" \
  --engine podman --node fireseed-control-plane
```

Confirm:

```bash
python3 - "$CONFIG" <<'PY'
import json,sys
from pathlib import Path
c=json.load(open(sys.argv[1])); p=Path(c['data_backup_directory'])
print(p); print((p/'backup.json').read_text())
PY
```

Expect COLD_BACKUP_COMPLETE. The helper validates PVC/PV/node association, requires no backend Pod/controller references before/after copying, streams tar archives from the node, records hashes and updates data_backup_directory. It does not change volume contents or test restoration. If unavailable, use a real storage/database backup procedure instead. A completed cold backup removes the need to fill an external backup path in section6.

## 4. Import images and publish Charts

Goal: validate bundle/context (reuse full verification while input file metadata is unchanged within the run), relocate the intermediate bundles, publish content-addressed OCI Charts and pull them back for verification. No NICo workloads are started.

Commands:

```bash
python3 "$KIT/onsite.py" preflight --config "$CONFIG"
python3 "$KIT/onsite.py" import --config "$CONFIG"
```

Confirm:

```bash
python3 -m json.tool "$WORK/catalog.json"
test -f "$WORK/state.json"
```

Expect `IMPORT_COMPLETE`. Rerun import with the same configuration to reuse completed Chart steps. No force-push is used. Catalog records source/image mappings and the relok8s transfer boundary, not kubelet pull acceptance.

Since relok8s 0.5.4 has no TLS options, a temporary streaming proxy binds only a random loopback port and uses the configured upstream HTTP/TLS policy. No system daemon config changes. The helper replaces this transient endpoint throughout vendored Charts and restores dependency conditions stripped by relok8s. It closes the port and removes temporary auth on exit.

Anonymous, inline Docker auths and same-origin Bearer authentication are supported. Credential-helper aliases and cross-host upload redirects fail explicitly. External token endpoints still require working connectivity/TLS. Kind-node image pulls require their own correctly configured authentication/TLS.

## 5. Freeze a deployment recipe

Goal: pull OCI Charts, check their manifest/archive hashes, derive values, render and verify container images against the imported lock.

Commands:

```bash
python3 "$KIT/onsite.py" recipe --config "$CONFIG"
```

Confirm:

```bash
python3 -m json.tool "$WORK/recipe/deployment.json"
ls -lh "$WORK/recipe/charts/" "$WORK/recipe/values/"
```

Expect `RECIPE_READY`. Additional reviewed phase values can be referenced by config.phase_values; file content hashes participate in run identity. Existing recipe output is never regenerated in place. Restore rejects automatic discovery/firmware policy in the resulting Core values. Frozen values are not an approval to migrate data.

## 6. Choose CLI or UI, never both concurrently

### Restore through CLI

Goal: restore infrastructure before Core migrations, retaining release ownership and persistent data.

Commands:

```bash
python3 "$KIT/onsite.py" install --config "$CONFIG" --phase cert-manager
python3 "$KIT/onsite.py" install --config "$CONFIG" --phase platform
python3 "$KIT/onsite.py" install --config "$CONFIG" --phase vault
```

Confirm with the actual site context:

```bash
kubectl --context kind-fireseed -n nico-system get pods,pvc
"$BUNDLE/tools/helm" --kube-context kind-fireseed -n nico-system list
```

If the previous cold backup completed, directly run install --phase all; no external backup-path update is needed. Otherwise prepare actual recoverable Postgres/Vault backups before Core migrations. Set DATA_BACKUP_DIR to that directory, then run:

```bash
python3 - "$CONFIG" <<'PY'
import json,os,sys
from pathlib import Path
p=sys.argv[1]; c=json.load(open(p)); backup=Path(os.environ['DATA_BACKUP_DIR']).resolve()
assert backup.is_dir() and any(backup.iterdir()), 'Missing/empty actual recovery backup'
c['data_backup_directory']=str(backup)
with open(p,'w') as f: json.dump(c,f,indent=2)
PY
python3 "$KIT/onsite.py" install --config "$CONFIG" --phase all
```

Confirm:

```bash
kubectl --context kind-fireseed -n nico-system get deploy,sts,pods,jobs,pvc
cat "$WORK/timings.jsonl"
```

Completed phases are rechecked/skipped. Backup gating only checks the operator-provided directory exists/nonempty; it does not prove recoverability. Metadata snapshots are not data backups. Before Helm, existing ownership is checked; after Helm, previous PVC UIDs/PV bindings must remain intact. No automatic deletion or atomic rollback hides schema changes.

After inspecting Helm/Jobs/logs and fixing a failure, explicitly resume one phase:

```bash
python3 "$KIT/onsite.py" install --config "$CONFIG" --phase core --resume-failed
```

Replace core with the actual failed phase. Pending Helm operations are not forcibly unlocked. CLI uses a local site lock; legacy UI does not share it, so the operator must choose one execution path.

### Upload to existing PXEye

Goal: reuse the existing full-recipe upload without requiring a UI upgrade. After actual backup configuration:

```bash
python3 "$KIT/onsite.py" ui-package --config "$CONFIG"
ls -lh "$WORK/ui-recipe.tar.gz"
```

Confirm:

```bash
python3 -m json.tool "$WORK/recipe-result.json"
```

Securely transfer the small package to the browser machine and upload it using the existing NICo offline full-recipe entry. Retain the frozen site/namespace/release defaults. The package can contain private effective Helm values, is mode600 and must not be committed/shared publicly.

This is a compatibility handoff: the CLI pulls/freezes OCI Charts; legacy UI consumes the full recipe. Automatic multi-phase catalog ingestion by UI is still unimplemented. Restore can generate CLI files before backups, but withholds UI packages until backup evidence is configured.

### Bootstrap PXEye on a new site only

Goal: start UI with its own Chart when no existing PXEye needs preservation.

Commands:

```bash
python3 "$KIT/onsite.py" bootstrap --config "$CONFIG"
```

Confirm:

```bash
kubectl --context kind-fireseed -n nico-system get deploy,pods,svc
```

The Chart supplies ConfigMap, auth Secret, PVCs, ServiceAccount/RBAC and Service. Default release is namespace-pxeye; config.pxeye_release/pxeye_values can override it. The generated password is held in the release Secret, never printed in routine logs. Existing objects owned outside this Helm release are rejected, not automatically adopted. Existing non-Helm PXEye migration is a separate task.

## 7. Evidence and limits

Goal: locate continuation information.

Commands:

```bash
ls -lh "$WORK/catalog.json" "$WORK/state.json" "$WORK/timings.jsonl"
ls "$WORK/logs" "$WORK/private"
```

Confirm:

```bash
python3 -m json.tool "$WORK/state.json"
```

logs holds import command results; private holds effective old values, rendered objects, metadata snapshots and Helm installation output. timings.jsonl records command durations/exit codes. Existing archives/images/PVCs are not removed. `HELM_PHASES_COMPLETE` is not a claim of strict mTLS, physical boot or OS installation success.
