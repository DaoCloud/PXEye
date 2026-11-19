# Rack operations: NICo data contract

**English** · [简体中文](rack-operations-data-contract.zh-CN.md) · [Design documents](README.md)

Which NICo Core interface and which fields each page uses, and whether they were verified at a real site. Use this document to fetch data when developing and testing at a new site.

- Evidence: on 2026-11-19, at a general server site, the Core definitions were read through server reflection and called read-only. The Core held one server and no switch, power shelf, rack or SKU. Nothing here is inferred from source code or online documentation.
- With a different Core version, repeat section 1 first.
- Marks: **verified** = real data existed at the site and was checked; **definition only** = the interface exists but returned nothing, so the fields come from the definition; **unavailable** = the call failed or does not return what is needed.

## 1. Fetching data

`tools/core-survey.py` runs inside a PXEye container and uses the Core address and client identity that instance already has. It reads the Core actually deployed at the site through gRPC reflection. Run it in a read-only observer instance.

```bash
survey() { kubectl -n <namespace> exec -i deploy/<pxeye> -c pxeye -- python3 - "$@" < tools/core-survey.py; }

survey list                          # callable read methods
survey describe FindSwitches         # request and response of a method
survey message forge.Machine         # full definition of a message
survey call 'FindRackIds={}'         # call it and print the response structure
survey call 'FindMachineStateHistories={"machineIds":[{"id":"MID"}]}'
```

Rules:

- Only methods named `Find*`, `Get*`, `List*` or `Determine*` can be called.
- Methods that return credentials or serve the boot path are refused even though they read: any name containing `Credential`, `Password`, `Secret` or `Token`, and `GetBMCMetaData`, `GetPxeInstructions`, `GetCloudInitInstructions`.
- Output redacts fields whose names look like credentials and shortens long values. It shows the structure of a response, not a copy of the site's data.
- `MID` in a `call` body is replaced with the first machine ID the Core returns.
- Raw site responses do not enter this repository. Test samples use placeholder values.
- This tool shows structure only. To keep responses verbatim, use `tools/core-capture.py`; see the [field survey guide](../field-survey/README.md).

Conventions in the responses:

| Observation | Handling |
| --- | --- |
| Field names are camelCase (proto JSON) | Convert with `snake()` from `services/equipment.py` before business code |
| Empty lists, `false` and zero enum values are absent; `{}` means none | Use `.get(key) or default`; never assume a key exists |
| Two ID shapes: machines are `{"id": …}`; switches, power shelves and racks are `{"value": …}` | `object_id()` accepts both |
| A machine state is text such as `Ready` or `Failed/…`; state history holds JSON documents | `state_text()` in `services/device_status.py` handles both |
| MAC addresses are upper case | Lower-case before comparing |

A read-only observer admits only `Find`, `Get` and `Determine` at the application layer. Before a page uses a `List*` interface, add it in `read_only.py` and confirm no `List*` method writes.

## 2. Implemented pages

Backend `services/device_status.py`, endpoints `GET /api/device-status` and, per machine, `GET /api/device-status/machines/<machine ID>/history` and `…/firmware` (machine IDs must match `[a-z0-9]{1,128}`; any other path returns 404); frontend `web/pages/device_status.js`; tests `tests/unit/test_device_status.py`.

The device list comes from the existing `GET /api/equipment`. Status is joined to a device as follows:

| Kind | Join |
| --- | --- |
| Server | The `machine_id` of that serial number in `/api/resources`; otherwise the MAC of the device's `host_bmc` interface against the machine's `bmc.mac` |
| Switch, power shelf | `native_id` of the device in `/api/equipment` against `id.value` of the Core object |

### 2.1 Servers

Interface: `FindMachineIds {}`, then `FindMachinesByIds {"machineIds":[…],"includeHistory":false}`, returning `machines[]` (`forge.Machine`).

| Page content | Field (snake case) | Verification |
| --- | --- | --- |
| Status | `status.lifecycle.state`, falling back to `state` | verified |
| State reason | `status.lifecycle.state_reason.outcome_msg` | verified |
| Handler outcome | `status.lifecycle.state_reason.outcome`: `ERROR`, `TRANSITION`, `DO_NOTHING`, `TODO`; `WAIT` is the zero value and is absent | `ERROR` verified; other values definition only |
| Past the state time limit | `status.lifecycle.sla.time_in_state_above_sla` | verified |
| Health | `status.health.alerts[]`: `id`, `target`, `message`, `in_alert_since`, `classifications`; `status.health.source`, `observed_at` | verified; `target` definition only |
| Power | `power_state` from `/api/equipment` (from `GetPowerOptions`) | verified |
| BMC address | `bmc.ip`, `bmc.mac`, falling back to `bmc_info` | verified |
| Uplink switches, LLDP neighbours | `status.lldp_neighbors[]`: `mac_address`, `lldp.name`, `lldp.local_port`, `lldp.id_value`, `lldp.remote_port_type`, `lldp.remote_port_value`, `lldp.med_inventory.{serial,manufacturer,model}`, `lldp.description` | verified |
| Hardware capabilities | `status.capabilities.{cpu,gpu,memory,storage,network,infiniband,dpu}[]`: `name`, `count`, `vendor`, `capacity` | `cpu`, `memory`, `storage`, `network` verified; `gpu`, `infiniband`, `dpu` definition only |
| Failure details, last reboot, Scout version | `status.failure_details`, `status.last_reboot_time`, `status.last_scout_observed_version` | verified |
| Rack | `rack_id.value`. Declared by hand through `rack_id` of the expected device; Core does not discover it | definition only |
| Slot, tray | `placement_in_rack.{slot_number,tray_index}`. The expected device declaration has no input for it | definition only |
| SKU | `config.hw_sku`, `status.hw_sku.last_match_attempt` | definition only |
| BMC firmware | `status.bmc_status.firmware_version` | unavailable: returned empty. Firmware versions come from `GetComponentInventory`, see 3.2 |
| Quarantine, maintenance | `status.quarantine.{mode,reason}`, `config.maintenance_reference` | definition only |
| Associated DPUs | `status.associated_dpu_machine_ids[]` | definition only |

“Needs attention” means `outcome` is `ERROR`, or the state is past its time limit, or there is a health alert.

To verify: whether a machine with a DPU returns both the host and the DPU; the state text of a machine with an instance; the latency and size of one request for all IDs at a large site.

### 2.2 Switches

A Core Switch is an NVLink switch only. Interface: `FindSwitches {}`, returning `switches[]` (`forge.Switch`). All fields are definition only.

| Page content | Field |
| --- | --- |
| Status | `status.lifecycle.state`, falling back to `status.controller_state`, `controller_state` |
| Health | `status.health_status` (`ok`, `warning`, `critical`), `status.health.alerts[]` |
| Power | `status.power_state` (`on`, `off`, `standby`) |
| NVOS management ports | `status.nvos_ports[]`: `mac`, `is_primary`, `service_port`, `addresses[].address` |
| Fabric manager | `status.fabric_manager_status`, `status.fabric_manager_status_details.{fabric_manager_state,reason,error_message}` |
| BMC | `bmc_info.{ip,mac,firmware_version}` |
| Rack, slot | `rack_id.value`, `placement_in_rack` |
| Other | `is_primary`, `nvlink_domain_uuid.value`, `config.enable_nmxc`, `status.serial_number` |

### 2.3 Power shelves

A Core power shelf has no outlets, and rack PDUs are not in Core. Interface: `FindPowerShelves {}`, returning `powerShelves[]` (`forge.PowerShelf`). All fields are definition only.

| Page content | Field |
| --- | --- |
| Status, health, power | As for switches |
| Capacity, voltage | `config.capacity` (watts), `config.voltage` (volts) |
| BMC (PMC) | `bmc_info.{ip,mac,firmware_version}` |
| Rack | `rack_id.value` |

### 2.4 Cabling

No new Core interface. The data is `status.lldp_neighbors` from 2.1, read through `servers[].lldp` of `/api/device-status`, and the page groups by switch (its name, else `id_value`, else serial). A switch port reported by different interfaces is a conflict. When `remote_port_type` is `mac` the port shows as a MAC; no interface name is guessed.

To verify: values of `remote_port_type` other than `mac`; a real port conflict; a switch with a serial but no name or ID.

## 3. Interfaces for candidate pages

### 3.1 Machine state timeline (verified, implemented)

`FindMachineStateHistories {"machineIds":[{"id":"<machine ID>"}]}`

```json
{"histories": {"<machine ID>": {"records": [
  {"event": "{\"state\": \"created\"}", "time": "2026-01-01T00:00:00Z", "version": "V2-T…"},
  {"event": "{\"state\": \"hostinit\", \"machine_state\": {\"state\": \"waitingforlockdown\"}}", "time": "…", "version": "…"},
  {"event": "{\"state\": \"ready\"}", "time": "…", "version": "…"}
]}}}
```

`event` is JSON text with nested `state` values. The time spent in a state is the difference between consecutive `time` values; the last record runs to now. Switches, power shelves and racks have matching `Find…StateHistories` interfaces, definition only.

Implementation: `/history` returns `{observed_at, records:[{state, entered_at, duration_seconds, current}]}`. Records are ordered by `time`, and consecutive identical state texts become one stay that keeps the first entry time. `time` is parsed as RFC 3339 and may carry more than six fraction digits; unreadable records are skipped. `state_text()` follows `state` keys only, so sub-objects without one (such as retry counts) are not told apart and those sub-steps merge into one stay. No history returns an empty list.

To verify: whether the number of records is capped; the raw `time` format, once more on a real site.

### 3.2 Firmware inventory (verified, implemented)

`GetComponentInventory {"machineIds":{"machineIds":[{"id":"<machine ID>"}]}}`. The request is a one-of; `switchIds`, `powerShelfIds` or BMC MAC lists are also accepted.

```json
{"entries": [{"result": {"componentId": "<machine ID>"}, "report": {
  "endpointType": "Bmc", "vendor": "<vendor>",
  "systems": [{"id": "1", "manufacturer": "…", "serialNumber": "…", "pcieDevices": [{"id": "…", "name": "…", "firmwareVersion": "…"}], "ethernetInterfaces": [{"macAddress": "…", "linkStatus": "LinkUp"}]}],
  "chassis": [{"id": "1", "model": "…", "partNumber": "…", "serialNumber": "…", "manufacturer": "…"}],
  "service": [{"id": "FirmwareInventory", "inventories": [
    {"id": "BMC-Primary", "description": "…", "version": "…", "releaseDate": "…"},
    {"id": "UEFI", "description": "…", "version": "…", "releaseDate": "…"}]}],
  "machineSetupStatus": {"isDone": true},
  "secureBootStatus": {},
  "lockdownStatus": {"message": "…"}}}]}
```

- The `id` of a firmware entry is the vendor's own naming and differs between vendors; do not match on fixed names.
- The report is the Redfish result of site exploration and also carries the model, part number, lockdown state and secure boot state.
- Baseline: `GetDesiredFirmwareVersions {}` returns `entries[]` (`vendor`, `model`, `componentVersions`); `ListHostFirmware {}` returns `available[]`. The verification site had entries for DPUs only and no host baseline, so host firmware can be shown but not judged compliant.
- Unavailable: `ListComponentFirmwareVersions` returns `Unimplemented` for servers.
- `GetComponentFirmwareStatus` returns `statuses[]` (`result.componentId`, `state`); its meaning is not yet understood.
- Implementation: `/firmware` returns `vendor`, `endpoint_type`, `chassis.{model,part_number,manufacturer}` (the first chassis with a model), `lockdown` (`lockdownStatus.message`), `secure_boot` (as given), `entries[].{id,description,version,release_date}`, and `reported`, `note`, `observed_at`. Entries with an empty version are kept. Without a report, `reported` is false and no error is raised. It is read once per machine when the dialog opens; the list does not read it per row.
- To verify: whether one request can carry many machines; whether this interface reads a cache or reaches the BMC; the fields of a non-empty `secureBootStatus`.

### 3.3 Discovery diagnostics (verified, implemented)

`GetSiteExplorationReport {}`

```json
{"endpoints": [{"address": "<BMC address>", "preingestionState": "Initial",
   "report": {"endpointType": "Unknown", "lastExplorationLatency": "10.0s",
     "lastExplorationErrorSchema": {"errorCode": "NICO-SITEEXPLORER-101", "text": "…", "mitigation": "…"}}}],
 "managedHosts": [{"hostBmcIp": "<BMC address>"}],
 "lastRun": {"startedAt": "…", "finishedAt": "…", "success": true, "endpointExplorations": "5", "endpointExplorationsSuccess": "1", "endpointExplorationsFailed": "4"}}
```

For an endpoint explored successfully, `report` has the same structure as in 3.2. Related interfaces: `FindExploredEndpointIds` and `FindExploredEndpointsByIds` (already used by existing code), `GetAllUnexpectedMachines`.


Implementation: `GET /api/exploration` (only with `rack_operations` on). The `report` of a successful endpoint is a full Redfish inventory; only the address, type, vendor, ingestion stage, latency, error code / text / mitigation, the `Type` in `lastExplorationError` (raw text when not JSON), report version, reset and reboot times, whether it is a managed host, and for successful endpoints the system serial and model are kept. `lastRun` counts arrive as strings and are converted to integers. The page joins endpoints to devices by address.

A failed `lastRun` has been seen at a real site: `success` false, `error` “Site Explorer credentials are missing or invalid”, `failureCategory` `missing_credentials`, all counts 0 and no endpoints. The page shows this failure and its cause at the top.

To verify: serial and model have never been extracted from a full real report; a `machineId` has not been seen; other values of `failureCategory`.

### 3.4 Hardware validation (partly verified, implemented)

| Interface | Returns | Verification site |
| --- | --- | --- |
| `GetMachineValidationRuns {"machineId":{"id":…}}` | `runs[]`: `validationId.value`, `startTime`, `endTime`, `name`, `context`, `status`, `durationToComplete` | One run, skipped |
| `GetMachineValidationResults {"machineId":{"id":…}}` | `results[]` | Empty |
| `GetMachineValidationTests {}` | `tests[]`: `testId`, `name`, `description`, `contexts`, `command`, `timeout`, `supportedPlatforms`, `isEnabled` | 11 built-in tests |
| `GetAllSkuIds {}`, then `FindSkusByIds {"ids":[…]}` | SKU definitions | Empty |


Implementation: `/api/device-status/machines/<machine ID>/validation` reads runs and results with `includeHistory: true` and groups results by validation ID; it does not read the test list per machine. A run's `status` is a one-of object (such as `{"completed": "Skipped"}`), turned into short text and kept as given. stdout and stderr in results are cut to 2000 characters each and are not shown in the list. A missing `exitCode` counts as 0 (Core omits zero values); exit code 0 shows as passed.

To verify: the fields of a validation result (`forge.MachineValidationResult`) have never been seen at a site and are definition only; `Success`, `Failed` and in-progress states have not been seen; `durationToComplete` has only been seen as `0s`.

### 3.5 Health history (verified, implemented)

`FindMachineHealthHistories {"machineIds":[{"id":…}]}`, optionally with `startTime` and `endTime`. It returns `histories.<machine ID>.records[]`, each with `time` and `health` (the structure of health in 2.1). `ListMachineHealthReports` and `ListHealthReportOverrides` returned nothing at the verification site. Current alerts come from `status.health.alerts` of each object.


Implementation: `/api/device-status/machines/<machine ID>/health` orders the records by time and, per alert ID and `target`, merges consecutive records into a period: its start is `inAlertSince`, or the first record time when absent; a record without the alert ends the period, and a return starts a new one. Only alerts in the latest record count as still present. The record count and time span are returned too.

To verify: whether the number of records is capped for a long-running machine; alerts with a non-empty `target`.

### 3.6 Power details (verified)

`GetComponentPowerDetails {"machineIds":{"machineIds":[{"id":…}]}}` returns `entries[]`: `componentId`, `actual.{state,source,observedAt}`, `desired.{status,state,source}`, `actions`. Compared with `GetPowerOptions` it adds the source and observation time. It has no power readings.

### 3.7 Racks (definition only)

| Interface | Returns | Verification site |
| --- | --- | --- |
| `FindRackIds {}`, then `FindRacksByIds {"rackIds":[…]}` | `racks[]` (`forge.Rack`): `id`, `rack_state`, `config`, `status.{health,lifecycle}`, `rack_group_id` | Empty |
| `GetAllExpectedRacks {}` | `expected_racks[]`: `rack_id`, `rack_profile_id`, `metadata` | Empty |
| `GetAllExpectedRackGroups {}` | `expected_rack_groups[]`: `rack_group_id`, `topology`, `racks[].{rack_id,members[].{type,manufacturer,id}}` | Empty |
| `ListRackProfiles {}` | Built-in rack models, not site data | 14 |

### 3.8 Unavailable

- `GetNetworkTopology {}` returns nothing. Cabling is available only from `status.lldp_neighbors` of machines.
- `GetMachinePositionInfo` returns machine IDs without a position.

## 4. Operations Core offers that are not integrated

None of these has been called; the list is for planning only: power control and reset of machines and components, power shelf power, machine maintenance marks, rack maintenance, host quarantine, component firmware updates and update windows, SKU creation, assignment and verification, on-demand machine validation, manual health report insertion and removal, rack and rack group declaration, switch and power shelf decommissioning, NVLink domains and partitions.

## 5. Field survey

How to collect and check each page at a site, and what data the user has to provide, is in the [field survey guide](../field-survey/README.md), one document per page. This document records only fields and verification results; come back here to update them after a survey.
