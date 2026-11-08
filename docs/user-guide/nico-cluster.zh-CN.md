---
page_id: nico-cluster
language: zh-CN
title: NICo 集群
description: 在当前 Kubernetes 部署 NICo，查看服务和部署进度，并连接站点。
navigation_group: configuration
updated_at: "2026-11-08"
product_version: "0.22.0"
---

# NICo 集群

[English](nico-cluster.md) · **简体中文** · [页面使用指南](README.zh-CN.md)

## 1. 用途与入口

进入 **配置 → NICo 集群**，在 PXEye 所在的 Kubernetes 集群通过 Helm 部署 NICo，查看服务运行状态。未连接 NICo 时，登录后默认进入此页；业务页面在连接站点后启用。

先准备 [Helm 部署包及部署权限](../nico-deployment.zh-CN.md)。PXEye 登录口令、数据存储和启动均独立于 NICo。

## 2. 字段填写

| 字段 | 填写要求 |
| --- | --- |
| 部署包 | 选择已挂载到 `/nico-packages` 的版本包；包含 Chart、values、初始化作业和文件摘要。 |
| 站点名称 | 必填，1–100 个字符，用于站点标识。 |
| 发布名前缀 | 小写字母、数字和连字符；各 Helm 发布使用此名前缀。需要与包内资源命名一致。 |
| 命名空间 | 来自 PXEye 的部署配置，页面只读；本页只操作当前集群。 |
| Core HTTPS 地址 | PXEye 可访问的 `https://主机:端口`，必须匹配 Core 证书。 |
| PXE / HTTP 对外地址 | 被安装主机可访问的 `http://主机:端口` 或 HTTPS 地址，不带目录路径。 |

服务暴露、数据库、网络和存储的具体配置保存在部署包的 values 中。包中的变量决定表单字段如何作用于 Chart。

## 3. 操作步骤

1. 在**部署配置**填写字段，点击**检查部署配置**。检查在后台执行，可在**部署流程**查看当前阶段及命令记录。
2. 检查通过后点击**开始部署**，核对站点、命名空间及地址并确认。服务按包内依赖顺序启动。
3. 在**服务总览**查看服务、副本和端口；点击服务名称可查看工作负载、运行镜像和初始化镜像。
4. 必需服务、初始化作业、证书、存储和引导材料全部就绪后，点击**应用到站点**。系统验证客户端身份并读取 Core，成功后更新站点与材料服务地址，启用业务页面。
5. 部署异常时查看失败阶段与服务状态，处理后点击**核对并继续**。若 Helm 发布仍处于 pending 状态，需要先处理该发布。

## 4. 填写示例

| 字段 | 示例 |
| --- | --- |
| 站点名称 | `Example site` |
| 发布名前缀 | `mmzhou` |
| 命名空间 | `mmzhou` |
| Core HTTPS 地址 | `https://mmzhou-nico-api.mmzhou.svc:1079` |
| PXE / HTTP 对外地址 | `http://192.0.2.50:31880` |

此示例要求包内使用对应 Service 名称，并将 PXE HTTP 暴露到指定端口。地址需要替换为实际部署值。

## 5. 注意事项

- 默认清单覆盖 Core、PXE、DHCP、DNS、NTP、硬件健康、SSH Console、数据库、Vault、证书管理、REST、Temporal 和 Keycloak。MAT、Flow、DPF 等单独列为可选组件。
- Boot 材料由 Core/PXE 的初始化容器或挂载目录提供；其架构必须匹配被安装主机。
- 已有服务用于观察；本页不会自动接管旧 Helm 发布或覆盖同名资源。
- 部署失败保留发布与持久数据。服务重启期间未确认的阶段需要核对后继续。
- 服务就绪及 Boot HTTP 可读取后，仍需验证实际 DHCP、Relay、主机 PXE 和 OS 安装路径。
- 部署包关闭自动接管和固件自动更新；部署操作不会自动启动真实主机装机。

相关：[部署材料与权限](../nico-deployment.zh-CN.md) · [站点设置](site-settings.zh-CN.md) · [网络管理](network-management.zh-CN.md)
