# PXEye Keycloak Chart

This Chart deploys the optional Keycloak service used by the NICo REST profile.
It is not enabled by PXEye's parent Chart by default.

The Chart never creates credentials. Before rendering it, a site must provide:

- an existing Secret containing the bootstrap administrator username and password;
- an existing Secret containing the Keycloak database username and password;
- exactly one realm import source: an existing ConfigMap for non-sensitive JSON, or an
  existing Secret when the realm includes a client secret;
- a reviewed JDBC URL and production-appropriate Keycloak startup arguments.

For example, the following values reference existing site resources without placing
credentials in Helm values:

```yaml
admin:
  existingSecret: keycloak-admin
database:
  url: jdbc:postgresql://postgres.nico-rest.svc:5432/keycloak?sslmode=require
  existingSecret: keycloak-db
realm:
  existingSecret: nico-rest-realm
startup:
  args: [start, --import-realm, --http-enabled=true]
```

The legacy development `start-dev` mode and hard-coded `admin/admin` credentials are
intentionally not defaults. A build profile may render this Chart to collect its image
for an offline bundle, while the shipped parent values keep the optional component
disabled.
