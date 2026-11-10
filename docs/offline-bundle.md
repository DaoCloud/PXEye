# Build a complete offline Core bundle

**English** · [简体中文](offline-bundle.zh-CN.md) · [Documentation](README.md)

Use `tools/build-nico-offline-bundle.py` on a Linux amd64 packaging machine. It
assembles previously built images and materials; it does not compile NICo, build
PXEye images, deploy Kubernetes resources or read a running site's credentials.
Python 3.11+ with PyYAML, GNU patch, Helm 3 and sufficient disk space are required.
Use Python 3.12+ in the PXEye image for the bundled importer's safe extraction.

## Inputs and command

Prepare the pinned e703126e4 original field bundle, two single-image OCI archives
(UI >=0.22.16 and the known CLI-capable Vault bootstrap image), and a site build
configuration based on [build.example.json](../deploy/offline-core/build.example.json).
The config's archive paths are relative to that config file. The example is not
an operational site: replace its registry, context, service addresses and source
image names with your planned values. No password, private key or Secret is input.

From a clean committed PXEye source checkout on the packaging machine:

```bash
python3 tools/build-nico-offline-bundle.py \
  --source-bundle /srv/nico-input/base-bundle \
  --config /srv/nico-input/site-build.json \
  --version 20261110T180000Z \
  --source-revision "$(git rev-parse HEAD)" \
  --output /srv/nico-output/20261110T180000Z
```

For an exported source tree, pass the full revision of the Git archive instead.
The output directory must be new and outside the input. Repeated builds use new
versions/output directories. A per-output lock prevents concurrent builds, old
outputs are never overwritten, and failures retain a `.building-*` directory.

Outputs: `bundle/`, `bundle.tar.gz`, `SHA256SUMS`, `build-result.json`. Deliver all
four. After copying, run:

```bash
cd /srv/nico-output/20261110T180000Z
sha256sum -c SHA256SUMS
python3 bundle/tools/verify-bundle.py bundle
```

The generated `bundle/docs/INSTALL.md` has concrete site values and ordered
execution/confirmation commands. It includes both PXEye images, runtime ConfigMap
input, namespaced and cluster RBAC, a full Deployment with the first Pod's mount,
normal-login API tools, image importers and acceptance checks. Authentication is
created interactively outside the bundle. This profile targets a Podman Kind node
with an existing `/home/kind` bind mount and a pre-existing, unauthenticated HTTPS
Registry Service; it does not create that base infrastructure or configure Harbor
authentication.

## Integrated fixes and gates

- Exact raw Chart and base OCI hashes; complete OCI blob/amd64 graph verification.
- Both extra PXEye image archives, source references and expected manifest digests.
- Original boot/DPU/HTTP/source materials copied only through their verified inventory.
- cert-manager leader election and all startup-check Job/SA/RBAC hook dependencies.
- PostgreSQL TLS, Vault bootstrap/maintenance SA roles and prefixed generated Secrets.
- Short certificate CNs, canonical service SPIFFE names, admin intermediate public CA
  trust and full API FQDN; no bypass/permissive authorization.
- Migration deadline/labels, current Kea hook path and hardware-health API variable.
- Explicit DNS/PXE/NTP Service IPs pinned to the same inputs as Kea DHCP parameters.
- Helm rendering of all four phases: 13 single-replica workloads, no cross-namespace
  drift, no unresolved tokens, and every rendered image present in a lock.
- Fresh recipe/file-inventory/descriptor checksums, source provenance and an outer
  tarball checksum. No hard links back to input, live database, kubeconfig or private
  site state is copied. The inventory intentionally excludes only its own file.

The builder deliberately rejects other upstream Chart revisions rather than
applying patches blindly. Review and add a new compatibility profile for another
NICo version. The original bundle may carry ARM/DPU materials, but this recipe
still provisions only the x86 Core boot-image path. It does not certify ARM OS
installation, full DPU management, external DHCP/PXE reachability or production HA.
A package rendering successfully is not evidence of a fresh cluster installation.
