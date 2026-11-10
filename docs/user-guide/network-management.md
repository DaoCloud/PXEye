---
page_id: network-management
language: en
title: Network management
description: Create installation subnets and review DHCP relay, reservations and device subnet bindings.
navigation_group: resources
updated_at: "2026-11-10"
product_version: "0.22.14"
---

# Network management

**English** · [简体中文](network-management.zh-CN.md) · [Page guides](README.md)

## 1. Purpose and entry point

Open **Resources → Networks (资源 → 网络管理)** to inspect NICo segments and create installation subnets. Device discovery, address planning and host installation use these networks. Configure individual fixed addresses under **Device management → Address management (设备管理 → 地址管理)**.

### Network requirements

- **Service connection**: PXEye can reach NICo Core and read and create segments.
- **Address plan**: define the IPv4 subnet, gateway, MTU and reserved range. New subnets must not overlap existing NICo networks.
- **DHCP path**: client broadcasts must reach NICo DHCP. For cross-subnet access, configure DHCP relay to forward to the actual service IP on UDP `67`. Requests and responses must both be reachable; clients use UDP `68`. Relay `giaddr` should belong to the client's NICo subnet. This page neither accepts `giaddr` nor configures switch relay.
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
| DNS domain (DNS 域) | Automatically associated; no UUID input is required. Select by name when multiple domains cannot be resolved automatically. HostInband requires an existing eligible site DNS domain. | `example.internal` |
| DHCP start / end (DHCP 起始 / 结束地址) | Optional; fill both or leave both blank. Inclusive IPv4 bounds in this subnet, excluding the gateway. Explicit bounds replace the initial reservation count. | `192.0.2.100` / `192.0.2.200` |
| Policy (地址策略) | Creation currently supports **Dynamic allocation (动态分配)** only. | `动态分配` |

| Type | Usage |
| --- | --- |
| HostInband · 主机带内 | Direct host boot/management connectivity; BMC sharing depends on site design. |
| Admin · 管理 | Host management before tenant assignment in the managed-DPU model. |
| Underlay | BMC, DPU, switch BMC/NVOS and power shelf PMC infrastructure management, following the actual NICo topology. |

## 3. Actions

### View

Click **Refresh data (刷新数据)**, locate the segment and click **View (查看)** to check type, prefix, gateway, MTU and associated interfaces. Existing segments support separate DHCP pool configuration; name, CIDR, gateway and MTU remain read-only. Set MTU under **Add subnet**; it defaults to 1500. Existing segment details show MTU without an edit control. Device planning sheets do not define MTU; additional static interfaces inherit their subnet MTU during installation.

### Create

A DNS domain groups device hostnames and address records; it is separate from the DNS server IP. NICo generates the domain UUID when creating the domain object. Adding a subnet reuses an existing domain. The console uses the only eligible infrastructure forward domain, or the single domain shared by existing HostInband segments. Otherwise, select a domain by name. Deleted, reverse and tenant domains are excluded.

1. Click **Add subnet (新增子网)**, complete the fields and check the values.
2. Click **Create in NICo (创建到 NICo)**. The system resolves the DNS domain, validates format and prefix overlap, creates the segment and reads back its configuration. There is no separate Save draft step.
3. Find the new record in the list and click **View (查看)** to confirm it matches the plan.
4. For server management, choose this HostInband range under **Device management → System configuration (设备管理 → 系统配置)**. The planning CSV's `management_subnet` must exactly match an existing subnet CIDR.

### Configure a DHCP pool

1. Click **View → Configure DHCP pool (查看 → 配置 DHCP 地址池)** for the subnet and enter the first and last IP, for example `192.0.2.100` through `192.0.2.200`.
2. Click **Apply (应用)**. The list shows the range read back from NICo. The subnet remains `192.0.2.0/24`; fixed addresses are managed separately.
3. Leave both endpoints blank and apply to restore subnet allocation with the initial reservation count.

If existing dynamic allocations fall outside the requested range, the change fails with their addresses and preserves the current configuration. Leases are never reclaimed. Occupied and fixed addresses inside the pool are not allocated again. This supports site segments with exactly one IPv4 prefix; it does not change IPv6 or tenant networks. Unsupported Core versions show an upgrade message and cannot submit a ranged configuration. See [deployment requirements](../deployment.md#dhcp-address-pool-support).

### Delete

1. Confirm the segment is unused, remove device plan references and release associated interfaces/addresses.
2. Click **Delete (删除)**, check the name and range, select the confirmation checkbox and submit.
3. Follow **Subnet deletion progress (子网删除进度)** and refresh until the segment disappears.

Internal segments show an explanation without a Delete button. For other segments, read the adjacent reason when deletion is disabled. Tenant and site-configuration-owned segments cannot be deleted here.

## 4. Example

These are documentation-only addresses. Replace them with the actual site plan.

| Setting | Value |
| --- | --- |
| Name / Type | `host-install` / `HostInband · 主机带内` |
| CIDR / Gateway | `192.0.2.0/24` / `192.0.2.1` |
| MTU / Initial reservation count | `1500` / `11`, reserving `.0–.10`. |
| DNS domain | Automatically uses an existing site domain; select by name when needed. |
| Policy | `动态分配` |

Click **Create in NICo (创建到 NICo)** after checking the values. Actual allocations must also be excluded from `.11–.254` before dynamic allocation. The allocator separately excludes gateway, network and broadcast addresses; do not count them again on top of the reservation range.

## 5. Notes

- **Verification**: a listed segment or `READY` status does not establish DHCP availability; an actual client must obtain an address from the expected network.
- **Fixed addresses**: creating a subnet does not change devices to planned IPs. Apply BMC updates separately; installation tasks apply host management addresses.
- **Policy**: labels mentioning site configuration or creation default describe configuration sources and do not confirm the current allocator policy. Unconfirmed (待确认) means it cannot be determined.
- **Errors**: after a create/delete timeout, refresh and verify NICo state before another submission. Wait if another operation is running.

Related: [Device management](device-management.md) · [Pre-installation checklist](../pre-installation-checklist.md) · [Install your first server](../getting-started.md) · [NVIDIA network configuration](https://docs.nvidia.com/infra-controller/documentation/provisioning-day-0/ip-and-network-configuration)
