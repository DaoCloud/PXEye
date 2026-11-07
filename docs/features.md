# Features and support boundaries

**English** · [简体中文](features.zh-CN.md) · [Documentation](README.md)

This guide describes current code capabilities. UI rendering, fixture-based demonstrations and physical hardware validation provide different evidence. Validate the workflow against your NICo revision and hardware before using it for delivery.

## Rack topology

Group servers, DPU endpoints, NVLink switches and power shelves by rack. View serial numbers, observed management addresses and reported power state. Drag devices within their category and save display order in PXEye SQLite. Layout changes do not change NICo Rack membership, U positions or cabling. A green indicator means the latest reported power state is on; it is not an OS health check.

## Discovery and enrollment

Read endpoints observed by NICo DHCP and filter them by source network. Use administrator-supplied shared credentials to retrieve Redfish identity, including serial number, model and supported interfaces, then select devices for enrollment. Discovery does not start Scout, erase disks or install an OS.

DHCP discovery requires an enabled DHCP client and correctly routed requests. A controller configured with an unknown static address cannot be discovered merely by receiving power. Without BMC connectivity and authentication, DHCP information generally cannot identify a physical unit reliably.

## Device and address management

Import CSV or Excel inventories, edit individual device plans and keep their revisions. Server plans include BMC and host management addresses, boot MAC, hostname, target OS and profile. Other equipment uses address management without the server-installation workflow.

Saving a plan persists product data and derived files. Batch actions perform separate operations:

| Action | Effect |
| --- | --- |
| Update BMC address | Preflight the target and identity, configure a supported Redfish management interface, verify the new address and synchronize records. |
| Update management address | Operate on supported management endpoints; available behavior depends on device type and the interface driver. |
| Refresh device details | Read hardware identity and supported interface details; does not change addresses. |

The list distinguishes current and planned addresses. Expected Machine declarations and interface-address records are synchronized where supported; a NICo reservation alone does not reconfigure a controller already using a static IP. These operations cannot force every device to renew DHCP.

## Network management

Inspect NICo `NetworkSegment` prefixes, gateways, MTU, interface references and allocations. Maintain local drafts separately from live Core configuration. The current create form exposes HostInband, Admin and Underlay with dynamic allocation. Existing live segments are read-only in the current UI; native in-place updates are not available in the integrated revision. Deleting a local draft does not delete its live segment. Deleting an occupied live segment remains subject to NICo lifecycle constraints.

OS DNS is maintained through network management as PXEye installation data, frozen into the task and rendered into the target OS network configuration. It is not a native NetworkSegment DNS field. DHCP DNS is supplied to the requesting interface as lease information and may differ from OS DNS. Relay `giaddr` and site configuration determine which segment matches a request. PXEye does not configure relay, VLANs or ACLs on switches.

## Operating-system library

Upload ISO chunks or import from a read-only directory mounted in the PXEye service. Validate file size and SHA256, identify supported Ubuntu media and extract kernel/initrd. Publish the files through a host-reachable artifact service, then register the NICo OS definition. Enable or disable definitions and inspect their references. Only the version used by an active installation is locked.

A custom ISO still needs a supported unattended installer. NICo's Scout boot artifacts serve discovery and cleanup; user OS media has a separate lifecycle.

## Installation profiles

Profiles are PXEye composition resources, not a native NICo resource of the same name. Reuse OS selection and installation defaults. Select the system disk using a unique match, capacity ordering, bus constraints, model/serial glob filters and capacity bounds. Define GPT/UEFI partitions with EFI plus ext4 or XFS root storage.

Explicit device settings override profile defaults where applicable. Task creation freezes the resolved configuration and its sources. Boot interface and disk identity are resolved for the specific machine rather than assuming a universal interface name or disk path. Ambiguous selection blocks writing.

## Installation execution

Check identity, networking, artifacts, resource occupancy and disk scope. For first installation, request hardware preparation and create an Instance when needed; reinstall uses an existing Instance. Render controlled autoinstall data and launch PXE/iPXE through NICo boot control. Collect SOL output and installer events.

After installation, use task-specific SSH identity to inspect hostname, root disk, EFI, network and the installation receipt, then verify a normal reboot. Uncertain external writes retain evidence and require readback or an explicit recovery action instead of blind replay.

Scout runs in the discovery environment before the business OS is installed. Site ingestion policies may clean all disks or apply credential, BIOS and firmware settings. This scope differs from writing the selected OS system disk.

## Instances and site

Inspect Instances and associated Machines, OS definitions and lifecycle state. Release initiates NICo reclamation and may trigger cleanup; it is not deletion of a UI record. Track actual progress and reported failures.

Site settings display Core connectivity, the mTLS client identity, storage and configured service endpoints. Limited name/Core edits are validated using the current identity. Service indicators distinguish TCP reachability, configuration presence and protocol checks.

## Current operating envelope

- One site, one service replica, one operator and serial installation execution.
- No distributed queue, multi-site management or complete user/tenant RBAC.
- Principal physical validation: Ubuntu Server 24.04, x86_64 and UEFI.
- ARM64, GB200/GB300, other distributions and OEM-specific boot behavior require separate validation.
- DPU, NVLink switch and power-shelf write operations depend on their actual management interfaces.

See the [architecture](architecture.md), [operator guide](getting-started.md) and [security policy](../SECURITY.md).
