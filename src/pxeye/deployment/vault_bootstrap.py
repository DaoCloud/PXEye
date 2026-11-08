"""Helm-hook Vault bootstrap; recovery credentials are saved only in Kubernetes Secrets."""

import base64
import json
import os
import ssl
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from pxeye.clients.process import run
from pxeye.deployment.kubernetes import CurrentCluster


def main():
    os.umask(0o077)
    prefix = os.environ["NICO_PREFIX"]
    cluster = CurrentCluster({}, "/tmp")
    address = os.environ["NICO_VAULT_URL"]
    names = {
        key: prefix + "-nico-" + value
        for key, value in (
            ("ca", "site-ca"),
            ("recovery", "vault-recovery"),
            ("token", "vault-token"),
        )
    }

    def secret(name):
        row = cluster.get("secrets", name)
        return (
            {k: base64.b64decode(v).decode() for k, v in row.get("data", {}).items()}
            if row
            else None
        )

    def write_secret(name, values):
        path = cluster.path("secrets", cluster.namespace, name)
        existing = cluster.request(path)
        if existing:
            raise ValueError("Bootstrap refused to overwrite an existing Secret")
        cluster.request(
            cluster.path("secrets", cluster.namespace),
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {
                    "name": name,
                    "namespace": cluster.namespace,
                    "labels": {"app.kubernetes.io/instance": prefix + "-vault-bootstrap"},
                },
                "type": "Opaque",
                "stringData": values,
            },
        )

    deadline = time.monotonic() + 480
    ca = secret(names["ca"])
    while not ca and time.monotonic() < deadline:
        time.sleep(2)
        ca = secret(names["ca"])
    if not ca:
        raise ValueError("Site CA was not issued before the bootstrap deadline")
    with tempfile.TemporaryDirectory() as directory:
        ca_path = Path(directory) / "ca.crt"
        ca_path.write_text(ca["tls.crt"])
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(ca_path))),
        )
        root_token = None

        def call(method, path, data=None):
            request = urllib.request.Request(
                address + "/v1/" + path,
                method=method,
                data=json.dumps(data).encode() if data is not None else None,
                headers={
                    "Content-Type": "application/json",
                    **({"X-Vault-Token": root_token} if root_token else {}),
                },
            )
            try:
                with opener.open(request, timeout=15) as response:
                    return json.loads(response.read() or b"{}")
            except urllib.error.HTTPError as error:
                raise ValueError(f"Vault bootstrap API returned HTTP {error.code}") from None

        while True:
            try:
                initialized = call("GET", "sys/init")["initialized"]
                break
            except (ValueError, OSError):
                if time.monotonic() >= deadline:
                    raise ValueError("Vault TLS endpoint unavailable") from None
                time.sleep(2)
        recovery = secret(names["recovery"])
        if not initialized:
            if recovery:
                raise ValueError(
                    "Vault data and existing recovery Secret differ; refusing initialization"
                )
            result = call("POST", "sys/init", {"secret_shares": 1, "secret_threshold": 1})
            write_secret(names["recovery"], {"initialization.json": json.dumps(result)})
            recovery = {"initialization.json": json.dumps(result)}
        if not recovery:
            raise ValueError("Vault is already initialized but its recovery Secret is missing")
        result = json.loads(recovery["initialization.json"])
        if call("GET", "sys/seal-status")["sealed"]:
            call("POST", "sys/unseal", {"key": result["keys_base64"][0]})
        root_token = result["root_token"]
        while True:
            leader = call("GET", "sys/leader")
            if not leader.get("ha_enabled") or leader.get("is_self"):
                break
            if time.monotonic() >= deadline:
                raise ValueError("Vault leader unavailable")
            time.sleep(2)
        mounts = call("GET", "sys/mounts")["data"]
        if "secrets/" not in mounts:
            call("POST", "sys/mounts/secrets", {"type": "kv", "options": {"version": "2"}})
        if "certs/" not in mounts:
            call("POST", "sys/mounts/certs", {"type": "pki", "config": {"max_lease_ttl": "87600h"}})
        call("POST", "certs/config/ca", {"pem_bundle": ca["tls.crt"] + ca["tls.key"]})
        call(
            "POST",
            "certs/roles/nico-cluster",
            {
                "allow_any_name": True,
                "allow_localhost": True,
                "allow_bare_domains": True,
                "allow_subdomains": True,
                "require_cn": False,
                "max_ttl": "720h",
                "allowed_uri_sans": ["spiffe://nico.local/*"],
            },
        )
        policy = "\n".join(
            (
                'path "secrets/data/*" { capabilities = ["create", "read", "update", "delete", "list"] }',
                'path "secrets/metadata/*" { capabilities = ["read", "list", "delete"] }',
                'path "certs/issue/nico-cluster" { capabilities = ["create", "update"] }',
                'path "certs/sign/nico-cluster" { capabilities = ["create", "update"] }',
                'path "certs/cert/*" { capabilities = ["read"] }',
            )
        )
        call("PUT", "sys/policies/acl/nico-core", {"policy": policy})
        auth = call("GET", "sys/auth")["data"]
        if "kubernetes/" not in auth:
            call("POST", "sys/auth/kubernetes", {"type": "kubernetes"})
        call(
            "POST",
            "auth/kubernetes/config",
            {
                "kubernetes_host": cluster.server,
                "kubernetes_ca_cert": (cluster.account / "ca.crt").read_text(),
            },
        )
        core_account = os.environ.get("NICO_CORE_SERVICE_ACCOUNT") or prefix + "-nico-api"
        call(
            "POST",
            "auth/kubernetes/role/nico-api",
            {
                "bound_service_account_names": [core_account],
                "bound_service_account_namespaces": [cluster.namespace],
                "policies": ["nico-core"],
                "ttl": "1h",
            },
        )
        if not secret(names["token"]):
            token = call(
                "POST",
                "auth/token/create",
                {
                    "policies": ["nico-core"],
                    "period": "720h",
                    "renewable": True,
                    "display_name": prefix + "-nico-core",
                },
            )
            write_secret(names["token"], {"token": token["auth"]["client_token"]})
        else:
            token = secret(names["token"])["token"]
            call("POST", "auth/token/renew", {"token": token})
        ssh_name = prefix + "-ssh-host-key"
        if not secret(ssh_name):
            key = Path(directory) / "ssh_host_ed25519_key"
            run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)])
            public = key.with_suffix(".pub").read_text()
            write_secret(
                ssh_name,
                {
                    "ssh_host_ed25519_key": key.read_text(),
                    "ssh_host_ed25519_key.pub": public,
                    "ssh_host_ed25519_key_pub": public,
                },
            )
    print(
        "Vault initialized and unsealed; core token and recovery material stored in restricted Secrets."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            "Vault bootstrap failed: "
            + (str(error) if isinstance(error, ValueError) else type(error).__name__)
        )
        raise SystemExit(1)
