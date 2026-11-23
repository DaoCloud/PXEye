# Field survey: alerts

**English** · [简体中文](alerts.zh-CN.md) · [Field survey guide](README.md)

> **Archived (2026-11-23).** This document belongs to a design that the whole-rack design has superseded. It is no longer maintained and is kept as it was when archived, for reference only. See the current [design documents](../../../design/README.md) and the [archive index](../../README.md).

Page: Device management → Alerts. The page gathers the current health alerts of servers, switches and power shelves, grouped by alert or by device, filtered by device kind and classification, and counts the alerts that carry `PreventAllocations`; device names open the existing status dialog. The page is read-only and has no new Core interface; its data is the same as that of the server, switch and power shelf pages. For preparation (environment variables, observer instance, survey directory) see section 1 of the [field survey guide](README.md).

## 1. Data sources

| Page item | gRPC call the page code makes (request) | Equivalent nico CLI | Parity | Captured automatically |
| --- | --- | --- | --- | --- |
| Current alerts of servers | `FindMachineIds` (`{}`), then `FindMachinesByIds` (`{"machineIds":[…],"includeHistory":false}`) | `--json machine show <machine ID>` | Same | Yes |
| Current alerts of switches | `FindSwitches` (`{}`) | `--json switch show <switch ID>` | Same | Yes |
| Current alerts of power shelves | `FindPowerShelves` (`{}`) | `--json power-shelf show <power shelf ID>` | Same | Yes |
| Alert history (not used by the page; used by the status dialog) | `FindMachineHealthHistories` (not called by the alerts page) | `machine health-history <machine ID>` | Same | Yes, for history only |
| Alerts the site treats as known | None | None | None | No, the user provides them |

The page code does not use the CLI; checks are decided by the gRPC call or the capture file (see section 1.3 of the [field survey guide](README.md)).

Fields the page uses are in section 2.5 of the [data contract](../design/rack-operations-data-contract.md): `health.level` and `health.alerts[]` (`id`, `target`, `message`, `since`, `classifications`) of each device in `/api/device-status`.

## 2. Commands

Run from the repository root, with the `SURVEY_*` variables exported as in section 1.2 of the [field survey guide](README.md).

Step 1, the IDs of each device kind:

```bash
tools/site-survey.sh --save alerts-machine-ids.txt survey ids machines
tools/site-survey.sh --save alerts-switch-ids.txt survey ids switches
tools/site-survey.sh --save alerts-power-shelf-ids.txt survey ids power-shelves
```

Step 2, details of devices with alerts. Do the whole-site capture of step 3 first and find devices with alerts with the first `jq` of section 3; take one of each kind (skip a kind that has none):

```bash
tools/site-survey.sh --save alerts-machine-<machine ID>.json cli --json machine show <machine ID>
tools/site-survey.sh --save alerts-machine-health-<machine ID>.txt cli machine health-history <machine ID>
tools/site-survey.sh --save alerts-switch-<switch ID>.json cli --json switch show <switch ID>
tools/site-survey.sh --save alerts-power-shelf-<power shelf ID>.json cli --json power-shelf show <power shelf ID>
```

`machine health-history` gives history only: use it to tell a persistent alert from a recurring one, not as the source of current alerts.

Step 3, the raw capture of the whole site is done once ([field survey guide](README.md) section 2), not once per page. If it has not been done yet:

```bash
tools/site-survey.sh capture
```

## 3. Checks

No browser is needed. `$C` in the table is the capture file, see section 3.1 of the [field survey guide](README.md).

| Item | Pass criterion | Compare with | Record on failure |
| --- | --- | --- | --- |
| Devices with alerts | The devices listed match those with alerts in the CLI details | `jq '.pxeye_responses["/api/device-status"].body \| [(.servers, .switches, .power_shelves)[] \| select((.health.alerts \| length) > 0)] \| length' $C`; the `--json … show` output of step 2 | Extra or missing devices |
| Alert count and kinds | Counts per `id` match the CLI | `jq '[.pxeye_responses["/api/device-status"].body \| (.servers, .switches, .power_shelves)[] \| .health.alerts[]] \| group_by(.id) \| map({id: .[0].id, count: length})' $C` | The actual alert IDs and counts |
| Fields | `target`, `message`, `since`, `classifications` of each alert match the CLI details | `jq '.pxeye_responses["/api/device-status"].body.servers[].health.alerts[]' $C` (likewise for switches and power shelves); `alerts-machine-<machine ID>.json` | Differing fields and both values |
| `PreventAllocations` | The number of alerts with that classification matches the capture | `jq '[.pxeye_responses["/api/device-status"].body \| (.servers, .switches, .power_shelves)[] \| .health.alerts[] \| select(.classifications \| index("PreventAllocations"))] \| length' $C` | The actual count and other classifications seen |
| Abnormal level without alerts | Every device at `warning`, `alert` or `critical` with empty `alerts` is listed | `jq '[.pxeye_responses["/api/device-status"].body \| (.servers, .switches, .power_shelves)[] \| select((.health.alerts \| length) == 0 and (.health.level \| IN("warning","alert","critical")))] \| length' $C` | The levels of those devices |
| Read errors | The page endpoint has no read errors | `jq '.pxeye_responses["/api/device-status"].body.errors' $C`; `jq '.summary' $C` | Error text, failed method and error code |

The page lists only devices that device management holds and that are joined to a NICo object; the jq counts cover every object in `/api/device-status`. A device counted by jq but missing on the page is usually not in device management; record its ID.

When done, add the conclusions to the open items of section 2.5 of the data contract (real alert IDs, classifications, `target` values).

## 4. Data the user provides

The page needs nothing from the user. Optional:

| Data | Why it is needed | How the user gets it | Saved as |
| --- | --- | --- | --- |
| Alerts the site treats as known and acceptable | To tell alerts needing action from alerts the site has accepted | Ask the site owner; compare with the alert IDs summarised in section 3 | `supplements/alerts-known.csv`: `alert_id,target,reason` |

## 5. Common cases

| Symptom | Meaning |
| --- | --- |
| The page has no alerts | No device reports an alert now. This is a normal result; use `machine health-history` to see whether there were any before |
| A device's level needs attention but it lists no alert | The page shows “未报告告警项”; record the level and the `health` content of `--json … show` |
| The same alert on many devices | Usually a site-wide cause (for example the same issue on one model); group by alert to see the extent and ask the user whether it is known |
| An alert carries `PreventAllocations` | NICo will not allocate that device; record the alert ID and the device |
| `target` is empty | The alert applies to the whole device; the page shows “—” |
| One device kind fails to read | The page endpoint's `errors` holds the text; retry it alone and record it as in section 6 of the [field survey guide](README.md) |

## 6. AI checklist

1. Run `tools/site-survey.sh check`. Continue only if it prints output with a Core version; on failure check the `SURVEY_*` variables, and if it still fails, stop and show the error to the user.
2. Run the three commands of step 1 in section 2 and note the count of each device kind.
3. Check whether the whole-site capture was done (`capture-*.json` under `$SURVEY_DIR`). If not, run `tools/site-survey.sh capture`; on exit code 2 fix the cause and rerun.
4. Count the devices with alerts with the first `jq` of section 3.
5. Count is 0:
   1. Confirm with the “abnormal level without alerts” check of section 3 that no device has an abnormal level.
   2. Take the first line of `alerts-machine-ids.txt` and run `tools/site-survey.sh --save alerts-machine-health-<machine ID>.txt cli machine health-history <machine ID>` to see whether there were alerts before.
   3. Record “no alerts at capture time” and go to step 9.
6. Count above 0: for each device kind take one device with alerts and run the matching commands of step 2 in section 2. Continue only on exit code 0; on failure retry once alone, and if it still fails record the command, error code and message and go on with the next.
7. Check each item of section 3 and record “pass” or what failed.
8. Show the alert IDs summarised in section 3 to the user and ask: “Are any of these alerts known to the site and acceptable?” If so, put them into `supplements/alerts-known.csv` (columns `alert_id,target,reason`) and ask the user to confirm; if not, or no answer, do not create the file.
9. In the “Alerts” section of `session.md` write: the Core version; the count of each device kind and of devices with alerts; each alert ID and count; the classifications seen; the result of each item of section 3; failed commands and error codes; known alerts the user confirmed; what to add or correct in section 2.5 of the data contract.
