# Start PXEye before deploying NICo

**English** · [简体中文](nico-deployment.zh-CN.md) · [Documentation](README.md)

PXEye can start independently in an existing Kubernetes/Kind cluster. Use the [NICo cluster page](user-guide/nico-cluster.md) to deploy online or offline. Online is the default: enter a source, release and values. Offline materials are uploaded in the browser, without a server login or package mount. Kubernetes, CNI, storage and external service access must already be available.

## 1. Runtime prerequisites

- The PXEye image includes `nico-admin-cli`, `grpcurl` and **Helm 3** matching the control-plane architecture; place them in `bin/` before building.
- `/data` persists tasks, configuration, deployment records and restricted client identity files. `/materials` stores uploaded OS artifacts.
- `/secrets/auth.json` holds the operator password SHA256. Initial startup does not require Core certificates or an SSH private key; PXEye creates its SSH identity in the backend data directory.
- PXEye manages online and uploaded materials privately under `/data/nico-deployment/`; uploads need no extra PVC. Existing `/nico-packages` mounts remain an optional source.
- A field bundle can be mounted read-only at `/nico-bundles`. PXEye reads its manifests and small `deployment/` recipe without copying the 17GiB OCI archive into `/data`.
- PXEye and PXE share the material storage. Single-node/RWO storage requires a node selector to schedule PXE on the PXEye node; multi-node deployments can use RWX storage.

Use [bootstrap-site.example.json](../examples/bootstrap-site.example.json). Leave `core_url` empty, enable `nico_deployment.enabled` and set the namespace consistently with the Pod.

## 2. Online and offline deployment

| Mode | Page input |
| --- | --- |
| Download URL (default) | Use the fixed NICo source URL or enter a Chart `.tgz` / source archive URL. PXEye downloads and prepares the Chart. |
| Helm repository | Enter repository URL, Chart name, optional version and values; PXEye runs `helm pull --repo`. |
| OCI | Enter an `oci://...` Chart reference, optional version and values; PXEye runs `helm pull`. |
| Offline | Upload a `.tgz` with dependencies and paste or read values; complete `.tar.gz` / `.zip` recipes are also accepted. |

PXEye downloads sources; nodes pull images. Private registries need appropriate existing authentication. Ordinary Charts need no deployment.json, component mapping or checksum table. Full ordered recipes retain their phase and connection metadata.

### 2.1 Mounted field bundles

```text
nico-x86-field-<version>/
├── bundle.json
├── manifests/file-inventory.json
├── manifests/images-lock.json
├── images/nico-amd64.oci.tar
└── deployment/              # optional deployment.json, charts/ and values/
```

When `deployment/` is absent, the page reports the bundle inventory but refuses to start Helm. This is the current state of the `.50` 17GiB package. Run `tools/package-nico-field-bundle.py` after adding a recipe; PXEye discovers it on refresh and copies only the recipe into its writable package directory. Configure `nico_deployment.bundles_directory` and mount the directory using [the example patch](../deploy/nico-bundle-mount.example.yaml).

If a site explicitly requires one heavyweight PXEye image, build `Dockerfile.bundle` on top of the normal PXEye image with the bundle as a separate approximately 17GiB layer. This is supported as an exception, but the read-only mount remains the default because upgrades and rollbacks otherwise move the entire archive.

After checks, inspect the command in the confirmation dialog:

```bash
helm upgrade --install mmzhou ./chart.tgz \
  -n mmzhou -f values.yaml --wait --wait-for-jobs --timeout 900s
```

Actual commands use the current Pod identity and the PXEye naming/mount renderer, and appear in deployment progress. The Core Chart receives `mmzhou` workload names and the shared materials PVC; set `nico_deployment.materials_claim` for another PVC. A successful individual Chart means Helm completed, while full services, Boot and site connection are checked separately.

## 3. Complete Helm recipe (optional)

Keep a site's configuration in `values/`:

```text
site-recipe/
├── deployment.json
├── charts/
│   ├── cert-manager-v1.17.1.tgz
│   ├── pxeye-nico-platform-0.1.0.tgz
│   ├── nico-0.1.1.tgz
│   ├── temporal-0.35.0.tgz
│   ├── site-keycloak.tgz
│   ├── nico-rest-0.1.13.tgz
│   └── nico-rest-site-agent-0.1.9.tgz
└── values/
    ├── cert-manager.yaml
    ├── platform.yaml
    ├── vault.yaml
    ├── core.yaml
    ├── temporal.yaml
    ├── keycloak.yaml
    ├── rest.yaml
    └── site-agent.yaml
```

Copy [deployment.example.json](../deploy/nico/deployment.example.json) and adjust names/versions to the actual Charts and values. It demonstrates the complete service contract; it does not supply all site values, images or Charts. Older offline packages containing Charts and directly applied JSON need this contract and complete initialization phases first.

| Phase | Materials and requirements |
| --- | --- |
| Certificate management | cert-manager Chart/images; reuse healthy controller, cainjector and webhook when available. Add shared namespaces to `observe_namespaces` and grant read access there. |
| Database and certificates | This repository's [nico-platform Chart](../deploy/nico-platform/Chart.yaml), in `infrastructure` mode, provides single-replica PostgreSQL/Vault, PVCs, site CA and client certificates; [values example](../deploy/nico/platform-values.example.yaml). |
| Vault initialization | The same Chart's `vault-bootstrap` mode uses the initialization command in the new PXEye image; [values example](../deploy/nico/vault-values.example.yaml). Recovery information is written only to restricted Kubernetes Secrets; scheduled jobs renew tokens and unseal Vault. |
| Core and networking | NICo Chart matching runtime images; database/Vault Secrets, Issuer, admin-client trust, complete site TOML, service exposure and Boot materials. Disable automatic enrollment and firmware updates. |
| Temporal | Chart, database/TLS configuration and schema initialization jobs. |
| Keycloak | A site Chart with database, Realm and REST client configuration. `site-keycloak.tgz` is a site-supplied example name, not a bundled NICo file. |
| REST | NICo REST Chart, migration image, database credentials, CA signing Secret, Temporal namespace/queue and authentication configuration. Dependency Secrets must exist before pre-install migrations. |
| Site Agent | Chart, registration hook, Core mTLS and Temporal/database configuration. |

The single-replica platform Chart provides basic functionality for a single-node installation environment. HA deployments must replace the appropriate phases with configured database, Vault and storage solutions.

Package the platform Chart, then freeze the complete site materials:

```bash
helm package deploy/nico-platform --destination /srv/site-recipe/charts
python3 tools/package-nico-deployment.py \
  --source /srv/site-recipe \
  --destination /srv/nico-packages/site-v1
```

The helper copies declared Charts/values, generates file SHA256 values and refuses to overwrite a destination. Archive the output and upload it in Offline mode:

```bash
tar -C /srv/nico-packages -czf /srv/site-v1.tar.gz site-v1
```

Existing read-only `/nico-packages` mounts remain supported. Offline material must already contain Chart dependencies.

Helm does not consume an OCI tar directly. The PXEye image includes `skopeo` and `/usr/local/bin/pxeye-import-oci-bundle`, which can push the archive from the PXEye Pod using a read-only auth Secret; no host Docker/containerd socket is required. All Kubernetes nodes must still reach the Harbor registry.

## 4. Recipe fields and shared materials

| Field | Purpose |
| --- | --- |
| `schema_version` | Currently `1`. |
| `name` / `version` / `defaults` | Package identity and form defaults. |
| `phases` | Dependency order, release name, Chart, values files and timeout. |
| `components` | Service ID, workload kind/name/namespace and phase; cover all 25 required services in the example. |
| `initialization` | Vault, Core, Temporal and REST initialization phases; each must actually render a Job. |
| `connection` | Core client/CA Secret names and keys, with an optional internal PXE URL. |
| `boot_checks` | Architecture-specific EFI, Scout and rootfs HTTP URLs and minimum sizes. |
| `files` | Chart/values SHA256 generated by the helper. |

Values support `@{site_name}`, `@{release_prefix}`, `@{namespace}`, `@{core_url}` and `@{pxe_url}`. `@{pxeye_node}` comes from the Pod's `POD_NODE_NAME` for normal scheduling of shared RWO materials. Values without variables retain their packaged values. Release prefixes do not rewrite Service DNS, SPIFFE identities or Secret references; configure these references consistently in values.

Helm hooks bypass post-renderers: configure their Pod instance labels and bounded Job deadlines in the Chart itself. Preflight checks the actual hook output. Service selectors are aligned with workload identity labels; a selector spanning several workloads must be configured explicitly.

`phases[].pod_overrides` adds node selection, volumes and mounts to exact workloads. The example mounts `mmzhou-pxeye-materials` read-only in PXE at `/forge-boot-artifacts/blobs/internal/nico/os-library`, using shared `fsGroup: 1000`. Uploaded files map as follows:

```text
PXEye: /materials/<os-id>/install.iso
PXE:   /forge-boot-artifacts/blobs/internal/nico/os-library/<os-id>/install.iso
HTTP:  <pxe-url>/public/blobs/internal/nico/os-library/<os-id>/install.iso
```

Configure Boot init containers in both Core and PXE. Include the supplied versions of the custom x86 Boot image and Grace ARM64 files; the control-plane CPU architecture alone does not determine boot artifacts.

## 5. Start PXEye

Configure data/material PVCs for the available storage class; the bootstrap manifest does not require a package PVC. Create configuration and login credential files:

```bash
mkdir -p deploy/local/bootstrap
cp examples/bootstrap-site.example.json deploy/local/bootstrap/site.json
python3 - <<'PY'
import getpass, hashlib, json, os
from pathlib import Path
os.umask(0o077)
password = getpass.getpass('PXEye operator password: ')
if not password:
    raise SystemExit('Empty password refused')
Path('deploy/local/bootstrap/auth.json').write_text(
    json.dumps({'password_sha256': hashlib.sha256(password.encode()).hexdigest()}))
PY
```

Use the confirmed target context, replacing `SITE_CONTEXT`. Replace `image: pxeye:dev` in the example Deployment with the built version image before applying it.

```bash
SITE_CONTEXT=your-cluster
kubectl --context "$SITE_CONTEXT" create namespace mmzhou --dry-run=client -o yaml \
  | kubectl --context "$SITE_CONTEXT" apply -f -
kubectl --context "$SITE_CONTEXT" -n mmzhou create configmap mmzhou-pxeye \
  --from-file=site.json=deploy/local/bootstrap/site.json --dry-run=client -o yaml \
  | kubectl --context "$SITE_CONTEXT" apply -f -
kubectl --context "$SITE_CONTEXT" -n mmzhou create secret generic mmzhou-pxeye \
  --from-file=auth.json=deploy/local/bootstrap/auth.json --dry-run=client -o yaml \
  | kubectl --context "$SITE_CONTEXT" apply -f -
kubectl --context "$SITE_CONTEXT" apply -f deploy/bootstrap-kubernetes.yaml
kubectl --context "$SITE_CONTEXT" -n mmzhou rollout status deployment/mmzhou-pxeye --timeout=180s
```

The example exposes TCP `31808`. Open that port on the actual node and log in. Kind needs existing port mappings or another platform-provided access route.

The base manifest grants application installation permissions in the current namespace. Installing cert-manager CRDs/cluster RBAC or the platform Chart's Vault TokenReview binding additionally requires an administrator to apply [cluster installation permissions](../deploy/nico-cluster-permissions.yaml) and set `allow_cluster_resources: true`. Without these permissions, use a package with prepared dependencies. After deployment, installation rights can be withdrawn while retaining observation and access to the designated identity Secrets.

## 6. Deploy and verify in the page

Follow the [page guide](user-guide/nico-cluster.md). **Deployment workflow → Operations and commands** displays commands and exit codes by phase. Raw Helm output, which may contain credentials, is retained only in restricted files under `/data/nico-deployment/`.

After required services and initialization are ready, verify the physical machine's DHCP/PXE path. Preserve PVCs and Secrets on failure; do not delete the database to retry. Back up the Vault recovery Secret through a restricted channel.

References: [NVIDIA Quick Start](https://docs.nvidia.com/infra-controller/documentation/getting-started/quick-start-guide) · [Reference Installation](https://docs.nvidia.com/infra-controller/documentation/getting-started/installation-options/reference-installation) · [Architecture](https://docs.nvidia.com/infra-controller/documentation/architecture/overview-and-components)
