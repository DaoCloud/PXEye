---
page_id: site-settings
language: zh-CN
title: 站点设置
description: 查看控制面连接、客户端身份和存储，设置站点、引导服务地址及安装并发。
navigation_group: configuration
updated_at: "2026-11-08"
product_version: "0.22.0"
---

# 站点设置

[English](site-settings.md) · **简体中文** · [页面使用指南](README.zh-CN.md)

## 1. 用途与入口

进入 **配置 → 站点设置**，核对 PXEye 连接的 NICo Core、客户端证书、数据目录和服务端点，维护物理引导服务地址，并设置新安装批次的默认并发。用于初次部署核对和日常连接排查。

## 2. 字段填写

点击**编辑站点**可修改以下三项：

| 字段 | 填写要求 |
| --- | --- |
| 站点名称 | 必填，1–100 字符，用于界面标识。 |
| Core HTTPS 地址 | 完整的 `https://主机:端口`；不填写 API 路径、查询串或片段。地址必须从 PXEye 可达，并接受当前 mTLS 客户端身份。 |
| 默认安装并发 | `1–50` 的整数，默认 `5`；按控制面及网络容量设置。 |

其余信息用于查看：

| 信息 | 含义 |
| --- | --- |
| 连接身份 | 当前客户端证书的主体、签发者和有效期。 |
| 数据目录 | 任务/规划历史、OS 启动材料、ISO 来源目录及其所在文件系统的可用容量。 |
| 网络与基础服务 | 已配置服务的端点、检查状态和检查时间；具体结果标注 TCP 可达或仅已配置。 |

## 3. 引导网络服务地址

点击**管理引导网络**可维护 DHCP、PXE HTTP、DNS 和 NTP 的对外 IPv4 VIP；PXEye 会先显示将修改的 Kubernetes Service、Kea ConfigMap 和 DHCP Deployment。确认**保存并应用**后，PXEye 创建或更新自身管理的 `pxeye-site-*` LoadBalancer Service，等待 VIP 分配，再写入 Kea 的 DHCP Option 54、PXE、DNS、NTP 下发参数并滚动 DHCP。

该操作不修改 HostInband 网段、DHCP 地址池、设备规划或现有安装任务。HostInband 是 NICo 为主机启动口选择 DHCP 网段和地址分配的网络对象，仍在网络管理和设备/安装预检中维护，不是服务 VIP。

应用前应处于维护窗口：存在活动安装任务时 PXEye 会阻止改址。应用成功只说明 Kubernetes 与 Kea 已完成受控更新；还需从实际引导 VLAN 完成 DHCP Offer 和 PXE HTTP 验证。PXEye 当前不会自动改写已有 OS 定义中的材料 URL；该迁移需待 NICo 契约验证后通过独立操作完成。

## 4. 操作步骤

1. 点击**刷新数据**，核对站点、Core 地址、证书有效期、目录和服务状态。
2. 点击**编辑站点**，修改名称、Core 地址或默认并发，点击**验证并保存**。
3. 切换 Core 时，系统使用当前 mTLS 身份读取新 Core；失败则不应用修改。存在执行中或待处理的安装任务时不能切换 Core。
4. 保存后核对页面显示，再在对应资源页刷新数据；新安装批次使用保存后的默认并发。

## 5. 填写示例

| 字段 | 示例 |
| --- | --- |
| 站点名称 | `Demo Site` |
| Core HTTPS 地址 | `https://nico-api.nico-system.svc.cluster.local:1079`（仅适用于实际采用此 Service 的集群） |
| 默认安装并发 | `3` |

保存后，新批次最多同时执行 3 台；已有批次保持创建时的并发值。

## 6. 注意事项

- 页面显示的 Core 连接正常主要来自 TCP 检查，不代表完整 API、DHCP 或装机流程通过。
- 存储容量显示所在文件系统的使用量，不是某个目录独占的容量。
- 证书、私钥、材料目录、来源目录和 HTTP 发布 URL 通过部署配置及挂载维护，本页不上传或修改这些文件。
- 更换 Core 不会自动迁移设备规划、方案和任务历史；切换前核对资源引用及数据归属。

相关：[部署指南](../deployment.zh-CN.md) · [网络管理](network-management.zh-CN.md) · [安装任务](installation-tasks.zh-CN.md)

首次没有 Core 时，先使用 [NICo 集群](nico-cluster.zh-CN.md) 部署并应用站点；已有 Core 可使用本页连接，客户端身份仍需有效。
