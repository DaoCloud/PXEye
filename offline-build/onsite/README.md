# One-command fireseed installation

**English** · [简体中文](README.zh-CN.md)

## Goal

Import one PXEye/NICo offline delivery and deploy its control plane with one command. The runner accepts only the
absolute path to `bundle.tar.gz`; it does not ask for a checksum, extraction directory, work directory, namespace,
release name, certificate mode, DNS/PXE/NTP addresses, or a HostInband network.

The first install is fixed to:

- namespace: `nico-system`
- NICo parent-Chart release: `nico`
- PXEye Service: `NodePort` `31808` (Kubernetes also allocates its ClusterIP)

The runner prefers the current `kind-*` context (otherwise it accepts exactly one candidate), discovers the Registry, skips TLS certificate-chain/name validation for
the site Registry by default, and reuses a healthy shared cert-manager. It installs the bundled cert-manager
only when no cert-manager exists. A partial or unhealthy cert-manager stops the run; it is never adopted or replaced.
After the Core phase, it uses the same-namespace client Secrets and the in-cluster Core address to verify mTLS and
connect PXEye to the new Core.

## Prerequisites

The fireseed host needs Python 3.11+, PyYAML and `kubectl`; cluster nodes must already be able to pull from the site
Registry. Put these delivery files in one directory:

```text
bundle.tar.gz          # large offline delivery
onsite-tools.tar.gz    # small bootstrap runner for the delivery tools
```

`nico-system` must be empty, except for Kubernetes' own default objects or resources managed by the `nico` / PXEye
releases created by this same run. The installer rejects residual PVCs, Secrets, Services and other namespaced
resources instead of adopting legacy four-release NICo deployments, existing PXEye, or existing data.

## Run

Run the following on the fireseed host. The first command extracts only the small runner, not the large bundle.

```bash
cd /srv/nico
tar -xzf onsite-tools.tar.gz
python3 /srv/nico/onsite-tools/tools/onsite/run.py \
  --archive /srv/nico/bundle.tar.gz
```

`--archive` is the only required input. If Registry discovery cannot find one unique endpoint from workload-image or
`local-registry-hosting` evidence, the runner stops during stage 2. Only in that exception, set
`NICO_REGISTRY_URL=http(s)://registry-host:port` before rerunning. The variable selects only the Registry endpoint;
the default policy still skips its TLS certificate-chain/name validation and must not be treated as Registry identity
verification.

## Confirm

Success ends with `PXEYE_CORE_CONNECTED` and `ONSITE_COMPLETE`. The latter means Helm is ready and PXEye has completed
an in-cluster mTLS connection to Core. Directories are derived from the archive name; for
`/srv/nico/bundle.tar.gz`, the runner creates:

```text
/srv/nico/bundle/             # extracted delivery; internal inventory verified
/srv/nico/bundle.onsite/      # progress, logs, frozen Helm recipe, private state
```

The runner also writes a read-only `environment.sh` in that run directory for inspection and troubleshooting. It is
not an installer input; it prevents confirmation commands from accidentally using the current shell's business-cluster
context.

```bash
source /srv/nico/bundle.onsite/environment.sh
kubectl --context "$CONTEXT" -n "$NICO_NAMESPACE" get pods
kubectl --context "$CONTEXT" -n "$NICO_NAMESPACE" get service "$PXEYE_RELEASE"
cat "$(dirname "$WORK")/progress.json"
```

An unclaimed Kubernetes NodePort does not prove that the fireseed host or an external network can reach it. A Kind
cluster still needs the required port mapping at creation time, or an existing controlled access route / `kubectl
port-forward`.

## Resume

After fixing an external cause, rerun the identical command:

```bash
python3 /srv/nico/onsite-tools/tools/onsite/run.py \
  --archive /srv/nico/bundle.tar.gz
```

Completed stages are rechecked and reused. The runner neither reimports verified Charts nor automatically unlocks a
pending Helm operation. Inspect:

```bash
tail -n 80 /srv/nico/bundle.onsite/run.log
cat /srv/nico/bundle.onsite/progress.json
```

## Initial networking boundary

This step installs only the control plane. It does not turn a Kubernetes `ClusterIP` into a physical address, create a
sample HostInband subnet, or configure DNS/PXE/NTP VIPs, DHCP Relay, LoadBalancers, switch relay, routing, ACLs, or
firewall rules. The initial Chart creates neither external boot-service endpoints nor a HostInband plan; this is not
physical-provisioning acceptance and is not a substitute for network-isolation controls.

The bundled `nico-dhcp` Deployment intentionally starts at zero replicas. Its upstream DHCP option placeholders are
not valid physical endpoints, so no Kea process is started until later site-network configuration supplies real
DNS/NTP/PXE/VIP values and explicitly enables DHCP.

Physical boot endpoints and HostInband planning belong to the subsequent PXEye site configuration: DNS/NTP servers,
PXE/DHCP-Relay external endpoints, provisioning-VLAN prefix/gateway/MTU, external Services/VIPs, and switch relay,
routing, ACL and firewall rules. Configure and validate those from the provisioning VLAN before enabling real
provisioning. Helm readiness is not physical-installation acceptance.
