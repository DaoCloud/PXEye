# Start PXEye before deploying NICo

**English** · [简体中文](nico-deployment.zh-CN.md) · [Documentation](README.md)

PXEye can start independently in an existing Kubernetes/Kind cluster. After login, use the [NICo cluster page](user-guide/nico-cluster.md) to deploy NICo applications in the current cluster. Kubernetes, CNI, storage classes and external network access must already be available.

## 1. Runtime prerequisites

- The PXEye image includes `nico-admin-cli`, `grpcurl` and **Helm 3** matching the control-plane architecture; place them in `bin/` before building.
- `/data` persists tasks, configuration, deployment records and restricted client identity files. `/materials` stores uploaded OS artifacts.
- `/secrets/auth.json` holds the operator password SHA256. Initial startup does not require Core certificates or an SSH private key; PXEye creates its SSH identity in the backend data directory.
- `/nico-packages` mounts prepared deployment packages read-only and is not served over HTTP.
- PXEye and PXE share the material storage. Single-node/RWO storage requires a node selector to schedule PXE on the PXEye node; multi-node deployments can use RWX storage.

Use [bootstrap-site.example.json](../examples/bootstrap-site.example.json). Leave `core_url` empty, enable `nico_deployment.enabled` and set the namespace consistently with the Pod.

## 2. Prepare the Helm package

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

The helper copies declared Charts/values, generates file SHA256 values and refuses to overwrite a destination. Place the output on the existing `mmzhou-nico-packages` PVC so PXEye sees `/nico-packages/site-v1/deployment.json`. Import images into the nodes or supply an accessible registry first; the page does not import host images or run online dependency updates.

## 3. Recipe fields and mounts

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

## 4. Start PXEye

Populate the `mmzhou-nico-packages` PVC and configure data/material PVCs for the available storage class. Create local configuration and login credential files:

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

## 5. Deploy and verify in the page

Follow the [page guide](user-guide/nico-cluster.md). **Deployment workflow → Operations and commands** displays commands and exit codes by phase. Raw Helm output, which may contain credentials, is retained only in restricted files under `/data/nico-deployment/`.

After required services and initialization are ready, verify the physical machine's DHCP/PXE path. Preserve PVCs and Secrets on failure; do not delete the database to retry. Back up the Vault recovery Secret through a restricted channel.

References: [NVIDIA Quick Start](https://docs.nvidia.com/infra-controller/documentation/getting-started/quick-start-guide) · [Reference Installation](https://docs.nvidia.com/infra-controller/documentation/getting-started/installation-options/reference-installation) · [Architecture](https://docs.nvidia.com/infra-controller/documentation/architecture/overview-and-components)
