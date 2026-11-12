# Step 3: import and deploy onsite

**English** · [简体中文](README.zh-CN.md) · [Overview](../README.md)

`run.py` imports offline images and Charts on the fireseed host and deploys PXEye and NICo to the configured Kubernetes cluster. One deployment configuration controls resource management through Helm.

## Deployment stages

| Stage | Action | Key point |
| --- | --- | --- |
| Verify/unpack | Verify archives/inventory and unpack independently | Revalidate completed extraction before reuse |
| Resolve/preflight | Confirm context, Registry, tools and settings | Never use the default cluster; namespace defaults to nico-system |
| Import | Push images with relok8s; publish and read back Helm OCI Charts | Import success does not establish node image pulls |
| Freeze recipe | Generate site values, order and hashes | Do not edit generated files |
| Optional PXEye | Bootstrap the UI through its own Helm Chart | false preserves existing PXEye |
| Install NICo | cert-manager → platform → Vault → optional materials → Core | Each phase must pass; preserve original PVC identities |

## Environment and configuration

Requirements: Python 3.11+/PyYAML, kubectl, an available cluster/Registry and configured node image pulls. Helm/relok8s come with the large bundle.

Copy the three files printed by step 2's `DELIVERY_FILES` to `/srv/nico/`, then run once:

```bash
cd /srv/nico
sha256sum -c SHA256SUMS &&
test ! -e onsite-tools &&
test ! -e onsite-run.json &&
tar -xzf onsite-tools.tar.gz &&
cp onsite-tools/tools/onsite/run-config.example.json onsite-run.json &&
${EDITOR:-vi} onsite-run.json
```

`onsite-run.json` is the deployment configuration entry point:

| Setting | Key rule |
| --- | --- |
| archive / checksums | Absolute large-archive and checksum paths |
| extract_directory / work_directory | Independent per-installation directories, created automatically |
| site.context / namespace | Explicit context recommended; null allows only one Kind context; namespace defaults to nico-system |
| site.mode / release_prefix | restore reuses the unique existing Core or PXEye parent release when prefix is empty; new is for fresh sites |
| site.cert_manager.mode | `install` (default) installs the bundled controller; `reuse` is only for a new, empty namespace with a verified shared cert-manager |
| site.registry | Empty URL discovers one valid endpoint; configure CA/TLS policy and external authentication references |
| site.service_ips / host_network | New sites require DNS/PXE/NTP IPv4 and network name/prefix/gateway/mtu; restore may reuse existing settings |
| bootstrap_pxeye | Optional standalone PXEye UI startup; defaults to false |
| site.storage_class / phase_values | Optional storage and per-phase overrides; credentials remain protected-file references |

The template defaults to **restore mode and preserving existing PXEye**. Fresh sites must change the mode/options/network. Preparation runs once; do not overwrite tools or configuration when resuming.

`bootstrap_pxeye=true` starts only the PXEye UI. NICo components remain
disabled until their ordered installation phases. For a second isolated
deployment in a cluster that already has cert-manager, set
`site.cert_manager.mode` to `reuse`; the installer validates the shared CRDs
and controller, skips the bundled cert-manager phase, and never adopts the
existing release. A new install requires a namespace with no Helm releases.
If the default PXEye NodePort is occupied, set a distinct
`site.pxeye_values.service.nodePort` (or use `ClusterIP`). Restore is supported
only when the existing site already uses the single parent-Chart release; a
legacy four-release NICo installation requires an explicit migration or a
clean namespace and is rejected before Registry import.

## Deployment command

Command, from any working directory; identical after failure:

```bash
python3 /srv/nico/onsite-tools/tools/onsite/run.py --config /srv/nico/onsite-run.json
```

Confirmation: current `STAGE`, `DONE` / `FAILED`, then `ONSITE_COMPLETE`. The runner coordinates import, recipe generation and installation.

## Recovery and logs

Inspect the failure, fix its cause and rerun the original command. Using template paths:

```bash
tail -n 60 /srv/nico/onsite/field-install-01/run.log
cat /srv/nico/onsite/field-install-01/progress.json
```

| Record | Purpose |
| --- | --- |
| work_directory/progress.json | Stage, status, attempts, duration and error |
| events.jsonl / run.log | Appended execution history, including failures |
| deployment/state.json | Chart/Helm checkpoints and installation intent |
| deployment/logs/ and timings.jsonl | Command output and duration |
| deployment/private/ | Protected snapshots, values and installation output |

Completed stages are verified before skipping. Failed/absent Helm releases may retry; pending operations stop for operator investigation, without automatic unlock or rollback. A successful operation interrupted before journaling is recovered only after checking saved intent, version, values, health and PVCs.

Changed inputs/configuration/implementation require a new work directory. Do not edit checkpoints or run UI and CLI installers concurrently. Recovery is per stage, not by byte offset.

`ONSITE_COMPLETE` means import and Helm readiness passed. Strict mTLS, material HTTP, physical DHCP/Scout and OS acceptance remain separate. The runner does not wipe data, recreate Kind, discover devices, write Redfish or install hosts.

References: [NICo reference installation](https://docs.nvidia.com/infra-controller/documentation/getting-started/installation-options/reference-installation), [Helm OCI](https://helm.sh/docs/v3/topics/registries/).
