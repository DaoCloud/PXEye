# Step 3: one-command NICo onsite deployment

**English** · [简体中文](README.zh-CN.md)

One configuration and one command perform archive verification/extraction, site resolution, preflight, image and Helm OCI import, frozen recipe generation, optional PXEye bootstrap, cert-manager, platform, Vault, optional materials and Core installation. This tool neither builds images nor changes containerd, discovers devices, writes Redfish or installs host operating systems.

## Prepare one configuration

Goal: on the Linux amd64 fireseed host, provide Python 3.11+/PyYAML, kubectl, `bundle.tar.gz`, `SHA256SUMS`, Registry permissions and node image-pull configuration. The bundle contains Helm/relok8s. Install the helper kit at `/srv/nico/nico-onsite-tools/tools/onsite`; existing archives may use a small kit produced by `export.py` without rebuilding large images.

Command, once after installing the kit:

```bash
cp /srv/nico/nico-onsite-tools/tools/onsite/run-config.example.json /srv/nico/onsite-run.json
```

Confirmation:

```bash
python3 -m json.tool /srv/nico/onsite-run.json
```

Edit only this file:

| Setting | Meaning |
| --- | --- |
| archive / checksums | Absolute delivery paths |
| extract_directory / work_directory | Separate per-installation extraction and progress directories |
| bootstrap_pxeye | false preserves existing PXEye; true installs it with Helm |
| site.context | Explicit context recommended; null selects only a unique Kind context, never the default context |
| site.namespace | Defaults to nico-system |
| site.mode / release_prefix | restore selects the unique original Core release when prefix is null; new defaults to nico |
| site.registry | URL null discovers one Registry V2 from cluster evidence; explicit URL resolves ambiguity. TLS defaults strict; configure a CA or explicitly skip verification. Authentication uses a protected Docker config directory |
| site.service_ips / host_network | Restore reuses existing client service addresses/network; new sites require DNS/PXE/NTP IPv4 and network name/prefix/gateway/mtu |
| site.storage_class | Optional site StorageClass |
| site.publish_materials | Optional material service; consumer URLs still require separate review |
| site.phase_values | Optional per-phase YAML paths; hashes are included in run identity |

The supplied configuration defaults to restore mode and preserves PXEye. Missing site information stops the relevant stage; do not use another site's addresses as generic defaults.

## Run or resume

Goal: complete stages in dependency order. Any working directory is supported.

Command (identical after a failure):

```bash
python3 /srv/nico/nico-onsite-tools/tools/onsite/run.py --config /srv/nico/onsite-run.json
```

Confirmation, with the template work directory:

```bash
cat /srv/nico/onsite/field-install-01/progress.json
```

Output identifies stages, completion, failures and reused work; success prints `ONSITE_COMPLETE`. No manual preflight/import/recipe/install sequence or shell activation is needed.

Completed extraction and Charts are verified before reuse. Frozen recipes are checked. Installed Helm phases are rechecked for deployed state, health and original PVC identity, then skipped. Failed phases retry only when Helm is definitively failed or absent. Pending operations stop for operator investigation; the tool never force-unlocks, rolls back or deletes resources. A successful Helm operation interrupted before journaling is recovered only after matching the saved intent, Chart version, actual values, health and PVCs, avoiding repeated initialization.

Resume is per stage, not at a file byte offset. Fix the actual problem and rerun; there is no infinite in-process retry loop. Changed configuration, checksum list, phase values or implementation requires a new work directory. Do not edit frozen/generated records. Do not install through the UI and CLI concurrently; older UI versions do not share this lock.

## Logs and output

Goal: inspect the failed stage and retained history.

Commands:

```bash
tail -n 60 /srv/nico/onsite/field-install-01/run.log
```

Confirmation:

```bash
cat /srv/nico/onsite/field-install-01/progress.json
ls /srv/nico/onsite/field-install-01/deployment/logs
```

```text
work_directory/
  progress.json                    # atomic status, attempts, duration, error
  events.jsonl                     # append-only stage history
  run.log                          # appended terminal output
  site-config.json                 # generated, frozen; do not edit
  environment.sh                   # optional diagnostic activation
  deployment/
    state.json                     # Chart/Helm checkpoints and intent
    timings.jsonl                  # command durations and exit codes
    catalog.json
    recipe/
    logs/                          # appended attempt output and exit codes
    private/                       # protected snapshots, values and Helm output
```

Files are permission restricted; credentials remain external references. Do not commit onsite state. Existing archives/images/PVCs remain; backend volume backup is optional, not part of this flow. Helm readiness is distinct from strict Core mTLS, material HTTP, physical DHCP/Scout and OS acceptance.

For an example site context, explicit acceptance commands are:

```bash
kubectl --context kind-fireseed -n nico-system get deploy,sts,pods,jobs,pvc
```

Confirmation:

```bash
cat /srv/nico/onsite/field-install-01/deployment/state.json
```

Manual `onsite.py` subcommands remain available for diagnosis. References: [NICo reference installation](https://docs.nvidia.com/infra-controller/documentation/getting-started/installation-options/reference-installation), [Helm OCI](https://helm.sh/docs/v3/topics/registries/). Checkpoint recovery is implemented by this project, not by the upstream NICo installer.
