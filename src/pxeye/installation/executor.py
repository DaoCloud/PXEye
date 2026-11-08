from pxeye.services.device_plans import frozen_plan

"""Bounded, single-device reinstall. Recovery is gated by fresh installation evidence."""
import base64
import hashlib
import json
import os
import pty
import re
import select
import socket
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path

from pxeye.common import sha
from pxeye.installation.accept_config import validate_config
from pxeye.installation.install_events import observations
from pxeye.installation.boot_control import (
    in_uefi,
    selection as boot_selection,
    standard_once as standard_boot_once,
    apply as apply_boot,
)


def installer_exit_evidence(text, task_id, trusted_key):
    """Serial progress omits SUCCESS; completed shutdown is a candidate for disk-log verification."""
    if (
        terminal_installer_failure(text)
        or not trusted_key
        or ("NICO_UI_HOSTKEY " + task_id + " " + trusted_key) not in text
    ):
        return False
    for stage in ["Late/run", "Install/install"]:
        pattern = r"^finish:\s+subiquity/" + stage + r":(?:[ \t]*|[ \t]*SUCCESS:[^\n]*)$"
        if not re.search(pattern, text, re.M):
            return False
        if re.search(r"^finish:\s+subiquity/" + stage + r":[ \t]*(?:FAIL|ERROR):", text, re.M):
            return False
    return "reboot: Restarting system" in text


def installation_identity_candidate(text, task, trusted_key):
    """A task-bound SOL key permits read-only disk verification, never success or reset."""
    if not trusted_key or terminal_installer_failure(text):
        return False
    if re.search(
        r"^finish:\s+subiquity/(?:Late/run|Install/install):[ \t]*(?:FAIL|ERROR):", text, re.M
    ):
        return False
    matches = re.findall(
        r"^NICO_UI_HOSTKEY "
        + re.escape(task["id"])
        + r" (ssh-ed25519 [A-Za-z0-9+/=]+)(?: [^\n]*)?\n",
        text,
        re.M,
    )
    return set(matches) == {trusted_key}


def installer_disk_phase_started(text):
    """Storage execution evidence is stronger than the install controller's initialization."""
    return bool(
        re.search(
            r"start:\s+(?:curtin/|subiquity/Install/(?:install/)?(?:partitioning|curtin_install))",
            text,
        )
    )


def prewrite_disk_failure(text):
    """Only the terminal Subiquity disk-conversion failure, before curtin writes."""
    if installer_disk_phase_started(text):
        return None
    match = re.search(
        r"^finish:\s+subiquity/apply_autoinstall_config:[^\n]*(?:matched no disk|autoinstall config did not create needed bootloader partition)[^\n]*$",
        text,
        re.M,
    )
    return match.group(0) if match else None


def installer_execution_started(text):
    """Subiquity may stream child events without the parent start event."""
    return bool(re.search(r"^start:\s+subiquity/Install/install(?:/[^:\n]+)?:", text, re.M))


def terminal_installer_failure(text):
    """Explicit failure evidence must stop monitoring without retrying disk writes."""
    if re.search(r"^NICO_APT_PRECHECK_FAILED:", text, re.M):
        return "软件源预检失败，尚未分区；请检查镜像源和依赖。日志 /run/nico-apt-check/check.log。"
    if (
        re.search(r"^(?:start|finish):\s+subiquity/ErrorReporter/[^\n]*\.install_fail/", text, re.M)
        or re.search(r"^finish:\s+subiquity/Install/install:[ \t]*(?:FAIL|ERROR):", text, re.M)
        or re.search(r"^An error occurred\. Press enter to start a shell\s*$", text, re.M)
    ):
        return (
            "Ubuntu 安装器已报告安装失败；保留系统盘和错误现场，请查看安装日志。不会自动重新安装。"
        )
    return None


def boot_progress(text):
    """Separate NICo platform preparation from actual Linux installer boot evidence."""
    if re.search(
        r"Linux version |Begin: .*casper|Starting .*Ubuntu Server Installer|/casper/(?:vmlinuz|initrd)[^\n]*\.\.\.\s*ok",
        text,
    ):
        return "pxe", "已加载 Ubuntu 安装环境，等待安装器启动。"
    if re.search(r"^Current state: Assigned/HostPlatformConfiguration", text, re.M):
        return (
            "boot",
            "NICo 正在核验 BIOS 和启动顺序；此轮引导暂未放行，等待控制器完成准备并重新启动。",
        )
    return None


def interactive_installer_failure(text):
    """Only a visible interactive screen before installation may be retried."""
    if re.search(
        r"start:\s+(?:curtin/|subiquity/Install/)|NICO_UI_HOSTKEY |reboot: Restarting system", text
    ):
        return None
    clean = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    screen = re.search(
        r"(?:^|\n)[ \t]*(?:Language selection|Choose your language|Select your language|Network configuration|Ubuntu archive mirror configuration)[ \t]+\[ Help \]",
        clean,
    )
    return (
        "安装器进入交互配置，自动安装未生效；请检查启动地址与 Instance 配置关联。"
        if screen
        else None
    )


def verified_installation_identity(text, task, trusted_key):
    if installer_exit_evidence(text, task["id"], trusted_key):
        return True
    # Recovery is for already installed legacy templates that regenerated keys.
    # Keep the original installer evidence and require the new public identity
    # to have been read through the authenticated BMC console, never ssh-keyscan.
    proof = task.get("console_identity_recovery", {})
    if (
        proof.get("source") != "authenticated-bmc-console"
        or proof.get("serial") != task.get("device")
        or proof.get("task_id") != task["id"]
        or proof.get("host_key") != trusted_key
        or not installer_exit_evidence(text, task["id"], proof.get("installer_host_key"))
    ):
        return False
    marker = "NICO_UI_IDENTITY_RECOVERY " + task["id"] + " " + task["device"] + " " + trusted_key
    # GRUB's serial terminal wraps at 80 columns, including inside the key.
    return marker in text.replace("\n", "")


class Console:
    def __init__(self, adapter, device, folder):
        self.adapter, self.device, self.folder = adapter, device, folder
        self.process = None
        self.master = None
        self.raw = b""
        self.last = time.monotonic()
        self.next_attach = 0

    def attach(self):
        self.next_attach = time.monotonic() + 15
        cred = self.adapter.credentials(self.device)
        self.master, slave = pty.openpty()
        env = dict(os.environ, IPMI_PASSWORD=cred["password"])
        self.process = subprocess.Popen(
            [
                "ipmitool",
                "-I",
                "lanplus",
                "-H",
                self.device["bmc_ip"],
                "-U",
                cred["username"],
                "-E",
                "sol",
                "activate",
            ],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            close_fds=True,
            env=env,
        )
        os.close(slave)
        self.last = time.monotonic()

    def detach(self):
        if self.process is None:
            return
        try:
            os.write(self.master, b"\n~.")
        except OSError:
            pass
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        os.close(self.master)
        self.process = None

    def poll(self):
        if (
            self.process is None
            or self.process.poll() is not None
            or time.monotonic() - self.last > 100
        ):
            if time.monotonic() < self.next_attach:
                time.sleep(0.5)
                return
            self.detach()
            self.attach()
        ready, _, _ = select.select([self.master], [], [], 1)
        if ready:
            try:
                data = os.read(self.master, 65536)
            except OSError:
                return
            if data:
                self.last = time.monotonic()
                self.raw += data
                with (self.folder / "console.raw").open("ab") as output:
                    output.write(data)

    @property
    def text(self):
        return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", self.raw.decode(errors="replace")).replace(
            "\r", ""
        )


class Executor:
    def __init__(self, adapter, store):
        self.adapter, self.store = adapter, store

    def event(self, task, stage, message, **extra):
        task["stage"] = stage
        task.setdefault("events", []).append(
            {"at": time.time(), "stage": stage, "message": message, **extra}
        )
        task["updated_at"] = time.time()
        self.store.save(task)
        print(
            json.dumps(
                {"task": task["id"], "stage": stage, "message": message}, ensure_ascii=False
            ),
            flush=True,
        )

    def identity_candidate(self, task, text, trusted_key):
        events = observations(self.adapter, self.store, task)
        signed = any(
            " ".join(e.get("host_key", "").split()[:2]) == trusted_key
            for stage, e in events.items()
            if stage in ("identity", "installed", "shutdown")
        )
        return signed or installation_identity_candidate(text, task, trusted_key)

    def installation_exited(self, task, text, trusted_key):
        events = observations(self.adapter, self.store, task)
        event = events.get("shutdown", {})
        signed = (
            not events.get("failed")
            and bool(trusted_key)
            and " ".join(event.get("host_key", "").split()[:2]) == trusted_key
            and event.get("completion_stages") == ["Late/run", "Install/install"]
        )
        return signed or installer_exit_evidence(text, task["id"], trusted_key)

    def observe_installation(self, task, device, known, *, save=True):
        events = observations(self.adapter, self.store, task)
        if not events:
            return None
        if events.get("failed"):
            raise RuntimeError("安装器已通过签名事件报告安装失败；保留现场，不自动重装。")
        identities = {
            " ".join(e["host_key"].split()[:2])
            for stage, e in events.items()
            if stage in ("identity", "installed", "shutdown") and e.get("host_key")
        }
        boots = {e["boot_id"] for e in events.values()}
        if len(identities) > 1 or len(boots) != 1:
            raise RuntimeError("本轮安装事件出现不同启动或SSH身份，停止自动恢复。")
        key = next(iter(identities), None)
        if key:
            if known.exists() and known.read_text().split()[1:3] != key.split():
                raise RuntimeError("签名安装事件与已有可信SSH身份不同。")
            known.write_text(device["management_ip"] + " " + key + "\n")
            known.chmod(0o600)
        progress = {
            stage: {
                k: v
                for k, v in e.items()
                if k in ("received_at", "boot_id", "console", "log_sha256")
            }
            for stage, e in events.items()
        }
        if progress != task.get("installer_progress"):
            task["installer_progress"] = progress
            if save:
                stage = "handoff" if "shutdown" in events else "install"
                message = (
                    "安装器成功收尾并已进入退出阶段，等待磁盘启动。"
                    if "shutdown" in events
                    else "安装器已成功完成写盘及收尾，等待其自动重启。"
                    if "installed" in events
                    else "已收到任务签名安装事件，进度采集不依赖固定TTY。"
                )
                self.event(task, stage, message)
        return key

    @frozen_plan
    def run(self, task):
        folder = self.adapter.data / "tasks" / task["id"]
        folder.mkdir(parents=True, mode=0o700, exist_ok=True)
        console = None
        try:
            if task.get("deferred_bootstrap"):
                self.bootstrap_first(task, folder)
            device = self.task_device(task)
            task["status"] = "running"
            old = task["preflight"]["snapshot"]
            if task.get("retry_existing_install"):
                console = self.start_install_retry(task, device, folder)
            elif task.get("mode") == "first_install":
                console = self.start_first(task, device, folder)
            else:
                self.event(task, "preflight", "执行前重新核对 Core、BMC、网络规划与目标盘。")
                fresh = self.adapter.preflight(task["device"], task["hostname"])
                if not fresh["passed"]:
                    raise RuntimeError(
                        "执行前检查失败："
                        + "；".join(c["detail"] for c in fresh["checks"] if not c["passed"])
                    )
                old = task["preflight"]["snapshot"]
                if fresh.get("installation_plan") != task.get(
                    "synchronized_plan", task.get("installation_plan")
                ) or fresh["snapshot"].get("baseline_sha256") != old.get("baseline_sha256"):
                    raise RuntimeError("预检后设备、网络或安装模板发生变化，停止执行。")
                if fresh["snapshot"]["live_sha256"] != old["live_sha256"]:
                    raise RuntimeError("预检后 Instance 配置发生变化，停止执行。")
                from pxeye.services.device_plans import DevicePlans
                from pxeye.services.resources import Resources

                self.event(
                    task,
                    "planning",
                    "同步本任务已确认的设备规划到 NICo；尚未更新安装配置或发送 PXE。",
                )
                DevicePlans(self.adapter, Resources(self.adapter, self.store)).synchronize(
                    task["device"], "hardware"
                )
                self.bind_synchronized_plan(task, self.adapter.installation_plan(task["device"]))
                self.verify_materials(task)
                if task["synchronized_plan"] != self.adapter.installation_plan(task["device"]):
                    raise RuntimeError("材料校验期间规划发生变化，停止写入配置。")
                config = self.adapter.render(device, task)
                digest = sha(config["user_data"])
                (folder / "rendered-os.json").write_text(json.dumps(config))
                (folder / "instance.before.json").write_text(
                    json.dumps(self.adapter.instance(device))
                )
                task["user_data_sha256"] = digest
                task["reinstall_config_requested"] = True
                self.event(
                    task,
                    "configure",
                    "已生成安装配置；hostname 和 UI 任务回执将写入新系统。",
                    sha256=digest,
                )
                self.adapter.core(
                    [
                        "--cloud-unsafe-op",
                        self.adapter.config.get("unsafe_operation_reason", "PXEye OS installation"),
                        "instance",
                        "update-os",
                        "--instance",
                        device["instance_id"],
                        "--os",
                        json.dumps(config),
                    ]
                )
                instance = self.adapter.instance(device)
                if sha(instance["config"]["os"]["user_data"]) != digest:
                    raise RuntimeError("Core 配置读回摘要不匹配。")
                task["config_version"] = instance["config_version"]
                console = Console(self.adapter, device, folder)
                console.attach()
                for _ in range(5):
                    console.poll()
                if "SOL Session operational" not in console.text and not self.adapter.config.get(
                    "installer_events_url"
                ):
                    raise RuntimeError("未建立认证 BMC SOL，停止发起重装。")
                if task["synchronized_plan"] != self.adapter.installation_plan(task["device"]):
                    raise RuntimeError("启动前设备或网络规划发生变化，停止发送 PXE。")
                task["address_assignment_requested"] = True
                self.event(
                    task, "network", "同步本设备 NICo 固定地址与安装目标；失败不重放地址写入。"
                )
                task["address_assignment"] = self.adapter.assign_install_address(
                    task["installation_plan"]
                )
                self.event(task, "network", "NICo 固定地址已写入并读回，随后从该地址引导新系统。")
                task["delivery_verification"] = self.adapter.verify_install_delivery(device, task)
                self.event(task, "network", "主启动地址、Instance 地址及本次安装配置已核对一致。")
                # Fresh stream for this task: no historical installer output is read.
                self.event(
                    task, "boot", "已建立认证 SOL；向既有 Instance 发送一次性 custom PXE 重装。"
                )
                task["reinstall_boot_requested"] = True
                self.store.save(task)
                self.adapter.core(
                    ["instance", "reboot", "--instance", device["instance_id"], "--custom-pxe"]
                )
                task["native_reinstall_requests"] = 1
                self.event(task, "boot", "NICo 已接受重装请求，等待主机网络引导。")
            duration = self.adapter.config.get("task_timeout_seconds", 2400)
            task["observation_deadline"] = time.time() + duration
            self.store.save(task)
            deadline = time.monotonic() + duration
            began = time.monotonic()
            last_probe = 0
            exit_recovered = bool(task.get("disk_exit_recovery_requested"))
            install_started = False
            install_finished = None
            trusted_key = None
            known = folder / "known_hosts"
            initial = None
            while time.monotonic() < deadline:
                console.poll()
                text = console.text
                signed_key = self.observe_installation(task, device, known)
                install_started = install_started or bool(
                    task.get("installer_progress", {}).get("started")
                )
                if signed_key:
                    if trusted_key and trusted_key != signed_key:
                        raise RuntimeError("签名安装事件与已有SSH身份不同。")
                    trusted_key = signed_key
                terminal = terminal_installer_failure(text)
                if terminal:
                    task["installer_failure"] = {"kind": "installer_failed", "detail": terminal}
                    raise RuntimeError(terminal)
                interaction = interactive_installer_failure(text)
                if interaction:
                    task["installer_failure"] = {
                        "kind": "interactive_before_install",
                        "detail": interaction,
                    }
                    raise RuntimeError(interaction)
                failure = prewrite_disk_failure(text)
                if failure:
                    task["installer_failure"] = {
                        "kind": "storage_config_before_write",
                        "detail": failure,
                    }
                    raise RuntimeError(
                        "安装器在写盘前拒绝存储配置："
                        + failure.split(":", 2)[-1].strip()
                        + "；修复后可在原任务重试安装。"
                    )
                if not install_started and installer_execution_started(text):
                    install_started = True
                    self.event(
                        task, "install", "已进入自动安装流程，正在检查网络、软件源和系统盘。"
                    )
                progress = boot_progress(text) if not install_started else None
                if progress and task.get("last_boot_progress") != progress[1]:
                    task["last_boot_progress"] = progress[1]
                    self.event(task, *progress)
                matches = re.findall(
                    r"NICO_UI_HOSTKEY "
                    + re.escape(task["id"])
                    + r" (ssh-ed25519 [A-Za-z0-9+/=]+)(?: [^\n]*)?\n",
                    text,
                )
                if matches and not trusted_key:
                    if len(set(matches)) != 1:
                        raise RuntimeError("本轮认证 SOL 返回多个不同的目标 SSH 身份。")
                    trusted_key = matches[0]
                    base64.b64decode(trusted_key.split()[1], validate=True)
                    known.write_text(device["management_ip"] + " " + trusted_key + "\n")
                    self.event(
                        task, "install", "从本轮任务标记绑定的认证 BMC SOL 取得新 SSH 身份。"
                    )
                if install_finished is None and self.installation_exited(task, text, trusted_key):
                    install_finished = time.monotonic()
                    self.event(
                        task, "firstboot", "安装器结束并请求重启；等待磁盘 OS 的日志与新系统验收。"
                    )
                if time.monotonic() - last_probe < 12:
                    continue
                last_probe = time.monotonic()
                if not install_started and time.monotonic() - began > 140:
                    try:
                        machine_state = str(self.adapter.machine(device).get("state", ""))
                    except RuntimeError as error:
                        task["network_entry_observation_error"] = str(error)
                        self.store.save(task)
                    else:
                        recovery = task.get("automatic_recovery") or {}
                        bios_blocked = machine_state.startswith(("Assigned/Failed", "Failed")) or (
                            machine_state.startswith("Assigned/HostPlatformConfiguration")
                            and "PollingBiosSetup" in machine_state
                        )
                        if bios_blocked and not recovery:
                            if self.automatic_boot_recovery(task):
                                duration = self.adapter.config.get("task_timeout_seconds", 2400)
                                deadline = max(deadline, time.monotonic() + duration)
                                began = time.monotonic()
                                continue
                        if machine_state.startswith(("Assigned/Failed", "Failed")):
                            if recovery.get("state") in (
                                "observing",
                                "waiting_reboot",
                                "waiting_installation",
                            ):
                                if time.time() > recovery.get("deadline", 0):
                                    raise RuntimeError(
                                        "启动配置自动修复后，NICo 未在限定时间恢复；保留现场。"
                                    )
                                continue
                            raise RuntimeError(
                                "NICo 启动配置失败，且当前证据不允许自动修复；保留原任务。"
                            )
                        self.observe_automatic_recovery(task, machine_state)
                if not trusted_key or (
                    not install_finished and not self.identity_candidate(task, text, trusted_key)
                ):
                    continue
                try:
                    candidate = self.accept(device, task, trusted_key, known)
                except Exception:
                    candidate = {"passed": False, "error": "等待可信 SSH 首启可达"}
                if candidate.get("report") and candidate.get("category") == "service_connectivity":
                    task["installation_checks"] = candidate["report"]
                    self.store.save(task)
                if candidate["passed"]:
                    initial = candidate["report"]
                    self.record_disk_evidence(task, initial, text, trusted_key)
                    (folder / "initial.json").write_text(json.dumps(initial, indent=2))
                    task["initial"] = initial
                    self.event(task, "reboot", "新系统独立验收通过，执行不带 PXE 的普通重启复验。")
                    break
                if task.get("last_acceptance_error") != candidate["error"]:
                    task["last_acceptance_error"] = candidate["error"]
                    self.event(task, "firstboot", "首启验收等待：" + candidate["error"])
                # Exit is a candidate; target disk logs must prove SUCCESS before completion.
                if (
                    install_finished
                    and not exit_recovered
                    and time.monotonic() - install_finished
                    > self.adapter.config.get("boot_handoff_grace_seconds", 300)
                ):
                    system = self.observe_boot_system(task, device)
                    if system and in_uefi(system) and not self.ssh_open(device):
                        exit_recovered = self.recover_disk_boot(task, device, system)
            if initial is None:
                raise TimeoutError(
                    "装机/首启未在限定时间完成；保留 Instance、任务锁和现场，不自动重装。"
                )
            self.finish(
                task,
                device,
                console,
                folder,
                known,
                trusted_key,
                initial,
                int(bool(task.get("automatic_recovery"))) + int(exit_recovered),
            )
        except Exception as error:
            task["status"] = "needs_attention"
            task["error"] = str(error)
            task["resume_available"] = self.can_resume(task)
            task["prepare_available"] = self.can_prepare(task)
            task["retry_available"] = self.can_retry_install(task)
            task["restart_available"] = self.can_restart_preinstall(task)
            self.event(task, task.get("stage", "preflight"), "任务需要处理：" + str(error))
        finally:
            if console:
                console.detach()

    @staticmethod
    def bind_synchronized_plan(task, actual):
        """Only our confirmed address synchronization may change its native address binding."""
        expected = task["installation_plan"]
        dynamic = {
            "boot_addresses",
            "binding_revision",
            "disk_selection",
            "previous_disk_serial",
            "disk_change",
        }
        allowed_addresses = set(expected.get("boot_addresses", [])) | {expected["management_ip"]}
        if (
            {k: v for k, v in expected.items() if k not in dynamic}
            != {k: v for k, v in actual.items() if k not in dynamic}
            or not actual.get("boot_addresses")
            or not set(actual["boot_addresses"]) <= allowed_addresses
        ):
            raise RuntimeError("规划同步后的接口、子网或地址变化超出本任务范围，停止更新安装配置。")
        task["synchronized_plan"] = actual

    @staticmethod
    def can_restart_preinstall(task):
        """Only a reinstall stopped before any installation configuration or power request."""
        allowed = {"queued", "preflight", "planning", "materials"}
        return (
            task.get("status") == "needs_attention"
            and task.get("mode", "reinstall") == "reinstall"
            and task.get("stage") in allowed
            and all(event.get("stage") in allowed for event in task.get("events", []))
            and not any(
                task.get(key)
                for key in (
                    "config_version",
                    "user_data_sha256",
                    "reinstall_config_requested",
                    "reinstall_boot_requested",
                    "address_assignment_requested",
                    "allocation_requested",
                    "native_allocation_requests",
                    "native_reinstall_requests",
                    "retry_config_requested",
                    "retry_boot_requested",
                    "normal_reboot_requested",
                    "disk_exit_recovery_requested",
                )
            )
        )

    @frozen_plan
    def restart_preflight(self, task):
        from pxeye.services.device_plans import DevicePlans
        from pxeye.services.resources import Resources
        from pxeye.common import digest

        if not self.can_restart_preinstall(task):
            raise ValueError(
                "仅允许安装配置更新前停止的重装任务重新检查；存在安装或电源请求时须核对现场。"
            )
        plans = DevicePlans(self.adapter, Resources(self.adapter, self.store))
        record = plans.get(task["device"], current=True)
        if digest(record) != task["installation_plan"].get("device_plan_revision"):
            raise ValueError("设备规划已变化，不能按原任务继续。")
        if plans.synchronization_state(task["device"]) in ("requesting", "needs_attention"):
            raise ValueError("NICo规划同步结果未知，须先核对同步账本，不能重复发送。")
        fresh = self.adapter.preflight(task["device"], task["hostname"])
        old = task["preflight"]["snapshot"]
        current = fresh["snapshot"]
        if fresh["passed"] and (
            fresh.get("installation_plan")
            != task.get("synchronized_plan", task.get("installation_plan"))
            or any(
                current.get(key) != old.get(key)
                for key in ("baseline_sha256", "live_sha256", "config_version")
            )
        ):
            raise ValueError("原任务的规划或 Instance 配置已变化，停止继续。")
        return {
            "task_id": task["id"],
            "device": task["device"],
            "hostname": task["hostname"],
            "management_ip": task["management_ip"],
            "current_management_ip": task.get("current_management_ip"),
            "disk_serial": task.get("disk_serial"),
            "disk_wwn": task.get("disk_wwn"),
            "instance_id": task["instance_id"],
            "passed": fresh["passed"],
            "checks": fresh["checks"],
            "binding": digest(
                {
                    "task": task,
                    "plan": fresh.get("installation_plan"),
                    "snapshot": {
                        key: current.get(key)
                        for key in ("baseline_sha256", "live_sha256", "config_version")
                    },
                }
            ),
        }

    @staticmethod
    def can_prepare(task):
        return (
            task.get("mode") == "first_install"
            and task.get("deferred_bootstrap") is True
            and not any(
                task.get(k)
                for k in (
                    "allocation_requested",
                    "address_assignment_requested",
                    "native_allocation_requests",
                    "native_reinstall_requests",
                )
            )
        )

    def attempt_text(self, task):
        path = self.adapter.data / "tasks" / task["id"] / "console.raw"
        raw = path.read_bytes()[task.get("console_attempt_offset", 0) :]
        return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", raw.decode(errors="replace")).replace(
            "\r", ""
        )

    @staticmethod
    def verified_retry_configuration(task):
        attempt = task.get("retry_attempt") or {}
        return (
            attempt.get("state") == "config_verified"
            and task.get("retry_config_requested") is True
            and not task.get("retry_boot_requested")
            and isinstance(attempt.get("source_offset"), int)
            and attempt["source_offset"] >= 0
        )

    def retry_failure_text(self, task):
        if self.verified_retry_configuration(task):
            task = dict(task, console_attempt_offset=task["retry_attempt"]["source_offset"])
        return self.attempt_text(task)

    def can_retry_install(self, task):
        allowed = (
            task.get("mode") == "first_install"
            and task.get("native_allocation_requests") == 1
            or task.get("mode") == "reinstall"
            and task.get("native_reinstall_requests") == 1
        )
        if not allowed or task.get("normal_reboot_requested") or not task.get("execution_device"):
            return False
        attempt = task.get("retry_attempt")
        if attempt:
            if attempt.get("state") not in (
                "claimed",
                "accepted",
            ) and not self.verified_retry_configuration(task):
                return False
        elif task.get("retry_config_requested") or task.get("retry_boot_requested"):
            # r4 recorded exactly one accepted native retry before attempt ledgers existed.
            if not (
                task.get("native_retry_requests") == 1
                and task.get("console_attempt_offset", 0) > 0
                and task.get("retry_boot_requested")
            ):
                return False
        try:
            text = self.retry_failure_text(task)
            failure = prewrite_disk_failure(text) if task.get("mode") == "first_install" else None
            return bool(
                failure or interactive_installer_failure(text) or terminal_installer_failure(text)
            ) and not re.search(r"NICO_UI_HOSTKEY |reboot: Restarting system", text)
        except (OSError, KeyError, TypeError):
            return False

    def wait_for_boot_read(self, task, error):
        if task.get("last_boot_read_error") != str(error):
            task["last_boot_read_error"] = str(error)
            self.event(
                task, "firstboot", "BMC 启动信息暂时读取失败，继续等待系统启动：" + str(error)
            )

    def observe_boot_system(self, task, device):
        try:
            return self.adapter.redfish(device)
        except RuntimeError as error:
            self.wait_for_boot_read(task, error)
            return None

    @staticmethod
    def obsolete_automatic_recovery(recovery):
        """The v1 gate used an internal NICo flag omitted by the public Instance API."""
        return (
            recovery.get("version") == 1
            and recovery.get("state") == "blocked"
            and recovery.get("error")
            == "原 Instance 已没有待执行的一次性 custom PXE，停止自动恢复。"
            and len(recovery.get("steps", [])) == 5
            and all(
                step.get("status") == ("failed" if step.get("id") == "diagnosis" else "pending")
                for step in recovery.get("steps", [])
            )
        )

    @staticmethod
    def can_start_automatic_recovery(task):
        """Whether an accepted install may enter the bounded BIOS recovery runbook."""
        requests = int(task.get("native_reinstall_requests") or 0) + int(
            task.get("native_allocation_requests") or 0
        )
        legacy = task.get("network_entry_recovery") or {}
        recovery = task.get("automatic_recovery") or {}
        return (
            task.get("status") in ("running", "needs_attention")
            and task.get("stage") in ("boot", "pxe")
            and requests == 1
            and (not recovery or Executor.obsolete_automatic_recovery(recovery))
            and legacy.get("state") != "reboot_accepted"
            and not task.get("installer_failure")
            and not task.get("installer_progress")
            and not task.get("normal_reboot_requested")
            and not task.get("disk_exit_recovery_requested")
            and not task.get("retry_boot_requested")
        )

    @staticmethod
    def recovery_step(recovery, step_id, status, detail=None):
        step = next(item for item in recovery["steps"] if item["id"] == step_id)
        step["status"] = status
        if detail:
            step["detail"] = detail
        step["updated_at"] = time.time()
        recovery["updated_at"] = step["updated_at"]

    def automatic_boot_recovery(self, task):
        """Repair one proven pre-installer BIOS convergence block without replaying PXE."""
        if not self.can_start_automatic_recovery(task):
            return False
        folder = self.adapter.data / "tasks" / task["id"]
        if not (folder / "event-binding.json").exists():
            return False
        known = folder / "known_hosts"
        if known.exists() and known.read_text().strip():
            return False
        try:
            text = self.attempt_text(task)
        except OSError:
            text = ""
        if (
            installer_execution_started(text)
            or terminal_installer_failure(text)
            or interactive_installer_failure(text)
            or prewrite_disk_failure(text)
            or observations(self.adapter, self.store, task)
        ):
            return False

        device = self.task_device(task)
        self.check_bound(device, task)
        machine = self.adapter.machine(device)
        state = str(machine.get("state", ""))
        polling = state.startswith("Assigned/HostPlatformConfiguration") and (
            "PollingBiosSetup" in state
        )
        failed = state.startswith("Assigned/Failed") and "BiosSetupFailed" in state
        if machine.get("id") != device.get("machine_id"):
            raise RuntimeError("NICo Machine 与任务绑定不一致。")
        if not (polling or failed):
            return False

        previous = task.get("automatic_recovery")
        recovery = {
            "version": 2,
            "code": "NICO_BIOS_SETUP_FAILED",
            "source": "NICo",
            "title": "启动配置自动修复",
            "state": "diagnosing",
            "started_at": time.time(),
            "updated_at": time.time(),
            "steps": [
                {"id": "diagnosis", "label": "核对现场", "status": "running"},
                {"id": "configuration", "label": "修复配置", "status": "pending"},
                {"id": "nico", "label": "NICo 接管", "status": "pending"},
                {"id": "reboot", "label": "网络重启", "status": "pending"},
                {"id": "installation", "label": "继续安装", "status": "pending"},
            ],
            "legacy_recovery": task.get("network_entry_recovery"),
        }
        if previous:
            task.setdefault("automatic_recovery_history", []).append(previous)
        task["automatic_recovery"] = recovery
        self.store.save(task)
        try:
            system = self.adapter.redfish(device)
            plan = boot_selection(self.adapter, device, system, "Pxe")
            if (
                plan.get("method") != "oem-order"
                or plan.get("body", {}).get("BootOrderNext", [None])[0] != "Network"
            ):
                raise RuntimeError("当前硬件没有已认证的持久网络优先恢复适配器。")
            recovery.update(
                machine_id=device["machine_id"],
                instance_id=device["instance_id"],
                boot_mac=device["boot_mac"],
                change={
                    "before": plan["before"].get("BootOrderNext", []),
                    "after": plan["body"]["BootOrderNext"],
                },
            )
            self.recovery_step(
                recovery,
                "diagnosis",
                "completed",
                "设备、Instance、启动口、NICo BIOS状态和未写盘证据一致。",
            )
            self.recovery_step(recovery, "configuration", "running", "写入网络优先并读回。")
            recovery["state"] = "config_requesting"
            self.store.save(task)
            if plan["before"].get("BootOrderNext") != plan["body"]["BootOrderNext"]:
                apply_boot(self.adapter, device, plan)
                config_detail = "启动顺序已写入并读回一致。"
            else:
                config_detail = "启动顺序已经符合目标，无需重复写入。"
            recovery["state"] = "config_verified"
            self.recovery_step(recovery, "configuration", "completed", config_detail)
            recovery["state"] = "observing"
            recovery["deadline"] = time.time() + self.adapter.config.get(
                "task_timeout_seconds", 2400
            )
            task["observation_deadline"] = recovery["deadline"]
            task["error"] = None
            self.recovery_step(
                recovery, "nico", "running", "等待 NICo 重新检查 BIOS 与启动顺序。"
            )
            self.event(
                task,
                "boot",
                "已修复 NICo 等待的网络启动顺序；等待原状态机继续，不重发安装请求。",
                recovery=True,
                recovery_code=recovery["code"],
            )
            return True
        except Exception as error:
            state = recovery.get("state")
            uncertain = state == "config_requesting"
            recovery["state"] = "unknown" if uncertain else "blocked"
            recovery["error"] = str(error)
            running = next(
                (item for item in recovery["steps"] if item["status"] == "running"), None
            )
            if running:
                self.recovery_step(recovery, running["id"], "failed", str(error))
            self.store.save(task)
            raise

    def observe_automatic_recovery(self, task, machine_state=None):
        recovery = task.get("automatic_recovery") or {}
        if recovery.get("state") not in (
            "observing",
            "waiting_reboot",
            "waiting_installation",
            "waiting_installation_retry",
            "waiting_standard_pxe_retry",
        ):
            return False
        if machine_state is None:
            machine_state = str(self.adapter.machine(self.task_device(task)).get("state", ""))
        if machine_state.startswith("Assigned/Failed"):
            return False
        if recovery["state"] == "observing" and (
            machine_state.startswith("Assigned/HostPlatformConfiguration")
            and "PollingBiosSetup" in machine_state
        ):
            return True
        if recovery["state"] == "observing":
            recovery["state"] = "waiting_reboot"
            self.recovery_step(
                recovery, "nico", "completed", "NICo 已离开 BiosSetupFailed 并接管原状态机。"
            )
            self.recovery_step(recovery, "reboot", "running", "等待NICo完成原custom PXE重启。")
            self.event(task, "boot", "NICo 已接管恢复流程，等待原 custom PXE 重启完成。")
        if recovery["state"] == "waiting_reboot" and machine_state.startswith("Assigned/Ready"):
            recovery["state"] = "waiting_installation"
            self.recovery_step(recovery, "reboot", "completed", "NICo 已完成原请求的网络重启。")
            self.recovery_step(
                recovery, "installation", "running", "等待原 custom PXE 进入安装器。"
            )
            self.event(task, "boot", "NICo 启动配置已恢复，等待原安装请求进入安装器。")
        if recovery["state"] == "waiting_installation":
            self.recover_unconsumed_network_boot(task, machine_state)
        elif recovery["state"] == "waiting_installation_retry":
            self.recover_standard_pxe_boot(task, machine_state)
        device = self.task_device(task)
        folder = self.adapter.data / "tasks" / task["id"]
        self.observe_installation(task, device, folder / "known_hosts")
        if task.get("installer_progress", {}).get("started"):
            recovery["state"] = "completed"
            recovery["completed_at"] = time.time()
            self.recovery_step(
                recovery, "installation", "completed", "原安装请求已进入安装器，正在安装系统。"
            )
            self.store.save(task)
        return True

    def installation_not_started(self, task):
        """Return true only while this attempt has no installer or disk-write evidence."""
        folder = self.adapter.data / "tasks" / task["id"]
        known = folder / "known_hosts"
        try:
            text = self.attempt_text(task)
        except OSError:
            text = ""
        return not (
            task.get("installer_progress")
            or task.get("installer_failure")
            or (known.exists() and known.read_text().strip())
            or installer_execution_started(text)
            or installer_disk_phase_started(text)
            or observations(self.adapter, self.store, task)
        )

    def recover_unconsumed_network_boot(self, task, machine_state):
        """Use one standard PXE override when NICo is Ready but PXE was not consumed."""
        recovery = task["automatic_recovery"]
        if recovery.get("standard_pxe_retry"):
            return False
        grace = self.adapter.config.get("automatic_network_boot_grace_seconds", 180)
        if isinstance(grace, bool) or not isinstance(grace, (int, float)):
            grace = 180
        reboot_step = next(item for item in recovery["steps"] if item["id"] == "reboot")
        if time.time() - reboot_step.get("updated_at", recovery["started_at"]) < max(60, grace):
            return False
        if not machine_state.startswith("Assigned/Ready"):
            return False
        if not self.installation_not_started(task):
            return False

        return self.request_standard_pxe_boot(
            task,
            machine_state,
            "NICo 已 Ready，但限定时间内没有主机 DHCP、PXE 或安装器证据。",
        )

    def recover_standard_pxe_boot(self, task, machine_state):
        """Upgrade an older two-stage recovery ledger to the standard PXE override."""
        recovery = task["automatic_recovery"]
        if recovery.get("standard_pxe_retry"):
            return False
        previous = recovery.get("network_boot_retry") or {}
        if previous.get("state") != "reset_accepted":
            return False
        grace = self.adapter.config.get("automatic_network_boot_grace_seconds", 180)
        if isinstance(grace, bool) or not isinstance(grace, (int, float)):
            grace = 180
        if time.time() - previous.get("accepted_at", time.time()) < max(60, grace):
            return False
        return self.request_standard_pxe_boot(
            task,
            machine_state,
            "旧版持久网络优先恢复没有产生 PXE 证据。",
        )

    def request_standard_pxe_boot(self, task, machine_state, reason):
        """Apply one bounded Redfish Pxe/Once override without replaying installation."""
        recovery = task["automatic_recovery"]
        if recovery.get("standard_pxe_retry"):
            return False
        if not machine_state.startswith("Assigned/Ready"):
            return False
        if (
            task.get("native_allocation_requests") != 1
            and task.get("native_reinstall_requests") != 1
        ):
            return False
        if not self.installation_not_started(task):
            return False

        device = self.task_device(task)
        self.check_bound(device, task)
        system = self.adapter.redfish(device)
        plan = standard_boot_once(self.adapter, device, system, "Pxe")
        retry = {
            "state": "override_requesting",
            "reason": reason,
            "before": {
                "target": plan["before"].get("BootSourceOverrideTarget"),
                "enabled": plan["before"].get("BootSourceOverrideEnabled"),
            },
            "after": {"target": "Pxe", "enabled": "Once"},
            "requested_at": time.time(),
        }
        recovery["standard_pxe_retry"] = retry
        recovery["state"] = "standard_pxe_override_requesting"
        self.recovery_step(
            recovery,
            "installation",
            "running",
            "原安装请求尚未进入网络引导；正在设置一次性PXE启动。",
        )
        self.store.save(task)
        try:
            apply_boot(self.adapter, device, plan)
            retry["state"] = "reset_requesting"
            retry["configured_at"] = time.time()
            recovery["state"] = "standard_pxe_reset_requesting"
            self.check_bound(device, task)
            current = str(self.adapter.machine(device).get("state", ""))
            if not current.startswith("Assigned/Ready"):
                raise RuntimeError("NICo 已离开 Assigned/Ready，不执行单次PXE重启。")
            self.store.save(task)
            self.adapter.redfish(
                device, "/Actions/ComputerSystem.Reset", "POST", {"ResetType": "ForceRestart"}
            )
        except Exception as error:
            recovery["state"] = "unknown"
            recovery["error"] = "单次PXE恢复结果需要核对：" + str(error)
            retry["state"] = "unknown"
            retry["error"] = str(error)
            self.recovery_step(recovery, "installation", "failed", recovery["error"])
            self.store.save(task)
            raise RuntimeError(recovery["error"]) from error

        retry.update(state="reset_accepted", reboot_accepted=True, accepted_at=time.time())
        recovery["state"] = "waiting_standard_pxe_retry"
        recovery["deadline"] = time.time() + self.adapter.config.get(
            "task_timeout_seconds", 2400
        )
        task["observation_deadline"] = recovery["deadline"]
        self.recovery_step(
            recovery,
            "installation",
            "running",
            "已设置标准Redfish单次PXE并重启，等待原安装请求进入安装器。",
        )
        self.event(
            task,
            "boot",
            "原安装请求未进入网络引导；已设置一次性PXE并受控重启，不重发custom PXE。",
            recovery=True,
            recovery_code=recovery["code"],
        )
        return True

    def recover_disk_boot(self, task, device, system):
        """One recovery only, after trustworthy installer shutdown and observed UEFI."""
        if (
            task.get("disk_exit_recovery_requested")
            or task.get("normal_reboot_requested")
            or (
                task.get("native_allocation_requests") != 1
                and task.get("native_reinstall_requests") != 1
            )
        ):
            return False
        if (
            system.get("SerialNumber") != device["serial"]
            or not in_uefi(system)
            or self.ssh_open(device)
        ):
            return False
        folder = self.adapter.data / "tasks" / task["id"]
        parts = (folder / "known_hosts").read_text().split()
        if (
            parts[0] != device["management_ip"]
            or parts[1] != "ssh-ed25519"
            or not self.installation_exited(task, self.attempt_text(task), " ".join(parts[1:3]))
        ):
            raise RuntimeError("缺少本轮安装结束与退出证据，不执行启动恢复。")
        self.check_bound(device, task)
        machine = self.adapter.machine(device)
        if not str(machine.get("state", "")).startswith("Assigned/Ready"):
            raise RuntimeError("NICo尚未返回Assigned/Ready，不执行磁盘启动恢复。")
        instance = self.adapter.instance(device)
        if instance.get("use_custom_pxe_on_boot") or instance.get("useCustomPxeOnBoot"):
            raise RuntimeError("NICo仍保留一次性安装请求，不执行磁盘启动恢复。")
        try:
            plan = boot_selection(self.adapter, device, system, "Hdd")
        except RuntimeError as error:
            # Old BMC firmware can expose the Lenovo BootSettings link while the
            # linked resource temporarily returns 500 during UEFI POST.  This is
            # still a read-only observation: keep waiting and never create the
            # write ledger until a complete boot plan has been read.
            self.wait_for_boot_read(task, error)
            return False
        task["disk_exit_recovery_requested"] = True
        task["disk_exit_compatibility"] = {
            "source": "bmc-observed-capability",
            "plan": plan,
            "state": "config_requesting",
            "requested_at": time.time(),
        }
        self.event(
            task,
            "handoff",
            "安装器已成功收尾并退出；BMC确认停在UEFI，准备一次磁盘启动恢复。",
            recovery=True,
        )
        apply_boot(self.adapter, device, plan)
        task["disk_exit_compatibility"]["state"] = "reset_requesting"
        self.check_bound(device, task)
        self.store.save(task)
        self.adapter.redfish(
            device, "/Actions/ComputerSystem.Reset", "POST", {"ResetType": "ForceRestart"}
        )
        task["disk_exit_compatibility"].update(state="reset_accepted", reboot_accepted=True)
        self.event(
            task, "firstboot", "磁盘启动目标已读回，恢复重启已受理；等待目标系统盘与本轮回执验收。"
        )
        return True

    @frozen_plan
    def install_retry_preflight(self, task):
        from pxeye.services.onboarding import discovery_info
        from pxeye.services.resources import Resources
        from pxeye.common import digest

        if not self.can_retry_install(task):
            raise ValueError(
                "仅允许有本轮明确安装失败证据的任务重新检查；请求结果不确定时须先排障。"
            )
        device = self.task_device(task)
        self.check_bound(device, task)
        instance = self.adapter.instance(device)
        if (
            instance.get("machine_id") != device["machine_id"]
            or instance.get("config_version") != task["config_version"]
        ):
            raise ValueError("原 Instance 的关联或配置版本已变化。")
        machine = self.adapter.machine(device)
        info = discovery_info(machine)
        if (
            task["device"]
            not in {
                info.get("dmi_data", {}).get("product_serial"),
                info.get("dmi_data", {}).get("chassis_serial"),
            }
            or len(
                [
                    d
                    for d in info.get("block_devices", [])
                    if d.get("serial") == device["disk_serial"]
                ]
            )
            != 1
        ):
            raise ValueError("原任务的 Machine 身份或系统盘已变化。")
        system = self.adapter.redfish(device)
        if system.get("SerialNumber") != task["device"]:
            raise ValueError("BMC 返回的序列号与原任务不匹配。")
        fresh = Resources(self.adapter, self.store).execution_plan(
            task["device"], device=dict(device)
        )
        dynamic = {"current_management_ip", "boot_addresses", "binding_revision"}
        if device["management_ip"] not in fresh["boot_addresses"] or any(
            task["installation_plan"].get(k) != v for k, v in fresh.items() if k not in dynamic
        ):
            raise ValueError("原任务的网络、规划或安装方案已变化，停止重试。")
        baseline = (
            digest(self.adapter.baseline(device))
            if task.get("mode") == "first_install"
            else sha(json.dumps(self.adapter.baseline(device), sort_keys=True))
        )
        if baseline != task["preflight"]["snapshot"]["baseline_sha256"]:
            raise ValueError("原任务安装模板已变化，停止重试。")
        try:
            self.adapter.verify_install_delivery(device, task)
        except RuntimeError as error:
            raise ValueError(str(error)) from None
        text = self.retry_failure_text(task)
        terminal = terminal_installer_failure(text)
        requires_disk = bool(terminal and installer_disk_phase_started(text))
        failure = terminal or prewrite_disk_failure(text) or interactive_installer_failure(text)
        return {
            "task_id": task["id"],
            "device": task["device"],
            "hostname": task["hostname"],
            "management_ip": device["management_ip"],
            "disk_serial": device["disk_serial"],
            "instance_id": device["instance_id"],
            "passed": True,
            "requires_disk_confirmation": requires_disk,
            "failure_kind": (
                "installer_failed_after_write" if requires_disk else "installer_failed_before_write"
            )
            if terminal
            else (
                "interactive_before_install"
                if interactive_installer_failure(text)
                else "storage_config_before_write"
            ),
            "failure_detail": failure.split(":", 2)[-1].strip(),
            "binding": digest(
                {
                    "plan": task["installation_plan"],
                    "config_version": task["config_version"],
                    "failure": failure,
                    "requires_disk_confirmation": requires_disk,
                    "apt_repair": task.get("apt_repair"),
                }
            ),
        }

    def start_install_retry(self, task, device, folder):
        # Preserve this Instance and address. Never repeat Allocate or ingestion cleanup.
        self.install_retry_preflight(task)
        self.verify_materials(task)
        self.install_retry_preflight(task)
        if self.verified_retry_configuration(task):
            self.event(
                task,
                "configure",
                "原任务安装配置已写入并核对；完成地址校验后直接继续网络引导，不重复更新配置。",
            )
        else:
            config = self.adapter.render(device, task)
            task["retry_config_requested"] = True
            task.setdefault("retry_attempt", {"number": task.get("native_retry_requests", 0) + 1})[
                "state"
            ] = "config_requesting"
            self.event(
                task,
                "configure",
                "更新原任务的自动安装配置；复用原 Instance、地址和系统盘，不重复接入清理。",
            )
            self.adapter.core(
                [
                    "--cloud-unsafe-op",
                    self.adapter.config.get("unsafe_operation_reason", "PXEye OS installation"),
                    "instance",
                    "update-os",
                    "--instance",
                    device["instance_id"],
                    "--os",
                    json.dumps(config),
                ]
            )
            instance = self.adapter.instance(device)
            if instance.get("machine_id") != device["machine_id"] or sha(
                instance["config"]["os"]["user_data"]
            ) != sha(config["user_data"]):
                raise RuntimeError("重试配置读回不匹配；不重复请求。")
            task["user_data_sha256"] = sha(config["user_data"])
            task["config_version"] = instance["config_version"]
            task["retry_attempt"]["state"] = "config_verified"
            (folder / "rendered-os.retry.json").write_text(json.dumps(config))
        console = Console(self.adapter, device, folder)
        try:
            task["console_attempt_offset"] = (folder / "console.raw").stat().st_size
            console.attach()
            for _ in range(5):
                console.poll()
            if "SOL Session operational" not in console.text and not self.adapter.config.get(
                "installer_events_url"
            ):
                raise RuntimeError("重试前未建立认证 BMC SOL。")
            self.check_bound(device, task)
            task["delivery_verification"] = self.adapter.verify_install_delivery(device, task)
            task["retry_boot_requested"] = True
            task["retry_attempt"]["state"] = "boot_requesting"
            self.event(
                task,
                "boot",
                "按管理员确认重新安装原系统盘；复用原 Instance，不重复接入清理、分配地址或自动重放启动请求。",
            )
            self.adapter.core(
                ["instance", "reboot", "--instance", device["instance_id"], "--custom-pxe"]
            )
            task["native_retry_requests"] = task.get("native_retry_requests", 0) + 1
            task["retry_attempt"]["state"] = "accepted"
            self.event(task, "boot", "NICo 已接受原 Instance 的安装重试，等待本轮网络引导。")
            return console
        except Exception:
            console.detach()
            raise

    def select_install_boot_interface(self, task, onboarding, row, machine):
        """Apply the confirmed install NIC through NICo; never change another host."""
        from pxeye.services.onboarding import discovery_info
        from pxeye.common import value_id

        if (
            task.get("mode") != "first_install"
            or task.get("device") != row["chassis_serial_number"]
        ):
            raise RuntimeError("主启动口选择缺少本次首次安装的设备确认。")
        info = discovery_info(machine)
        if task["device"] not in {
            info.get("dmi_data", {}).get("product_serial"),
            info.get("dmi_data", {}).get("chassis_serial"),
        }:
            raise RuntimeError("主启动口选择前 Scout 身份不匹配。")
        hosts = [
            n
            for n in row.get("interfaces", [])
            if n.get("primary") and n.get("role", "host") in ("host", "unspecified", 0, 1)
        ]
        if len(hosts) != 1:
            raise RuntimeError("安装规划需要唯一的主启动网卡。")
        mac = hosts[0]["mac_address"].lower()
        if (
            len(
                [
                    n
                    for n in info.get("network_interfaces", [])
                    if n.get("mac_address", "").lower() == mac
                ]
            )
            != 1
        ):
            raise RuntimeError("Scout 没有报告唯一匹配的规划启动网卡。")
        interfaces = self.adapter.rpc("FindInterfaces", {}).get("interfaces", [])
        owned = [n for n in interfaces if n.get("machineId", {}).get("id") == machine["id"]]
        bmc = [n for n in owned if n.get("isBmc")]
        links = [n for n in owned if not n.get("isBmc") and n.get("macAddress", "").lower() == mac]
        if (
            len(bmc) != 1
            or bmc[0].get("macAddress", "").lower() != row["bmc_mac_address"].lower()
            or len(links) != 1
        ):
            raise RuntimeError("规划启动网卡或 BMC 不属于唯一匹配的 NICo Machine。")
        if links[0].get("primaryInterface"):
            return False
        request = {
            "host_machine_id": {"id": machine["id"]},
            "interface_id": {"value": value_id(links[0]["id"])},
            "force_reconcile": False,
        }
        if not request["interface_id"]["value"]:
            raise RuntimeError("NICo 启动接口缺少有效 ID。")
        previous = task.get("boot_interface_selection")
        if previous:
            raise RuntimeError("此前主启动口选择尚未生效；先核对 NICo 现场，不自动重放。")
        task["boot_interface_selection"] = {"request": request, "status": "requesting", "mac": mac}
        self.event(task, "prepare", "应用已确认的主启动网卡到 NICo；不修改 BMC 地址或下发 ISO。")
        self.adapter.rpc("SetPrimaryInterface", request)
        readback = self.adapter.rpc("FindInterfaces", {}).get("interfaces", [])
        if (
            len(
                [
                    n
                    for n in readback
                    if value_id(n.get("id")) == request["interface_id"]["value"]
                    and n.get("machineId", {}).get("id") == machine["id"]
                    and n.get("primaryInterface")
                    and not n.get("isBmc")
                ]
            )
            != 1
        ):
            raise RuntimeError("NICo 主启动口选择尚未读回确认；保留原任务，不重复请求。")
        task["boot_interface_selection"]["status"] = "verified"
        self.event(task, "prepare", "NICo 已确认主启动网卡；等待启动配置收敛后继续安装。")
        return True

    def bootstrap_first(self, task, folder):
        """Prepare one approved device, then use the strict Ready preflight.

        An ingestion request of unknown outcome is never replayed.  Preparation
        failures retain the device reservation and can be explicitly continued.
        """
        from pxeye.services.onboarding import Onboarding, discovery_info, preparation_message
        from pxeye.common import digest

        onboarding = Onboarding(self.adapter, self.store)
        task["status"] = "running"
        self.event(task, "prepare", "核对已确认规划、BMC 身份和启动网络，准备设备。")
        fresh = onboarding.deferred_preflight(
            task["device"],
            task["hostname"],
            task["profile"],
            task.get("disk_serial"),
            task_id=task["id"],
        )
        if (
            fresh["installation_plan"] != task["installation_plan"]
            or fresh["snapshot"] != task["preflight"]["snapshot"]
        ):
            raise RuntimeError("规划或安装模板已变化；请核对设备规划后在原任务继续准备。")
        from pxeye.domain.workflow import authorize_impact

        grant = task.get("impact_authorization") or {}
        impact = authorize_impact(fresh, self.adapter.config, grant.get("cleanup_scope"))
        if grant.get("policy_revision") != impact["policy_revision"]:
            raise RuntimeError("站点接入策略已变化，需重新核对清理范围；未放行接入。")
        row = onboarding.inventory_row(task["device"])
        onboarding.check_preparation(row)
        observed = onboarding.observed([row])[task["device"]]
        onboarding.check_scout_boot_guard(row, observed["machine"])
        previous = onboarding.admission(row["id"])
        # Accepted admission may already have rotated the BMC credentials.
        probe, _ = onboarding.probe(
            row, managed=bool(observed["machine"] or previous and previous["status"] == "accepted")
        )
        if observed["instances"] or str((observed["machine"] or {}).get("state", "")).startswith(
            "Assigned"
        ):
            raise RuntimeError("设备已有 Instance；本次首次安装停止，请核对关联。")
        if not observed["machine"]:
            endpoint = {"ip_address": probe["bmc_ip"], "mac_address": row["bmc_mac_address"]}
            gate = self.adapter.rpc("DetermineMachineIngestionState", endpoint).get(
                "machineIngestionState"
            )
            if previous and previous["status"] != "accepted":
                raise RuntimeError("此前接入请求结果待核对；不会重复发送开机或接入请求。")
            if gate == "WaitingForIngestion" and not previous:
                self.event(
                    task,
                    "prepare",
                    "按所选设备 SN/BMC MAC 放行一次 NICo 接入，等待 Machine 和 Scout。",
                )
                onboarding.admit(
                    {
                        "serial": task["device"],
                        "revision": digest(row),
                        "confirm_serial": task["device"],
                        "confirm_ingestion": True,
                    },
                    task.get("actor", "nico-ui"),
                    task_id=task["id"],
                )
            elif (
                gate not in ("IngestionMachineNotCreated", "IngestionMachineCreated")
                and not previous
            ):
                raise RuntimeError("BMC 尚未进入 NICo 发现；请检查 BMC 网络和 Site Explorer。")
        deadline = time.monotonic() + self.adapter.config.get("discovery_timeout_seconds", 900)
        task["preparation_deadline"] = time.time() + self.adapter.config.get(
            "discovery_timeout_seconds", 900
        )
        last_progress = None
        next_guard_check = time.monotonic() + 30
        while time.monotonic() < deadline:
            observed = onboarding.observed([row])[task["device"]]
            machine = observed["machine"] or {}
            if observed["instances"] or str(machine.get("state", "")).startswith("Assigned"):
                raise RuntimeError("准备期间设备已被分配 Instance，停止首次安装。")
            info = discovery_info(machine)
            serials = {
                info.get("dmi_data", {}).get("product_serial"),
                info.get("dmi_data", {}).get("chassis_serial"),
            }
            if any(serials) and task["device"] not in serials:
                raise RuntimeError("Scout 主机序列号与设备清单不匹配，停止执行。")
            if time.monotonic() >= next_guard_check or observed["first_install_ready"]:
                onboarding.check_scout_boot_guard(row, machine)
                next_guard_check = time.monotonic() + 30
            progress = {
                "machine_id": machine.get("id"),
                "state": machine.get("state"),
                "scout_received": bool(info),
                "failure_details": observed.get("failure_details"),
            }
            if progress != last_progress:
                task["preparation_observation"] = progress
                self.event(task, "prepare", preparation_message(progress), observation=progress)
                last_progress = progress
            if str(machine.get("state", "")).startswith("Failed") or observed.get(
                "failure_details"
            ):
                raise RuntimeError(
                    "NICo 设备准备失败："
                    + str(machine.get("state"))
                    + "；请查看 NICo 失败详情，修复后继续原任务。"
                )
            if observed["first_install_ready"]:
                if self.select_install_boot_interface(task, onboarding, row, machine):
                    time.sleep(2)
                    continue
                selected = task.get("disk_serial")
                fresh = onboarding.preflight(
                    task["device"], task["hostname"], task["profile"], selected
                )
                if not fresh["passed"]:
                    raise RuntimeError(
                        "执行前检查失败："
                        + "；".join(c["detail"] for c in fresh["checks"] if not c["passed"])
                    )
                selected = fresh["disk_serial"]
                device = fresh["execution_device"]
                device["instance_id"] = str(uuid.uuid4())
                task.update(
                    deferred_bootstrap=False,
                    disk_serial=selected,
                    execution_device=device,
                    instance_id=device["instance_id"],
                    management_ip=device["management_ip"],
                    installation_plan=fresh["installation_plan"],
                    preflight=fresh,
                )
                self.event(task, "prepare", "设备 Ready，身份、网口和目标盘已核对，开始安装系统。")
                return
            time.sleep(5)
        state = (last_progress or {}).get("state") or "尚未创建 Machine"
        raise TimeoutError(
            "设备准备超时："
            + state
            + "。"
            + preparation_message(last_progress or {})
            + " 请查看任务技术日志；修复后在原任务继续准备。"
        )

    @frozen_plan
    def can_resume(self, task):
        if (
            task.get("native_reinstall_requests") != 1
            and task.get("native_allocation_requests") != 1
        ):
            return False

        try:
            folder = self.adapter.data / "tasks" / task["id"]
            device = self.task_device(task)
            self.observe_installation(task, device, folder / "known_hosts", save=False)
            parts = (folder / "known_hosts").read_text().split()
            if parts[0] != device["management_ip"] or parts[1] != "ssh-ed25519":
                return False
            text = self.attempt_text(task)
            key = " ".join(parts[1:3])
            if not (
                verified_installation_identity(text, task, key)
                or self.identity_candidate(task, text, key)
            ):
                return False
            if task.get("normal_reboot_requested") and not task.get("initial"):
                return False
            return True
        except Exception:
            return False

    def start_first(self, task, device, folder):
        from pxeye.services.onboarding import Onboarding

        onboarding = Onboarding(self.adapter, self.store)
        self.event(task, "preflight", "首次安装重新核对 Ready、无 Instance、BMC、Scout 与系统盘。")
        fresh = onboarding.preflight(
            task["device"], task["hostname"], device["profile"], device["disk_serial"]
        )
        old_snapshot = task.get("preflight", {}).get("snapshot", {})
        if (
            not fresh["passed"]
            or fresh["installation_plan"] != task["installation_plan"]
            or fresh["snapshot"].get("baseline_sha256") != old_snapshot.get("baseline_sha256")
        ):
            raise RuntimeError("首次安装预检已变化或不再通过，停止分配。")
        from pxeye.services.device_plans import DevicePlans

        DevicePlans(self.adapter, onboarding.resources).synchronize(task["device"], "hardware")
        self.verify_materials(task)
        plan, _, _ = onboarding.plan(task["device"], device["profile"], device["disk_serial"])
        if plan != task["installation_plan"]:
            raise RuntimeError("材料校验期间设备或网络变化，停止分配。")
        config = self.adapter.render(device, task)
        task["user_data_sha256"] = sha(config["user_data"])
        (folder / "rendered-os.json").write_text(json.dumps(config))
        console = Console(self.adapter, device, folder)
        try:
            console.attach()
            for _ in range(5):
                console.poll()
            if "SOL Session operational" not in console.text and not self.adapter.config.get(
                "installer_events_url"
            ):
                raise RuntimeError("未建立认证 BMC SOL，停止首次安装。")
            plan, _, _ = onboarding.plan(task["device"], device["profile"], device["disk_serial"])
            if plan != task["installation_plan"]:
                raise RuntimeError("分配前设备或网络变化。")
            task["address_assignment_requested"] = True
            self.event(task, "network", "首次安装：同步该主机固定地址，失败保留现场。")
            task["address_assignment"] = self.adapter.assign_install_address(plan)
            profile = onboarding.profile(device["profile"])
            allocation = dict(profile["allocation"])
            allocation["tenant"] = dict(allocation["tenant"], hostname=task["hostname"])
            os_config = dict(config)
            variant = os_config.pop("variant", None)
            if variant:
                if set(variant) != {"OperatingSystemId"}:
                    raise RuntimeError("首次安装方案需要 NICo OS 库引用。")
                os_config["operating_system_id"] = {"value": variant["OperatingSystemId"]}
            allocation["os"] = os_config
            request = {
                "machine_id": {"id": device["machine_id"]},
                "instance_id": {"value": device["instance_id"]},
                "config": allocation,
                "allow_unhealthy_machine": False,
                "metadata": {
                    "name": task["hostname"],
                    "description": "NICo UI first OS installation",
                    "labels": [{"key": "nico-ui-task", "value": task["id"]}],
                },
            }
            (folder / "allocation-request.json").write_text(json.dumps(request))
            task["allocation_requested"] = True
            self.event(
                task,
                "allocate",
                "为指定 Machine 创建唯一新 Instance，触发首次网络安装；请求不自动重放。",
            )
            response = self.adapter.rpc("AllocateInstance", request)
            if response.get("id", {}).get("value") != device["instance_id"]:
                raise RuntimeError("首次分配回执的 Instance ID 不匹配。")
            task["native_allocation_requests"] = 1
            instance = self.adapter.instance(device)
            if (
                instance.get("machine_id") != device["machine_id"]
                or sha(instance["config"]["os"]["user_data"]) != task["user_data_sha256"]
            ):
                raise RuntimeError("新 Instance 的 Machine 关联或 OS 配置摘要不匹配。")
            task["config_version"] = instance["config_version"]
            self.event(task, "boot", "NICo 已接受首次安装分配，等待该主机网络引导。")
            return console
        except Exception:
            console.detach()
            raise

    @frozen_plan
    def resume(self, task):
        """Explicit UI continuation only: no update-os, PXE, Release or reinstall."""
        console = None
        try:
            if not self.can_resume(task):
                raise RuntimeError("缺少本轮安装退出和可信 SSH 证据，不能继续验收。")
            device = self.task_device(task)
            folder = self.adapter.data / "tasks" / task["id"]
            known = folder / "known_hosts"
            trusted_key = " ".join(known.read_text().split()[1:3])
            self.check_bound(device, task)
            task["status"] = "running"
            task["resume_available"] = False
            self.event(
                task, "firstboot", "UI 已确认仅继续本轮首启与普通重启验收；不重复安装或发送 PXE。"
            )
            console = Console(self.adapter, device, folder)
            console.attach()
            began = time.monotonic()
            deadline = began + 600
            initial = task.get("initial") if task.get("normal_reboot_requested") else None
            recovered = bool(task.get("disk_exit_recovery_requested"))
            while initial is None and time.monotonic() < deadline:
                self.observe_installation(task, device, known)
                for _ in range(6):
                    console.poll()
                try:
                    result = self.accept(device, task, trusted_key, known)
                except Exception as error:
                    result = {"passed": False, "error": str(error)}
                if result["passed"]:
                    initial = result["report"]
                    self.record_disk_evidence(task, initial, self.attempt_text(task), trusted_key)
                    break
                if task.get("last_acceptance_error") != result["error"]:
                    task["last_acceptance_error"] = result["error"]
                    self.event(task, "firstboot", "首启验收等待：" + result["error"])
                if (
                    not recovered
                    and time.monotonic() - began
                    > self.adapter.config.get("boot_handoff_grace_seconds", 300)
                    and self.installation_exited(task, self.attempt_text(task), trusted_key)
                ):
                    system = self.observe_boot_system(task, device)
                    if system and in_uefi(system) and not self.ssh_open(device):
                        recovered = self.recover_disk_boot(task, device, system)
                        if recovered:
                            # The initial deadline includes the natural-boot
                            # grace period.  Once the single recovery reboot is
                            # accepted, give the target OS its own bounded boot
                            # and cloud-init convergence window.
                            deadline = max(deadline, time.monotonic() + 600)
            if initial is None:
                raise TimeoutError("继续首启验收超时；保留任务与现场。")
            (folder / "initial.json").write_text(json.dumps(initial, indent=2))
            task["initial"] = initial
            self.event(task, "reboot", "新系统独立验收通过，执行普通重启复验。")
            self.finish(
                task,
                device,
                console,
                folder,
                known,
                trusted_key,
                initial,
                sum(bool(e.get("recovery")) for e in task.get("events", [])),
            )
        except Exception as error:
            task["status"] = "needs_attention"
            task["error"] = str(error)
            task["resume_available"] = self.can_resume(task)
            task["prepare_available"] = self.can_prepare(task)
            self.event(task, task.get("stage", "firstboot"), "继续验收需要处理：" + str(error))
        finally:
            if console:
                console.detach()

    def finish(self, task, device, console, folder, known, trusted_key, initial, recovery_count):
        reboot_script = """import subprocess
subprocess.run(['systemctl','reboot','--no-block'],check=True)
print('NORMAL_REBOOT_REQUESTED')
"""
        self.check_bound(device, task)
        task["last_acceptance_error"] = None
        task["initial"] = initial
        if not task.get("normal_reboot_requested"):
            task["normal_reboot_requested"] = True
            task["normal_reboot_state"] = "requesting"
            self.store.save(task)
            self.adapter.ssh(device, reboot_script, known=known)
            task["normal_reboot_state"] = "accepted"
            self.store.save(task)
        after = None
        reboot_deadline = time.monotonic() + 480
        while time.monotonic() < reboot_deadline:
            for _ in range(6):
                console.poll()
            try:
                result = self.accept(device, task, trusted_key, known, initial=initial)
            except Exception:
                continue
            if result["passed"]:
                after = result["report"]
                break
        if after is None:
            raise TimeoutError("普通重启复验未通过；不标记完成。")
        self.check_bound(device, task)
        system = self.adapter.redfish(device)
        if system.get("Boot", {}).get("BootSourceOverrideEnabled") != "Disabled":
            raise RuntimeError("最终 BMC 启动覆盖仍未禁用。")
        (folder / "after-reboot.json").write_text(json.dumps(after, indent=2))
        task["after_reboot"] = after
        task["warnings"] = after.get("warnings", [])
        task["recovery_count"] = recovery_count
        task["completed_at"] = time.time()
        task["status"] = "completed"
        task["resume_available"] = False
        task["last_acceptance_error"] = None
        task["receipt"] = {
            "schema_version": 1,
            "source": "nico-ui",
            "task_id": task["id"],
            "serial": device["serial"],
            "hostname": task["hostname"],
            "installation_mode": task.get("mode", "reinstall"),
            "disk_serial": device.get("disk_serial"),
            "instance_id": device["instance_id"],
            "config_version": task["config_version"],
            "user_data_sha256": task["user_data_sha256"],
            "initial": initial,
            "after_reboot": after,
            "recovery_count": task["recovery_count"],
            "normal_reboot": True,
            "everyboot": False,
            "installation_attempts": 1 + task.get("native_retry_requests", 0),
            "installation_retries": task.get("installation_retries", []),
            "console_identity_recovery": task.get("console_identity_recovery"),
            "installation_evidence": task.get("installation_evidence"),
            "bmc_override": "Disabled",
            "unattended_standard_boot_certified": False,
        }
        (folder / "receipt.json").write_text(json.dumps(task["receipt"], indent=2))
        (self.adapter.identity / (device["serial"] + ".known_hosts")).write_text(known.read_text())
        (self.adapter.identity / (device["serial"] + ".known_hosts")).chmod(0o600)
        self.adapter.remember_connection(device, task)
        self.event(
            task,
            "completed",
            "安装、目标系统盘启动及普通重启验收通过。"
            + ("环境服务有告警，请查看验收详情。" if task.get("warnings") else ""),
        )

    def record_disk_evidence(self, task, report, text, trusted_key):
        if verified_installation_identity(text, task, trusted_key):
            return
        if not self.identity_candidate(task, text, trusted_key):
            raise RuntimeError("缺少本轮可信身份，停止磁盘安装结果验收。")
        self.check_bound(self.task_device(task), task)
        task["installation_evidence"] = {
            "source": "trusted-ssh-target-disk",
            "task_id": task["id"],
            "serial": task["device"],
            "config_version": task["config_version"],
            "checked_at": report["checked_at"],
            "installer_log_sha256": report["installer_log_sha256"],
            "hostkey_fingerprint": report["hostkey_fingerprint"],
            "root_uuid": report["root_uuid"],
        }
        self.event(
            task,
            "firstboot",
            "串口结束日志不完整；已通过本轮可信 SSH、目标盘安装成功日志、任务回执及完整验收确认安装结果。",
        )

    def task_device(self, task):
        if task.get("execution_device"):
            device = dict(task["execution_device"])
            plan = task.get("installation_plan") or {}
            device.update(
                {k: plan[k] for k in ("management_ip", "prefixlen", "gateway") if k in plan}
            )
            return device
        # Historic tasks keep their submitted address when the inventory changes.
        device = dict(self.adapter.device(task["device"]))
        if task.get("management_ip"):
            device["management_ip"] = task["management_ip"]
        return device

    def check_bound(self, device, task):
        instance = self.adapter.instance(device)
        os_config = instance["config"]["os"]
        if (
            sha(os_config["user_data"]) != task["user_data_sha256"]
            or os_config.get("run_provisioning_instructions_on_every_boot")
            or instance.get("config_version") != task.get("config_version")
            or instance.get("machine_id") != device.get("machine_id")
        ):
            raise RuntimeError("执行中 Instance 配置发生变化，停止自动操作。")
        if self.adapter.redfish(device).get("SerialNumber") != device["serial"]:
            raise RuntimeError("执行中 BMC 身份变化。")

    def verify_materials(self, task):
        self.event(task, "materials", "完整读取安装材料并核对固定 SHA256。")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        reports = []
        for material in self.task_device(task).get("materials", self.adapter.config["materials"]):
            digest, size = hashlib.sha256(), 0
            start = time.monotonic()
            with opener.open(
                material.get("verification_url", material["url"]), timeout=25
            ) as response:
                while True:
                    block = response.read(4 * 1024 * 1024)
                    if not block:
                        break
                    digest.update(block)
                    size += len(block)
                    if time.monotonic() - start > 240:
                        raise TimeoutError("完整材料校验超时。")
            if size != material["size"] or digest.hexdigest() != material["sha256"]:
                raise RuntimeError("材料完整摘要不匹配：" + material["name"])
            reports.append({"name": material["name"], "size": size, "sha256": digest.hexdigest()})
        task["material_verification"] = reports
        self.event(task, "materials", "ISO、kernel 和 initrd 完整摘要均匹配。")

    def accept(self, device, task, trusted_key, known, initial=None):
        if device.get("login_mode") == "password":
            self.adapter.verify_password_login(device, known)
        context = {"device": device, "task": task, "trusted_key": trusted_key, "initial": initial}
        # repr produces a Python string literal; this is transmitted as stdin, never through a shell interpolation.
        script = (
            Path(__file__).with_name("disk_identity.py").read_text()
            + "\nCTX = "
            + repr(context)
            + "\n"
            + Path(__file__).with_name("accept_host.py").read_text()
        )
        result = json.loads(self.adapter.ssh(device, script, known=known, timeout=100))
        result = validate_config(result, device, task)
        if (
            result.get("passed")
            and not result["report"]["checks"]["services"]
            and self.adapter.config.get("service_connectivity_required", False)
        ):
            failures = [
                check["name"] + "未通过"
                for check in result["report"]["service_checks"]
                if not check["passed"]
            ]
            return {
                "passed": False,
                "error": "环境服务检查未通过：" + "；".join(failures),
                "report": result["report"],
                "category": "service_connectivity",
            }
        return result

    @staticmethod
    def ssh_open(device):
        try:
            with socket.create_connection((device["management_ip"], 22), timeout=2):
                return True
        except OSError:
            return False
