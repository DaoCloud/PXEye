"""Durable planned BMC changes: protect, PATCH once, verify, then synchronize."""

import ipaddress
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from pxeye.clients.redfish import REDFISH_DEADLINE
from pxeye.clients.errors import RedfishRequestError
from pxeye.common import redact
from pxeye.common import digest

PHASES = [
    ("check", "检查地址与身份"),
    ("update", "更新 BMC"),
    ("verify", "验证新地址"),
    ("sync", "同步管理记录"),
]
OBSERVATION_SECONDS = 300


class BMCJobs:
    def __init__(self, addresses):
        self.addresses = addresses
        self.adapter = addresses.adapter

    def fingerprint(self, row, prefix, path):
        return digest(
            {
                "interface_id": row["interface_id"],
                "mac_address": row["mac_address"],
                "serial": row.get("serial"),
                "role": row["role"],
                "network_id": row["network_id"],
                "addresses": row["addresses"],
                "target_ip": row.get("target_ip"),
                "prefix": prefix,
                "path": path,
            }
        )

    def preview(self, body, owner):
        if set(body) != {"device_ids", "scope"} or body["scope"] != "bmc":
            raise ValueError("BMC 更新参数无效。")
        a = self.addresses
        rows, snapshot = a._selected_rows(body["device_ids"], manager_only=True)
        present = {row.get("device_id") for row in rows}
        rows += a.missing_device_rows(snapshot, body["device_ids"], present)

        def inspect(row):
            base = {
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
            token = REDFISH_DEADLINE.set(time.monotonic() + OBSERVATION_SECONDS)
            try:
                if not row.get("interface_id"):
                    raise ValueError("设备没有 BMC / PMC 接口。")
                current, _ = a.context(row["interface_id"], snapshot)
                if a.pending(row["interface_id"]):
                    raise ValueError("该接口有未完成操作，请先查看进度并核对。")
                target, network, prefix = a.target_context(
                    current, current.get("target_ip"), snapshot
                )
                base.update(current_ip=current["addresses"][0], target_ip=target)
                credential = a.credentials(current, snapshot)
                if not credential:
                    raise ValueError("未保存 BMC / PMC 凭据。")
                capability = a.redfish_interface(current, current["addresses"][0], credential)
                if target != current["addresses"][0]:
                    try:
                        self.adapter.redfish_request(target, "/redfish/v1/Managers", credential)
                    except RedfishRequestError as error:
                        if error.status is not None:
                            raise ValueError(
                                "目标 IP 已有 HTTPS 服务，不能确认空闲；请检查地址占用。"
                            ) from None
                    else:
                        # A reachable new address is allowed only for this same controller.
                        a.identity(current, target, credential)
                        a.redfish_interface(current, target, credential)
                # A configured static list alone is not proof that the address is in use.
                nic = capability["current"]
                if (
                    not isinstance(nic.get("DHCPv4", {}).get("DHCPEnabled"), bool)
                    or "IPv4Addresses" not in nic
                ):
                    raise ValueError("设备未提供标准 IPv4 / DHCP 配置，请先确认厂商 Redfish 能力。")
                return base | {
                    "passed": True,
                    "serial": capability["identity"]["serial"],
                    "current_ip": current["addresses"][0],
                    "target_ip": target,
                    "network_id": network["id"],
                    "nic_path": capability["nic_path"],
                    "subnet_mask": str(ipaddress.ip_network(prefix["prefix"]).netmask),
                    "gateway": prefix.get("gateway", ""),
                    "fingerprint": self.fingerprint(current, prefix, capability["nic_path"]),
                }
            except (RuntimeError, ValueError) as error:
                return base | {"passed": False, "detail": str(error)}
            finally:
                REDFISH_DEADLINE.reset(token)

        with ThreadPoolExecutor(max_workers=4) as pool:
            result = list(pool.map(inspect, rows))
        key = a.equipment.create_check(
            "redfish-address-bmc", owner, {"scope": "bmc", "rows": result}
        )
        return {
            "id": key,
            "scope": "bmc",
            "rows": redact(result),
            "ready": sum(r["passed"] for r in result),
        }

    def apply(self, check, batch_id, actor):
        a = self.addresses
        with a.equipment.lock, a.lock:
            rows = [row for row in check["rows"] if row.get("passed")]
            if not rows or any(a.pending(row["interface_id"]) for row in rows):
                raise ValueError("接口已有未完成操作或预检未通过，请刷新。")
            # Persist the complete batch before starting external work.
            for row in rows:
                key = str(uuid.uuid4())
                a.write(
                    "operations",
                    key,
                    row
                    | {
                        "id": key,
                        "batch_id": batch_id,
                        "action": "redfish_bmc",
                        "actor": actor,
                        "created_at": time.time(),
                        "status": "bmc_running",
                        "detail": "预检已通过，等待更新",
                        "steps": [
                            {
                                "key": k,
                                "label": label,
                                "status": "completed" if k == "check" else "waiting",
                                **(
                                    {
                                        "detail": "规划、地址占用、设备身份与接口能力已检查。",
                                        "updated_at": time.time(),
                                    }
                                    if k == "check"
                                    else {}
                                ),
                            }
                            for k, label in PHASES
                        ],
                    },
                )

        def work():
            records = self.status(batch_id)["rows"]
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda r: self.run(r["id"]), records))

        threading.Thread(target=work, name="bmc-redfish", daemon=True).start()
        return self.status(batch_id)

    def status(self, batch_id):
        # The single-use preview id is a UUID, persisted only in individual operations.
        uuid.UUID(batch_id)
        rows = sorted(
            (
                r
                for r in self.addresses.records("operations")
                if r.get("action") == "redfish_bmc" and r["batch_id"] == batch_id
            ),
            key=lambda r: (r["created_at"], r["id"]),
        )
        if not rows:
            raise ValueError("BMC 更新记录不存在。")
        return {
            "id": batch_id,
            "rows": redact(rows),
            "running": any(r["status"] == "bmc_running" for r in rows),
            "completed": sum(r["status"] == "verified" for r in rows),
            "total": len(rows),
        }

    def step(self, record, key, status, detail):
        for phase in record["steps"]:
            if phase["key"] == key:
                phase.update(status=status, detail=detail, updated_at=time.time())
        record.update(detail=detail, updated_at=time.time())
        self.addresses.write("operations", record["id"], record)

    def verify_target(self, record, row, credential):
        identity = self.addresses.identity(row, record["target_ip"], credential)
        if identity["serial"] != record["serial"]:
            raise ValueError("新地址返回的 SN 与本次设备不同。")
        nic = self.adapter.redfish_read(record["target_ip"], record["nic_path"], credential)
        if str(nic.get("MACAddress", "")).lower() != record["mac_address"]:
            raise ValueError("新地址的管理 MAC 不符。")
        expected = {
            "Address": record["target_ip"],
            "SubnetMask": record["subnet_mask"],
            "Gateway": record["gateway"],
        }
        adopted = any(
            all(entry.get(k, "") == v for k, v in expected.items())
            for entry in nic.get("IPv4Addresses", [])
        )
        configured = any(
            all(entry.get(k, "") == v for k, v in expected.items())
            for entry in nic.get("IPv4StaticAddresses", [])
        )
        old_still_active = record["current_ip"] != record["target_ip"] and any(
            e.get("Address") == record["current_ip"] for e in nic.get("IPv4Addresses", [])
        )
        if (
            old_still_active
            or not adopted
            or not configured
            or nic.get("DHCPv4", {}).get("DHCPEnabled") is not False
        ):
            raise RuntimeError("等待 BMC 实际采用规划 IP、掩码、网关并关闭 DHCP。")
        return identity

    def synchronize(self, record, row):
        a = self.addresses
        self.adapter.rpc(
            "AssignStaticAddress",
            {"interface_id": {"value": record["interface_id"]}, "ip_address": record["target_ip"]},
        )
        if not a.assigned(record):
            raise RuntimeError("BMC 已采用新地址，NICo 接口同步尚未确认。")
        if row["kind"] == "server" and row["role"] == "host_bmc":
            from pxeye.services.device_plans import DevicePlans
            from pxeye.services.bmc_addresses import BMCAddresses

            plans = DevicePlans(self.adapter, a.resources)
            planned = plans.get(row["serial"])
            if planned and planned["machine"].get("bmc_ip_address") != record["target_ip"]:
                raise ValueError("设备规划已变化；保留当前硬件地址，停止同步。")
            actual = next(
                (m for m in a.resources.inventory() if m["chassis_serial_number"] == row["serial"]),
                None,
            )
            if not actual or actual["bmc_mac_address"].lower() != record["mac_address"]:
                raise ValueError("原生主机身份缺失或与管理 MAC 不一致。")
            if (
                actual.get("bmc_ip_address") != record["target_ip"]
                or actual.get("bmc_ip_allocation") != "Fixed"
            ):
                from pxeye.domain.machines import machine_rpc

                payload = machine_rpc(
                    {
                        "id": actual["id"],
                        "bmc_ip_address": record["target_ip"],
                        "bmc_ip_allocation": "Fixed",
                    }
                )
                self.adapter.rpc(
                    "PatchExpectedMachines",
                    {
                        "patches": [
                            {
                                "expected_machine": payload,
                                "update_mask": {"paths": ["bmc_ip_address", "bmc_ip_allocation"]},
                            }
                        ]
                    },
                )
                actual = next(
                    (
                        m
                        for m in a.resources.inventory()
                        if m["chassis_serial_number"] == row["serial"]
                    ),
                    None,
                )
                if (
                    not actual
                    or actual.get("bmc_ip_address") != record["target_ip"]
                    or actual.get("bmc_ip_allocation") != "Fixed"
                ):
                    raise RuntimeError("原生主机声明的新地址尚未读回。")
            machine = next(
                s
                for s in a.resources.planned_inventory()
                if s["chassis_serial_number"] == row["serial"]
            )
            BMCAddresses(self.adapter, a.resources).save(
                row["serial"],
                {
                    "id": record["id"],
                    "status": "verified",
                    "current_ip": record["target_ip"],
                    "planned_ip": record["target_ip"],
                    "bmc_mac": record["mac_address"],
                    "declaration_revision": digest(machine),
                    "verified_at": time.time(),
                    "detail": "Redfish 新地址与 NICo 记录已核对。",
                },
            )
        elif row["kind"] in ("switch", "power_shelf"):
            item = a.equipment.item(record["device_id"], a.equipment.snapshot())
            if (
                item.get("declaration", {}).get("bmc_mac_address", "").lower()
                != record["mac_address"]
            ):
                raise ValueError("本地设备身份与管理 MAC 不一致。")
            a.equipment.controller_plan(item, record["target_ip"], verified=True)
        record.update(status="verified", verified_at=time.time())
        self.step(record, "sync", "completed", "管理联系地址与 NICo 静态分配已同步。")

    def run(self, key):
        a = self.addresses
        record = a.record("operations", key)
        phase = "check"
        deadline = time.monotonic() + OBSERVATION_SECONDS
        token = REDFISH_DEADLINE.set(deadline)
        try:
            with a.equipment.lock, a.lock:
                row, snapshot = a.context(record["interface_id"])
                target, _, prefix = a.target_context(row, row.get("target_ip"), snapshot)
                credential = a.credentials(row, snapshot)
                if not credential:
                    raise ValueError("BMC / PMC 凭据已移除，请重新检查。")
                if (
                    self.fingerprint(row, prefix, record["nic_path"]) != record["fingerprint"]
                    or target != record["target_ip"]
                ):
                    raise ValueError("地址规划或接口已变化，请重新检查。")
                record["reservation_attempted"] = True
                a.write("operations", key, record)
                self.adapter.rpc(
                    "PrepareStaticAddress",
                    {
                        "interface_id": {"value": record["interface_id"]},
                        "ip_address": target,
                        "current_ip_address": record["current_ip"],
                    },
                )
                record["target_protected"] = True
            self.step(record, phase, "completed", "预检结果有效；目标已保护，旧联系地址仍保留。")
            phase = "update"
            self.step(record, phase, "running", "通过 Redfish 应用静态地址并关闭 DHCP。")
            record["patch_attempted"] = True
            a.write("operations", key, record)
            payload = {
                "DHCPv4": {"DHCPEnabled": False},
                "IPv4StaticAddresses": [
                    {
                        "Address": record["target_ip"],
                        "SubnetMask": record["subnet_mask"],
                        "Gateway": record["gateway"],
                    }
                ],
            }
            try:
                response = self.adapter.redfish_request(
                    record["current_ip"],
                    record["nic_path"],
                    credential,
                    method="PATCH",
                    body=payload,
                )
                record["http_status"] = response.get("status")
                record["task_path"] = response.get("location", "")
                self.step(record, phase, "submitted", "写入已提交；等待设备确认采用新地址。")
            except RedfishRequestError as error:
                if error.status is not None and 400 <= error.status < 500:
                    raise RuntimeError(
                        str(error) + " BMC 拒绝配置；请核对权限和网络参数。"
                    ) from None
                self.step(
                    record, phase, "submitted", "写入响应未确认；只读核对新地址，不重复下发。"
                )
            except RuntimeError:
                self.step(
                    record, phase, "submitted", "写入响应未确认；只读核对新地址，不重复下发。"
                )
            phase = "verify"
            self.step(record, phase, "running", "从新地址读取同一设备及实际网络配置。")
            last = "新地址尚未确认。"
            while time.monotonic() < deadline:
                try:
                    self.verify_target(record, row, credential)
                    break
                except (RuntimeError, ValueError) as error:
                    last = str(error)
                    time.sleep(min(5, max(0, deadline - time.monotonic())))
            else:
                raise RuntimeError(last + " 观察窗口结束；保留地址保护，请核对。")
            self.step(record, "update", "completed", "静态配置写入已由设备实际采用确认。")
            self.step(
                record, phase, "completed", "新地址、SN、MAC、掩码、网关与 DHCP 关闭状态一致。"
            )
            phase = "sync"
            self.step(record, phase, "running", "更新 NICo 分配与管理联系地址。")
            self.synchronize(record, row)
        except Exception as error:
            # Publish one terminal record while excluding user-triggered recovery.
            # Otherwise a late failure write could overwrite a successful recovery.
            with a.lock:
                record.update(
                    status="bmc_needs_attention"
                    if record.get("reservation_attempted")
                    else "blocked"
                )
                detail = (
                    str(error)
                    if isinstance(error, (ValueError, RuntimeError))
                    else "操作未完成，请核对；未重复写入。"
                )
                for step in record["steps"]:
                    if step["status"] == "running":
                        step.update(status="failed", detail="结果待核对；未重发配置。")
                self.step(record, phase, "failed", detail)
        finally:
            REDFISH_DEADLINE.reset(token)

    def finish_sync(self, body):
        if set(body) != {"id", "confirm_sync"} or body["confirm_sync"] is not True:
            raise ValueError("请确认：只读验证新地址后继续同步记录，不重复 BMC 写入。")
        a = self.addresses
        with a.equipment.lock, a.lock:
            record = a.record("operations", body["id"])
            if (
                record.get("action") != "redfish_bmc"
                or record["status"] != "bmc_needs_attention"
                or not record.get("patch_attempted")
            ):
                raise ValueError("该操作不允许继续同步，请刷新进度。")
            row, snapshot = a.context(record["interface_id"])
            if row.get("target_ip") != record["target_ip"]:
                raise ValueError("规划已变化，请先核对。")
            token = REDFISH_DEADLINE.set(time.monotonic() + OBSERVATION_SECONDS)
            phase = "verify"
            try:
                self.step(record, phase, "running", "只读核对新地址与设备身份。")
                self.verify_target(record, row, a.credentials(row, snapshot))
                self.step(record, "update", "completed", "设备静态配置已确认采用。")
                self.step(record, "verify", "completed", "新地址与同一设备身份核对通过。")
                phase = "sync"
                self.step(record, phase, "running", "只继续同步管理记录。")
                self.synchronize(record, row)
            except Exception as error:
                record.update(status="bmc_needs_attention")
                self.step(
                    record,
                    phase,
                    "failed",
                    str(error)
                    if isinstance(error, (RuntimeError, ValueError))
                    else "同步未完成，请核对。",
                )
                raise
            finally:
                REDFISH_DEADLINE.reset(token)
        return self.status(record["batch_id"])

    def restart_unsent(self, body):
        if set(body) != {"id", "confirm_update"} or body["confirm_update"] is not True:
            raise ValueError("请确认重新检查并更新 BMC。")
        a = self.addresses
        with a.equipment.lock, a.lock:
            record = a.record("operations", body["id"])
            if (
                record.get("action") != "redfish_bmc"
                or record["status"] != "bmc_needs_attention"
                or record.get("patch_attempted")
            ):
                raise ValueError("BMC 写入已尝试或任务仍在运行；只能核对新地址并继续同步。")
            a.context(record["interface_id"])
            record.update(
                status="bmc_running", detail="用户重新确认；重新检查尚未发送的 BMC 更新。"
            )
            record["steps"] = [
                {"key": k, "label": label, "status": "waiting"} for k, label in PHASES
            ]
            a.write("operations", record["id"], record)
            threading.Thread(
                target=self.run, args=(record["id"],), name="bmc-redfish-unsent", daemon=True
            ).start()
        return self.status(record["batch_id"])
