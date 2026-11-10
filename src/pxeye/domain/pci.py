"""PCI function addresses are observed attributes, never device identities."""

import re

from pxeye.domain.nic_inventory import INVENTORY_FIELDS, nic_mac


def pci_address(value):
    value = str(value or "").strip().lower()
    return value if re.fullmatch(r"(?:[0-9a-f]{4}:)?[0-9a-f]{2}:[01][0-9a-f]\.[0-7]", value) else ""


def unique_pci_address(values):
    addresses = {address for value in values if (address := pci_address(value))}
    # A short BDF can agree with one complete address without inventing a domain.
    complete = {a for a in addresses if len(a) == 12}
    short = {a for a in addresses if len(a) == 7}
    if len(complete) == 1 and short <= {next(iter(complete))[-7:]}:
        return next(iter(complete))
    return next(iter(addresses)) if len(addresses) == 1 else ""


def scout_pci_address(properties):
    address = pci_address(properties.get("slot"))
    if address:
        return address
    # Select the NIC's final PCI function, not an upstream bridge in its sysfs path.
    parts = str(properties.get("path") or "").split("/")
    if "net" in parts:
        parts = parts[: parts.index("net")]
    return next((a for part in reversed(parts) if (a := pci_address(part))), "")


def redfish_pci_address(report, *, lenovo=False):
    def number(key, maximum):
        value = report.get(key)
        if type(value) is int:
            parsed = value
        elif isinstance(value, str) and re.fullmatch(r"(?:0[xX])?[0-9a-fA-F]+", value):
            parsed = int(value, 16)
        else:
            return None
        return parsed if 0 <= parsed <= maximum else None

    bus, device = number("BusNumber", 255), number("DeviceNumber", 31)
    function = number("FunctionNumber", 7)
    if function is None:
        function = number("FunctionId", 7)
    if bus is not None and device is not None and function is not None:
        segment = number("SegmentNumber", 65535)
        prefix = f"{segment:04x}:" if segment is not None else ""
        return f"{prefix}{bus:02x}:{device:02x}.{function:x}"
    if lenovo:
        # Older XCC documents the function BDF in Name, e.g. "Adapter 03:00:01".
        match = re.search(
            r"\b([0-9a-f]{2}):([01][0-9a-f]):0([0-7])$", str(report.get("Name") or "").lower()
        )
        if match:
            return f"{match[1]}:{match[2]}.{match[3]}"
    return ""


def merge_host_nics(observations, bmc):
    merged, addresses, attributes = {}, {}, {}
    latest = {}
    for nics in observations:
        for nic in nics:
            if "Redfish" in str(nic.get("inventory_source") or ""):
                hardware = nic_mac(nic.get("mac_address") or nic.get("mac"))
                latest[hardware] = max(
                    latest.get(hardware, ""), str(nic.get("inventory_read_at") or "")
                )
    for nics in observations:
        for nic in nics:
            hardware = (
                str(nic.get("mac_address") or nic.get("mac") or "")
                .strip()
                .lower()
                .replace("-", ":")
            )
            if (
                not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", hardware)
                or int(hardware[:2], 16) & 1
                or hardware == "00:00:00:00:00:00"
            ):
                continue
            if hardware == bmc:
                continue
            item = merged.setdefault(hardware, {"mac_address": hardware, "name": ""})
            stale = "Redfish" in str(nic.get("inventory_source") or "") and str(
                nic.get("inventory_read_at") or ""
            ) < latest.get(hardware, "")
            for key in ("name", "model", "vendor"):
                if nic.get(key) and not stale:
                    item[key] = nic[key]
            if nic.get("pci_conflict"):
                item["pci_conflict"] = True
            addresses.setdefault(hardware, set()).add(pci_address(nic.get("pci_address")))
            for key in INVENTORY_FIELDS[3:]:
                if stale and key != "inventory_source":
                    continue
                value = nic.get(key)
                if value is None or value == "":
                    continue
                if type(value) is float and value.is_integer():
                    value = int(value)
                # Prefer newer BMC observations over old cached discovery proofs.
                stamp = "" if key == "inventory_source" else str(nic.get("inventory_read_at") or "")
                previous = attributes.setdefault(hardware, {}).get(key)
                if previous is None or stamp > previous[0]:
                    attributes[hardware][key] = (stamp, {str(value): value})
                elif stamp == previous[0]:
                    previous[1][str(value)] = value
    for hardware, item in merged.items():
        conflicts = []
        for key, (_, values) in attributes.get(hardware, {}).items():
            if len(values) == 1:
                item[key] = next(iter(values.values()))
            elif key in {"inventory_note", "inventory_source", "description"}:
                item[key] = "; ".join(sorted(values))
            else:
                conflicts.append(key)
        if conflicts:
            item["inventory_note"] = "; ".join(
                filter(
                    None,
                    [
                        item.get("inventory_note"),
                        "Conflicting observations: " + ", ".join(conflicts),
                    ],
                )
            )
        known = addresses[hardware] - {""}
        item["pci_address"] = "" if item.get("pci_conflict") else unique_pci_address(known)
        if known and not item["pci_address"]:
            item["pci_conflict"] = True
        if item.get("pci_conflict"):
            item["pci_note"] = "PCIe 地址回报不一致，请刷新设备信息核对。"
    return [merged[key] for key in sorted(merged)]
