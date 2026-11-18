"""Read-only storage inventory for the device-details page."""

import json
import time

from pxeye.clients.redfish import REDFISH_DEADLINE
from pxeye.common import atomic_json, digest


def _media(report):
    value = report.get("MediaType")
    return value if value in ("SSD", "HDD", "SMR", "Optane") else None


def _row(report, media_type):
    capacity = report.get("CapacityBytes")
    return {
        "name": report.get("Name") or report.get("DisplayName"),
        "model": report.get("Model"),
        "capacity_bytes": capacity if type(capacity) is int and capacity > 0 else None,
        "media_type": media_type,
        "serial": report.get("SerialNumber"),
    }


def collect_disks(read, system):
    cache = {}

    def fetch(link):
        path = link["@odata.id"]
        if path not in cache:
            if len(cache) >= 512:
                raise ValueError("存储清单超出读取上限。")
            cache[path] = read(path)
        return cache[path]

    def members(link):
        collection = fetch(link)
        items = collection["Members"]
        if collection.get("Members@odata.nextLink") or not isinstance(items, list):
            raise ValueError("存储清单不完整。")
        return [fetch(item) for item in items]

    if not system.get("Storage"):
        raise ValueError("BMC 未提供 Storage 清单。")
    rows, claimed, seen_volumes = [], set(), set()
    standalone = {}
    for controller in members(system["Storage"]):
        drives = {ref["@odata.id"]: fetch(ref) for ref in controller.get("Drives", [])}
        volumes = members(controller["Volumes"]) if controller.get("Volumes") else []
        raid = bool(volumes) or "raid" in str(controller.get("Name", "")).casefold()
        for volume in volumes:
            path = volume["@odata.id"]
            refs = {ref["@odata.id"] for ref in volume.get("Links", {}).get("Drives", [])}
            refs.update(
                uri
                for uri, drive in drives.items()
                if any(
                    ref.get("@odata.id") == path
                    for ref in drive.get("Links", {}).get("Volumes", [])
                )
            )
            claimed.update(refs)
            if path in seen_volumes:
                continue
            seen_volumes.add(path)
            media = {_media(fetch({"@odata.id": uri})) for uri in refs}
            kind = _media(volume)
            if not kind and media and None not in media:
                kind = " / ".join(sorted(media))
            rows.append(_row(volume, kind))
        for path, drive in drives.items():
            if drive.get("Status", {}).get("State") == "Absent":
                continue
            if drive.get("Links", {}).get("Volumes"):
                claimed.add(path)
                continue
            if (
                drive.get("HotspareType") not in (None, "None")
                or drive.get("StatusIndicator") == "Hotspare"
            ):
                continue
            if raid and not (
                drive.get("Oem", {}).get("Dell", {}).get("DellPhysicalDisk", {}).get("RaidStatus")
                == "NonRAID"
            ):
                continue
            standalone[path] = drive
    rows.extend(
        _row(drive, _media(drive)) for path, drive in standalone.items() if path not in claimed
    )
    hidden_serials = {fetch({"@odata.id": path}).get("SerialNumber") for path in claimed}
    return {"rows": rows, "member_serials": sorted(value for value in hidden_serials if value)}


def _path(adapter, serial, mac):
    return (
        adapter.data
        / "observations"
        / "storage"
        / (digest([serial.upper(), mac.lower()]) + ".json")
    )


def cached_disks(adapter, serial, mac):
    path = _path(adapter, serial, mac)
    return json.loads(path.read_text()) if path.is_file() else {}


def refresh_disks(adapter, address, credential, identity, mac):
    serial = identity["serial"]
    previous = cached_disks(adapter, serial, mac)
    deadline = time.monotonic() + 20
    token = REDFISH_DEADLINE.set(min(REDFISH_DEADLINE.get() or deadline, deadline))
    try:

        def read(path):
            return adapter.redfish_read(address, path, credential)

        system = read("/redfish/v1/Systems/" + identity["evidence"]["system_id"])
        if system.get("SerialNumber", "").strip().upper() != serial.upper():
            raise ValueError("存储所属主机身份不匹配。")
        inventory = dict(collect_disks(read, system), observed_at=time.time())
    except (RuntimeError, ValueError, OSError, KeyError, TypeError, AttributeError):
        inventory = dict(previous, error="未能读取完整的 BMC 磁盘清单。")
    finally:
        REDFISH_DEADLINE.reset(token)
    atomic_json(_path(adapter, serial, mac), inventory)
    return inventory


def display_disks(inventory, scout):
    rows = [dict(row) for row in inventory.get("rows", [])]
    known = {row["serial"]: row for row in rows if row.get("serial")}
    hidden = set(inventory.get("member_serials", []))
    for disk in scout:
        serial = disk.get("serial")
        if serial and serial in hidden:
            continue
        if serial == "NO_SERIAL":
            serial = None
        size = disk.get("size_mb")
        capacity = size * 1024**2 if size else None
        if serial in known:
            if sum(row.get("serial") == serial for row in rows) != 1:
                continue
            row = known[serial]
            row["model"] = row.get("model") or disk.get("model")
            row["capacity_bytes"] = row.get("capacity_bytes") or capacity
        elif not inventory.get("rows") or disk.get("is_nvme"):
            rows.append(
                {
                    "name": disk.get("name"),
                    "model": disk.get("model"),
                    "capacity_bytes": capacity,
                    "media_type": None,
                }
            )
    return [{key: value for key, value in row.items() if key != "serial"} for row in rows]
