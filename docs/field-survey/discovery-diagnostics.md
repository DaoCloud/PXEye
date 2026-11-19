# Field survey: discovery diagnostics

**English** · [简体中文](discovery-diagnostics.zh-CN.md) · [Field survey guide](README.md)

Page: Device management → Discovery diagnostics. It lists the result of NICo site exploration for each BMC address, and shows why a device has not entered NICo. For preparation and the common procedure, see the [field survey guide](README.md).

## 1. Data sources

| Page content | NICo CLI | gRPC interface | Captured automatically |
| --- | --- | --- | --- |
| Type, vendor, ingestion stage and exploration result of each BMC address | `site-explorer get-report endpoint` | `GetSiteExplorationReport` | Yes |
| Error code, error description, suggested action | `site-explorer get-report endpoint` | Same (`lastExplorationErrorSchema`) | Yes |
| Addresses that already form managed hosts | `site-explorer get-report managed-host` | Same (`managedHosts`) | Yes |
| Time and counts of the last exploration | — | Same (`lastRun`) | Yes |
| Expected BMC addresses | — | — | No: NICo knows only the addresses it has explored |
| Whether the network can reach the BMC | — | — | No; check on the BMC network |
| Whether the BMC credentials are correct | — | — | Cannot be read; the user confirms |

For the field mapping, see section 3.3 of the [data contract](../design/rack-operations-data-contract.md).

## 2. Capture commands

```bash
D=<survey directory>/cli
cli site-explorer get-report endpoint            > $D/discovery-endpoints.txt
cli site-explorer get-report managed-host        > $D/discovery-managed-hosts.txt
cli --json site-explorer get-report all          > $D/discovery-report.json
```

The output of `get-report all` contains the full Redfish report of each successfully explored endpoint. The file can be large and contains serial numbers and addresses. Keep it only in the survey directory.

If there are no endpoints, NICo has not explored any address yet. Check the discovery subnets in the site settings, and whether the BMCs got addresses from NICo DHCP.

## 3. Checks

| Item | Pass criterion | Record on failure |
| --- | --- | --- |
| Address count | Page row count equals the row count of `get-report endpoint` | Extra or missing addresses |
| Result | Error code, description and suggested action of failures match the command output | Addresses that differ |
| Association | Addresses of managed devices are associated with the device | Addresses that cannot be associated, and the BMC address recorded for that device in device management |
| Successful endpoints | Displayed serial number and model match the report | Actual serial number and model fields in the report |
| Last exploration | Time and counts match the report | Reason when exploration failed |

## 4. Data the user provides

| Data | Why it is needed | How the user gets it | Save as |
| --- | --- | --- | --- |
| List of expected BMC addresses | The page shows only addresses NICo has explored; devices that never appeared are not visible | Device plan, delivery list or DHCP lease records. The **Device plans (设备规划)** tab in device management can export it | `supplements/discovery-expected-bmcs.csv`: `serial,bmc_mac,bmc_ip` |
| Network reachability | When the error is "connection refused" or a timeout, tell a network failure from a BMC service that is not running | Run the checks below on a machine on the BMC network | `supplements/discovery-reachability.txt` |
| Whether BMC credentials are configured | Authentication errors need the credentials confirmed | Ask the user; do not write the credentials into any file | In `session.md` (write only "confirmed" or "not confirmed") |

### Reachability check

Run on a machine that can reach the BMC network. Read-only; no login:

```bash
ping -c 3 <BMC address>
curl -sk -o /dev/null -w '%{http_code}\n' --max-time 10 https://<BMC address>/redfish/v1
```

If `curl` returns `200` or `401`, the Redfish service is running. Connection refused or a timeout means the network is down or Redfish is not enabled on the BMC.

## 5. Common cases

| Symptom | Interpretation |
| --- | --- |
| Error code `NICO-SITEEXPLORER-101`, connection refused | The address is reachable, but Redfish is not enabled on the BMC, or the address is not a BMC (for example, a switch or PDU got an address in the same subnet) |
| Type shows `Unknown` | Exploration has not succeeded; NICo cannot tell the device type |
| The device is in the expected list, but its address is not on the page | The BMC got no address, or it is not in a subnet NICo explores |
| Onboarding stage stays at `Initial` | Exploration has never succeeded |
