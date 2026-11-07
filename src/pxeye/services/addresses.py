"""Interface address planning and durable, bounded DHCP handoff operations."""

import copy
import ipaddress
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from pxeye.common import atomic_json, digest, value_id
from pxeye.services.equipment import (
    snake,
    mac,
    ipv4,
    chassis_identity,
    verify_manager_mac,
    ROLE_LABELS,
)
from pxeye.common import redact
from pxeye.clients.errors import RedfishRequestError

MANAGER_ROLES = {"host_bmc", "switch_bmc", "pmc", "dpu_bmc"}
STATES = {
    "queued",
    "checking",
    "synchronizing",
    "assigning",
    "assignment_unknown",
    "requesting_dhcp",
    "dhcp_unknown",
    "waiting_dhcp",
    "dhcp_observed",
    "bmc_running",
    "bmc_needs_attention",
}


class ManagementAddresses:
    def __init__(self, adapter, resources, equipment):
        self.adapter, self.resources, self.equipment = adapter, resources, equipment
        self.directory = adapter.data / "config" / "management-addresses"
        for name in ("plans", "operations", "proofs"):
            (self.directory / name).mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        # Interrupted requests are observable, never automatically replayed.
        for record in self.records("operations"):
            previous = record["status"]
            if record.get("action") == "redfish_bmc":
                if previous == "bmc_running":
                    record.update(
                        status="bmc_needs_attention",
                        detail="服务中断；请核对新地址，未自动重复写入。",
                    )
                    for step in record["steps"]:
                        if step["status"] == "running":
                            step.update(status="failed", detail=record["detail"])
                    self.write("operations", record["id"], record)
                continue
            if previous in ("queued", "checking", "synchronizing", "assigning", "requesting_dhcp"):
                record.update(
                    status="assignment_unknown"
                    if previous in ("assigning", "synchronizing")
                    else "dhcp_unknown"
                    if previous == "requesting_dhcp"
                    else "blocked",
                    detail="服务更新中断了执行，请只读核对；未自动重发。",
                )
                self.write("operations", record["id"], record)

    def record(self, name, key):
        key = str(uuid.UUID(key))
        path = self.directory / name / (key + ".json")
        return json.loads(path.read_text()) if path.exists() else {}

    def write(self, name, key, data):
        atomic_json(self.directory / name / (str(uuid.UUID(key)) + ".json"), data)

    def records(self, name):
        return [json.loads(p.read_text()) for p in (self.directory / name).glob("*.json")]

    def pending(self, interface_id):
        return any(
            r.get("interface_id") == interface_id and r["status"] in STATES
            for r in self.records("operations")
        )

    def snapshot(self):
        snapshot = self.equipment.snapshot()
        rows = snapshot["allocations"]
        proofs = {
            p.stem: json.loads(p.read_text()) for p in (self.directory / "proofs").glob("*.json")
        }
        plans = {
            p.stem: json.loads(p.read_text()) for p in (self.directory / "plans").glob("*.json")
        }
        operations_by_interface = {}
        all_operations = self.records("operations")
        for operation in all_operations:
            operations_by_interface.setdefault(operation["interface_id"], []).append(operation)
        snapshot["address_operations"] = all_operations
        for row in rows:
            if row.get("role", "").startswith("dpu_"):
                row["parent_serial"] = row.get("serial", "")
                row["serial"] = ""
                row["address_kind"] = "dpu"
            proof = proofs.get(row["interface_id"], {})
            if proof.get("mac_address") == row["mac_address"]:
                row["serial"] = row.get("serial") or proof["serial"]
                row["address_kind"] = proof["kind"]
                row["credential_present"] = True
            plan = plans.get(row["interface_id"], {})
            row["address_revision"] = digest(plan) if plan else ""
            if plan:
                if not plan.get("target_from_device_plan"):
                    row["target_ip"] = plan["target_ip"]
                row["address_name"] = plan.get("name", "")
                row["serial"] = row.get("serial") or plan.get("serial", "")
                row["address_kind"] = plan.get("kind", row.get("address_kind", row["kind"]))
                row["credential_present"] = row.get("credential_present", False) or bool(
                    plan.get("credential")
                )
                if row["role"] == "unknown":
                    row["role"] = plan.get("role", "unknown")
                    row["role_label"] = ROLE_LABELS.get(row["role"], "未知接口")
            operations = operations_by_interface.get(row["interface_id"], [])
            if operations:
                operation = max(operations, key=lambda o: o["created_at"])
                row["address_operation"] = redact(operation)
            for item in snapshot["items"]:
                for port in item["ports"]:
                    if port["mac_address"] == row["mac_address"]:
                        port["target_ip"] = row.get("target_ip", "")
            if plan and not row.get("device_id"):
                key = "address-" + row["interface_id"]
                snapshot["items"].append(
                    {
                        "id": key,
                        "kind": plan["kind"],
                        "serial": row.get("serial", ""),
                        "name": plan.get("name", ""),
                        "status": "address_only",
                        "address_only": True,
                        "rack_id": "",
                        "declaration": {},
                        "ports": [
                            {
                                "mac_address": row["mac_address"],
                                "role": row["role"],
                                "role_label": row["role_label"],
                                "target_ip": row.get("target_ip", ""),
                                "observed": [copy.deepcopy(row)],
                            }
                        ],
                    }
                )
                row["device_id"] = key
        return snapshot

    def view(self, snapshot=None):
        snapshot = snapshot or self.snapshot()
        return {
            "interfaces": redact(snapshot["allocations"]),
            "operations": redact(snapshot["address_operations"]),
            "observed_at": snapshot["observed_at"],
        }

    def context(self, interface_id, snapshot=None):
        snapshot = snapshot or self.snapshot()
        rows = [a for a in snapshot["allocations"] if a["interface_id"] == interface_id]
        if len(rows) != 1 or snapshot["errors"]:
            raise ValueError("接口或类型声明读取不完整，请刷新。")
        row = rows[0]
        if row.get("identity_conflict") or row["network_name"] == "static-assignments":
            raise ValueError("接口归属冲突或属于系统地址段，不能改址。")
        if row["segment_type"] not in ("UNDERLAY", "HOST_INBAND", "HOSTINBAND"):
            raise ValueError("请选择物理管理网络接口。")
        if len(row["addresses"]) != 1 or ":" in row["addresses"][0]:
            raise ValueError("先完成 DHCP，取得此接口唯一 IPv4。")
        hardware = mac(row["mac_address"])
        if len([a for a in snapshot["allocations"] if a["mac_address"] == hardware]) != 1:
            raise ValueError("MAC 对应多个接口，无法确定改址对象。")
        serial = row.get("parent_serial") or row.get("serial")
        if row["kind"] == "server" and serial and self.resources.store.active(serial):
            raise ValueError("该设备有活动安装任务或待处理现场。")
        return row, snapshot

    def target_context(self, row, target, snapshot):
        target = ipv4(target)
        network = next((n for n in snapshot["networks"] if n["id"] == row["network_id"]), None)
        if not network or network["state"] != "READY":
            raise ValueError("管理子网尚未就绪。")
        prefixes = [
            p
            for p in network["prefixes"]
            if ipaddress.IPv4Address(target) in ipaddress.ip_network(p["prefix"])
        ]
        if len(prefixes) != 1:
            raise ValueError("目标 IP 必须属于当前子网；跨 VLAN 需先完成网络迁移。")
        prefix = prefixes[0]
        net = ipaddress.ip_network(prefix["prefix"])
        if target == prefix.get("gateway") or ipaddress.ip_address(target) in (
            net.network_address,
            net.broadcast_address,
        ):
            raise ValueError("目标地址不能是网关、网络地址或广播地址。")
        for entry in snapshot["allocations"]:
            if entry["interface_id"] != row["interface_id"] and (
                target in entry["addresses"] or target == entry.get("target_ip")
            ):
                raise ValueError("目标 IP 已被其他接口使用或规划。")
        for item in snapshot["items"]:
            for port in item["ports"]:
                if port["mac_address"] != row["mac_address"] and port.get("target_ip") == target:
                    raise ValueError("目标 IP 已被另一设备声明。")
        for machine in snapshot["server_declarations"]:
            for hardware, address in [
                (machine["bmc_mac_address"], machine.get("bmc_ip_address"))
            ] + [(n.get("mac_address"), n.get("fixed_ip")) for n in machine.get("interfaces", [])]:
                if address == target and hardware != row["mac_address"]:
                    raise ValueError("目标 IP 已在原生主机声明中使用。")
        for plan in self.records("plans"):
            if plan["interface_id"] != row["interface_id"] and plan.get("target_ip") == target:
                raise ValueError("目标 IP 已保存于其他接口规划。")
        return target, network, prefix

    def save(self, body):
        allowed = {
            "interface_id",
            "revision",
            "mac_address",
            "target_ip",
            "name",
            "serial",
            "kind",
            "role",
            "username",
            "password",
        }
        if set(body) - allowed:
            raise ValueError("地址规划字段无效。")
        with self.equipment.lock, self.lock:
            row, snapshot = self.context(body.get("interface_id"))
            if mac(body.get("mac_address")) != row["mac_address"]:
                raise ValueError("不能修改已发现的 MAC；硬件替换请重新发现新接口。")
            old = self.record("plans", row["interface_id"])
            if body.get("revision", "") != (digest(old) if old else "") or self.pending(
                row["interface_id"]
            ):
                raise ValueError("规划已变化或有未完成操作，请先核对。")
            target, _, _ = self.target_context(row, body.get("target_ip"), snapshot)
            serial = str(body.get("serial", row.get("serial", ""))).strip()
            if row.get("serial") and serial != row["serial"]:
                raise ValueError("SN 与设备清单不符。")
            if len(serial) > 128 or any(ord(c) < 32 for c in serial):
                raise ValueError("SN 格式无效。")
            actual_kind = row.get("address_kind", row["kind"])
            kind = body.get("kind", actual_kind)
            if kind not in ("server", "switch", "power_shelf", "dpu", "unknown", "other"):
                raise ValueError("设备类型无效。")
            if row["kind"] != "unknown" and kind != actual_kind:
                raise ValueError("设备类型由现有归属决定。")
            role = body.get("role", row["role"])
            if role not in ROLE_LABELS or role != row["role"] and row["kind"] != "unknown":
                raise ValueError("接口角色与已知设备归属不符。")
            if row["kind"] == "unknown" and role == "host":
                raise ValueError("LOM 需先关联服务器规划。")
            credential = copy.deepcopy(old.get("credential", {}))
            if body.get("username") or body.get("password"):
                credential = {
                    "username": body.get("username", ""),
                    "password": body.get("password") or credential.get("password", ""),
                }
                if any(
                    not isinstance(v, str) or not v or len(v) > 256 or any(ord(c) < 32 for c in v)
                    for v in credential.values()
                ):
                    raise ValueError("账号和密码需成对提供，已有密码留空保留。")
            name = str(body.get("name", "")).strip()
            if len(name) > 256 or any(ord(c) < 32 for c in name):
                raise ValueError("名称格式无效。")
            plan = {
                "interface_id": row["interface_id"],
                "mac_address": row["mac_address"],
                "network_id": row["network_id"],
                "target_ip": target,
                "serial": serial,
                "kind": kind,
                "role": role,
                "name": name,
                "credential": credential,
                "saved_at": time.time(),
            }
            if row["kind"] == "server":
                # Reuse the existing device plan. Do not keep a second host address authority.
                from pxeye.services.device_plans import DevicePlans

                plans = DevicePlans(self.adapter, self.resources)
                current = plans.get(row.get("parent_serial") or row["serial"], current=True)
                machine = copy.deepcopy(current["machine"])
                if row["role"] == "host_bmc":
                    machine.update(bmc_ip_address=target, bmc_ip_allocation="Fixed")
                nic = next(
                    (
                        n
                        for n in machine.get("interfaces", [])
                        if n.get("mac_address", "").lower() == row["mac_address"]
                    ),
                    None,
                )
                if nic:
                    # ExpectedMachine uses a title-cased BMC policy but lower-case
                    # HostNic policies; keep the two protobuf enums distinct.
                    nic.update(fixed_ip=target, ip_allocation="fixed")
                elif row["role"] != "host_bmc":
                    raise ValueError("接口尚未关联设备规划，请先在设备配置中补齐该 MAC。")
                intent = copy.deepcopy(current["intent"])
                intent.pop("serial", None)
                intent.pop("login_ref", None)
                plans.save(
                    {
                        "id": machine["id"],
                        "revision": digest(current),
                        "machine": machine,
                        "intent": intent,
                    }
                )
                plan.pop("target_ip")
                # Only optional own-interface credentials/name are stored here for servers.
                plan["target_from_device_plan"] = True
            self.write("plans", row["interface_id"], plan)
            return {"saved": True, "revision": digest(plan), "detail": "地址规划已保存。"}

    def credentials(self, row, snapshot):
        saved = self.record("plans", row["interface_id"]).get("credential")
        if saved:
            return saved
        proof = self.record("proofs", row["interface_id"])
        if proof.get("mac_address") == row["mac_address"]:
            return proof["credential"]
        if row.get("role") in ("dpu_bmc", "dpu_os", "nvos", "host"):
            return {}
        item = next((i for i in snapshot["items"] if i["id"] == row.get("device_id")), {})
        declaration = item.get("declaration", {})
        if row["kind"] == "server":
            declaration = next(
                (s for s in snapshot["servers"] if s["chassis_serial_number"] == row.get("serial")),
                {},
            )
        if declaration.get("bmc_username") and declaration.get("bmc_password"):
            return {
                "username": declaration["bmc_username"],
                "password": declaration["bmc_password"],
            }
        proofs = [
            p
            for p in self.equipment.records("proofs")
            if p.get("interface", {}).get("interface_id") == row["interface_id"]
            and p.get("verified_ip") == row["addresses"][0]
        ]
        return max(proofs, key=lambda p: p["verified_at"])["credentials"] if proofs else {}

    def identify_many(self, body):
        if set(body) != {"interface_ids", "username", "password"}:
            raise ValueError("请选择接口并提供统一 BMC 账号密码。")
        ids = body["interface_ids"]
        if not isinstance(ids, list) or not 1 <= len(ids) <= 256 or len(set(ids)) != len(ids):
            raise ValueError("每批选择1至256个不同接口。")
        credential = {"username": body["username"], "password": body["password"]}
        if any(
            not isinstance(v, str) or not v or len(v) > 256 or any(ord(c) < 32 for c in v)
            for v in credential.values()
        ):
            raise ValueError("请填写有效账号密码。")
        snapshot = self.snapshot()

        def read(iid):
            try:
                row, _ = self.context(iid, snapshot)
                if row.get("role") in ("host", "nvos", "dpu_os"):
                    raise ValueError("此接口不提供 BMC 身份读取。")
                identity = self.identity(row, row["addresses"][0], credential)
                self.write(
                    "proofs",
                    iid,
                    {
                        "mac_address": row["mac_address"],
                        "serial": identity["serial"],
                        "kind": identity["kind"],
                        "credential": credential,
                        "verified_at": time.time(),
                        "verified_ip": row["addresses"][0],
                    },
                )
                return {"interface_id": iid, "passed": True, "identity": identity}
            except (ValueError, RuntimeError) as error:
                return {"interface_id": iid, "passed": False, "detail": str(error)}

        with ThreadPoolExecutor(max_workers=4) as pool:
            return {"rows": list(pool.map(read, ids))}

    def identity(self, row, address, credential):
        kind = (
            "dpu"
            if row.get("role", "").startswith("dpu_")
            else row.get("address_kind", row["kind"])
        )
        if kind == "server" and row.get("role") not in ("dpu_bmc", "dpu_os"):
            from pxeye.services.discovery import read_identity

            identity = {
                "kind": "server",
                **read_identity(self.adapter, address, row["mac_address"], credential),
            }
        else:
            identity = chassis_identity(self.adapter, address, credential)
            if identity["kind"] == "unknown":
                systems = self.adapter.redfish_read(address, "/redfish/v1/Systems", credential).get(
                    "Members", []
                )
                if len(systems) > 16:
                    raise ValueError("Systems 数量超限。")
                reports = [
                    self.adapter.redfish_read(address, x["@odata.id"], credential) for x in systems
                ]
                reports = [r for r in reports if r.get("SerialNumber")]
                if len(reports) != 1:
                    raise ValueError("无法读取唯一设备 SN。")
                report = reports[0]
                identity = {
                    "kind": "dpu"
                    if str(report.get("Id", "")).lower() in ("bluefield", "bluefield_0")
                    else "other",
                    "serial": report["SerialNumber"].strip(),
                }
            verify_manager_mac(self.adapter, address, row["mac_address"], credential)
        if row.get("serial") and row["serial"] != identity["serial"]:
            raise ValueError("BMC 返回的 SN 与地址规划不同。")
        if kind not in ("unknown", "other") and identity["kind"] != kind:
            raise ValueError("实际设备类型与规划不符。")
        return identity

    def manager(self, row, address, credential):
        if row.get("role") in ("host", "nvos", "dpu_os"):
            raise ValueError("此接口需通过设备侧续租；不支持 BMC 管理控制器重启。")
        identity = self.identity(row, address, credential)
        managers = self.adapter.redfish_read(address, "/redfish/v1/Managers", credential).get(
            "Members", []
        )
        if len(managers) > 8:
            raise ValueError("Manager 数量超限。")
        matches = []
        for member in managers:
            path = member["@odata.id"]
            manager = self.adapter.redfish_read(address, path, credential)
            collection = (manager.get("EthernetInterfaces") or {}).get("@odata.id")
            if not collection:
                continue
            ports = self.adapter.redfish_read(address, collection, credential).get("Members", [])
            if len(ports) > 32:
                raise ValueError("管理接口数量超限。")
            for port in ports:
                nic = self.adapter.redfish_read(address, port["@odata.id"], credential)
                if str(nic.get("MACAddress", "")).lower() != row["mac_address"]:
                    continue
                reset = manager.get("Actions", {}).get("#Manager.Reset", {})
                allowed = reset.get("ResetType@Redfish.AllowableValues", [])
                if not allowed and reset.get("@Redfish.ActionInfo"):
                    info = self.adapter.redfish_read(
                        address, reset["@Redfish.ActionInfo"], credential
                    )
                    allowed = next(
                        (
                            p.get("AllowableValues", [])
                            for p in info.get("Parameters", [])
                            if p.get("Name") == "ResetType"
                        ),
                        [],
                    )
                enabled = nic.get("DHCPv4", {}).get("DHCPEnabled")
                if type(enabled) is not bool:
                    raise ValueError("管理接口未提供 DHCPv4 控制能力。")
                if enabled and ("GracefulRestart" not in allowed or not reset.get("target")):
                    raise ValueError("管理控制器未声明 GracefulRestart，需人工重新 DHCP。")
                if enabled is False:
                    self.require_patch_capability(
                        address,
                        port["@odata.id"],
                        credential,
                        "管理接口未声明 PATCH 能力，需人工启用 DHCP。",
                    )
                # Only links below this exact Manager are eligible for a later write.
                if (enabled and not reset["target"].startswith(path + "/Actions/")) or not port[
                    "@odata.id"
                ].startswith(path + "/EthernetInterfaces/"):
                    raise ValueError("Redfish 管理操作路径与当前 Manager 不匹配。")
                matches.append(
                    {
                        "nic_path": port["@odata.id"],
                        "reset_path": reset.get("target"),
                        "dhcp_enabled": enabled,
                        "identity": identity,
                    }
                )
        if len(matches) != 1:
            raise ValueError("未找到此 MAC 对应的唯一管理接口。")
        return matches[0]

    def require_patch_capability(
        self, address, path, credential, detail="该 Redfish 管理接口未声明 PATCH 能力。"
    ):
        """Use OPTIONS when implemented; tolerate controllers that reject OPTIONS itself."""
        try:
            result = self.adapter.redfish_request(address, path, credential, method="OPTIONS")
        except RedfishRequestError as error:
            if error.status not in (400, 405, 501):
                raise
            return
        allowed = result.get("allow", [])
        if allowed and "PATCH" not in allowed:
            raise ValueError(detail)

    def redfish_interface(self, row, address, credential):
        """Resolve one Redfish Manager EthernetInterface without assuming DHCP mode."""
        if row.get("role") in ("host", "nvos", "dpu_os"):
            raise ValueError("该接口不由 Redfish Manager 管理，需由操作系统或设备管理面配置。")
        identity = self.identity(row, address, credential)
        managers = self.adapter.redfish_read(address, "/redfish/v1/Managers", credential).get(
            "Members", []
        )
        if len(managers) > 8:
            raise ValueError("Manager 数量超限。")
        matches = []
        for member in managers:
            manager_path = member.get("@odata.id", "")
            manager = self.adapter.redfish_read(address, manager_path, credential)
            collection = (manager.get("EthernetInterfaces") or {}).get("@odata.id")
            if not collection:
                continue
            ports = self.adapter.redfish_read(address, collection, credential).get("Members", [])
            if len(ports) > 32:
                raise ValueError("管理接口数量超限。")
            for port in ports:
                path = port.get("@odata.id", "")
                nic = self.adapter.redfish_read(address, path, credential)
                if str(nic.get("MACAddress", "")).lower() != row["mac_address"]:
                    continue
                self.require_patch_capability(address, path, credential)
                reset = manager.get("Actions", {}).get("#Manager.Reset", {})
                matches.append(
                    {
                        "nic_path": path,
                        "reset_path": reset.get("target"),
                        "current": nic,
                        "identity": identity,
                    }
                )
        if len(matches) != 1:
            raise ValueError("未找到此 MAC 对应的唯一 Redfish 管理接口。")
        return matches[0]

    def _selected_rows(self, device_ids, *, manager_only=False):
        if (
            not isinstance(device_ids, list)
            or not 1 <= len(device_ids) <= 256
            or len(set(device_ids)) != len(device_ids)
        ):
            raise ValueError("请选择1至256台不同设备。")
        snapshot = self.snapshot()
        known = {item["id"] for item in snapshot["items"]}
        if any(key not in known for key in device_ids):
            raise ValueError("设备清单已变化，请刷新后重试。")
        rows = [row for row in snapshot["allocations"] if row.get("device_id") in device_ids]
        if manager_only:
            rows = [row for row in rows if row.get("role") in MANAGER_ROLES]
        return rows, snapshot

    @staticmethod
    def missing_device_rows(snapshot, device_ids, present):
        items = {item["id"]: item for item in snapshot["items"]}
        return [
            {"device_id": key, "serial": items[key].get("serial", "")}
            for key in device_ids
            if key not in present
        ]

    def batch_refresh(self, body):
        if set(body) != {"device_ids"}:
            raise ValueError("刷新参数无效。")
        rows, snapshot = self._selected_rows(body["device_ids"], manager_only=True)
        present = {row.get("device_id") for row in rows}
        work = rows + self.missing_device_rows(snapshot, body["device_ids"], present)

        def read(row):
            device_id = row.get("device_id")
            if not row.get("interface_id"):
                return {
                    "device_id": device_id,
                    "passed": False,
                    "detail": "设备没有 BMC / PMC 管理接口。",
                }
            try:
                credential = self.credentials(row, snapshot)
                if not credential:
                    raise ValueError("未保存 BMC / PMC 凭据。")
                identity = self.identity(row, row["addresses"][0], credential)
                proof = {
                    "mac_address": row["mac_address"],
                    "serial": identity["serial"],
                    "kind": identity["kind"],
                    "credential": credential,
                    "verified_at": time.time(),
                    "verified_ip": row["addresses"][0],
                }
                self.write("proofs", row["interface_id"], proof)
                return {
                    "device_id": device_id,
                    "interface_id": row["interface_id"],
                    "passed": True,
                    "serial": identity["serial"],
                    "kind": identity["kind"],
                    "model": identity.get("model", ""),
                    "address": row["addresses"][0],
                    "refreshed_at": proof["verified_at"],
                }
            except (ValueError, RuntimeError) as error:
                return {
                    "device_id": device_id,
                    "interface_id": row.get("interface_id"),
                    "passed": False,
                    "serial": row.get("serial", ""),
                    "detail": str(error),
                }

        with ThreadPoolExecutor(max_workers=4) as pool:
            return {"rows": list(pool.map(read, work)), "observed_at": time.time()}

    def bmc_jobs(self):
        from pxeye.services.bmc_jobs import BMCJobs

        return BMCJobs(self)

    def batch_redfish_preview(self, body, owner):
        if body.get("scope") == "bmc":
            return self.bmc_jobs().preview(body, owner)
        if set(body) != {"device_ids", "scope"} or body.get("scope") != "management":
            raise ValueError("批量改址参数无效。")
        rows, snapshot = self._selected_rows(body["device_ids"])
        candidates = [row for row in rows if row.get("role") in ("host", "nvos", "dpu_os")]
        present = {row.get("device_id") for row in candidates}
        candidates += self.missing_device_rows(snapshot, body["device_ids"], present)
        results = [
            {
                k: row.get(k, "")
                for k in (
                    "device_id",
                    "interface_id",
                    "serial",
                    "role_label",
                    "mac_address",
                    "target_ip",
                )
            }
            | {
                "passed": False,
                "current_ip": row["addresses"][0] if len(row.get("addresses", [])) == 1 else "",
                "detail": "该管理口不由 Redfish Manager 配置；请通过 OS、NVOS 或对应设备接口更新。",
            }
            for row in candidates
        ]
        token = self.equipment.create_check(
            "redfish-address-management", owner, {"scope": "management", "rows": results}
        )
        return {"id": token, "scope": "management", "rows": results, "ready": 0}

    def batch_redfish_apply(self, body, owner, actor):
        if set(body) != {"preflight_id", "confirm"} or body.get("confirm") is not True:
            raise ValueError("请确认执行已通过预检的 Redfish 改址。")
        token = body["preflight_id"]
        check = self.equipment.claim_check(token, "redfish-address-bmc", owner)
        return self.bmc_jobs().apply(check, token, actor)

    def check(self, interface_id, snapshot=None, restart=False, operation_id=None):
        row, snapshot = self.context(interface_id, snapshot)
        plan = self.record("plans", interface_id)
        target = row.get("target_ip") or row["addresses"][0]
        target, network, prefix = self.target_context(row, target, snapshot)
        if any(
            o["interface_id"] == interface_id and o["status"] in STATES and o["id"] != operation_id
            for o in self.records("operations")
        ):
            raise ValueError("此接口已有未完成操作，请先核对。")
        if row.get("role") == "host":
            raise ValueError("LOM 地址规划已保存；正式 OS 地址在安装任务中应用。")
        if (
            self.equipment.pending("interface-" + interface_id)
            or row.get("device_id")
            and self.equipment.pending(row["device_id"])
        ):
            raise ValueError("此接口或设备有原生操作待核对。")
        if target != row["addresses"][0]:
            current = ipaddress.ip_address(row["addresses"][0])
            net = ipaddress.ip_network(prefix["prefix"])
            if current not in net or int(current) - int(net.network_address) >= int(
                prefix.get("reserveFirst", 0)
            ):
                raise ValueError("旧地址仍在动态池内，需先保护旧租约地址；可先固定当前 IP。")
        credential = self.credentials(row, snapshot)
        capability = None
        if restart:
            if not credential:
                raise ValueError("自动重新 DHCP 需要此管理接口的账号密码。")
            capability = self.manager(row, row["addresses"][0], credential)
        elif (
            credential
            and target != row["addresses"][0]
            and row.get("role") not in ("host", "nvos", "dpu_os")
        ):
            self.identity(row, row["addresses"][0], credential)
        elif target != row["addresses"][0] and row.get("role") in MANAGER_ROLES:
            raise ValueError("管理控制器改址前需提供账号密码并核对 SN/MAC。")
        fingerprint = digest(
            {
                "row": {
                    k: row.get(k)
                    for k in (
                        "interface_id",
                        "mac_address",
                        "network_id",
                        "addresses",
                        "target_ip",
                        "kind",
                        "role",
                        "serial",
                        "device_id",
                    )
                },
                "network": network["revision"],
                "plan": plan,
            }
        )
        return {
            "interface_id": interface_id,
            "mac_address": row["mac_address"],
            "serial": row.get("serial", ""),
            "kind": row.get("address_kind", row["kind"]),
            "role": row["role"],
            "role_label": row["role_label"],
            "current_ip": row["addresses"][0],
            "target_ip": target,
            "network_id": row["network_id"],
            "fingerprint": fingerprint,
            "restart": restart,
            "capability": capability,
            "detail": "固定地址并请求管理控制器重新 DHCP" if restart else "固定分配；等待设备续租",
        }

    def preview(self, body, owner):
        if set(body) != {"interface_ids", "restart"} or type(body["restart"]) is not bool:
            raise ValueError("请选择接口和 DHCP 执行方式。")
        ids = body["interface_ids"]
        if not isinstance(ids, list) or not 1 <= len(ids) <= 256 or len(set(ids)) != len(ids):
            raise ValueError("每批选择1至256个不同接口。")
        snapshot = self.snapshot()

        def read(iid):
            try:
                return self.check(iid, snapshot, body["restart"]) | {"passed": True}
            except (ValueError, RuntimeError) as error:
                row = next((a for a in snapshot["allocations"] if a["interface_id"] == iid), {})
                return {
                    "interface_id": iid,
                    "passed": False,
                    "serial": row.get("serial", ""),
                    "mac_address": row.get("mac_address", ""),
                    "current_ip": ", ".join(row.get("addresses", [])),
                    "target_ip": row.get("target_ip", ""),
                    "detail": str(error),
                }

        with ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(read, ids))
        token = self.equipment.create_check(
            "addresses", owner, {"rows": rows, "restart": body["restart"]}
        )
        return {"id": token, "rows": redact(rows), "passed": any(r["passed"] for r in rows)}

    def start(self, body, owner, actor):
        if set(body) != {"preflight_id", "interface_ids"}:
            raise ValueError("请核对接口预览后提交。")
        with self.equipment.lock, self.lock:
            check = self.equipment.claim_check(body["preflight_id"], "addresses", owner)
            ids = body["interface_ids"]
            if not isinstance(ids, list) or not ids or len(set(ids)) != len(ids):
                raise ValueError("请选择通过检查的接口。")
            rows = [r for r in check["rows"] if r["interface_id"] in ids and r["passed"]]
            if len(rows) != len(ids):
                raise ValueError("不能提交未通过检查的接口。")
            if any(self.pending(row["interface_id"]) for row in rows):
                raise ValueError("所选接口已有未完成操作，请先核对。")
            operations = []
            for row in rows:
                key = str(uuid.uuid4())
                operation = row | {
                    "id": key,
                    "batch_id": body["preflight_id"],
                    "actor": actor,
                    "created_at": time.time(),
                    "status": "queued",
                }
                self.write("operations", key, operation)
                operations.append(key)

            def work():
                with ThreadPoolExecutor(max_workers=4) as pool:
                    list(pool.map(self.run, operations))

            threading.Thread(target=work, name="management-addresses", daemon=True).start()
            return {
                "ids": operations,
                "status": "queued",
                "detail": "已提交；可刷新查看逐接口结果。",
            }

    def run(self, key):
        record = self.record("operations", key)
        try:
            with self.equipment.lock, self.lock:
                # Exclude this queued record when rechecking, then restore the durable queued state.
                self.write("operations", key, record | {"status": "checking"})
                checked = self.check(
                    record["interface_id"], restart=record["restart"], operation_id=key
                )
                if checked["fingerprint"] != record["fingerprint"] or checked.get(
                    "capability"
                ) != record.get("capability"):
                    raise ValueError("接口、规划、网络或管理能力已变化，请重新预览。")
                row, snapshot = self.context(record["interface_id"])
                credential = self.credentials(row, snapshot)
                if row["kind"] == "server" and row["role"] == "host_bmc":
                    record["status"] = "synchronizing"
                    self.write("operations", key, record)
                    from pxeye.services.device_plans import DevicePlans

                    DevicePlans(self.adapter, self.resources).synchronize(row["serial"], "bmc")
                record.update(status="assigning", last_dhcp_before=row.get("last_dhcp"))
                self.write("operations", key, record)
                self.adapter.rpc(
                    "AssignStaticAddress",
                    {
                        "interface_id": {"value": record["interface_id"]},
                        "ip_address": record["target_ip"],
                    },
                )
                if not self.assigned(record):
                    raise RuntimeError("固定地址写入未能读回。")
                record.update(status="waiting_dhcp", assignment_verified_at=time.time())
                self.write("operations", key, record)
                if record["restart"]:
                    capability = record["capability"]
                    record["status"] = "requesting_dhcp"
                    self.write("operations", key, record)
                    if not capability["dhcp_enabled"]:
                        self.adapter.redfish_request(
                            record["current_ip"],
                            capability["nic_path"],
                            credential,
                            method="PATCH",
                            body={"DHCPv4": {"DHCPEnabled": True}},
                        )
                        record["dhcp_enable_sent"] = True
                        self.write("operations", key, record)
                    else:
                        # Already DHCP-enabled: restart only the exact management controller.
                        self.adapter.redfish_request(
                            record["current_ip"],
                            capability["reset_path"],
                            credential,
                            method="POST",
                            body={"ResetType": "GracefulRestart"},
                        )
                    record.update(status="waiting_dhcp", dhcp_request_sent=True)
                    self.write("operations", key, record)
            # Bounded observation. Service restart never resumes or repeats a write.
            deadline = time.monotonic() + (300 if record["restart"] else 0)
            while True:
                result = self.verify({"id": key}, record["actor"])
                if result["status"] == "verified" or time.monotonic() >= deadline:
                    break
                time.sleep(10)
        except Exception as error:
            current = self.record("operations", key)
            status = current["status"]
            current.update(
                status="assignment_unknown"
                if status in ("assigning", "synchronizing")
                else "dhcp_unknown"
                if status == "requesting_dhcp"
                else "blocked",
                detail=str(error)
                if isinstance(error, (ValueError, RuntimeError))
                else "执行失败；请只读核对。",
            )
            self.write("operations", key, current)

    def assigned(self, record):
        addresses = snake(
            self.adapter.rpc(
                "FindInterfaceAddresses", {"interface_id": {"value": record["interface_id"]}}
            )
        ).get("addresses", [])
        links = snake(self.adapter.rpc("FindInterfaces", {})).get("interfaces", [])
        link = next((n for n in links if value_id(n["id"]) == record["interface_id"]), {})
        return (
            link.get("mac_address", "").lower() == record["mac_address"]
            and value_id(link.get("segment_id")) == record["network_id"]
            and link.get("address") == [record["target_ip"]]
            and any(
                a["address"] == record["target_ip"]
                and str(a.get("allocation_type", "")).lower() == "static"
                for a in addresses
            )
        )

    def verify(self, body, actor):
        with self.lock:
            record = self.record("operations", body.get("id"))
            if not record:
                raise ValueError("操作记录不存在。")
            if record.get("action") == "redfish_bmc":
                raise ValueError("请从 BMC 更新记录查看进度或核对并完成同步。")
            if record["status"] in (
                "queued",
                "checking",
                "synchronizing",
                "assigning",
                "requesting_dhcp",
            ):
                return redact(record)
            try:
                if not self.assigned(record):
                    record.update(
                        status="assignment_unknown", detail="NICo 分配与本次规划不一致，请核对。"
                    )
                else:
                    row, snapshot = self.context(record["interface_id"])
                    credential = self.credentials(row, snapshot)
                    actual = False
                    if credential and row.get("role") not in ("host", "nvos", "dpu_os"):
                        self.identity(row, record["target_ip"], credential)
                        # Reachability plus identity alone is insufficient; require reported IP on the exact MAC.
                        manager = self.adapter.redfish_read(
                            record["target_ip"], "/redfish/v1/Managers", credential
                        )
                        for member in manager.get("Members", [])[:8]:
                            report = self.adapter.redfish_read(
                                record["target_ip"], member["@odata.id"], credential
                            )
                            path = (report.get("EthernetInterfaces") or {}).get("@odata.id")
                            if not path:
                                continue
                            ports = self.adapter.redfish_read(record["target_ip"], path, credential)
                            for p in ports.get("Members", [])[:32]:
                                nic = self.adapter.redfish_read(
                                    record["target_ip"], p["@odata.id"], credential
                                )
                                if str(nic.get("MACAddress", "")).lower() == record["mac_address"]:
                                    actual |= any(
                                        a.get("Address") == record["target_ip"]
                                        for a in nic.get("IPv4Addresses", [])
                                    )
                    else:
                        observed = bool(
                            row.get("last_dhcp")
                            and row["last_dhcp"] != record.get("last_dhcp_before")
                        )
                        record.update(
                            status="dhcp_observed" if observed else "waiting_dhcp",
                            detail="已见新 DHCP 请求；客户端采用地址需设备侧核对。"
                            if observed
                            else "固定分配已读回；等待设备续租，随后刷新核对。",
                        )
                    if credential and row.get("role") not in ("host", "nvos", "dpu_os"):
                        record.update(
                            status="verified" if actual else "waiting_dhcp",
                            detail="固定地址已生效，设备采用已核对。"
                            if actual
                            else "固定分配已读回；等待设备采用目标地址。",
                        )
                        if actual and row["kind"] == "server" and row["role"] == "host_bmc":
                            from pxeye.services.bmc_addresses import BMCAddresses

                            machine = next(
                                s
                                for s in snapshot["servers"]
                                if s["chassis_serial_number"] == row["serial"]
                            )
                            address = BMCAddresses(self.adapter, self.resources)
                            address.save(
                                row["serial"],
                                {
                                    "id": record["id"],
                                    "status": "verified",
                                    "current_ip": record["target_ip"],
                                    "planned_ip": record["target_ip"],
                                    "bmc_mac": row["mac_address"],
                                    "declaration_revision": digest(machine),
                                    "verified_at": time.time(),
                                    "detail": record["detail"],
                                },
                            )
            except (RuntimeError, ValueError):
                record.update(
                    status="waiting_dhcp"
                    if record.get("assignment_verified_at")
                    else "assignment_unknown",
                    detail="等待设备采用目标地址；可在设备侧重新 DHCP 后核对。",
                )
            record.update(checked_at=time.time(), checked_by=actor)
            self.write("operations", record["id"], record)
            return redact(record)
