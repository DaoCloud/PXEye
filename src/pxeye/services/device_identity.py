"""Shared Redfish device classification and management-MAC verification."""

import re
import time

from pxeye.clients.redfish import REDFISH_DEADLINE


def field(report, name):
    """Accept Redfish fields and NICo's camel/snake-case exploration fields."""
    aliases = {
        "SerialNumber": ("serialNumber", "serial_number"),
        "SystemType": ("systemType", "system_type"),
        "MACAddress": ("macAddress", "mac_address"),
        "EthernetInterfaces": ("ethernetInterfaces", "ethernet_interfaces"),
    }
    for key in (name, name[:1].lower() + name[1:], *aliases.get(name, ())):
        if key in report:
            return report[key]
    return None


def text(report, name):
    value = field(report, name)
    return value.strip() if isinstance(value, str) else ""


def serial_number(report):
    serial = text(report, "SerialNumber")
    if not serial or len(serial) > 128 or any(ord(c) < 32 for c in serial):
        raise ValueError("已识别设备类型，但没有有效的硬件 SN。")
    return serial


def identity(kind, report, source):
    serial = serial_number(report)
    if kind == "server" and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", serial):
        raise ValueError("BMC 返回的主机 SN 无效。")
    return {
        "kind": kind,
        "serial": serial,
        "model": text(report, "Model"),
        "manufacturer": text(report, "Manufacturer"),
        "nics": [],
        "evidence": {
            source + "_id": text(report, "Id"),
            "manufacturer": text(report, "Manufacturer"),
        },
    }


def classify_chassis(chassis):
    """Match NICo's supported NVLink switch and power-shelf identities."""
    recognized = []
    for report in chassis:
        ident, maker = text(report, "Id").lower(), text(report, "Manufacturer").lower()
        delta_shelf = "delta" in maker and (
            ident == "chassis" or re.search(r"power.*shelf", ident) is not None
        )
        if "mgx_nvswitch_0" in ident:
            kind = "switch"
        elif "powershelf" in ident or delta_shelf or (ident == "chassis" and "lite-on" in maker):
            kind = "power_shelf"
        else:
            continue
        recognized.append(identity(kind, report, "chassis"))
    if len(recognized) > 1:
        raise ValueError("返回多个受支持 Chassis，无法唯一确认设备身份。")
    return recognized[0] if recognized else {"kind": "unknown"}


def classify_device(chassis, systems):
    """Classify from observed hardware, independent of a user's declared type."""
    result = classify_chassis(chassis)
    if result["kind"] != "unknown":
        return result
    dpus = [s for s in systems if text(s, "Id").lower() in ("bluefield", "bluefield_0")]
    physical = [
        s
        for s in systems
        if text(s, "SerialNumber")
        and (text(s, "SystemType") or "Physical").lower() == "physical"
        and s not in dpus
    ]
    if dpus:
        if len(dpus) != 1 or physical:
            raise ValueError("返回多个主机或 DPU System，无法唯一确认设备身份。")
        system = dpus[0]
        if not text(system, "SerialNumber"):
            cards = [c for c in chassis if text(c, "Id").lower() == "card1"]
            if len(cards) == 1:
                system = dict(system, SerialNumber=text(cards[0], "SerialNumber"))
        return identity("dpu", system, "system")
    if len(physical) == 1:
        return identity("server", physical[0], "system")
    if physical:
        raise ValueError("未返回唯一物理主机 SN；请核对机型和 BMC。")
    other = [s for s in systems if text(s, "SerialNumber")]
    if len(other) == 1:
        return identity("other", other[0], "system")
    raise ValueError("未返回可唯一识别的设备类型和硬件 SN；请核对机型和 BMC / PMC。")


def members(read, path, limit, label):
    collection = read(path)
    links = collection.get("Members", [])
    if not isinstance(links, list) or len(links) > limit:
        raise ValueError(label + "数量超出支持范围。")
    return [read(member["@odata.id"]) for member in links]


def chassis_identity(adapter, address, credential):
    read = lambda path: adapter.redfish_read(address, path, credential)
    return classify_chassis(members(read, "/redfish/v1/Chassis", 16, "Chassis"))


def verify_manager_mac(adapter, address, hardware, credential):
    read = lambda path: adapter.redfish_read(address, path, credential)
    _verify_manager_mac(read, hardware)


def _verify_manager_mac(read, hardware):
    reported = set()
    for manager in members(read, "/redfish/v1/Managers", 16, "Manager"):
        path = (field(manager, "EthernetInterfaces") or {}).get("@odata.id")
        if path:
            reported.update(
                text(nic, "MACAddress").lower() for nic in members(read, path, 64, "Manager 接口")
            )
    if hardware.lower() not in reported:
        raise ValueError("BMC / PMC 报告的管理 MAC 与观察端点不符。")


def read_device_identity(adapter, address, hardware, credential):
    """Read once per resource, classify, then verify the observed management MAC."""
    cache = {}

    def read(path):
        if path not in cache:
            cache[path] = adapter.redfish_read(address, path, credential)
        return cache[path]

    chassis = members(read, "/redfish/v1/Chassis", 16, "Chassis")
    result = classify_chassis(chassis)
    systems = []
    if result["kind"] == "unknown":
        systems = members(read, "/redfish/v1/Systems", 16, "System")
        result = classify_device(chassis, systems)
    _verify_manager_mac(read, hardware)
    if result["kind"] == "server":
        system = next(s for s in systems if text(s, "SerialNumber") == result["serial"])
        path = (field(system, "EthernetInterfaces") or {}).get("@odata.id")
        ethernet = members(read, path, 64, "主机接口") if path else []
        from pxeye.services.redfish_nics import host_nics

        # Optional PCI inventory must not turn a successful identity read into
        # an unbounded walk through slow or unsupported firmware resources.
        deadline = time.monotonic() + 15
        existing = REDFISH_DEADLINE.get()
        token = REDFISH_DEADLINE.set(min(existing, deadline) if existing else deadline)
        try:
            result["nics"] = host_nics(read, system, chassis, ethernet, hardware.lower())
        finally:
            REDFISH_DEADLINE.reset(token)
    return result


def read_server_identity(adapter, address, hardware, credential):
    result = read_device_identity(adapter, address, hardware, credential)
    if result["kind"] != "server":
        raise ValueError("此端点不是物理服务器，不能通过主机装机入口纳管。")
    return result
