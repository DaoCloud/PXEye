---
page_id: nico-cluster
language: zh-CN
title: NICo 集群
description: 在线或离线通过 Helm 部署 NICo，查看服务和部署进度，并连接站点。
navigation_group: configuration
updated_at: "2026-11-08"
product_version: "0.22.1"
---

# NICo 集群

[English](nico-cluster.md) · **简体中文** · [页面使用指南](README.zh-CN.md)

## 1. 用途与入口

进入 **配置 → NICo 集群**，在 PXEye 所在的 Kubernetes 集群执行 Helm 安装，查看服务状态。PXEye 可以先于 NICo 启动；连接站点后启用业务页面。

## 2. 字段填写

| 字段 | 填写要求 |
| --- | --- |
| 部署方式 | 默认**在线部署**；无法联网时选择**离线部署**。 |
| Chart 来源 | 在线支持下载地址、Helm 仓库或 OCI。默认下载固定版本的 NICo 源码并准备其中的 Core Chart。 |
| 仓库地址 / Chart 名称 | 选择 Helm 仓库时填写；例如 `https://charts.example.com` 和 `nico`。 |
| Chart 版本 | 仓库或 OCI 可选；留空使用来源默认版本。下载地址直接决定版本。 |
| 离线部署材料 | 从本机上传 `.tgz` Chart，或 `.tar.gz` / `.zip` 完整部署包，最大 128 MiB。无需登录服务器或挂载部署包目录。 |
| 站点名称 | 站点标识，最长 100 字符。 |
| Helm 发布名 | 使用 `mmzhou` 或 `mmzhou-` 前缀，例如 `mmzhou`、`mmzhou-postgres`。 |
| 命名空间 | PXEye 所在命名空间，页面只读。 |
| 部署超时 | 默认 900 秒，可填 60–1800 秒。 |
| values YAML | 粘贴所选 Chart 的安装参数，或点击**从文件读取**。普通 Chart 无需另外编写组件映射表；完整部署包使用包内各阶段 values。 |
| 站点连接 | 可选展开。填写 Core HTTPS、PXE 对外地址、客户端和 CA Secret，以及目标主机架构；也可在安装后的连接确认中补填服务地址。 |

NICo 的镜像、数据库、Vault、服务暴露和 Boot 配置按 Chart 的 values 填写。NICo Core Chart 会自动适配 `mmzhou` 工作负载命名，并使用 PXEye 的共享材料 PVC。

## 3. 操作步骤

1. 选择在线来源，或切换离线并上传材料。
2. 填写发布名和 values，点击**检查并预览**。系统在后台准备 Chart、检查配置与权限。
3. 检查通过后点击**开始部署**，查看生成的 Helm 命令并确认。**部署流程**显示实际命令、阶段和退出码。
4. 在**服务总览**查看完整组件、副本、端口和镜像。单个 Chart 安装成功显示**Helm 已完成**；依赖未齐全时可返回部署配置继续安装其他 Chart。
5. 必需服务、依赖资源和 Boot HTTP 材料就绪后，点击**应用到站点**。验证 Core 身份成功才保存站点配置并启用业务页面。

## 4. 填写示例

| 场景 | 填写方式 |
| --- | --- |
| 在线仓库 | 来源选择 Helm 仓库，填写仓库地址、Chart 名称与可选版本，粘贴其 values。 |
| 在线 OCI | 填写 `oci://registry.example.com/charts/nico`，并指定版本和 values。 |
| 离线 Chart | 上传 `nico-0.1.1.tgz`，发布名填写 `mmzhou`，读取对应的 values YAML。 |

示例地址需要替换为实际值。完整部署与参数准备见[部署说明](../nico-deployment.zh-CN.md)。

## 5. 注意事项

- PXEye 的 ServiceAccount 需要安装权限；在线下载由 PXEye 执行，镜像由 Kubernetes 节点拉取，二者都需要相应网络连接。
- NICo Core Chart 不包含全部 PostgreSQL、Vault、证书管理、REST 和 Temporal 依赖；它们可分别用 Chart 部署，也可由完整部署包按顺序安装。
- 离线 Chart 必须包含子 Chart 依赖，相关镜像应提前可用；上传 Chart 不会向节点导入镜像。
- 已有服务用于观察，安装不会自动接管同名资源。失败保留发布和持久数据，核对后继续。
- 服务 Ready 与物理 DHCP、Relay、PXE 和 OS 安装分别验证。部署不会自动启动真实主机装机或固件更新。

相关：[部署与权限](../nico-deployment.zh-CN.md) · [站点设置](site-settings.zh-CN.md) · [网络管理](network-management.zh-CN.md)
