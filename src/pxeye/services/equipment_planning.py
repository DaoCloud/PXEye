"""Editable arrival plans, separate from authenticated inventory and execution plans."""

import copy
import csv
import io
import ipaddress
import json
import time
import uuid
from collections import Counter

from pxeye.common import digest, sha
from pxeye.domain.machines import confirms_fields
from pxeye.services.device_plans import DevicePlans
from pxeye.services.equipment import Equipment, mac, ipv4

FIELDS = (
    "serial",
    "management_ip",
    "management_mac",
    "management_subnet",
    "bmc_ip",
    "bmc_mac",
    "rack",
)


def is_host(interface):
    return interface.get("role") in (None, "host", "unspecified", 0, 1)


def normalize(values):
    if not isinstance(values, dict) or set(values) != set(FIELDS):
        raise ValueError("请使用设备规划模板的七个字段，官方设备声明请使用原生导入接口。")
    row = {}
    for key, value in values.items():
        if not isinstance(value, str) or len(value) > 128 or any(ord(c) < 32 for c in value):
            raise ValueError("规划字段需为不含控制字符的文本，最多128字符。")
        row[key] = value.strip()
    if not row["serial"]:
        raise ValueError("设备 SN 不能为空。")
    for key in ("management_mac", "bmc_mac"):
        if row[key]:
            row[key] = mac(row[key])
    for key in ("management_ip", "bmc_ip"):
        row[key] = ipv4(row[key])
    if row["management_subnet"]:
        network = ipaddress.IPv4Network(row["management_subnet"], strict=True)
        row["management_subnet"] = str(network)
        if row["management_ip"]:
            address = ipaddress.IPv4Address(row["management_ip"])
            if address not in network or address in (
                network.network_address,
                network.broadcast_address,
            ):
                raise ValueError("管理 IP 不属于管理子网或使用了网络/广播地址。")
    if (row["management_ip"] or row["management_subnet"]) and not row["management_mac"]:
        raise ValueError("填写管理 IP 或管理子网时必须提供管理 MAC。")
    if row["bmc_mac"] and row["bmc_mac"] == row["management_mac"]:
        raise ValueError("BMC 和主机管理接口不能使用相同 MAC。")
    return row


def check_interface_values(record, values):
    if (record or {}).get("interface_rows") and record["values"]["serial"] != values["serial"]:
        raise ValueError("带网卡规划的主机 SN 来自已采集硬件，不能通过编辑更换。")
    for row in (record or {}).get("interface_rows", []):
        if row["mac"] == values["management_mac"] and (
            values["management_ip"]
            and values["management_ip"] != row["ip"]
            or values["management_subnet"]
            and values["management_subnet"] != row["subnet"]
        ):
            raise ValueError("该 MAC 已有网卡地址规划，请通过网卡规划表统一更新 IP 和子网。")


class EquipmentPlanning:
    def __init__(self, adapter, resources):
        self.adapter, self.resources, self.store = adapter, resources, resources.store
        self.plans = DevicePlans(adapter, resources)

    @staticmethod
    def records(db):
        return {
            r["id"]: json.loads(r["data"])
            for r in db.execute("SELECT id,data FROM equipment_planning ORDER BY serial")
        }

    @staticmethod
    def public(record):
        return {k: record[k] for k in ("id", "values", "saved_at", "source")} | {
            "revision": digest(record),
            "interface_rows": record.get("interface_rows", []),
        }

    @staticmethod
    def put(db, record):
        db.execute(
            "INSERT INTO equipment_planning VALUES (?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET serial=excluded.serial,data=excluded.data",
            (record["id"], record["values"]["serial"], json.dumps(record, ensure_ascii=False)),
        )

    def list(self):
        with self.store.db() as db:
            rows = [self.public(r) for r in self.records(db).values()]
        return {"rows": rows}

    @staticmethod
    def template():
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(FIELDS)
        writer.writerow(
            [
                "SERIAL-1",
                "192.0.2.10",
                "02:00:00:00:00:21",
                "192.0.2.0/24",
                "198.51.100.10",
                "02:00:00:00:00:20",
                "RACK-01",
            ]
        )
        return stream.getvalue()

    def save(self, body):
        if (
            set(body) != {"id", "revision", "values"}
            or not isinstance(body["id"], str)
            or not isinstance(body["revision"], str)
        ):
            raise ValueError("设备规划字段无效。")
        values = normalize(body["values"])
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            records = self.records(db)
            old = records.get(body["id"])
            if body["id"] and not old or body["revision"] != (digest(old) if old else ""):
                raise ValueError("设备规划已变化，请刷新后编辑。")
            check_interface_values(old, values)
            if any(
                r["values"]["serial"] == values["serial"] and r != old for r in records.values()
            ):
                raise ValueError("规划清单中已存在此 SN，请编辑原记录。")
            if old and old["values"] == values:
                return self.public(old) | {"status": "unchanged"}
            record = {
                **(old or {}),
                "id": old["id"] if old else str(uuid.uuid4()),
                "values": values,
                "saved_at": time.time(),
                "source": "ui",
            }
            self.put(db, record)
        return self.public(record) | {"status": "saved"}

    def preview(self, text, owner):
        if not isinstance(text, str) or len(text.encode()) > 1024 * 1024:
            raise ValueError("规划 CSV 最大1 MiB。")
        reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")), strict=True)
        from pxeye.services.interface_planning import InterfacePlanning, interface_header

        try:
            header = reader.fieldnames or []
        except csv.Error:
            raise ValueError("CSV 表头格式错误，请检查引号。") from None
        if interface_header(header):
            return InterfacePlanning(self).preview(text, owner)
        if (
            not reader.fieldnames
            or len(reader.fieldnames) != len(FIELDS)
            or set(reader.fieldnames) != set(FIELDS)
        ):
            raise ValueError("请下载新的设备规划 CSV 模板；不支持旧版官方声明表头或额外字段。")
        incoming = []
        try:
            for row in reader:
                if len(incoming) >= 5000:
                    raise ValueError("一次最多导入5000条设备规划。")
                incoming.append((reader.line_num, row))
        except csv.Error:
            raise ValueError("CSV 格式错误，请检查引号和列数。") from None
        if not incoming:
            raise ValueError("CSV 中没有设备规划。")
        serials = Counter(str(r.get("serial") or "").strip() for _, r in incoming)
        with self.store.db() as db:
            existing = {r["values"]["serial"]: r for r in self.records(db).values()}
        rows, updates = [], []
        for line, raw in incoming:
            serial = str(raw.get("serial") or "").strip()
            try:
                if None in raw or any(value is None for value in raw.values()):
                    raise ValueError("CSV 行的列数与模板不一致。")
                if serials[serial] != 1:
                    raise ValueError("CSV 中的 SN 重复。")
                old = existing.get(serial)
                # Blank CSV cells keep the saved source values; editor fields can clear them.
                merged = dict(raw)
                if old:
                    merged = {
                        k: v if v.strip() else old["values"].get(k, "") for k, v in raw.items()
                    }
                values = normalize(merged)
                check_interface_values(old, values)
                operation = (
                    "create" if not old else "unchanged" if old["values"] == values else "update"
                )
                record = {
                    **(old or {}),
                    "id": old["id"] if old else str(uuid.uuid4()),
                    "values": values,
                    "saved_at": time.time(),
                    "source": "csv",
                }
                updates.append(
                    {
                        "record": record,
                        "revision": digest(old) if old else "",
                        "operation": operation,
                    }
                )
                rows.append(
                    {"line": line, "serial": serial, "operation": operation, "values": values}
                )
            except (ValueError, TypeError) as error:
                rows.append(
                    {"line": line, "serial": serial, "operation": "invalid", "detail": str(error)}
                )
        counts = {
            k: sum(r["operation"] == k for r in rows)
            for k in ("create", "update", "unchanged", "invalid")
        }
        key = uuid.uuid4().hex
        if not counts["invalid"]:
            self.store.preflight(
                key,
                {"kind": "equipment-planning-import", "owner": owner, "updates": updates},
                lifetime=900,
            )
        return {"preview_id": key if not counts["invalid"] else "", "rows": rows, "counts": counts}

    def import_csv(self, body, owner):
        if set(body) != {"preview_id"} or not isinstance(body["preview_id"], str):
            raise ValueError("请先预览设备规划。")
        with self.store.db() as db:
            row = db.execute(
                "SELECT data FROM preflights WHERE id=?", (body["preview_id"],)
            ).fetchone()
        if row and json.loads(row["data"]).get("kind") == "interface-planning-import":
            from pxeye.services.interface_planning import InterfacePlanning

            return InterfacePlanning(self).apply(body, owner)
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            preview = db.execute(
                "SELECT * FROM preflights WHERE id=?", (body["preview_id"],)
            ).fetchone()
            if not preview or preview["expires"] < time.time():
                raise ValueError("导入预览已过期，请重新预览。")
            data = json.loads(preview["data"])
            if data.get("kind") != "equipment-planning-import" or data.get("owner") != owner:
                raise ValueError("导入预览不属于当前会话。")
            if preview["used"]:
                return {"status": "saved", "count": data["count"]}
            records = self.records(db)
            serials = {r["values"]["serial"]: r["id"] for r in records.values()}
            for item in data["updates"]:
                record = item["record"]
                old = records.get(record["id"])
                if (
                    item["revision"] != (digest(old) if old else "")
                    or serials.get(record["values"]["serial"], record["id"]) != record["id"]
                ):
                    raise ValueError("规划已变化，请重新预览；本批未保存。")
            count = 0
            for item in data["updates"]:
                if item["operation"] != "unchanged":
                    self.put(db, item["record"])
                    count += 1
            data["count"] = count
            db.execute(
                "UPDATE preflights SET used=1,data=? WHERE id=?",
                (json.dumps(data), body["preview_id"]),
            )
        return {"status": "saved", "count": count}

    def migrate_legacy(self, native_rows):
        """Archive only CSV-only arrivals after a successful native inventory read."""
        protected = {r["chassis_serial_number"] for r in native_rows}
        protected.update(d["serial"] for d in self.adapter.config.get("devices", []))
        for path in (self.adapter.data / "config" / "execution").glob("*.json"):
            execution = json.loads(path.read_text())
            if execution.get("serial"):
                protected.add(execution["serial"])
        for path in (self.adapter.data / "config" / "discovery").glob("*.json"):
            proof = json.loads(path.read_text())
            if proof.get("verified_at") and proof.get("serial"):
                protected.add(proof["serial"])
        with self.store.db() as db:
            protected.update(r["device"] for r in db.execute("SELECT DISTINCT device FROM tasks"))
            candidates = [
                (r["serial"], json.loads(r["data"]))
                for r in db.execute("SELECT * FROM device_plans")
            ]
        candidates = [
            (s, r) for s, r in candidates if s not in protected and r.get("source") == "csv"
        ]
        if not candidates:
            return
        networks = {n["id"]: n for n in self.resources.networks()}
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = {r["values"]["serial"] for r in self.records(db).values()}
            migrated = 0
            for serial, old in candidates:
                current = db.execute(
                    "SELECT data FROM device_plans WHERE serial=?", (serial,)
                ).fetchone()
                if not current or digest(json.loads(current["data"])) != digest(old):
                    continue
                machine = old["machine"]
                hosts = [n for n in machine.get("interfaces", []) if is_host(n)]
                primary = [n for n in hosts if n.get("primary")]
                host = primary[0] if len(primary) == 1 else hosts[0] if len(hosts) == 1 else {}
                network = networks.get(
                    old.get("intent", {})
                    .get("network_bindings", {})
                    .get(host.get("mac_address", "").lower()),
                    {},
                )
                prefixes = network.get("prefixes", [])
                subnet = prefixes[0]["prefix"] if len(prefixes) == 1 else ""
                values = {
                    "serial": serial,
                    "management_ip": host.get("fixed_ip") or "",
                    "management_mac": host.get("mac_address") or "",
                    "management_subnet": subnet,
                    "bmc_ip": machine.get("bmc_ip_address") or "",
                    "bmc_mac": machine["bmc_mac_address"],
                    "rack": str(machine.get("rack_id") or ""),
                }
                try:
                    values = normalize(values)
                except ValueError:
                    # Preserve incompatible historical records without blocking service startup.
                    continue
                if serial not in existing:
                    self.put(
                        db,
                        {
                            "id": str(uuid.uuid4()),
                            "values": values,
                            "saved_at": old["saved_at"],
                            "source": "legacy-csv",
                            "archived_revision": digest(old),
                        },
                    )
                # Immutable original versions (including credentials) remain recoverable.
                self.plans.put(db, serial, old)
                db.execute("DELETE FROM device_plans WHERE serial=?", (serial,))
                migrated += 1
        if migrated:
            self.plans.export()

    def host_macs(self, record):
        return {nic["mac_address"] for nic in self.host_nics(record)}

    def host_nics(self, record):
        from pxeye.domain.pci import merge_host_nics

        machine = record["machine"]
        serial, bmc = machine["chassis_serial_number"], machine["bmc_mac_address"].lower()
        observed = []
        path = self.adapter.data / "observations" / "hardware" / (sha(serial) + ".json")
        if path.exists():
            cached = json.loads(path.read_text())
            hardware = cached.get("hardware") or {}
            if cached.get("device_id") == machine["id"] and serial in {
                hardware.get("product_serial"),
                hardware.get("chassis_serial"),
            }:
                observed.append(hardware.get("nics", []))
        proofs = []
        for path in (self.adapter.data / "config" / "management-addresses" / "proofs").glob(
            "*.json"
        ):
            proof = json.loads(path.read_text())
            if (
                proof.get("serial") == serial
                and proof.get("kind") == "server"
                and proof.get("mac_address", "").lower() == bmc
                and proof.get("verified_at")
                and "nics" in proof
            ):
                proofs.append(proof)
        if proofs:
            proof = max(proofs, key=lambda p: p["verified_at"])
            observed.append(proof["nics"])
        proofs = []
        for path in (self.adapter.data / "config" / "discovery").glob("*.json"):
            proof = json.loads(path.read_text())
            if (
                proof.get("serial") == serial
                and proof.get("status") == "registered"
                and proof.get("expected_id") == machine["id"]
                and str(proof.get("bmc_mac", bmc)).lower() == bmc
                and proof.get("verified_at")
            ):
                proofs.append(proof)
        if proofs:
            proof = max(proofs, key=lambda p: p["verified_at"])
            observed.append(proof.get("nics", []))
        return merge_host_nics(observed, bmc)

    def prepare_match(self, source, old, records, networks, network_revisions):
        values = source["values"]
        machine, intent = copy.deepcopy(old["machine"]), copy.deepcopy(old["intent"])
        if not machine.get("bmc_username") or not machine.get("bmc_password"):
            raise ValueError("设备缺少已保存的 BMC 凭据，请先完成纳管。")
        if values["bmc_mac"] and values["bmc_mac"] != machine["bmc_mac_address"].lower():
            raise ValueError("规划 BMC MAC 与纳管设备不一致。")
        if values["bmc_ip"]:
            machine.update(bmc_ip_address=values["bmc_ip"], bmc_ip_allocation="Fixed")
            bmcs = [n for n in machine.get("interfaces", []) if n.get("role") == "host_bmc"]
            if not bmcs:
                machine.setdefault("interfaces", []).append(
                    {
                        "role": "host_bmc",
                        "mac_address": machine["bmc_mac_address"].lower(),
                        "network_segment_type": 2,
                    }
                )
                bmcs = [machine["interfaces"][-1]]
            if len(bmcs) != 1:
                raise ValueError("设备没有唯一 BMC 接口。")
            bmcs[0].update(fixed_ip=values["bmc_ip"], ip_allocation="fixed")
        if values["management_mac"]:
            hardware = values["management_mac"]
            if not hardware or hardware not in self.host_macs(old):
                raise ValueError(
                    "管理 MAC 未在该设备已采集硬件中找到，请先获取硬件信息或核对规划。"
                )
            hosts = [
                n
                for n in machine.get("interfaces", [])
                if n.get("mac_address", "").lower() == hardware and is_host(n)
            ]
            if len(hosts) != 1:
                raise ValueError("管理 MAC 未唯一对应设备主机接口，请先完善系统配置。")
            host = hosts[0]
            for n in machine["interfaces"]:
                if is_host(n) and n.get("primary") and n is not host:
                    n["primary"] = False
            host["primary"] = True
            host.update(role="host", network_segment_type=3)
            if values["management_ip"]:
                host.update(fixed_ip=values["management_ip"], ip_allocation="fixed")
            if values["management_subnet"]:
                cidr = values["management_subnet"]
                matches = [
                    n
                    for n in networks
                    if n["segment_type"] == "HOST_INBAND"
                    and len(n["prefixes"]) == 1
                    and str(ipaddress.ip_network(n["prefixes"][0]["prefix"])) == cidr
                    and n.get("name") != "static-assignments"
                ]
                if len(matches) != 1:
                    raise ValueError(
                        "管理子网不存在，请先在网络管理创建。"
                        if not matches
                        else "管理子网无法唯一确定，请检查重复子网。"
                    )
                network = matches[0]
                prefix = network["prefixes"][0]
                host.update(
                    fixed_mask=str(ipaddress.ip_network(cidr).netmask),
                    fixed_gateway=prefix.get("gateway") or "",
                )
                intent.setdefault("network_bindings", {})[hardware] = network["id"]
        # Validate affected references against the same network snapshot used for CIDR resolution.
        from pxeye.services.device_config import DeviceConfig

        changed_bindings = {
            m: key
            for m, key in intent.get("network_bindings", {}).items()
            if m == values["management_mac"]
            or values["bmc_ip"]
            and m == machine["bmc_mac_address"].lower()
        }
        current_networks = {n["id"]: n for n in networks}
        for key in changed_bindings.values():
            if (
                key not in current_networks
                or network_revisions.get(key) != current_networks[key]["revision"]
            ):
                raise ValueError("关联子网配置已变化，请刷新后重新匹配。")
        DeviceConfig(self.adapter, self.resources).validate_networks(
            changed_bindings, machine, networks=networks
        )
        clean = {k: v for k, v in intent.items() if k not in ("serial", "login_ref")}
        _, prepared = self.plans.prepare(
            {"id": machine["id"], "revision": digest(old), "machine": machine, "intent": clean},
            records,
        )
        if prepared["intent"].get("login_ref") != old["intent"].get("login_ref"):
            raise ValueError("现有 OS 凭据无法原样保留，请先核对系统配置。")
        prepared["intent"] = intent
        if source.get("interface_rows"):
            from pxeye.services.interface_planning import InterfacePlanning

            if source.get("interface_bmc") != machine["bmc_mac_address"].lower():
                raise ValueError("网卡规划的 BMC 身份与纳管设备不同。")
            for row in source["interface_rows"]:
                network = InterfacePlanning.network(row, networks)
                if network_revisions.get(network["id"]) != network["revision"]:
                    raise ValueError("网卡子网配置已变化，请刷新后重新匹配。")
            prepared = InterfacePlanning(self).merge(
                prepared,
                source["interface_rows"],
                records | {machine["chassis_serial_number"]: prepared},
                networks,
                self.host_macs(old),
            )
        if (
            confirms_fields(old["machine"], prepared["machine"])
            and confirms_fields(prepared["machine"], old["machine"])
            and old["intent"] == prepared["intent"]
        ):
            return copy.deepcopy(old)
        return prepared

    def match(self, body):
        if (
            set(body) != {"selections", "network_revisions"}
            or not isinstance(body["selections"], list)
            or not 1 <= len(body["selections"]) <= 50
        ):
            raise ValueError("一次请选择1–50台纳管服务器。")
        network_revisions = body["network_revisions"]
        if (
            not isinstance(network_revisions, dict)
            or len(network_revisions) > 5000
            or any(
                not isinstance(k, str) or not isinstance(v, str)
                for k, v in network_revisions.items()
            )
        ):
            raise ValueError("子网配置版本无效，请刷新。")
        selections = body["selections"]
        fields = {"serial", "device_id", "device_revision", "plan_id", "plan_revision"}
        if any(
            not isinstance(s, dict)
            or set(s) != fields
            or any(not isinstance(v, str) for v in s.values())
            for s in selections
        ) or len({s["device_id"] for s in selections}) != len(selections):
            raise ValueError("设备选择或规划版本无效。")
        # The route holds the normal OS/configuration lock throughout this one-pass operation.
        snapshot = Equipment(self.adapter, self.resources).snapshot(servers=[])
        networks = snapshot["networks"]
        results = []
        for selection in selections:
            result = {"serial": selection["serial"], "status": "failed", "changes": []}
            try:
                with self.store.db() as db:
                    db.execute("BEGIN IMMEDIATE")
                    sources = self.records(db)
                    source = sources.get(selection["plan_id"])
                    if not source or source["values"]["serial"] != selection["serial"]:
                        raise ValueError("没有相同 SN 的设备规划。")
                    if digest(source) != selection["plan_revision"]:
                        raise ValueError("源规划已变化，请刷新后重新匹配。")
                    records = {
                        r["serial"]: json.loads(r["data"])
                        for r in db.execute("SELECT * FROM device_plans")
                    }
                    old = records.get(selection["serial"])
                    if not old or "server-" + old["machine"]["id"] != selection["device_id"]:
                        raise ValueError("纳管设备身份已变化，请刷新。")
                    if sum(
                        r["machine"]["chassis_serial_number"] == selection["serial"]
                        for r in records.values()
                    ) != 1 or any(i["serial"] == selection["serial"] for i in snapshot["items"]):
                        raise ValueError("纳管清单中的 SN 不唯一。")
                    native = [
                        r
                        for r in snapshot["server_declarations"]
                        if r["chassis_serial_number"] == selection["serial"]
                    ]
                    if (
                        len(native) != 1
                        or native[0]["id"] != old["machine"]["id"]
                        or native[0]["bmc_mac_address"].lower()
                        != old["machine"]["bmc_mac_address"].lower()
                    ):
                        raise ValueError("设备没有唯一的原生登记身份，请先纳管或刷新设备数据。")
                    if digest(old) != selection["device_revision"]:
                        raise ValueError("设备配置已变化，请刷新后重新匹配。")
                    prepared = self.prepare_match(source, old, records, networks, network_revisions)
                    before = {"BMC IP": old["machine"].get("bmc_ip_address") or ""}
                    after = {"BMC IP": prepared["machine"].get("bmc_ip_address") or ""}
                    for record, values in ((old, before), (prepared, after)):
                        host = next(
                            (
                                n
                                for n in record["machine"].get("interfaces", [])
                                if n.get("primary") and is_host(n)
                            ),
                            {},
                        )
                        values.update(
                            {
                                "管理 MAC / 启动口": host.get("mac_address") or "",
                                "管理 IP": host.get("fixed_ip") or "",
                                "管理子网": next(
                                    (
                                        n["prefixes"][0]["prefix"]
                                        for n in networks
                                        if len(n["prefixes"]) == 1
                                        and n["id"]
                                        == record["intent"]
                                        .get("network_bindings", {})
                                        .get(host.get("mac_address", "").lower())
                                    ),
                                    "",
                                ),
                                "管理掩码": host.get("fixed_mask") or "",
                                "管理网关": host.get("fixed_gateway") or "",
                            }
                        )
                    result["changes"] = [
                        {"field": k, "before": before[k], "after": after[k]}
                        for k in before
                        if before[k] != after[k]
                    ]
                    for planned in source.get("interface_rows", []):
                        hardware = planned["mac"]
                        previous = next(
                            (
                                n
                                for n in old["machine"].get("interfaces", [])
                                if n.get("mac_address") == hardware
                            ),
                            {},
                        )
                        current = next(
                            (
                                n
                                for n in prepared["machine"].get("interfaces", [])
                                if n.get("mac_address") == hardware
                            ),
                            {},
                        )
                        fields = ("fixed_ip", "fixed_mask", "fixed_gateway")
                        if any(previous.get(k) != current.get(k) for k in fields):
                            result["changes"].append(
                                {
                                    "field": "网卡 " + hardware,
                                    "before": " / ".join(previous.get(k) or "—" for k in fields),
                                    "after": " / ".join(current.get(k) or "—" for k in fields),
                                }
                            )
                    if (
                        old["machine"] == prepared["machine"]
                        and old["intent"] == prepared["intent"]
                    ):
                        result.update(status="unchanged", detail="配置无变化。")
                    else:
                        records[selection["serial"]] = prepared
                        self.plans.validate_conflicts(records, snapshot=snapshot)
                        self.plans.put(db, selection["serial"], prepared)
                        result.update(status="saved", detail="设备地址规划已保存。")
            except (ValueError, RuntimeError, OSError) as error:
                result["detail"] = str(error)
                result["changes"] = []
            results.append(result)
        counts = {
            s: sum(r["status"] == s for r in results) for s in ("saved", "unchanged", "failed")
        }
        if counts["saved"]:
            self.plans.export()
        return {"rows": results, "counts": counts}
