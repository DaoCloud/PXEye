---
page_id: device-management
language: en
title: Device management
description: Arrival plans, discovery, enrollment and address configuration matching by serial number.
navigation_group: resources
updated_at: "2026-11-08"
product_version: "0.21.25"
---

# Device management

**English** · [简体中文](device-management.zh-CN.md) · [Page guides](README.md)

## 1. Purpose and entry point

Open **Resources → Device management (资源 → 设备管理)** to import arrival plans, discover and enroll devices, then apply plans to the corresponding server configuration.

| Tab | Purpose |
| --- | --- |
| Discovered devices (发现设备) | Inspect DHCP endpoints, authenticate with BMC / PMC credentials and enroll the identified device. |
| Managed devices (纳管设备) | View existing devices and use matching, system configuration and address management. This tab opens by default. |
| Device plans (设备规划) | Import or edit serial numbers, addresses, MACs, management subnets and racks; compare them with enrolled device configuration. |

Device plans are stored separately. Continue the existing discovery, authentication and enrollment steps after import; imported plans do not automatically become managed devices.

Device plans is the last tab. Search by SN, IP, MAC or rack; the search field and table text use the shared device management styles.

## 2. Field values

Download the CSV template under **Device plans** with one host per row, or use **New plan (新增规划)** to enter a single host.

| CSV field | UI field | Requirement |
| --- | --- | --- |
| `serial` | Device SN | Required and unique; must exactly match the managed device serial number. |
| `management_ip` | Management IP | Planned host management IPv4; requires a management MAC. |
| `management_mac` | Management MAC | MAC of the actual host management/boot interface. Matching selects this port even when the management IP and subnet are blank. |
| `management_subnet` | Management subnet | CIDR such as `192.0.2.0/24`; requires a management MAC. |
| `bmc_ip` | BMC IP | Planned BMC IPv4, rather than the temporary discovery address. |
| `bmc_mac` | BMC MAC | When supplied, must match the enrolled device BMC MAC. |
| `rack` | Rack | Used for display and comparison. Matching does not change rack membership. |

CSV headers must contain all seven columns. Fields other than SN may be empty. When updating an existing plan, blank CSV cells preserve saved values; use **Edit plan (编辑规划)** to clear them. Management subnets display their ranges without names.

## 3. Actions

### Import and edit

1. Under **Device plans**, select **Download template (下载模板)**, fill in the CSV and select **Import plans (导入规划)**.
2. Select **Validate and preview (校验并预览)** and review new, updated, unchanged and invalid rows. Correct errors and preview again.
3. Select **Save imported plans (保存导入规划)**. Use **Edit plan** to change any row, including its SN.

### Discover and enroll

1. Enable DHCP on the device and provide working request and response paths to NICo.
2. Under **Discovered devices**, select **Get device information (获取设备信息)** for the endpoint and enter valid BMC / PMC credentials.
3. For devices sharing credentials, select endpoints (or all eligible endpoints in the current filtered list) and click **Get device information in bulk (批量获取设备信息)**. The dialog contains only shared username and password fields and uses the selected devices’ observed management addresses. No second device list or address selection is required. Each batch supports up to 50 endpoints with four concurrent reads. Changing the discovery subnet clears selection; conflicting endpoints and those without a usable management IPv4 cannot be selected.
4. Review each device’s SN, type, model and success or failure. Results remain on the current page and can be reopened with **View retrieval results (查看获取结果)**. Retry failed devices as a separate batch with the correct credentials; other devices continue independently.
5. Select **Review and enroll (确认并纳管)** or **Confirm device information (确认设备信息)**, verify the details, then click **Add to managed devices (加入纳管设备)**. Review devices one at a time from the batch results without re-entering credentials. The managed list retains the detected type.

Retrieval reads only already-discovered endpoints; it does not automatically enroll devices or change hardware. Passwords are excluded from browser state and results. The server retains restricted identity proofs for subsequent enrollment. Proofs expire after 15 minutes; reload the information after a full page refresh, address/ownership change or proof expiry.

Discovery information retrieval and **Refresh device details (刷新设备详情)** use the same identification rules for physical servers, NVLink switches and supported power shelves. Refresh also verifies the device serial number and management MAC; identity or type conflicts are reported as failures.

### Match plans

1. In [Network management](network-management.md), create a HostInband subnet with the exact planned CIDR and configure its actual gateway.
2. Under **Managed devices**, select servers and click **Match plans (一键匹配)**. Each operation supports up to 50 servers.
3. Review per-device results. Matching associates plans by unique SN, verifies management MAC ownership against collected hardware, then saves the target BMC address, management interface and subnet configuration.
4. Use **Update BMC address (更新 BMC 地址)** to apply the BMC address. Installation tasks apply host management configuration. Maintain installation profiles and OS accounts under **System configuration (系统配置)**.

The plan page's **Configuration matches (配置一致)** means the plan matches saved device configuration. Match again after editing the source plan.

## 4. Example

These are fictional values; replace them with the actual site plan:

```csv
serial,management_ip,management_mac,management_subnet,bmc_ip,bmc_mac,rack
SERIAL-1,192.0.2.10,02:00:00:00:00:21,192.0.2.0/24,198.51.100.10,02:00:00:00:00:20,RACK-01
```

After enrolling the server with SN `SERIAL-1`, matching selects `02:00:00:00:00:21` as its management/boot port and references the existing `192.0.2.0/24` subnet. The netmask and gateway come from that subnet.

## 5. Notes

- **Matching requirements**: Only unique server SN matching is supported. The management MAC must exist in collected hardware, and the subnet must match exactly and uniquely. Retrieve device details first if hardware information is missing.
- **Credentials and effects**: Matching preserves BMC and OS credentials. It does not change Redfish addresses, allocate DHCP addresses, reboot devices or install an OS.
- **Errors and concurrency**: A failed device is not saved; other valid devices can continue. Refresh and match again if a plan or device configuration changes. Finish outstanding address operations first.
- **Format**: Planning CSV files support up to 1 MiB and 5,000 rows. Legacy Expected Machine CSV/Excel files use a different format; transfer their values to this page's template.

Related: [Pre-installation checks](../pre-installation-checklist.md) · [First-server installation](../getting-started.md) · [NVIDIA host ingestion](https://docs.nvidia.com/infra-controller/documentation/provisioning-day-0/ingesting-hosts)
