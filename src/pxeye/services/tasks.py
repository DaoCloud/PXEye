"""Task claiming, scheduling, recovery and operation lock policy."""

import json
import os
import threading
import time
import uuid
from pathlib import Path
from contextlib import nullcontext
from pxeye.installation.executor import terminal_installer_failure
from pxeye.domain.workflow import installation_impact, authorize_impact
from pxeye.services.device_plans import bmc_choice
from pxeye.services.instances import check_release_pending


class TaskCoordinator:
    def __init__(
        self, *, config, adapter, store, executor, resources, onboarding, device_config, os_library
    ):
        self.config, self.adapter, self.store = config, adapter, store
        self.executor, self.resources = executor, resources
        self.onboarding, self.device_config = onboarding, device_config
        self.os_library = os_library
        self.worker_lock = threading.Lock()

    def recover(self):
        data_dir = self.adapter.data
        auto_continue = []
        for task in self.store.incomplete():
            if task["status"] == "queued" and task.get("batch_id"):
                continue
            if task["status"] in ("running", "queued"):
                if (
                    (Path(data_dir) / "tasks" / task["id"] / "event-binding.json").exists()
                    and task.get("stage")
                    in ("boot", "pxe", "install", "handoff", "firstboot", "reboot")
                    and (
                        task.get("native_reinstall_requests") == 1
                        or task.get("native_allocation_requests") == 1
                    )
                ):
                    auto_continue.append(task["id"])
                task["status"] = "needs_attention"
                try:
                    failure = terminal_installer_failure(self.executor.attempt_text(task))
                except OSError:
                    failure = None
                task["error"] = (
                    failure
                    or "服务更新或重启；保留设备锁和现场。具备本轮安装退出与可信身份时可仅继续验收。"
                )
                if failure:
                    task["installer_failure"] = {"kind": "installer_failed", "detail": failure}
                task["resume_available"] = self.executor.can_resume(task)
                task["prepare_available"] = self.executor.can_prepare(task)
                task["retry_available"] = self.executor.can_retry_install(task)
                task["restart_available"] = self.executor.can_restart_preinstall(task)
                task.setdefault("events", []).append(
                    {
                        "at": time.time(),
                        "stage": task.get("stage", "install"),
                        "message": task["error"],
                    }
                )
                self.store.save(task)
            elif task["status"] == "needs_attention":
                task["resume_available"] = self.executor.can_resume(task)
                task["prepare_available"] = self.executor.can_prepare(task)
                task["retry_available"] = self.executor.can_retry_install(task)
                task["restart_available"] = self.executor.can_restart_preinstall(task)
                self.store.save(task)
        if auto_continue:
            self.start_recovered(auto_continue)
        elif self.store.queued():
            self.start_queue()

    def task_view(self, task):
        """Refresh recovery actions from current evidence without rewriting task history."""
        if task.get("status") != "needs_attention" or not task.get("execution_device"):
            return task
        result = dict(task)
        result["resume_available"] = self.executor.can_resume(result)
        result["retry_available"] = self.executor.can_retry_install(result)
        return result

    def start_recovered(self, task_ids):
        def work():
            with self.worker_lock:
                for task_id in task_ids:
                    task = self.store.get(task_id)
                    if not task or task["status"] != "needs_attention":
                        continue
                    remaining = max(
                        0, task.get("observation_deadline", time.time() + 600) - time.time()
                    )
                    deadline = time.monotonic() + remaining
                    # Wait read-only until this same attempt has trustworthy identity.
                    while time.monotonic() < deadline:
                        if self.executor.can_resume(task):
                            task["status"] = "running"
                            task["error"] = None
                            self.store.save(task)
                            self.executor.resume(task)
                            break
                        time.sleep(10)
            if self.store.queued():
                self.start_queue()

        threading.Thread(target=work, daemon=True, name="resume-observation").start()

    @staticmethod
    def installation_mode(observed):
        instances = observed["instances"]
        assigned = str((observed.get("machine") or {}).get("state", "")).startswith("Assigned")
        if len(instances) > 1 or (assigned and not instances):
            raise ValueError("NICo Machine 与 Instance 分配关系不明确，请刷新或检查实例状态。")
        return "reinstall" if instances else "first_install"

    @staticmethod
    def allocation_observation(observed):
        return {
            "machine_id": (observed.get("machine") or {}).get("id"),
            "instance_ids": [i["id"] for i in observed["instances"]],
            "first_install_ready": observed["first_install_ready"],
        }

    def batch_preflight(self, body, owner):
        if set(body) != {"mode", "profile_id", "devices"} or body["mode"] not in (
            "auto",
            "first_install",
            "reinstall",
        ):
            raise ValueError("请提供安装设备及逐机配置。")
        devices = body["devices"]
        if not isinstance(devices, list) or not 1 <= len(devices) <= 50:
            raise ValueError("每批选择 1–50 台设备。")
        if any(
            not isinstance(d, dict)
            or not {"serial", "hostname", "disk_serial"} <= set(d)
            or set(d) - {"serial", "hostname", "disk_serial", "bmc_choice"}
            for d in devices
        ):
            raise ValueError("逐机配置字段无效。")
        if len({d["serial"] for d in devices}) != len(devices) or len(
            {d["hostname"] for d in devices}
        ) != len(devices):
            raise ValueError("同一批次的设备和 hostname 不能重复。")

        def check_all():
            checks = []
            observations = self.onboarding.observed(
                [self.onboarding.inventory_row(d["serial"]) for d in devices]
            )
            for row in devices:
                check_release_pending(self.adapter, row["serial"])
                if self.store.active(row["serial"]):
                    raise ValueError(row["serial"] + " 已有任务或待处理现场。")
                with bmc_choice(row["serial"], row.get("bmc_choice", "require_planned")):
                    observed = observations[row["serial"]]
                    mode = self.installation_mode(observed)
                    if body["mode"] != "auto" and body["mode"] != mode:
                        raise ValueError("设备分配状态已变化，请刷新后重新检查。")
                    if mode == "first_install":
                        profile_id = (
                            self.device_config.get(row["serial"]).get("profile_id")
                            if body["mode"] == "auto"
                            else body["profile_id"]
                        )
                        if not profile_id:
                            raise ValueError(row["serial"] + " 请先在设备规划中选择安装方案。")
                        check = (
                            self.onboarding.preflight(
                                row["serial"], row["hostname"], profile_id, row["disk_serial"]
                            )
                            if observed["first_install_ready"]
                            else self.onboarding.deferred_preflight(
                                row["serial"], row["hostname"], profile_id, row["disk_serial"]
                            )
                        )
                        if check.get("deferred_first_install"):
                            try:
                                declared = self.onboarding.inventory_row(row["serial"])
                                self.onboarding.check_preparation(declared)
                                self.onboarding.check_scout_boot_guard(
                                    declared, observed["machine"]
                                )
                                self.onboarding.probe(declared, managed=bool(observed["machine"]))
                                check["checks"].append(
                                    {
                                        "name": "BMC身份、启动网络配置及Scout保护",
                                        "passed": True,
                                        "detail": "只读核对通过；不代表物理引导链路已验证",
                                    }
                                )
                            except (ValueError, RuntimeError) as error:
                                check["checks"].append(
                                    {"name": "设备接入条件", "passed": False, "detail": str(error)}
                                )
                                check["passed"] = False
                    else:
                        check = self.adapter.preflight(
                            row["serial"],
                            row["hostname"],
                            native_observation=observed,
                        )
                        if check["scope"]["instance_id"] != observed["instances"][0]["id"]:
                            raise ValueError(
                                "执行配置与 NICo 当前 Instance 不一致，请刷新设备后重新检查。"
                            )
                check["mode"] = mode
                check["allocation_observation"] = self.allocation_observation(observed)
                check["impact"] = installation_impact(check, self.config)
                checks.append(check)
            addresses = [
                c.get("installation_plan", {}).get("management_ip")
                for c in checks
                if c.get("installation_plan")
            ]
            if len(set(addresses)) != len(addresses):
                raise ValueError("本批次存在重复管理 IP，请先修改设备清单。")
            modes = {c["mode"] for c in checks}
            result = {
                "id": uuid.uuid4().hex,
                "owner": owner,
                "mode": next(iter(modes)) if len(modes) == 1 else "mixed",
                "profile_id": body["profile_id"],
                "checks": checks,
                "passed": all(c["passed"] for c in checks),
                "checked_at": time.time(),
                "max_concurrency": 1,
            }
            self.store.preflight(result["id"], result, lifetime=900)
            return {k: v for k, v in result.items() if k != "owner"}

        return self.configure(check_all)

    def submit_batch(self, body, owner, actor):
        if set(body) - {
            "preflight_id",
            "request_key",
            "confirm_serials",
            "confirm_disk",
            "confirm_reboot",
            "cleanup_scope",
        } or not {
            "preflight_id",
            "request_key",
            "confirm_serials",
            "confirm_disk",
            "confirm_reboot",
        } <= set(body):
            raise ValueError("批量提交字段不完整。")
        if not isinstance(body["request_key"], str) or not 16 <= len(body["request_key"]) <= 80:
            raise ValueError("无效的幂等请求标识。")
        existing = self.store.batch(body["request_key"])
        if existing:
            if existing["preflight_id"] != body["preflight_id"] or existing["owner"] != owner:
                raise ValueError("幂等请求标识已用于另一批次。")
            return existing

        def claim():
            with self.store.db() as db:
                row = db.execute(
                    "SELECT data,expires,used FROM preflights WHERE id=?", (body["preflight_id"],)
                ).fetchone()
            if not row or row["used"] or row["expires"] < time.time():
                raise ValueError("批量预检已失效，请重新检查。")
            check = json.loads(row["data"])
            serials = [c["device"] for c in check["checks"]]
            if (
                body["confirm_serials"] != serials
                or body["confirm_disk"] is not True
                or body["confirm_reboot"] is not True
            ):
                raise ValueError("请核对全部设备 SN、逐机系统盘及重启验收范围。")
            tasks = []
            batch_id = "BATCH-" + time.strftime("%Y%m%d-") + uuid.uuid4().hex[:10]
            observations = self.onboarding.observed(
                [self.onboarding.inventory_row(c["device"]) for c in check["checks"]]
            )
            for c in check["checks"]:
                observed = observations[c["device"]]
                if self.installation_mode(observed) != c["mode"] or c.get(
                    "allocation_observation", self.allocation_observation(observed)
                ) != self.allocation_observation(observed):
                    raise ValueError("设备分配状态已变化，请重新检查并确认安装影响。")
                check_release_pending(self.adapter, c["device"])
                if not c["passed"]:
                    raise ValueError("批次存在预检阻断项。")
                impact = authorize_impact(c, self.config, body.get("cleanup_scope"))
                if impact != c.get("impact"):
                    raise ValueError("站点策略已变化，请重新核对安装影响。")
                with bmc_choice(
                    c["device"], c["installation_plan"].get("bmc_choice", "require_planned")
                ):
                    if c["mode"] == "first_install":
                        if c.get("deferred_first_install"):
                            fresh = self.onboarding.deferred_preflight(
                                c["device"], c["hostname"], c["profile_id"], c["disk_serial"]
                            )
                            plan, device = fresh["installation_plan"], None
                        else:
                            plan, device, _ = self.onboarding.plan(
                                c["device"], c["profile_id"], c["disk_serial"]
                            )
                            device["redfish_system"] = c["execution_device"]["redfish_system"]
                            device["instance_id"] = str(uuid.uuid4())
                    else:
                        plan = self.resources.execution_plan(c["device"])
                        device = self.adapter.target_device(c["device"], plan)
                        if device["instance_id"] != observed["instances"][0]["id"]:
                            raise ValueError("Instance 已变化，请重新检查。")
                if plan != c["installation_plan"]:
                    raise ValueError("设备、发现信息或网络规划已变化，请重新检查。")
                task = {
                    "id": "UI-" + time.strftime("%Y%m%d-") + uuid.uuid4().hex[:10],
                    "batch_id": batch_id,
                    "mode": c["mode"],
                    "device": c["device"],
                    "hostname": c["hostname"],
                    "status": "queued",
                    "stage": "queued",
                    "created_at": time.time(),
                    "actor": actor,
                    "events": [],
                    "profile": (device or {}).get("profile", c.get("profile_id")),
                    "disk_wwn": (device or {}).get("disk_wwn"),
                    "disk_serial": (device or {}).get("disk_serial", c.get("disk_serial")),
                    "instance_id": (device or {}).get("instance_id"),
                    "management_ip": (device or {}).get(
                        "management_ip", c.get("scope", {}).get("management_ip")
                    ),
                    "current_management_ip": plan.get("current_management_ip"),
                    "installation_plan": plan,
                    "impact_authorization": impact | {"confirmed_at": time.time(), "actor": actor},
                    "execution_device": device,
                    "deferred_bootstrap": bool(c.get("deferred_first_install")),
                    "source": "nico-ui",
                    "executor": {
                        "namespace": os.environ.get("POD_NAMESPACE")
                        or self.config.get("site", {}).get("namespace"),
                        "controller": self.config.get("site", {}).get("deployment"),
                        "pod_uid": os.environ.get("POD_UID"),
                        "node": os.environ.get("NODE_NAME"),
                    },
                }
                tasks.append(task)
            batch = {
                "id": batch_id,
                "mode": check["mode"],
                "profile_id": check["profile_id"],
                "owner": owner,
                "preflight_id": body["preflight_id"],
                "created_at": time.time(),
                "actor": actor,
                "max_concurrency": 1,
                "task_ids": [t["id"] for t in tasks],
            }
            key, _ = self.store.claim_batch(
                body["preflight_id"], batch, tasks, body["request_key"], owner
            )
            return self.store.batch(key)

        result = self.configure(claim)
        self.start_queue()
        return result

    def start_queue(self):
        if not self.worker_lock.acquire(blocking=False):
            return

        def work():
            try:
                for task in self.store.queued():
                    self.executor.run(task)
            finally:
                self.worker_lock.release()

        threading.Thread(target=work, daemon=True, name="installation-queue").start()

    def os_lock(self):
        library = getattr(self, "os_library", None)
        return library.lock if library else nullcontext()

    def plan(self, action):
        with self.os_lock():
            return action()

    def configure(self, action):
        if not self.worker_lock.acquire(blocking=False):
            raise ValueError("已有安装或资源操作执行中，请稍后再试。")
        try:
            with self.os_lock():
                return action()
        finally:
            self.worker_lock.release()

    def apply_network(self, sid):
        if not self.worker_lock.acquire(blocking=False):
            raise ValueError("已有安装或资源应用任务执行中。")
        try:
            result = self.resources.apply_network(sid)
            if result["status"] == "waiting_deletion":

                def work():
                    try:
                        self.resources.finish_network_replacement(sid)
                    except Exception as error:
                        print("NETWORK_APPLY_ERROR", type(error).__name__, flush=True)
                    finally:
                        self.worker_lock.release()

                threading.Thread(target=work, daemon=True, name="network-" + sid).start()
                return result
        except Exception:
            self.worker_lock.release()
            raise
        self.worker_lock.release()
        return result

    def submit(self, body, actor):
        allowed = {
            "device",
            "hostname",
            "preflight_id",
            "request_key",
            "confirm_serial",
            "confirm_disk",
            "confirm_reboot",
        }
        if set(body) != allowed:
            raise ValueError("提交字段不完整或含未知字段。")
        self.ensure_executable(body["device"])
        device = self.adapter.device(body["device"])
        if (
            body["confirm_serial"] != device["serial"]
            or body["confirm_disk"] is not True
            or body["confirm_reboot"] is not True
        ):
            raise ValueError("请核对设备 SN、系统盘及验收重启范围。")
        if not isinstance(body["request_key"], str) or not 16 <= len(body["request_key"]) <= 80:
            raise ValueError("无效的幂等请求标识。")
        if not self.worker_lock.acquire(blocking=False):
            # A retransmission of the same request should return the existing task.
            with self.store.db() as db:
                row = db.execute(
                    "SELECT data FROM tasks WHERE request_key=?", (body["request_key"],)
                ).fetchone()
            if row:
                return json.loads(row["data"])
            raise ValueError("已有任务执行中，请等待该任务完成。")
        try:
            with self.os_lock():
                plan = self.resources.execution_plan(body["device"])
                device = self.adapter.target_device(body["device"], plan)
                task = {
                    "id": "UI-" + time.strftime("%Y%m%d-") + uuid.uuid4().hex[:10],
                    "device": device["serial"],
                    "hostname": body["hostname"],
                    "status": "queued",
                    "stage": "queued",
                    "actor": actor,
                    "created_at": time.time(),
                    "events": [],
                    "instance_id": device["instance_id"],
                    "profile": device["profile"],
                    "disk_wwn": device["disk_wwn"],
                    "disk_serial": device.get("disk_serial"),
                    "management_ip": device["management_ip"],
                    "current_management_ip": plan["current_management_ip"],
                    "installation_plan": plan,
                    "execution_device": device,
                    "executor": {
                        "namespace": os.environ.get("POD_NAMESPACE")
                        or self.config.get("site", {}).get("namespace"),
                        "controller": self.config.get("site", {}).get("deployment"),
                        "pod_uid": os.environ.get("POD_UID"),
                        "node": os.environ.get("NODE_NAME"),
                    },
                    "source": "nico-ui",
                }
                task, created = self.store.claim(body["preflight_id"], task, body["request_key"])
            if created:

                def work():
                    try:
                        self.executor.run(task)
                    finally:
                        self.worker_lock.release()

                threading.Thread(target=work, daemon=True, name=task["id"]).start()
            else:
                self.worker_lock.release()
            return task
        except Exception:
            self.worker_lock.release()
            raise

    def ensure_executable(self, serial):
        device = next((d for d in self.resources.devices() if d["serial"] == serial), None)
        if not device or not device["executable"]:
            raise ValueError((device or {}).get("execution_reason", "设备尚未接入重装执行范围。"))

    def preparation_preflight(self, task_id, owner):
        def check():
            task = self.store.get(task_id)
            if (
                not task
                or task["status"] != "needs_attention"
                or not self.executor.can_prepare(task)
            ):
                raise ValueError("该任务不能继续设备准备；请查看已执行动作。")
            from pxeye.services.device_config import DeviceConfig

            intent = DeviceConfig(self.adapter, self.resources).get(task["device"])
            profile = intent.get("profile_id") or task["profile"]
            hostname = intent.get("hostname") or task["hostname"]
            disk = intent.get("disk_serial") or task.get("disk_serial")
            with bmc_choice(
                task["device"], task["installation_plan"].get("bmc_choice", "require_planned")
            ):
                result = self.onboarding.deferred_preflight(
                    task["device"], hostname, profile, disk, task_id=task_id
                )
            result["impact"] = installation_impact(result, self.config)
            result["previous_scope"] = task.get("impact_authorization")
            result["previous_plan"] = {
                k: task["installation_plan"].get(k)
                for k in ("device_plan_revision", "management_ip", "disk_serial", "profile_id")
            }
            result.update(
                id=uuid.uuid4().hex, type="continue_prepare", task_id=task_id, owner=owner
            )
            self.store.preflight(result["id"], result, lifetime=900)
            return {k: v for k, v in result.items() if k != "owner"}

        return self.configure(check)

    def continue_preparation(self, task_id, body, owner, actor):
        if (
            set(body) - {"preflight_id", "confirm_serial", "confirm_reboot", "cleanup_scope"}
            or not {"preflight_id", "confirm_serial", "confirm_reboot"} <= set(body)
            or body["confirm_reboot"] is not True
        ):
            raise ValueError("请核对继续设备准备及安装范围。")

        def claim():
            task = self.store.get(task_id)
            if (
                not task
                or task["status"] != "needs_attention"
                or not self.executor.can_prepare(task)
                or body["confirm_serial"] != task["device"]
            ):
                raise ValueError("任务当前不允许继续设备准备。")
            with self.store.db() as db:
                row = db.execute(
                    "SELECT * FROM preflights WHERE id=?", (body["preflight_id"],)
                ).fetchone()
            if not row or row["used"] or row["expires"] < time.time():
                raise ValueError("规划核对已失效，请重新检查。")
            check = json.loads(row["data"])
            if (
                check.get("type") != "continue_prepare"
                or check["task_id"] != task_id
                or check["owner"] != owner
            ):
                raise ValueError("继续准备的规划核对与任务不匹配。")
            with bmc_choice(
                task["device"], check["installation_plan"].get("bmc_choice", "require_planned")
            ):
                fresh = self.onboarding.deferred_preflight(
                    task["device"],
                    check["hostname"],
                    check["profile_id"],
                    check["disk_serial"],
                    task_id=task_id,
                )
            impact = authorize_impact(fresh, self.config, body.get("cleanup_scope"))
            if impact != check.get("impact"):
                raise ValueError("站点策略已变化，请重新核对。")
            if (
                fresh["installation_plan"] != check["installation_plan"]
                or fresh["snapshot"] != check["snapshot"]
            ):
                raise ValueError("规划已变化，请重新检查。")
            task.setdefault("preparation_continuations", []).append(
                {
                    "at": time.time(),
                    "actor": actor,
                    "previous_plan": task["installation_plan"],
                    "previous_preflight": task["preflight"],
                }
            )
            task.update(
                status="queued",
                error=None,
                prepare_available=False,
                stage="queued",
                impact_authorization=impact | {"confirmed_at": time.time(), "actor": actor},
                hostname=check["hostname"],
                profile=check["profile_id"],
                disk_serial=check["disk_serial"],
                management_ip=check["scope"]["management_ip"],
                installation_plan=check["installation_plan"],
                preflight=check,
            )
            # Consume once and update the same reserved task in one transaction.
            with self.store.db() as db:
                db.execute("BEGIN IMMEDIATE")
                changed = db.execute(
                    "UPDATE preflights SET used=1 WHERE id=? AND used=0", (body["preflight_id"],)
                ).rowcount
                if changed != 1:
                    raise ValueError("该规划核对已被使用。")
                db.execute(
                    "UPDATE tasks SET status=?,data=? WHERE id=?",
                    ("queued", json.dumps(task), task_id),
                )
            return task

        task = self.configure(claim)
        self.start_queue()
        return task

    def restart_preflight(self, task_id, owner):
        def check():
            task = self.store.get(task_id)
            if not task:
                raise ValueError("任务不存在。")
            result = self.executor.restart_preflight(task)
            result.update(id=uuid.uuid4().hex, type="restart_preinstall", owner=owner)
            self.store.preflight(result["id"], result)
            return {k: v for k, v in result.items() if k != "owner"}

        return self.configure(check)

    def restart_install(self, task_id, body, owner, actor):
        if (
            set(body) != {"preflight_id", "confirm_serial", "confirm_reboot"}
            or body["confirm_reboot"] is not True
        ):
            raise ValueError("请核对原任务的系统盘、地址及重装范围。")

        def claim():
            task = self.store.get(task_id)
            if not task or body["confirm_serial"] != task["device"]:
                raise ValueError("任务与设备不匹配。")
            fresh = self.executor.restart_preflight(task)
            with self.store.db() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT * FROM preflights WHERE id=?", (body["preflight_id"],)
                ).fetchone()
                if not row or row["used"] or row["expires"] < time.time():
                    raise ValueError("检查已过期或已使用，请重新检查。")
                check = json.loads(row["data"])
                if (
                    check.get("type") != "restart_preinstall"
                    or check.get("task_id") != task_id
                    or check.get("owner") != owner
                    or not fresh["passed"]
                    or not check.get("passed")
                    or check.get("binding") != fresh["binding"]
                ):
                    raise ValueError("检查与当前任务、会话或现场不匹配，请重新检查。")
                task.setdefault("preinstall_continuations", []).append(
                    {"at": time.time(), "actor": actor, "error": task.get("error")}
                )
                task.update(status="queued", stage="queued", error=None, restart_available=False)
                task.setdefault("events", []).append(
                    {
                        "at": time.time(),
                        "stage": "queued",
                        "message": "UI 已重新核对原任务、当前系统及目标规划；确认继续原任务安装。",
                    }
                )
                db.execute("UPDATE preflights SET used=1 WHERE id=?", (body["preflight_id"],))
                db.execute(
                    "UPDATE tasks SET status=?,data=? WHERE id=?",
                    ("queued", json.dumps(task), task_id),
                )
            return task

        result = self.configure(claim)
        self.start_queue()
        return result

    def retry_install_preflight(self, task_id, owner):
        def check():
            task = self.store.get(task_id)
            if not task or task["status"] != "needs_attention":
                raise ValueError("任务当前不允许重试安装。")
            result = self.executor.install_retry_preflight(task)
            result.update(id=uuid.uuid4().hex, type="retry_install", owner=owner)
            self.store.preflight(result["id"], result)
            return {k: v for k, v in result.items() if k != "owner"}

        return self.configure(check)

    def retry_install(self, task_id, body, owner, actor):
        if (
            set(body)
            not in (
                {"preflight_id", "confirm_serial", "confirm_reboot"},
                {"preflight_id", "confirm_serial", "confirm_reboot", "confirm_disk_serial"},
            )
            or body["confirm_reboot"] is not True
        ):
            raise ValueError("请确认原任务系统盘与安装重试范围。")

        def claim():
            task = self.store.get(task_id)
            if (
                not task
                or task["status"] != "needs_attention"
                or body["confirm_serial"] != task["device"]
            ):
                raise ValueError("任务当前不允许重试安装。")
            fresh = self.executor.install_retry_preflight(task)
            if (
                fresh.get("requires_disk_confirmation")
                and body.get("confirm_disk_serial") != fresh["disk_serial"]
            ):
                raise ValueError("本轮已进入写盘阶段；请填写原系统盘序列号，明确确认重新覆盖该盘。")
            with self.store.db() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT * FROM preflights WHERE id=?", (body["preflight_id"],)
                ).fetchone()
                if not row or row["used"] or row["expires"] < time.time():
                    raise ValueError("重试核对已过期或已使用，请重新检查。")
                check = json.loads(row["data"])
                if (
                    check.get("type") != "retry_install"
                    or check.get("task_id") != task_id
                    or check.get("owner") != owner
                    or check.get("binding") != fresh["binding"]
                ):
                    raise ValueError("重试核对与当前任务、会话或现场不匹配。")
                verified = self.executor.verified_retry_configuration(task)
                source_offset = (
                    task["retry_attempt"]["source_offset"]
                    if verified
                    else task.get("console_attempt_offset", 0)
                )
                task.setdefault("installation_retries", []).append(
                    {
                        "at": time.time(),
                        "actor": actor,
                        "reason": fresh.get("failure_kind")
                        or (task.get("installer_failure") or {}).get(
                            "kind", "storage_config_before_write"
                        ),
                        "previous_config_version": task["config_version"],
                        "previous_attempt": task.get("retry_attempt"),
                        "confirmed_disk_serial": body.get("confirm_disk_serial"),
                        "apt_repair": task.get("apt_repair"),
                    }
                )
                task.update(
                    status="queued",
                    stage="queued",
                    error=None,
                    retry_available=False,
                    retry_existing_install=True,
                    installer_failure=None,
                    retry_config_requested=verified,
                    retry_boot_requested=False,
                    retry_attempt={
                        "number": task.get("native_retry_requests", 0) + 1,
                        "state": "config_verified" if verified else "claimed",
                        "source_offset": source_offset,
                    },
                )
                db.execute("UPDATE preflights SET used=1 WHERE id=?", (body["preflight_id"],))
                db.execute(
                    "UPDATE tasks SET status=?,data=? WHERE id=?",
                    (task["status"], json.dumps(task), task_id),
                )
            return task

        result = self.configure(claim)
        self.start_queue()
        return result

    def resume(self, task_id, body, actor):
        task = self.store.get(task_id)
        if task is None or task["status"] != "needs_attention":
            raise ValueError("任务当前不允许继续验收。")
        if (
            set(body) != {"confirm_serial", "confirm_reboot"}
            or body["confirm_serial"] != task["device"]
            or body["confirm_reboot"] is not True
        ):
            raise ValueError("请确认设备 SN 和继续首启/普通重启范围。")
        if not self.worker_lock.acquire(blocking=False):
            raise ValueError("已有任务执行中。")
        try:
            if not self.executor.can_resume(task):
                raise ValueError(
                    "缺少本轮可信 SSH 身份、安装已报告失败，或已请求普通重启，须先核对现场。"
                )
            task["status"] = "running"
            task["error"] = None
            task["resume_available"] = False
            task.setdefault("continuations", []).append(
                {
                    "at": time.time(),
                    "actor": actor,
                    "namespace": os.environ.get("POD_NAMESPACE")
                    or self.config.get("site", {}).get("namespace"),
                    "controller": self.config.get("site", {}).get("deployment"),
                    "pod_uid": os.environ.get("POD_UID"),
                    "node": os.environ.get("NODE_NAME"),
                }
            )
            self.store.save(task)

            def work():
                try:
                    self.executor.resume(task)
                finally:
                    self.worker_lock.release()

            threading.Thread(target=work, daemon=True, name=task["id"] + "-acceptance").start()
            return task
        except Exception:
            self.worker_lock.release()
            raise
