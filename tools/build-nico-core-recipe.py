#!/usr/bin/env python3
"""Build a PXEye-discoverable offline recipe for the bundled NICo Core stack.

The field bundle currently contains the Core umbrella chart and its single-node
platform dependencies, but not the site-supplied REST/Temporal/Keycloak charts.
This tool therefore creates an explicitly scoped Core recipe instead of claiming
that the optional REST stack is present.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import shutil
import subprocess
from pathlib import Path
from textwrap import dedent


DEFAULTS = {
    "core_image": "docker.io/library/nico-api:mmzhou-e703126e4",
    "bmc_image": "docker.io/library/nico-bmc-proxy:mmzhou-e703126e4",
    "pxe_image": "docker.io/library/nico-pxe:mmzhou-e703126e4",
    "boot_image": "docker.io/library/boot-artifacts-x86_64:mmzhou-e703126e4",
    "postgres_image": "m.daocloud.io/docker.io/library/postgres:16.6",
    "vault_image": "m.daocloud.io/docker.io/hashicorp/vault:1.20.2",
    "chrony_image": "m.daocloud.io/docker.io/dockurr/chrony:latest",
    "pxeye_image": "docker.io/library/mmzhou-os-install-console:0.20.3-20261107-r16",
    "site_name": "NICo Core single-node lab",
    "network_name": "mmzhou-host-boot",
    "network_prefix": "192.0.2.0/24",
    "network_gateway": "192.0.2.1",
}


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).lstrip())
    path.chmod(0o600)


def copy_chart(bundle: Path, pattern: str, destination: Path) -> Path:
    """Copy one chart package without accidentally selecting optional charts.

    The field bundle contains ``nico-0.1.1.tgz`` alongside
    ``nico-rest-*.tgz``.  A broad ``nico-*.tgz`` glob therefore cannot identify
    the Core umbrella chart.  The caller passes a pattern whose first version
    character is constrained to a digit.
    """

    charts = sorted((bundle / "charts").glob(pattern))
    if len(charts) != 1:
        raise SystemExit(f"expected exactly one {pattern} in {bundle / 'charts'}")
    target = destination / charts[0].name
    shutil.copyfile(charts[0], target)
    target.chmod(0o600)
    return target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chart-source", type=Path, required=True)
    parser.add_argument("--release-prefix", default="mmzhou")
    parser.add_argument("--site-name", default=DEFAULTS["site_name"])
    parser.add_argument("--network-name", default=DEFAULTS["network_name"])
    parser.add_argument("--network-prefix", default=DEFAULTS["network_prefix"])
    parser.add_argument("--network-gateway", default=DEFAULTS["network_gateway"])
    for key in DEFAULTS:
        if key in {"site_name", "network_name", "network_prefix", "network_gateway"}:
            continue
        parser.add_argument(f"--{key.replace('_', '-')}", dest=key, default=DEFAULTS[key])
    return parser.parse_args()


def image_parts(reference: str) -> tuple[str, str]:
    repository, separator, tag = reference.rpartition(":")
    if not separator or not repository or not tag or "/" in tag:
        raise SystemExit(f"image reference must include a tag: {reference}")
    return repository, tag


def lock_recipe_files(output: Path, manifest: dict) -> None:
    """Add the SHA256 lock required by PXEye's ``Packages.load``.

    A recipe generated directly under ``bundle/deployment`` must already be a
    valid PXEye package.  The separate packaging helper remains useful when a
    recipe is copied into an upload package, but field-bundle discovery does
    not run that helper for us.
    """

    locked = {}
    for phase in manifest["phases"]:
        for relative in [phase["chart"], *phase.get("values", [])]:
            path = (output / relative).resolve()
            if not path.is_file() or not path.is_relative_to(output):
                raise SystemExit(f"recipe file is missing: {relative}")
            locked[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest["files"] = dict(sorted(locked.items()))


def main() -> None:
    args = parse_args()
    bundle = args.bundle.resolve()
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"output already exists: {output}")
    if not (bundle / "images" / "nico-amd64.oci.tar").is_file():
        raise SystemExit("bundle is missing images/nico-amd64.oci.tar")
    if not args.chart_source.joinpath("Chart.yaml").is_file():
        raise SystemExit("chart source must contain Chart.yaml")

    charts = output / "charts"
    values = output / "values"
    charts.mkdir(parents=True)
    values.mkdir()
    copy_chart(bundle, "cert-manager-v[0-9]*.tgz", charts)
    copy_chart(bundle, "nico-[0-9]*.tgz", charts)
    platform_package = charts / "pxeye-nico-platform-0.1.0.tgz"
    subprocess.run(
        ["helm", "package", str(args.chart_source), "--destination", str(charts)],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    packaged = sorted(charts.glob("pxeye-nico-platform-*.tgz"))
    if len(packaged) != 1:
        raise SystemExit("platform chart did not produce exactly one package")
    if packaged[0] != platform_package:
        packaged[0].rename(platform_package)

    prefix = "@{release_prefix}"
    namespace_token = "@{namespace}"
    cert_chart = next(charts.glob("cert-manager-*.tgz")).name
    nico_chart = next(charts.glob("nico-*.tgz")).name
    core_repository, core_tag = image_parts(args.core_image)
    bmc_repository, bmc_tag = image_parts(args.bmc_image)
    pxe_repository, pxe_tag = image_parts(args.pxe_image)
    boot_repository, boot_tag = image_parts(args.boot_image)
    chrony_repository, chrony_tag = image_parts(args.chrony_image)
    if not re.fullmatch(r"mmzhou-[a-z0-9-]+", args.network_name):
        raise SystemExit("network name must use the mmzhou-* convention")
    try:
        network = ipaddress.ip_network(args.network_prefix, strict=True)
        gateway = ipaddress.ip_address(args.network_gateway)
    except ValueError as error:
        raise SystemExit(f"invalid IPv4 network or gateway: {error}") from None
    if network.version != 4 or gateway not in network:
        raise SystemExit("network prefix and gateway must be an IPv4 pair")
    site_toml = f'''\
tpm_required = false
attestation_enabled = false
allow_insecure_discovery = false
sitename = "{args.site_name}"
initial_domain_name = "nico.internal"
ntp_servers = []
dhcp_servers = []
route_servers = []
enable_route_servers = false
site_fabric_prefixes = []

[pools.lo-ip]
type = "ipv4"
ranges = [{{ start = "10.254.250.1", end = "10.254.250.254" }}]
[pools.vlan-id]
type = "integer"
ranges = [{{ start = "3000", end = "3099" }}]
[pools.vni]
type = "integer"
ranges = [{{ start = "100000", end = "100999" }}]
[pools.vpc-vni]
type = "integer"
ranges = [{{ start = "200000", end = "200999" }}]

[site_explorer]
enabled = false
create_machines = false
dpu_policy = "ignore"
[firmware_global]
autoupdate = false
[dpf]
enabled = false
[machine_validation_config]
enabled = false

[networks.{args.network_name}]
type = "hostinband"
prefix = "{network}"
gateway = "{gateway}"
mtu = 1500
reserve_first = 5
allocation_strategy = "reserved"
'''
    site_config_block = "\n".join(
        "              " + line for line in dedent(site_toml).strip().splitlines()
    )

    write(
        values / "cert-manager.yaml",
        f"""
        crds:
          enabled: true
          keep: true
        image:
          repository: m.daocloud.io/quay.io/jetstack/cert-manager-controller
          tag: v1.17.1
          pullPolicy: IfNotPresent
        cainjector:
          image:
            repository: m.daocloud.io/quay.io/jetstack/cert-manager-cainjector
            tag: v1.17.1
            pullPolicy: IfNotPresent
        webhook:
          image:
            repository: m.daocloud.io/quay.io/jetstack/cert-manager-webhook
            tag: v1.17.1
            pullPolicy: IfNotPresent
        startupapicheck:
          image:
            repository: m.daocloud.io/quay.io/jetstack/cert-manager-startupapicheck
            tag: v1.17.1
            pullPolicy: IfNotPresent
        """,
    )
    write(
        values / "platform.yaml",
        f"""
        mode: infrastructure
        prefix: "{prefix}"
        storageClass: ""
        postgresStorage: 20Gi
        vaultStorage: 5Gi
        postgresImage: "{args.postgres_image}"
        vaultImage: "{args.vault_image}"
        """,
    )
    write(
        values / "vault.yaml",
        f"""
        mode: vault-bootstrap
        prefix: "{prefix}"
        bootstrapImage: "{args.pxeye_image}"
        coreServiceAccount: "{prefix}-nico-api"
        """,
    )
    write(
        values / "core.yaml",
        f"""
        global:
          image:
            repository: "{core_repository}"
            tag: "{core_tag}"
            pullPolicy: IfNotPresent
          certificate:
            useCertManager: false
            issuerRef:
              kind: Issuer
              name: "{prefix}-nico-site-issuer"
              group: cert-manager.io
          spiffe:
            trustDomain: nico.local
        nico-api:
          siteConfig:
            enabled: true
            nicoApiSiteConfig: |
{site_config_block}
          hostname: "nico.local"
          vaultClusterInfo:
            VAULT_SERVICE: "https://{prefix}-nico-vault.{namespace_token}.svc:8200"
            VAULT_NAMESPACE: ""
            NICO_VAULT_MOUNT: "secrets"
            NICO_VAULT_PKI_MOUNT: "certs"
          databaseConfig:
            DB_HOST: "{prefix}-nico-postgres.{namespace_token}.svc"
            DB_PORT: "5432"
            DB_NAME: "nico"
          env:
            VAULT_PKI_ROLE_NAME: "nico-cluster"
          envFrom:
            vaultApproleTokens: {{secretName: "{prefix}-nico-vault-approle-tokens"}}
            vaultToken: {{secretName: "{prefix}-nico-vault-token"}}
            vaultClusterInfo: {{configMapName: "{prefix}-vault-cluster-info"}}
            databaseCredentials: {{secretName: "{prefix}-postgres-credentials"}}
            databaseConfig: {{configMapName: "{prefix}-nico-database-config"}}
            nicoWebHostname: {{configMapName: "{prefix}-nico-web-hostname"}}
          dpf:
            rbacCreate: false
        nico-bmc-proxy:
          image: {{repository: "{bmc_repository}", tag: "{bmc_tag}"}}
          envFrom:
            vaultApproleTokens: {{secretName: "{prefix}-nico-vault-approle-tokens"}}
            vaultToken: {{secretName: "{prefix}-nico-vault-token"}}
            vaultClusterInfo: {{configMapName: "{prefix}-vault-cluster-info"}}
            databaseCredentials: {{secretName: "{prefix}-postgres-credentials"}}
            databaseConfig: {{configMapName: "{prefix}-nico-database-config"}}
        nico-pxe:
          image: {{repository: "{pxe_repository}", tag: "{pxe_tag}"}}
          replicas: 1
          bootArtifactContainers:
            - name: boot-artifacts-x86-64
              image: "{boot_repository}:{boot_tag}"
              command: ["sh", "-c", "set -e; cp -r /x86_64 /forge-boot-artifacts/blobs/internal"]
        nico-ntp:
          image:
            repository: "{chrony_repository}"
            tag: "{chrony_tag}"
        nico-dsx-exchange-consumer:
          enabled: false
        nico-machine-a-tron:
          enabled: false
        nico-postgres-exporter:
          enabled: false
        unbound:
          enabled: false
        """,
    )

    manifest = {
        "schema_version": 1,
        "name": "NICo Core single-node lab",
        "version": "e703126e4-core-site-v1",
        "description": "Core、PXE、DHCP、DNS、NTP、BMC Proxy、PostgreSQL、Vault 和 cert-manager；不包含 REST/Temporal/Keycloak。",
        "profile": "helm",
        "initialization": {
            "vault": "vault"
        },
        "defaults": {
            "site_name": args.site_name,
            "release_prefix": args.release_prefix,
            "core_url": "https://mmzhou-nico-api.mmzhou.svc:1079",
            "pxe_url": "http://mmzhou-nico-pxe.mmzhou.svc:8080",
        },
        "phases": [
            {"id": "cert-manager", "name": "证书管理", "release": f"{prefix}-cert-manager", "chart": f"charts/{cert_chart}", "values": ["values/cert-manager.yaml"], "timeout_seconds": 900},
            {"id": "platform", "name": "数据库与站点证书", "release": f"{prefix}-platform", "chart": "charts/pxeye-nico-platform-0.1.0.tgz", "values": ["values/platform.yaml"], "timeout_seconds": 900},
            {"id": "vault", "name": "Vault 初始化", "release": f"{prefix}-vault", "chart": "charts/pxeye-nico-platform-0.1.0.tgz", "values": ["values/vault.yaml"], "timeout_seconds": 900},
            {"id": "core", "name": "NICo Core 与网络引导", "release": prefix, "chart": f"charts/{nico_chart}", "values": ["values/core.yaml"], "timeout_seconds": 900},
        ],
        "connection": {
            "namespace": "@{namespace}",
            "client_secret": f"{prefix}-nico-admin-client",
            "ca_secret": f"{prefix}-nico-site-ca",
            "ca_key": "tls.crt",
            "pxe_internal_url": f"http://{prefix}-nico-pxe.@{{namespace}}.svc:8080",
        },
        "boot_checks": [
            {"architecture": "x86_64", "url": f"http://{prefix}-nico-pxe.@{{namespace}}.svc:8080/public/blobs/internal/x86_64/ipxe.efi", "min_bytes": 100000},
            {"architecture": "x86_64", "url": f"http://{prefix}-nico-pxe.@{{namespace}}.svc:8080/public/blobs/internal/x86_64/scout.efi", "min_bytes": 100000},
            {"architecture": "x86_64", "url": f"http://{prefix}-nico-pxe.@{{namespace}}.svc:8080/public/blobs/internal/x86_64/scout.squashfs", "min_bytes": 100000000},
        ],
    }
    lock_recipe_files(output, manifest)
    (output / "deployment.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    (output / "deployment.json").chmod(0o600)
    print(output)


if __name__ == "__main__":
    main()
