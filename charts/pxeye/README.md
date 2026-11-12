# PXEye Helm Chart

**English** · [简体中文](README.zh-CN.md)

Deploys the PXEye web console with its ServiceAccount, RBAC, ConfigMap, authentication Secret, data/material PVCs and Service. Direct Helm deployments and offline packaging use this same Chart source.

## Installation

Run with Helm 3 and access to the target cluster. Replace the image reference with the prepared version:

```bash
helm upgrade --install pxeye ./charts/pxeye \
  --namespace nico-system --create-namespace \
  --set image=registry.example.com/nico/pxeye:VERSION \
  --wait --timeout 5m
```

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
| `nodeSelector` / `imagePullSecrets` | Empty | Scheduling and image-pull authentication |

PVCs use the Helm keep policy. NICo Core is installed through a separate deployment workflow.
