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
export CONTEXT=kind-fireseed
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

Goal: explicitly select the Kubernetes context, Registry and release identity. The helper reads KIT/BUNDLE/CONFIG/WORK (namespace defaults to nico-system). CONTEXT uses an explicit argument/environment first, then an existing config, otherwise the unique kind- context from local kubeconfig; multiple candidates require --context, and the default context is never selected implicitly. Sourcing retains the selected CONTEXT/NICO_NAMESPACE in the caller. It discovers the existing Core release and Registry, creates a restore config and runs preflight. It performs only read-only cluster queries. Matching existing configuration is preserved and reused; mismatched inputs/TLS policy stop the helper without overwriting it.

Commands:

```bash
source "$KIT/prepare-site.sh"
```

Confirm:

```bash
python3 -m json.tool "$CONFIG"
```

Pass options directly to prepare-site.sh, such as `--skip-tls-verify` for explicitly accepted Registry certificate bypass or `--ca-file` for a private CA.

Omitting `--registry-url` discovers candidates from PXEye image authorities, private-IP/loopback image authorities in the selected namespace, and Kind's `kube-public/local-registry-hosting` declaration. The unique reachable Registry V2 endpoint is saved as `registry.url`, with evidence in `registry.discovery`. No subnet scan is performed. A 200/401 response must include the Registry V2 API header; 401 does not prove credentials or push access. HTTPS is preferred; certificate failures never silently downgrade to HTTP. Use `--ca-file /absolute/path/ca.crt` for a private CA or explicitly opt into `--skip-tls-verify`. Missing, unreachable or ambiguous candidates stop configuration creation; override with `--registry-url https://actual-endpoint`. A new cluster without discovery evidence also needs this override.

For authentication, use `--docker-config-directory /absolute/path/docker-auth` with an authenticated `config.json`. No passwords on command lines. Harbor project/account provisioning remains separate. Discovery does not change containerd or prove Kind-node image pulls.

Restore mode reads existing effective Helm values and DNS/PXE Service IPs and the NTP client Service (-nico-ntp-client) IP; the headless NTP Service is not a client address, retaining credentials/network settings while selecting the imported image versions. It does not silently choose running images from a source cluster. Configuration/override-file changes require a new work directory, except that recovery backup evidence can be supplied later.

prepare-site.sh is for restoring retained releases/data. For a new site use onsite.py write-config with explicit context/bundle/work paths, omit `--restore`, select a prefix and configure storage/network from the handover table. After setting DNS_IP, PXE_IP, NTP_IP, HOST_PREFIX and HOST_GATEWAY in the terminal:

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

Continue the remaining phases:

```bash
python3 "$KIT/onsite.py" install --config "$CONFIG" --phase all
```

Confirm:

```bash
kubectl --context kind-fireseed -n nico-system get deploy,sts,pods,jobs,pvc
cat "$WORK/timings.jsonl"
```

Completed phases are rechecked/skipped. Before Helm, existing ownership is checked; after Helm, previous PVC UIDs/PV bindings must remain intact. No automatic deletion or atomic rollback hides schema changes.

After inspecting Helm/Jobs/logs and fixing a failure, explicitly resume one phase:

```bash
python3 "$KIT/onsite.py" install --config "$CONFIG" --phase core --resume-failed
```

Replace core with the actual failed phase. Pending Helm operations are not forcibly unlocked. CLI uses a local site lock; legacy UI does not share it, so the operator must choose one execution path.

### Upload to existing PXEye

Goal: reuse the existing full-recipe upload without requiring a UI upgrade. After generating the recipe:

```bash
python3 "$KIT/onsite.py" ui-package --config "$CONFIG"
ls -lh "$WORK/ui-recipe.tar.gz"
```

Confirm:

```bash
python3 -m json.tool "$WORK/recipe-result.json"
```

Securely transfer the small package to the browser machine and upload it using the existing NICo offline full-recipe entry. Retain the frozen site/namespace/release defaults. The package can contain private effective Helm values, is mode600 and must not be committed/shared publicly.

This is a compatibility handoff: the CLI pulls/freezes OCI Charts; legacy UI consumes the full recipe. Automatic multi-phase catalog ingestion by UI is still unimplemented. A generated recipe can be packaged for UI immediately; backups are not a prerequisite.

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

The standalone backup utility remains available on demand; recipe generation, UI packaging and Core installation do not require it.

## relok8s 0.5.4 root image fields

This version can fail with `need path or selectors or both` when rewriting root scalar image fields. Build and onsite import share relocation.py: intermediate metadata uses temporary nested aliases, then onsite restores the original values shape. Image bytes remain unchanged. Existing deliveries use a derived working copy without modifying the original archive or inventory; no large-bundle rebuild is required. Resume import with the same configuration to verify/reuse completed Charts.

The image catalog distinguishes source_digest (input lock) from digest (the transferred manifest). relok8s may reserialize Docker manifests, so these can differ. The catalog derives unique digests from successful transfer evidence with destination-path checks; recipe image validation remains strict. An existing catalog is refreshed before freezing a new recipe without retransferring images.
