# Field survey: cabling

**English** · [简体中文](cabling.zh-CN.md) · [Field survey guide](README.md)

Page: Device management → Cabling. Lists, per switch, which port each server network port is actually connected to. The data comes only from the LLDP neighbors on NICo machine objects: when a server enters discovery, Scout receives the LLDP packets that the switch sends on each network port and reports them. NICo does not need to manage these switches. For preparation and the common procedure, see the [Field survey guide](README.md).

## 1. Data sources

| Page content | NICo CLI | gRPC interface | Captured automatically |
| --- | --- | --- | --- |
| Server network port (port name, MAC) | `machine show <machine ID>` | `FindMachinesByIds` `status.lldpNeighbors[].macAddress`, `lldp.localPort` | Yes |
| Switch identifier (usually the switch MAC) | Same as above | `lldp.idValue` | Yes |
| Switch name | Same as above | `lldp.name` | Only if the switch sends it |
| Switch model, serial number | Same as above | `lldp.medInventory` | Only if the switch sends it |
| Switch port | Same as above | `lldp.remotePortValue`, `remotePortType` | Yes, but it may be a MAC rather than a port name |
| Capture time | — | — | No: the record has no time field |
| Front-panel port name (when the port identifier is a MAC) | — | — | No, look it up on the switch |
| Expected cabling | — | — | No, the user must provide it |

The LLDP standard requires the switch to send the chassis identifier and the port identifier; name, model and serial number are optional. For the field mapping, see section 2.4 of the [data contract](../design/rack-operations-data-contract.md).

## 2. Capture commands

```bash
D=<survey directory>/cli
cli --json machine show --hosts                  > $D/cabling-machines.json
```

The LLDP neighbors of each machine are in the machine details. Check a few machines:

```bash
M=<machine ID>
survey call 'FindMachinesByIds={"machineIds":[{"id":"'$M'"}]}' > $D/cabling-$M.txt
```

An empty `status.lldpNeighbors` means that Scout has not run on this machine yet, or that its switch does not have LLDP enabled.

A full-site capture records all LLDP neighbors of every machine as they are. The cabling page needs no separate capture.

## 3. Checks

| Item | Pass criterion | Record on failure |
| --- | --- | --- |
| Network port count | Each server's port count on the page equals its number of LLDP neighbors | Servers that do not match |
| Switch grouping | Ports of the same physical switch are in the same group | Cases split into several groups or mixed into one group, with the switch identifiers at the time |
| Switch name | Switches with a name show the name; others show the switch MAC | Items the switch does not send (name, model, serial number) |
| Port identifier | Record the type of port identifier (`mac`, port name or other) | An example of each type |
| Port conflict | Confirm on site whether each conflict marked in red is real | Location of real conflicts; cause of false reports |
| No LLDP data | The listed servers really have no neighbor records | Cause: Scout has not run, or the switch does not have LLDP enabled |

A conflict on the page only means the data contradicts itself (one port reported by two network ports). It does not mean a cable is wrong.

## 4. Data the user must provide

| Data | Why it is needed | How the user gets it | Saved as |
| --- | --- | --- | --- |
| Switch name, model, management address | When the switch sends no name, the page can only show a MAC and you cannot tell which switch it is | The network administrator's device inventory; or view the local information on the switch (see below) | `supplements/cabling-switches.csv`: `chassis_mac,name,model,serial,management_ip,rack` |
| Mapping from port MAC to front-panel port name | When the port identifier is a MAC, you cannot find the port on the panel directly | View the local LLDP information of each port on the switch (see below) | `supplements/cabling-switch-ports.csv`: `chassis_mac,port_id,port_name` |
| Expected cabling (optional) | Without it you only see actual connections and cannot tell whether a cable is wrong | Cabling plan or installation drawings | `supplements/cabling-expected.csv`: `server_serial,server_port,switch_name,switch_port` |
| Whether LLDP is enabled on the switches | Explains servers with "no LLDP data" | Confirmed by the network administrator | Written in `session.md` |

Fill `chassis_mac` and `port_id` with the values shown on the page. They match the supplementary data to the LLDP records.

### Viewing local information on the switch

The network administrator runs these on the switch. The device manual is authoritative; below are the usual commands for common vendors:

| Switch system | Local identifier and port identifiers of each port | Neighbor list (for comparison) |
| --- | --- | --- |
| H3C Comware, Huawei VRP | `display lldp local-information` | `display lldp neighbor-information list` |
| Arista EOS | `show lldp local-info` | `show lldp neighbors detail` |
| Systems using lldpd (Cumulus Linux; on SONiC, run in the `lldp` container) | `lldpcli show interfaces` | `lldpcli show neighbors` |

For other systems, look up the command that shows "LLDP local information" in the device manual.

Save the output as `supplements/cabling-<switch name>-lldp.txt`, then turn it into the two CSV files above. Only read-only show commands are needed; the switch configuration does not need to change.

## 5. Common cases

| Symptom | Interpretation |
| --- | --- |
| The port shows as a MAC string | The switch uses the port MAC as the port identifier (for example, the H3C default). Add the mapping with the commands above |
| A server has no neighbors at all | Scout has not run yet, or the switch does not have LLDP enabled, or a device in between does not forward LLDP |
| Same switch identifier, different names | Possibly a switch stack; record it |
| The page does not change after recabling | The LLDP record is a snapshot from Scout's last run; wait for Scout to run again |
