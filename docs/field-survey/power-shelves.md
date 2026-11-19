# Field survey: power shelves

**English** · [简体中文](power-shelves.zh-CN.md) · [Field survey guide](README.md)

Page: Device management → Power shelves. A power shelf in NICo is the **Power Shelf** of a rack-scale site. Rack PDUs are not managed by NICo and do not appear here. For preparation and the common procedure, see the [Field survey guide](README.md).

## 1. Data sources

| Page content | NICo CLI | gRPC interface | Captured automatically |
| --- | --- | --- | --- |
| Power shelf list, status, health, power | `power-shelf list`, `power-shelf show <power shelf identifier>` | `FindPowerShelves` | Yes |
| Capacity, voltage | `power-shelf show <power shelf identifier>` | `FindPowerShelves` | Yes |
| Device inventory (serial number, PMC MAC) | `expected-power-shelf show` | `GetAllExpectedPowerShelves` | Yes |
| Health history | `power-shelf health-history <power shelf identifier>` | `FindPowerShelfHealthHistories` | Yes (not yet used by the page) |
| Live power | — | — | No: NICo returns no power readings |
| Whether the site has power shelves | — | — | No; the user must confirm |

All fields are currently "definition only": the verified site has no power shelves. For the field mapping, see section 2.3 of the [data contract](../design/rack-operations-data-contract.md).

## 2. Capture commands

```bash
D=<survey directory>/cli
cli power-shelf list                             > $D/power-shelves-list.txt
cli expected-power-shelf show                    > $D/power-shelves-expected.txt
```

When both are empty, the page shows a scope note. After you confirm this matches the site (see section 4), you are done.

When power shelves exist, run for each one:

```bash
P=<power shelf identifier>
cli power-shelf show $P                          > $D/power-shelves-$P-show.txt
cli --json power-shelf show $P                   > $D/power-shelves-$P-show.json
cli power-shelf health-history $P                > $D/power-shelves-$P-health.txt
```

A full-site capture records the `FindPowerShelves` response as returned.

## 3. Checks

| Item | Pass criterion | Record on failure |
| --- | --- | --- |
| Row count | Page row count equals the number of power shelves in device management | Extra or missing serial numbers |
| Association | Each one is associated with a NICo power shelf object | Devices that cannot be associated, and the identifiers on both sides |
| Status, health, power | Match `power-shelf show` | Actual status text, health value, power value |
| Capacity, voltage | Match `power-shelf show`, in watts and volts | Actual values and units |
| Fields | Whether each "definition only" field in section 2.3 of the data contract actually has a value | Actual value of each field, or "empty" |

## 4. Data the user must provide

| Data | Why it is needed | How the user gets it | Saved as |
| --- | --- | --- | --- |
| Whether the site has power shelves | When commands return nothing, tells "the site has none" apart from "present but not managed" | Ask the site owner; check whether the site is rack-scale | Written in `session.md` |
| Expected power shelf list (if any) | Shows which ones are not yet managed | The rack-scale shipping list | `supplements/power-shelves-expected.csv`: `serial,pmc_mac,rack` |
| Rack PDU list (optional) | NICo does not manage PDUs; rack power work later needs to know which PDUs exist and how to reach them | The data center power documentation | `supplements/power-pdus.csv`: `rack,name,model,management_ip,protocol` |

Fill `protocol` with the management protocol the PDU supports, for example `snmp`, `redfish`, `http`. Record information only; no passwords are required.

## 5. Common cases

| Symptom | Assessment |
| --- | --- |
| List is empty and the site uses ordinary server racks | Normal. This page does not apply to the site |
| User asks how much power a rack uses | NICo does not provide it and the page cannot show it. Record the user's need and the PDU list |
