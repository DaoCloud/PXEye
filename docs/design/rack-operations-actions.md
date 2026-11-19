# Rack operations: rules for operations (draft)

**English** · [简体中文](rack-operations-actions.zh-CN.md) · [Design documents](README.md)

- Status: **draft, not implemented**. No code is written until the items in section 8 are decided.
- Scope: operations that change a device, such as power, maintenance marks, quarantine and on-demand validation. Read-only pages are in [scope and status](rack-operations.md); target capabilities in sections 6.3 and 6.10 of the [capability requirements](rack-operations-requirements.md).
- Evidence: the existing code (device occupancy by installation tasks, read-only mode) and the interface definitions of the site's Core version `7c7788a8c7f1`. None of these writes has been called at a site.

## 1. Candidate operations and risk

| Operation | Core interface | Effect on the device | Reversible | Risk |
| --- | --- | --- | --- | --- |
| Maintenance mark | `SetMaintenance` (`Enable` with a ticket link / `Disable`) | No hardware change; Core stops allocating the host | Yes | Low |
| Power on | `AdminPowerControl` (`On`) | The host powers on and may boot from PXE or its system | Yes | Medium |
| Graceful shutdown, graceful restart | `AdminPowerControl` (`GracefulShutdown`, `GracefulRestart`) | Carried out by the operating system; may do nothing when the system does not respond | Yes | Medium |
| Force off, force restart, AC power cycle | `AdminPowerControl` (`ForceOff`, `ForceRestart`, `ACPowercycle`) | Bypasses the operating system; can corrupt data being written | No (data) | High |
| Quarantine | `SetManagedHostQuarantineState` (`BLOCK_ALL_TRAFFIC`) / `ClearManagedHostQuarantineState` | Cuts all tenant network traffic of the host | Yes | High |
| On-demand validation | `OnDemandMachineValidation` | Runs tests on the host; may restart it and change the state machine | Partly | High |
| Health override | `InsertHealthReportOverride` / `RemoveHealthReportOverride` | Marks health by hand; affects allocation | Yes | Medium |
| Firmware update | `UpdateComponentFirmware` | Flashes firmware | No | Very high; outside this work |

Rack-level operations (powering a whole rack): a general server site has no rack object in Core, so PXEye can only sequence single-device operations by rack. Whole-rack sites have `OnDemandRackMaintenance`, unverified.

## 2. Yielding to installation

1. When a device has an installation task in progress (status `queued`, `running` or `needs_attention` in the `tasks` table), every operation is refused with a request to deal with the installation task first.
2. While an operation is in progress, no installation task can be created for the same device. This needs the installation preflight to read the operation record, which touches protected installation code and must be reviewed on its own (section 8). Until then, stage 1 opens only the maintenance mark, which changes neither power nor network.
3. When the device is in an installation-related state of the NICo state machine (such as `HostInit` or the installation stages of `Assigned/…`), power and quarantine operations are refused; the maintenance mark is allowed.
4. The server repeats the checks on submission; a check in the page never replaces it.

## 3. Confirmation

- The confirmation names the object and the effect: serial number, machine ID, current state, and the consequence (for example “force off bypasses the operating system and can corrupt data being written”).
- A single high-risk operation requires typing the device serial number.
- A batch is limited to 10 devices; each device is listed, and only those that passed the checks are confirmed; the others are listed with their reason and not run.
- Enabling the maintenance mark requires a reason or ticket link, written to Core's `reference`.
- Check results are valid for 5 minutes after confirmation; after that they are run again.

## 4. Execution and result

- “Request sent” is recorded before Core is called. On a timeout or unknown result, **nothing is resent automatically**; the state is read back first: power from `GetComponentPowerDetails`, maintenance and quarantine from the machine object.
- Only a read-back matching the expectation counts as done; otherwise the result is “unknown”, with the value read back and the next step.
- A batch runs and records device by device; one failure does not affect the others, and devices already done are not rolled back automatically.
- Rack-level power follows the order within the rack with an interval between devices (10 seconds by default, configurable), and stops at the first failure with a report.

## 5. Audit

A new append-only table, `rack_actions`:

| Field | Content |
| --- | --- |
| Time | Requested and completed |
| Operator | The signed-in session (the console has one operator identity today; record the session and source address) |
| Object | Device serial number, machine ID |
| Operation | Interface and parameters (no credentials) |
| Reason | The reason or ticket link the user gave |
| Checks | The result of the pre-execution checks |
| Result | Sent / succeeded / failed / unknown; Core's message; the state read back |

The page lists records by device and time and offers no deletion.

## 6. Switch and environment

- A new switch, `rackActions`, off by default and independent of `rackOperations`: read-only pages can be on while operations stay off.
- A read-only observer can never run them: it refuses writes at the HTTP layer and shows no operation buttons.
- Verification happens only on designated test devices and never while an installation batch runs; it needs a writable test environment, since the observer cannot verify writes.

## 7. Stages

| Stage | Operations | Precondition |
| --- | --- | --- |
| 1 | Maintenance mark (enable, disable); audit table and record page | Items 1, 3 and 4 of section 8 |
| 2 | Power on, graceful shutdown, graceful restart; single and batch | The installation preflight reading operation records (section 2, item 2) reviewed and implemented |
| 3 | Force off, force restart; rack-level sequencing | Stage 2 stable on test devices |
| 4 | Quarantine, health override, on-demand validation | Reviewed one by one |
| Not done | Firmware update, AC power cycle (`ACPowercycle`) | — |

## 8. To decide

1. Whether to start stage 1.
2. Whether stage 2 may change the installation preflight (protected installation code) to check operation records before an installation task is submitted.
3. Whether the batch limit, confirmation style and interval take the values in this draft.
4. Which environment and devices to verify writes on.
5. Operator identity: there is one sign-in password today, so audit can only record the session; whether individual operators must be told apart.
