# Field survey: servers

**English** · [简体中文](servers.zh-CN.md) · [Field survey guide](README.md)

Pages: Device management → Servers, and the server status dialog (state timeline, health history, hardware validation, firmware inventory). For preparation and the common procedure, see the [Field survey guide](README.md).

## 1. Data sources

| Page content | NICo CLI | gRPC interface | Captured automatically |
| --- | --- | --- | --- |
| Server list, status, health, hardware capabilities, LLDP | `machine show --hosts`, `machine show <machine ID>` | `FindMachineIds`, `FindMachinesByIds` | Yes |
| Device inventory (serial number, BMC MAC) | `expected-machine show` | (PXEye uses the CLI) | Yes |
| Power state | — | `GetPowerOptions` | Yes |
| Current state (all machines) | `machine states --hosts` | `FindMachinesByIds` | Yes |
| State timeline | `machine show <machine ID> --history-count 100` | `FindMachineStateHistories` | Yes |
| Health history | `machine health-history <machine ID>` | `FindMachineHealthHistories` | Yes |
| Hardware validation | `machine-validation runs show --machine <machine ID> --history`, `machine-validation results show --machine <machine ID>` | `GetMachineValidationRuns`, `GetMachineValidationResults` | Yes |
| Firmware inventory, model, lockdown, secure boot | `site-explorer get-report endpoint` | `GetComponentInventory` | Yes |
| Rack | Rack column of `expected-machine show` | The machine's `rack_id` | Only values already filled in; missing ones come from the user |
| Slot, tray | Slot and Tray columns of `machine show --hosts` | `placement_in_rack` | Not present at generic server sites; NICo provides no way to enter them |
| Host firmware baseline | `firmware show` | `GetDesiredFirmwareVersions` | Only NICo's built-in DPU entries; host entries come from the user |

For field mappings, see sections 2.1, 3.1, 3.2, 3.4 and 3.5 of the [data contract](../design/rack-operations-data-contract.md).

## 2. Capture commands

```bash
D=<survey directory>/cli
cli machine show --hosts                         > $D/servers-machine-show.txt
cli --json machine show --hosts                  > $D/servers-machine-show.json
cli expected-machine show                        > $D/servers-expected-machine.txt
cli machine states --hosts                       > $D/servers-states.txt
```

If there are 0 servers, every device on the page shows "NICo has not created a device object (NICo 尚未建立设备对象)". Skip the remaining commands and go to section 4.

Then pick two or three representative machines: one ready, one stuck or failed, and one with a DPU (if any). For each, run:

```bash
M=<machine ID>
cli machine show $M --history-count 100        > $D/servers-$M-show.txt
cli machine health-history $M                    > $D/servers-$M-health.txt
cli machine-validation runs show --machine $M --history > $D/servers-$M-validation-runs.txt
cli machine-validation results show --machine $M > $D/servers-$M-validation-results.txt
survey call 'GetComponentInventory={"machineIds":{"machineIds":[{"id":"'$M'"}]}}' > $D/servers-$M-firmware.txt
```

Take the site-level configuration once each:

```bash
cli machine-validation tests show                > $D/servers-validation-tests.txt
cli sku show                                     > $D/servers-sku.txt
cli firmware show                                > $D/servers-firmware-baseline.txt
```

Finally, run one full-site capture (see section 2 of the guide). It records the reads above and the four status-dialog reads for every machine as returned.

## 3. Checks

| Item | Pass criterion | Record on failure |
| --- | --- | --- |
| Row count | Page row count equals the number of servers in device management | Extra or missing serial numbers |
| Matching | Every server with an object in NICo is matched (the **Created in NICo (NICo 已建立对象)** number in the summary bar equals the row count of `machine show --hosts`) | Unmatched devices: their BMC MAC, and the BMC MAC of the corresponding machine in `machine show` |
| Status and health | Status and health on the page match `machine show <machine ID>` | The differing fields and both values |
| Needs attention | Machines listed under **Needs attention (需要处理)** really failed, exceeded a state time limit, or have alerts | False or missed machines |
| State timeline | Segment count and order match the history of `machine show <machine ID> --history-count 100`; the current state matches `machine states` | Raw time format; new structures in the timeline |
| Health history | Alert start and recovery match `machine health-history` | Record count; alerts with a target |
| Hardware validation | Record count and results match `machine-validation runs show` | Validation result fields seen for the first time |
| Firmware inventory | Entry count equals the number of firmware entries in the report; entries with an empty version are still shown | Entry naming by vendor; fields when secure boot is not empty |
| With DPU | A host appears only once; a DPU is not treated as a server | Machine type in `machine show` |

## 4. Data the user provides

| Data | Why it is needed | How the user gets it | Saved as |
| --- | --- | --- | --- |
| Rack of each server | NICo does not discover racks; it only records manually declared values. Servers without one do not appear in the rack groups of the rack topology | Racking records or asset sheet of the data center | `supplements/servers-rack.csv`: `serial,rack` |
| U position of the server in the rack (optional) | NICo provides no position at generic server sites | Racking records, or on-site inspection | `supplements/servers-position.csv`: `serial,rack,unit` |
| Host firmware baseline (optional) | Without a baseline, versions can only be shown, not checked for compliance | Versions recommended by the hardware vendor, or versions set by the site | `supplements/servers-firmware-baseline.csv`: `vendor,model,component,version` |
| Whether machine validation and SKU are enabled | When disabled, validation records only show **Skipped (已跳过)**. This is a site setting, not a fault | Ask the site owner | Write in `session.md` |
| Expected server list | Shows whether any server never entered NICo | Delivery list or purchase list | `supplements/servers-expected.csv`: `serial,bmc_mac,rack` |

The `component` column uses the component ID shown in the firmware inventory (such as `BMC-Primary`, `UEFI`). Naming differs by vendor. Use the names that actually appear at the site.

Racks can be filled in per server in a writable console, through the system configuration of device management. The read-only observer instance cannot be used for this.

## 5. Common cases

| Symptom | Assessment |
| --- | --- |
| `machine show --hosts` is empty, but device management has servers | The servers are planned in PXEye but have not entered NICo discovery. See [discovery diagnostics](discovery-diagnostics.md) |
| A machine stays in one state past its time limit | In the state timeline, find the step where it stayed longest, together with the health history and the state reason in `machine show` |
| All validation records are **Skipped (已跳过)** | The site has not enabled machine validation. Confirm with the user |
| Firmware inventory is empty | The BMC exploration report for this machine is incomplete. Check the result for that address in discovery diagnostics |
