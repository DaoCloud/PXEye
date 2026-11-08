# Deployment guide

**English** · [简体中文](deployment.zh-CN.md) · [Documentation](README.md)

PXEye currently runs as a single Kubernetes replica. The supplied manifest is a deployment skeleton, not an installer for NICo. Commands below are generic deployment examples; use your authorized context and namespace. In a shared environment, follow its resource-naming and namespace rules.

Use the [pre-installation checklist](pre-installation-checklist.md) alongside this guide: complete discovery prerequisites before the first Scout boot, then prepare the OS-writing checks through [Install your first server](getting-started.md).

## 1. Prepare dependencies

Provide a reachable NICo Core, DHCP and PXE service; compatible Linux `nico-admin-cli` and `grpcurl` binaries; a Core CA and client certificate/key; and a dedicated SSH key for acceptance. Match both binaries to the image CPU architecture. The existing physical path was validated on amd64; an arm64 image requires separate validation.

The PXEye runtime needs routes to Core and hardware controllers. Target hosts need routes to DHCP/relay, boot files, ISO, autoinstall data and installer callbacks. The UI being reachable does not establish these paths.

## 2. Build the image

From the repository root, supply compatible binaries as [build inputs](../bin/README.md):

```bash
install -m 0755 /path/to/nico-admin-cli bin/nico-admin-cli
install -m 0755 /path/to/grpcurl bin/grpcurl
make image IMAGE=pxeye:dev BASE_IMAGE=ubuntu:24.04
```

Load the image into the target cluster or push it to your authorized registry and update its manifest reference. PXEye does not download the NICo client automatically.

## 3. Configure the site and credentials

Copy [site.example.json](../examples/site.example.json) to a private `site.json`. Set the Core endpoint, site metadata, artifact paths and publication URLs. Initial devices and materials may be empty; add them through the UI. Additional execution defaults and baselines must be prepared for the chosen installation path.

Prepare a private secret directory with these exact filenames:

| File | Purpose |
| --- | --- |
| `auth.json` | Operator authentication: `{"password_sha256":"<SHA256 of the chosen password>"}`. |
| `ca.crt` | Trusted Core CA. |
| `client.crt`, `client.key` | Core mTLS identity. |
| `ssh_key`, `ssh_key.pub` | Dedicated private/public key for OS acceptance. |
| `known_hosts` | Trusted SSH baseline for paths requiring existing host access. |
| Configuration-referenced files | Legacy baseline or BMC credential files, when that path requires them. |

Do not use literal placeholders as credentials. Generate the password digest without echoing the password:

```bash
python3 - <<'PYTHON'
import getpass, hashlib, json, os
from pathlib import Path
os.umask(0o077)
Path('/private/pxeye-secrets/auth.json').write_text(json.dumps({
    'password_sha256': hashlib.sha256(getpass.getpass('Operator password: ').encode()).hexdigest()
}) + '\n')
PYTHON
```

Create `/private/pxeye-secrets` first and replace that path with your restricted local directory. Secrets are mounted read-only and must not be included in ConfigMaps, images or Git.

The generic manifest uses namespace `pxeye`. Select the appropriate context first, then create its configuration resources:

```bash
kubectl create namespace pxeye
kubectl -n pxeye create configmap pxeye --from-file=site.json=/private/site.json
kubectl -n pxeye create secret generic pxeye --from-file=/private/pxeye-secrets
kubectl apply -f deploy/kubernetes.yaml
kubectl -n pxeye rollout status deployment/pxeye --timeout=120s
```

Review storage classes, image availability, resource limits and namespace before applying. The manifest does not create NICo, an Ingress, a StorageClass or a DHCP relay.

## 4. Mount and publish materials

| Path | Mount | Contents |
| --- | --- | --- |
| `/config/site.json` | ConfigMap, read-only | Site and execution configuration. |
| `/secrets` | Secret, read-only | Authentication and trusted identities. |
| `/data` | Writable PVC | `console.sqlite3`, plans, tasks, logs and recovery files. |
| `/materials` | Writable persistent volume | Imported ISO and extracted boot artifacts. |
| `/iso-sources` | Optional read-only volume | Administrator-provided ISO source files. |
| `/tmp` | Bounded `emptyDir` | Temporary files. |

`os_library.directory` is the service's writable artifact path. `sources[].directory` must exist **inside the PXEye container**; a file on the Kubernetes node is invisible unless mounted. Add the optional `/iso-sources` volume/mount to use directory import.

`public_base_url` must deliver those same prepared files to target hosts. `verification_base_url` is the route PXEye uses to check delivery. Use NICo PXE's HTTP service to publish the materials: mount the same persistent files into NICo PXE and map their directory to its configured HTTP path. The supplied Deployment does not mount `/materials` into NICo PXE automatically. Also configure NICo's host-facing metadata and callback routes for task delivery.

Keep Scout discovery artifacts supplied by NICo available even when installing your own ISO.

## 5. Access and verify

For local inspection of the service:

```bash
kubectl -n pxeye port-forward service/pxeye 8080:80
```

Open `http://127.0.0.1:8080` and use the configured operator password. A port-forward only exposes the browser interface locally; it is not the PXE or artifact route used by hosts. A persistent deployment should use a controlled TLS entry point.

`GET /healthz` indicates HTTP process availability, not end-to-end NICo or hardware health. Use Site settings for the bounded component probes and inspect their check level.

## Storage and updates

The service reads `CONSOLE_CONFIG` (default `/config/site.json`), `CONSOLE_SECRETS` (`/secrets`), `CONSOLE_DATA` (`/data`), `CONSOLE_STATIC` (packaged `pxeye/web`) and `PORT` (`8080`). Run one replica with `Recreate`; a local file lock also prevents duplicate executors.

Stop accepting writes and wait for active or unresolved operations before replacement. Preserve both data and artifact PVCs. Back up SQLite consistently using its backup API or while the process is stopped; copying only the database file during WAL writes is insufficient. Include the associated configuration, task and identity files in a recovery backup. Replacing the image does not delete PVC history; deleting the PVC does.

The manifest uses a non-root UID, read-only root filesystem and restricted capabilities. See [Security](../SECURITY.md) for the current authentication envelope.
