#!/usr/bin/env python3
"""Run read-only nico-admin-cli commands with the Core identity of a PXEye instance.

Run inside a PXEye container, where the Core address and client identity already
exist. Only the reading commands listed in READ_COMMANDS are accepted, so a field
survey cannot change the site by mistake:

    kubectl -n <namespace> exec -i deploy/<pxeye> -c pxeye -- python3 - machine show --hosts < tools/core-cli.py
    kubectl -n <namespace> exec -i deploy/<pxeye> -c pxeye -- python3 - --json machine show <machine ID> < tools/core-cli.py
    kubectl -n <namespace> exec -i deploy/<pxeye> -c pxeye -- python3 - list < tools/core-cli.py

`--json` asks the CLI for JSON instead of a table. `list` prints the accepted commands.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

# Command words that only read, as accepted after `nico-admin-cli`. A longer command
# line is accepted when it starts with one of these; options and IDs may follow.
READ_COMMANDS = [
    ("version",),
    ("machine", "show"),
    ("machine", "states"),
    ("machine", "health-history"),
    ("machine", "positions"),
    ("machine", "network", "status"),
    ("machine-interfaces", "show"),
    ("machine-interfaces", "show-addresses"),
    ("machine-validation", "runs", "show"),
    ("machine-validation", "results", "show"),
    ("machine-validation", "tests", "show"),
    ("instance", "show"),
    ("expected-machine", "show"),
    ("expected-switch", "show"),
    ("expected-power-shelf", "show"),
    ("expected-rack", "show"),
    ("switch", "show"),
    ("switch", "list"),
    ("switch", "health-history"),
    ("power-shelf", "show"),
    ("power-shelf", "list"),
    ("power-shelf", "health-history"),
    ("rack", "show"),
    ("rack", "list"),
    ("rack", "state-history"),
    ("rack", "health-history"),
    ("site-explorer", "get-report"),
    ("sku", "show"),
    ("sku", "show-machines"),
    ("firmware", "show"),
    ("network-device", "show"),
    ("network-segment", "show"),
]


def accepted(words):
    return any(tuple(words[: len(command)]) == command for command in READ_COMMANDS)


def settings():
    config = json.loads(Path(os.environ.get("CONSOLE_CONFIG", "/config/site.json")).read_text())
    data = Path(os.environ.get("CONSOLE_DATA", "/data"))
    for name in ("deployment-site.json", "site-settings.json"):
        path = data / "config" / name
        if path.exists():
            config.update(json.loads(path.read_text()))
    if not config.get("core_url"):
        sys.exit("This PXEye instance is not connected to a Core.")
    identity = Path(
        config.get("core_identity_directory") or os.environ.get("CONSOLE_SECRETS", "/secrets")
    )
    return config, identity


def main():
    arguments = sys.argv[1:]
    if not arguments or arguments in (["-h"], ["--help"]):
        sys.exit(__doc__)
    if arguments == ["list"]:
        print("\n".join(" ".join(command) for command in READ_COMMANDS))
        return
    json_output = arguments[0] == "--json"
    if json_output:
        arguments = arguments[1:]
    words = [word for word in arguments if not word.startswith("-")]
    if not accepted(words):
        sys.exit(
            "Refused: only reading commands are accepted. "
            "Run with `list` to see them: " + " ".join(arguments)
        )
    config, identity = settings()
    argv = [
        config.get("cli", "/usr/local/bin/nico-admin-cli"),
        "-a",
        config["core_url"],
        "--root-ca-path",
        str(identity / "ca.crt"),
        "--client-cert-path",
        str(identity / "client.crt"),
        "--client-key-path",
        str(identity / "client.key"),
    ]
    if json_output:
        argv += ["-f", "json"]
    environment = {
        k: v
        for k, v in os.environ.items()
        if k.lower() not in ("http_proxy", "https_proxy", "all_proxy")
    }
    result = subprocess.run(argv + arguments, env=environment, timeout=120)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
