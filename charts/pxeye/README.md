# PXEye Helm Chart

**English** · [简体中文](README.zh-CN.md)

This is the delivery parent Chart. By default it deploys only the PXEye web console with its ServiceAccount, RBAC, ConfigMap, authentication Secret, data/material PVCs and Service. The offline builder vendors the locked NICo dependencies under this Chart, resolves `Chart.lock`, and relocates one complete image closure.

The dependency tree is cert-manager, the platform infrastructure Chart, a separate Vault-bootstrap alias of that Chart, NICo Core, and the optional material publisher. The material publisher is disabled in the current image-only delivery.

## Installation

Run with Helm 3 and access to the target cluster. Replace the image reference with the prepared version:

```bash
helm upgrade --install pxeye ./charts/pxeye \
  --namespace nico-system --create-namespace \
  --set image=registry.example.com/nico/pxeye:VERSION \
  --wait --timeout 5m
```

For a source-tree deployment, first use the offline builder to download and vendor the pinned dependencies. `charts/pxeye` intentionally does not commit copied upstream Chart trees; the generated `charts/` directory and `Chart.lock` are delivery artifacts.

## Configuration

| Field | Default | Purpose |
| --- | --- | --- |
| `image` | Empty, required | Complete PXEye image reference |
| `storageClass` | Empty | Use the cluster default StorageClass |
| `dataStorage` / `materialsStorage` | `2Gi` / `50Gi` | Data and material PVC sizes |
| `service.type` / `service.port` / `service.nodePort` | `NodePort` / `80` / `31808` | Service access |
| `auth.existingSecret` | Empty | Reuse a Secret containing `auth.json`; otherwise generate credentials on first install and retain them on upgrade |
| `nico.enabled` | `true` | Enable console NICo deployment configuration |
| `nico.allowClusterResources` | `false` | Create cluster permissions for CRDs, ClusterRoles and related resources |
| `siteBootstrap.*` | `enabled=false` | Reserved for the automated onsite installer: connect PXEye after Core is ready using in-cluster endpoints and existing client Secrets; it never publishes physical PXE/DNS/NTP addresses |
| `siteBootNetwork.namespace` | Release namespace | Namespace containing the NICo DHCP/PXE/DNS/NTP runtime resources when it differs from PXEye; this is not a physical-network setting |
| `components.pxeye.enabled` | `true` | Render PXEye UI resources in this parent release |
| `components.certManager/platform/vaultBootstrap/core.enabled` | `false` | Enable a locked NICo child component; the onsite runner enables these cumulatively in readiness-aware phases |
| `components.materials.enabled` | `false` | Reserved optional publisher; disabled in the current POC |
| `nodeSelector` / `imagePullSecrets` | Empty | Scheduling and image-pull authentication |

PVCs use the Helm keep policy. The onsite workflow reuses one parent release: cert-manager → platform/certificates → Vault bootstrap → Core. This avoids treating Helm dependency order as a substitute for controller, certificate, and Vault readiness.

`siteBootstrap` is not for normal manual installation. It contains only in-cluster Core/PXE service endpoints and client
Secret names; PXEye retries safely until Core and its certificates are ready, then persists the mTLS connection. Do not
put external PXE, DHCP, DNS, NTP, or HostInband settings there: apply them through subsequent site-network configuration
and physical-network validation.

When PXEye and NICo use different namespaces and `siteBootNetwork.namespace` names the NICo namespace, the Chart also
creates a namespace-scoped Role/RoleBinding there. It grants PXEye access to namespaced resources in that target
namespace for the later **Manage boot network** page; it grants neither cluster-scoped access nor Secret reads.
