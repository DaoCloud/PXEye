"""Typed equipment planning and bounded DHCP operations; no hardware lifecycle RPCs."""

import copy
import csv
import io
import ipaddress
import json
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from pxeye.common import atomic_json, digest, value_id, omit_unset_fields, redact
from pxeye.services.device_identity import (
    chassis_identity as chassis_identity,
    verify_manager_mac as verify_manager_mac,
    read_device_identity,
)

KINDS = {
    "switch": {
        "rpc": "Switch",
        "plural": "switches",
        "serial": "switch_serial_number",
        "id": "expected_switch_id",
        "list": "expected_switches",
    },
    "power_shelf": {
        "rpc": "PowerShelf",
        "plural": "power_shelves",
        "serial": "shelf_serial_number",
        "id": "expected_power_shelf_id",
        "list": "expected_power_shelves",
    },
}
COMMON = [
    "bmc_mac_address",
    "bmc_username",
    "bmc_password",
    "bmc_ip_address",
    "bmc_retain_credentials",
    "metadata",
    "rack_id",
]
FIELDS = {
    kind: ["bmc_mac_address", "bmc_username", "bmc_password", cfg["serial"], *COMMON[3:], cfg["id"]]
    + (
        ["nvos_interfaces", "nvos_ip_address", "nvos_username", "nvos_password"]
        if kind == "switch"
        else []
    )
    for kind, cfg in KINDS.items()
}
LABELS = {
    "server": "服务器",
    "switch": "NVLink 交换机",
    "power_shelf": "供电框",
    "dpu": "DPU",
    "unknown": "待识别",
}
ROLE_LABELS = {
    "host_bmc": "主机 BMC",
    "host": "主机管理 / 引导",
    "dpu_bmc": "DPU BMC",
    "dpu_os": "DPU OS",
    "switch_bmc": "交换机 BMC",
    "nvos": "NVOS",
    "pmc": "PMC",
    "unknown": "未知接口",
}


def snake(value):
    if isinstance(value, dict):
        return {re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower(): snake(v) for k, v in value.items()}
    if isinstance(value, list):
        return [snake(v) for v in value]
    return value


def object_id(value):
    return (value.get("id") or value.get("value")) if isinstance(value, dict) else value


def mac(value):
    value = str(value or "").replace("-", ":").lower()
    if (
        not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", value)
        or int(value[:2], 16) & 1
        or value == "00:00:00:00:00:00"
    ):
        raise ValueError("请输入有效的单播 MAC 地址。")
    return value


def ipv4(value):
    if not isinstance(value, str):
        raise ValueError("地址需要使用 IPv4 文本。")
    return str(ipaddress.IPv4Address(value)) if value else ""


def equipment_id(kind, identity):
    return "eq-" + digest([kind, identity])[:32]


def validate(kind, declaration, previous=None, *, complete=False):
    if (
        kind not in KINDS
        or not isinstance(declaration, dict)
        or set(declaration) - set(FIELDS[kind])
    ):
        raise ValueError("设备类型或原生声明字段无效。")
    cfg, old = KINDS[kind], previous or {}
    row = copy.deepcopy(old) | copy.deepcopy(declaration)
    for key in ("bmc_password", "nvos_password"):
        if not row.get(key) and old.get(key):
            row[key] = old[key]
    for key in ("bmc_mac_address", cfg["serial"]):
        if not isinstance(row.get(key), str) or not row[key].strip():
            raise ValueError("请填写设备 SN 和 BMC / PMC MAC。")
    row["bmc_mac_address"] = mac(row["bmc_mac_address"])
    serial = row[cfg["serial"]].strip()
    if len(serial) > 128 or any(ord(c) < 32 for c in serial):
        raise ValueError("设备 SN 格式无效。")
    row[cfg["serial"]] = serial
    if old and any(
        row.get(key) != old.get(key) for key in ("bmc_mac_address", cfg["serial"], cfg["id"])
    ):
        raise ValueError("已有设备的类型、SN、BMC MAC 和声明 ID 不能通过编辑规划修改。")
    row["bmc_ip_address"] = ipv4(row.get("bmc_ip_address", ""))
    for key in ("rack_id", cfg["id"]):
        if row.get(key):
            row[key] = str(uuid.UUID(value_id(row[key])))
        elif key == cfg["id"]:
            row[key] = str(uuid.uuid4())
        else:
            row.pop(key, None)
    for key in ("bmc_username", "bmc_password", "nvos_username", "nvos_password"):
        limit = 16 if key == "bmc_username" else 20 if key == "bmc_password" else 256
        if key in row and (
            not isinstance(row[key], str)
            or len(row[key]) > limit
            or any(ord(c) < 32 for c in row[key])
        ):
            raise ValueError("账号或密码格式无效。")
    if "bmc_retain_credentials" in row and type(row["bmc_retain_credentials"]) is not bool:
        raise ValueError("保留 BMC 凭据需要布尔值。")
    metadata = row.get("metadata")
    if metadata is not None:
        if not isinstance(metadata, dict) or set(metadata) - {"name", "description", "labels"}:
            raise ValueError("Metadata 只支持 name、description 和 labels。")
        if any(
            not isinstance(metadata.get(k, ""), str) or len(metadata.get(k, "")) > 2048
            for k in ("name", "description")
        ):
            raise ValueError("名称或说明格式无效。")
        labels = metadata.get("labels", [])
        if (
            not isinstance(labels, list)
            or len(labels) > 64
            or any(
                not isinstance(x, dict)
                or set(x) - {"key", "value"}
                or not isinstance(x.get("key"), str)
                or not x["key"]
                or not isinstance(x.get("value", ""), str)
                for x in labels
            )
        ):
            raise ValueError("Metadata labels 格式无效。")
        if len({x["key"] for x in labels}) != len(labels):
            raise ValueError("Metadata label key 不能重复。")
    if kind == "switch":
        ports = row.get("nvos_interfaces", [])
        if not isinstance(ports, list) or len(ports) > 16:
            raise ValueError("NVOS 端口需要使用数组，最多 16 项。")
        seen = {row["bmc_mac_address"]}
        for port in ports:
            if not isinstance(port, dict) or set(port) - {"mac_address", "is_primary"}:
                raise ValueError("NVOS 端口只支持 mac_address 和 is_primary。")
            port["mac_address"] = mac(port.get("mac_address"))
            if port["mac_address"] in seen:
                raise ValueError("BMC 和 NVOS MAC 不能重复。")
            seen.add(port["mac_address"])
            if type(port.get("is_primary", False)) is not bool:
                raise ValueError("NVOS primary 需要布尔值。")
        if len(ports) == 1:
            ports[0]["is_primary"] = True
        if ports and sum(bool(p.get("is_primary")) for p in ports) != 1:
            raise ValueError("请明确选择一个 NVOS primary / eth0 端口。")
        row["nvos_interfaces"] = ports
        row["nvos_ip_address"] = ipv4(row.get("nvos_ip_address", ""))
        if row["nvos_ip_address"] and len(ports) != 1:
            raise ValueError("固定 NVOS IP 仅支持恰好一个已声明 NVOS 管理口。")
        if bool(row.get("nvos_username")) != bool(row.get("nvos_password")):
            raise ValueError("NVOS 用户名和密码必须成对提供；已有密码留空保留。")
        if complete and not ports:
            raise ValueError("接入交换机前至少需要一个 NVOS MAC。")
    if complete and not all(row.get(k) for k in ("bmc_username", "bmc_password")):
        raise ValueError("接入前请提供有效的 BMC / PMC 账号。")
    return row


def normal_native(kind, row):
    row = snake(row)
    result = {k: copy.deepcopy(row[k]) for k in FIELDS[kind] if k in row}
    for key in ("rack_id", KINDS[kind]["id"]):
        if result.get(key):
            result[key] = value_id(result[key])
    return result


def native_payload(kind, row):
    result = omit_unset_fields(copy.deepcopy(row))
    for key in ("rack_id", KINDS[kind]["id"]):
        if result.get(key):
            result[key] = {"value": value_id(result[key])}
    return result


def interfaces_for(kind, row):
    if kind == "server":
        ports = [
            {
                "mac_address": row["bmc_mac_address"].lower(),
                "role": "host_bmc",
                "target_ip": row.get("bmc_ip_address", ""),
            }
        ]
        for port in row.get("interfaces", []):
            if (
                port.get("mac_address")
                and port["mac_address"].lower() != row["bmc_mac_address"].lower()
            ):
                role = port.get("role")
                if type(role) is int and 0 <= role <= 4:
                    role = ["unspecified", "host", "dpu_os", "dpu_bmc", "host_bmc"][role]
                ports.append(
                    {
                        "mac_address": port["mac_address"].lower(),
                        "role": role or "host",
                        "primary": port.get("primary", False),
                        "target_ip": port.get("fixed_ip", ""),
                    }
                )
        return ports
    ports = [
        {
            "mac_address": row.get("bmc_mac_address", "").lower(),
            "role": "switch_bmc" if kind == "switch" else "pmc",
            "target_ip": row.get("bmc_ip_address", ""),
        }
    ]
    if kind == "switch":
        ports += [
            {
                "mac_address": p["mac_address"].lower(),
                "role": "nvos",
                "primary": p.get("is_primary", False),
                "target_ip": row.get("nvos_ip_address", "")
                if len(row.get("nvos_interfaces", [])) == 1
                else "",
            }
            for p in row.get("nvos_interfaces", [])
        ]
    return ports


class Equipment:
    def __init__(self, adapter, resources):
        self.adapter, self.resources, self.store = adapter, resources, resources.store
        self.directory = adapter.data / "config" / "equipment"
        for name in ("plans", "versions", "operations", "proofs", "imports"):
            (self.directory / name).mkdir(mode=0o700, parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def records(self, name):
        return [json.loads(p.read_text()) for p in sorted((self.directory / name).glob("*.json"))]

    def record(self, name, key):
        if not isinstance(key, str) or not re.fullmatch(r"[a-zA-Z0-9-]{1,80}", key):
            raise ValueError("记录 ID 无效。")
        path = self.directory / name / (key + ".json")
        return json.loads(path.read_text()) if path.exists() else {}

    def write(self, name, key, record):
        self.record(name, key)  # Validate the path component before writing.
        atomic_json(self.directory / name / (key + ".json"), record)

    def native(self):
        calls = {}
        for kind, cfg in KINDS.items():
            calls[kind + ":expected"] = (
                "GetAllExpected" + ("Switches" if kind == "switch" else "PowerShelves"),
                cfg["list"],
            )
            calls[kind + ":assets"] = (
                "Find" + ("Switches" if kind == "switch" else "PowerShelves"),
                cfg["plural"],
            )
        result, errors = {}, {}

        def read(item):
            key, (method, field) = item
            try:
                return key, snake(self.adapter.rpc(method, {})).get(field, []), None
            except (RuntimeError, ValueError):
                return key, [], "NICo " + method + " 未能读取；此类型写入已禁用。"

        with ThreadPoolExecutor(max_workers=4) as pool:
            for key, rows, error in pool.map(read, calls.items()):
                result[key] = rows
                if error:
                    errors[key] = error
        return result, errors

    def snapshot(self, servers=None):
        native, errors = self.native()
        links = snake(self.adapter.rpc("FindInterfaces", {})).get("interfaces", [])
        try:
            power_options = snake(self.adapter.rpc("GetPowerOptions", {"machineId": []})).get(
                "response", []
            )
        except (RuntimeError, ValueError, OSError):
            power_options = []
        try:
            machine_ids = self.adapter.rpc("FindMachineIds", {}).get("machineIds", [])
            machines = (
                snake(
                    self.adapter.rpc(
                        "FindMachinesByIds", {"machineIds": machine_ids, "includeHistory": False}
                    )
                ).get("machines", [])
                if machine_ids
                else []
            )
        except (RuntimeError, ValueError, OSError):
            machines = []
        networks = self.resources.networks()
        segments = {n["id"]: n for n in networks}
        servers = self.resources.planned_inventory() if servers is None else servers
        server_declarations = self.resources.inventory()
        plans = self.records("plans")
        items, claimed = [], {}
        for server in servers:
            items.append(
                {
                    "id": "server-"
                    + str(server.get("id") or digest(server["bmc_mac_address"])[:32]),
                    "kind": "server",
                    "serial": server["chassis_serial_number"],
                    "name": (server.get("metadata") or {}).get("name", ""),
                    "legacy_id": server.get("id"),
                    "ports": interfaces_for("server", server),
                    "declaration": {},
                    "status": "server",
                    "rack_id": value_id(server.get("rack_id")),
                }
            )
        for kind, cfg in KINDS.items():
            expected = [normal_native(kind, r) for r in native[kind + ":expected"]]
            assets = [a for a in native[kind + ":assets"] if not a.get("deleted")]
            consumed = set()
            declarations = []
            for plan in [p for p in plans if p["kind"] == kind]:
                row = plan["declaration"]
                current = next(
                    (
                        r
                        for r in expected
                        if value_id(r.get(cfg["id"])) == value_id(row.get(cfg["id"]))
                        or r.get("bmc_mac_address", "").lower() == row["bmc_mac_address"]
                    ),
                    None,
                )
                if current:
                    consumed.add(current["bmc_mac_address"].lower())
                declarations.append((plan["id"], row, plan, current))
            for row in expected:
                if row["bmc_mac_address"].lower() not in consumed:
                    declarations.append(
                        (equipment_id(kind, row["bmc_mac_address"].lower()), row, None, row)
                    )
            asset_ids = set()
            for key, row, plan, current in declarations:
                asset = next(
                    (
                        a
                        for a in assets
                        if (a.get("bmc_info") or {}).get("mac", "").lower()
                        == row["bmc_mac_address"].lower()
                        or any(
                            value_id(
                                link.get("switch_id" if kind == "switch" else "power_shelf_id")
                            )
                            == value_id(a["id"])
                            and link.get("mac_address", "").lower()
                            == row["bmc_mac_address"].lower()
                            for link in links
                        )
                    ),
                    None,
                )
                if asset:
                    asset_ids.add(value_id(asset["id"]))
                item = {
                    "id": key,
                    "kind": kind,
                    "serial": row.get(cfg["serial"], ""),
                    "name": (row.get("metadata") or {}).get("name", ""),
                    "rack_id": value_id(row.get("rack_id")),
                    "declaration": row,
                    "revision": digest(plan) if plan else "",
                    "native_revision": digest(current) if current else "",
                    "native_declaration": current,
                    "native_id": value_id(asset.get("id")) if asset else None,
                    "native_state": (asset.get("status") or {}).get("controller_state")
                    or asset.get("controller_state")
                    if asset
                    else None,
                    "power_state": (asset.get("status") or {}).get("power_state")
                    if asset
                    else None,
                    "ports": interfaces_for(kind, row),
                    "status": "managed" if asset else "declared" if current else "draft",
                }
                items.append(item)
            for asset in assets:
                if value_id(asset["id"]) in asset_ids:
                    continue
                bmc = asset.get("bmc_info") or {}
                row = {"bmc_mac_address": bmc.get("mac", ""), "bmc_ip_address": ""}
                items.append(
                    {
                        "id": equipment_id(kind, value_id(asset["id"])),
                        "kind": kind,
                        "serial": (asset.get("status") or {}).get("serial_number", ""),
                        "name": (asset.get("metadata") or {}).get("name", ""),
                        "native_id": value_id(asset["id"]),
                        "native_state": (asset.get("status") or {}).get("controller_state"),
                        "power_state": (asset.get("status") or {}).get("power_state"),
                        "rack_id": value_id(asset.get("rack_id")),
                        "declaration": {},
                        "revision": "",
                        "ports": interfaces_for(kind, row),
                        "status": "managed",
                        "unplanned": True,
                    }
                )
        for item in items:
            if item["kind"] == "switch" and item.get("native_id"):
                asset = next(
                    (a for a in native["switch:assets"] if value_id(a["id"]) == item["native_id"]),
                    {},
                )
                for port in (asset.get("status") or {}).get("nvos_ports", []):
                    hardware = (port.get("mac") or "").lower()
                    if hardware and not any(p["mac_address"] == hardware for p in item["ports"]):
                        item["ports"].append(
                            {
                                "mac_address": hardware,
                                "role": "nvos",
                                "primary": port.get("is_primary", False),
                                "target_ip": "",
                                "source": "native-port",
                            }
                        )
            item["kind_label"] = LABELS[item["kind"]]
            for port in item["ports"]:
                # MAC text is case-insensitive. Keep a single canonical key for
                # declarations, Core observations and ownership lookups.
                port["mac_address"] = port.get("mac_address", "").lower()
                for path in (self.adapter.data / "config" / "management-addresses" / "plans").glob(
                    "*.json"
                ):
                    address_plan = json.loads(path.read_text())
                    if address_plan.get("mac_address", "").lower() == port[
                        "mac_address"
                    ] and not address_plan.get("target_from_device_plan"):
                        port["target_ip"] = address_plan["target_ip"]
                matches = [
                    link
                    for link in links
                    if link.get("mac_address", "").lower() == port["mac_address"]
                ]
                port["observed"] = [self.observed(link, segments) for link in matches]
                port["role_label"] = ROLE_LABELS.get(port["role"], port["role"])
                if port["mac_address"]:
                    claimed.setdefault(port["mac_address"], []).append((item, port))
            if item["kind"] == "server":
                machine_ids = {
                    row.get("machine_id")
                    for port in item["ports"]
                    for row in port.get("observed", [])
                    if row.get("machine_id")
                }
                bmc_macs = {
                    port.get("mac_address", "").lower()
                    for port in item["ports"]
                    if port.get("role") == "host_bmc"
                }
                machine_ids.update(
                    object_id(machine.get("id"))
                    for machine in machines
                    if (machine.get("bmc") or machine.get("bmc_info") or {}).get("mac", "").lower()
                    in bmc_macs
                )
                machine_ids.discard(None)
                options = [
                    row for row in power_options if object_id(row.get("host_id")) in machine_ids
                ]
                if len(options) == 1:
                    # Proto JSON omits enum zero; PowerState.On is zero in this NICo version.
                    item["power_state"] = options[0].get("actual_state", "on")
                    item["power_state_updated_at"] = options[0].get("actual_state_updated_at")
        allocations = []
        for link in links:
            entry = self.observed(link, segments)
            owners = claimed.get(entry["mac_address"], [])
            if len(owners) == 1:
                item, port = owners[0]
                entry.update(
                    device_id=item["id"],
                    kind=item["kind"],
                    serial=item["serial"],
                    role=port["role"],
                    role_label=port["role_label"],
                    target_ip=port.get("target_ip", ""),
                    plan_revision=item.get("revision", ""),
                    declaration_revision=item.get("native_revision", ""),
                )
            else:
                switch_id, shelf_id = (
                    value_id(link.get("switch_id")),
                    value_id(link.get("power_shelf_id")),
                )
                associated = next(
                    (
                        i
                        for i in items
                        if i.get("native_id") and i["native_id"] in (switch_id, shelf_id)
                    ),
                    None,
                )
                entry.update(
                    device_id=associated["id"] if associated else None,
                    kind=associated["kind"]
                    if associated
                    else "dpu"
                    if link.get("attached_dpu_machine_id")
                    else "server"
                    if link.get("machine_id")
                    else "unknown",
                    serial=associated["serial"] if associated else "",
                    role="unknown",
                    role_label="未知接口",
                    identity_conflict=len(owners) > 1,
                )
            entry["observation"] = digest(link)
            allocations.append(entry)
        return {
            "items": items,
            "allocations": allocations,
            "networks": networks,
            "errors": errors,
            "native": native,
            "links": links,
            "servers": servers,
            "server_declarations": server_declarations,
            "observed_at": time.time(),
        }

    @staticmethod
    def observed(link, segments):
        sid = value_id(link.get("segment_id"))
        segment = segments.get(sid, {})
        return {
            "interface_id": value_id(link.get("id")),
            "mac_address": link.get("mac_address", "").lower(),
            "addresses": link.get("address", []),
            "network_id": sid,
            "network_name": segment.get("name", ""),
            "network_allocation_strategy": segment.get("allocation_strategy", "UNKNOWN"),
            "network_prefixes": [
                p.get("prefix", "") for p in segment.get("prefixes", []) if p.get("prefix")
            ],
            "segment_type": segment.get("segment_type"),
            "last_dhcp": link.get("last_dhcp"),
            "machine_id": value_id(link.get("machine_id")),
            "dpu_machine_id": value_id(link.get("attached_dpu_machine_id")),
            "switch_id": value_id(link.get("switch_id")),
            "power_shelf_id": value_id(link.get("power_shelf_id")),
            "allocation_type": "待查询",
        }

    def view(self, snapshot=None):
        snapshot = snapshot or self.snapshot()
        items = []
        for item in snapshot["items"]:
            row = copy.deepcopy(item)
            declaration = row.pop("declaration", {})
            row.pop("native_declaration", None)
            row["declaration"] = redact(declaration)
            row["credential_present"] = bool(declaration.get("bmc_password"))
            row["nvos_credential_present"] = bool(declaration.get("nvos_password"))
            row["can_sync"] = (
                item["kind"] in KINDS
                and not item.get("unplanned")
                and not item.get("address_only")
                and not any(k.startswith(item["kind"] + ":") for k in snapshot["errors"])
            )
            items.append(row)
        endpoints = [
            a
            for a in snapshot["allocations"]
            if a["segment_type"] == "UNDERLAY" and a["network_name"] != "static-assignments"
        ]
        return {
            "devices": items,
            "endpoints": endpoints,
            "observed_at": snapshot["observed_at"],
            "operations": redact(self.records("operations")),
            "errors": list(snapshot["errors"].values()),
            "site_explorer": self.explorer_settings(),
        }

    def explorer_settings(self):
        settings = self.adapter.config.get("site_explorer_settings", {})
        return {
            "source": "UI站点配置记录，非本次Core动态读回",
            "create_switches": settings.get("create_switches"),
            "create_power_shelves": settings.get("create_power_shelves"),
            "note": "原生两类自动接入开关源码默认开启；同步声明可能启动探索、凭据和初始化流程。",
        }

    def item(self, key, snapshot=None):
        snapshot = snapshot or self.snapshot()
        found = next((x for x in snapshot["items"] if x["id"] == key), None)
        if not found or found["kind"] not in KINDS or found.get("unplanned"):
            raise ValueError("请选择有类型声明的交换机或供电框。")
        return found

    def check_conflicts(self, candidates, snapshot, replaced=()):
        """One ownership check across local plans, native declarations and observed interfaces."""
        rows = [x for x in snapshot["items"] if x["id"] not in replaced] + candidates
        macs, addresses, identities = {}, {}, {}
        for item in rows:
            identity = (item["kind"], item["serial"])
            if identity in identities and identities[identity] != item["id"]:
                raise ValueError("同类型设备 SN 重复，请使用原记录编辑。")
            identities[identity] = item["id"]
            for port in item["ports"]:
                address = port.get("target_ip") or ""
                hardware = port["mac_address"].lower()
                if hardware in macs and macs[hardware] != item["id"]:
                    raise ValueError("MAC 已归属于另一台设备。")
                if hardware:
                    macs[hardware] = item["id"]
                if address:
                    if address in addresses and addresses[address] != hardware:
                        raise ValueError("目标 IP 已分配给另一管理接口。")
                    addresses[address] = hardware
        for link in snapshot["allocations"]:
            hardware = link["mac_address"]
            for address in link["addresses"]:
                if address in addresses and addresses[address] != hardware:
                    raise ValueError("目标 IP 已被其他 Core 接口占用。")
            if hardware in macs:
                owner = macs[hardware]
                item = next(x for x in rows if x["id"] == owner)
                if item["kind"] in KINDS and (
                    link.get("machine_id")
                    or link["kind"] == "dpu"
                    or link.get("identity_conflict")
                    or (link.get("device_id") and link["device_id"] != owner)
                ):
                    raise ValueError("接口原生资产关系与申报设备冲突。")
        for server in snapshot["server_declarations"]:
            for port in interfaces_for("server", server):
                hardware = port["mac_address"].lower()
                owner = macs.get(hardware)
                if owner:
                    item = next(x for x in rows if x["id"] == owner)
                    if (
                        item["kind"] != "server"
                        or item["serial"] != server["chassis_serial_number"]
                    ):
                        raise ValueError("MAC 已存在于另一原生服务器声明。")
                address = port.get("target_ip")
                if address and address in addresses and addresses[address] != hardware:
                    raise ValueError("目标 IP 已存在于另一原生服务器接口声明。")
        for path in (self.adapter.data / "config" / "management-addresses" / "plans").glob(
            "*.json"
        ):
            plan = json.loads(path.read_text())
            target = plan.get("target_ip")
            if target and target in addresses and addresses[target] != plan["mac_address"]:
                raise ValueError("目标 IP 已存在于管理接口地址规划。")

    def prepare(self, body, snapshot):
        if set(body) - {"id", "kind", "revision", "native_revision", "declaration", "bindings"}:
            raise ValueError("规划字段无效。")
        kind = body.get("kind")
        if kind not in KINDS:
            raise ValueError("此入口仅支持 NVLink 交换机和供电框。")
        old = self.item(body["id"], snapshot) if body.get("id") else None
        if old and (
            old["kind"] != kind
            or body.get("revision", "") != old.get("revision", "")
            or body.get("native_revision", "") != old.get("native_revision", "")
        ):
            raise ValueError("设备或原生声明已变化，请刷新后编辑。")
        declaration = validate(
            kind, body.get("declaration"), old.get("declaration") if old else None
        )
        if old:
            for path in (self.adapter.data / "config" / "management-addresses" / "plans").glob(
                "*.json"
            ):
                address_plan = json.loads(path.read_text())
                if any(p["mac_address"] == address_plan["mac_address"] for p in old["ports"]):
                    if any(
                        declaration.get(key) != old["declaration"].get(key)
                        for key in ("bmc_ip_address", "nvos_ip_address")
                    ):
                        raise ValueError("已有接口地址规划，请从管理地址入口修改目标 IP。")
        key = old["id"] if old else equipment_id(kind, declaration["bmc_mac_address"])
        if self.pending(key):
            raise ValueError("设备有未完成管理操作，请先查看进度并核对。")
        if not old and any(
            i["id"] == key
            or i["kind"] == kind
            and i.get("declaration", {}).get("bmc_mac_address", "").lower()
            == declaration["bmc_mac_address"]
            for i in snapshot["items"]
        ):
            raise ValueError("此 MAC 已有设备记录，请从原记录编辑并核对规划版本。")
        ports = interfaces_for(kind, declaration)
        previous = self.record("plans", key)
        bindings = copy.deepcopy(body.get("bindings", previous.get("bindings", {})))
        if not isinstance(bindings, dict) or set(bindings) - {p["mac_address"] for p in ports}:
            raise ValueError("网络引用必须对应本设备已申报的接口 MAC。")
        networks = {n["id"]: n for n in snapshot["networks"]}
        for port in ports:
            sid = bindings.get(port["mac_address"])
            if not sid:
                continue
            network = networks.get(sid)
            if (
                not network
                or network["segment_type"] != "UNDERLAY"
                or network["name"] == "static-assignments"
            ):
                raise ValueError("BMC、PMC 和 NVOS 需关联有效 Underlay 网络。")
            if port["target_ip"] and not any(
                ipaddress.ip_address(port["target_ip"]) in ipaddress.ip_network(p["prefix"])
                for p in network["prefixes"]
            ):
                raise ValueError("目标地址不属于选定网络。")
        return {
            "id": key,
            "kind": kind,
            "serial": declaration[KINDS[kind]["serial"]],
            "ports": ports,
            "declaration": declaration,
            "bindings": bindings,
            "updated_at": time.time(),
        }

    def persist(self, plan):
        version = digest(plan)
        self.write("versions", plan["id"] + "-" + version[:16], plan)
        self.write("plans", plan["id"], plan)
        return {"id": plan["id"], "revision": version, "status": "draft"}

    def save(self, body):
        with self.lock:
            snapshot = self.snapshot()
            if snapshot["errors"]:
                raise ValueError("原生类型声明未完整读取，暂不能安全核对跨类型冲突。")
            plan = self.prepare(body, snapshot)
            self.check_conflicts([plan], snapshot, [plan["id"]])
            return self.persist(plan)

    def address_types(self, endpoints):
        def read(endpoint):
            row = copy.deepcopy(endpoint)
            try:
                result = snake(
                    self.adapter.rpc(
                        "FindInterfaceAddresses", {"interface_id": {"value": row["interface_id"]}}
                    )
                )
                row["address_allocations"] = result.get("addresses", [])
                row["allocation_type"] = (
                    ", ".join(
                        sorted(
                            {a.get("allocation_type", "未知") for a in result.get("addresses", [])}
                        )
                    )
                    or "无分配"
                )
            except (ValueError, RuntimeError):
                row["allocation_type"] = "读取失败"
                row["address_allocations"] = []
            return row

        with ThreadPoolExecutor(max_workers=4) as pool:
            return list(pool.map(read, endpoints))

    def allocations(self, network_id):
        snapshot = self.snapshot()
        if not any(n["id"] == network_id for n in snapshot["networks"]):
            raise ValueError("子网不存在。")
        return {
            "allocations": self.address_types(
                [a for a in snapshot["allocations"] if a["network_id"] == network_id]
            ),
            "observed_at": snapshot["observed_at"],
        }

    def detail(self, key):
        snapshot = self.snapshot()
        item = next((x for x in snapshot["items"] if x["id"] == key and x["kind"] in KINDS), None)
        if item is None:
            raise ValueError("设备不存在。")
        result = copy.deepcopy(item)
        result["credential_present"] = bool(item["declaration"].get("bmc_password"))
        result["nvos_credential_present"] = bool(item["declaration"].get("nvos_password"))
        result["bindings"] = self.record("plans", key).get("bindings", {})
        result["allocations"] = self.address_types(
            [a for a in snapshot["allocations"] if a.get("device_id") == key]
        )
        result["operations"] = [
            o
            for o in self.records("operations")
            if o.get("device_id") == key or o.get("equipment_id") == key
        ]
        result["proofs"] = [p for p in self.records("proofs") if p.get("device_id") == key]
        result["site_explorer"] = self.explorer_settings()
        result["errors"] = list(snapshot["errors"].values())
        return redact(result)

    @staticmethod
    def template(kind):
        if kind not in KINDS:
            raise ValueError("模板类型无效。")
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=FIELDS[kind])
        writer.writeheader()
        example = {
            "bmc_mac_address": "02:00:00:00:00:20",
            KINDS[kind]["serial"]: "REPLACE-SERIAL",
            "bmc_username": "",
            "bmc_password": "",
            "bmc_retain_credentials": "true",
            "metadata": json.dumps({"name": "replace-name", "labels": []}),
        }
        if kind == "switch":
            example["nvos_interfaces"] = json.dumps(
                [{"mac_address": "02:00:00:00:00:21", "is_primary": True}]
            )
        writer.writerow(example)
        return stream.getvalue()

    def import_preview(self, body, owner):
        kind, text = body.get("kind"), body.get("csv")
        if kind not in KINDS or not isinstance(text, str):
            raise ValueError("请选择类型并提交 CSV。")
        reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
        if (
            not reader.fieldnames
            or len(set(reader.fieldnames)) != len(reader.fieldnames)
            or set(reader.fieldnames) - set(FIELDS[kind])
        ):
            raise ValueError("CSV 表头不匹配该类型原生字段。")
        with self.lock:
            snapshot = self.snapshot()
            if snapshot["errors"]:
                raise ValueError("原生声明读取失败，不能核对导入冲突。")
            plans, revisions, seen = [], {}, set()
            for line, raw in enumerate(reader, 2):
                if len(plans) >= 50 or None in raw or any(v is None for v in raw.values()):
                    raise ValueError("CSV 每次最多 50 行，列数需与表头一致。")
                try:
                    row = {
                        k: v if k in ("bmc_password", "nvos_password") else v.strip()
                        for k, v in raw.items()
                        if v != "" and (k in ("bmc_password", "nvos_password") or v.strip())
                    }
                    for key in ("metadata", "nvos_interfaces", "bmc_retain_credentials"):
                        if key in row:
                            row[key] = json.loads(row[key])
                    hardware = mac(row.get("bmc_mac_address"))
                    old = next(
                        (
                            i
                            for i in snapshot["items"]
                            if i["kind"] == kind
                            and i.get("declaration", {}).get("bmc_mac_address", "").lower()
                            == hardware
                        ),
                        None,
                    )
                    request = {"kind": kind, "declaration": row}
                    if old:
                        request.update(
                            id=old["id"],
                            revision=old["revision"],
                            native_revision=old["native_revision"],
                        )
                    plan = self.prepare(request, snapshot)
                    if plan["id"] in seen:
                        raise ValueError("同一设备重复出现。")
                    seen.add(plan["id"])
                    revisions[plan["id"]] = (
                        [old.get("revision", ""), old.get("native_revision", "")] if old else None
                    )
                    plans.append(plan)
                except (ValueError, TypeError, KeyError):
                    raise ValueError(
                        "第 " + str(line) + " 行格式、身份或网络校验失败；请检查该行。"
                    ) from None
            if not plans:
                raise ValueError("CSV 没有设备行。")
            self.check_conflicts(plans, snapshot, seen)
            token = str(uuid.uuid4())
            self.write(
                "imports",
                token,
                {
                    "owner": owner,
                    "expires": time.time() + 900,
                    "plans": plans,
                    "revisions": revisions,
                },
            )
            return {
                "id": token,
                "devices": [
                    {
                        "id": p["id"],
                        "kind": kind,
                        "serial": p["serial"],
                        "declaration": redact(p["declaration"]),
                    }
                    for p in plans
                ],
                "note": "确认后仅保存本地规划；原生接入需逐台另行确认。",
            }

    def import_apply(self, body, owner):
        with self.lock:
            preview = self.record("imports", body.get("id"))
            if (
                not preview
                or preview.get("owner") != owner
                or preview.get("expires", 0) < time.time()
                or preview.get("used")
            ):
                raise ValueError("导入预览已失效或已提交。")
            snapshot = self.snapshot()
            if snapshot["errors"]:
                raise ValueError("原生声明读取失败。")
            current = {
                i["id"]: [i.get("revision", ""), i.get("native_revision", "")]
                for i in snapshot["items"]
            }
            if any(current.get(k) != v for k, v in preview["revisions"].items()):
                raise ValueError("规划已变化，请重新预览导入。")
            self.check_conflicts(preview["plans"], snapshot, preview["revisions"])
            preview.update(used=True, results=[])
            self.write("imports", body["id"], preview)
            # Keep each completed result if a filesystem error interrupts a multi-row import.
            for plan in preview["plans"]:
                preview["results"].append(self.persist(plan))
                self.write("imports", body["id"], preview)
            return {"results": preview["results"], "status": "saved"}

    def create_check(self, action, owner, data):
        token = str(uuid.uuid4())
        self.store.preflight(token, {"equipment_action": action, "owner": owner, **data})
        return token

    def claim_check(self, token, action, owner):
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM preflights WHERE id=?", (token,)).fetchone()
            if not row or row["used"] or row["expires"] < time.time():
                raise ValueError("操作预览已失效或已提交，请重新读取现状。")
            check = json.loads(row["data"])
            if check.get("equipment_action") != action or check.get("owner") != owner:
                raise ValueError("操作预览与会话不匹配。")
            db.execute("UPDATE preflights SET used=1 WHERE id=?", (token,))
            return check

    def pending(self, key):
        from pxeye.services.addresses import STATES

        for path in (self.adapter.data / "config" / "management-addresses" / "operations").glob(
            "*.json"
        ):
            operation = json.loads(path.read_text())
            if operation.get("device_id") == key and operation.get("status") in STATES:
                return True
        return any(
            o.get("device_id") == key and o.get("status") in ("requesting", "needs_attention")
            for o in self.records("operations")
        )

    def sync_context(self, key):
        snapshot = self.snapshot()
        item = self.item(key, snapshot)
        if snapshot["errors"] or self.pending(key):
            raise ValueError("原生能力读取失败或上次写入结果待核对；请先刷新记录。")
        declaration = copy.deepcopy(item["declaration"])
        for port in item["ports"]:
            if port["role"] in ("switch_bmc", "pmc"):
                declaration["bmc_ip_address"] = port.get("target_ip", "")
            elif port["role"] == "nvos" and len(declaration.get("nvos_interfaces", [])) == 1:
                declaration["nvos_ip_address"] = port.get("target_ip", "")
        row = validate(item["kind"], declaration, complete=True)
        self.check_conflicts([item], snapshot, [key])
        bindings = self.record("plans", key).get("bindings", {})
        for port in item["ports"]:
            target = port.get("target_ip")
            if not target:
                continue
            address = ipaddress.IPv4Address(target)
            matches = [
                (n, p)
                for n in snapshot["networks"]
                if n["segment_type"] == "UNDERLAY" and n["name"] != "static-assignments"
                for p in n["prefixes"]
                if address.version == ipaddress.ip_network(p["prefix"]).version
                and address in ipaddress.ip_network(p["prefix"])
            ]
            if len(matches) != 1 or bindings.get(port["mac_address"]) not in (
                None,
                "",
                matches[0][0]["id"],
            ):
                raise ValueError("接入前目标 IP 必须唯一匹配已生效的 Underlay 网络及接口引用。")
            prefix = ipaddress.ip_network(matches[0][1]["prefix"])
            if address in (prefix.network_address, prefix.broadcast_address) or target == matches[
                0
            ][1].get("gateway"):
                raise ValueError("目标管理地址不能使用网段、广播或网关地址。")
        # A local declaration cannot reuse a native ID owned by a different MAC.
        cfg = KINDS[item["kind"]]
        expected = [
            normal_native(item["kind"], r) for r in snapshot["native"][item["kind"] + ":expected"]
        ]
        if any(
            value_id(r.get(cfg["id"])) == value_id(row[cfg["id"]])
            and r["bmc_mac_address"].lower() != row["bmc_mac_address"]
            for r in expected
        ):
            raise ValueError("原生声明 ID 已归属于另一 MAC。")
        return snapshot, item, row

    def sync_preview(self, body, owner):
        with self.lock:
            snapshot, item, row = self.sync_context(body.get("id"))
            token = self.create_check(
                "sync",
                owner,
                {
                    "device_id": item["id"],
                    "revision": item["revision"],
                    "native_revision": item["native_revision"],
                    "declaration": row,
                    "site_settings": digest(self.explorer_settings()),
                },
            )
            return {
                "id": token,
                "serial": item["serial"],
                "kind": item["kind"],
                "declaration": redact(row),
                "current_declaration": redact(item.get("native_declaration")),
                "operation": "Patch" if item.get("native_declaration") else "Add",
                "site_explorer": self.explorer_settings(),
                "effect": "声明同步后可能启动原生探索、凭据处理及设备管理；不保证仅分配地址。已有分配不会因修改声明自动迁移。",
            }

    @staticmethod
    def equivalent(actual, desired, fields):
        for key in fields:
            a, b = actual.get(key), desired.get(key)
            if key in ("metadata", "nvos_interfaces"):
                a = a or ({} if key == "metadata" else [])
                b = b or ({} if key == "metadata" else [])
                if key == "metadata":
                    a = {k: v for k, v in a.items() if v}
                    b = {k: v for k, v in b.items() if v}
                    for metadata in (a, b):
                        if metadata.get("labels"):
                            metadata["labels"] = sorted(
                                [
                                    {"key": x["key"], "value": x.get("value", "")}
                                    for x in metadata["labels"]
                                ],
                                key=lambda x: x["key"],
                            )
                else:
                    a = sorted(
                        [
                            {
                                "mac_address": p["mac_address"].lower(),
                                "is_primary": bool(p.get("is_primary")),
                            }
                            for p in a
                        ],
                        key=lambda x: x["mac_address"],
                    )
                    b = sorted(
                        [
                            {
                                "mac_address": p["mac_address"].lower(),
                                "is_primary": bool(p.get("is_primary")),
                            }
                            for p in b
                        ],
                        key=lambda x: x["mac_address"],
                    )
            elif a is None or b is None:
                a, b = a or "", b or ""
            if a != b:
                return False
        return True

    def sync_apply(self, body, owner, actor):
        with self.lock:
            check = self.claim_check(body.get("preflight_id"), "sync", owner)
            snapshot, item, row = self.sync_context(check["device_id"])
            if (
                body.get("confirm_serial") != item["serial"]
                or body.get("confirm_management") is not True
            ):
                raise ValueError("请核对 SN 并确认接入原生设备管理范围。")
            if [item["revision"], item["native_revision"], row] != [
                check["revision"],
                check["native_revision"],
                check["declaration"],
            ]:
                raise ValueError("设备规划或原生声明已变化，请重新预览。")
            if check["site_settings"] != digest(self.explorer_settings()):
                raise ValueError("站点接入配置记录已变化，请重新确认管理范围。")
            cfg = KINDS[item["kind"]]
            current = item.get("native_declaration")
            fields = [
                k
                for k in set(row) | ({"rack_id"} if current and current.get("rack_id") else set())
                if k not in ("bmc_mac_address", cfg["id"])
                and (not current or not self.equivalent(current, row, [k]))
            ]
            if current and not fields:
                return {"status": "synced", "detail": "声明已一致；本次没有写入。"}
            payload = native_payload(
                item["kind"],
                row
                if not current
                else {cfg["id"]: row[cfg["id"]], **{k: row.get(k) for k in fields}},
            )
            if not current:
                for optional in ("nvos_username", "nvos_password", "nvos_ip_address"):
                    if not payload.get(optional):
                        payload.pop(optional, None)
            if current:
                paths = [
                    path
                    for k in fields
                    for path in (
                        ["metadata.name", "metadata.description", "metadata.labels"]
                        if k == "metadata"
                        else [k]
                    )
                ]
                payload = {
                    "expected_"
                    + ("switch" if item["kind"] == "switch" else "power_shelf"): payload,
                    "update_mask": {"paths": paths},
                }
            operation = {
                "id": str(uuid.uuid4()),
                "action": "sync",
                "device_id": item["id"],
                "kind": item["kind"],
                "serial": item["serial"],
                "actor": actor,
                "created_at": time.time(),
                "status": "requesting",
                "request": row,
                "baseline": item.get("native_declaration"),
                "fields": sorted(set(fields) | {"bmc_mac_address", cfg["id"], cfg["serial"]}),
            }
            self.write("operations", operation["id"], operation)
            try:
                self.adapter.rpc(
                    ("PatchExpected" if current else "AddExpected") + cfg["rpc"], payload
                )
                operation["response_received"] = True
            except (RuntimeError, ValueError):
                operation["response_received"] = False
            operation["status"] = "needs_attention"
            self.write("operations", operation["id"], operation)
            return self.reconcile({"id": operation["id"]}, actor)

    def pin_context(self, interface_id):
        from pxeye.services.addresses import STATES

        for path in (self.adapter.data / "config" / "management-addresses" / "operations").glob(
            "*.json"
        ):
            operation = json.loads(path.read_text())
            if operation.get("interface_id") == interface_id and operation.get("status") in STATES:
                raise ValueError("接口有未完成的管理地址操作，请先核对。")
        snapshot = self.snapshot()
        if snapshot["errors"]:
            raise ValueError("类型声明读取不完整，暂不能安全核对接口目标。")
        row = next((a for a in snapshot["allocations"] if a["interface_id"] == interface_id), None)
        if (
            not row
            or row["segment_type"] != "UNDERLAY"
            or row["network_name"] == "static-assignments"
        ):
            raise ValueError("仅支持当前 Underlay 管理接口。")
        if (
            row["kind"] in ("server", "dpu")
            or row.get("machine_id")
            or row.get("dpu_machine_id")
            or row.get("identity_conflict")
        ):
            raise ValueError("主机和 DPU 请使用现有设备规划入口；冲突接口不能操作。")
        if len(row["addresses"]) != 1 or ipaddress.ip_address(row["addresses"][0]).version != 4:
            raise ValueError("仅支持已有唯一 IPv4 的接口。")
        if self.pending("interface-" + interface_id):
            raise ValueError("上次地址操作结果待核对。")
        if any(
            a["interface_id"] != interface_id and row["addresses"][0] in a["addresses"]
            for a in snapshot["allocations"]
        ):
            raise ValueError("当前 IP 存在跨接口冲突。")
        if row.get("target_ip") and row["target_ip"] != row["addresses"][0]:
            raise ValueError("规划与当前地址不同；本期不支持地址迁移。")
        return row

    def pin_preview(self, body, owner):
        with self.lock:
            row = self.pin_context(body.get("interface_id"))
            token = self.create_check("pin", owner, {"interface": row})
            return {
                "id": token,
                "interface": row,
                "effect": "仅将当前同一 IP 固定为 Static；不创建 Expected 声明，不认证设备身份。",
            }

    def pin_apply(self, body, owner, actor):
        with self.lock:
            check = self.claim_check(body.get("preflight_id"), "pin", owner)
            if body.get("confirm_same_ip") is not True:
                raise ValueError("请确认仅固定当前地址。")
            row = self.pin_context(check["interface"]["interface_id"])
            if row != check["interface"]:
                raise ValueError("接口、地址或规划已变化，请重新预览。")
            operation = {
                "id": str(uuid.uuid4()),
                "action": "pin",
                "device_id": "interface-" + row["interface_id"],
                "equipment_id": row.get("device_id"),
                "actor": actor,
                "created_at": time.time(),
                "status": "requesting",
                "interface": row,
            }
            self.write("operations", operation["id"], operation)
            try:
                self.adapter.rpc(
                    "AssignStaticAddress",
                    {
                        "interface_id": {"value": row["interface_id"]},
                        "ip_address": row["addresses"][0],
                    },
                )
                operation["response_received"] = True
            except (ValueError, RuntimeError):
                operation["response_received"] = False
            operation["status"] = "needs_attention"
            self.write("operations", operation["id"], operation)
            return self.reconcile({"id": operation["id"]}, actor)

    def reconcile(self, body, actor):
        with self.lock:
            operation = self.record("operations", body.get("id"))
            if not operation:
                raise ValueError("操作记录不存在。")
            try:
                if operation["action"] == "sync":
                    native, errors = self.native()
                    kind, desired = operation["kind"], operation["request"]
                    cfg = KINDS[kind]
                    actual = next(
                        (
                            normal_native(kind, r)
                            for r in native[kind + ":expected"]
                            if value_id(r.get(cfg["id"])) == desired[cfg["id"]]
                        ),
                        None,
                    )
                    passed = (
                        not errors
                        and actual
                        and self.equivalent(actual, desired, operation["fields"])
                    )
                else:
                    row = operation["interface"]
                    links = snake(self.adapter.rpc("FindInterfaces", {})).get("interfaces", [])
                    link = next(
                        (x for x in links if value_id(x.get("id")) == row["interface_id"]), {}
                    )
                    addresses = snake(
                        self.adapter.rpc(
                            "FindInterfaceAddresses",
                            {"interface_id": {"value": row["interface_id"]}},
                        )
                    ).get("addresses", [])
                    passed = (
                        link.get("mac_address", "").lower() == row["mac_address"]
                        and value_id(link.get("segment_id")) == row["network_id"]
                        and link.get("address", []) == row["addresses"]
                        and any(
                            a.get("address") == row["addresses"][0]
                            and str(a.get("allocation_type", "")).lower() == "static"
                            for a in addresses
                        )
                    )
                operation["status"] = (
                    "synced"
                    if passed and operation["action"] == "sync"
                    else "reserved"
                    if passed
                    else "needs_attention"
                )
            except (ValueError, RuntimeError):
                operation["status"] = "needs_attention"
            operation.update(checked_at=time.time(), checked_by=actor)
            self.write("operations", operation["id"], operation)
            return {
                "id": operation["id"],
                "status": operation["status"],
                "detail": "已完成原生读回；实际 DHCP 与硬件身份需独立核对。"
                if operation["status"] != "needs_attention"
                else "请求结果尚不能确认；保留现场，请核对原生记录，不要重复提交。",
            }

    def validate_server_plans(self, records, *, snapshot=None):
        snapshot = self.snapshot(servers=[]) if snapshot is None else snapshot
        if snapshot["errors"]:
            raise ValueError("类型声明读取失败，无法完整核对设备冲突。")
        candidates = [
            {
                "id": "server-" + serial,
                "kind": "server",
                "serial": serial,
                "ports": interfaces_for("server", r["machine"]),
            }
            for serial, r in records.items()
        ]
        self.check_conflicts(candidates, snapshot)

    def validate_server_import(self, incoming):
        records = {r["chassis_serial_number"]: {"machine": r} for r in self.resources.inventory()}
        for row in self.resources.planned_inventory() + incoming:
            serial = row["chassis_serial_number"]
            records[serial] = {"machine": records.get(serial, {}).get("machine", {}) | row}
        self.validate_server_plans(records)

    def identify(self, body, owner):
        """Authenticate a bounded, already observed endpoint, never scan a network."""
        credential = self.identity_credential(body)
        snapshot = self.snapshot()
        return self.identify_observed(body, owner, credential, snapshot)

    @staticmethod
    def identity_credential(body):
        credential = {"username": body.get("username"), "password": body.get("password")}
        if not all(
            isinstance(v, str) and 1 <= len(v) <= limit
            for v, limit in [(credential["username"], 16), (credential["password"], 20)]
        ):
            raise ValueError("请输入 BMC 账号（最多16字符）和密码（最多20字符）。")
        return credential

    def identify_many(self, body, owner):
        """Read selected discovery endpoints with one credential and bounded concurrency."""
        rows = body.get("endpoints")
        if (
            set(body) != {"endpoints", "username", "password"}
            or not isinstance(rows, list)
            or not 1 <= len(rows) <= 50
            or any(
                not isinstance(row, dict)
                or set(row) != {"interface_id", "ip"}
                or not isinstance(row["interface_id"], str)
                or not isinstance(row["ip"], str)
                for row in rows
            )
            or len({row["interface_id"] for row in rows}) != len(rows)
        ):
            raise ValueError("请选择 1–50 个不重复的发现端点及其临时 IPv4。")
        credential = self.identity_credential(body)
        snapshot = self.snapshot()
        if snapshot["errors"]:
            raise ValueError("设备和接口读取不完整，请刷新发现结果后重试。")

        def read(row):
            try:
                result = self.identify_observed(
                    row, owner, credential, snapshot, discovery_only=True
                )
                return {**row, "passed": True, **result}
            except (ValueError, RuntimeError) as error:
                return {
                    **row,
                    "passed": False,
                    "detail": str(error).replace(credential["password"], "[已隐藏]"),
                }

        with ThreadPoolExecutor(max_workers=4) as pool:
            return {"rows": list(pool.map(read, rows))}

    def identify_observed(self, body, owner, credential, snapshot, *, discovery_only=False):
        endpoint = next(
            (a for a in snapshot["allocations"] if a["interface_id"] == body.get("interface_id")),
            None,
        )
        if (
            not endpoint
            or endpoint["segment_type"] != "UNDERLAY"
            or endpoint["network_name"] == "static-assignments"
        ):
            raise ValueError("请选择已观察的 Underlay 管理端点。")
        if (
            endpoint.get("identity_conflict")
            or endpoint["kind"] == "dpu"
            or endpoint.get("role") in ("nvos", "host")
        ):
            raise ValueError("此接口不是支持的 BMC / PMC 身份读取入口。")
        if discovery_only and (
            not endpoint.get("last_dhcp")
            or any(
                endpoint.get(k)
                for k in (
                    "device_id",
                    "machine_id",
                    "dpu_machine_id",
                    "switch_id",
                    "power_shelf_id",
                )
            )
        ):
            raise ValueError("发现端点已纳管或归属已变化，请刷新列表。")
        address = ipv4(body.get("ip", ""))
        if not address or address not in endpoint["addresses"]:
            raise ValueError("待验证 IPv4 不属于此端点。")
        identity = read_device_identity(self.adapter, address, endpoint["mac_address"], credential)
        if endpoint["kind"] not in ("unknown", identity["kind"]):
            raise ValueError("硬件类型与现有声明或原生关联冲突。")
        if endpoint.get("serial") and identity["serial"] != endpoint["serial"]:
            raise ValueError("硬件 SN 与已申报 SN 不符。")
        token = str(uuid.uuid4())
        proof = {
            "id": token,
            "device_id": endpoint.get("device_id"),
            "owner": owner,
            "interface": endpoint,
            "credentials": credential,
            "identity": identity,
            "verified_at": time.time(),
            "verified_ip": address,
            "tls_verification": "HTTPS；按站点BMC证书策略",
            "used": False,
        }
        self.write("proofs", token, proof)
        return {
            "id": token,
            "identity": identity,
            "verified_at": proof["verified_at"],
            "device_id": endpoint.get("device_id"),
            "can_enroll": identity["kind"] in ("server", *KINDS)
            and not any(
                endpoint.get(k)
                for k in (
                    "device_id",
                    "machine_id",
                    "dpu_machine_id",
                    "switch_id",
                    "power_shelf_id",
                )
            ),
            "note": "身份仅对本次地址、MAC 和观察快照有效；不代表原生纳管完成。",
        }

    def enroll(self, body, owner, discovery, actor):
        with self.lock:
            proof = self.record("proofs", body.get("id"))
            if (
                not proof
                or proof["owner"] != owner
                or proof["used"]
                or proof["verified_at"] < time.time() - 900
            ):
                raise ValueError("身份验证已失效或已提交。")
            if body.get("confirm_registration") is not True:
                raise ValueError("请确认加入本地清单。")
            snapshot = self.snapshot()
            endpoint = next(
                (
                    a
                    for a in snapshot["allocations"]
                    if a["interface_id"] == proof["interface"]["interface_id"]
                ),
                None,
            )
            if endpoint != proof["interface"] or any(
                endpoint.get(k)
                for k in (
                    "device_id",
                    "machine_id",
                    "dpu_machine_id",
                    "switch_id",
                    "power_shelf_id",
                )
            ):
                raise ValueError("接口或归属已变化，请重新验证身份。")
            identity = proof["identity"]
            if identity["kind"] not in ("server", *KINDS):
                raise ValueError("此设备类型不支持通过当前入口纳管。")
            if identity["kind"] == "server":
                # Preserve the existing paused ExpectedMachine registration and history contract.
                candidate = next(
                    (
                        c
                        for c in discovery.candidates()["candidates"]
                        if c["bmc_mac"] == endpoint["mac_address"]
                        and c["bmc_ip"] == proof["verified_ip"]
                    ),
                    None,
                )
                if not candidate:
                    raise ValueError("服务器候选已变化，请刷新。")
                compatible = {
                    **identity,
                    "id": candidate["id"],
                    "owner": owner,
                    "observation": candidate["observation"],
                    "credentials": proof["credentials"],
                    "verified_at": proof["verified_at"],
                    "verified_ip": proof["verified_ip"],
                    "identity_source": "ui-redfish",
                }
                atomic_json(discovery.directory / (candidate["id"] + ".json"), compatible)
                proof["used"] = True
                self.write("proofs", proof["id"], proof)
                return discovery.enroll(
                    {"ids": [candidate["id"]], "confirm_registration": True}, owner, actor
                )
            kind = identity["kind"]
            declaration = {
                "bmc_mac_address": endpoint["mac_address"],
                KINDS[kind]["serial"]: identity["serial"],
                "bmc_ip_address": proof["verified_ip"],
                "bmc_username": proof["credentials"]["username"],
                "bmc_password": proof["credentials"]["password"],
                "bmc_retain_credentials": True,
            }
            result = self.save(
                {
                    "kind": kind,
                    "declaration": declaration,
                    "bindings": {endpoint["mac_address"]: endpoint["network_id"]},
                }
            )
            proof.update(used=True, device_id=result["id"])
            self.write("proofs", proof["id"], proof)
            return result
