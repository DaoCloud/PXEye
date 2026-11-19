# Field survey: switches

**English** · [简体中文](switches.zh-CN.md) · [Field survey guide](README.md)

Page: Equipment → Switches. The page lists the **NVLink switches** managed by NICo (rack-scale sites) with their state, health, power, NVOS management port and Fabric Manager status, and the device list. Ordinary Ethernet access switches are not managed by NICo and do not appear here; their connections are on [Cabling](cabling.md). For preparation (environment variables, observer instance, survey directory) see section 1 of the [field survey guide](README.md).

## 1. Data sources

| Page item | gRPC call the page code makes (request) | Equivalent nico CLI | Parity | Captured automatically |
| --- | --- | --- | --- | --- |
| Switch list, state, health, power | `FindSwitches` (`{}`) | `switch list`, `switch show <switch ID>` | Same | Yes |
| NVOS management port, Fabric Manager | `FindSwitches` (`{}`) | `switch show <switch ID>`; full record with `--json switch show <switch ID>` | Same | Yes |
| Device list (serial number, BMC MAC) | `GetAllExpectedSwitches` (`{}`) | `expected-switch show` | Same | Yes |
| Health history (not yet used by the page) | `FindSwitchHealthHistories` (not called by the page code) | `switch health-history <switch ID>` | Same | Yes, CLI only |
| Whether the site has NVLink switches | None | None | None | No, the user confirms |

The page code does not use the CLI; checks are decided by the gRPC call or the capture file (see section 1.3 of the [field survey guide](README.md)).

All fields are currently "defined only": the sites verified so far have no NVLink switches. Field mapping: section 2.2 of the [data contract](../design/rack-operations-data-contract.md).

## 2. Survey commands

Run from the repository root with the `SURVEY_*` variables exported as in section 1.2 of the [field survey guide](README.md).

Step one, count and IDs:

```bash
tools/site-survey.sh --save switches-ids.txt survey ids switches
```

The output has one switch ID per line. With 0 lines, run only the `GetAllExpectedSwitches` and `expected-switch show` commands below, then follow the "count is 0" branch in section 6.

Step two, each item. List and device list:

```bash
tools/site-survey.sh --save switches-find.txt survey call 'FindSwitches={}'
tools/site-survey.sh --save switches-list.txt cli switch list
tools/site-survey.sh --save switches-expected-find.txt survey call 'GetAllExpectedSwitches={}'
tools/site-survey.sh --save switches-expected.txt cli expected-switch show
tools/site-survey.sh --save switches-expected.json cli --json expected-switch show
```

Details and health history of one switch. Take `<switch ID>` from the first line of `switches-ids.txt`; also find a switch in `switches-list.txt` whose state is not ready or whose health is not OK, and repeat with its ID (if there is none, do only the first):

```bash
tools/site-survey.sh --save switches-show-<switch ID>.txt cli switch show <switch ID>
tools/site-survey.sh --save switches-show-<switch ID>.json cli --json switch show <switch ID>
tools/site-survey.sh --save switches-health-<switch ID>.txt cli switch health-history <switch ID>
tools/site-survey.sh --save switches-health-describe.txt survey describe FindSwitchHealthHistories
```

`survey call` output is structure only (long values shortened, lists keep the first item); for full data use the `cli --json` output or the capture file.

Step three, the raw capture is done once per site (section 2 of the [field survey guide](README.md)), not once per page. If it has not been done yet:

```bash
tools/site-survey.sh capture
```

## 3. Checks

When switches exist, **this is the first time real data is seen**; check field by field. `$C` below is the capture file, see section 3.1 of the [field survey guide](README.md).

| Item | Pass criterion | Compare with | Record on failure |
| --- | --- | --- | --- |
| Row count | Page rows equal the Core switch count | line count of `switches-ids.txt`; `jq '.pxeye_responses["/api/device-status"].body.switches \| length' $C`; `jq '[.pxeye_responses["/api/equipment"].body.devices[] \| select(.kind=="switch")] \| length' $C` | Extra or missing switch IDs or serial numbers |
| Association | Every device in the device list is linked to a NICo switch object | `switches-expected.json` against `switches-ids.txt`; `jq '.pxeye_responses["/api/equipment"].body.devices[] \| select(.kind=="switch")' $C` | Devices that do not link, with the identifiers on both sides |
| State, health, power | Match the CLI | `switches-list.txt`, `switches-show-<switch ID>.json`; `jq '.pxeye_responses["/api/device-status"].body.switches' $C` | Actual state text, health value, power value |
| NVOS management port | MAC and address match the CLI | `switches-show-<switch ID>.json`; the same `jq` | Why the port is empty, if it is |
| Fabric Manager | Status matches the CLI | `switches-show-<switch ID>.json`; the same `jq` | Actual status and reason text |
| Fields | Whether each "defined only" field in data contract section 2.2 has a value | `switches-show-<switch ID>.json`, `switches-expected.json` | Actual value of each field, or "empty" |
| Read errors | The page API has no switch read error | `jq '.pxeye_responses["/api/device-status"].body.errors' $C`; `jq '.summary' $C` | Error text, failed method and error code |

After checking, change the checked fields in data contract section 2.2 from "defined only" to "verified".

## 4. Data the user must provide

| Data | Why it is needed | How the user gets it | Stored as |
| --- | --- | --- | --- |
| Whether the site has NVLink switches | When the commands return nothing, tells "site has none" from "present but not managed" | Ask the site owner; check whether the racks are GB200, GB300 or similar rack-scale systems; compare with `tools/site-survey.sh cli rack list` | Written in `session.md` |
| Expected NVLink switch list (if any) | Shows which are not managed yet | Rack shipping list; declared ones are in `tools/site-survey.sh cli expected-switch show` | `supplements/switches-expected.csv`: `serial,bmc_mac,rack` |

## 5. Common cases

| Observation | Meaning |
| --- | --- |
| List empty, site has only Ethernet switches | Normal. The page does not apply to this site; see the Cabling page for connections |
| User says NVLink switches exist, but the list is empty | Not managed. Check whether `expected-switch show` declares them, and the probe results for the switch BMC addresses in Discovery diagnostics |
| In the device list but not in `FindSwitches` | Declared but not discovered yet; check the probe result for the `<BMC address>` on the Discovery diagnostics page |
| Switch present but health "unknown" | Core has not run a health check on it yet; record it and look again later |
| `FindSwitches` call fails | The page API `errors` contains "NICo 未返回交换机运行状态。"; retry and record per section 6 of the [field survey guide](README.md) |

## 6. AI checklist

1. Run `tools/site-survey.sh check`. Continue only if it prints output with a Core version; on failure check the `SURVEY_*` variables, and if it still fails stop and show the error to the user.
2. Run `tools/site-survey.sh --save switches-ids.txt survey ids switches` and count the lines.
3. Count is 0:
   1. Run `tools/site-survey.sh --save switches-expected-find.txt survey call 'GetAllExpectedSwitches={}'` and `tools/site-survey.sh --save switches-expected.txt cli expected-switch show`.
   2. Meaning: Core manages no NVLink switches; the page shows only the scope notice.
   3. Stop and ask the user: "Does this site have NVLink switches (GB200, GB300 or similar rack-scale systems)?" If yes, ask for the shipping list, put it into `supplements/switches-expected.csv` (columns `serial,bmc_mac,rack`) and ask the user to confirm it.
   4. User says no: record "not applicable" and go to step 9. User says yes: record "present but not managed", point to the Discovery diagnostics page, and go to step 9.
4. Count is above 0: run the five list and device-list commands of section 2 step two in order. Continue only on exit code 0; on failure retry once, and if it still fails record the command, error code and message and go on.
5. Use the first line of `switches-ids.txt` as `<switch ID>` and run the four single-switch commands of section 2; find a switch in `switches-list.txt` with abnormal state or health and run the first three again for it.
6. Check whether the site capture exists (`capture-*.json` under `$SURVEY_DIR`). If not, run `tools/site-survey.sh capture`; on exit code 2 fix the cause and run it again.
7. Check each item of section 3 and record "pass" or what failed.
8. Stop and ask the user: "How many NVLink switches should the site have? Please give the shipping list." Put it into `supplements/switches-expected.csv` (columns `serial,bmc_mac,rack`) and ask the user to confirm; if the user cannot provide it, record what is missing in `session.md`.
9. In the "Switches" section of `session.md` write: Core version; line count of `switches-ids.txt` and number of device-list entries; whether the site has NVLink switches (the user's answer); the result of each item in section 3; failed commands and error codes; missing user data; fields in data contract section 2.2 to mark "verified" or to correct.
