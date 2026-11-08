# Install your first server

**English** · [简体中文](getting-started.zh-CN.md) · [Documentation](README.md)

This guide follows one server from enrollment to OS acceptance. Begin with a dedicated device and a prepared [deployment](deployment.md); complete the [pre-installation checklist](pre-installation-checklist.md) at its discovery and OS-writing stages, then expand the batch after confirming that hardware's workflow.

## 1. Check the site and networks

For network field values and actions, see the [network management guide](user-guide/network-management.md).

Open **Site settings (站点设置)** and inspect Core connectivity, client identity and storage. In **Networks (网络管理)**, confirm the BMC discovery segment and host boot/management segment. Arrange relay and routing outside PXEye. Use the OS DNS editor in network management for the target system's DNS servers.

An unknown BMC address is discoverable through DHCP only when the BMC DHCP client is enabled and its requests reach NICo. Controllers with unknown static addresses need an external network or inventory procedure first.

## 2. Prepare the operating system

In **Operating systems (操作系统)**, upload a supported Ubuntu ISO or import it from the configured source directory. Directory paths belong to the PXEye service runtime. Wait for extraction and publication checks, register the OS with NICo, then confirm it is available for selection.

Your ISO replaces the target installation media, not Scout's discovery environment. The target host must reach the ISO, kernel, initrd and installer metadata URLs.

## 3. Discover and enroll devices

In **Device management → Discover devices (设备管理 → 发现设备)**, select the source BMC network and refresh. Supply the controller credentials and use **Get device information (获取设备信息)** to retrieve identity. Match serial numbers and device types to the received hardware before enrollment.

For a prepared inventory, use **Import devices (导入设备)** with the downloadable CSV/Excel template. Imports save plans; they do not install machines automatically.

## 4. Save addresses and installation settings

In **Managed devices (纳管设备)**, edit address plans by controller/interface MAC. Review observed and desired BMC addresses separately. Use **System configuration (系统配置)** on servers to choose hostname, target OS, account and profile.

Create the reusable profile in **Installation profiles (安装方案)**. Choose a disk rule appropriate to the fleet and a partition strategy. Hardware reports resolve the rule to the target disk; avoid relying on a guessed `/dev/sdX` name. Device overrides take priority where applicable.

Saving is independent of execution. If the BMC address needs to change before installation, select the devices and use **Update BMC address (更新 BMC 地址)**. Its workflow checks identity, updates the controller, verifies the new address and synchronizes records. Retain access to the existing management network throughout migration.

Switches, DPU endpoints and power equipment stop at enrollment/address management; do not create server OS tasks for them.

## 5. Create an installation task

Open **Installation tasks (安装任务)**, select the server and create a task. The workflow determines whether an Instance must be allocated or reused. Review the effective OS, address, hostname, disk selection and cleanup scope before confirmation.

For first ingestion, NICo may boot Scout and apply the site's hardware-preparation policy. Site cleanup can cover all disks, independently of the OS system-disk selection. Confirm that scope for the intended device.

## 6. Follow execution and acceptance

The task view links to the BMC console and persistent logs. Monitor preparation, installation, system-disk handoff, SSH verification and normal-reboot verification. A completed task requires acceptance evidence, not just an installer login screen.

If a task needs attention, read its specific error and logs, confirm the actual host state, then use its scoped recovery action. Changes to a saved device plan do not change an already frozen task; a recovery action describes which plan it will use.

## 7. Retain the delivery record

Download the acceptance report when available. Preserve the task record, effective plan, logs and receipts with the data volume. Instance release is a separate reclamation workflow and may clean the device; it is not removal of installation history.
