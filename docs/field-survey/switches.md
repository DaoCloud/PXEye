# Field survey: switches

**English** · [简体中文](switches.zh-CN.md) · [Field survey guide](README.md)

Page: Device management → Switches. A switch in NICo means only an **NVLink switch** (rack-scale sites). Ordinary Ethernet access switches are not managed by NICo and do not appear here; for their connections see [Cabling](cabling.md). For preparation and the general procedure see the [Field survey guide](README.md).

## 1. Data sources

| Page content | NICo CLI | gRPC interface | Captured automatically |
| --- | --- | --- | --- |
| Switch list, status, health, power | `switch list`, `switch show <switch ID>` | `FindSwitches` | Yes |
| NVOS management port, Fabric Manager | `switch show <switch ID>` | `FindSwitches` | Yes |
| Device inventory (serial number, BMC MAC) | `expected-switch show` | `GetAllExpectedSwitches` | Yes |
| Health history | `switch health-history <switch ID>` | `FindSwitchHealthHistories` | Yes (not yet used by the page) |
| Whether the site has NVLink switches | — | — | No, the user must confirm |

All fields are currently "definition only": the verified sites have no NVLink switches. For the field mapping see section 2.2 of the [data contract](../design/rack-operations-data-contract.md).

## 2. Capture commands

```bash
D=<survey directory>/cli
cli switch list                                  > $D/switches-list.txt
cli expected-switch show                         > $D/switches-expected.txt
```

When both are empty, the page shows a scope note and has no content at this site. Once you confirm this matches reality (see section 4), you are done.

When switches exist, run for each one (or a few representative ones):

```bash
S=<switch ID>
cli switch show $S                               > $D/switches-$S-show.txt
cli --json switch show $S                        > $D/switches-$S-show.json
cli switch health-history $S                     > $D/switches-$S-health.txt
```

The full-site capture records the `FindSwitches` response as is.

## 3. Checks

When switches exist, **this is the first time real data is seen**. Check every field:

| Item | Pass criterion | Record on failure |
| --- | --- | --- |
| Row count | Page row count equals the switch count in device management | Extra or missing serial numbers |
| Association | Each one is associated with a NICo switch object | Devices that do not associate, and the identifiers on both sides |
| Status, health, power | Match `switch show` | The actual status text, health value and power value |
| NVOS management port | Management port MAC and address match `switch show` | The reason when the management port is empty |
| Fabric Manager | State matches `switch show` | The actual state and reason text |
| Fields | Whether each "definition only" field in section 2.2 of the data contract actually has a value | The actual value of each field, or "empty" |

After the checks, change the checked fields in section 2.2 of the data contract from "definition only" to "verified".

## 4. Data the user must provide

| Data | Why it is needed | How the user gets it | Saved as |
| --- | --- | --- | --- |
| Whether the site has NVLink switches | When the commands return nothing, tells "the site has none" from "present but not managed" | Ask the site owner; check whether the rack model is a rack-scale system such as GB200 or GB300 | Written in `session.md` |
| Expected NVLink switch list (if any) | Shows which ones are not yet managed | The rack-scale shipping list | `supplements/switches-expected.csv`: `serial,bmc_mac,rack` |

## 5. Common situations

| Symptom | Assessment |
| --- | --- |
| The list is empty and the site has only Ethernet switches | Normal. This page does not apply at this site; see the cabling page for connections |
| The user says there are NVLink switches, but the list is empty | Not managed. Check whether `expected-switch show` declares them, and the probe results for the switch BMC addresses in discovery diagnostics |
| Switches exist but health is "unknown" | Core has not run health checks on them yet. Record it and check again later |
