# Field survey guide

**English** · [简体中文](README.zh-CN.md) · [Documentation](../README.md)

At a site, use this directory to collect real data for each rack operations page: which NICo CLI commands and interfaces to use, what to check, where to keep the results, and which data NICo lacks and must come from the user. Each page has one document; this file holds the shared preparation and rules.

For the full field mapping see the [data contract](../design/rack-operations-data-contract.md); for the purpose and scope of the pages see [scope and status](../design/rack-operations.md).

| Page | Document | NICo provides | User provides |
| --- | --- | --- | --- |
| Device management → Servers (including the state timeline, health history, hardware validation and firmware inventory of the status dialog) | [Servers](servers.md) | State, health, hardware capabilities, LLDP, state and health history, validation records, firmware versions | Rack assignment, host firmware baseline, whether validation is enabled |
| Device management → Switches | [Switches](switches.md) | State, health and management port of NVLink switches | Whether the site has NVLink switches, the expected list |
| Device management → Power shelves | [Power shelves](power-shelves.md) | State, health, capacity and voltage of power shelves | Whether the site has power shelves, the expected list |
| Device management → Cabling | [Cabling](cabling.md) | LLDP links from server interfaces to switch ports | Switch names and models, mapping of port MACs to panel port names, expected cabling |
| Device management → Discovery diagnostics | [Discovery diagnostics](discovery-diagnostics.md) | Probe result, error code and mitigation for each BMC address | Expected list of BMC addresses, network reachability |

## 1. Preparation

### 1.1 Where to run

- Run a read-only observer instance at the site: the same PXEye image with `readOnly` and `rackOperations` enabled, connected to the site's Core. It rejects every write and takes no part in installation.
- Run every command in this instance's container, **never in the console that is installing**.
- The scripts are passed from this repository into the container on standard input; the image does not need `tools/`.

### 1.2 Three tools

| Tool | Purpose | Output |
| --- | --- | --- |
| `tools/core-cli.py` | Runs read-only `nico-admin-cli` commands | A table, or JSON with `--json` |
| `tools/core-survey.py` | Shows interface definitions through gRPC reflection and calls read interfaces | Structure only: long values shortened, lists reduced to their first item |
| `tools/core-capture.py` | Saves every Core response the pages use, verbatim | One JSON file that can be replayed locally |

All three tools only read. `core-cli.py` accepts only commands on its allow list; `cli list` shows them all. Commands that change the site, such as `machine force-delete` and `site-explorer explore`, are rejected.

Define at the repository root:

```bash
NS=<namespace>; DEPLOY=<pxeye>
cli()     { kubectl -n "$NS" exec -i deploy/"$DEPLOY" -c pxeye -- python3 - "$@" < tools/core-cli.py; }
survey()  { kubectl -n "$NS" exec -i deploy/"$DEPLOY" -c pxeye -- python3 - "$@" < tools/core-survey.py; }
capture() { kubectl -n "$NS" exec -i deploy/"$DEPLOY" -c pxeye -- python3 - < tools/core-capture.py; }
```

First confirm the connection and version:

```bash
cli version
```

Note `build_version` and `git_sha` from the output. Every page conclusion afterwards states the Core version it applies to.

### 1.3 Survey directory

Create one directory per survey, **outside this repository**, in a place only project members can read, for example `operations/runs/<run id>/`:

```text
<survey directory>/
  session.md                 process and conclusions
  capture-<site>.json         verbatim core-capture output (mode 600)
  cli/<page>-<command>.txt        CLI output
  supplements/<name>.csv      data provided by the user
```

Save command output by redirecting it, for example:

```bash
mkdir -p <survey directory>/cli <survey directory>/supplements
cli machine show --hosts > <survey directory>/cli/servers-machine-show.txt
```

Captures and command output hold site addresses, serial numbers and machine IDs. They **must not enter this repository**.

## 2. Common procedure

Every page follows the same four steps; each page document covers only the differences:

1. **Check for data**: run the commands in section 2 of the page document and note the row counts. A count of 0 means the page has no content at that site; go to step 4 and confirm that this matches reality.
2. **Capture verbatim**: run once per site; it covers all pages:

   ```bash
   capture > <survey directory>/capture-<site>.json
   chmod 600 <survey directory>/capture-<site>.json
   ```

   At the end it prints a summary: whether the capture is complete, the failed calls, and the methods that returned nothing. Exit code 0 means complete (it may contain failed calls, which are facts about the site); 2 means it stopped midway, so fix the cause and run it again.
3. **Check item by item**: open the page on the observer instance and compare it with the command output by the pass criteria in section 3 of the page document.
4. **Ask the user**: following section 4 of the page document, ask the user for data NICo lacks and save it as CSV in the given format.

## 3. Back from the site

```bash
PYTHONPATH=src python3 tools/core-replay.py check <survey directory>/capture-<site>.json
PYTHONPATH=src python3 tools/core-replay.py serve <survey directory>/capture-<site>.json --port 18930
```

- `check` recomputes each console API response with the current code and compares it field by field with the captured one. It exits 0 when all match.
- `serve` starts a local console whose Core reads all come from the capture; pages and backend are the real code.
- `UNRECORDED` means the code read data the capture does not hold. Capture the site again; never make up a response.

After changing code:

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

1. Run only the commands listed in this directory and those in `cli list`. Do not run writes, and do not run commands in the console that is installing.
2. Save the output of every command in the survey directory; do not just look at it.
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
