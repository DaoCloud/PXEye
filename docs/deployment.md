# Deployment guide

**English** · [简体中文](deployment.zh-CN.md) · [Documentation](README.md)

PXEye currently runs as a single Kubernetes replica. This guide connects an existing NICo site; for a new control plane, use [Start PXEye and deploy NICo](nico-deployment.md). Commands below are generic deployment examples; use your authorized context and namespace. In a shared environment, follow its resource-naming and namespace rules.

Use the [pre-installation checklist](pre-installation-checklist.md) alongside this guide: complete discovery prerequisites before the first Scout boot, then prepare the OS-writing checks through [Install your first server](getting-started.md).

## 1. Prepare dependencies

Provide a reachable NICo Core, DHCP and PXE service; compatible Linux `nico-admin-cli`, `grpcurl` and Helm 3 binaries; a Core CA and client certificate/key; and a dedicated SSH key for acceptance. Match both binaries to the image CPU architecture. The existing physical path was validated on amd64; an arm64 image requires separate validation.

The PXEye runtime needs routes to Core and hardware controllers. Target hosts need routes to DHCP/relay, boot files, ISO, autoinstall data and installer callbacks. The UI being reachable does not establish these paths.

## 2. Build the image

Prepare the [external tools](../bin/README.md) at the repository root: `bin/nico-admin-cli`, `bin/grpcurl`, and `bin/helm`. Supply Linux binaries for the target image architecture. The standard Dockerfile requires reachable Ubuntu and Python package sources; offline material packaging does not make the PXEye build offline.

### Image name and tag

The default repository is `mmzhou-os-install-console`. Tags follow `<pyproject.toml version>-<YYYYMMDDHHmm>`, using `Asia/Shanghai` (UTC+8), to the minute; for example, `mmzhou-os-install-console:0.22.16-202611121830`. The application version excludes the timestamp. OCI labels record the full Git commit in `org.opencontainers.image.revision` and the application version in `org.opencontainers.image.version`. Retain existing SHA-based tags unchanged.

### Build and inspect

Run at the PXEye repository root on the build host with Python 3.11+, Make, and Docker. Commit changes first; the working tree must be clean. External binaries remain outside Git. Plain `make image` generates the default reference automatically; the following commands freeze it for subsequent steps:

```bash
export PXEYE_VERSION="$(python3 -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"
export PXEYE_TAG="$PXEYE_VERSION-$(TZ=Asia/Shanghai date +%Y%m%d%H%M)"
export PXEYE_IMAGE="mmzhou-os-install-console:$PXEYE_TAG"
make image IMAGE="$PXEYE_IMAGE"
docker image inspect "$PXEYE_IMAGE" \
  --format '{{.Id}} {{.Architecture}} {{index .Config.Labels "org.opencontainers.image.version"}} {{index .Config.Labels "org.opencontainers.image.revision"}}'
```

An existing local tag blocks the build. To rebuild, regenerate the variables in a later minute. Do not overwrite delivered tags. After publishing, record the registry digest and use it as the immutable deployment reference.

### Save and import into containerd

Continue in the same terminal on the build host. These commands apply only when the target Kubernetes uses this host's `/run/containerd/containerd.sock` and namespace `k8s.io`; appropriate permissions are required:

```bash
mkdir -p ../pxeye-image-archives
docker save -o "../pxeye-image-archives/pxeye-$PXEYE_TAG.tar" "$PXEYE_IMAGE"
ctr --address /run/containerd/containerd.sock --namespace k8s.io \
  images import "../pxeye-image-archives/pxeye-$PXEYE_TAG.tar"
ctr --address /run/containerd/containerd.sock --namespace k8s.io \
  images list -q | grep -Fx "docker.io/library/$PXEYE_IMAGE"
```

Docker and containerd have separate image stores. `docker images` does not establish Kubernetes availability. Without a namespace, `ctr` selects `default`. For multiple nodes, publish to a registry reachable by every node or import on each node; a local import does not populate other nodes.

Neither building nor importing updates a Deployment. Deployment manifests and offline image lists must reference the exact tag; use the full reference returned above for offline export. Add the destination registry path when publishing, preserving the tag. Follow the relevant deployment procedure for configuration, secrets, persistent volumes, and retaining the previous image for rollback.

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


## DHCP address pool support

PXEye 0.22.14 can configure inclusive IPv4 DHCP ranges with a compatible NICo Core image. The Core image must implement `FindNetworkSegmentDhcpRanges`, `SetNetworkSegmentDhcpRange` and `CreateNetworkSegmentWithDhcpRange`, including their database migration and allocator changes. Upgrading PXEye alone does not add this capability to an older Core image.

Back up the NICo database before upgrading Core. Upgrade every Core replica before enabling a range: an older allocator ignores the new policy, so mixed versions must not serve DHCP allocation requests while ranges are enabled. The additive migration preserves existing subnets and allocations; it does not set a default range. Before rolling Core back, clear explicit ranges and verify that the original subnet allocation policy is acceptable.

PXEye detects the RPC capability and reads the applied policy back from Core. If unsupported, existing subnet operations remain available, ranged drafts can be saved, and applying a range is blocked. No external DHCP server is required. See [Network management](user-guide/network-management.md#configure-a-dhcp-pool).
