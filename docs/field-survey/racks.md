# Field survey: racks

**English** · [简体中文](racks.zh-CN.md) · [Field survey guide](README.md)

Page: Device management → Racks. The page shows the rack objects NICo Core keeps for declared whole racks (for example a GB200 NVL72): name, rack profile, state, health, member counts and, per rack, the state and health history. A general server site has no rack object, and the page says so. With `rackActions` on, the page also starts rack maintenance and rack firmware updates; those are never run during a survey. For preparation (environment variables, survey directory, `--save`), see the [Field survey guide](README.md).

## 1. Data sources

| Page item | gRPC call made by the page code (request) | Equivalent nico CLI | Parity | Captured automatically |
| --- | --- | --- | --- | --- |
| Rack IDs | `FindRackIds` `{}` | `rack list` | Same | Yes (the capture records `/api/racks`) |
| Rack name, state, health, group | `FindRacksByIds` `{"rackIds":[{"id":"<rack ID>"}]}` | `rack show <rack ID>`; full record: `--json rack show <rack ID>` | Same | Yes, as above |
| Rack profile | `GetAllExpectedRacks` `{}` | `expected-rack show` | Same | Yes, as above |
| State history | `FindRackStateHistories` `{"rackIds":[{"id":"<rack ID>"}]}` | `rack state-history <rack ID>` | Same | No: the capture reads the rack list, not each rack's history; use section 2 commands |
| Health history | `FindRackHealthHistories` `{"rackIds":[{"id":"<rack ID>"}]}` | `rack health-history <rack ID>` | Same | No, as above |
| Whether RMS answers (shown in the operation dialog) | `GetRmsVersion` `{}` | `backend rms status` (not in the survey whitelist) | Same | No; read only through `survey call` |
| Whether the site is a whole-rack site; whether RMS is deployed | — | — | None | No, the user must confirm |

The page code does not use the CLI; checks rely on the gRPC call, see [Field survey guide section 1.3](README.md#13-how-cli-commands-relate-to-interfaces). Interfaces and fields are in section 4.3 of the [data contract](../design/rack-operations-data-contract.md).

## 2. Commands

Assumes the `SURVEY_*` variables are exported as in [Field survey guide section 1.2](README.md#12-entry-script); run from the repository root.

(1) Count and IDs:

```bash
tools/site-survey.sh --save racks-ids.txt survey ids racks
```

The output has one rack ID per line; the line count is the number of racks. If it is 0, go to section 4.

(2) The gRPC call and equivalent CLI for each item. Take `<rack ID>` from the first line of `racks-ids.txt`; if `rack list` shows a rack that is in maintenance, in an error state or has a health alert, repeat the commands with `<rack ID>` for one such ID.

```bash
# List, state, health
tools/site-survey.sh --save racks-find.txt survey call 'FindRackIds={}'
tools/site-survey.sh --save racks-list.txt cli rack list
tools/site-survey.sh --save racks-show.txt cli rack show <rack ID>
tools/site-survey.sh --save racks-show-json.txt cli --json rack show <rack ID>

# Rack profile
tools/site-survey.sh --save racks-expected-grpc.txt survey call 'GetAllExpectedRacks={}'
tools/site-survey.sh --save racks-expected.txt cli expected-rack show

# State and health history
tools/site-survey.sh --save racks-state-history.txt cli rack state-history <rack ID>
tools/site-survey.sh --save racks-health-history.txt cli rack health-history <rack ID>

# RMS reachability (a read; an error means RMS did not answer)
tools/site-survey.sh --save racks-rms-version.txt survey call 'GetRmsVersion={}'
```

`survey call` output shows structure only (long values shortened, lists keep the first item); for full data use the `cli --json` output.

(3) The capture is done once per site ([Field survey guide section 2](README.md#2-common-procedure)), not per page. It records `/api/racks` (rack list, state, health, member devices and declarations), but not each rack's history:

```bash
tools/site-survey.sh capture
```

## 3. Checks

Saved files are under `$SURVEY_DIR/cli/` and `$SURVEY_DIR/survey/`. Compare with the racks page of the read-only observer.

| Item | Pass criterion | Compare with | Record on failure |
| --- | --- | --- | --- |
| Row count | The page's rack count equals the ID count | The racks page against the line count of `survey/racks-ids.txt` | Both counts, extra or missing IDs |
| State, health | Matches the CLI | The racks page against `cli/racks-show-json.txt` | Actual state text and health value |
| Profile | The profile on the page matches the expected rack | The racks page against `cli/racks-expected.txt` | Rack ID, profile on each side |
| State history | The page's timeline has the same states in the same order | The rack history on the page against `cli/racks-state-history.txt` | States missing or out of order |
| Fields | Whether each field in data contract sections 3.7 and 4.3 has a value | `cli/racks-show-json.txt`, `survey/racks-expected-grpc.txt` | Actual value or "empty" per field |
| RMS | `GetRmsVersion` returns a version, or the error is recorded | `survey/racks-rms-version.txt` | Error code and message |

For the field mapping, see sections 3.7 and 4.3 of the [data contract](../design/rack-operations-data-contract.md). All rack fields are "definition only" or from the demo capture: the sites verified so far have no rack object.

## 4. Data the user provides

| Data | Why | How the user gets it | Saved as |
| --- | --- | --- | --- |
| Whether the site is a whole-rack site | When the commands return nothing, distinguish "general servers" from "racks not declared" | Ask the site owner; compare with `tools/site-survey.sh cli expected-rack show` | Written in `session.md` |
| Whether RMS is deployed | Tray, switch, power shelf, firmware and rack maintenance operations go through RMS when Core's component manager backends are `rms`; without RMS they fail | Ask the NICo operator for the `component_manager` backends in the Core configuration and whether RMS runs; compare with `survey/racks-rms-version.txt` | Written in `session.md`: the three backends, RMS yes/no |
| Rack profile (if whole-rack) | Check the profile NICo holds | The rack shipping list | `supplements/racks-expected.csv`: `rack,profile` |

## 5. Common cases

| Observation | Conclusion |
| --- | --- |
| ID count is 0, the site uses general servers | Normal. This page does not apply at the site |
| ID count is 0, but `expected-rack show` is not empty | Racks are declared but no rack object exists yet; record the expected racks and ask the user |
| `GetRmsVersion` fails while the backends are `rms` | RMS is not deployed or not reachable; RMS-backed operations will fail at this site. Record it |
| The user asks to power a whole rack on or off | NICo does not provide it (see [rules for operations](../design/rack-operations-actions.md)). Record the request |

## 6. AI checklist

1. Run `tools/site-survey.sh --save racks-ids.txt survey ids racks`. On success, count the lines. On failure, retry once as in [Field survey guide section 5](README.md#5-rules-for-ai); if it still fails, record the error and stop this page.
2. Run `tools/site-survey.sh --save racks-rms-version.txt survey call 'GetRmsVersion={}'` and record the version or the error.
3. Line count is 0: run `tools/site-survey.sh --save racks-expected.txt cli expected-rack show`. Two cases, by its output:
   - Empty: stop and ask the user: "Is this a whole-rack site (for example GB200/GB300 NVL72)? Is RMS deployed, and what are the `component_manager` backends in the Core configuration?" Record the answers and end this page; go to step 8.
   - Not empty: record the expected rack IDs and profiles in `session.md`, then stop and ask the user: "These N racks are declared but NICo has no rack object for them; is that expected?" Record the answer and end this page; go to step 8.
4. Line count above 0: run all commands of section 2 (2) in order, with `<rack ID>` from the first line; for a rack in `rack list` in maintenance, in error or with a health alert, run the commands with an ID again for it. Move to the next command only after the previous one succeeds.
5. Check each item of section 3; write pass or fail and the recorded content for each.
6. Ask the user whether RMS is deployed and for the rack profiles; save `supplements/racks-expected.csv` and ask the user to confirm it.
7. Do not run any operation from the racks page or the operation dialog, and do not run `rack maintenance` or any other write command.
8. Write this page into `session.md`: Core version, rack count, whether there is data, RMS answer, the three backends, each check result, failed calls, user data received and missing, data contract fields that need updating.
