# Offline NICo REST management materials

**English** · [简体中文](README.zh-CN.md)

## Native dependencies and namespaces

| Component | Child Chart | Opt-in release / namespace |
| --- | --- | --- |
| REST services | Upstream `nico-rest` | `nico-rest` / `nico-rest` |
| Site Agent | Upstream `nico-rest-site-agent` | `nico-rest-site-agent` / `nico-rest` |
| Temporal | NICo-pinned upstream `temporal` | `temporal` / `temporal` |
| Keycloak | Project `pxeye-keycloak` (the pinned NICo version used prerequisite manifests, not a standalone Chart) | `nico-keycloak` / `nico-rest`; Service `keycloak` |

The parent always contains these dependencies but is not the install target for optional releases. The helper selects the actual child (vendored `.tgz` or expanded directory) from the **onsite relocated** parent. Helm records the child's name and version; for example, `helm list -n temporal` should show `temporal-0.35.0`, not `pxeye-*`. `managementReleases` in the parent values supplies the default release names and namespaces. Preview first:

```bash
bash tools/management-release.sh template temporal "$PARENT_CHART" -f site-values.yaml
# Existing upstream Temporal values need no temporal: wrapper:
bash tools/management-release.sh template temporal "$PARENT_CHART" --native-values temporal-values.yaml
```

Other component keys are `rest`, `siteagent` and `keycloak`. Run from the full delivery tools directory (Bash, GNU tar, Helm, yq and jq). For a standalone copy of the helper, set `PXEYE_ONSITE_LIB` to the matching trusted kit's `onsite/lib`. The standard `relocation/pxeye/chart.tgz` is matched to the import's `catalog.json`; pass `--catalog /path/to/catalog.json` when the archive is copied elsewhere. A completed import, matching parent SHA256 and rendered workload/init/hook images present in that onsite registry catalog are required before any Helm write.

`-f` keeps the parent format: only the selected subtree and the parent's `global` are passed down, with parent globals taking precedence on conflicts. `--native-values` takes child-shaped values directly; later files of each kind win. During upgrade, explicit values from the existing native release are retained unless overridden by site `-f` files, then by `--native-values`. Packaged image bindings take precedence; upstream-registry fallback is not allowed. `template` does not read the cluster: supply a restricted `--native-values` file to preview an existing release's customizations. Do not put credentials in command arguments.

Only `upgrade` writes to the cluster: absent releases use `helm install --wait`; existing ones use `helm upgrade --wait` after Helm metadata confirms the release name, namespace, **native Chart name** and `deployed` status. Old `pxeye` parent releases, other Charts and non-deployed states require separate migration or reconciliation. Prepare the namespace first; if overriding the release name or namespace, review DNS, TLS SANs, RBAC and site registration as well.

These are delivery inputs, not an installer or an authorization grant. Core/PXEye installation does not create REST, Site Agent, Temporal, Keycloak or the Site CRD by default. Render with site-specific values and review namespaces, resource names, RBAC, TLS SANs and relocated images before enabling anything. Never deploy the packager's per-component render fixtures. By default Site Manager is not granted cluster-wide RBAC; provision its dedicated ServiceAccount and permissions in the target namespace.

| Packaged material | Purpose and site inputs |
| --- | --- |
| `charts/nico-rest-*.tgz` | REST API, credential manager, Site Manager, cloud/site workers, DB migration Job and Site CRD. The REST credential manager is distinct from Kubernetes cert-manager. Provision separate databases, owners and migration grants on an approved PostgreSQL installation; `databases.sql.example` contains no passwords. |
| `charts/temporal-*.tgz` | PostgreSQL persistence, frontend/history/matching/worker, admin tools and schema Jobs. `temporal-certificates.reference.yaml` comes from the pinned Chart source. Adapt namespace, issuer, Secrets and service DNS before requesting certificates. After TLS and schema setup, use the shipped admin tools to inspect and initialize the logical `cloud`, `site` and site-UUID Temporal namespaces as needed; these are not Kubernetes namespaces. |
| `charts/pxeye-keycloak-*.tgz` | Optional development IdP; omit it when using an external OIDC issuer. `realm.blueprint.json` preserves upstream roles, clients and claim mappers but contains no users, credentials or grants. Configure the site's organization, issuer, TLS, client credentials and role assignments before providing the realm via an existing Secret. |
| `charts/nico-rest-site-agent-*.tgz` | Site registration hook, helper image and agent. Supply the intended Site UUID, Core endpoint, dedicated trusted Core mTLS identity, Temporal certificates and site naming policy. Do not copy another application's admin key. NICo Flow is outside this host-management profile. |

The parent switches `components.{rest,siteagent,temporal,keycloak}.enabled` default to `false`; component settings live under `rest`, `siteagent`, `temporal` and `keycloak`. Switches do not sequence readiness: provision the DB, issuer and IdP, then Temporal, migrations and REST, then register the Site Agent. Verify `nicocli user get`, `nicocli site list` and `expected-machine list` for the intended Site; ready Pods alone do not prove access.

Use `databases.sql.example` only for new databases, supplying approved identifiers and existing roles via `psql -v`. Provision a separate database and identity for a bundled Keycloak; an external IdP does not need these. Preload or publish the REST image references pinned in the parent Chart on the build host (`nico-local` is not a guaranteed public registry source). Repin and verify the image lock when upgrading; legacy image availability does not prove interoperability with a newer running Core.

Do not ship site keys, tokens, DB passwords or an existing site's OTP. The [NVIDIA Quick Start](https://docs.nvidia.com/infra-controller/documentation/getting-started/quick-start-guide) describes authentication and topology choices. This material covers the PostgreSQL-backed REST profile, not every third-party Temporal backend or NICo hardware extension.
