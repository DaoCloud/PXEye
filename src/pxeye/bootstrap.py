"""Same-origin console with authenticated, persistent reinstall tasks."""

import fcntl
import json
import os
import socket
import ssl
import time
from pathlib import Path
from urllib.parse import urlsplit

from pxeye.services.execution import Adapter
from pxeye.installation.executor import Executor
from pxeye.services.tasks import TaskCoordinator
from pxeye.persistence.store import get_store
from pxeye.services.resources import Resources
from pxeye.common import atomic_json
from pxeye.services.onboarding import Onboarding
from pxeye.services.os_library import OSLibrary
from pxeye.services.discovery import Discovery
from pxeye.services.device_config import DeviceConfig
from pxeye.services.bmc_addresses import BMCAddresses
from pxeye.services.profiles import InstallProfiles
from pxeye.services.instances import Instances
from pxeye.services.current_systems import CurrentSystems
from pxeye.services.equipment import Equipment
from pxeye.services.addresses import ManagementAddresses


class Application:
    def __init__(self, config, secret_dir, data_dir, static_dir):
        self.config = config
        self.adapter = Adapter(config, secret_dir, data_dir)
        self.store = get_store(Path(data_dir) / "console.sqlite3")
        self.executor = Executor(self.adapter, self.store)
        self.resources = Resources(self.adapter, self.store) if config.get("core_url") else None
        self.instances = (
            Instances(self.adapter, self.resources, self.store) if self.resources else None
        )
        self.onboarding = (
            Onboarding(self.adapter, self.store, self.resources) if self.resources else None
        )
        self.os_library = (
            OSLibrary(self.adapter, recover=True, store=self.store) if self.resources else None
        )
        self.discovery = (
            Discovery(self.adapter, self.resources, self.onboarding) if self.resources else None
        )
        self.device_config = DeviceConfig(self.adapter, self.resources) if self.resources else None
        self.bmc_addresses = BMCAddresses(self.adapter, self.resources) if self.resources else None
        self.equipment = Equipment(self.adapter, self.resources) if self.resources else None
        self.management_addresses = (
            ManagementAddresses(self.adapter, self.resources, self.equipment)
            if self.resources
            else None
        )
        self.profiles = InstallProfiles(self.adapter, self.store) if self.resources else None
        self.current_systems = (
            CurrentSystems(self.adapter, self.resources, self.store) if self.resources else None
        )
        self.adapter.resources = self.resources
        self.adapter.device_config = self.device_config
        self.adapter.profiles = self.profiles
        self.static = Path(static_dir)
        self.auth = json.loads((Path(secret_dir) / "auth.json").read_text())
        self.failures = {}
        self.lockfile = (Path(data_dir) / "executor.lock").open("w")
        fcntl.flock(self.lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if self.resources:
            self.resources.recover_network_operations()
            self.profiles.import_legacy()
            try:
                self.resources.refresh_inventory()
            except (RuntimeError, OSError):
                # Preserve saved plans while Core is unavailable; refresh is explicit in the UI.
                pass
        self.coordinator = TaskCoordinator(
            config=config,
            adapter=self.adapter,
            store=self.store,
            executor=self.executor,
            resources=self.resources,
            onboarding=self.onboarding,
            device_config=self.device_config,
            os_library=self.os_library,
        )
        self.coordinator.recover()

    @property
    def worker_lock(self):
        return self.coordinator.worker_lock

    def site_information(self):
        def certificate():
            try:
                row = ssl._ssl._test_decode_cert(str(self.adapter.secrets / "client.crt"))
                label = lambda value: ", ".join("=".join(item) for group in value for item in group)
                return {
                    "subject": label(row.get("subject", ())),
                    "issuer": label(row.get("issuer", ())),
                    "valid_from": row.get("notBefore"),
                    "valid_until": row.get("notAfter"),
                }
            except (OSError, ValueError, ssl.SSLError):
                return {"error": "客户端证书无法读取"}

        def storage(path, role):
            result = {"path": path, "role": role}
            try:
                stat = os.statvfs(path)
                result.update(
                    total_bytes=stat.f_blocks * stat.f_frsize,
                    available_bytes=stat.f_bavail * stat.f_frsize,
                    available=True,
                )
            except OSError:
                result["available"] = False
            return result

        def probe(row):
            result = {k: v for k, v in row.items() if k != "probe"}
            target = row.get("probe") or {}
            if target.get("type") != "tcp":
                return result | {
                    "state": "configured",
                    "detail": "端点已配置；未执行协议级健康检查",
                }
            started = time.monotonic()
            try:
                with socket.create_connection((target["host"], int(target["port"])), timeout=1.5):
                    pass
                return result | {
                    "state": "reachable",
                    "detail": "TCP 可达",
                    "latency_ms": round((time.monotonic() - started) * 1000),
                }
            except (OSError, ValueError, KeyError):
                return result | {"state": "unreachable", "detail": "端点当前不可达"}

        core = urlsplit(self.config["core_url"])
        configured_components = self.config.get("site_components") or [
            {
                "id": "core",
                "name": "NICo Core",
                "endpoint": self.config["core_url"],
                "role": "资源、状态与装机编排 API",
                "probe": {"type": "tcp", "host": core.hostname, "port": core.port or 443},
            }
        ]
        components = [probe(row) for row in configured_components]
        return {
            "site": self.config["site"],
            "core_url": self.config["core_url"],
            "identity": certificate(),
            "storage": [
                storage("/data", "任务、规划和安装历史"),
                storage(
                    self.config.get("os_library", {}).get("directory", "/materials"), "OS 启动材料"
                ),
                storage(
                    next(
                        (
                            s.get("directory")
                            for s in self.config.get("os_library", {}).get("sources", [])
                            if s.get("directory")
                        ),
                        "/iso-sources",
                    ),
                    "ISO 来源（只读）",
                ),
            ],
            "components": components,
            "checked_at": time.time(),
            "dns_maintenance": {
                "page": "network",
                "detail": "OS DNS 在网络管理的 HostInband 子网中维护",
            },
        }

    def save_site(self, body):
        if set(body) != {"name", "core_url"}:
            raise ValueError("站点设置字段无效。")
        name, core_url = str(body["name"]).strip(), str(body["core_url"]).strip()
        if not 1 <= len(name) <= 100:
            raise ValueError("站点名称长度应为 1–100 个字符。")
        parsed = urlsplit(core_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Core 地址必须是完整的 HTTPS 服务地址。")
        if core_url != self.config["core_url"]:
            if self.store.incomplete():
                raise ValueError("存在执行中或待处理的安装任务，暂不能切换 Core。")
            proposed = dict(self.config, core_url=core_url)
            candidate = Adapter(proposed, self.adapter.secrets, self.adapter.data)
            try:
                candidate.rpc("FindNetworkSegmentIds", {})
            except Exception:
                raise ValueError("无法使用当前 mTLS 身份读取新的 Core，未应用修改。") from None
        atomic_json(
            self.adapter.data / "config" / "site-settings.json",
            {"name": name, "core_url": core_url},
        )
        self.config["site"]["name"] = name
        self.config["core_url"] = core_url
        return {"status": "saved", "detail": "站点设置已应用。", "site": self.site_information()}

    def task_view(self, task):
        return self.coordinator.task_view(task)

    def start_recovered(self, task_ids):
        return self.coordinator.start_recovered(task_ids)

    @staticmethod
    def installation_mode(observed):
        return TaskCoordinator.installation_mode(observed)

    @staticmethod
    def allocation_observation(observed):
        return TaskCoordinator.allocation_observation(observed)

    def batch_preflight(self, body, owner):
        return self.coordinator.batch_preflight(body, owner)

    def submit_batch(self, body, owner, actor):
        return self.coordinator.submit_batch(body, owner, actor)

    def start_queue(self):
        return self.coordinator.start_queue()

    def os_lock(self):
        return self.coordinator.os_lock()

    def plan(self, action):
        return self.coordinator.plan(action)

    def configure(self, action):
        return self.coordinator.configure(action)

    def apply_network(self, sid):
        return self.coordinator.apply_network(sid)

    def submit(self, body, actor):
        return self.coordinator.submit(body, actor)

    def ensure_executable(self, serial):
        return self.coordinator.ensure_executable(serial)

    def preparation_preflight(self, task_id, owner):
        return self.coordinator.preparation_preflight(task_id, owner)

    def continue_preparation(self, task_id, body, owner, actor):
        return self.coordinator.continue_preparation(task_id, body, owner, actor)

    def restart_preflight(self, task_id, owner):
        return self.coordinator.restart_preflight(task_id, owner)

    def restart_install(self, task_id, body, owner, actor):
        return self.coordinator.restart_install(task_id, body, owner, actor)

    def retry_install_preflight(self, task_id, owner):
        return self.coordinator.retry_install_preflight(task_id, owner)

    def retry_install(self, task_id, body, owner, actor):
        return self.coordinator.retry_install(task_id, body, owner, actor)

    def resume(self, task_id, body, actor):
        return self.coordinator.resume(task_id, body, actor)
