# Offline NICo REST management materials

**English** · [简体中文](README.zh-CN.md)

## Native dependencies and namespaces

| Component | Child Chart | Opt-in release / namespace |
| --- | --- | --- |
| REST services | Upstream `nico-rest` | `nico-rest` / `nico-rest` |
| Site Agent | Upstream `nico-rest-site-agent` | `nico-rest-site-agent` / `nico-rest` |
| Temporal | NICo-pinned upstream `temporal` | `temporal` / `temporal` |
| Keycloak | Project `pxeye-keycloak` (the pinned NICo version used prerequisite manifests, not a standalone Chart) | `nico-keycloak` / `nico-rest`; Service `keycloak` |

The parent always contains these child Charts. Each management release enables one component. `managementReleases` in the parent values is the authority for release names and namespaces. Preview with the **onsite relocated** parent Chart and site-specific values:

```bash
bash tools/management-release.sh template temporal "$PARENT_CHART" -f site-values.yaml
```

Other component keys are `rest`, `siteagent` and `keycloak`. Only the explicit `upgrade` action runs `helm upgrade --install --wait`; prepare the target namespace first. A same-name native release or a release for another component is not automatically adopted. If overriding `managementReleases.<component>.namespace` or `.name`, also review DNS, certificate SANs, RBAC references and site registration settings. Do not enable all components in the Core release. Build-time authentication fixtures are not onsite values.

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
