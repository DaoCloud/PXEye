"""Same-origin console with authenticated, persistent reinstall tasks."""

import fcntl
import base64
import copy
import json
import os
import socket
import ssl
import time
import threading
import uuid
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
from pxeye.deployment.service import NicoDeployment
from pxeye.clients.process import run
from pxeye.common import atomic_text


class Application:
    def __init__(self, config, secret_dir, data_dir, static_dir):
        self.config = config
        config.setdefault("core_url", "")
        config.setdefault(
            "site", {"name": "PXEye", "namespace": "mmzhou", "deployment": "mmzhou-pxeye"}
        )
        for key, default in (
            ("devices", []),
            ("materials", []),
            ("network", {}),
            ("first_install_profiles", []),
        ):
            config.setdefault(key, default)
        self.connection_lock = threading.RLock()
        self.adapter = Adapter(config, secret_dir, data_dir)
        self.store = get_store(Path(data_dir) / "console.sqlite3")
        self.executor = Executor(self.adapter, self.store)
        self._bind_core_services()
        self.static = Path(static_dir)
        self.auth = json.loads((Path(secret_dir) / "auth.json").read_text())
        self.failures = {}
        self.lockfile = (Path(data_dir) / "executor.lock").open("w")
        fcntl.flock(self.lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self._create_coordinator()
        if self.resources:
            self.resources.recover_network_operations()
            self.profiles.import_legacy()
            self.coordinator.recover()
            # Core inventory can take a minute when unavailable; never block the HTTP listener.
            threading.Thread(target=self._refresh_inventory, daemon=True).start()
        self.nico_deployment = NicoDeployment(self)
        if config.get("core_identity_source"):
            threading.Thread(target=self._maintain_core_identity, daemon=True).start()

    def _bind_core_services(self):
        config = self.config
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

    def _create_coordinator(self):
        self.coordinator = TaskCoordinator(
            config=self.config,
            adapter=self.adapter,
            store=self.store,
            executor=self.executor,
            resources=self.resources,
            onboarding=self.onboarding,
            device_config=self.device_config,
            os_library=self.os_library,
        )

    def _refresh_inventory(self):
        try:
            self.resources.refresh_inventory()
        except (RuntimeError, ValueError, OSError):
            pass

    def readiness(self):
        identity = all(
            (self.adapter.core_secrets / name).is_file()
            for name in ("ca.crt", "client.crt", "client.key")
        )
        return {
            "business_available": bool(self.config.get("core_url") and identity and self.resources),
            "core_configured": bool(self.config.get("core_url")),
            "site_name": self.config["site"]["name"],
            "deployment_enabled": bool(self.config.get("nico_deployment", {}).get("enabled")),
            "reason": "请先部署 NICo 并应用到站点，或在站点设置中连接已有 Core。",
        }

    def _core_identity(self, source):
        namespace = source.get("namespace", self.nico_deployment.cluster.namespace)
        client = self.nico_deployment.cluster.get("secrets", source["client_secret"], namespace)
        root = self.nico_deployment.cluster.get("secrets", source["ca_secret"], namespace)
        if not client or not root:
            raise ValueError("未取得 Core 客户端证书，请检查部署包中的 Secret 引用。")
        directory = self.adapter.data / "core-identity" / uuid.uuid4().hex
        directory.mkdir(parents=True, mode=0o700)
        values = {
            "client.crt": client["data"][source.get("client_cert_key", "tls.crt")],
            "client.key": client["data"][source.get("client_private_key", "tls.key")],
            "ca.crt": root["data"][source.get("ca_key", "tls.crt")],
        }
        try:
            for name, data in values.items():
                atomic_text(directory / name, base64.b64decode(data, validate=True).decode())
            crt, key, ca = [str(directory / p) for p in ("client.crt", "client.key", "ca.crt")]
            run(["openssl", "x509", "-in", crt, "-checkend", "300", "-noout"])
            run(
                [
                    "openssl",
                    "verify",
                    "-purpose",
                    "sslclient",
                    "-CAfile",
                    ca,
                    "-untrusted",
                    crt,
                    crt,
                ]
            )
            if run(["openssl", "x509", "-in", crt, "-pubkey", "-noout"]) != run(
                ["openssl", "pkey", "-in", key, "-pubout"]
            ):
                raise ValueError("Core 客户端证书与私钥不匹配。")
        except Exception:
            import shutil

            shutil.rmtree(directory)
            raise ValueError("Core 客户端身份校验失败，未修改站点连接。") from None
        return directory, {
            "client": client["metadata"]["resourceVersion"],
            "ca": root["metadata"]["resourceVersion"],
        }

    def connect_deployed_site(self, operation):
        with self.connection_lock:
            if self.store.incomplete():
                raise ValueError("存在未完成安装任务，未切换 Core。")
            settings = operation["configuration"]
            source = operation["connection"]
            directory, revision = self._core_identity(source)
            proposed = copy.deepcopy(self.config)
            proposed.update(
                core_url=settings["core_url"],
                core_identity_directory=str(directory),
                core_identity_source=source,
                core_identity_revision=revision,
            )
            proposed["site"]["name"] = settings["site_name"]
            candidate = Adapter(proposed, self.adapter.secrets, self.adapter.data)
            try:
                candidate.rpc("FindNetworkSegmentIds", {})
            except Exception:
                raise ValueError("无法使用部署身份读取 Core，站点配置保持原值。") from None
            components = self.nico_deployment.view()["components"]
            proposed["site_components"] = [
                {
                    "id": c["id"],
                    "name": c["name"],
                    "role": c["role"],
                    "endpoint": ", ".join(
                        f"{e['name']}.{e.get('namespace', settings['namespace'])}.svc: {' / '.join(e['ports'])}"
                        for e in c["endpoints"]
                    ),
                    **(
                        {
                            "probe": {
                                "type": "tcp",
                                "host": urlsplit(settings["core_url"]).hostname,
                                "port": urlsplit(settings["core_url"]).port or 443,
                            }
                        }
                        if c["id"] == "core"
                        else {}
                    ),
                }
                for c in components
                if c["workloads"]
            ]
            pxe = next(b for b in operation["bindings"] if b["id"] == "pxe")
            proposed.setdefault("os_library", {}).update(
                directory=self.config.get("os_library", {}).get("directory", "/materials"),
                public_base_url=settings["pxe_url"] + "/public/blobs/internal/nico/os-library",
                verification_base_url=source.get(
                    "pxe_internal_url", f"http://{pxe['name']}.{pxe['namespace']}.svc:8080"
                )
                + "/public/blobs/internal/nico/os-library",
            )
            persisted = {
                k: proposed[k]
                for k in (
                    "site",
                    "core_url",
                    "core_identity_directory",
                    "core_identity_source",
                    "core_identity_revision",
                    "site_components",
                    "os_library",
                )
            }
            atomic_json(self.adapter.data / "config" / "deployment-site.json", persisted)
            atomic_json(
                self.adapter.data / "config" / "site-settings.json",
                {
                    "name": settings["site_name"],
                    "core_url": settings["core_url"],
                    "default_install_concurrency": self.config.get(
                        "default_install_concurrency", 5
                    ),
                },
            )
            self.config.update(persisted)
            self.adapter.core_secrets = directory
            if self.os_library:
                # The library holds a settings reference; refresh it after the site handoff.
                self.os_library.settings = self.config["os_library"]
                self.os_library.root = Path(self.os_library.settings["directory"])
            if not self.resources:
                self._bind_core_services()
                self._create_coordinator()
                self.resources.recover_network_operations()
                self.profiles.import_legacy()
                self.coordinator.recover()
            threading.Thread(target=self._refresh_inventory, daemon=True).start()
            if not getattr(self, "identity_maintenance_started", False):
                threading.Thread(target=self._maintain_core_identity, daemon=True).start()

    def _maintain_core_identity(self):
        self.identity_maintenance_started = True
        while self.config.get("core_identity_source"):
            try:
                source = self.config["core_identity_source"]
                client = self.nico_deployment.cluster.get(
                    "secrets", source["client_secret"], source.get("namespace")
                )
                root = self.nico_deployment.cluster.get(
                    "secrets", source["ca_secret"], source.get("namespace")
                )
                revision = (
                    {
                        "client": client["metadata"]["resourceVersion"],
                        "ca": root["metadata"]["resourceVersion"],
                    }
                    if client and root
                    else None
                )
                if revision and revision != self.config.get("core_identity_revision"):
                    directory, revision = self._core_identity(source)
                    with self.connection_lock:
                        self.adapter.core_secrets = directory
                        self.config.update(
                            core_identity_directory=str(directory), core_identity_revision=revision
                        )
                        path = self.adapter.data / "config" / "deployment-site.json"
                        record = json.loads(path.read_text())
                        record.update(
                            core_identity_directory=str(directory), core_identity_revision=revision
                        )
                        atomic_json(path, record)
            except Exception:
                # Retain the last verified identity; no Secret content reaches service logs.
                pass
            time.sleep(60)

    @property
    def worker_lock(self):
        return self.coordinator.worker_lock

    def site_information(self):
        def certificate():
            try:
                row = ssl._ssl._test_decode_cert(str(self.adapter.core_secrets / "client.crt"))
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
        configured_components = self.config.get("site_components") or (
            [
                {
                    "id": "core",
                    "name": "NICo Core",
                    "endpoint": self.config["core_url"],
                    "role": "资源、状态与装机编排 API",
                    "probe": {"type": "tcp", "host": core.hostname, "port": core.port or 443},
                }
            ]
            if self.config["core_url"]
            else []
        )
        components = [probe(row) for row in configured_components]
        return {
            "site": self.config["site"],
            "core_url": self.config["core_url"],
            "default_install_concurrency": self.config.get("default_install_concurrency", 5),
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
        if set(body) != {"name", "core_url", "default_install_concurrency"}:
            raise ValueError("站点设置字段无效。")
        name, core_url = str(body["name"]).strip(), str(body["core_url"]).strip()
        concurrency = body["default_install_concurrency"]
        if (
            isinstance(concurrency, bool)
            or not isinstance(concurrency, int)
            or not 1 <= concurrency <= 50
        ):
            raise ValueError("默认安装并发应为 1–50 的整数。")
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
        if core_url != self.config["core_url"] or not self.resources:
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
            {
                "name": name,
                "core_url": core_url,
                "default_install_concurrency": concurrency,
            },
        )
        self.config["site"]["name"] = name
        self.config["core_url"] = core_url
        self.config["default_install_concurrency"] = concurrency
        if not self.resources:
            self._bind_core_services()
            self._create_coordinator()
            self.profiles.import_legacy()
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

    def skip_acceptance(self, task_id, body, actor):
        return self.coordinator.skip_acceptance(task_id, body, actor)

    def resume(self, task_id, body, actor):
        return self.coordinator.resume(task_id, body, actor)

    def close_task(self, task_id, body, actor):
        return self.coordinator.close_task(task_id, body, actor)
