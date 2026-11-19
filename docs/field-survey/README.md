# Field survey guide

**English** · [简体中文](README.zh-CN.md) · [Documentation](../README.md)

At a site, use this directory to collect real data for each rack operations page: which NICo CLI commands and interfaces to use, what to check, where to keep the results, and which data NICo lacks and must come from the user. Each page has one document; this file holds the shared preparation and rules.

For the full field mapping see the [data contract](../design/rack-operations-data-contract.md); for the purpose and scope of the pages see [scope and status](../design/rack-operations.md).

| Page | Document | NICo provides | User provides |
| --- | --- | --- | --- |
| Device management → Servers (including the state timeline, health history, hardware validation and firmware inventory of the status dialog) | [Servers](servers.md) | State, health, hardware capabilities, LLDP, state and health history, validation records, firmware versions | Rack assignment, host firmware baseline, whether validation is enabled |
| Device management → Switches | [Switches](switches.md) | State, health and management port of NVLink switches | Whether the site has NVLink switches, the expected list |
| Device management → Power shelves | [Power shelves](power-shelves.md) | State, health, capacity and voltage of power shelves | Whether the site has power shelves, the expected list |
| Device management → Alerts | [Alerts](alerts.md) | Current health alerts of servers, switches and power shelves | Nothing required; optionally the alerts the site treats as known |
| Device management → Cabling | [Cabling](cabling.md) | LLDP links from server interfaces to switch ports | Switch names and models, mapping of port MACs to panel port names, expected cabling |
| Device management → Discovery diagnostics | [Discovery diagnostics](discovery-diagnostics.md) | Probe result, error code and mitigation for each BMC address | Expected list of BMC addresses, network reachability |

## 1. Preparation

### 1.1 Where to run

- Run a read-only observer instance at the site: the same PXEye image with `readOnly` and `rackOperations` enabled, connected to the site's Core. It rejects every write and takes no part in installation.
- Run every command in this instance's container, **never in the console that is installing**.
- The scripts are passed from this repository into the container on standard input; the image does not need `tools/`.

### 1.2 Entry script

Every survey step goes through one script, `tools/site-survey.sh`. Each call stands on its own and needs no function or variable defined earlier, so an AI can run the commands one by one. Run it from the repository root.

Set the environment first (in every new shell, or in front of the command):

| Variable | Meaning | Required |
| --- | --- | --- |
| `SURVEY_NAMESPACE` | Namespace of the read-only observer instance | Yes |
| `SURVEY_DEPLOYMENT` | Deployment name of the observer | Yes |
| `SURVEY_CONTEXT` | kubectl context | No |
| `SURVEY_SSH` | When kubectl does not work on this machine, a command that reaches one where it does, such as `ssh -p 2022 root@<node address>` | No |
| `SURVEY_DIR` | Survey directory, outside this repository | To save output |

```bash
export SURVEY_NAMESPACE=<namespace> SURVEY_DEPLOYMENT=<pxeye> SURVEY_DIR=<survey directory>
tools/site-survey.sh check
```

`check` prints the versions of Core (`carbide-api`) and of the CLI (`nico-admin-cli`), and the number of machines, switches and power shelves. Note `build_version` and `git_sha` of both; every page conclusion afterwards states the Core version it applies to. The two can differ: the CLI ships with the PXEye image, Core with the site deployment.

The script has four uses:

| Use | Purpose | Underneath |
| --- | --- | --- |
| `tools/site-survey.sh cli <command>` | Runs a read-only NICo CLI command, `nico-admin-cli`; put `--json` before the command for JSON | `tools/core-cli.py`, which runs `/usr/local/bin/nico-admin-cli` in the container with the Core address and identity |
| `tools/site-survey.sh survey call '<interface>=<request>'` | Calls a Core gRPC read interface with the same request the page code sends | `tools/core-survey.py`, which runs `grpcurl` in the container |
| `tools/site-survey.sh survey ids machines` | Lists full machine IDs, one per line; also `switches`, `power-shelves`, `racks` | Same |
| `tools/site-survey.sh capture` | Saves every Core response the pages use, verbatim, in the survey directory | `tools/core-capture.py` |

Put `--save <file name>` before the first argument to also keep the output under `$SURVEY_DIR/cli/` or `$SURVEY_DIR/survey/`. A failed command leaves no file and exits non-zero.

All three tools only read:

- `cli` accepts only commands on its allow list; `tools/site-survey.sh cli list` shows them. Commands such as `machine force-delete` and `site-explorer explore` are refused.
- `survey call` accepts only interfaces named `Find`, `Get`, `List` or `Determine`, and refuses those that return credentials.
- `survey call` shows structure only: long values shortened, lists reduced to their first item. Use `cli --json` or `capture` for full data.

### 1.3 How CLI commands relate to interfaces

The page code calls gRPC interfaces only and does not use the CLI. `nico-admin-cli` is another client of the same Core API, and its output is reworked: tables cut long values, and JSON uses snake_case field names. Each page document therefore lists the two apart:

| Equivalence | Meaning | When checking |
| --- | --- | --- |
| Same | The CLI calls the same interface as the page code | The CLI output can be used to check the page |
| Close | The CLI gets similar data through another interface | Cross-reference only; when they differ, `survey call` or the capture decides |
| None | No CLI command | Use `survey call` or the capture |

The correspondence was checked against the CLI source of the site's Core version (`7c7788a8c7f1`). With another Core version, confirm it again with `cli <command> --help` and `survey describe <interface>`.

### 1.4 Survey directory

Create one directory per survey, **outside this repository**, in a place only project members can read, for example `operations/runs/<run id>/`:

```text
<survey directory>/
  session.md                 process and conclusions
  capture-<site>.json         verbatim core-capture output (mode 600)
  cli/<page>-<content>.txt        CLI output
  survey/<page>-<content>.txt     gRPC call output
  supplements/<name>.csv      data provided by the user
```

Save command output with `--save`, for example:

```bash
tools/site-survey.sh --save servers-machine-show.txt cli machine show --hosts
```

Data the user provides is put into `supplements/` by the AI or the user.

Captures and command output hold site addresses, serial numbers and machine IDs. They **must not enter this repository**.

## 2. Common procedure

Every page follows the same four steps; each page document covers only the differences:

1. **Check for data**: run the commands in section 2 of the page document and note the row counts. A count of 0 means the page has no content at that site; go to step 4 and confirm that this matches reality.
2. **Capture verbatim**: run once per site; it covers all pages:

   ```bash
   tools/site-survey.sh capture
   ```

   The file is saved as `$SURVEY_DIR/capture-<date-time>.json` with mode 600. At the end it prints a summary: whether the capture is complete, the failed calls, and the methods that returned nothing. Exit code 0 means complete (it may contain failed calls, which are facts about the site); 2 means it stopped midway, the file name ends in `-incomplete`, and the cause must be fixed before running it again; any other value means it could not run and no file is kept.
3. **Check item by item**: compare the page with the command output by the pass criteria in section 3 of the page document. With a browser, open the page on the observer instance; without one, compare against the console API output in the capture (section 3.1).
4. **Ask the user**: following section 4 of the page document, ask the user for data NICo lacks and save it as CSV in the given format.

## 3. After the site

```bash
PYTHONPATH=src python3 tools/core-replay.py check <survey directory>/capture-<site>.json
PYTHONPATH=src python3 tools/core-replay.py serve <survey directory>/capture-<site>.json --port 18930
```

- `check` recomputes each console API response with the current code and compares it field by field with the captured one. It exits 0 when all match.
- `serve` starts a local console whose Core reads all come from the capture; pages and backend are the real code.
- `UNRECORDED` means the code read data the capture does not hold. Capture the site again; never make up a response.

### 3.1 Checking pages without a browser

The capture's `pxeye_responses` holds the data the page got from the console API at the time. Extract it with `jq` and compare it with the command output:

```bash
C=$SURVEY_DIR/capture-<date-time>.json
jq '.pxeye_responses | keys' $C                                        # console reads in the capture
jq '.pxeye_responses["/api/device-status"].body.servers | length' $C   # servers the page joined
jq '.pxeye_responses["/api/equipment"].body.devices | map(.kind) | group_by(.) | map({(.[0]): length}) | add' $C
jq '.summary' $C                                                       # capture summary
```

Filtering, grouping and conflict detection on the pages happen in the browser and cannot be checked this way; when needed, open the page locally with `serve`.

### 3.2 After changing code

| `check` result | Action |
| --- | --- |
| All OK | None |
| DIFF, expected from this change | Confirm each line, then save a copy with `--write <new file>`; the Core responses in it stay verbatim |
| DIFF, not expected | Regression; fix the code |
| UNRECORDED | Capture the site again |

A capture never stops because one item could not be read. Empty responses, failed calls and partly failed reads are recorded verbatim and appear the same way on replay; see section 6.

## 4. Data the user provides

Data NICo lacks comes from the user and is saved as CSV:

- Files go in `<survey directory>/supplements/`; file names and columns follow section 4 of each page document.
- The first row holds the column names, UTF-8 encoded, one record per row.
- When the user gives a spreadsheet, screenshot or verbal description, turn it into the required CSV and ask the user to confirm it.
- When the user cannot provide something yet, write in `session.md` what is missing and which item of which page it affects. Do not fill in guessed values.

For now these CSV files serve only for checking and later development. PXEye has no place to enter them, except racks (racks are entered in the system configuration of device management, on a writable console).

## 5. Rules for AI

An AI helping with a survey at a site works by these rules:

1. Run commands only through `tools/site-survey.sh`, and only those listed in this directory and in `tools/site-survey.sh cli list`. Do not run writes, and do not run commands in the console that is installing.
2. Add `--save` to every command to keep its output in the survey directory; do not just look at it.
3. The data listed in section 4 of a page document is not in NICo and must be asked from the user. When asking, state what is needed, why, how the user can get it (give the command), and the format to save it in. Do not infer it from other data.
4. When a command fails, retry it once on its own to tell an intermittent failure from a persistent one; for a persistent failure, record the command, error code and message.
5. At the end, write in `session.md`: the Core version, whether each page has data, the check results, the missing user data, and the updates needed to documents and tests.
6. For new findings, update the documents and test samples as in section 7; when the implementation status changes, update the [capability requirements](../design/rack-operations-requirements.md).

## 6. Empty data and failures

A capture never stops because one item could not be read. Each case is recorded as it happened and appears the same way on replay:

| Case | In the capture | On replay |
| --- | --- | --- |
| Core returns nothing (no such device, no record). Core omits empty lists, so the usual answer is `{}` | The empty response verbatim; the method is listed in `summary.empty_calls` | The same empty data |
| A Core call fails (unknown method, invalid argument, timeout, connection failure) | The error's type, message and attributes (such as an error code), listed in `summary.failed_calls` | The same error type is raised, so the console returns the same status and error code as at the site |
| Part of a console read fails (for example switches cannot be read while servers can) | The read returns 200 with the failure in its `errors`, listed in `summary.reads_with_errors` | The same |
| A console read returns an error status | The status and body; a body that is not JSON is kept as text | Compared field by field |
| A console read returns nothing (timeout, connection closed) | `status` is empty and the reason is kept | Not compared; shown as `SKIP` |
| The capture fails midway (for example sign-in fails) | What was read so far is still written; `summary.complete` is false and `aborted` gives the reason | Only what exists is replayed |

At the end the command prints a summary on standard error: complete or aborted, each failed call, each failed or partly failed read, and the methods that returned nothing. Exit code 0 means the capture is complete (it may contain failed calls, which are facts about the site); 2 means it stopped midway.

After reading the summary:

- **Empty responses**: decide whether they match the site. `FindSwitches` returning nothing at a general server site is normal; no servers while device management lists some means checking enrollment in Core.
- **Failed calls**: call the method again on its own with `survey call` to see whether the failure is intermittent or persistent. For a persistent failure, record the method, error code and message in the matching field table of the [data contract](../design/rack-operations-data-contract.md); for a method this Core version lacks, note it in its sections 2 and 3.
- **Aborted**: fix the cause and capture again. An aborted file can be kept for diagnosis but is not used as a test baseline.

## 7. What to bring back

1. The capture, in the restricted directory, noting the kind of site (general server or whole rack) and the Core version.
2. The results of the checks in section 3 of each page document: change “definition only” to “verified” in the [data contract](../design/rack-operations-data-contract.md), or record the difference.
3. Structures seen for the first time (new states, alerts, device kinds) go into `tests/unit/test_device_status.py`, with only the fields needed and placeholder values. Unit tests never read a capture.
4. When the implementation status changes, update the [capability requirements](../design/rack-operations-requirements.md) by its maintenance rules.

## 8. Limits

- A capture is one moment. How states change is seen only through repeated captures or the state history.
- A device kind the site lacks is absent from the capture; switches and power shelves wait for a site that has them.
- Replay has no Kubernetes; the cluster-dependent parts of the site settings page show as unavailable.
- Captures are reads. Writes (power, maintenance, firmware updates) cannot be verified by replay.
