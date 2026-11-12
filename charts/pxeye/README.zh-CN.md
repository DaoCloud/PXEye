# PXEye Helm Chart

[English](README.md) · **简体中文**

部署 PXEye Web 控制台及其 ServiceAccount、RBAC、ConfigMap、认证 Secret、数据和材料 PVC、Service。该 Chart 源码同时用于直接 Helm 部署和离线交付构建。

## 安装

在具有目标集群访问权限、已安装 Helm 3 的环境执行。以下命令使用本地 Chart 源码，镜像引用需替换为已准备的实际版本：

```bash
helm upgrade --install pxeye ./charts/pxeye \
  --namespace nico-system --create-namespace \
  --set image=registry.example.com/nico/pxeye:VERSION \
  --wait --timeout 5m
```

## 配置

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `image` | 空，必填 | PXEye 完整镜像引用 |
| `storageClass` | 空 | 使用集群默认 StorageClass |
| `dataStorage` / `materialsStorage` | `2Gi` / `50Gi` | 数据和材料 PVC 容量 |
| `service.type` / `service.port` / `service.nodePort` | `NodePort` / `80` / `31808` | 服务访问方式 |
| `auth.existingSecret` | 空 | 复用含 `auth.json` 的已有 Secret；为空时首次生成密码，升级时保留原认证信息 |
| `nico.enabled` | `true` | 启用控制台中的 NICo 部署配置 |
| `nico.allowClusterResources` | `false` | 创建操作 CRD、ClusterRole 等资源所需的集群级权限 |
| `nodeSelector` / `imagePullSecrets` | 空 | 调度约束与镜像拉取认证 |

PVC 带有 Helm keep 策略。Chart 不安装 NICo Core，NICo 由独立安装流程部署。
