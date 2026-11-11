# Part 2: initialize a site and deploy NICo from offline materials

**English** · [简体中文](CONFIGURE.zh-CN.md)

> Legacy delivery workflow. Use the current [three-step flow](README.md) and [onsite runner](onsite/README.md).

Part1 builds reusable materials. The deployment site supplies Registry, cluster and network settings. Initialization generates consistent Helm values, certificate identity references, RBAC, PXEye bootstrap resources and an executable deployment guide. It does not access Kubernetes/Registry, install services or modify source materials.

## 1. Select the materials and toolkit

Goal: use a new generic bundle or a supported previous complete Core builder bundle. Run all commands as root in Bash on the target seed machine. This profile requires one existing Podman Kind node, linux/amd64, the `/home/kind` host bind mount and a no-auth Registry. Other runtimes/authenticated registries require separate adaptation.

Run:

```bash
bash
set -euo pipefail
export MATERIALS=/home/kind/nico-bundles/nico-core-materials
export KIT="$MATERIALS/deployment-kit"
test -f "$MATERIALS/manifests/file-inventory.json"
test -f "$KIT/configure.py"
python3 -c 'import sys,yaml; assert sys.version_info >= (3,11); print(yaml.__version__)'
command -v helm
```

Confirm:

```bash
python3 "$KIT/configure.py" --help
python3 -m json.tool "$MATERIALS/bundle.json"
```

`MATERIALS` is the extracted directory; use the actual delivery's top-level name. For a previous complete builder bundle, set `MATERIALS` to its extracted directory and `KIT` to the new standalone toolkit, such as `/srv/nico-build-kit`. Keep the old inventory; do not overwrite old small files or recompress first. Raw materials without `manifests/build-report.json` are unsupported.

## 2. Supply site settings

Goal: reject unknown/null values instead of installing example addresses. Namespace `nico-system`, release prefix and repository prefix have conventional defaults.

Run in the same shell; the configuration file may live elsewhere:

```bash
export SITE_CONFIG=/root/nico-site-config.json
test ! -e "$SITE_CONFIG"
cp "$KIT/site-config.example.json" "$SITE_CONFIG"
vi "$SITE_CONFIG"
```

| Field | Confirm onsite |
| --- | --- |
| `site.bundle_id` | New output basename, default nico-site, distinct from materials id |
| `site.registry` | Image-reference host:port, without scheme or credentials |
| `registry_access.push_url` | http(s)://host:port reachable from the seed host |
| `registry_access.pull_url` | Registry endpoint reachable from Kind and the PXEye Pod; it may differ from the external address |
| `registry_access.insecure` | Skip verification only for this Registry when explicitly selected; default false, independent of Core/Vault TLS |
| `site.context`, `site.kind_node` | kubeconfig context, Kind container and matching node name |
| `site.service_cidr`, `site.service_ips` | Actual Service CIDR and unused internal DNS/PXE/NTP addresses |
| `site.host_network` | HostInband name, physical provisioning prefix/gateway/MTU; distinct from the Service network |
| `site.bundle_host_path` | Host directory visible at the same path inside Kind; default /home/kind/nico-bundles |
| `site.node_port` | Unused UI port, default31808 |
| `storage_class` | Existing StorageClass usable by these workloads |

Confirm:

```bash
python3 -m json.tool "$SITE_CONFIG"
kubectl config get-contexts
kubectl --context "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["site"]["context"])' "$SITE_CONFIG")" get nodes,storageclass
```

Check Registry protocol/trust/authentication, Service CIDR/address use, NodePort, disk and shared mount against the actual site. The current importer supports no-auth registries only; do not put credentials in JSON or URLs. Existing deployments require an ownership/data review before following a first-install guide.

## 3. Generate the site directory

Goal: keep the current PXEye bundle format while reusing large images without copying. Use a new output directory on the same filesystem as the materials. Its basename must match `site.bundle_id`.

Run in the same seed-machine Bash:

```bash
export SITE_OUTPUT="$(python3 -c 'import json,sys; s=json.load(open(sys.argv[1]))["site"]; print(s["bundle_host_path"]+"/"+s["bundle_id"])' "$SITE_CONFIG")"
python3 "$KIT/configure.py" \
  --bundle "$MATERIALS" \
  --site-config "$SITE_CONFIG" \
  --output "$SITE_OUTPUT"
chmod -R a+rX "$SITE_OUTPUT/config" "$SITE_OUTPUT/deployment" "$SITE_OUTPUT/docs"
```

Confirm:

```bash
python3 "$SITE_OUTPUT/tools/verify-bundle.py" "$SITE_OUTPUT"
python3 -m json.tool "$SITE_OUTPUT/manifests/build-report.json"
ls -lh "$SITE_OUTPUT/deployment/pxeye-bootstrap.yaml" "$SITE_OUTPUT/docs/INSTALL.md"
```

Expect `SITE_CONFIGURED ... large_bytes_copied=0 archive_recompressed=false`. Output includes runtime config, four values files, Deployment/RBAC, helpers and a new inventory. Source bytes are unchanged; large materials use hard links and must not be edited. For changes, select a new bundle id/output and regenerate consistently, rather than editing some values while leaving hashes/identity references stale. Hashing large files can take time.

Four Helm phases are rendered locally. Initialization does not check live network reachability/address allocation or install anything. Failure retains `.configuring-*` and does not overwrite existing sites.

## 4. Deploy using the generated guide

Goal: follow site-specific commands in dependency order: materials/cluster checks → Registry/node pulls → ConfigMap/Secret → mounted PXEye/RBAC → NICo images → Helm/UI installation → strict acceptance.

Run in the same shell:

```bash
cat "$SITE_OUTPUT/docs/INSTALL.md"
```

Confirm after deployment, following that guide:

```bash
kubectl --context "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["site"]["context"])' "$SITE_CONFIG")" \
  -n nico-system get pods
```

Every generated chapter includes a goal, execution commands and confirmation commands. Use its fixed site context/namespace and directories, not a previous site's guide. Rendering is not deployment acceptance; Pod readiness is not proof of physical provisioning-network operation.
