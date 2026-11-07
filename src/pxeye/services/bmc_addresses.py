"""Explicit BMC allocation and identity verification, independent of OS jobs."""

import ipaddress
import json
import time
import uuid

from pxeye.common import sha
from pxeye.services.discovery import read_identity
from pxeye.common import atomic_json, digest, value_id


class BMCAddresses:
    def __init__(self, adapter, resources):
        self.adapter, self.resources = adapter, resources
        self.directory = adapter.data / "config" / "bmc-addresses"

    def record(self, serial):
        path = self.directory / (sha(serial) + ".json")
        return json.loads(path.read_text()) if path.exists() else {}

    def save(self, serial, record):
        atomic_json(self.directory / (sha(serial) + ".json"), record)

    def contact(self, row, links):
        record = self.record(row["chassis_serial_number"])
        if record.get("current_ip"):
            return record["current_ip"]
        proofs = []
        for path in (self.adapter.data / "config" / "discovery").glob("*.json"):
            proof = json.loads(path.read_text())
            if proof.get("expected_id") == row["id"] and proof.get("verified_ip"):
                proofs.append(proof)
        if proofs:
            return max(proofs, key=lambda p: p.get("verified_at", 0))["verified_ip"]
        addresses = {
            a
            for link in links
            if link.get("macAddress", "").lower() == row["bmc_mac_address"].lower()
            for a in link.get("address", [])
            if ":" not in a
        }
        return (
            next(iter(addresses))
            if len(addresses) == 1
            else row.get("bmc_ip_address")
            if not addresses
            else None
        )

    def view(self, row, links=None):
        links = (
            self.adapter.rpc("FindInterfaces", {}).get("interfaces", []) if links is None else links
        )
        record = self.record(row["chassis_serial_number"])
        current, desired = self.contact(row, links), row.get("bmc_ip_address")
        state = record.get("status", "unverified")
        if record.get("declaration_revision") != digest(row) and state == "verified":
            state = "unverified"
        if (
            current
            and desired
            and current != desired
            and state not in ("assigning", "waiting_address", "needs_attention")
        ):
            state = "planned"
        return {
            "current_ip": current,
            "planned_ip": desired,
            "status": state,
            "verified_at": record.get("verified_at"),
            "operation_id": record.get("id"),
            "detail": record.get("detail"),
            "revision": digest(record),
        }

    def row(self, serial):
        rows = self.resources.planned_inventory()
        matches = [r for r in rows if r["chassis_serial_number"] == serial]
        if len(matches) != 1:
            raise ValueError("设备序列号不存在或不唯一。")
        return matches[0], rows

    def identity(self, row, ip):
        if not ip or not row.get("bmc_username") or not row.get("bmc_password"):
            raise ValueError("需要可达 BMC 地址和用户提供的账号密码。")
        identity = read_identity(
            self.adapter,
            ip,
            row["bmc_mac_address"].lower(),
            {"username": row["bmc_username"], "password": row["bmc_password"]},
        )
        if identity["serial"] != row["chassis_serial_number"]:
            raise ValueError("目标 BMC 的 SN 与设备清单不同，已阻断。")
        return identity

    def plan(self, serial):
        row, rows = self.row(serial)
        self.resources.check_address_operation(row)
        if self.resources.store and self.resources.store.active(serial):
            raise ValueError("设备有安装任务或待处理现场，不能修改 BMC 地址。")
        links = self.adapter.rpc("FindInterfaces", {}).get("interfaces", [])
        matches = [
            n for n in links if n.get("macAddress", "").lower() == row["bmc_mac_address"].lower()
        ]
        if len(matches) != 1:
            raise ValueError("未找到唯一 BMC 接口；先完成 DHCP 发现。")
        link = matches[0]
        if link.get("switchId") or link.get("powerShelfId") or link.get("attachedDpuMachineId"):
            raise ValueError("该接口属于交换机、供电设备或 DPU，不能作为主机 BMC 应用。")
        if row.get("bmc_ip_allocation") != "Fixed":
            raise ValueError("请在设备配置中选择固定 BMC 地址并保存规划。")
        target = ipaddress.IPv4Address(row.get("bmc_ip_address", ""))
        segments = self.resources.networks()
        segment = next((n for n in segments if n["id"] == value_id(link.get("segmentId"))), None)
        if not segment or segment["segment_type"] != "UNDERLAY" or segment["state"] != "READY":
            raise ValueError("当前 BMC Underlay 网络尚未就绪。")
        prefixes = [p for p in segment["prefixes"] if target in ipaddress.ip_network(p["prefix"])]
        if len(prefixes) != 1:
            raise ValueError("BMC 跨子网迁移需要先完成现场网络迁移。")
        prefix, current = prefixes[0], self.contact(row, links)
        net = ipaddress.ip_network(prefix["prefix"])
        if target in (net.network_address, net.broadcast_address) or str(target) == prefix.get(
            "gateway"
        ):
            raise ValueError("规划 BMC 地址不能是网络地址、广播地址或网关。")
        for other in rows:
            if other["id"] != row["id"] and (
                other.get("bmc_ip_address") == str(target)
                or any(n.get("fixed_ip") == str(target) for n in other.get("interfaces", []))
            ):
                raise ValueError("规划地址已在另一设备声明中使用。")
        if any(
            str(target) in n.get("address", []) and value_id(n["id"]) != value_id(link["id"])
            for n in links
        ):
            raise ValueError("规划地址已由另一 NICo 接口使用。")
        if current != str(target):
            if any(
                link.get(k)
                for k in ("machineId", "attachedDpuMachineId", "switchId", "powerShelfId")
            ):
                raise ValueError("已接管设备的 BMC 入口迁移需单独维护，当前只支持未接管设备。")
            if not current or ipaddress.ip_address(current) not in net:
                raise ValueError("当前 BMC 地址不明确或不属于本子网，不能自动切换。")
            offset = int(ipaddress.ip_address(current)) - int(net.network_address)
            if offset >= int(prefix.get("reserveFirst", 0)):
                raise ValueError(
                    "旧 BMC 地址仍在动态可分配范围；规划已保存，待建立旧地址保护后迁移。可选择固定当前地址。"
                )
        self.identity(row, current)
        return {
            "serial": serial,
            "current_ip": current,
            "planned_ip": str(target),
            "interface_id": value_id(link["id"]),
            "declaration_revision": digest(row),
            "segment_revision": segment["revision"],
            "binding_revision": digest(link),
        }, row

    def preview(self, body, owner):
        if set(body) != {"serial"}:
            raise ValueError("请选择设备。")
        try:
            plan, _ = self.plan(body["serial"])
        except (ValueError, RuntimeError) as error:
            return {"passed": False, "detail": str(error)}
        plan.update(id=uuid.uuid4().hex, owner=owner, type="bmc-address", passed=True)
        self.resources.store.preflight(plan["id"], plan, lifetime=900)
        return {k: v for k, v in plan.items() if k != "owner"}

    def apply(self, body, owner, actor):
        if set(body) != {"preflight_id", "confirm_serial"}:
            raise ValueError("请检查并确认 BMC 地址应用。")
        with self.resources.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            saved = db.execute(
                "SELECT * FROM preflights WHERE id=?", (body["preflight_id"],)
            ).fetchone()
            if not saved or saved["used"] or saved["expires"] < time.time():
                raise ValueError("预检已失效或已执行；请核对当前地址状态。")
            check = json.loads(saved["data"])
            if (
                check.get("type") != "bmc-address"
                or check["owner"] != owner
                or check["serial"] != body["confirm_serial"]
            ):
                raise ValueError("地址预检与设备确认不匹配。")
            db.execute("UPDATE preflights SET used=1 WHERE id=?", (body["preflight_id"],))
        old = self.record(check["serial"])
        if old.get("status") in ("assigning", "waiting_address", "needs_attention"):
            raise ValueError("已有地址应用记录；先验证实际地址，不重复发送。")
        plan, row = self.plan(check["serial"])
        if any(plan[k] != check[k] for k in plan):
            raise ValueError("设备、接口或网络已变化，请重新检查。")
        record = plan | {
            "machine_snapshot": row,
            "id": check["id"],
            "status": "assigning",
            "actor": actor,
            "at": time.time(),
        }
        self.save(check["serial"], record)
        try:
            from pxeye.services.device_plans import DevicePlans

            DevicePlans(self.adapter, self.resources).synchronize(check["serial"], "bmc")
            result = self.adapter.rpc(
                "AssignStaticAddress",
                {"interface_id": {"value": plan["interface_id"]}, "ip_address": plan["planned_ip"]},
            )
            if (
                result.get("ipAddress") != plan["planned_ip"]
                or value_id(result.get("interfaceId")) != plan["interface_id"]
            ):
                raise RuntimeError("NICo 地址应用回执不匹配。")
            addresses = self.adapter.core(
                ["machine-interfaces", "show-addresses", plan["interface_id"]], data=True
            )
            if not any(
                a["address"] == plan["planned_ip"] and a["allocation_type"].lower() == "static"
                for a in addresses
            ):
                raise RuntimeError("NICo 固定分配读回不匹配。")
            record.update(
                status="waiting_address", detail="分配已应用；等待 BMC 采用规划地址并验证身份。"
            )
            self.save(check["serial"], record)
        except Exception:
            record.update(
                status="needs_attention", detail="地址写入结果需核对；仅验证，不自动重放。"
            )
            self.save(check["serial"], record)
            raise
        return self.verify({"serial": check["serial"]}, actor)

    def verify(self, body, actor):
        if set(body) != {"serial"}:
            raise ValueError("请选择设备验证 BMC 地址。")
        row, _ = self.row(body["serial"])
        record = self.record(body["serial"])
        if record.get("machine_snapshot"):
            row = record["machine_snapshot"]
        if not record or record["declaration_revision"] != digest(row):
            raise ValueError("没有匹配当前规划的地址应用记录，请重新检查。")
        try:
            addresses = self.adapter.core(
                ["machine-interfaces", "show-addresses", record["interface_id"]], data=True
            )
            if not any(
                a["address"] == record["planned_ip"] and a["allocation_type"].lower() == "static"
                for a in addresses
            ):
                raise ValueError("NICo 实际分配与规划不同，请核对现场。")
            self.identity(row, record["planned_ip"])
            record.update(
                status="verified",
                current_ip=record["planned_ip"],
                verified_at=time.time(),
                detail="规划地址已可达，BMC 账号、SN 与管理 MAC 验证通过。",
                verified_by=actor,
            )
        except (ValueError, RuntimeError) as error:
            record.update(
                status="waiting_address", detail=str(error).replace(row["bmc_password"], "[已隐藏]")
            )
        self.save(body["serial"], record)
        return self.view(row)
