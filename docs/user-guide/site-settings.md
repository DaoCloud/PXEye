---
page_id: site-settings
language: en
title: Site settings
description: Inspect Core connections, client identity and storage, and configure site boot-service addresses and installation concurrency.
navigation_group: configuration
updated_at: "2026-11-08"
product_version: "0.22.0"
---

# Site settings

**English** · [简体中文](site-settings.zh-CN.md) · [Page guides](README.md)

## 1. Purpose and entry point

Open **Configuration → Site settings (配置 → 站点设置)** to inspect NICo Core, client certificates, storage and service endpoints, manage physical boot-service addresses, and set default concurrency for new installation batches. Use it for deployment checks and connection troubleshooting.

## 2. Field values

**Edit site (编辑站点)** changes three fields:

| Field | Requirement |
| --- | --- |
| Site name (站点名称) | Required, 1–100 characters; identifies the site in the UI. |
| Core HTTPS address (Core HTTPS 地址) | Full `https://host:port`, without API paths, queries or fragments. PXEye must reach it and its current mTLS identity must be accepted. |
| Default installation concurrency (默认安装并发) | Integer `1–50`, default `5`; choose according to control-plane and network capacity. |

Other information is read-only:

| Information | Meaning |
| --- | --- |
| Connection identity (连接身份) | Subject, issuer and validity of the current client certificate. |
| Data directories (数据目录) | Task/planning history, OS boot materials and ISO sources, with free capacity of their filesystems. |
| Network and infrastructure services (网络与基础服务) | Configured endpoints, status and check time; results distinguish TCP reachability from configuration only. |

## 3. Boot-network service addresses

Use **Manage boot network (管理引导网络)** to maintain the external IPv4 VIPs for DHCP, PXE HTTP, DNS and NTP. PXEye previews the Kubernetes Services, Kea ConfigMap and DHCP Deployment before any write. After **Save and apply (保存并应用)** is confirmed, PXEye creates or updates only its `pxeye-site-*` LoadBalancer Services, waits for the requested VIPs, writes Kea DHCP Option 54 plus PXE/DNS/NTP advertisement values, and rolls DHCP.

This does not change HostInband segments, DHCP pools, device plans or existing installation tasks. HostInband is NICo's network object for choosing a host boot interface's DHCP segment and allocating its address; it remains in network management and device/installation checks, not in this VIP form.

Use a maintenance window: PXEye blocks an address change while installation tasks are active. A successful apply proves only the controlled Kubernetes and Kea update. Validate DHCP Offer and PXE HTTP from the actual boot VLAN separately. PXEye does not yet rewrite existing OS-definition material URLs automatically; that migration will be a separate operation after NICo contract validation.

## 4. Actions

1. Click **Refresh data (刷新数据)** and inspect site, Core address, certificate validity, directories and services.
2. Click **Edit site (编辑站点)**, change name, Core address or concurrency, and **Verify and save (验证并保存)**.
3. When switching Core, the service reads the new Core with the current mTLS identity. Failure leaves settings unchanged. Running or pending-issue installation tasks block switching Core.
4. Review the saved settings and refresh the relevant resource pages. New batches use the saved concurrency.

## 5. Example

| Field | Example |
| --- | --- |
| Site name | `Demo Site` |
| Core HTTPS address | `https://nico-api.nico-system.svc.cluster.local:1079` (only for clusters actually using this Service) |
| Default installation concurrency | `3` |

New batches run at most three devices concurrently. Existing batches retain their original concurrency.

## 6. Notes

- A healthy Core indicator primarily reflects TCP reachability, not complete API, DHCP or installation validation.
- Storage figures cover the filesystem, rather than space used exclusively by one directory.
- Maintain certificates, private keys, material/source directories and HTTP publication URLs through deployment configuration and mounts; this page does not upload or modify those files.
- Switching Core does not migrate plans, profiles or history. Verify resource references and data ownership before switching.

Related: [Deployment](../deployment.md) · [Network management](network-management.md) · [Installation tasks](installation-tasks.md)

For a new cluster, deploy and apply the site from [NICo cluster](nico-cluster.md). An existing Core can be connected here with a valid client identity.
