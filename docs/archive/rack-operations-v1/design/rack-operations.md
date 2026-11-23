# Rack operations: scope and status

**English** · [简体中文](rack-operations.zh-CN.md) · [Design documents](../../../design/README.md)

> **Archived (2026-11-23).** This document belongs to a design that the whole-rack design has superseded. It is no longer maintained and is kept as it was when archived, for reference only. See the current [design documents](../../../design/README.md) and the [archive index](../../README.md).

- Requirements baseline: [capability requirements](rack-operations-requirements.md). It describes the whole of the target capabilities; this document says what each of them can actually do.
- Status: draft; the items in section 8 are awaiting confirmation. It records what has been decided and what has been verified.
- Evidence: the interface definitions of a NICo Core at a real site, read on 2026-11-19, and read-only calls against it. Requests and responses for each interface are in the [data contract](rack-operations-data-contract.md).
- Implementation: the site switch `rackOperations`, off by default.

## 1. Purpose

Without affecting installation, present the operational status of enrolled devices and the rack view of a site in pages an operator can use. The current stage is read-only: it shows which devices are not ready, at which step they are held and why. It starts no operation that changes a device.

Installation and device discovery are the main line of the product. This work does not change their flows; it reads the data they already hold and links to the entries they already provide.

## 2. Two kinds of site

NICo Core provides very different data for the two, and whether a page has content depends on which kind the site is.

| | General server site | Whole-rack site (GB200 class) |
| --- | --- | --- |
| Servers | Core has machine objects with full data | Same |
| Racks | No rack objects, only the `rack_id` declared by hand on each device | Core has rack objects, rack groups, rack health and rack maintenance |
| Switches | Access switches are not managed by Core and are visible only as LLDP neighbours of servers | Core manages NVLink switches |
| Power | Rack PDUs are not in Core | Core manages power shelves |
| Slot | Not provided by Core | Objects carry slot and tray fields; their source is unverified |

The site used for verification is a general server site. In the whole-rack column, everything except servers is unverified and rests on interface definitions only.

## 3. Capability comparison

For each of the ten functional areas, the target, what Core actually provides and how far PXEye has gone are recorded under “Implementation status” in section 6 of the [capability requirements](rack-operations-requirements.md), and maintained only there. This document covers the pages, rules and plan of the current stage.

## 4. Pages

### 4.1 Done

Eight pages sit under device management as second-level entries. Servers, switches and power shelves list the same devices as device management, split by kind, with the operational status Core reports; alerts gathers their current health alerts; cabling and discovery diagnostics summarise by switch and by BMC address; racks lists the rack objects NICo keeps; operation records lists the operations PXEye sent.

| Page | Purpose | What the user can do | Verification |
| --- | --- | --- | --- |
| Servers | See which servers are not ready, at which step and why; check uplink switches; find devices without a declared rack | Filter by “needs attention” and rack, search; open the status dialog (state reason, health alerts, hardware capabilities, LLDP neighbours, state timeline, firmware inventory); go to the installation task, hardware details and address management; open the system settings to declare a rack; import rack unit positions (“导入 U 位”) | The list and the basic status content were verified with real data; the state timeline and firmware inventory follow the response structure recorded at a real site and were verified with authored sample data only |
| Switches | View status, health, management ports and fabric manager state of NVLink switches Core manages | Same | Verified with authored sample data only. A general server site has no such device, and the page explains what it covers |
| Power shelves | View status, health, capacity and voltage of power shelves Core manages | Same | Same |
| Alerts | See which current health alerts affect which servers, switches and power shelves | Group by alert or by device; filter by device kind and classification, search; see how many alerts carry `PreventAllocations`; open a device's status dialog | Reads only the health already returned for the device lists (no new Core interface); verified with authored sample data only |
| Cabling | See, per switch, which port each server interface is connected to; find a port reported by more than one interface; find servers without LLDP data | Filter by switch, search; open a server's hardware details; import switch names and panel port names (“导入交换机信息”) | The data comes from servers' LLDP neighbours, whose structure was verified with real data (one server, one switch); the page was verified with authored sample data only. It shows observed connections and is not compared with a plan |
| Discovery diagnostics | See the result of NICo site exploration for each BMC address, to find why a device was not discovered | Filter by result, search by address, serial or error code; failures first, with error code and mitigation; open the details of a joined device | The response structure was verified with real data (5 addresses, 4 refused connections); the page was verified with authored sample data only |
| Racks | See the rack objects NICo keeps for declared whole racks: profile, state, member counts, state and health history | Open a rack's history; with `rackActions` on, start or terminate rack maintenance and rack firmware updates | Verified with the demo capture only (one GB200 NVL72 rack); a general server site has no rack object and the page says so |
| Operation records | See every operation PXEye sent, with checks, result and the state read back | Filter by action and result; search by object ID, serial, name, reason or operator; no deletion | Verified with the demo capture and `tools/core-replay.py --demo-writes` only |

With `rackActions` off, the pages start no write to NICo. With it on (and `rackOperations` on, not a read-only observer), the servers, switches and power shelves pages offer an operation dialog (操作, or 批量操作 for up to 10 selected devices) and the racks page offers rack actions; the rules are in [rules for operations](rack-operations-actions.md). Two pages own data that PXEye keeps in its own database, imported as CSV and never written to NICo; neither import is offered on a read-only observer:

- The server page owns rack unit positions (`serial,rack,unit[,height]`). The server list shows `U<n>` (`U<n>–U<m>` when the height is above 1); the rack topology orders a compute section by unit, top first, when every server in it has one and the layout is not being edited. The rack column is only compared with the device's rack.
- The cabling page owns switch labels (switches and panel ports, matched to LLDP by chassis MAC and port). The page shows the imported names next to what LLDP reports.

Formats, validation and matching are in the [data contract](rack-operations-data-contract.md).

After the server status dialog opens, it reads four more items, each showing loading, its result or its failure without affecting the rest of the dialog:

| Content | Use | Notes |
| --- | --- | --- |
| State timeline | Which states a machine went through, how long it stayed in each, and where it is now | Consecutive identical states form one stay; the last runs to the time of reading |
| Firmware inventory | Actual firmware versions per component, with model, part number, lockdown and secure boot state | Versions are shown, not judged compliant (there is no host firmware baseline); the list does not read them per row |
| Health history | Which alerts the machine had, when each began, when it was last seen and whether it cleared | An alert that clears and returns counts as two periods |
| Hardware validation | Validation runs, the result of each and the result of each test | The verification site had one skipped run only; the fields of test results come from the interface definition only |

### 4.2 Next

Nothing is decided. A candidate from 4.3 is listed here once chosen.

### 4.3 Candidates

| Content | Decision needed first |
| --- | --- |
| Cabling check (intended against actual) | Where the intended cabling comes from; arrival planning is deferred |

### 4.4 Not done, or not possible

- Rack power total: Core returns no power readings; it needs a PDU integration.
- Outlet-level power management: a Core power shelf has no outlets.
- Leak detection response: Core has no dedicated interface.
- Ports and configuration of third-party switches: not managed by Core.
- Switch OS installation, DPU upgrades, firmware baselines: explicitly deferred. Single component firmware updates through NICo exist under `rackActions`.
- Arrival planning: explicitly deferred. Device planning in device management already imports and compares by serial number and is where it would be extended.

## 5. Design rules

General rules are in [interaction rules](interaction-rules.md). This work adds:

1. Read-only first.
2. Installation and device discovery are not changed; new features live in new files and shared files only gain registrations.
2. With the switch off, navigation and API are as before.
4. The device list is the one device management uses, joined by Core object identifiers; no second set of device data.
5. Details, addresses and rack declaration open the existing dialogs.
6. Only show what has data.
7. “Needs attention” uses Core's own signals: a failed handler run, a state past its time limit, or a health alert.
8. The only data these pages edit is PXEye-local: rack unit positions and switch labels. It is used for display and comparison, never written to NICo, and cannot be edited on a read-only observer.

## 6. Preconditions for operations

Operations are implemented behind the `rackActions` switch and are not verified at a site. The operations, their NICo interfaces, RMS dependency, yielding to installation, confirmation, execution, audit and what NICo does not provide are in [rules for operations](rack-operations-actions.md); implementation status per area is in the [capability requirements](rack-operations-requirements.md).

Still open:

- Verification: a writable test environment with designated devices, and RMS for the actions that need it.
- The installation preflight does not yet read operation records; it is protected installation code and needs its own review.
- Operator identity: records hold the session and source address only.

## 7. How this is developed

- A read-only observer instance provides real data: the same image with `readOnly` on, connected to the Core of an existing site. It rejects every write, takes no part in installation, and can run beside the console in use.
- At a site, follow the [field survey guide](../field-survey/README.md) page by page: which CLI commands and interfaces to use, how to check, and what the user has to provide.
- Away from the site, develop and test by replaying the capture (`tools/core-replay.py`) instead of writing Core responses by hand.
- Raw site responses and operation records do not enter this repository.

## 8. Awaiting confirmation

1. Whether the target site is a general server site or a whole-rack site. This decides whether the switch page, the power shelf page and rack features are meaningful.
2. Which candidates to build.
3. Where operations are verified first (section 6).

## 9. Stages

| Stage | Content | Status |
| --- | --- | --- |
| 1 | Read-only observer instance; server, switch and power shelf pages | Done |
| 2 | State timeline, firmware inventory, health history, hardware validation, cabling, discovery diagnostics; alerts page, switch label import, rack unit import | Done; to be checked at a real site |
| 3 | Verify switch, power shelf and rack fields at a site that has them; decide the candidates | Awaiting a site |
| 4 | Operations under `rackActions`; racks and operation records pages | Implemented; not verified at a site |
| 5 | Verify operations on test devices, with RMS where needed; installation preflight reading operation records | Awaiting a writable test environment and review |
