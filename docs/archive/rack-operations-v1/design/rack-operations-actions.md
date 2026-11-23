# Rack operations: rules for operations

**English** · [简体中文](rack-operations-actions.zh-CN.md) · [Design documents](../../../design/README.md)

> **Archived (2026-11-23).** This document belongs to a design that the whole-rack design has superseded. It is no longer maintained and is kept as it was when archived, for reference only. See the current [design documents](../../../design/README.md) and the [archive index](../../README.md).

- Status: **implemented behind the `rackActions` switch, not verified at a site.** No write has been sent to a real Core. The operations were run only against `tools/core-replay.py --demo-writes` on the demo capture.
- Scope: operations that change a device or a rack through NICo Core. Read-only pages are in [scope and status](rack-operations.md); implementation status per area is in the [capability requirements](rack-operations-requirements.md); request shapes and the audit table are in section 4 of the [data contract](rack-operations-data-contract.md).
- Evidence: `src/pxeye/services/rack_actions.py` and the NICo source at the site's Core version `7c7788a`. The CLI commands are the `nico-admin-cli` subcommands that call the same interface; PXEye does not run them.

## 1. Operations

PXEye calls only NICo Core; it never talks to a BMC or to RMS itself. Operations are started from the operation dialog (操作, or 批量操作) on the servers, switches and power shelves pages, and from the racks page (机柜). Every operation is listed on the operation records page (操作记录).

| Operation | NICo interface | Equivalent `nico-admin-cli` | Risk | Needs RMS | Status |
| --- | --- | --- | --- | --- | --- |
| Power on; graceful shutdown; graceful restart | `AdminPowerControl` (`On`, `GracefulShutdown`, `GracefulRestart`) | `bmc-machine admin-power-control` | Medium | No: through the host BMC | Implemented |
| Force off; force restart; AC power cycle | `AdminPowerControl` (`ForceOff`, `ForceRestart`, `ACPowercycle`) | `bmc-machine admin-power-control` | High | No: through the host BMC | Implemented |
| Maintenance mark set / clear | `SetMaintenance` (`Enable` with `reference`, `Disable`) | `managed-host maintenance on` / `off` | Low | No: NICo state only | Implemented |
| Quarantine | `SetManagedHostQuarantineState` (`BLOCK_ALL_TRAFFIC`) | `managed-host quarantine on` | High | No: NICo network control | Implemented |
| Clear quarantine | `ClearManagedHostQuarantineState` | `managed-host quarantine off` | Medium | No: NICo network control | Implemented |
| Host reset | `TriggerManagedHostReset` | `managed-host reset` | High | No | Implemented |
| BMC reset | `AdminBmcReset` | `bmc-machine bmc-reset` | Medium | No: through the host BMC | Implemented |
| On-demand validation | `OnDemandMachineValidation` (`Start`) | `machine-validation on-demand start` | High | No | Implemented |
| SKU check | `VerifySkuForMachine` | `sku verify` | Low | No | Implemented |
| Compute tray power on / off / restart | `ComponentPowerControl` (machine IDs) | `component-manager component-power-control` | Medium (on), high | Yes when `compute_tray_backend` is `rms`; no when it is `core` (NICo's own Redfish) | Implemented |
| Switch power on / off / restart | `ComponentPowerControl` (switch IDs) | `component-manager component-power-control` | Medium (on), high | Yes: switch power goes through RMS | Implemented |
| Switch reset (BMC reset, BMC / NVOS / SDN factory reset) | `ComponentReset` | `component-manager component-reset` | High | Yes: component reset goes through RMS | Implemented |
| Switch decommission | `DecommissionSwitch` | `managed-switch decommission` | High | No | Implemented |
| Power shelf power on / off | `SetPowerShelfMaintenance` (`POWER_ON`, `POWER_OFF`) | `power-shelf maintenance` | Medium (on), high | Yes when `power_shelf_backend` is `rms` | Implemented |
| Power shelf decommission | `DecommissionPowerShelf` | `power-shelf decommission` | High | No | Implemented |
| Rack maintenance (firmware, NVOS, power sequence, NMX-C) | `OnDemandRackMaintenance` | `rack maintenance start` | High | Yes: NICo orchestrates; firmware, NVOS and NMX-C steps go through RMS | Implemented |
| Terminate rack maintenance | `TerminateRackMaintenance` | `rack maintenance terminate` | Medium | Yes: as rack maintenance | Implemented |
| Component firmware update (compute tray, switch, rack) | `UpdateComponentFirmware` | `component-manager update-firmware` | High | Yes: component firmware goes through RMS | Implemented |
| Rack power on / off | — | — | High | — | Not provided by NICo (section 2) |
| Rack cold reboot | — | — | High | — | Not provided by NICo (section 2) |
| Power shelf firmware update | — | — | — | — | Not provided by NICo; not offered (section 2) |

RMS is the NVIDIA Rack Management Service, open source under Apache-2.0 ([source](https://github.com/dsx-ai-factory/nv-rms), [documentation](https://docs.nvidia.com/rms/documentation/home/)). NICo hands tray, switch and power shelf power, component reset, component firmware and the rack maintenance steps to RMS when the component manager backends are `rms`, which is the NICo chart default; `compute_tray_backend` may instead be `core`, NICo's own Redfish path. RMS supports only NVIDIA whole-rack hardware: GB200 and GB300 compute trays, NVSwitch trays, LiteOn and Delta power shelves; VR NVL72 is in development. Where Core is configured for `rms` and no RMS is deployed, these operations fail. The dialog shows the result of `GetRmsVersion` as information and does not block on it.

Not implemented by PXEye: health overrides (`InsertHealthReportOverride`, `RemoveHealthReportOverride`).

## 2. Rack-level operations NICo does not provide

- **Rack power on and off.** In NICo's rack state machine the power sequence states `PoweringOn` and `PoweringOff` are stubs. Only `PowerReset`, a graceful restart of the rack's compute hosts, is implemented; it is reached through rack maintenance with the `power_sequence` activity.
- **Rack cold reboot.** It exists only in RMS (`ExecuteColdReboot`); NICo does not call it.
- **Power shelf firmware update.** NICo does not implement it.

The racks page shows rack power on/off and rack cold reboot as disabled buttons, with the reason. Power shelf firmware update is not offered at all.

## 3. Yielding to installation

1. A target with an installation task in status `queued`, `running` or `needs_attention` is refused, whatever the operation. For a rack, the serials of the machines placed in it are checked.
2. Power, quarantine, host reset, validation and compute tray firmware are refused while the machine's NICo lifecycle state is installation-related: it starts with `HostInit`, or it starts with `Assigned` and is not `Assigned/Ready`. Maintenance marks and the SKU check are not guarded.
3. The checks run on the server at preview and again at execution; a check in the page never replaces them.
4. Not done: while an operation is in progress, the installation preflight does not refuse a new installation task for the same device. That needs the preflight to read operation records, which is protected installation code and needs its own review.

## 4. Confirmation

- Preview runs on the server and checks each target: it exists in Core, no installation task is in progress, the lifecycle state allows the operation, and required parameters are present. A batch holds at most 10 targets.
- The preview lists each target with its serial, current state, the effect of the operation and, for refused targets, the reason. Only targets that passed are run.
- A preview is valid for 5 minutes and is used once; after that the user previews again.
- A high-risk operation requires typing the serial of each target (the object ID when it has no serial).
- Setting the maintenance mark and quarantining require a reason or ticket link; for the maintenance mark it is written to Core's `reference`.

## 5. Execution and result

- The record is written with status `sent` before Core is called. Core is called once per target.
- A timeout or unknown result is **never resent automatically**. After the call the state is read back: power from `GetComponentPowerDetails`, maintenance, quarantine and SKU check from the machine object, rack maintenance from the rack object, decommission from the switch or power shelf list.
- The result is `succeeded` only when the read-back matches; `failed` when Core reports failure or the request was not sent; otherwise `unknown`, with the value read back. The operator decides what to do next.
- A batch runs target by target; one failure does not stop the others, and nothing is rolled back.
- PXEye does not sequence devices across a rack; rack-level work is NICo's rack maintenance.

## 6. Audit

Every target of every execution gets a row in the SQLite table `rack_actions`: time, operator, action, target, parameters (credential-like keys redacted), reason, checks, status, Core's message and the state read back. Columns are in section 4 of the [data contract](rack-operations-data-contract.md). Rows are not deleted; the operation records page lists them and offers no deletion.

## 7. Switch and environment

- `rackActions` (chart) / `rack_actions` (`site.json`), off by default. It takes effect only with `rackOperations` on and the instance not a read-only observer.
- A read-only observer never runs operations: it refuses writes at the HTTP layer and shows no operation buttons.
- Verification must happen on designated test devices in a writable environment, never while an installation batch runs. The verification site has general servers and no NICo rack object, and its Core is configured with all three backends `rms` while no RMS is deployed, so RMS-backed operations fail there.

## 8. Implemented and remaining

| Item | Status |
| --- | --- |
| Catalog, preview, execute, read-back, audit table, records endpoint | Implemented |
| Operation dialog on servers, switches and power shelves; racks page; operation records page | Implemented |
| Demo capture with a GB200 NVL72 rack and `tools/core-replay.py --demo-writes` | Implemented; demo captures only, other commands stay refused |
| Verification at a site, with RMS deployed for RMS-backed operations | Not done |
| Installation preflight reading operation records (section 3, item 4) | Not done; protected code |

## 9. To decide

1. Operator identity: there is one sign-in password, so a record holds only the session and source address. Whether individual operators must be told apart.
2. Which environment and devices to verify writes on, and whether that environment has RMS.
