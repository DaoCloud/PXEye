# Field survey: servers

**English** · [简体中文](servers.zh-CN.md) · [Field survey guide](README.md)

Pages: Device management → Servers, and the server status dialog (state timeline, health history, hardware validation, firmware inventory). The page lists the servers that NICo has created objects for, with their status, health, hardware capabilities, LLDP, power state and rack. For preparation (environment variables, `--save`, survey directory) and the common procedure, see the [Field survey guide](README.md).

## 1. Data sources

| Page content | gRPC interface the page code calls (request) | Equivalent nico CLI | Equivalence | Captured automatically |
| --- | --- | --- | --- | --- |
| Server list, status, health, hardware capabilities, LLDP | `FindMachineIds` `{}`, then `FindMachinesByIds` `{"machineIds":[...],"includeHistory":false}` | `machine show --hosts` (list), `--json machine show <machine ID>` (full JSON incl. `lldp_neighbors`) | Same | Yes |
| Device inventory (serial number, BMC MAC) | The page code runs the CLI `expected-machine show` (JSON) | `expected-machine show` | Same | Yes |
| Power state | `GetPowerOptions` `{"machineId":[]}` | — | None | Yes |
| Current state (all hosts, cross check only) | `FindMachinesByIds` (as in the first row; this row only cross-checks its state) | `machine states --hosts` (`FindMachineStatesByIds`, a different source) | Similar | Yes |
| State timeline | `FindMachineStateHistories` `{"machineIds":[{"id":"<machine ID>"}]}` | `machine show <machine ID> --history-count 100` | Similar | Yes |
| Health history | `FindMachineHealthHistories` `{"machineIds":[{"id":"<machine ID>"}]}` | `machine health-history <machine ID>` | Same | Yes |
| Hardware validation | `GetMachineValidationRuns` `{"machineId":{"id":"<machine ID>"},"includeHistory":true}`, `GetMachineValidationResults` `{"machineId":{"id":"<machine ID>"},"includeHistory":true}` | `machine-validation runs show --machine <machine ID> --history`, `machine-validation results show --machine <machine ID>` | Same | Yes |
| Site configuration of validation and SKU (reference only) | None (the page reads no site configuration) | `machine-validation tests show` (`GetMachineValidationTests`), `sku show`; read through the CLI only | None | Yes |
| Firmware inventory, model, lockdown, secure boot | `GetComponentInventory` `{"machineIds":{"machineIds":[{"id":"<machine ID>"}]}}` | `site-explorer get-report endpoint <BMC address>` | Similar | Yes |
| Rack | The machine's `rack_id` (`FindMachinesByIds`) | Rack column of `expected-machine show` | Same | Only values already filled in; missing ones come from the user |
| Slot, tray | The machine's `placement_in_rack` (`FindMachinesByIds`) | Slot and Tray columns of `machine show --hosts` | Same | Not present at general-purpose server sites; NICo offers no way to enter them |
| Host firmware baseline | None (the page reads no baseline) | `firmware show` (`ListHostFirmware`), only as a reference for what NICo holds | None | Only NICo's built-in DPU entries; host entries come from the user |

The page code does not use the CLI (except for the device inventory); checks rely on the gRPC interfaces or the capture file, see [guide section 1.3](README.md#13-how-cli-commands-relate-to-interfaces).

## 2. Survey commands

Run the commands below from the repository root, with the `SURVEY_*` variables exported as in [guide section 1.2](README.md#12-entry-script).

(1) Counts and IDs:

```bash
tools/site-survey.sh --save servers-ids.txt survey ids machines
tools/site-survey.sh --save servers-machine-show.txt cli machine show --hosts
tools/site-survey.sh --save servers-machine-states.txt cli machine states --hosts
```

How to pick `<machine ID>`:
- First machine: the first line of `survey/servers-ids.txt`.
- Second machine: a host in `cli/servers-machine-states.txt` whose state contains `Failed` or `Error`, or that stays in a state other than `Ready`; skip if there is none.
- A host with a DPU (if any): one with a non-empty DPU column in `cli/servers-machine-show.txt`.

`<BMC address>`: the machine's BMC IP in the output of `--json machine show <machine ID>`.

(2) Each item. List and device inventory (once per site):

```bash
tools/site-survey.sh --save servers-list.txt survey call 'FindMachineIds={}'
tools/site-survey.sh --save servers-expected-machine.txt cli expected-machine show
tools/site-survey.sh --save servers-power.txt survey call 'GetPowerOptions={"machineId":[]}'
tools/site-survey.sh --save servers-validation-tests.txt cli machine-validation tests show
tools/site-survey.sh --save servers-sku.txt cli sku show
tools/site-survey.sh --save servers-firmware-baseline.txt cli firmware show
```

For each selected machine (replace `<machine ID>` and `<BMC address>` with real values):

```bash
tools/site-survey.sh --save servers-<machine ID>-machine.txt survey call 'FindMachinesByIds={"machineIds":[{"id":"<machine ID>"}],"includeHistory":false}'
tools/site-survey.sh --save servers-<machine ID>-machine-json.txt cli --json machine show <machine ID>
tools/site-survey.sh --save servers-<machine ID>-history.txt survey call 'FindMachineStateHistories={"machineIds":[{"id":"<machine ID>"}]}'
tools/site-survey.sh --save servers-<machine ID>-history-cli.txt cli machine show <machine ID> --history-count 100
tools/site-survey.sh --save servers-<machine ID>-health.txt survey call 'FindMachineHealthHistories={"machineIds":[{"id":"<machine ID>"}]}'
tools/site-survey.sh --save servers-<machine ID>-health-cli.txt cli machine health-history <machine ID>
tools/site-survey.sh --save servers-<machine ID>-validation-runs.txt survey call 'GetMachineValidationRuns={"machineId":{"id":"<machine ID>"},"includeHistory":true}'
tools/site-survey.sh --save servers-<machine ID>-validation-runs-cli.txt cli machine-validation runs show --machine <machine ID> --history
tools/site-survey.sh --save servers-<machine ID>-validation-results.txt survey call 'GetMachineValidationResults={"machineId":{"id":"<machine ID>"},"includeHistory":true}'
tools/site-survey.sh --save servers-<machine ID>-validation-results-cli.txt cli machine-validation results show --machine <machine ID>
tools/site-survey.sh --save servers-<machine ID>-firmware.txt survey call 'GetComponentInventory={"machineIds":{"machineIds":[{"id":"<machine ID>"}]}}'
tools/site-survey.sh --save servers-<machine ID>-explore-report.txt cli site-explorer get-report endpoint <BMC address>
```

`survey call` output shows structure only (long values shortened, lists keep the first item); for full data, use the `cli --json` output or the capture file.

(3) The site capture `tools/site-survey.sh capture` runs once per site ([guide section 2](README.md#2-common-procedure)), not per page. It records the reads above and the four status items of every machine.

## 3. Checks

Below, `C` is the capture file: `C=$SURVEY_DIR/capture-<date-time>.json`.

| Item | Pass criterion | Compare with | Record on failure |
| --- | --- | --- | --- |
| Row count | Servers on the page equal machines in NICo | `jq '.pxeye_responses["/api/device-status"].body.servers \| length' $C` against the line count of `survey/servers-ids.txt` | Extra or missing machine IDs |
| Matching | Every server with a NICo object is matched to the device inventory | `cli/servers-expected-machine.txt` against the BMC MACs in `cli/servers-machine-show.txt` | Unmatched devices: their BMC MAC and the BMC MAC of the corresponding machine |
| Status and health | Page status and health match the machine JSON | `jq '.pxeye_responses["/api/device-status"].body.servers["<machine ID>"]' $C` against `cli/servers-<machine ID>-machine-json.txt` | Differing fields and both values |
| Power state | Every machine has a power state, or is shown as unknown | The jq output of the previous row against `survey/servers-power.txt` | Machines without a power state |
| Needs attention | Machines listed under "needs attention" have failed, timed out or have alerts | The page computes "needs attention" in the browser from `lifecycle.outcome == "error"`, `lifecycle.above_sla` or `health.level` warning/alert/critical: `jq -r '.pxeye_responses["/api/device-status"].body.servers \| to_entries[] \| select(.value.lifecycle.outcome == "error" or .value.lifecycle.above_sla or (.value.health.level \| IN("warning","alert","critical"))) \| .key' $C`, against `cli/servers-machine-states.txt` | False or missed machines |
| State timeline | Segment count and order match the state history | `jq '.pxeye_responses["/api/device-status/machines/<machine ID>/history"].body' $C` against `survey/servers-<machine ID>-history.txt`, cross reference `cli/servers-<machine ID>-history-cli.txt` | Raw time format; new structures |
| Health history | Alert start and recovery match the health history | `jq '.pxeye_responses["/api/device-status/machines/<machine ID>/health"].body' $C` against `cli/servers-<machine ID>-health-cli.txt` | Record count; alerts with a target |
| Hardware validation | Record count and results match | `jq '.pxeye_responses["/api/device-status/machines/<machine ID>/validation"].body' $C` against `cli/servers-<machine ID>-validation-runs-cli.txt`, `cli/servers-<machine ID>-validation-results-cli.txt` | Validation result fields seen for the first time |
| Firmware inventory | Entry count equals the inventory entries; entries with empty versions still shown | `jq '.pxeye_responses["/api/device-status/machines/<machine ID>/firmware"].body' $C` against `survey/servers-<machine ID>-firmware.txt`, cross reference `cli/servers-<machine ID>-explore-report.txt` | Entry naming per vendor; fields when secure boot is not empty |
| Rack | Machines with a `rack_id` show that rack | Rack column of `cli/servers-expected-machine.txt` | Serial numbers of machines without a rack |
| With DPU | A host appears once; a DPU is not shown as a server | `cli/servers-machine-show.txt` (`--hosts` lists hosts only) against the jq output of the first row | Machine type in `machine show` |

## 4. Data the user provides

| Data | Why it is needed | How the user gets it | Saved as |
| --- | --- | --- | --- |
| Rack of each server | NICo does not discover racks; it only records declared values. Servers without one do not appear in rack groups of the rack topology | Racking records or asset sheet; filled values are in the rack column of `tools/site-survey.sh cli expected-machine show` | `supplements/servers-rack.csv`: `serial,rack` |
| Rack unit of each server (optional) | NICo has no position at general-purpose server sites | Racking records, or on-site inspection | `supplements/servers-position.csv`: `serial,rack,unit[,height]` |
| Host firmware baseline (optional) | Without a baseline, versions can be shown but not judged for compliance | Vendor recommended versions, or the site's required versions; current NICo content in `tools/site-survey.sh cli firmware show` | `supplements/servers-firmware-baseline.csv`: `vendor,model,component,version` |
| Whether machine validation and SKU are enabled | When disabled, validation only shows "skipped"; this is a site setting, not a fault | Ask the site owner; current configuration in `tools/site-survey.sh cli machine-validation tests show` and `tools/site-survey.sh cli sku show` | In `session.md` |
| Expected server list | Shows whether any server never entered NICo | Delivery or purchase list | `supplements/servers-expected.csv`: `serial,bmc_mac,rack` |

The `component` column uses the component IDs shown in the firmware inventory (such as `BMC-Primary`, `UEFI`). Naming differs by vendor; use the names that appear at the site.

Racks can be filled in per server in the system configuration of Device management on a writable console. The observation instance is read-only and cannot be used for this.

Rack units can be imported on a writable console with “导入 U 位” on the server page, as CSV `serial,rack,unit[,height]`. PXEye keeps them in its own database and does not write them to NICo; the rack column is only compared with the device's rack. The read-only observer cannot import them. After an import, a capture includes `/api/rack-units`; check it with `jq '.pxeye_responses["/api/rack-units"].body | {positions: (.positions | length), mismatches, unknown}' $C`. Formats and validation are in section 2.6 of the [data contract](../design/rack-operations-data-contract.md).

## 5. Common cases

| Symptom | Interpretation |
| --- | --- |
| `machine show --hosts` is empty, but Device management lists servers | The servers are planned in PXEye but have not entered NICo discovery. See [discovery diagnostics](discovery-diagnostics.md) |
| A machine stays in one state beyond its time limit | In the state timeline, find the longest step; combine with the health history and the state reason in `machine show` |
| All validation records are "skipped" | Machine validation is not enabled at the site; confirm with the user |
| Firmware inventory is empty | The BMC exploration report of this machine is incomplete; check the result for that address in discovery diagnostics |
| `GetPowerOptions` fails or is empty | The page shows power as unknown; retry once alone, and record the error code if it keeps failing |

## 6. AI checklist

1. Run `tools/site-survey.sh check`. Record `build_version` and `git_sha`. On failure, stop and ask the user to check the `SURVEY_*` variables and cluster access.
2. Run `tools/site-survey.sh --save servers-ids.txt survey ids machines` and count the lines.
3. Count is 0: NICo has no server objects at this site, and the page only shows "NICo has not created a device object". Run `tools/site-survey.sh --save servers-expected-machine.txt cli expected-machine show`, then ask the user: "NICo has no servers. Should this site have servers? If yes, please fill `supplements/servers-expected.csv` with `serial,bmc_mac,rack`." Record the answer, stop this page and go to [discovery diagnostics](discovery-diagnostics.md).
4. Count is above 0: run the other two commands of section 2 (1), and select `<machine ID>` (first line, a failed one, one with a DPU) and `<BMC address>` by the rules in section 2.
5. Run the site-level commands of section 2 (2), then all machine-level commands for each selected machine. If a command fails, retry it once alone; if it still fails, record the command, error code and message, and continue.
6. If the site has no capture file yet, run `tools/site-survey.sh capture` once. On exit code 2, fix the cause and rerun; on another non-zero code, stop and report.
7. Check each row of section 3, writing pass or fail and what was recorded.
8. Ask the user for the data in section 4: rack (`supplements/servers-rack.csv`), expected server list (`supplements/servers-expected.csv`), rack unit and firmware baseline (optional, `supplements/servers-position.csv` with `serial,rack,unit[,height]`, `supplements/servers-firmware-baseline.csv`), and whether validation and SKU are enabled. For each, say what, why and how to get it. Do not guess values the user cannot give. On a writable console, have the user import the rack units with “导入 U 位” on the server page (not possible on the read-only observer); after the next capture, record the `mismatches` and `unknown` of `/api/rack-units`.
9. Write a section for this page in `session.md`: Core version; server count; machine IDs used; result of each check in section 3; failed commands and error codes; user data received and missing (what is missing, which item it affects); documents and tests that need updating.
