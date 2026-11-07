"""Deployment-side sync of cert-manager TLS material; never logs Secret data."""

import argparse
import base64
import datetime
import json
import subprocess
import tempfile
from pathlib import Path


def command(argv, *, data=None):
    result = subprocess.run(argv, input=data, capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError(
            f"{Path(argv[0]).name} {argv[1]} failed (exit {result.returncode}); output withheld"
        )
    return result.stdout


def sync(
    context,
    source_namespace,
    target_namespace,
    target_secret="pxeye",
    target_instance="pxeye",
):
    base = ["kubectl", "--context=" + context]

    def read(namespace, name):
        return json.loads(command(base + ["-n", namespace, "get", "secret", name, "-o", "json"]))

    cert = read(source_namespace, "nico-admin-client")
    ca = read(source_namespace, "nico-site-ca")
    desired = {
        "client.crt": cert["data"]["tls.crt"],
        "client.key": cert["data"]["tls.key"],
        "ca.crt": ca["data"]["tls.crt"],
    }
    # Validate the source pair and trust before touching the destination.
    with tempfile.TemporaryDirectory(prefix="nico-cert-") as directory:
        paths = {name: Path(directory) / name for name in desired}
        for name, value in desired.items():
            paths[name].write_bytes(base64.b64decode(value, validate=True))
            paths[name].chmod(0o600)
        crt, key, root = (str(paths[n]) for n in ("client.crt", "client.key", "ca.crt"))
        command(["openssl", "x509", "-in", crt, "-checkend", "3600", "-noout"])
        command(
            ["openssl", "verify", "-purpose", "sslclient", "-CAfile", root, "-untrusted", crt, crt]
        )
        public_cert = command(["openssl", "x509", "-in", crt, "-pubkey", "-noout"])
        public_key = command(["openssl", "pkey", "-in", key, "-pubout"])
        if public_cert != public_key:
            raise RuntimeError("Source certificate/key mismatch; destination preserved")
        expiry = command(["openssl", "x509", "-in", crt, "-enddate", "-noout"]).decode().strip()
    target = read(target_namespace, target_secret)
    changed = any(target.get("data", {}).get(k) != v for k, v in desired.items())
    if changed:
        patch = {
            "data": desired,
            "metadata": {
                "resourceVersion": target["metadata"]["resourceVersion"],
                "annotations": {
                    "nico-console/core-cert-source-version": cert["metadata"]["resourceVersion"]
                },
            },
        }
        command(
            base
            + [
                "-n",
                target_namespace,
                "patch",
                "secret",
                target_secret,
                "--type=merge",
                "--patch-file=/dev/stdin",
            ],
            data=json.dumps(patch).encode(),
        )
    # Prompt kubelet to refresh the projected Secret without restarting the app.
    command(
        base
        + [
            "-n",
            target_namespace,
            "annotate",
            "pod",
            "-l",
            "app.kubernetes.io/instance=" + target_instance,
            "nico-console/core-cert-source-version=" + cert["metadata"]["resourceVersion"],
            "--overwrite",
        ]
    )
    print(
        json.dumps(
            {
                "changed": changed,
                "certificate": expiry,
                "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True)
    parser.add_argument("--source-namespace", default="nico-system")
    parser.add_argument("--target-namespace", default="pxeye")
    parser.add_argument("--target-secret", default="pxeye")
    parser.add_argument("--target-instance", default="pxeye")
    args = parser.parse_args()
    try:
        sync(
            args.context,
            args.source_namespace,
            args.target_namespace,
            args.target_secret,
            args.target_instance,
        )
    except Exception as error:
        # Avoid tracebacks involving Secret-bearing locals or command responses.
        print(
            json.dumps(
                {
                    "error": "Certificate synchronization failed",
                    "type": type(error).__name__,
                    "detail": str(error) if isinstance(error, RuntimeError) else "output withheld",
                }
            )
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
