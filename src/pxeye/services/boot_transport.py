"""Frozen external-DHCP intent; NICo Core owns every VirtualMedia/BMC write."""

import ipaddress
import json
import time
import uuid

from pxeye.services.boot_media import BootMedia


FIXED_LEASE_NOTICE = (
    "请在外部 DHCP 为设备规划中的启动 MAC 配置固定租约，保证 iPXE、Scout 和安装器阶段获得相同 IP。"
)


def site_boot_snapshot(adapter):
    """Absent settings preserve the existing Nico DHCP workflow."""
    path = adapter.data / "config" / "site-boot-network.json"
    if not path.exists():
        return {"dhcp_mode": "nico"}
    current = json.loads(path.read_text()).get("current") or {}
    values = current.get("values") or {}
    mode = values.get("dhcp_mode", "nico")
    if mode not in ("nico", "external"):
        raise ValueError("站点 DHCP 模式无效，请重新保存引导网络。")
    if mode == "external" and current.get("status") != "applied":
        raise ValueError("外部 DHCP 配置尚未应用成功；请先确认本站点 Kea 已停止。")
    return {
        "dhcp_mode": mode,
        "revision": current.get("revision"),
        "pxe_http_endpoint": values.get("pxe_http_endpoint", ""),
    }


def external_boot(task):
    # Old tasks were created with the native PXE contract, even if site mode changes.
    return (task.get("boot_network") or {}).get("dhcp_mode") == "external"


def status_value(status, key, default=None):
    pieces = key.split("_")
    camel = pieces[0] + "".join(piece.title() for piece in pieces[1:])
    return status.get(camel, status.get(key, default))


class BootTransport:
    """Publish immutable boot media and submit idempotent, typed Core intents."""

    def __init__(self, adapter, store, *, save=None):
        self.adapter, self.store = adapter, store
        self.save = save or store.save

    def row(self, serial):
        rows = [
            row
            for row in self.adapter.resources.planned_inventory()
            if row["chassis_serial_number"] == serial
        ]
        if len(rows) != 1:
            raise ValueError("外部引导需要唯一的 Expected Machine 设备规划。")
        return rows[0]

    @staticmethod
    def check_scope(profile, machine=None, *, row=None):
        """Keep the initial external transport limited to Flat x86 hosts."""
        status = (machine or {}).get("status") or {}
        dpus = status_value(status, "associated_dpu_machine_ids", [])
        if (
            profile.get("architecture") != "x86_64"
            or profile.get("network_mode") != "flat"
            or dpus
            or (row or {}).get("dpu_policy") in ("manage", 1)
        ):
            raise ValueError("外部 DHCP 引导首版仅支持 x86_64、无受管 DPU、Flat 网络。")

    @staticmethod
    def identity(row, device=None):
        hosts = [
            host
            for host in row.get("interfaces", [])
            if host.get("primary") and host.get("role", "host") in ("host", "unspecified", 0, 1)
        ]
        if len(hosts) != 1 or not hosts[0].get("mac_address") or not hosts[0].get("fixed_ip"):
            raise ValueError(FIXED_LEASE_NOTICE + " 请先完成主启动 MAC/IP 规划。")
        host = hosts[0]
        address = ipaddress.IPv4Address(host["fixed_ip"])
        if address.is_unspecified or address.is_multicast:
            raise ValueError("外部 DHCP 固定租约地址无效。")
        if device and (
            device.get("architecture") != "x86_64"
            or device.get("boot_mac", "").lower() != host["mac_address"].lower()
            or device.get("management_ip") != str(address)
        ):
            raise ValueError("外部 DHCP 首版仅支持 x86_64，且执行网卡/IP 必须与固定租约规划一致。")
        return {
            "expected_machine_id": {"value": row["id"]},
            "boot_mac_address": host["mac_address"].lower(),
            "fixed_ip_address": str(address),
        }

    def check(self, row, device=None):
        snapshot = site_boot_snapshot(self.adapter)
        if snapshot["dhcp_mode"] != "external":
            return snapshot
        identity = self.identity(row, device)
        try:
            self.adapter.rpc(
                "GetHostBootIntent", {"expected_machine_id": identity["expected_machine_id"]}
            )
        except RuntimeError as error:
            raise RuntimeError(
                "无法读取 Core HostBootIntent；外部 DHCP 需要配套的 Core 接口及有效连接。"
            ) from error
        return snapshot

    def check_os(self, device):
        """Immutable OS definitions must pass Core's per-attempt boot nonce to Linux."""
        baseline = self.adapter.baseline(device)
        variant = baseline.get("variant") or {}
        os_id = device.get("os_id") or variant.get("OperatingSystemId")
        if not os_id:
            raise ValueError("外部 DHCP 安装需要支持引导回执的 OS 库版本。")
        native = self.adapter.rpc("GetOperatingSystem", {"value": os_id})
        parameters = status_value(native, "ipxe_template_parameters", [])
        kernel = next(
            (p.get("value", "") for p in parameters if p.get("name") == "kernel_params"), ""
        )
        if not all(
            "host_boot_" + name + "=${host_boot_" + name + "}" in kernel
            for name in ("expected_machine_id", "generation", "token")
        ):
            raise ValueError(
                "该 OS 版本不含外部引导回执参数；请从 OS 库创建新版本，既有 OS 不修改。"
            )

    def prepare(self, task, purpose, *, device=None, row=None):
        if not external_boot(task):
            return None
        row = row or self.row(task["device"])
        identity = self.identity(row, device)
        if purpose == "INSTALLATION":
            self.check_os(device)
        attempt = (task.get("retry_attempt") or {}).get("number", 0)
        key = purpose + ":" + str(attempt)
        intents = task.setdefault("host_boot_intents", {})
        intent = intents.get(key)
        if not intent:
            media = (
                BootMedia(self.adapter).prepare(
                    task["boot_network"]["pxe_http_endpoint"],
                    boot_mac=identity["boot_mac_address"],
                )
                if purpose != "LOCAL_DISK"
                else None
            )
            request = identity | {
                "generation": str(uuid.uuid4()),
                "purpose": "HOST_BOOT_PURPOSE_" + purpose,
                "architecture": "X86",
            }
            if media:
                request.update(artifact_url=media["url"], artifact_sha256=media["sha256"])
            intent = {"request": request, "media": media, "state": "requesting"}
            intents[key] = intent
            task["active_host_boot_intent"] = key
            self.save(task)
        elif any(intent["request"].get(k) != v for k, v in identity.items()):
            raise RuntimeError("本轮引导意图的设备规划已改变；不能覆盖冻结的 MAC/IP。")
        # Set is idempotent for the identical generation and payload. It only declares
        # policy; the native lifecycle owns BIOS, mount, boot override and reset.
        status = self.adapter.rpc("SetHostBootIntent", intent["request"])
        if status_value(status, "generation") != intent["request"]["generation"]:
            raise RuntimeError("Core 返回的引导请求代次不一致。")
        intent["state"] = "accepted"
        task["active_host_boot_intent"] = key
        self._record(task, status)
        self.save(task)
        return status

    @staticmethod
    def _record(task, status):
        task["host_boot_status"] = {
            key: status_value(status, key)
            for key in (
                "generation",
                "purpose",
                "phase",
                "acknowledged",
                "cleanup_complete",
                "last_error",
                "owned_media_uri",
                "cancelled",
                "revision",
            )
        }

    def observe(self, task):
        if not external_boot(task) or not task.get("active_host_boot_intent"):
            return None
        intent = task["host_boot_intents"][task["active_host_boot_intent"]]
        status = self.adapter.rpc(
            "GetHostBootIntent", {"expected_machine_id": intent["request"]["expected_machine_id"]}
        )
        if status_value(status, "generation") != intent["request"]["generation"]:
            raise RuntimeError("Core 引导意图已被另一请求替换，停止本轮操作。")
        self._record(task, status)
        self.save(task)
        if status_value(status, "cancelled"):
            raise RuntimeError("Core 引导意图已取消。")
        if status_value(status, "phase") == "HOST_BOOT_PHASE_FAILED":
            raise RuntimeError(
                "Core 引导需要处理：" + (status_value(status, "last_error") or "请检查 Core 状态。")
            )
        return status

    def completion_status(self, task):
        """Read the current LOCAL_DISK cleanup fence without changing Core or storage."""
        key = task.get("active_host_boot_intent")
        request = (task.get("host_boot_intents", {}).get(key) or {}).get("request") or {}
        if (
            request.get("purpose") != "HOST_BOOT_PURPOSE_LOCAL_DISK"
            or not request.get("generation")
            or not request.get("expected_machine_id")
        ):
            raise ValueError("Core 尚未完成本轮本地盘引导交接；请继续原任务，不能跳过介质清理。")
        status = self.adapter.rpc(
            "GetHostBootIntent", {"expected_machine_id": request["expected_machine_id"]}
        )
        if status_value(status, "generation") != request["generation"]:
            raise ValueError("Core 引导意图已被另一请求替换；请先处理原任务。")
        if (
            status_value(status, "cancelled")
            or status_value(status, "phase") == "HOST_BOOT_PHASE_FAILED"
        ):
            raise ValueError("Core 本地盘交接未成功；请先处理原任务的引导状态。")
        if status_value(status, "purpose") != "HOST_BOOT_PURPOSE_LOCAL_DISK" or not status_value(
            status, "cleanup_complete"
        ):
            raise ValueError("Core 正在清理本轮引导介质并交接本地盘；完成后才能结束验收。")
        return status

    @staticmethod
    def _requests(record):
        return [
            intent["request"]
            for intent in record.get("host_boot_intents", {}).values()
            if intent.get("request", {}).get("generation")
            and intent["request"].get("expected_machine_id")
        ]

    def check_standalone_admissions(self):
        """Do not switch site networking under an outstanding standalone admission."""

        def ready(admission):
            machines = self.adapter.core(["machine", "show", "--hosts"], data=True)["machines"]
            matches = [
                machine
                for machine in machines
                if (machine.get("bmc") or machine.get("bmc_info") or {}).get("mac", "").lower()
                == admission.get("bmc_mac", "").lower()
                and admission.get("bmc_mac")
            ]
            return len(matches) == 1 and matches[0].get("state") in ("Ready", "Assigned/Ready")

        def blocked(admission):
            raise ValueError(
                "存在未完成的外部 DHCP 接管请求（"
                + admission["serial"]
                + "）；请等待主机 Ready，或明确取消并完成 Core 介质清理，再修改引导网络。"
            )

        for path in (self.adapter.data / "config" / "admissions").glob("*.json"):
            admission = json.loads(path.read_text())
            if not external_boot(admission):
                continue  # Task-backed admissions are guarded by Store.incomplete().
            requests = self._requests(admission)
            if not requests:
                if admission.get("ingestion_requested") and not ready(admission):
                    blocked(admission)
                continue  # No Core intent was submitted before this admission stopped.
            expected_ids = {json.dumps(r["expected_machine_id"], sort_keys=True) for r in requests}
            for expected in expected_ids:
                status = self.adapter.rpc(
                    "GetHostBootIntent", {"expected_machine_id": json.loads(expected)}
                )
                generation = status_value(status, "generation")
                if not generation:
                    if admission.get("ingestion_requested") and not ready(admission):
                        blocked(admission)
                    continue  # A released policy no longer owns media or boot control.
                if not any(
                    r["generation"] == generation
                    and r["expected_machine_id"] == json.loads(expected)
                    for r in requests
                ) or not status_value(status, "cleanup_complete"):
                    blocked(admission)
                # Scout may eject between HostInit/BIOS/cleanup boots. Ejection
                # alone does not mean native admission has finished needing media.
                if not status_value(status, "cancelled") and not ready(admission):
                    blocked(admission)

    def acknowledge(self, task, event):
        if not external_boot(task):
            return
        binding = event.get("host_boot") or {}
        intent = next(
            (
                item
                for item in task.get("host_boot_intents", {}).values()
                if item["request"]["generation"] == binding.get("generation")
                and item["request"]["purpose"] == "HOST_BOOT_PURPOSE_INSTALLATION"
            ),
            None,
        )
        if not intent or not binding:
            raise ValueError("安装器未返回本轮引导介质标识；请使用支持外部 DHCP 的 OS 版本。")
        request = intent["request"]
        if (
            binding.get("expected_machine_id") != request["expected_machine_id"]["value"]
            or binding.get("generation") != request["generation"]
        ):
            raise ValueError("安装器引导回执与本轮 Core 意图不一致。")
        active = task["host_boot_intents"].get(task.get("active_host_boot_intent"), {})
        if active.get("request", {}).get("purpose") == "HOST_BOOT_PURPOSE_LOCAL_DISK":
            # Handoff is only requested after this installation generation completed
            # media cleanup. Later signed installer events remain valid observations.
            return
        status = self.adapter.rpc(
            "AcknowledgeHostBoot",
            {
                "expected_machine_id": request["expected_machine_id"],
                "generation": request["generation"],
                "acknowledgement_token": binding.get("token", ""),
                "evidence": "HOST_BOOT_EVIDENCE_INSTALLER_INDEPENDENT",
                "machine_id": {"id": task["execution_device"]["machine_id"]},
            },
        )
        # Callback handlers never save a stale task snapshot over the running worker.
        # The worker reads Core status through observe().
        if not status_value(status, "acknowledged"):
            raise RuntimeError("Core 未确认安装器引导回执。")

    def handoff(self, task, device):
        status = self.observe(task)
        if not status or not status_value(status, "cleanup_complete"):
            return False
        if status_value(status, "purpose") != "HOST_BOOT_PURPOSE_LOCAL_DISK":
            status = self.prepare(task, "LOCAL_DISK", device=device)
        return status_value(status, "purpose") == "HOST_BOOT_PURPOSE_LOCAL_DISK" and status_value(
            status, "cleanup_complete"
        )

    def wait_for_handoff(self, task, device, *, timeout=75):
        """Allow Core's asynchronous eject/boot cleanup to settle in the write worker."""
        deadline = time.monotonic() + timeout
        while True:
            if self.handoff(task, device):
                return self.completion_status(task)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Core 尚未完成介质清理与本地盘交接；请稍后在原任务继续验收。")
            time.sleep(min(2, remaining))

    def cancel(self, task):
        if not external_boot(task) or not task.get("active_host_boot_intent"):
            return
        intent = task["host_boot_intents"][task["active_host_boot_intent"]]
        request = intent["request"]
        status = self.adapter.rpc(
            "GetHostBootIntent", {"expected_machine_id": request["expected_machine_id"]}
        )
        generation = status_value(status, "generation")
        if not generation:
            return  # A failed declaration never created a Core policy.
        if generation != request["generation"]:
            raise ValueError("Core 引导意图已被另一请求替换；不能取消其他代次。")
        status = self.adapter.rpc(
            "CancelHostBoot",
            {
                "expected_machine_id": request["expected_machine_id"],
                "generation": request["generation"],
            },
        )
        if status_value(status, "generation") != request["generation"]:
            raise ValueError("Core 取消结果的引导代次不一致；请先核对原请求。")
        if not status_value(status, "cleanup_complete"):
            raise ValueError("Core 已收到取消请求，正在清理本轮介质；读回完成后再关闭任务。")

    def check_readmission(self, admission, row):
        """Authorize a new admission only after the old external request is safe."""
        expected_id = {"value": row["id"]}
        status = self.adapter.rpc("GetHostBootIntent", {"expected_machine_id": expected_id})
        generation = status_value(status, "generation")
        if not generation:
            return  # The former policy was explicitly released or never created.
        if (
            not any(
                r["expected_machine_id"] == expected_id and r["generation"] == generation
                for r in self._requests(admission)
            )
            or not status_value(status, "cancelled")
            or not status_value(status, "cleanup_complete")
        ):
            raise ValueError("旧外部接管请求尚未明确取消并完成同代介质清理；不能重新接管。")

    def release_for_native(self, task):
        """Explicitly leave a previous external policy after the site's mode switch."""
        if external_boot(task):
            return
        with self.store.db() as db:
            previous = [
                json.loads(row["data"])
                for row in db.execute(
                    "SELECT data FROM tasks WHERE device=? ORDER BY created DESC", (task["device"],)
                )
            ]
        for path in (self.adapter.data / "config" / "admissions").glob("*.json"):
            admission = json.loads(path.read_text())
            if admission.get("serial") == task["device"]:
                previous.append(admission)
        requests = [request for record in previous for request in self._requests(record)]
        expected_ids = {json.dumps(r["expected_machine_id"], sort_keys=True) for r in requests}
        releasable = []
        for expected in expected_ids:
            expected_id = json.loads(expected)
            status = self.adapter.rpc("GetHostBootIntent", {"expected_machine_id": expected_id})
            generation = status_value(status, "generation")
            if not generation:
                continue
            if not any(
                r["expected_machine_id"] == expected_id and r["generation"] == generation
                for r in requests
            ):
                raise ValueError(
                    "Core 引导意图已被另一请求替换；请先处理原请求，不能释放其他代次。"
                )
            if not status_value(status, "cleanup_complete"):
                raise ValueError(
                    "该设备的外部引导介质尚未清理；请先处理原任务，不能切换回 Nico DHCP。"
                )
            releasable.append({"expected_machine_id": expected_id, "generation": generation})
        if len(releasable) > 1:
            raise ValueError("同一序列号存在多个 Core 引导策略；请先核对设备规划与原请求。")
        if not releasable:
            return
        self.adapter.rpc(
            "ReleaseHostBootPolicy",
            releasable[0],
        )
