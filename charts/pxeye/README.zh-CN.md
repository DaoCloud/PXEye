# PXEye Helm Chart

[English](README.md) · **简体中文**

这是交付父 Chart。默认仅部署 PXEye Web 控制台及其 ServiceAccount、RBAC、ConfigMap、认证 Secret、数据和材料 PVC、Service。离线构建器会在此 Chart 下引入已锁定的 NICo 依赖、生成 `Chart.lock`，再对完整镜像闭包执行一次搬迁。

依赖树包含 cert-manager、平台基础设施 Chart、该平台 Chart 的 Vault 初始化别名、NICo Core 和可选材料发布器。本轮镜像闭包 POC 中材料发布器保持关闭。

## 安装

在具有目标集群访问权限、已安装 Helm 3 的环境执行。以下命令使用本地 Chart 源码，镜像引用需替换为已准备的实际版本：

```bash
helm upgrade --install pxeye ./charts/pxeye \
  --namespace nico-system --create-namespace \
  --set image=registry.example.com/nico/pxeye:VERSION \
  --wait --timeout 5m
```

若从源码树部署，先通过离线构建器下载并引入固定依赖。`charts/pxeye` 不提交复制的上游 Chart 树；生成的 `charts/` 目录和 `Chart.lock` 属于交付制品。

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
| `siteBootstrap.*` | `enabled=false` | 仅供自动化现场安装器使用：Core 就绪后使用集群内地址和已有客户端 Secret 接通 PXEye；不填写或发布物理 PXE/DNS/NTP 地址 |
| `siteBootNetwork.namespace` | Release namespace | PXEye 与 NICo namespace 不同时，指定 NICo DHCP/PXE/DNS/NTP 运行资源所在 namespace；不是物理网络参数 |
| `components.pxeye.enabled` | `true` | 在父 Release 中渲染 PXEye UI 资源 |
| `components.certManager/platform/vaultBootstrap/core.enabled` | `false` | 启用锁定的 NICo 子组件；现场安装器按就绪阶段累计开启 |
| `components.materials.enabled` | `false` | 预留的可选材料发布器；当前 POC 关闭 |
| `nodeSelector` / `imagePullSecrets` | 空 | 调度约束与镜像拉取认证 |

PVC 带有 Helm keep 策略。现场流程复用同一个父 Release：cert-manager → 平台/证书 → Vault 初始化 → Core；不把 Helm 依赖顺序当成控制器、证书与 Vault 就绪的替代条件。

`siteBootstrap` 不用于普通手工安装。它只记录集群内 Core/PXE 服务和客户端 Secret 的名称；PXEye 在 Core
与证书尚未就绪时安全重试，连接成功后才持久化 mTLS 身份。外部 PXE、DHCP、DNS、NTP 与 HostInband 网络不应
写入该字段，须通过后续站点网络配置和现场验证应用。

当 PXEye 与 NICo 位于不同 namespace 且 `siteBootNetwork.namespace` 指向 NICo namespace 时，Chart 还会在该
目标 namespace 创建最小 Role/RoleBinding，使 PXEye 仅能读取、创建或更新引导网络所需的 Service、Kea ConfigMap
和 DHCP Deployment。该权限用于后续页面的“管理引导网络”，不授予集群级权限或 Secret 读取权限。
