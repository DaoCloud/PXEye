---
page_id: network-management
language: en
title: Network management
description: Subnet purpose, field values, creation and deletion.
navigation_group: resources
updated_at: "2026-11-08"
product_version: "0.21.7"
---

# Network management

**English** · [简体中文](network-management.zh-CN.md) · [Page guides](README.md)

## 1. Purpose and entry point

Open **Resources → Networks (资源 → 网络管理)** to inspect NICo segments and create installation subnets. Device discovery, address planning and host installation use these networks. Configure individual fixed addresses under **Device management → Address management (设备管理 → 地址管理)**.

### Network requirements

- **Service connection**: PXEye can reach NICo Core and read and create segments.
- **Address plan**: define the IPv4 subnet, gateway, MTU and reserved range. New subnets must not overlap existing NICo networks.
- **DHCP path**: client broadcasts must reach NICo DHCP. For cross-subnet access, configure DHCP relay to forward to the actual service IP on UDP `67`, with relay information matching the client subnet. Requests and responses must both be reachable; clients use UDP `68`.
- **Installation access**: NICo can reach device management interfaces, and target hosts can reach the PXE/HTTP boot and installation material services in use. Configure the required VLANs, routes and access rules.

## 2. Field values

Click **Add subnet (新增子网)** and enter the site plan:

| Field | Requirement | Example |
| --- | --- | --- |
| Name (子网名称) | Required; 1–128 English letters, digits, `_`, `.` or `-`. No spaces, Chinese characters or `static-assignments`. | `host-install` |
| Type (网络类型) | Choose from the table below; defaults to HostInband. | `HostInband · 主机带内` |
| CIDR (子网 CIDR) | Required; one IPv4 network address and prefix length, not a device address. | `192.0.2.0/24` |
| Gateway (网关) | Enter the actual gateway for cross-subnet access. Must be inside the subnet and not its network or broadcast address. | `192.0.2.1` |
| MTU | Defaults to `1500`; integer `576–9216`, matching the site link. | `1500` |
| Initial reservation count (起始保留地址数) | Defaults to `0`; counts from the network address. Non-negative and smaller than the subnet's total address count. | `11` reserves `.0–.10` in this example. |
| DNS subdomain UUID (DNS 子域 UUID) | Required for HostInband; an existing NICo DNS subdomain UUID, not a DNS server IP. | Copy from **View (查看)** on an applicable existing segment. |
| Policy (地址策略) | Creation currently supports **Dynamic allocation (动态分配)** only. | `动态分配` |

| Type | Usage |
| --- | --- |
| HostInband · 主机带内 | Direct host boot/management connectivity; BMC sharing depends on site design. |
| Admin · 管理 | Host management before tenant assignment in the managed-DPU model. |
| Underlay | DPU and other foundational connectivity/management networks, following site design. |

## 3. Actions

### View

Click **Refresh data (刷新数据)**, locate the segment and click **View (查看)** to check type, prefix, gateway, MTU and associated interfaces. Existing segment names and network settings cannot currently be edited.

### Create

1. Click **Add subnet (新增子网)**, complete the fields and check the values.
2. Click **Create in NICo (创建到 NICo)**. The system validates format and prefix overlap, creates the segment and reads back its configuration.
3. Find the new record in the list and click **View (查看)** to confirm it matches the plan.

### Delete

1. Confirm the segment is unused, remove device plan references and release associated interfaces/addresses.
2. Click **Delete (删除)**, check the name and range, select the confirmation checkbox and submit.
3. Follow **Subnet deletion progress (子网删除进度)** and refresh until the segment disappears.

If deletion is disabled, read the adjacent reason. Internal, tenant and site-configuration-owned segments cannot be deleted here.

## 4. Example

These are documentation-only addresses. Replace them with the actual site plan.

| Setting | Value |
| --- | --- |
| Name / Type | `host-install` / `HostInband · 主机带内` |
| CIDR / Gateway | `192.0.2.0/24` / `192.0.2.1` |
| MTU / Initial reservation count | `1500` / `11`, reserving `.0–.10`. |
| DNS subdomain UUID | An existing NICo DNS subdomain UUID applicable to this network. |
| Policy | `动态分配` |

Click **Create in NICo (创建到 NICo)** after checking the values. Actual allocations must also be excluded from `.11–.254` before dynamic allocation. The allocator separately excludes gateway, network and broadcast addresses; do not count them again on top of the reservation range.

## 5. Notes

- **Verification**: a listed segment or `READY` status does not establish DHCP availability; an actual client must obtain an address from the expected network.
- **Policy**: labels mentioning site configuration or creation default describe configuration sources and do not confirm the current allocator policy. Unconfirmed (待确认) means it cannot be determined.
- **Errors**: after a create/delete timeout, refresh and verify NICo state before another submission. Wait if another operation is running.

Related: [Pre-installation checklist](../pre-installation-checklist.md) · [Install your first server](../getting-started.md) · [NVIDIA network configuration](https://docs.nvidia.com/infra-controller/documentation/provisioning-day-0/ip-and-network-configuration)
