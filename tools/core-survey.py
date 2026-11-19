#!/usr/bin/env python3
"""Survey the read interfaces of the NICo Core a PXEye instance is connected to.

Run inside a PXEye container, where the Core address and client identity already
exist. It uses gRPC server reflection, so the definitions it prints are those of
the Core actually deployed at the site, not of any source checkout:

    kubectl -n <namespace> exec -i deploy/<pxeye> -c pxeye -- python3 - list < tools/core-survey.py
    kubectl -n <namespace> exec -i deploy/<pxeye> -c pxeye -- python3 - describe FindSwitches < tools/core-survey.py
    kubectl -n <namespace> exec -i deploy/<pxeye> -c pxeye -- python3 - message forge.Machine < tools/core-survey.py
    kubectl -n <namespace> exec -i deploy/<pxeye> -c pxeye -- python3 - call 'FindRackIds={}' < tools/core-survey.py
    kubectl -n <namespace> exec -i deploy/<pxeye> -c pxeye -- python3 - ids machines < tools/core-survey.py

Only methods named Find*, Get*, List* or Determine* can be called, and methods that
return credentials or serve the boot path are refused. Values of fields whose names
look like credentials are redacted, and long values are shortened: the output shows
the structure of a response, not a copy of the site's data.

In a `call` request body, MID stands for the first machine ID the Core returns.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

READ = re.compile(r"^(Find|Get|List|Determine)")
# Reads by name, but they return credentials or belong to the machine boot path.
REFUSED = re.compile(
    r"Credential|Password|Secret|Token|^GetBMCMetaData$|^GetPxeInstructions$|^GetCloudInitInstructions$"
)
SENSITIVE = re.compile(r"pass|secret|token|credential|private|\bkey\b", re.I)


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
    return config["core_url"].removeprefix("https://"), identity


ENDPOINT, IDENTITY = settings()
ENV = {
    k: v
    for k, v in os.environ.items()
    if k.lower() not in ("http_proxy", "https_proxy", "all_proxy")
}


def grpcurl(*args, data=None):
    argv = ["/usr/local/bin/grpcurl", "-connect-timeout", "5", "-max-time", "40"]
    for flag, name in (("-cacert", "ca.crt"), ("-cert", "client.crt"), ("-key", "client.key")):
        argv += [flag, str(IDENTITY / name)]
    if data is not None:
        argv += ["-d", "@"]
    result = subprocess.run(
        argv + [ENDPOINT, *args], input=data, capture_output=True, text=True, env=ENV, timeout=60
    )
    return result.returncode == 0, (
        result.stdout if result.returncode == 0 else result.stderr.strip()[:300]
    )


def methods():
    ok, out = grpcurl("list", "forge.Forge")
    if not ok:
        sys.exit("Core reflection is unavailable: " + out)
    return sorted(name.split(".")[-1] for name in out.split())


def shape(value, depth=0):
    if isinstance(value, dict):
        if depth >= 6:
            return "{…}"
        return {
            key: "<redacted>" if SENSITIVE.search(key) else shape(item, depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [shape(value[0], depth + 1), f"…×{len(value)}"] if value else []
    if isinstance(value, str) and len(value) > 60:
        return value[:57] + "…"
    return value


def definition(name, limit=4000):
    ok, out = grpcurl("describe", name)
    lines = [
        line
        for line in out.splitlines()
        if line.strip() and "is a message:" not in line and "is an enum:" not in line
    ]
    return "\n".join(lines)[:limit]


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("list", "describe", "message", "call", "ids"):
        sys.exit(__doc__)
    mode, arguments = sys.argv[1], sys.argv[2:]
    if mode == "list":
        names = methods()
        reads = [name for name in names if READ.match(name) and not REFUSED.search(name)]
        print(f"{len(names)} methods; {len(reads)} callable reads:")
        print("\n".join(reads))
    elif mode == "describe":
        for method in arguments:
            ok, out = grpcurl("describe", "forge.Forge." + method)
            found = re.search(
                r"\( (?:stream )?\.([\w.]+) \) returns \( (?:stream )?\.([\w.]+) \)", out
            )
            if not (ok and found):
                print(f"\n## {method}: not found")
                continue
            print(f"\n## {method}  request={found.group(1)}  response={found.group(2)}")
            print(definition(found.group(1), 1500))
            print(definition(found.group(2), 2500))
    elif mode == "ids":
        # Full identifiers, one per line, for use in later commands. `call` shortens lists.
        kinds = {
            "machines": ("FindMachineIds", "machineIds", "id"),
            "switches": ("FindSwitchIds", "ids", "value"),
            "power-shelves": ("FindPowerShelfIds", "ids", "value"),
            "racks": ("FindRackIds", "rackIds", "value"),
        }
        if not arguments or arguments[0] not in kinds:
            sys.exit("ids takes one of: " + ", ".join(kinds))
        method, key, field = kinds[arguments[0]]
        ok, out = grpcurl("forge.Forge/" + method, data="{}")
        if not ok:
            sys.exit(f"{method} failed: {out}")
        for item in json.loads(out or "{}").get(key, []):
            print(item.get(field, ""))
    elif mode == "message":
        for name in arguments:
            print(f"\n## {name}\n{definition(name)}")
    else:
        ok, out = grpcurl("forge.Forge/FindMachineIds", data="{}")
        machines = (
            [row["id"] for row in json.loads(out or "{}").get("machineIds", [])] if ok else []
        )
        for item in arguments:
            method, _, body = item.partition("=")
            if not READ.match(method) or REFUSED.search(method):
                sys.exit(f"Refused: {method} is not a callable read.")
            if "MID" in body:
                if not machines:
                    print(f"\n## {method}: skipped, the Core has no machine")
                    continue
                body = body.replace("MID", machines[0])
            ok, out = grpcurl("forge.Forge/" + method, data=body or "{}")
            if not ok:
                print(f"\n## {method} -> failed: {out}")
                continue
            response = json.loads(out or "{}")
            counts = {key: len(item) for key, item in response.items() if isinstance(item, list)}
            print(f"\n## {method} -> keys={sorted(response)} counts={counts} bytes={len(out)}")
            print(json.dumps(shape(response), ensure_ascii=False, indent=1)[:4000])


if __name__ == "__main__":
    main()
