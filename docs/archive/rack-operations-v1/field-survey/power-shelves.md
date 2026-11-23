# Field survey: power shelves

**English** · [简体中文](power-shelves.zh-CN.md) · [Field survey guide](README.md)

> **Archived (2026-11-23).** This document belongs to a design that the whole-rack design has superseded. It is no longer maintained and is kept as it was when archived, for reference only. See the current [design documents](../../../design/README.md) and the [archive index](../../README.md).

Page: Device management → Power shelves. The page shows the power shelves NICo manages (the **Power Shelf** of a rack-scale site): the list, state, health, power state, capacity, voltage, and the serial number and PMC MAC from the device list. Rack PDUs are not managed by NICo and do not appear here. For preparation (environment variables, survey directory, `--save`), see the [Field survey guide](README.md).

## 1. Data sources

| Page item | gRPC call made by the page code (request) | Equivalent nico CLI | Parity | Captured automatically |
| --- | --- | --- | --- | --- |
| Power shelf list, state, health, power state | `FindPowerShelves` `{}` | `power-shelf list`, `power-shelf show <power shelf ID>`; full record: `--json power-shelf show <power shelf ID>` | Same | Yes |
| Capacity (W), voltage (V) | `FindPowerShelves` `{}` | `power-shelf show <power shelf ID>` | Same | Yes |
| Device list (serial number, PMC MAC) | `GetAllExpectedPowerShelves` `{}` | `expected-power-shelf show` | Same | Yes |
| Health history (not used by the page yet) | `FindPowerShelfHealthHistories` | `power-shelf health-history <power shelf ID>` | Same | Yes (section 2 commands; not in the capture) |
| Real-time power | None: no RPC returns watts | — | None | No |
| Whether the site has power shelves | — | — | None | No, the user must confirm |

The page code does not use the CLI; checks rely on the gRPC call or the capture file, see [Field survey guide section 1.3](README.md#13-how-cli-commands-relate-to-interfaces).

## 2. Commands

Assumes the `SURVEY_*` variables are exported as in [Field survey guide section 1.2](README.md#12-entry-script); run from the repository root.

(1) Count and IDs:

```bash
tools/site-survey.sh --save power-shelves-ids.txt survey ids power-shelves
```

The output has one power shelf ID per line; the line count is the number of power shelves. If it is 0, go to section 4.

(2) The gRPC call and equivalent CLI for each item. Take `<power shelf ID>` from the first line of `power-shelves-ids.txt`; if `power-shelf list` shows a power shelf that is not in a normal ready state or has a health alert, repeat the commands with `<power shelf ID>` for one such ID.

```bash
# List, state, health, power, capacity, voltage
tools/site-survey.sh --save power-shelves-find.txt survey call 'FindPowerShelves={}'
tools/site-survey.sh --save power-shelves-list.txt cli power-shelf list
tools/site-survey.sh --save power-shelves-show.txt cli power-shelf show <power shelf ID>
tools/site-survey.sh --save power-shelves-show-json.txt cli --json power-shelf show <power shelf ID>

# Device list
tools/site-survey.sh --save power-shelves-expected-grpc.txt survey call 'GetAllExpectedPowerShelves={}'
tools/site-survey.sh --save power-shelves-expected.txt cli expected-power-shelf show

# Health history (not used by the page yet)
tools/site-survey.sh --save power-shelves-health-describe.txt survey describe FindPowerShelfHealthHistories
tools/site-survey.sh --save power-shelves-health.txt cli power-shelf health-history <power shelf ID>
```

`survey call` output shows structure only (long values shortened, lists keep the first item); for full data use the `cli --json` output or the capture file.

(3) The capture is done once per site ([Field survey guide section 2](README.md#2-common-procedure)), not per page. If it has not been done yet:

```bash
tools/site-survey.sh capture
```

## 3. Checks

In the table, `$C` is the capture file `$SURVEY_DIR/capture-<date-time>.json`; saved files are under `$SURVEY_DIR/cli/` and `$SURVEY_DIR/survey/`.

| Item | Pass criterion | Compare with | Record on failure |
| --- | --- | --- | --- |
| Row count | The page's power shelf count equals the ID count | `jq '.pxeye_responses["/api/device-status"].body.power_shelves \| length' $C` against the line count of `survey/power-shelves-ids.txt` | Both counts, extra or missing IDs |
| Device list | The power shelf count in device management equals the device list count | `jq '.pxeye_responses["/api/equipment"].body.devices \| map(select(.kind=="power_shelf")) \| length' $C` against `cli/power-shelves-expected.txt` | Extra or missing serial numbers and PMC MACs |
| State, health, power | Matches the CLI | `jq '.pxeye_responses["/api/device-status"].body.power_shelves' $C` against `cli/power-shelves-show-json.txt` | Actual state text, health value, power value |
| Capacity, voltage | Matches the CLI, units are watts and volts | Same as above, fields `capacity_watts`, `voltage` | Actual values and units |
| Fields | Whether each "defined only" field in data contract section 2.3 has a value | `cli/power-shelves-show-json.txt`, `survey/power-shelves-find.txt` | Actual value or "empty" per field |
| Read errors | No failed calls | `jq '.summary' $C`: whether `failed_calls` or `reads_with_errors` contain `FindPowerShelves` or `GetAllExpectedPowerShelves` | Method, error code and message |

For the field mapping, see section 2.3 of the [data contract](../design/rack-operations-data-contract.md). All fields are currently "defined only": the sites verified so far have no power shelves.

## 4. Data the user provides

| Data | Why | How the user gets it | Saved as |
| --- | --- | --- | --- |
| Whether the site has power shelves | When the commands return nothing, distinguish "the site has none" from "present but not managed" | Ask the site owner; check whether the site is rack-scale. Compare with the output of `tools/site-survey.sh cli expected-power-shelf show` | Written in `session.md` |
| Expected power shelf list (if any) | Find the ones not yet managed | The rack-scale shipping list | `supplements/power-shelves-expected.csv`: `serial,pmc_mac,rack` |
| Rack PDU list (optional) | NICo does not manage PDUs; rack power later needs to know which PDUs exist and how to reach them | The data center's power documentation | `supplements/power-pdus.csv`: `rack,name,model,management_ip,protocol` |

`protocol` is the management protocol the PDU supports, for example `snmp`, `redfish`, `http`. Record information only; do not ask for passwords.

## 5. Common cases

| Observation | Conclusion |
| --- | --- |
| ID count is 0, the site uses ordinary server racks | Normal. This page does not apply at the site |
| ID count is 0, but the device list is not empty | Power shelves are registered but not yet managed; record the serial numbers from the list and ask the user |
| The user asks how much power a rack uses | NICo returns no power readings; the page cannot show it. Record the request and the PDU list |

## 6. AI checklist

1. Run `tools/site-survey.sh --save power-shelves-ids.txt survey ids power-shelves`. On success, count the lines. On failure, retry once as in [Field survey guide section 5](README.md#5-rules-for-ai); if it still fails, record the error and stop this page.
2. Line count is 0: run `tools/site-survey.sh --save power-shelves-expected.txt cli expected-power-shelf show`. This means the page has no managed power shelves at this site. Two cases, by its output:
   - Device list is empty: stop and ask the user: "Does this site have NVIDIA rack-scale power shelves (Power Shelf)? If so, provide the shipping list and fill in `supplements/power-shelves-expected.csv` (columns `serial,pmc_mac,rack`)." Also ask whether to record rack PDUs (`supplements/power-pdus.csv`). Record the answer and end this page; go to step 8.
   - Device list is not empty: record its serial numbers and PMC MACs in `session.md`, then stop and ask the user: "These N power shelves are registered but not managed by NICo; should they be?" Record the answer and end this page; go to step 8.
3. Line count above 0: run all commands of section 2 (2) in order, with `<power shelf ID>` from the first line; for a power shelf in `power-shelf list` with an abnormal state or health alert, run the commands with an ID again for it. Move to the next command only after the previous one succeeds.
4. If the site capture has not been done, run `tools/site-survey.sh capture`. Exit code 0: continue; 2: fix the cause and rerun.
5. Check each item of section 3; write pass or fail and the recorded content for each.
6. If the device list count differs from the ID count, or the list is empty, stop and ask the user for the expected power shelf list, save it as `supplements/power-shelves-expected.csv`, and ask the user to confirm it.
7. Ask the user whether to record rack PDUs; if yes, save `supplements/power-pdus.csv`, without passwords.
8. Write this page into `session.md`: Core version, power shelf count, whether there is data, each check result, failed calls, user data received and missing (what is missing, which item it affects), data contract fields that need updating.
