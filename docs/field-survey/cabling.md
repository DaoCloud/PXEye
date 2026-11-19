# Field survey: Cabling

**English** · [简体中文](cabling.zh-CN.md) · [Field survey guide](README.md)

Page: Device management → Cabling. Lists, per switch, which port each server interface is actually plugged into, and lists the servers without LLDP data. The data comes only from the LLDP neighbours on NICo machine objects: when a server goes through discovery, Scout receives the LLDP frames the switch sends on each interface and reports them. NICo does not need to manage these switches. Grouping by switch and port conflict detection are computed in the browser. For preparation (environment variables, `tools/site-survey.sh`, survey directory) see the [field survey guide](README.md).

## 1. Data sources

| Page item | gRPC call made by the page code (request) | Equivalent nico CLI | Parity | Collected automatically |
| --- | --- | --- | --- | --- |
| Server interface (name, MAC) | `FindMachineIds` `{}`, then `FindMachinesByIds` `{"machineIds":[...],"includeHistory":false}`: `status.lldp_neighbors[].mac_address`, `lldp.local_port` | `--json machine show <machine ID>` (the table view does not show LLDP) | Same | Yes |
| Switch identifier (usually the switch MAC) | Same: `lldp.id_value` | Same | Same | Yes |
| Switch name | Same: `lldp.name` | Same | Same | Only if the switch sends it |
| Switch model, serial | Same: `lldp.med_inventory` | Same | Same | Only if the switch sends it |
| Switch port | Same: `lldp.remote_port_value`, `lldp.remote_port_type` | Same | Same | Yes, but it may be a MAC instead of a port name |
| Servers without LLDP data | Same: `status.lldp_neighbors` empty | Same | Same | Yes |
| Collection time of LLDP | — | — | None | No: neither the RPC nor the CLI has this field |
| Panel port name (when the port ID is a MAC) | — | — | None | No, look it up on the switch (section 4) |
| Switch name (when the switch does not send it) | — | — | None | No, the user provides it (section 4) |
| Expected cabling | — | — | None | No, the user provides it (section 4) |

The page code does not use the CLI; checks rely on the gRPC call or the capture file (see [field survey guide section 1.3](README.md#13-how-cli-commands-relate-to-interfaces)).

The LLDP standard requires the switch identifier and port identifier; name, model and serial are optional. For the field mapping see section 2.4 of the [data contract](../design/rack-operations-data-contract.md).

## 2. Collection commands

Run the commands below from the repository root, with the `SURVEY_*` variables exported as in [field survey guide section 1.2](README.md#12-entry-script).

(1) Machine IDs and counts:

```bash
tools/site-survey.sh --save cabling-machine-ids.txt survey ids machines
tools/site-survey.sh --save cabling-machine-states.txt cli machine states --hosts
```

How to get `<machine ID>`: take the first line of `cabling-machine-ids.txt`; then in `cabling-machine-states.txt` find a host in a failed state (state name contains `Failed` or `Error`) and use its ID as the second `<machine ID>`. If no machine is in a failed state, use only the first.

(2) LLDP neighbours. gRPC call with the same request as the page code (the page code puts all IDs into `machineIds`; here only one):

```bash
tools/site-survey.sh --save cabling-find-machines-by-ids.txt survey call 'FindMachinesByIds={"machineIds":[{"id":"<machine ID>"}],"includeHistory":false}'
```

Equivalent CLI, printing the full machine record including `lldp_neighbors`:

```bash
tools/site-survey.sh --save cabling-machine-show-<machine ID>.txt cli --json machine show <machine ID>
```

Run both once for each selected `<machine ID>`. `survey call` output shows structure only (long values cut, lists keep the first item); for the full neighbour list use the `cli --json` output or the capture file. Empty `lldp_neighbors` means the machine has not run Scout yet, or its switch does not have LLDP enabled.

(3) The capture is run once per site as in [field survey guide section 2](README.md#2-common-procedure) (`tools/site-survey.sh capture`); it covers all pages, the cabling page needs no separate capture.

## 3. Checks

`C` is the capture file, for example `C=$SURVEY_DIR/capture-<date-time>.json` (see [field survey guide section 3.1](README.md#31-checking-pages-without-a-browser)).

| Item | Pass criterion | Compare with | Record when it fails |
| --- | --- | --- | --- |
| Servers with LLDP | The number of servers on the page equals the number of machines with neighbours | `jq '[.pxeye_responses["/api/device-status"].body.servers[] \| select((.lldp // []) \| length > 0)] \| length' $C` | Both numbers and the differing machine IDs |
| Interface count | Each server's interface count equals its LLDP neighbour count | Number of `lldp_neighbors` in `cli/cabling-machine-show-<machine ID>.txt`, against `jq '.pxeye_responses["/api/device-status"].body.servers[] \| select(.id=="<machine ID>") \| .lldp \| length' $C` | Servers that differ |
| Interface fields | Interface name, MAC, switch identifier and port match the CLI | `cli/cabling-machine-show-<machine ID>.txt` against `jq '.pxeye_responses["/api/device-status"].body.servers[] \| select(.id=="<machine ID>") \| .lldp' $C` | Fields that differ and both values |
| Switch grouping | Ports of one physical switch are in one group | `jq '[.pxeye_responses["/api/device-status"].body.servers[].lldp[]? \| {switch_id, switch}] \| unique' $C`; grouping itself is computed in the browser, use `core-replay.py serve` if needed | Switches split into several groups or merged into one, with the switch identifiers |
| Switch name | Shows the name when present, otherwise the switch MAC | Whether `switch` is empty in the output of the previous row | Items the switch did not send (name, model, serial) |
| Port identifier | Record the port ID type (`mac`, port name or other) | `jq '[.pxeye_responses["/api/device-status"].body.servers[].lldp[]?.remote_port_type] \| unique' $C` | An example of each type |
| Port conflicts | Each conflict marked red is confirmed on site as real or not | `jq '[.pxeye_responses["/api/device-status"].body.servers[] \| .id as $m \| .lldp[]? \| select((.remote_port // "") != "" and ((.switch_id // .switch // .switch_serial // "") != "")) \| {k:((.switch_id // .switch // .switch_serial) + " " + .remote_port), m:$m, mac_address:(.mac_address // .local_port)}] \| group_by(.k) \| map(unique_by({m, mac_address})) \| map(select(length>1))' $C` | Location of real conflicts; cause of false ones |
| No LLDP data | The listed servers really have no neighbour records | `jq '[.pxeye_responses["/api/device-status"].body.servers[] \| select((.lldp // []) \| length == 0) \| .id]' $C`, confirm one with `cli --json machine show <machine ID>` | Cause: Scout not run, or LLDP off on the switch |
| Servers without a NICo machine | The page total “servers without LLDP data” = the count in the previous row + console servers with no matching NICo machine (the page matches by `machine_id`, then by BMC MAC) | Page total minus the previous row; for each server check its machine ID with `jq '.pxeye_responses["/api/device-status"].body.servers \| keys' $C` | Serials of servers without a machine; cause: not managed, or BMC MAC differs |

A conflict on the page only means the data contradicts itself (one port reported by two interfaces); it does not mean a wrong cable. The conflict jq groups by switch identifier and port, so the same interface of one machine reported twice also appears; check whether the entries come from different interfaces.

## 4. Data the user provides

| Data | Why it is needed | How the user gets it | Save as |
| --- | --- | --- | --- |
| Switch name, model, management address | Without a name from the switch the page shows only a MAC, and you cannot tell which switch it is | The network administrator's inventory; or the local information on the switch (below) | `supplements/cabling-switches.csv`: `chassis_mac,name,model,serial,management_ip,rack` |
| Port MAC to panel port name | When the port ID is a MAC, you cannot find the port on the panel | The local LLDP information per port on the switch (below) | `supplements/cabling-switch-ports.csv`: `chassis_mac,port_id,port_name` |
| Expected cabling (optional) | Without it you see only actual connections and cannot tell a wrong cable | Cabling plan or installation drawing | `supplements/cabling-expected.csv`: `server_serial,server_port,switch_name,switch_port` |
| Whether LLDP is enabled on the switches | Explains servers with “no LLDP data” | Confirmed by the network administrator | Write in `session.md` |

Fill `chassis_mac` and `port_id` with the values shown on the page, so the supplements can be matched to the LLDP records.

### Viewing local information on the switch

Run by the network administrator on the switch. The device manual is authoritative; common vendors:

| Switch OS | Local identifier and port ID of each port | Neighbour list (for comparison) |
| --- | --- | --- |
| H3C Comware, Huawei VRP | `display lldp local-information` | `display lldp neighbor-information list` |
| Arista EOS | `show lldp local-info` | `show lldp neighbors detail` |
| Systems using lldpd (Cumulus Linux; on SONiC run in the `lldp` container) | `lldpcli show interfaces` | `lldpcli show neighbors` |

For other systems look up the command that shows “LLDP local information” in the manual.

Save the output as `supplements/cabling-<switch name>-lldp.txt`, then turn it into the two CSV files above. Only read-only show commands are needed; the switch configuration is not changed.

## 5. Common cases

| Symptom | Meaning |
| --- | --- |
| The port shows as a MAC | The switch uses the port MAC as port ID (for example the H3C default). Use the commands above to add the mapping |
| A server has no neighbours | Scout has not run yet, LLDP is off on the switch, or a device in between does not forward LLDP |
| No server has neighbours | LLDP is generally off on the switches, or no machine has gone through discovery yet; ask the network administrator |
| Same switch identifier, different names | Possibly a switch stack; record it |
| The page does not change after recabling | LLDP records are a snapshot from Scout's last run; wait for Scout to run again. The record has no time, so the data cannot show whether it is old |
| `machine show` table shows no LLDP | The table view does not show LLDP; add `--json` |

## 6. AI checklist

1. Run `tools/site-survey.sh --save cabling-machine-ids.txt survey ids machines`. If it succeeds, record the line count and go to step 2. If it fails, retry once as in [field survey guide section 5](README.md#5-rules-for-ai); if it still fails, record the error and stop.
2. Line count 0: NICo has no machines, the cabling page has no content at this site. Ask the user: “Are this site's servers managed by NICo? Does Device management show servers?” Write the answer into `session.md` and stop this page.
3. Run `tools/site-survey.sh --save cabling-machine-states.txt cli machine states --hosts` and pick one or two `<machine ID>` as in section 2.
4. For each `<machine ID>` run the `survey call 'FindMachinesByIds=...'` and `cli --json machine show <machine ID>` from section 2. Continue when both succeed.
5. Look at `lldp_neighbors` in `cli/cabling-machine-show-<machine ID>.txt`. If all are empty, ask the user: “Is LLDP enabled on the switches? Have these machines run discovery (Scout)?” Record the answer.
6. Make sure `tools/site-survey.sh capture` has run once for this site; if not, run it. Continue only on exit code 0; on 2 fix the cause and run it again.
7. Run each jq in section 3 and compare; record pass or fail for each item.
8. If switch names are empty or the port type is `mac`, stop and ask the user: “Please provide switch name, model, serial, management address and rack in `supplements/cabling-switches.csv` (columns `chassis_mac,name,model,serial,management_ip,rack`), and the port MAC to panel port name mapping in `supplements/cabling-switch-ports.csv` (columns `chassis_mac,port_id,port_name`). You can get them with the read-only switch commands in section 4.”
9. Ask the user whether an expected cabling plan exists; if so save it as `supplements/cabling-expected.csv` (columns `server_serial,server_port,switch_name,switch_port`), otherwise record “not provided”. Have the user confirm any CSV you assembled before saving.
10. Write into `session.md` for this page: Core version; machine count and number of servers with LLDP; port ID types; the result and differences of each check in section 3; port conflicts and the on-site confirmation; servers without LLDP and the cause (two groups: machine with empty LLDP; no NICo machine); supplements received and missing (what is missing, which item it affects); failed commands with error codes.
