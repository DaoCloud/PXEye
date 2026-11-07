"""Local, versioned planning. Only explicit execution synchronizes native declarations."""

import copy
import csv
import io
import ipaddress
import json
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

from pxeye.common import atomic_json, atomic_text, digest
from pxeye.domain.machines import machine_rpc, public_machine, validate_machine, confirms_fields
from pxeye.persistence.store import get_store

EXECUTING = ContextVar("device_plan_execution", default={})
BMC_CHOICES = ContextVar("device_plan_bmc_choices", default={})


@contextmanager
def bmc_choice(serial, choice):
    if choice not in ("require_planned", "use_current"):
        raise ValueError("BMC执行选择无效。")
    token = BMC_CHOICES.set(BMC_CHOICES.get() | {serial: choice})
    try:
        yield
    finally:
        BMC_CHOICES.reset(token)


def use_current_bmc(serial):
    return BMC_CHOICES.get().get(serial) == "use_current"


def frozen_plan(action):
    @wraps(action)
    def wrapped(self, task, *args, **kwargs):
        revision = (task.get("installation_plan") or {}).get("device_plan_revision")
        token = EXECUTING.set({task["device"]: revision} if revision else {})
        try:
            with bmc_choice(
                task.get("device", ""),
                (task.get("installation_plan") or {}).get("bmc_choice", "require_planned"),
            ):
                return action(self, task, *args, **kwargs)
        finally:
            EXECUTING.reset(token)

    return wrapped


class DevicePlans:
    def __init__(self, adapter, resources):
        self.adapter, self.resources = adapter, resources
        self.store = resources.store or get_store(adapter.data / "console.sqlite3")
        self.directory = adapter.data / "config"

    def get(self, serial, *, current=False):
        revision = None if current else EXECUTING.get().get(serial)
        with self.store.db() as db:
            if revision:
                row = db.execute(
                    "SELECT data FROM device_plan_versions WHERE revision=? AND serial=?",
                    (revision, serial),
                ).fetchone()
                if not row:
                    raise ValueError("任务绑定的规划版本缺失，停止执行。")
            else:
                row = db.execute(
                    "SELECT data FROM device_plans WHERE serial=?", (serial,)
                ).fetchone()
        return json.loads(row["data"]) if row else {}

    def cached_inventory(self):
        path = self.directory / "expected-machines.json"
        return json.loads(path.read_text()).get("expected_machines", []) if path.exists() else []

    def seed(self, rows):
        # Existing resources and secrets are preserved; migration has no Core write.
        from pxeye.common import sha

        sources = {}
        for path in (self.directory / "discovery").glob("*.json"):
            proof = json.loads(path.read_text())
            if proof.get("serial"):
                sources[proof["serial"]] = {
                    n["mac_address"].lower(): {
                        "source": "bmc",
                        "name": n.get("name", ""),
                        "observed_at": proof.get("verified_at"),
                    }
                    for n in proof.get("nics", [])
                }
        with self.store.db() as db:
            for machine in rows:
                serial = machine["chassis_serial_number"]
                path = self.directory / "device-intents" / (sha(serial) + ".json")
                intent = json.loads(path.read_text()) if path.exists() else {}
                record = {
                    "machine": machine,
                    "intent": intent,
                    "source": "nico",
                    "saved_at": 0,
                    "inventory_sources": sources.get(serial, {}),
                }
                if not db.execute(
                    "SELECT 1 FROM device_plans WHERE serial=?", (serial,)
                ).fetchone():
                    self.put(db, serial, record)

    def put(self, db, serial, record):
        data = json.dumps(record, ensure_ascii=False)
        db.execute("INSERT OR REPLACE INTO device_plans VALUES (?,?)", (serial, data))
        db.execute(
            "INSERT OR IGNORE INTO device_plan_versions VALUES (?,?,?)",
            (digest(record), serial, data),
        )

    def inventory(self):
        with self.store.db() as db:
            serials = [
                r["serial"] for r in db.execute("SELECT serial FROM device_plans ORDER BY serial")
            ]
        if not serials:
            return self.resources.inventory()
        return [copy.deepcopy(self.get(s)["machine"]) for s in serials]

    def public(self, serial):
        record = self.get(serial)
        if not record:
            return {"plan_revision": "", "planning_missing": [], "plan_saved": False}
        machine, intent = record["machine"], record["intent"]
        missing = []
        if not machine.get("bmc_username") or not machine.get("bmc_password"):
            missing.append("BMC 账号")
        if not any(
            n.get("primary") and n.get("role", "host") == "host"
            for n in machine.get("interfaces", [])
        ):
            missing.append("主机启动口")
        if not intent.get("profile_id"):
            missing.append("安装方案")
        if not intent.get("os_id") and not intent.get("profile_id"):
            missing.append("目标 OS")
        if not intent.get("hostname"):
            missing.append("hostname")
        if intent.get("profile_id"):
            from pxeye.services.profiles import InstallProfiles

            try:
                effective = InstallProfiles(self.adapter).resolve(intent)
                v = effective["values"]
                if not v.get("username"):
                    missing.append("OS 用户名")
                if v.get("login_mode") == "password" and not v.get("login_ref"):
                    missing.append("OS 密码")
                if v.get("login_mode") == "key" and not v.get("authorized_keys"):
                    missing.append("OS 公钥")
                missing.extend(effective["problems"])
            except ValueError:
                missing.append("可用安装方案")
        return {
            "plan_revision": digest(record),
            "planning_missing": missing,
            "plan_saved": record["saved_at"] != 0,
            "plan_saved_at": record["saved_at"],
            "planning_state": "draft" if missing else "planned",
            "inventory_sources": record.get("inventory_sources", {}),
            "plan_source": record["source"],
        }

    def prepare(self, body, records):
        if set(body) != {"id", "revision", "machine", "intent"} or not isinstance(
            body["machine"], dict
        ):
            raise ValueError("规划字段不完整。")
        changes = copy.deepcopy(body["machine"])
        serial = changes.get("chassis_serial_number", "")
        old = records.get(serial)
        if body["revision"] != (digest(old) if old else ""):
            raise ValueError("规划已被修改，请刷新后核对；本次内容尚未保存。")
        before = old["machine"] if old else {}
        if old:
            self.resources.check_address_operation(before)
        if old and any(
            changes.get(k, before.get(k)) != before.get(k) for k in ("chassis_serial_number", "id")
        ):
            raise ValueError("设备身份不能通过规划修改。")
        if (
            old
            and changes.get("bmc_mac_address", before["bmc_mac_address"]).lower()
            != before["bmc_mac_address"].lower()
        ):
            raise ValueError("BMC MAC 不能通过规划修改。")
        if old and body["id"] != before["id"] or not old and body["id"]:
            raise ValueError("规划设备ID不匹配。")
        if not changes.get("bmc_password"):
            changes["bmc_password"] = before.get("bmc_password", "")
        machine = validate_machine(before | changes, draft=True)
        machine["id"] = before.get("id") or str(uuid.uuid4())
        pause = before.get("default_pause_ingestion_and_poweron", True)
        if machine.get("default_pause_ingestion_and_poweron", True) != pause:
            raise ValueError("保存规划不能解除硬件准备暂停。")
        machine["default_pause_ingestion_and_poweron"] = pause
        allocation, ip = machine.get("bmc_ip_allocation"), machine.get("bmc_ip_address")
        if allocation in ("Dynamic", "Retained") and ip:
            raise ValueError("动态或保留策略不能指定 BMC IP；请清空规划 IP。")
        host_bmcs = [n for n in machine.get("interfaces", []) if n.get("role") == "host_bmc"]
        if len(host_bmcs) > 1 or any(
            n.get("mac_address", "").lower() != machine["bmc_mac_address"].lower()
            for n in host_bmcs
        ):
            raise ValueError("BMC接口必须唯一并匹配设备BMC MAC。")
        if any(n.get("fixed_ip") and ip and n["fixed_ip"] != ip for n in host_bmcs):
            raise ValueError("BMC顶部与接口规划IP不一致。")
        for nic in machine.get("interfaces", []):
            if nic.get("fixed_ip") and nic.get("fixed_mask"):
                interface = ipaddress.ip_interface(nic["fixed_ip"] + "/" + nic["fixed_mask"])
                if interface.ip in (
                    interface.network.network_address,
                    interface.network.broadcast_address,
                ):
                    raise ValueError("网卡IP不能使用网络或广播地址。")
                if nic.get("fixed_gateway") and (
                    ipaddress.ip_address(nic["fixed_gateway"]) not in interface.network
                    or nic["fixed_gateway"] == nic["fixed_ip"]
                ):
                    raise ValueError("网卡网关与规划IP不一致。")
        from pxeye.services.device_config import DeviceConfig

        intent = DeviceConfig(self.adapter, self.resources).prepare_draft(
            body["intent"], (old or {}).get("intent", {})
        )
        nics = {n.get("mac_address", "").lower() for n in machine.get("interfaces", [])}
        for mac, network in intent.get("network_bindings", {}).items():
            if mac.lower() not in nics or not isinstance(network, str):
                raise ValueError("子网引用必须对应本设备网卡 MAC。")
        sources = copy.deepcopy((old or {}).get("inventory_sources", {}))
        for nic in machine.get("interfaces", []):
            mac = nic.get("mac_address", "").lower()
            if mac and mac not in {
                n.get("mac_address", "").lower() for n in before.get("interfaces", [])
            }:
                sources[mac] = {"source": "manual"}
        record = {
            "machine": machine,
            "intent": intent,
            "source": "ui",
            "saved_at": time.time(),
            "inventory_sources": sources,
        }
        return serial, record

    def installation_selection(
        self, serial, hostname, profile_id=None, disk_serial=None, revision=None
    ):
        """Persist task form edits before checking; no native side effects."""
        record = self.get(serial, current=True)
        if not record:
            self.seed(self.resources.inventory())
            record = self.get(serial, current=True)
        if not record:
            raise ValueError("请先将设备加入清单并保存安装规划。")
        if revision is not None and revision != digest(record):
            raise ValueError("设备规划已变化，请刷新后核对。")
        if self.store.active(serial):
            raise ValueError("设备已有活动任务，不能保存任务准备配置。")
        body = {
            "id": record["machine"]["id"],
            "revision": digest(record),
            "machine": copy.deepcopy(record["machine"]),
            "intent": copy.deepcopy(record["intent"]),
        }
        body["intent"].pop("login_ref", None)
        body["intent"].pop("serial", None)
        body["intent"]["hostname"] = hostname
        if profile_id:
            body["intent"]["profile_id"] = profile_id
        if disk_serial:
            body["intent"]["disk_serial"] = disk_serial
        changed = any(
            record["intent"].get(k) != body["intent"].get(k)
            for k in ("hostname", "profile_id", "disk_serial")
        )
        if changed:
            self.save(body)

    def validate_conflicts(self, records):
        from pxeye.services.equipment import Equipment

        Equipment(self.adapter, self.resources).validate_server_plans(records)
        macs, addresses, hostnames = {}, {}, {}
        for serial, record in records.items():
            hostname = record.get("intent", {}).get("hostname")
            if hostname and hostname in hostnames and hostnames[hostname] != serial:
                raise ValueError("hostname 已规划给另一设备：" + hostnames[hostname])
            if hostname:
                hostnames[hostname] = serial
        for serial, record in records.items():
            machine = record["machine"]
            seen = set()
            for mac in [machine["bmc_mac_address"]] + [
                n.get("mac_address", "") for n in machine.get("interfaces", [])
            ]:
                mac = mac.lower()
                if not mac or mac in seen:
                    continue
                seen.add(mac)
                if mac in macs and macs[mac] != serial:
                    raise ValueError("网卡 MAC 已规划给另一设备：" + macs[mac])
                macs[mac] = serial
            own_ips = {}
            entries = [("bmc", machine.get("bmc_ip_address"))] + [
                (
                    "bmc"
                    if n.get("role") == "host_bmc"
                    else n.get("mac_address") or n.get("physical_ifname"),
                    n.get("fixed_ip"),
                )
                for n in machine.get("interfaces", [])
            ]
            for owner, ip in entries:
                if ip and ip in own_ips and own_ips[ip] != owner:
                    raise ValueError("同一设备不同网卡的规划IP冲突。")
                if ip:
                    own_ips[ip] = owner
            for ip in [machine.get("bmc_ip_address")] + [
                n.get("fixed_ip") for n in machine.get("interfaces", [])
            ]:
                if ip and ip in addresses and addresses[ip] != serial:
                    raise ValueError("规划 IP 已被另一设备使用：" + addresses[ip])
                if ip:
                    addresses[ip] = serial

    def save(self, body):
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            records = {
                r["serial"]: json.loads(r["data"]) for r in db.execute("SELECT * FROM device_plans")
            }
            serial, record = self.prepare(body, records)
            records[serial] = record
            self.validate_conflicts(records)
            self.put(db, serial, record)
        exported = self.export()
        return {
            "status": "saved",
            "revision": digest(record),
            "exported": exported,
            "serial": serial,
            "detail": "规划已保存；将在独立地址操作或安装时执行。"
            if exported
            else "规划已保存；配置文件导出待修复。",
        }

    def bulk_references(self, profile_id, network_id):
        from pxeye.services.profiles import InstallProfiles

        profile = InstallProfiles(self.adapter).get(profile_id) if profile_id else None
        network = (
            next((n for n in self.resources.networks() if n["id"] == network_id), None)
            if network_id
            else None
        )
        if network_id and (
            not network or network["segment_type"] != "HOST_INBAND" or len(network["prefixes"]) != 1
        ):
            raise ValueError("请选择单前缀的主机管理子网。")
        return {"profile": digest(profile), "network": (network or {}).get("revision")}, network

    def bulk_preview(self, body, owner):
        if set(body) != {"serials", "profile_id", "network_id"}:
            raise ValueError("请选择设备、方案或管理网络。")
        serials = body["serials"]
        if (
            not isinstance(serials, list)
            or not 1 <= len(serials) <= 50
            or any(not isinstance(s, str) for s in serials)
            or len(set(serials)) != len(serials)
        ):
            raise ValueError("每次规划1–50台不同设备。")
        if not body["profile_id"] and not body["network_id"]:
            raise ValueError("请选择要应用的方案或管理网络。")
        refs, network = self.bulk_references(body["profile_id"], body["network_id"])
        with self.store.db() as db:
            records = {
                r["serial"]: json.loads(r["data"]) for r in db.execute("SELECT * FROM device_plans")
            }
        updates, revisions, rows = {}, {}, []
        for serial in serials:
            old = records.get(serial)
            if not old:
                raise ValueError("设备尚未登记：" + serial)
            machine, intent = copy.deepcopy(old["machine"]), copy.deepcopy(old["intent"])
            before = {"profile_id": intent.get("profile_id"), "network_id": None}
            if body["profile_id"]:
                intent["profile_id"] = body["profile_id"]
            if network:
                hosts = [
                    n
                    for n in machine.get("interfaces", [])
                    if n.get("primary") and n.get("role", "host") == "host"
                ]
                if len(hosts) != 1:
                    raise ValueError(serial + " 请先选择唯一启动/管理MAC。")
                host, prefix = hosts[0], network["prefixes"][0]
                mac = host["mac_address"].lower()
                before["network_id"] = intent.get("network_bindings", {}).get(mac)
                if host.get("fixed_ip") and ipaddress.ip_address(
                    host["fixed_ip"]
                ) not in ipaddress.ip_network(prefix["prefix"]):
                    raise ValueError(
                        serial + " 原管理IP不属于目标子网，请先逐机规划地址；不会自动分配或覆盖IP。"
                    )
                host.update(
                    fixed_mask=str(ipaddress.ip_network(prefix["prefix"]).netmask),
                    fixed_gateway=prefix.get("gateway", ""),
                    network_segment_type=3,
                )
                intent.setdefault("network_bindings", {})[mac] = network["id"]
            # Prepare through the same model; preserve all explicit overrides and credential references.
            clean_intent = {k: v for k, v in intent.items() if k not in ("serial", "login_ref")}
            _, record = self.prepare(
                {
                    "id": machine["id"],
                    "revision": digest(old),
                    "machine": machine,
                    "intent": clean_intent,
                },
                records,
            )
            if (
                old["intent"].get("login_ref")
                and record["intent"].get("login_ref") != old["intent"]["login_ref"]
            ):
                raise ValueError(serial + " 新方案会使设备凭据不兼容，请在设备规划中单独处理。")
            from pxeye.services.profiles import InstallProfiles

            resolved = (
                InstallProfiles(self.adapter).resolve(record["intent"])
                if record["intent"].get("profile_id")
                else {"problems": []}
            )
            if resolved["problems"]:
                raise ValueError(serial + "：" + "；".join(resolved["problems"]))
            records[serial] = record
            updates[serial], revisions[serial] = record, digest(old)
            rows.append(
                {
                    "serial": serial,
                    "before": before,
                    "after": {
                        "profile_id": intent.get("profile_id"),
                        "network_id": body["network_id"] or before["network_id"],
                    },
                    "hostname": intent.get("hostname"),
                    "management_ip": next(
                        (
                            n.get("fixed_ip")
                            for n in machine.get("interfaces", [])
                            if n.get("primary")
                        ),
                        None,
                    ),
                    "overrides": intent.get("override_modes", {}),
                }
            )
        self.validate_conflicts(records)
        key = uuid.uuid4().hex
        atomic_json(
            self.directory / "bulk-plans" / (key + ".json"),
            {
                "owner": owner,
                "expires": time.time() + 900,
                "status": "preview",
                "body": body,
                "references": refs,
                "updates": updates,
                "revisions": revisions,
            },
        )
        return {
            "preview_id": key,
            "rows": rows,
            "detail": "仅保存下次安装规划；保留逐机覆盖、IP和凭据。不修改运行OS或BMC。",
        }

    def bulk_apply(self, body, owner):
        if (
            set(body) != {"preview_id"}
            or not isinstance(body["preview_id"], str)
            or not re_full_id(body["preview_id"])
        ):
            raise ValueError("批量规划预览无效。")
        path = self.directory / "bulk-plans" / (body["preview_id"] + ".json")
        preview = json.loads(path.read_text())
        if (
            preview["owner"] != owner
            or preview["expires"] < time.time()
            or preview["status"] != "preview"
        ):
            raise ValueError("批量规划预览已失效。")
        refs, _ = self.bulk_references(preview["body"]["profile_id"], preview["body"]["network_id"])
        if refs != preview["references"]:
            raise ValueError("方案或子网已变化，请重新预览。")
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            records = {
                r["serial"]: json.loads(r["data"]) for r in db.execute("SELECT * FROM device_plans")
            }
            if any(digest(records.get(s)) != rev for s, rev in preview["revisions"].items()):
                raise ValueError("设备规划已变化，请重新预览；整批未保存。")
            records.update(preview["updates"])
            self.validate_conflicts(records)
            for serial, record in preview["updates"].items():
                self.put(db, serial, record)
        preview["status"] = "saved"
        atomic_json(path, preview)
        return {"status": "saved", "count": len(preview["updates"]), "exported": self.export()}

    def export(self):
        try:
            with self.store.db() as db:
                records = [
                    json.loads(r["data"])
                    for r in db.execute("SELECT data FROM device_plans ORDER BY serial")
                ]
            atomic_json(self.directory / "device-plans.json", {"plans": records})
            from pxeye.domain.machines import CSV_FIELDS

            stream = io.StringIO()
            writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for record in records:
                row = record["machine"]
                writer.writerow(
                    {
                        k: json.dumps(row[k], ensure_ascii=False)
                        if isinstance(row.get(k), (dict, list, bool))
                        else row.get(k, "")
                        for k in CSV_FIELDS
                    }
                )
            target = self.directory / "machines.planned.csv"
            atomic_text(target, stream.getvalue())
            return True
        except OSError:
            return False

    def preview_csv(self, text, owner):
        from pxeye.domain.csv import convert

        if not isinstance(text, str) or len(text.encode()) > 1024 * 1024:
            raise ValueError("CSV 最大 1 MiB。")
        incoming = convert(io.StringIO(text.lstrip("\ufeff")))["expected_machines"]
        with self.store.db() as db:
            records = {
                r["serial"]: json.loads(r["data"]) for r in db.execute("SELECT * FROM device_plans")
            }
        bodies, rows = [], []
        for machine in incoming:
            serial = machine["chassis_serial_number"]
            old = records.get(serial)
            body = {
                "id": old["machine"]["id"] if old else None,
                "revision": digest(old) if old else "",
                "machine": machine,
                "intent": (old or {}).get("intent", {}),
            }
            # The internal credential reference is preserved; it is never accepted from CSV.
            body["intent"] = {
                k: v for k, v in body["intent"].items() if k not in ("serial", "login_ref")
            }
            serial, record = self.prepare(body, records)
            records[serial] = record
            bodies.append(body)
            rows.append(
                public_machine(record["machine"]) | {"operation": "update" if old else "create"}
            )
        self.validate_conflicts(records)
        key = uuid.uuid4().hex
        atomic_json(
            self.directory / "plan-imports" / (key + ".json"),
            {"owner": owner, "expires": time.time() + 900, "bodies": bodies, "status": "preview"},
        )
        return {
            "preview_id": key,
            "rows": rows,
            "counts": {k: sum(r["operation"] == k for r in rows) for k in ("create", "update")},
        }

    def import_csv(self, key, owner):
        if (
            not isinstance(key, str)
            or not all(c in "0123456789abcdef" for c in key)
            or len(key) != 32
        ):
            raise ValueError("导入预览无效。")
        path = self.directory / "plan-imports" / (key + ".json")
        preview = json.loads(path.read_text())
        if (
            preview["owner"] != owner
            or preview["expires"] < time.time()
            or preview["status"] != "preview"
        ):
            raise ValueError("导入预览已失效，请重新预览。")
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            records = {
                r["serial"]: json.loads(r["data"]) for r in db.execute("SELECT * FROM device_plans")
            }
            prepared = [self.prepare(body, records) for body in preview["bodies"]]
            records.update(prepared)
            self.validate_conflicts(records)
            for serial, record in prepared:
                record["source"] = "csv"
                for value in record.get("inventory_sources", {}).values():
                    if value.get("source") == "manual":
                        value["source"] = "csv"
                self.put(db, serial, record)
        preview["status"] = "saved"
        atomic_json(path, preview)
        return {"status": "saved", "count": len(prepared), "exported": self.export()}

    def synchronization_state(self, serial, scope="hardware"):
        record = self.get(serial)
        path = (
            self.directory
            / "plan-sync"
            / (digest({"serial": serial, "revision": digest(record), "scope": scope}) + ".json")
        )
        return json.loads(path.read_text()).get("status") if path.exists() else "new"

    def synchronize(self, serial, scope="hardware"):
        """Called after execution confirmation. Preserve fields outside the requested scope."""
        record = self.get(serial)
        if not record:
            return
        planned = validate_machine(record["machine"], draft=scope == "bmc")
        rows = self.resources.inventory()
        actual = next((r for r in rows if r["chassis_serial_number"] == serial), None)
        if actual and actual["id"] != planned["id"]:
            raise ValueError("NICo身份与规划绑定不同，停止同步。")
        if scope == "bmc":
            if not actual:
                raise ValueError("BMC改址须先完成NICo身份登记。")
            target = copy.deepcopy(actual)
            for key in ("bmc_ip_address", "bmc_ip_allocation", "bmc_username", "bmc_password"):
                target[key] = planned.get(key)
            target["interfaces"] = [
                n for n in actual.get("interfaces", []) if n.get("role") != "host_bmc"
            ] + [n for n in planned.get("interfaces", []) if n.get("role") == "host_bmc"]
        else:
            target = planned
            if actual and use_current_bmc(serial):
                for key in (
                    "bmc_ip_address",
                    "bmc_ip_allocation",
                    "bmc_username",
                    "bmc_password",
                    "bmc_retain_credentials",
                ):
                    if key in actual:
                        target[key] = actual[key]
                    else:
                        target.pop(key, None)
                target["interfaces"] = [
                    n for n in target.get("interfaces", []) if n.get("role") != "host_bmc"
                ] + [n for n in actual.get("interfaces", []) if n.get("role") == "host_bmc"]
        if actual and "default_pause_ingestion_and_poweron" in actual:
            target["default_pause_ingestion_and_poweron"] = actual[
                "default_pause_ingestion_and_poweron"
            ]
        if actual and confirms_fields(actual, target):
            return
        path = (
            self.directory
            / "plan-sync"
            / (digest({"serial": serial, "revision": digest(record), "scope": scope}) + ".json")
        )
        previous = json.loads(path.read_text()) if path.exists() else {}
        if previous.get("status") in ("requesting", "needs_attention"):
            raise ValueError("上次NICo声明同步结果待核对，不自动重放。")
        atomic_json(
            path,
            {"status": "requesting", "serial": serial, "revision": digest(record), "scope": scope},
        )
        try:
            if actual:
                patch = machine_rpc(target)
                patch.pop("server_name", None)
                mask = [
                    k
                    for k in patch
                    if k not in ("id", "bmc_mac_address", "metadata", "host_lifecycle_profile")
                ]
                if scope == "bmc":
                    mask = [
                        "bmc_ip_address",
                        "bmc_ip_allocation",
                        "bmc_username",
                        "bmc_password",
                        "host_nics",
                    ]
                    patch = {k: v for k, v in patch.items() if k in mask or k == "id"}
                mask += ["metadata." + k for k in patch.get("metadata", {})]
                mask += [
                    "host_lifecycle_profile." + k for k in patch.get("host_lifecycle_profile", {})
                ]
                self.adapter.rpc(
                    "PatchExpectedMachines",
                    {"patches": [{"expected_machine": patch, "update_mask": {"paths": mask}}]},
                )
            else:
                result = self.adapter.rpc(
                    "CreateExpectedMachines",
                    {
                        "expected_machines": {"expected_machines": [machine_rpc(target)]},
                        "accept_partial_results": False,
                    },
                )
                if not result.get("results") or not all(
                    r.get("success") for r in result["results"]
                ):
                    raise RuntimeError("NICo身份登记尚未确认成功。")
            readback = next(
                (r for r in self.resources.inventory() if r["chassis_serial_number"] == serial),
                None,
            )
            if not readback or not confirms_fields(readback, target):
                raise RuntimeError("NICo声明读回尚未核对通过。")
            atomic_json(
                path,
                {
                    "status": "verified",
                    "serial": serial,
                    "revision": digest(record),
                    "scope": scope,
                },
            )
        except Exception as error:
            atomic_json(
                path,
                {
                    "status": "not_sent"
                    if getattr(error, "request_not_sent", False)
                    else "needs_attention",
                    "serial": serial,
                    "revision": digest(record),
                    "scope": scope,
                },
            )
            raise


def re_full_id(value):
    return len(value) == 32 and all(c in "0123456789abcdef" for c in value)
