---
page_id: device-management
language: en
title: Device management
description: Device plans, discovery, enrollment, address updates and server system configuration.
navigation_group: resources
updated_at: "2026-11-09"
product_version: "0.22.5"
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

Seven-column arrival plans are stored separately. Continue the existing discovery, authentication and enrollment steps after import; imported plans do not automatically become managed devices. See section 6 for five-column interface plans.

Device plans is the last tab. Search by SN, IP, MAC or rack.

## 2. Field values

### Arrival plans

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

### Server system configuration

Under **Managed devices**, click the server's **System configuration (系统配置)**:

| Field | Requirement |
| --- | --- |
| Device name / rack ID (设备名称 / 机柜 ID) | Name is for display. Use an actual NICo Rack ID, rather than the CSV's rack display name. |
| BMC username / password (BMC 用户名 / 密码) | Valid controller credentials; empty password preserves the existing one. Maintain these separately from OS credentials. |
| Planned BMC IP / policy / subnet (BMC 规划 IP / 地址策略 / 子网) | Use the actual plan. Fixed addresses must be in the corresponding subnet; apply BMC updates separately after saving. |
| Boot NIC MAC / management IP / subnet (启动网卡 MAC / 管理 IP / 管理子网) | Choose the actual PXE / OS management port and an existing HostInband range. |
| Hostname (主机名) | 1–63 lowercase letters, digits or `-`; first and last characters must be letters or digits, such as `gpu-01`. |
| Current installation profile (当前安装方案) | A published, active [Installation profile](installation-profiles.md) version. |
| Next installation disk (下次安装系统盘) | First installation can use profile rules; reinstallation can retain the current disk. Alternatively choose a disk from collected hardware. |
| Device overrides (设备覆盖设置) | Inherit OS, username, login mode, password and keys from the selected profile or set per-device values. Inheriting a password hides its field. OS passwords use 8–128 characters without newlines; enter one complete public key per line. |

### Switch and power shelf configuration

| Field | Requirement |
| --- | --- |
| Device SN / name (设备 SN / 名称) | SN identifies the device uniquely and is read-only after registration; name is for display. |
| BMC / PMC MAC, target IPv4, management network | Actual interface and planned address, with an existing Underlay subnet. |
| BMC / PMC credentials and retention | Valid credentials; empty passwords preserve existing values. Choose credential handling according to device and site policy. |
| Rack UUID (机柜 UUID) | Optional actual NICo Rack UUID. |
| NVOS management interfaces (NVOS 管理接口) | Switches only: interface MACs and Underlay subnets. Target NVOS IPv4 supports one management port only; provide NVOS credentials as needed. |
| Description and labels (说明与标签) | Optional. Labels are a JSON array, such as `["rack-a"]`. |

### Interface address plans

Under **Address management → Plan address (地址管理 → 规划地址)**, verify MAC, current IPv4 and management subnet, then enter **Planned IPv4 (规划 IPv4)**. BMC / PMC interfaces may hold their own credentials; an empty password preserves the existing one. Device name, type and interface role identify the endpoint.

## 3. Actions

### Import and edit

1. Under **Device plans**, select **Download template (下载模板)**, fill in the CSV and select **Import plans (导入规划)**.
2. Select **Validate and preview (校验并预览)** and review new, updated, unchanged and invalid rows. Correct errors and preview again.
3. Select **Save imported plans (保存导入规划)**. Use **Edit plan** to change a row. Its SN can be changed only while it has no hardware-linked interface plan.

**Import devices / Download template (导入设备 / 下载模板)** in the managed list asks for a device type. Servers use the same planning CSV. Switches and power shelves have separate templates with JSON for nested fields; preview them and click **Confirm saving local plans (确认保存本地规划)**. **New device (新增设备)** enters one device by type. For non-server local plans, separately click **Synchronize to NICo (同步至 NICo)**, review the declaration and impact, enter SN and confirm enrollment. Synchronization may start native device management and credential handling.

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

### Save configuration and update addresses

1. Enter server settings in **System configuration** and click **Save plan (保存规划)**. Addresses can also be maintained through **Address management → Plan address → Save plan**. Saving does not immediately install or change addresses.
2. To update BMC / PMC, select devices in the managed list, click **Update BMC address (更新 BMC 地址)**, read the impact and click **Confirm and start update (确认并开始更新)**.
3. Follow **Check address and identity → Update BMC → Verify new address → Synchronize records (检查地址与身份 → 更新 BMC → 验证新地址 → 同步管理记录)**. Eligible devices disable DHCP and receive the planned static address through Redfish; failed checks show their reasons.
4. Submitted operations continue after closing the dialog and can be reopened from recent update records. For errors, use **Recheck and update (重新检查并更新)** or **Verify and finish synchronization (核对并完成同步)** as offered.
5. [Installation tasks](installation-tasks.md) apply server management addresses and OS configuration. **Update management address (更新管理地址)** provides only Redfish preflight for supported interfaces; it cannot replace host OS networking configuration.

Double-click a device row or click its name for details. Select devices and click **Refresh device details (刷新设备详情)** to start a background task; review the hardware update time and results after completion.

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
- **Format**: Server planning CSV files support up to 1 MiB and 5,000 rows; switch/power shelf templates support up to 2 MiB. Legacy Expected Machine CSV/Excel files use a different format; download the template for the selected entry point.
- **Other devices**: Switches and power shelves have their own system configuration and address management; they do not receive server OS installation tasks. Unknown DHCP endpoints can have address plans without being treated as authenticated, installable servers.

## 6. Export and import interface addresses

1. Retrieve server information in **Discovered devices**, select servers and click **Export device interface list (导出设备网卡列表)**. Managed servers can also be selected for export; select 1–50 per export.
2. The file is named `device-interfaces.xlsx` with the header `serial,mac,pci_address,ip,subnet,gateway` and one row per collected host port. Columns and rows are enlarged and sized for their contents, with wrapping and grid borders on every cell, including blank address cells. The header is frozen and supports filtering. Identity-verified Scout inventory, BMC refresh and enrollment discovery are combined and deduplicated by MAC. Saved IPs, subnet CIDRs and gateways are included; unconfigured values stay blank. Keep SN/MAC and fill the blanks. Completely blank address rows preserve existing settings. Temporary DHCP leases are not exported as planned addresses.
3. Use the existing **Import devices → Server** or **Import plans** action, upload the completed Excel file, review and save. Existing five-column CSV files remain supported. No subnet IDs, netmasks or NICo JSON are required.
4. Managed servers receive updates in the existing device interface structure and **System configuration**. Reopening the same device shows each MAC's IP, subnet and gateway; subsequent exports include the saved values. Unenrolled servers retain a source plan which is applied after explicit enrollment. If application fails, correct the issue and use existing **Match plans** to retry.
5. Confirm the existing boot interface, installation profile and other requirements, then install normally. Ubuntu matches interfaces by MAC. First-boot and reboot acceptance check their addresses, prefix lengths and MTUs.

The managed-device header checkbox selects or deselects only the current filtered list. It stays checked when all visible rows are selected; click again to deselect them. **Clear selection (清空选择)** also clears hidden selections. With mixed device types selected, interface export includes only servers; the note below the action bar shows included and excluded counts. Switches, power shelves and address-only records are excluded from the host OS interface sheet. **Match plans** still requires a server-only selection.

If a subnet has not been created, preview identifies the failed device by SN and shows MAC, IP, CIDR and the reason. Gateway mismatches, ownership errors and address conflicts also report their causes. Any validation error prevents the entire batch from being saved; other preview rows do not represent successful imports. Create the required HostInband subnet or correct the spreadsheet, then preview and confirm again. Import never creates subnets automatically.

```csv
serial,mac,pci_address,ip,subnet,gateway
SERVER001,02:00:00:00:01:01,0000:3b:00.0,192.0.2.11,192.0.2.0/24,192.0.2.1
SERVER001,02:00:00:00:01:02,0000:3b:00.1,198.51.100.11,198.51.100.0/24,
```

The example shows the six Excel columns as text. `pci_address` is observed information: discovery and device-detail refresh share the same parser, and device details also show it. Missing, ambiguous or conflicting reports leave it blank; a missing PCI domain is never invented. Fill only the three address columns. Import ignores the PCIe column and never changes hardware identity. Legacy `serial,mac,ip,subnet,gateway` CSV files remain accepted through the same entry point.

These are documentation addresses. One row represents one port; serials may repeat, MACs and IPs must not. The limit is 5,000 rows and 1 MiB.
Each CIDR must exactly match a unique existing single-IPv4-prefix HostInband network. Gateways must agree with the network definition; leave blank only when the network has no gateway.
Import preserves credentials and boot selection. A server without a boot interface still needs an explicit selection in System configuration; CSV order never selects it. The selected host interface has `primary: true`, with at most one per server. Change it in **System configuration → Host management and boot port → Boot NIC MAC (系统配置 → 主机管理与启动口 → 启动网卡 MAC)**. The seven-column arrival plan can also change it through `management_mac` followed by **Match plans**. This per-MAC interface sheet does not contain a primary flag.
Previews expire after 15 minutes. Device, hardware, source-plan or network changes and address conflicts block saving the batch; no partial import occurs. Installation tasks, outstanding attention items and address-operation records do not block saving a future plan. Running tasks retain their frozen revisions; execution entry points still check task and address-operation state.

**Multiple ports on one server:** Independent physical ports may use the same or overlapping subnets; bonds or VLANs are not required. Address format, hardware ownership, existing subnet/gateway definitions and IP conflicts are still validated.

**Routing and application:** Only the existing management interface supplies the default route. Additional interfaces inherit the subnet MTU; their gateway is retained without inventing extra default or destination routes.
Saving does not change the running OS, BMC or switch. Changes apply during the next installation; differences between source plans and system configuration remain visible.
This feature covers collected host Ethernet MACs, excluding BMC/DPU management ports, InfiniBand, bonds, VLANs, IPv6 and policy routing.
If the BMC omits ports, use the existing hardware information workflow to obtain Scout inventory. Export never starts Scout or reboots a machine.

Related: [Network management](network-management.md) · [Installation profiles](installation-profiles.md) · [Installation tasks](installation-tasks.md) · [Pre-installation checks](../pre-installation-checklist.md) · [NVIDIA host ingestion](https://docs.nvidia.com/infra-controller/documentation/provisioning-day-0/ingesting-hosts)


### Edit interface addresses in equipment planning

Edit planning lists collected host MACs and existing interface plans. Edit IP, subnet CIDR and gateway per MAC; MAC and PCIe identities are read-only. When the management MAC is listed, its management IP/subnet fields mirror that interface. Blank interfaces preserve existing configuration. Saving reuses spreadsheet import validation and atomic application. Enrolled interface changes are saved to system configuration for the next installation; device-level fields still require Match planning.

The table and editor display the matched subnet's actual MTU, including defaults. Network management remains the sole MTU configuration source. Missing, ambiguous or unreadable networks show an unavailable indication. Search covers SN, IP, MAC, rack and saved interface plans.

The managed list shows management addresses without role prefixes. Server, switch and power-shelf controller columns share current address, planned address and MAC formatting. Status cells omit raw JSON. Server registration creates a paused ExpectedMachine; switches and power shelves store Expected-shaped declarations locally without submitting them to NICo.


### Local switch and power-shelf management

Enrollment stores real serial, controller MAC, address and credentials in SQLite `equipment_records`, using ExpectedSwitch / ExpectedPowerShelf declaration fields. NVOS data may remain empty; no mock values are generated. Local records display Local managed; existing native assets keep their original status. System configuration and Sync to NICo actions are hidden for both types. Details and address management remain available; the server workflow is unchanged.

Plan an address in Address management, then run Update BMC address. Controller address intent and credentials come from the local declaration. After identity and Redfish address verification, the service records the actual address and synchronizes the NICo interface static allocation without creating or patching ExpectedSwitch / ExpectedPowerShelf. Existing native declarations can therefore retain their previous addresses; their complete lifecycle is outside this local management workflow. Unsupported DHCP/IPv4 writes return an explicit failure.

Upgrade imports historical equipment plans and versions into SQLite, preserving original files and history. Historical controller address overrides and credentials for matching local devices migrate once. SQLite is authoritative thereafter. Incomplete native-only assets require identity collection and a local record before address updates; identities and credentials are never guessed.
