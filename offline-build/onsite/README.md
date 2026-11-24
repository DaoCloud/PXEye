# One-command fireseed installation

**English** · [简体中文](README.zh-CN.md)

## Goal

Import an existing offline delivery into the site Registry and deploy the PXEye/NICo control plane through one
Shell entry point. The field host needs no Python, PyYAML, pip or container runtime. Build steps one and two,
Charts and the large delivery format remain unchanged.

Installation uses namespace `nico-system`, NICo parent-Chart release `nico`, and PXEye NodePort `31808`.
`--archive` is the only required parameter. Optional `--mode kind|k8s` defaults to `kind`; there is no installer
configuration file to fill in.

Append `--node <Kubernetes-node-name>` to install only on a selected node. The frozen recipe covers PXEye,
Core, platform workloads, install-hook Jobs and maintenance CronJobs. Without it, Kubernetes selects nodes
normally. The selected node needs Registry access and usable storage; an existing shared cert-manager is reused.

## Prerequisites

Use a Linux amd64 host with Bash 4+, kubectl, curl and standard GNU utilities: tar, gzip, find, sort, stat,
sha256sum, timeout, flock and sync. The helper kit includes pinned jq, Mike Farah yq and Caddy binaries.
It downloads no field dependencies and does not change the system Python.

The existing cluster needs a reachable API server, installation permissions, schedulable amd64 nodes, a usable
default StorageClass and sufficient capacity. Nodes must already pull from the site Registry, which must accept
images and Helm OCI Chart push/pull. The default StorageClass must actually provision and mount volumes;
its annotation alone does not establish storage health. NodePort `31808` must be available.

`nico-system` must be empty except for Kubernetes defaults or resources created by this same run. A healthy shared
cert-manager is reused; otherwise the bundled version is installed when none exists. Partial or unhealthy
cert-manager from another installation stops the run. A failed phase created by this run can be retried only
after its frozen intent and ownership match. Other installations, Releases, PVCs and data are never adopted.

## Run

Run on the fireseed host, with these files in `/srv/nico`:

```text
/srv/nico/
  bundle.tar.gz           # existing large image/Chart delivery
  onsite-tools.tar.gz     # Shell runner and pinned tools
```

Extract the small kit, then install into ordinary Kubernetes:

```bash
cd /srv/nico
tar -xzf onsite-tools.tar.gz
kubectl config current-context
bash /srv/nico/onsite-tools/install.sh \
  --archive /srv/nico/bundle.tar.gz --mode k8s
# Restrict this installation to one node
bash /srv/nico/onsite-tools/install.sh \
  --archive /srv/nico/bundle.tar.gz --mode k8s --node <Kubernetes-node-name>
```

`k8s` uses the kubeconfig's current context. Select the intended target with `kubectl config use-context` first.
For Kind, pass `--mode kind` or omit it: the current `kind-*` context wins, otherwise exactly one Kind candidate
is required.

Registry discovery reads workload image references and `local-registry-hosting`. When both loopback and non-loopback
endpoints are reachable, the runner ignores the host-only loopback candidate. If discovery remains ambiguous, set
`NICO_REGISTRY_URL` to the site's complete `http://host:port` or `https://host:port` endpoint before retrying.
The runner skips Registry server certificate-chain/name validation by default; node-side HTTP/certificate trust
must already be configured.

## Stages and paths

| Stage | Purpose |
| --- | --- |
| 01-unpack | Check archive members, extract and verify the embedded inventory |
| 02-site | Save mode, context, Registry and fixed installation identity |
| 03-preflight | Recheck bundle, cluster, tools, cert-manager and resource ownership |
| 04-import | Import images with relok8s, publish and read back Helm OCI Charts |
| 05-recipe | Freeze values, image references and the installation plan |
| 06-pxeye | Install or verify PXEye with Helm |
| 07-install-* | Install cert-manager, platform, Vault and Core in order |
| 08-pxeye-core | Verify PXEye's in-cluster mTLS connection to Core |

Directories derive from the archive filename:

```text
/srv/nico/bundle.extracted/         # extracted content; original delivery stays unchanged
/srv/nico/bundle.onsite/
  progress.json                    # stages and execution identity
  events.jsonl                     # stage history
  run.log                          # console log without passwords
  install-config.json              # generated runtime state, not user configuration
  environment.sh                   # inspection environment
  deployment/                      # OCI catalog, frozen recipe, private logs and install state
```

Caddy provides a process-owned loopback transport adapter for relok8s and exits with the runner. It does not
create or retain a Registry service. Python files already inside an older delivery remain intact but are never
called by the Shell installer. Recipe Charts may normalize invalid cert-manager dependency aliases; the recipe
records the source OCI digest, derived Chart hash and alias mapping. Source Charts and the delivery stay unchanged.
With a selected node, derived Charts add missing subchart placement settings. Every rendered Pod template,
including install hooks, is checked before installation; unsupported layouts stop the run. Placement uses
the scheduler and `nodeSelector`; the runner does not reconfigure other nodes.

## Verify

`PXEYE_CORE_CONNECTED` and `ONSITE_COMPLETE` mean Helm readiness and the PXEye/Core connection passed:

```bash
source /srv/nico/bundle.onsite/environment.sh
kubectl --context "$CONTEXT" -n "$NICO_NAMESPACE" get pods,pvc
kubectl --context "$CONTEXT" -n "$NICO_NAMESPACE" get service "$PXEYE_RELEASE"
cat /srv/nico/bundle.onsite/progress.json
```

## Access PXEye

The runner prints the target-specific access and password retrieval commands. Run on the fireseed host and keep
the terminal open:

```bash
source /srv/nico/bundle.onsite/environment.sh
kubectl --context "$CONTEXT" -n "$NICO_NAMESPACE" \
  port-forward --address 0.0.0.0 "service/$PXEYE_RELEASE" 31808:80
```

After `Forwarding` appears, use the fireseed host's reachable address on port `31808`. Retrieve the generated
bootstrap password in your own terminal:

```bash
kubectl --context "$CONTEXT" -n "$NICO_NAMESPACE" \
  get secret "$PXEYE_RELEASE" -o jsonpath='{.data.bootstrap-password}' | base64 -d; echo
```

The runner prints only that command and does not retrieve the password into its console log. Kind NodePort host
mappings depend on cluster creation; port-forward works in both modes.

## Resume after failure

Fix the cause, then rerun the identical command:

```bash
bash /srv/nico/onsite-tools/install.sh \
  --archive /srv/nico/bundle.tar.gz --mode k8s
```

Completed stages are checked and reused. A changed mode, context, selected node, archive or state format stops the run; restore
the original target to continue. Updating the Shell tools records the source fingerprint and rechecks the frozen
configuration, recipe and Helm intent, so tool fixes can resume. Pending Helm operations are never unlocked automatically. Existing Python
runner progress is not adopted. Start Shell with an archive name that has no installation in progress; do not edit
or delete old state to bypass identity checks.

After confirming no Helm installation process remains, an operator may inspect the release history and use
standard `helm rollback` to restore this installation's most recent completed predecessor, then rerun the original
command. The runner verifies that phase's frozen Chart, values, recorded intent, ownership, PVCs and health before
retrying the unfinished phase; unknown deployment states still stop the run. It never rolls back automatically or
edits Helm Secrets. Rollback may temporarily remove later-phase resources. A Core retry upgrades the cumulative
parent Chart, reconciles platform resources and runs the Vault upgrade hook; existing PVC identities and bindings
remain checked.

```bash
tail -n 80 /srv/nico/bundle.onsite/run.log
cat /srv/nico/bundle.onsite/progress.json
```

This installs the control plane and creates PXE 80/8080, Core 443, Unbound TCP/UDP 53 and, for `--new-site`, PXEye
LoadBalancer Services. DHCP initially has zero replicas. The subsequent site-network action reads their VIPs, writes
the `.forge` records and Nico DHCP option 6, and derives the installer callback. External DHCP must advertise the
displayed DNS VIP itself. Helm readiness does not by itself mean physical provisioning is ready.
