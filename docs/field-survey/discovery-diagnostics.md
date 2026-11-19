# Field survey: discovery diagnostics

**English** · [简体中文](discovery-diagnostics.zh-CN.md) · [Field survey guide](README.md)

Page: Device management → Discovery diagnostics. It lists the result of NICo site exploration for each BMC address (type, vendor, ingestion stage, error code and mitigation, whether it forms a managed host) and the time and counts of the last exploration run, and shows why a device has not entered NICo. The page reads the console endpoint `/api/exploration`. For preparation (environment variables, `--save`, survey directory), see the [field survey guide](README.md).

## 1. Data sources

| Page item | gRPC call in page code (request) | Equivalent nico CLI | Parity | Captured automatically |
| --- | --- | --- | --- | --- |
| Type, vendor and ingestion stage per BMC address | `GetSiteExplorationReport` `{}` (`endpoints[].report.endpointType`, `vendor`, `endpoints[].preingestionState`) | `--json site-explorer get-report all`; table: `site-explorer get-report endpoint` | Same | Yes |
| Error code, error text, mitigation | Same (`endpoints[].report.lastExplorationErrorSchema`, `lastExplorationError`) | `--json site-explorer get-report all`; table: `site-explorer get-report endpoint --erroronly` | Same | Yes |
| Serial number and model of successful endpoints | Same (`endpoints[].report.systems[]`) | `--json site-explorer get-report all`; one address: `site-explorer get-report endpoint <BMC address>` | Same | Yes |
| Addresses that form managed hosts | Same (`managedHosts[].hostBmcIp`) | `--json site-explorer get-report all`; table: `site-explorer get-report managed-host` | Same | Yes |
| Time and counts of the last run | Same (`lastRun`) | `--json site-explorer get-report all` | Same | Yes |
| Expected BMC addresses | — | — | None | No: NICo only knows addresses it has explored; the user provides them |
| Whether the network reaches the BMC | — | — | None | No, check on the BMC network |
| Whether BMC credentials are correct | — | — | None | Cannot be read; the user confirms |

Page code does not use the CLI; checks rely on the gRPC call or the capture file (see the [field survey guide](README.md#13-how-cli-commands-relate-to-interfaces)). For field mapping, see section 3.3 of the [data contract](../design/rack-operations-data-contract.md).

## 2. Survey commands

Run each line from the repository root, in a shell where the `SURVEY_*` variables are exported as in section 1.2 of the guide.

(1) Counts and IDs. This page does not request by ID; machine IDs are used only to check that addresses of managed devices are linked to the device:

```bash
tools/site-survey.sh --save discovery-machine-ids.txt survey ids machines
tools/site-survey.sh --save discovery-machine-states.txt cli machine states --hosts
```

This page uses one `<machine ID>`: in `discovery-managed-hosts.txt` (section 2 (2)), the Machine Id column of a row and the Host BMC Ip column of the same row (the managed `<BMC address>` below) belong to the same machine.

(2) Exploration report. The request the page code sends:

```bash
tools/site-survey.sh --save discovery-report-structure.txt survey call 'GetSiteExplorationReport={}'
```

`survey call` output shows structure only. For full data use the CLI, which calls the same RPC:

```bash
tools/site-survey.sh --save discovery-report.json cli --json site-explorer get-report all
tools/site-survey.sh --save discovery-endpoints.txt cli site-explorer get-report endpoint
tools/site-survey.sh --save discovery-endpoints-failed.txt cli site-explorer get-report endpoint --erroronly
tools/site-survey.sh --save discovery-managed-hosts.txt cli site-explorer get-report managed-host
```

Per address: take `<BMC address>` as the first address in `discovery-endpoints-failed.txt`, then one managed address from `discovery-managed-hosts.txt`:

```bash
tools/site-survey.sh --save discovery-endpoint-failed.txt cli site-explorer get-report endpoint <BMC address>
tools/site-survey.sh --save discovery-endpoint-managed.txt cli site-explorer get-report endpoint <BMC address>
```

`<machine ID>` for the link check: take the Machine Id on the same row of `discovery-managed-hosts.txt` as the managed `<BMC address>`. Confirm the BMC address this machine records with the JSON output:

```bash
tools/site-survey.sh --save discovery-machine-show.json cli --json machine show <machine ID>
```

`jq -r '.bmc_info.ip' $SURVEY_DIR/cli/discovery-machine-show.json` must equal `<BMC address>`. Skip this step when there are no managed hosts, and note why.

`discovery-report.json` contains full Redfish reports of successful endpoints. It can be large and holds serial numbers and addresses; keep it only in the survey directory.

(3) The raw capture (`tools/site-survey.sh capture`) is done once per site and covers all pages, see section 2 of the [field survey guide](README.md); do not repeat it for this page.

## 3. Checks

`C` is the capture file: `C=$SURVEY_DIR/capture-<date-time>.json`. CLI output is in `$SURVEY_DIR/cli/`.

| Item | Pass criterion | Compare with | Record on failure |
| --- | --- | --- | --- |
| Address count | Page rows equal the endpoints in the report | `jq '.pxeye_responses["/api/exploration"].body.endpoints \| length' $C` against `jq '.endpoints \| length' cli/discovery-report.json` (do not count lines of `cli/discovery-endpoints.txt`; it includes header and border lines) | Extra or missing addresses |
| Results | Error code, text and mitigation of failed addresses match the report | `jq '.pxeye_responses["/api/exploration"].body.endpoints \| map(select(.failed)) \| map({address, error})' $C` against `cli/discovery-endpoints-failed.txt` | Mismatched addresses and fields |
| Links | Addresses that form managed hosts are marked managed | `jq '[.pxeye_responses["/api/exploration"].body.endpoints[] \| select(.managed_host) \| .address]' $C` against `cli/discovery-managed-hosts.txt` and the BMC address in `cli/discovery-machine-show.json` (`.bmc_info.ip`) | Unlinked addresses, and the BMC address recorded for that device in device management |
| Successful endpoints | Serial number and model match the report | `jq '.pxeye_responses["/api/exploration"].body.endpoints \| map(select(.address=="<BMC address>")) \| map({address, serial, model})' $C` (`<BMC address>` is the managed address chosen in section 2) against `cli/discovery-endpoint-managed.txt` | The actual serial and model fields in the report |
| Last run | Time and counts match the report | `jq '.pxeye_responses["/api/exploration"].body.last_run' $C` against `jq '.last_run' cli/discovery-report.json` | Reason when the run failed (`error`, `failure_category`) |

## 4. Data the user provides

| Data | Why it is needed | How the user gets it | Saved as |
| --- | --- | --- | --- |
| List of expected BMC addresses | The page shows only addresses NICo explored; devices that never appeared are invisible | Device plan, delivery list or DHCP lease records. The "Device plan" tab in device management can export it | `supplements/discovery-expected-bmcs.csv`: `serial,bmc_mac,bmc_ip` |
| Network reachability | For "connection refused" or timeouts, separate an unreachable network from a BMC service that is off | Run the check below on a machine on the BMC network | `supplements/discovery-reachability.txt` |
| Whether BMC credentials are configured | Authentication errors need the credentials confirmed | Ask the user; never write the credentials into any file | In `session.md` (only "confirmed" or "not confirmed") |

### Reachability check

The user runs this on a machine that can reach the BMC network. Read-only, no login:

```bash
ping -c 3 <BMC address>
curl -sk -o /dev/null -w '%{http_code}\n' --max-time 10 https://<BMC address>/redfish/v1
```

`curl` returning `200` or `401` means the Redfish service runs; connection refused or a timeout means the network is unreachable or Redfish is off on the BMC.

## 5. Common cases

| Observation | Meaning |
| --- | --- |
| The page shows “site exploration last run failed” at the top, category `missing_credentials`, and no endpoints | Site Explorer has no BMC credentials, so no exploration ran at all; it is not a problem with one address. Ask the user to initialize the site credentials in site settings on a writable console; the read-only observer cannot do it |
| Error code `NICO-SITEEXPLORER-101`, connection refused | The address is reachable, but Redfish is off on the BMC, or the address is not a BMC (for example a switch or PDU got an address in the same subnet) |
| Type shown as `Unknown` | Exploration did not succeed, so NICo cannot tell the device type |
| A device is in the expected list but its address is not on the page | The BMC did not get an address, or it is outside the subnets NICo explores |
| Ingestion stage stays at `Initial` | Exploration has not succeeded yet |
| Endpoint count is 0 | NICo has not explored any address: check the discovery subnets in site settings, and whether BMCs got addresses from NICo DHCP |

## 6. AI checklist

1. Run `tools/site-survey.sh check` and note `build_version` and `git_sha`. On failure, retry once per rule 4 in section 5 of the guide; if it still fails, stop and report the error to the user.
2. Run the two commands of section 2 (1). Continue when they succeed.
3. Run `survey call 'GetSiteExplorationReport={}'`. If the call fails, retry once; if it still fails, record the error code and message, stop, and ask the user whether site exploration is enabled on this Core.
4. Run `cli --json site-explorer get-report all` and get the endpoint count with `jq '.endpoints | length' $SURVEY_DIR/cli/discovery-report.json`.
5. Endpoint count is 0: the page has no content at this site, meaning NICo has not explored any address. Ask the user: "Are discovery subnets configured in site settings? Should BMCs get addresses from NICo DHCP?" and ask the user to fill `supplements/discovery-expected-bmcs.csv` per section 4. Then confirm that the page's endpoint count in the capture is also 0: if `tools/site-survey.sh capture` has not been run for the site, run it once (section 2 of the guide), then run `jq '.pxeye_responses["/api/exploration"].body.endpoints | length' $C`; if it is not 0, record both counts and tell the user. Record the answers, stop this page and go to step 12.
6. Endpoint count above 0: run the other three table commands of section 2 (2).
7. Pick `<BMC address>` as section 2 describes and run the two per-address commands; then take `<machine ID>` from the same row of `discovery-managed-hosts.txt`, run `--json machine show`, and confirm `.bmc_info.ip` equals that `<BMC address>`. When there is no failed address or no managed host, skip the corresponding commands and note why.
8. Confirm that `tools/site-survey.sh capture` has been run once for the site; if not, run it once (section 2 of the guide). On exit code 2, fix the cause and run it again.
9. Check each item in section 3 and record pass or the difference.
10. Ask the user for the list of expected BMC addresses, explain why, and save it as `supplements/discovery-expected-bmcs.csv` (`serial,bmc_mac,bmc_ip`); have the user confirm it. List for the user the addresses in the list that are missing from the report.
11. If any address has connection refused or a timeout, ask the user to run the reachability check of section 4 on the BMC network and save the result as `supplements/discovery-reachability.txt`; for authentication errors, ask whether credentials are configured and record only "confirmed" or "not confirmed". Do not guess what the user cannot provide.
12. Write the conclusion for this page into `session.md`: Core version, endpoint count (failed, managed hosts), time and result of the last run, the result of each check in section 3 (if the endpoint count is 0, write "section 3 checks skipped because the endpoint count is 0"), missing user data and its effect, and needed updates to documents and tests.
