"""Round-trip collected host MACs through the existing planning CSV workflow."""

import copy
import csv
import io
import ipaddress
import json
import re
import time
import uuid
from urllib.parse import urlsplit

from pxeye.common import digest
from pxeye.domain.nic_inventory import INVENTORY_FIELDS
from pxeye.domain.pci import merge_host_nics
from pxeye.domain.workbook import interface_workbook
from pxeye.services.equipment import Equipment, mac

FIELDS = ("serial", "mac", "ip", "subnet", "gateway")
LEADING_FIELDS = (
    "serial",
    "mac",
    "location",
    "slot",
    "physical_port",
    "speed_mbps",
    "link_status",
    "pci_address",
    "vendor",
    "model",
    "ip",
    "subnet",
    "gateway",
)
EXPORT_FIELDS = (*LEADING_FIELDS, *(k for k in INVENTORY_FIELDS if k not in LEADING_FIELDS))


def interface_header(header):
    return len(header) == len(set(header)) and set(FIELDS) <= set(header) <= set(EXPORT_FIELDS)


class InterfacePlanning:
    def __init__(self, planning):
        self.planning = planning
        self.adapter, self.resources = planning.adapter, planning.resources
        self.store, self.plans = planning.store, planning.plans

    def snapshot(self):
        snapshot = Equipment(self.adapter, self.resources).snapshot(servers=[])
        if snapshot["errors"]:
            raise ValueError("设备或网络读取不完整，请刷新后重试。")
        return snapshot

    def catalog(self, snapshot, owner):
        """Use authenticated observations, never a CSV to prove MAC ownership."""
        with self.store.db() as db:
            records = {
                r["serial"]: json.loads(r["data"]) for r in db.execute("SELECT * FROM device_plans")
            }
        result = {}
        for native in snapshot["server_declarations"]:
            serial = native["chassis_serial_number"]
            old = records.get(serial)
            if not old or old["machine"]["id"] != native["id"]:
                continue
            bmc = native["bmc_mac_address"].lower()
            if old["machine"]["bmc_mac_address"].lower() != bmc or serial in result:
                raise ValueError("设备 SN 或 BMC 身份冲突：" + serial)
            nics = self.planning.host_nics(old)
            result[serial] = {
                "id": "server-" + native["id"],
                "bmc": bmc,
                "macs": [n["mac_address"] for n in nics],
                "nics": nics,
                "revision": digest(old),
            }
        endpoints = {a["interface_id"]: a for a in snapshot["allocations"]}
        equipment = Equipment(self.adapter, self.resources)
        latest = {}
        for proof in equipment.records("proofs"):
            key = (proof.get("owner"), proof.get("interface", {}).get("interface_id"))
            if proof.get("verified_at", 0) > latest.get(key, {}).get("verified_at", 0):
                latest[key] = proof
        for proof in latest.values():
            identity = proof.get("identity", {})
            endpoint = endpoints.get(proof.get("interface", {}).get("interface_id"))
            if (
                identity.get("kind") != "server"
                or proof.get("owner") != owner
                or proof.get("used")
                or proof.get("verified_at", 0) < time.time() - 900
                or not endpoint
                or endpoint != proof["interface"]
                or endpoint.get("identity_conflict")
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
                continue
            serial, bmc = identity["serial"], endpoint["mac_address"].lower()
            nics = merge_host_nics([identity.get("nics", [])], bmc)
            item = {
                "id": endpoint["interface_id"],
                "bmc": bmc,
                "macs": [n["mac_address"] for n in nics],
                "nics": nics,
                "revision": "",
            }
            if serial in result and result[serial] != item:
                raise ValueError("同一 SN 对应多个设备或不一致的网卡信息，请重新获取：" + serial)
            result[serial] = item
        return result

    def export(self, body, owner):
        ids = body.get("ids")
        if (
            set(body) != {"ids"}
            or not isinstance(ids, list)
            or not 1 <= len(ids) <= 50
            or any(not isinstance(i, str) for i in ids)
            or len(set(ids)) != len(ids)
        ):
            raise ValueError("请选择1–50台已获取硬件信息的服务器。")
        snapshot = self.snapshot()
        catalog = self.catalog(snapshot, owner)
        selected = [(s, c) for s, c in catalog.items() if c["id"] in ids]
        if len(selected) != len(ids) or any(not c["macs"] for _, c in selected):
            raise ValueError(
                "所选设备缺少可信的主机网卡信息，请先获取设备信息；已纳管设备可刷新硬件。"
            )
        macs = [m for _, c in selected for m in c["macs"]]
        if len(set(macs)) != len(macs):
            raise ValueError("所选设备存在重复 MAC，请核对硬件归属。")
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(EXPORT_FIELDS)
        rows = []
        with self.store.db() as db:
            records = {
                r["serial"]: json.loads(r["data"]) for r in db.execute("SELECT * FROM device_plans")
            }
            sources = {r["values"]["serial"]: r for r in self.planning.records(db).values()}
        for serial, item in sorted(selected):
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", serial):
                raise ValueError("主机 SN 不能安全导出，请先核对硬件身份。")
            record = records.get(serial)
            if (digest(record) if record else "") != item["revision"]:
                raise ValueError("设备配置已变化，请重新导出：" + serial)
            source = sources.get(serial, {})
            pending = {
                r["mac"]: r
                for r in source.get("interface_rows", [])
                if source.get("interface_bmc") == item["bmc"]
            }
            # Saved intent is authoritative; observed DHCP leases are not user configuration.
            for nic in item["nics"]:
                hardware = nic["mac_address"]
                values = self.saved_address(record, hardware, snapshot["networks"])
                if not record:
                    values = {k: pending.get(hardware, {}).get(k, "") for k in FIELDS[2:]}
                exported = {**nic, **values, "serial": serial, "mac": hardware}
                exported["inventory_note"] = "; ".join(
                    filter(None, [nic.get("inventory_note"), nic.get("pci_note")])
                )
                rows.append([exported.get(k, "") for k in EXPORT_FIELDS])
        writer.writerows(rows)
        return {
            "csv": stream.getvalue(),
            "xlsx": interface_workbook(EXPORT_FIELDS, rows),
            "count": len(rows),
        }

    @staticmethod
    def saved_address(record, hardware, networks):
        result = {k: "" for k in FIELDS[2:]}
        if not record:
            return result
        matches = [
            n
            for n in record["machine"].get("interfaces", [])
            if n.get("mac_address", "").lower() == hardware
            and n.get("role", "host") in ("host", "unspecified", 0, 1)
        ]
        if len(matches) != 1 or not matches[0].get("fixed_ip"):
            return result
        nic = matches[0]
        result["ip"] = nic["fixed_ip"]
        binding = record.get("intent", {}).get("network_bindings", {}).get(hardware)
        network = next((n for n in networks if n["id"] == binding), {})
        if nic.get("fixed_mask"):
            result["subnet"] = str(
                ipaddress.IPv4Interface(nic["fixed_ip"] + "/" + nic["fixed_mask"]).network
            )
        elif len(network.get("prefixes", [])) == 1:
            result["subnet"] = network["prefixes"][0]["prefix"]
        prefix = next(
            (p for p in network.get("prefixes", []) if p["prefix"] == result["subnet"]), {}
        )
        result["gateway"] = nic.get("fixed_gateway", prefix.get("gateway")) or ""
        return result

    @staticmethod
    def network(row, networks):
        matches = [
            n
            for n in networks
            if n["segment_type"] == "HOST_INBAND"
            and n.get("name") != "static-assignments"
            and len(n["prefixes"]) == 1
            and n["prefixes"][0]["prefix"] == row["subnet"]
        ]
        if not matches:
            exists = any(p["prefix"] == row["subnet"] for n in networks for p in n["prefixes"])
            raise ValueError(
                "子网 "
                + row["subnet"]
                + (
                    " 已存在，但不是单 IPv4 前缀的 HostInband 网络，请在网络管理中核对。"
                    if exists
                    else " 尚未创建，请先在网络管理中创建 HostInband 子网。"
                )
            )
        if len(matches) > 1:
            raise ValueError("子网 " + row["subnet"] + " 匹配多个网络，请在网络管理中核对。")
        network = matches[0]
        if type(network.get("mtu")) is not int or not 576 <= network["mtu"] <= 9216:
            raise ValueError("子网 MTU 配置不可用，请在网络管理中核对。")
        prefix = network["prefixes"][0]
        if (prefix.get("gateway") or "") != row["gateway"]:
            raise ValueError(
                "子网 "
                + row["subnet"]
                + " 的网关不一致：表格为 "
                + (row["gateway"] or "空")
                + "，系统为 "
                + (prefix.get("gateway") or "空")
                + "。"
            )
        address = ipaddress.IPv4Address(row["ip"])
        subnet = ipaddress.IPv4Network(row["subnet"])
        if int(address) - int(subnet.network_address) < int(prefix.get("reserveFirst", 0)):
            raise ValueError("IP 使用了子网起始保留地址。")
        return network

    def protect_services(self, rows):
        protected = {urlsplit(self.adapter.config.get("core_url", "")).hostname}
        protected.update(
            urlsplit(m["url"]).hostname for m in self.adapter.config.get("materials", [])
        )
        if any(row["ip"] in protected for row in rows):
            raise ValueError("规划 IP 与站点服务地址冲突。")

    def merge(self, old, rows, records, networks, hardware):
        machine, intent = copy.deepcopy(old["machine"]), copy.deepcopy(old["intent"])
        changed = {}
        self.protect_services(rows)
        for row in rows:
            if row["mac"] not in hardware:
                raise ValueError("MAC 不属于该设备已采集的主机网卡：" + row["mac"])
            matches = [
                n for n in machine.get("interfaces", []) if n.get("mac_address") == row["mac"]
            ]
            if (
                len(matches) > 1
                or matches
                and matches[0].get("role", "host") not in ("host", "unspecified", 0, 1)
            ):
                raise ValueError("MAC 未唯一对应主机网卡。")
            nic = (
                matches[0]
                if matches
                else {"mac_address": row["mac"], "role": "host", "primary": False}
            )
            if not matches:
                machine.setdefault("interfaces", []).append(nic)
            if nic.get("primary") and not row["gateway"]:
                raise ValueError("当前主启动接口需要管理网关，不能通过导入清空。")
            network = self.network(row, networks)
            nic.update(
                role="host",
                ip_allocation="fixed",
                network_segment_type=3,
                fixed_ip=row["ip"],
                fixed_mask=str(ipaddress.IPv4Network(row["subnet"]).netmask),
                fixed_gateway=row["gateway"],
            )
            intent.setdefault("network_bindings", {})[row["mac"]] = network["id"]
            changed[row["mac"]] = network["id"]
        from pxeye.services.device_config import DeviceConfig

        DeviceConfig(self.adapter, self.resources).validate_networks(
            changed, machine, networks=networks
        )
        clean = {k: v for k, v in intent.items() if k not in ("serial", "login_ref")}
        _, prepared = self.plans.prepare(
            {"id": machine["id"], "revision": digest(old), "machine": machine, "intent": clean},
            records,
        )
        if prepared["intent"].get("login_ref") != intent.get("login_ref"):
            raise ValueError("现有 OS 凭据无法保留，请先核对系统配置。")
        prepared["intent"] = intent
        for row in rows:
            if row["mac"] not in old.get("inventory_sources", {}):
                prepared["inventory_sources"][row["mac"]] = {"source": "observed"}
        if machine == old["machine"] and intent == old["intent"]:
            return copy.deepcopy(old)
        return prepared

    def preview(self, text, owner):
        reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")), strict=True)
        if not interface_header(reader.fieldnames or []):
            raise ValueError("设备网卡列表请保留 serial,mac,ip,subnet,gateway 及下载表中的信息列。")
        snapshot = self.snapshot()
        catalog = self.catalog(snapshot, owner)
        incoming, seen, addresses, errors, skipped = {}, set(), set(), [], 0
        try:
            for count, raw in enumerate(reader, 1):
                if count > 5000:
                    raise ValueError("一次最多导入5000个网口。")
                try:
                    if None in raw or any(
                        v is None
                        or len(v) > (128 if k in FIELDS else 4096)
                        or (k in FIELDS and any(ord(c) < 32 for c in v))
                        for k, v in raw.items()
                    ):
                        raise ValueError("列数、文本长度或控制字符无效。")
                    # Inventory columns are read-only; only address fields become planning input.
                    row = {k: raw[k].strip() for k in FIELDS}
                    row["mac"] = mac(row["mac"])
                    serial, hardware = row["serial"], row["mac"]
                    if serial not in catalog or hardware not in catalog[serial]["macs"]:
                        raise ValueError("SN/MAC 未匹配已认证的主机硬件，请先获取设备信息。")
                    if hardware in seen:
                        raise ValueError("同一 MAC 在表格中重复。")
                    seen.add(hardware)
                    if not any(row[k] for k in ("ip", "subnet", "gateway")):
                        skipped += 1
                        continue
                    row["ip"] = str(ipaddress.IPv4Address(row["ip"]))
                    subnet = ipaddress.IPv4Network(row["subnet"], strict=True)
                    row["subnet"] = str(subnet)
                    address = ipaddress.IPv4Address(row["ip"])
                    if address not in subnet or address in (
                        subnet.network_address,
                        subnet.broadcast_address,
                    ):
                        raise ValueError("IP 不属于子网或使用了网络/广播地址。")
                    if row["gateway"]:
                        gateway = ipaddress.IPv4Address(row["gateway"])
                        if gateway not in subnet or gateway in (
                            address,
                            subnet.network_address,
                            subnet.broadcast_address,
                        ):
                            raise ValueError("网关必须为子网内的有效地址，且不能与 IP 相同。")
                        row["gateway"] = str(gateway)
                    if row["ip"] in addresses:
                        raise ValueError("表格中 IP 地址重复。")
                    addresses.add(row["ip"])
                    self.network(row, snapshot["networks"])
                    incoming.setdefault(serial, []).append(row)
                except (ValueError, TypeError) as error:
                    errors.append(
                        {
                            "line": reader.line_num,
                            "serial": (raw.get("serial") or "").strip()[:128],
                            "interfaces": [{k: (raw.get(k) or "")[:128] for k in FIELDS}],
                            "operation": "invalid",
                            "detail": str(error),
                        }
                    )
        except csv.Error:
            raise ValueError("CSV 格式错误，请检查引号和列数。") from None
        if not incoming and not errors:
            raise ValueError("表格没有填写接口地址；空白地址行不修改已有配置。")
        updates, display = [], list(errors)
        with self.store.db() as db:
            sources = {r["values"]["serial"]: r for r in self.planning.records(db).values()}
            records = {
                r["serial"]: json.loads(r["data"]) for r in db.execute("SELECT * FROM device_plans")
            }
        for serial, rows in incoming.items():
            try:
                old_source, old = sources.get(serial), records.get(serial)
                item = catalog[serial]
                self.protect_services(rows)
                if old_source and old_source.get("interface_bmc", item["bmc"]) != item["bmc"]:
                    raise ValueError("SN 对应的 BMC 身份与已保存接口规划不同，请核对设备。")
                if (digest(old) if old else "") != item["revision"]:
                    raise ValueError("设备配置已变化，请重新预览。")
                if old:
                    prepared = self.merge(old, rows, records, snapshot["networks"], item["macs"])
                    records[serial] = prepared
                # Preserve other MACs and the device-level arrival plan, including credentials.
                merged = {r["mac"]: r for r in (old_source or {}).get("interface_rows", [])}
                merged.update({r["mac"]: r for r in rows})
                all_rows = sorted(merged.values(), key=lambda r: r["mac"])
                source = {
                    **(old_source or {}),
                    "id": old_source["id"] if old_source else str(uuid.uuid4()),
                    "values": (old_source or {}).get("values")
                    or {
                        k: serial if k == "serial" else ""
                        for k in (
                            "serial",
                            "management_ip",
                            "management_mac",
                            "management_subnet",
                            "bmc_ip",
                            "bmc_mac",
                            "rack",
                        )
                    },
                    "interface_rows": all_rows,
                    "interface_bmc": item["bmc"],
                    "saved_at": time.time(),
                    "source": "interface-csv",
                }
                source["values"] = copy.deepcopy(source["values"])
                management = next(
                    (r for r in all_rows if r["mac"] == source["values"].get("management_mac")),
                    None,
                )
                if management:
                    source["values"].update(
                        management_ip=management["ip"], management_subnet=management["subnet"]
                    )
                unchanged = (
                    old_source
                    and old_source.get("interface_rows") == all_rows
                    and (not old or records[serial] == old)
                )
                operation = "unchanged" if unchanged else "update" if old_source else "create"
                updates.append(
                    {
                        "source_revision": digest(old_source),
                        "serial": serial,
                        "rows": rows,
                        "catalog": item,
                        "record": source,
                        "operation": operation,
                    }
                )
                display.append(
                    {
                        "line": "—",
                        "serial": serial,
                        "operation": operation,
                        "interfaces": rows,
                        "detail": f"{len(rows)} 个网口；"
                        + ("保存到系统配置，下次安装生效" if old else "待纳管后自动带入系统配置"),
                    }
                )
            except (ValueError, RuntimeError) as error:
                display.append(
                    {
                        "line": "—",
                        "serial": serial,
                        "operation": "invalid",
                        "interfaces": rows,
                        "detail": str(error),
                    }
                )
        try:
            self.plans.validate_conflicts(records, snapshot=snapshot)
            self.check_pending(sources, updates, records, snapshot)
        except ValueError as error:
            display.append(
                {"line": "—", "serial": "", "operation": "invalid", "detail": str(error)}
            )
        counts = {
            k: sum(r["operation"] == k for r in display)
            for k in ("create", "update", "unchanged", "invalid")
        }
        key = "" if counts["invalid"] else uuid.uuid4().hex
        if key:
            self.store.preflight(
                key,
                {
                    "kind": "interface-planning-import",
                    "owner": owner,
                    "updates": updates,
                    "networks": {n["id"]: n["revision"] for n in snapshot["networks"]},
                },
                lifetime=900,
            )
        return {
            "preview_id": key,
            "rows": display,
            "counts": counts,
            "skipped": skipped,
            "format": "interfaces",
            "failed_devices": sorted(
                {r["serial"] for r in display if r["operation"] == "invalid" and r["serial"]}
            ),
        }

    @staticmethod
    def check_pending(sources, updates, records, snapshot):
        desired = {s: r.get("interface_rows", []) for s, r in sources.items()}
        desired.update({u["serial"]: u["record"]["interface_rows"] for u in updates})
        owners, macs = {}, {}
        for serial, rows in desired.items():
            for row in rows:
                owner = (serial, row["mac"])
                if row["mac"] in macs and macs[row["mac"]] != serial:
                    raise ValueError("MAC 与另一台机器的接口规划冲突：" + row["mac"])
                macs[row["mac"]] = serial
                if row["ip"] in owners and owners[row["ip"]] != owner:
                    raise ValueError("IP 与已保存的接口规划冲突：" + row["ip"])
                owners[row["ip"]] = owner
        for serial, record in records.items():
            bmc_ip = record["machine"].get("bmc_ip_address")
            if bmc_ip in owners:
                raise ValueError("IP 与 BMC 地址冲突：" + bmc_ip)
            for nic in record["machine"].get("interfaces", []):
                ip = nic.get("fixed_ip")
                if ip in owners and owners[ip] != (serial, nic.get("mac_address")):
                    raise ValueError("IP 与设备已有配置冲突：" + ip)
        for allocation in snapshot["allocations"]:
            for ip in allocation.get("addresses", []):
                if ip in owners and owners[ip][1] != allocation.get("mac_address", "").lower():
                    raise ValueError("IP 已由其他 NICo 接口占用：" + ip)

    def apply(self, body, owner):
        snapshot = self.snapshot()
        catalog = self.catalog(snapshot, owner)
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            preview = db.execute(
                "SELECT * FROM preflights WHERE id=?", (body["preview_id"],)
            ).fetchone()
            if not preview or preview["expires"] < time.time():
                raise ValueError("导入预览已过期，请重新预览。")
            data = json.loads(preview["data"])
            if data.get("kind") != "interface-planning-import" or data.get("owner") != owner:
                raise ValueError("导入预览不属于当前会话。")
            if preview["used"]:
                return {"status": "saved", "count": data["count"], "format": "interfaces"}
            if data["networks"] != {n["id"]: n["revision"] for n in snapshot["networks"]}:
                for item in data["updates"]:
                    for row in item["rows"]:
                        try:
                            self.network(row, snapshot["networks"])
                        except ValueError as error:
                            raise ValueError(
                                f"设备 {item['serial']} / MAC {row['mac']}：{error} 本批未保存。"
                            ) from None
                raise ValueError("子网配置已变化，请重新预览；本批未保存。")
            sources = self.planning.records(db)
            records = {
                r["serial"]: json.loads(r["data"]) for r in db.execute("SELECT * FROM device_plans")
            }
            prepared = {}
            for item in data["updates"]:
                serial = item["serial"]
                current = next(
                    (s for s in sources.values() if s["values"]["serial"] == serial), None
                )
                if (
                    digest(current) != item["source_revision"]
                    or catalog.get(serial) != item["catalog"]
                    or (digest(records.get(serial)) if serial in records else "")
                    != item["catalog"]["revision"]
                ):
                    raise ValueError(
                        "设备 " + serial + " 的硬件或规划已变化，请重新预览；本批未保存。"
                    )
                if serial in records:
                    prepared[serial] = self.merge(
                        records[serial],
                        item["rows"],
                        records,
                        snapshot["networks"],
                        catalog[serial]["macs"],
                    )
                    records[serial] = prepared[serial]
            self.plans.validate_conflicts(records, snapshot=snapshot)
            self.check_pending(
                {r["values"]["serial"]: r for r in sources.values()},
                data["updates"],
                records,
                snapshot,
            )
            for serial, record in prepared.items():
                self.plans.put(db, serial, record)
            for item in data["updates"]:
                if item["operation"] != "unchanged":
                    self.planning.put(db, item["record"])
            data["count"] = sum(i["operation"] != "unchanged" for i in data["updates"])
            db.execute(
                "UPDATE preflights SET used=1,data=? WHERE id=?",
                (json.dumps(data), body["preview_id"]),
            )
        self.plans.export()
        return {"status": "saved", "count": data["count"], "format": "interfaces"}

    def apply_pending(self, serial):
        """Only called after explicit enrollment; never writes native networking."""
        with self.store.db() as db:
            source = next(
                (r for r in self.planning.records(db).values() if r["values"]["serial"] == serial),
                None,
            )
        if not source or not source.get("interface_rows"):
            return ""
        snapshot = self.snapshot()
        native = [
            r for r in snapshot["server_declarations"] if r["chassis_serial_number"] == serial
        ]
        if len(native) != 1 or native[0]["bmc_mac_address"].lower() != source["interface_bmc"]:
            raise ValueError("设备没有唯一且一致的原生登记身份。")
        self.plans.seed(snapshot["server_declarations"])
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            current_source = self.planning.records(db).get(source["id"])
            if digest(current_source) != digest(source):
                raise ValueError("接口规划已变化，请重新匹配。")
            records = {
                r["serial"]: json.loads(r["data"]) for r in db.execute("SELECT * FROM device_plans")
            }
            old = records.get(serial)
            if not old or old["machine"]["bmc_mac_address"].lower() != source["interface_bmc"]:
                raise ValueError("接口规划的 BMC 身份与纳管设备不同。")
            record = self.merge(
                old,
                source["interface_rows"],
                records,
                snapshot["networks"],
                self.planning.host_macs(old),
            )
            records[serial] = record
            self.plans.validate_conflicts(records, snapshot=snapshot)
            self.check_pending(
                {r["values"]["serial"]: r for r in self.planning.records(db).values()},
                [],
                records,
                snapshot,
            )
            self.plans.put(db, serial, record)
        self.plans.export()
        return "已带入网卡地址规划；请在系统配置中确认主启动接口。"
