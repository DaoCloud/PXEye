---
page_id: site-settings
language: en
title: Site settings
description: Inspect Core connections, client identity and storage, and configure site boot-service addresses and installation concurrency.
navigation_group: configuration
updated_at: "2026-11-16"
product_version: "0.22.16"
---

# Site settings

**English** · [简体中文](site-settings.zh-CN.md) · [Page guides](README.md)

## 1. Purpose and entry point

Open **Configuration → Site settings (配置 → 站点设置)** to inspect NICo Core, client certificates, storage and service endpoints, manage physical boot-service addresses, and set default concurrency for new installation batches. Use it for deployment checks and connection troubleshooting.

## 2. Field values

**Site discovery (站点发现)** shows the actual switch on all ready Core replicas: enabled, paused, or unavailable. Automatic machine creation has its own status. New sites start Core with discovery enabled and automatic machine creation and firmware updates disabled. An enabled switch does not establish that a BMC has been discovered: Core also needs management network access and site credentials.

For an existing paused site with automatic creation off, choose **Enable site discovery**. Confirmation updates the mounted Core site ConfigMap and rolls Core; a single-replica API may be briefly unavailable. The discovery row in the site overview shows **Enabling** during the rollout and checks the live switch automatically afterwards. Do not resubmit while it is updating. If Helm or GitOps still supplies older values, set `[site_explorer].enabled` to `true` there as well to retain the change on future deployments. Saving unrelated site settings does not resume a paused site.

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

The site page displays **DHCP / PXE boot addresses** separately from the **installation-material HTTP endpoint**. Use **Manage boot network (管理引导网络)** as the single entry for these settings and the DHCP mode. In the default **Nico DHCP** mode, values are read from Kea; applying them updates DHCP Option 54 and PXE/DNS/NTP advertisement settings, then rolls DHCP. In **External DHCP** mode, enter the complete boot HTTP endpoint and configure a fixed lease for the planned boot MAC/IP. PXEye keeps Kea stopped and leaves its allocation settings unchanged. It does not inspect, create, modify or take ownership of external Services, proxies or relays. See [external DHCP provisioning](../external-dhcp.md) for Core/Scout and hardware requirements.

Choose one of the two radio options: **Nico DHCP** or **External DHCP**. Nico mode shows **Nico DHCP address** and **PXE boot server IP**; external mode shows the **Boot HTTP endpoint** and fixed-lease requirements. Selecting an option does not apply it. Previously saved addresses for the inactive mode are retained, and the preview shows only the active mode's boot fields.

This is a site default because applying external mode stops the site's shared Kea service. New tasks freeze the selected mode at creation. Per-host boot MAC/IP settings remain in Device planning.

| Boot field | Format and purpose |
| --- | --- |
| Nico DHCP address | IPv4 advertised as the DHCP Server Identifier (Option 54). |
| PXE boot server IP | IPv4 without a scheme or port; the next-server/boot server address advertised by Nico DHCP. |
| Boot HTTP endpoint | Complete `http://host:port` or `https://host:port`; embedded in external-mode bootstrap media to request `/api/v0/pxe/boot`. |
| Installation materials HTTP address and port | Publishes the bootstrap ISO and new OS versions' ISO/kernel/initrd; shared by both modes. |

The boot HTTP endpoint controls only the bootstrap medium's first request into Nico. It does not update the Core/PXE service's own ports or the service URLs in subsequent scripts. Existing service configuration must still provide reachable URLs; this setting is not a global PXE port override.

DNS and NTP addresses are optional; entered values must be valid IPv4 addresses. Leaving them blank clears the corresponding NICo DHCP hook service configuration without restoring its built-in defaults. This does not change NTP settings in installation profiles. Material or package URLs containing hostnames still require working DNS; offline sites can use internal services and IP URLs.

The installation-material HTTP endpoint comes from `os_library.public_base_url`, including the address and port reachable by target hosts, for example `http://192.0.2.10:31880/public/blobs/internal/nico/os-library`. It is the base URL for ISO, kernel and initrd published for newly created OS versions; it is not a Kea setting, and existing NICo OS definitions retain their individual immutable material URLs.

Opening or refreshing the site page runs an HTTP check against the current material endpoint. It reads response headers without downloading an ISO. The check prefers a locally published material path under the current endpoint and compares the response length: green means the material access check passed, red means the endpoint is missing or access failed, and amber means material access is not yet verified. When no published material is available, a directory response only indicates whether the HTTP service responded; a directory returning 403/404 does not by itself mean material downloads fail. The page also shows the check time and latency.

The check originates from PXEye and only affects the displayed status, not address-save validation. Reachability from the provisioning network must still be verified from that network.

This does not change HostInband segments, DHCP pools, device plans or existing installation tasks. HostInband is NICo's network object for choosing a host boot interface's DHCP segment and allocating its address; it remains in network management and device/installation checks, not in this address form.

Use a maintenance window: PXEye blocks an address change while installation tasks are active. A successful apply proves only the controlled Kubernetes update and saved mode; it is not an installation result. Validate DHCP Offer and material HTTP access from the actual boot VLAN separately. PXEye does not rewrite existing OS-definition material URLs automatically; after a material-endpoint change, create a new OS version and reference it from a new installation-plan version.

PXEye does not require DHCP topology or relay address inputs. For routed clients, configure DHCP relay on the relay device; NICo processes requests using the received `giaddr` and subnet rules.

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
- Maintain certificates, private keys and material/source directories through deployment configuration and mounts. Set the materials HTTP publication endpoint through **Manage boot network**; the page does not upload or modify certificate or material files.
- Switching Core does not migrate plans, profiles or history. Verify resource references and data ownership before switching.

Related: [Deployment](../deployment.md) · [Network management](network-management.md) · [Installation tasks](installation-tasks.md)

For a new cluster, deploy and apply the site from [NICo cluster](nico-cluster.md). An existing Core can be connected here with a valid client identity.
