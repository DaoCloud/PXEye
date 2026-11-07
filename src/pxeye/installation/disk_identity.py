"""Resolve Scout's udev serial to one persistent whole-disk path on the host."""

import json
import subprocess
from pathlib import Path


def properties(path):
    output = subprocess.check_output(
        ["udevadm", "info", "--query=property", "--name=" + str(path)], text=True, timeout=20
    )
    return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)


def resolve_disk(serial):
    rows = json.loads(
        subprocess.check_output(["lsblk", "-d", "-J", "-o", "NAME,TYPE,RM"], text=True, timeout=20)
    )["blockdevices"]
    matches = [
        Path("/dev") / d["name"]
        for d in rows
        if d["type"] == "disk"
        and not d["rm"]
        and properties(Path("/dev") / d["name"]).get("ID_SERIAL_SHORT") == serial
    ]
    if len(matches) != 1:
        raise RuntimeError("SCOUT_DISK_SERIAL_ABSENT_OR_AMBIGUOUS")
    paths = [
        p
        for p in Path("/dev/disk/by-id").iterdir()
        if p.resolve() == matches[0].resolve() and "-part" not in p.name
    ]
    if not paths:
        raise RuntimeError("DISK_HAS_NO_PERSISTENT_ID")
    return sorted(paths, key=lambda p: (not p.name.startswith("wwn-"), str(p)))[0]


def disk_layout(disk):
    return {k: disk.get(k) for k in ("type", "fstype", "wwn", "serial")} | {
        "children": [disk_layout(c) for c in disk.get("children", [])]
    }
