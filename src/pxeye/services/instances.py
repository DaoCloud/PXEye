"""Read-only native instances and a durable, single-send ReleaseInstance ledger."""

import json
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import yaml

from pxeye.common import atomic_json, digest, value_id


RELEASE_LOCK = threading.RLock()


def release_records(adapter):
    return [
        json.loads(p.read_text())
        for p in sorted((adapter.data / "instance-releases").glob("*.json"))
    ]


def check_release_pending(adapter, serial):
    with RELEASE_LOCK:
        pending = [
            r
            for r in release_records(adapter)
            if r["serial"] == serial and r["status"] != "completed"
        ]
        if not pending:
            return
        # A previous browser refresh is never an installation prerequisite.
        with ThreadPoolExecutor(max_workers=2) as pool:
            native = pool.submit(adapter.core, ["instance", "show"], data=True)
            machines = pool.submit(adapter.core, ["machine", "show", "--hosts"], data=True)
            records = reconcile_releases(
                adapter, native.result()["instances"], machines.result()["machines"]
            )
        pending = [r for r in records if r["serial"] == serial and r["status"] != "completed"]
        if pending:
            raise ValueError(pending[0]["detail"])


def reconcile_releases(adapter, native, machines):
    """Refresh the durable operation from native facts, including failures."""
    with RELEASE_LOCK:
        records = release_records(adapter)
        by_machine = {value_id(m["id"]): m for m in machines}
        current = {value_id(i["id"]) for i in native}
        for record in records:
            if record["status"] == "completed":
                continue
            machine = by_machine.get(record["machine_id"])
            state = (machine or {}).get("state") or ""
            failure = ((machine or {}).get("status") or {}).get("failure_details")
            removed = record["id"] not in current
            another = any(
                value_id(i.get("machine_id")) == record["machine_id"]
                and value_id(i["id"]) != record["id"]
                for i in native
            )
            if removed and (another or (state == "Ready" and not failure)):
                status = "completed"
                detail = (
                    "原实例已移除；该设备已分配新的实例。"
                    if another
                    else "原实例已移除，NICo Machine 已 Ready，可创建首次安装任务。"
                )
            elif state.startswith("Failed") or failure:
                status = "needs_attention"
                detail = ("实例已移除，但设备回收失败：" if removed else "设备回收失败：") + (
                    state or str(failure)
                )
                if "NVMECleanFailed" in state or "NVMECleanFailed" in str(failure):
                    detail += "。Scout 磁盘清理失败；请检查清理日志及磁盘擦除能力，恢复并确认 NICo Ready 后再安装。"
                else:
                    detail += "。请检查 NICo / Scout 错误并恢复设备；尚不能安装。"
            elif removed and not machine:
                status, detail = (
                    "needs_attention",
                    "原实例已移除，但未找到关联 Machine，无法确认设备回收结果；请核对设备关联。",
                )
            elif removed:
                status, detail = (
                    "preparing",
                    "原实例已移除，NICo 正在准备设备："
                    + state
                    + "；等待 Machine Ready 后可首次安装。",
                )
            else:
                status = (
                    record["status"] if record["status"] in ("accepted", "unknown") else "accepted"
                )
                detail = (
                    "回收请求结果待核对；原实例仍存在，不会自动重发。"
                    if status == "unknown"
                    else "NICo 已接受回收请求，原实例仍存在；当前设备状态："
                    + (state or "待核对")
                    + "。"
                )
            record.update(
                status=status,
                detail=detail,
                instance_removed=removed,
                machine_state=state or None,
                failure_details=failure,
                checked_at=time.time(),
            )
            atomic_json(adapter.data / "instance-releases" / (record["id"] + ".json"), record)
        return records


def instance_id(value):
    try:
        result = str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("实例 ID 无效。") from None
    if result != value:
        raise ValueError("实例 ID 格式无效。")
    return result


class Instances:
    def __init__(self, adapter, resources, store):
        self.adapter, self.resources, self.store = adapter, resources, store
        self.lock = RELEASE_LOCK

    def path(self, iid):
        return self.adapter.data / "instance-releases" / (instance_id(iid) + ".json")

    def active_tasks(self):
        with self.store.db() as db:
            return [
                json.loads(r["data"])
                for r in db.execute(
                    "SELECT data FROM tasks WHERE status IN ('queued','running','needs_attention')"
                )
            ]

    def snapshot(self):
        # Independent native reads; never reuse browser data to authorize release.
        with ThreadPoolExecutor(max_workers=3) as pool:
            ins = pool.submit(self.adapter.core, ["instance", "show"], data=True)
            machines = pool.submit(self.adapter.core, ["machine", "show", "--hosts"], data=True)
            inventory = pool.submit(self.resources.inventory)
            return (
                ins.result().get("instances", []),
                machines.result().get("machines", []),
                inventory.result(),
            )

    def project(self, native, machine, inventory, tasks):
        from pxeye.services.hardware import facts

        hardware = facts(machine)
        serials = {hardware.get("product_serial"), hardware.get("chassis_serial")} - {None, ""}
        bmc = (machine or {}).get("bmc") or (machine or {}).get("bmc_info") or {}
        mac = str(bmc.get("mac") or "").lower()
        matches = [
            r
            for r in inventory
            if r.get("chassis_serial_number") in serials
            and mac
            and str(r.get("bmc_mac_address", "")).lower() == mac
        ]
        serial = (
            matches[0]["chassis_serial_number"]
            if len(matches) == 1
            else next(iter(sorted(serials)), None)
        )
        config = native.get("config") or {}
        tenant = config.get("tenant") or {}
        os_config = config.get("os") or {}
        hostname, source = tenant.get("hostname"), "NICo 租户配置"
        # Return only this whitelisted scalar, never user_data or its identity credentials.
        raw = os_config.get("user_data") or ""
        if isinstance(raw, str) and len(raw) <= 1024 * 1024:
            try:
                parsed = yaml.safe_load(raw)
                target = (
                    parsed.get("autoinstall", {}).get("identity", {}).get("hostname")
                    if isinstance(parsed, dict)
                    else None
                )
                if isinstance(target, str) and len(target) <= 253:
                    hostname, source = target, "安装配置（非实时 OS 查询）"
            except (yaml.YAMLError, AttributeError, RecursionError):
                pass
        iid, mid = value_id(native["id"]), value_id(native.get("machine_id"))
        variant = os_config.get("variant") or {}
        os_id = value_id(variant.get("OperatingSystemId")) if isinstance(variant, dict) else None
        versions = {
            k: native.get(k)
            for k in (
                "config_version",
                "network_config_version",
                "ib_config_version",
                "dpu_extension_service_version",
                "nvlink_config_version",
            )
        }
        reason = ""
        if len(matches) != 1:
            reason = "未与唯一已登记设备的 BMC MAC 及 Scout SN 核对一致，仅可查询。"
        elif not hardware["disks"] or any(not d.get("serial") for d in hardware["disks"]):
            reason = "最近 Scout 回报的磁盘清单不完整，仅可查询。"
        elif any(
            t.get("device") == serial
            or t.get("instance_id") == iid
            or (t.get("execution_device") or {}).get("machine_id") == mid
            for t in tasks
        ):
            reason = "此设备有安装任务或待处理现场，请先处理安装任务。"
        else:
            try:
                self.resources.check_address_operation(matches[0])
            except ValueError as error:
                reason = str(error)
        path = self.path(iid)
        record = json.loads(path.read_text()) if path.exists() else None
        if record:
            reason = "已提交回收请求；请刷新核对进度，不会重复发送。"
        metadata = dict(native.get("metadata") or {})
        # Core labels are a set serialized from a map; CLI processes may reorder them.
        metadata["labels"] = sorted(
            metadata.get("labels") or [], key=lambda label: json.dumps(label, sort_keys=True)
        )
        # Native status changes on every observation; only freeze the configuration and identity.
        revision = digest(
            {
                "id": iid,
                "machine_id": mid,
                "config": config,
                "metadata": metadata,
                "versions": versions,
                "serial": serial,
                "mac": mac,
                "device_ids": [r.get("id") for r in matches],
                "disks": sorted(
                    hardware["disks"], key=lambda disk: json.dumps(disk, sort_keys=True)
                ),
            }
        )
        return {
            "id": iid,
            "name": (native.get("metadata") or {}).get("name") or iid,
            "machine_id": mid,
            "serial": serial,
            "hostname": hostname,
            "hostname_source": source,
            "tenant": tenant.get("tenant_organization_id"),
            "os_id": os_id,
            "os_name": os_id or ("自定义 iPXE" if variant else "未配置"),
            "addresses": [
                a
                for n in (native.get("status") or {}).get("network", {}).get("interfaces", [])
                for a in n.get("addresses", [])
            ],
            "machine_state": (machine or {}).get("state") or "Machine 暂未找到",
            "disks": hardware["disks"],
            "versions": versions,
            "revision": revision,
            "delete_allowed": not bool(reason),
            "delete_reason": reason,
            "release": record,
        }

    def reconcile(self, records, native, machines):
        return reconcile_releases(self.adapter, native, machines)

    def list(self):
        with self.lock:
            native, machines, inventory = self.snapshot()
            records = self.reconcile(release_records(self.adapter), native, machines)
            by_machine = {value_id(m["id"]): m for m in machines}
            tasks = self.active_tasks()
            rows = [
                self.project(i, by_machine.get(value_id(i.get("machine_id"))), inventory, tasks)
                for i in native
            ]
            ids = sorted({r["os_id"] for r in rows if r["os_id"]})
            os_error = None
            if ids:
                try:
                    names = {
                        value_id(o["id"]): o.get("name")
                        for o in self.adapter.rpc(
                            "FindOperatingSystemsByIds", {"ids": [{"value": i} for i in ids]}
                        ).get("operatingSystems", [])
                    }
                    for row in rows:
                        row["os_name"] = names.get(row["os_id"]) or row["os_name"]
                except (RuntimeError, OSError):
                    os_error = "OS 名称读取失败，保留原生 OS ID。"
            return {
                "instances": sorted(rows, key=lambda r: (r["serial"] or "", r["id"])),
                "releases": sorted(records, key=lambda r: r["requested_at"], reverse=True),
                "checked_at": time.time(),
                "warning": os_error,
            }

    def detail(self, iid):
        instance_id(iid)
        result = self.list()
        row = next((r for r in result["instances"] if r["id"] == iid), None)
        if not row:
            record = next((r for r in result["releases"] if r["id"] == iid), None)
            if not record:
                raise ValueError("当前实例不存在，请刷新实例列表。")
            return {"instance": None, "release": record, "checked_at": result["checked_at"]}
        return {"instance": row, "release": row["release"], "checked_at": result["checked_at"]}

    def release(self, iid, body, actor):
        instance_id(iid)
        if (
            set(body) != {"revision", "confirm_serial", "confirm_cleanup"}
            or body["confirm_cleanup"] is not True
        ):
            raise ValueError("请核对设备 SN 并确认全部磁盘清理及资源回收范围。")
        with self.lock:
            path = self.path(iid)
            if path.exists():
                return json.loads(path.read_text())  # Includes crash/timeout: never replay.
            row = self.detail(iid)["instance"]
            if not row or not row["delete_allowed"]:
                raise ValueError((row or {}).get("delete_reason") or "实例已不在当前列表。")
            if body["confirm_serial"] != row["serial"] or body["revision"] != row["revision"]:
                raise ValueError("设备 SN 或实例配置已变化，请刷新后重新核对。")
            check_release_pending(self.adapter, row["serial"])
            record = {
                k: row[k]
                for k in (
                    "id",
                    "name",
                    "machine_id",
                    "serial",
                    "hostname",
                    "disks",
                    "versions",
                    "revision",
                )
            }
            record.update(
                status="unknown",
                actor=actor,
                requested_at=time.time(),
                detail="请求结果待核对；只允许发送一次，请刷新查询，不能重新提交。",
            )
            # Durable intent precedes the only RPC, including power loss between these operations.
            atomic_json(path, record)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            self.resources.invalidate()
            try:
                self.adapter.rpc("ReleaseInstance", {"id": {"value": iid}})
            except Exception as error:
                code = re.search(
                    r"Code:\s*(InvalidArgument|NotFound|PermissionDenied|Unauthenticated|FailedPrecondition|Unavailable|DeadlineExceeded|Internal|Unknown)\b",
                    str(error),
                )
                if code:
                    record["rpc_code"] = code[1]
                    record["detail"] = (
                        "NICo 返回 " + code[1] + "；请核对原生状态和服务日志，不会重复发送。"
                    )
                    atomic_json(path, record)
                print("INSTANCE_RELEASE_RESULT_UNKNOWN", iid, type(error).__name__, flush=True)
            else:
                record.update(status="accepted", detail="NICo 已接受回收请求；不代表磁盘清理完成。")
                atomic_json(path, record)
            return record
