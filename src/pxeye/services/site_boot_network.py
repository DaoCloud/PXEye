"""PXEye-owned application of physical boot-service endpoints.

NICo retains DHCP allocation and PXE behavior. This service persists the
operator-selected physical endpoint addresses and applies only the Kea values
that advertise them. External Service and relay ownership remains outside PXEye.
"""

import ipaddress
import json
import threading
import time
import uuid
from urllib.parse import urlsplit, urlunsplit

from pxeye.common import atomic_json
from pxeye.deployment.kubernetes import ClusterError


class SiteBootNetwork:
    """Versioned site endpoints and their bounded Kubernetes projection."""

    def __init__(self, app):
        self.app = app
        self.cluster = app.nico_deployment.cluster
        self.path = app.adapter.data / "config" / "site-boot-network.json"
        self.lock = threading.RLock()
        self.state = self._load()
        self._restore_material_http_endpoint()

    def _load(self):
        try:
            value = json.loads(self.path.read_text())
        except (OSError, ValueError):
            value = {}
        return value if isinstance(value, dict) else {}

    def _save(self):
        atomic_json(self.path, self.state)

    def _restore_material_http_endpoint(self):
        current = self.state.get("current") or {}
        values = current.get("values") or {}
        if current.get("status") == "applied" and values.get("material_http_address"):
            self._set_material_http_endpoint(values)

    def namespace(self):
        source = self.app.config.get("core_identity_source") or {}
        bootstrap = (self.app.config.get("site_bootstrap") or {}).get("connection") or {}
        return str(
            (self.app.config.get("site_boot_network") or {}).get("namespace")
            or source.get("namespace")
            or bootstrap.get("namespace")
            or self.app.config.get("nico_deployment", {}).get("namespace")
            or self.cluster.namespace
        )

    @staticmethod
    def _ipv4(value, label, *, required=True):
        value = str(value or "").strip()
        if not value and not required:
            return ""
        try:
            parsed = ipaddress.ip_address(value)
        except ValueError:
            raise ValueError(label + "必须是 IPv4 地址。") from None
        if parsed.version != 4 or parsed.is_unspecified or parsed.is_multicast:
            raise ValueError(label + "必须是可用的 IPv4 地址。")
        return str(parsed)

    @classmethod
    def normalize(cls, body):
        required = {
            "dhcp_address",
            "pxe_address",
            "material_http_address",
            "material_http_port",
            "dns_address",
            "ntp_address",
            "topology",
            "relay_address",
        }
        if set(body) != required:
            raise ValueError("引导网络配置字段无效。")
        port = body["material_http_port"]
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("材料 HTTP 端口应为 1–65535。")
        topology = str(body["topology"])
        if topology not in ("same_l2", "relay"):
            raise ValueError("DHCP 拓扑只能是同二层或 Relay。")
        relay = cls._ipv4(body["relay_address"], "Relay 地址", required=topology == "relay")
        return {
            "dhcp_address": cls._ipv4(body["dhcp_address"], "DHCP 地址"),
            "pxe_address": cls._ipv4(body["pxe_address"], "PXE 引导地址"),
            "material_http_address": cls._ipv4(body["material_http_address"], "材料 HTTP 地址"),
            "material_http_port": port,
            "dns_address": cls._ipv4(body["dns_address"], "DNS 地址"),
            "ntp_address": cls._ipv4(body["ntp_address"], "NTP 地址"),
            "topology": topology,
            "relay_address": relay,
        }

    def _discover(self):
        namespace = self.namespace()
        configmaps = self.cluster.list("configmaps", namespace)
        maps = [row for row in configmaps if "kea_config.json" in row.get("data", {})]
        if len(maps) != 1:
            raise ValueError("无法唯一识别 NICo DHCP Kea ConfigMap；未修改任何运行配置。")
        configmap = maps[0]
        deployments = self.cluster.list("deployments", namespace)
        mounts = []
        for deployment in deployments:
            volumes = deployment.get("spec", {}).get("template", {}).get("spec", {}).get("volumes", [])
            if any(
                item.get("configMap", {}).get("name") == configmap["metadata"]["name"]
                for item in volumes
            ):
                mounts.append(deployment)
        if len(mounts) != 1:
            raise ValueError("无法唯一识别挂载 Kea ConfigMap 的 DHCP Deployment；未修改任何运行配置。")
        return {
            "namespace": namespace,
            "configmap": configmap,
            "deployment": mounts[0],
        }

    def _values_from_kea(self, configmap):
        """Return the currently advertised addresses from the live Kea ConfigMap."""
        try:
            dhcp = json.loads(configmap["data"]["kea_config.json"])["Dhcp4"]
        except (KeyError, TypeError, ValueError):
            raise ValueError("Kea ConfigMap 格式无效；无法读取当前引导网络地址。") from None

        option = next(
            (row for row in dhcp.get("option-data", []) if row.get("name") == "dhcp-server-identifier"),
            {},
        )
        hook = next(
            (
                row
                for row in dhcp.get("hooks-libraries", [])
                if "nico-provisioning-server-ipv4" in row.get("parameters", {})
                or "carbide-provisioning-server-ipv4" in row.get("parameters", {})
            ),
            None,
        )
        if not hook:
            raise ValueError("Kea 配置缺少 NICo DHCP hook；无法读取当前引导网络地址。")
        parameters = hook.get("parameters") or {}
        saved = (self.state.get("current") or {}).get("values") or {}
        return {
            "dhcp_address": str(option.get("data") or ""),
            "pxe_address": str(
                parameters.get("nico-provisioning-server-ipv4")
                or parameters.get("carbide-provisioning-server-ipv4")
                or ""
            ),
            "dns_address": str(
                parameters.get("nico-nameservers") or parameters.get("carbide-nameservers") or ""
            ),
            "ntp_address": str(
                parameters.get("nico-ntpserver") or parameters.get("carbide-ntpserver") or ""
            ),
            "topology": saved.get("topology", "same_l2"),
            "relay_address": saved.get("relay_address", ""),
        } | self._material_http_values()

    def _material_http_endpoint(self):
        """Return the configured public base URL for newly registered OS materials.

        Kea advertises a PXE IP address, while an OperatingSystem holds an
        immutable HTTP URL. These must remain separate site settings.
        """
        library = self.app.config.get("os_library") or {}
        return str(library.get("public_base_url") or "").rstrip("/")

    def _material_http_values(self):
        endpoint = self._material_http_endpoint()
        parsed = urlsplit(endpoint)
        return {
            "material_http_address": parsed.hostname or "",
            "material_http_port": parsed.port or 80,
            "material_http_endpoint": endpoint,
        }

    def _material_http_endpoint_for(self, values):
        parsed = urlsplit(self._material_http_endpoint())
        path = parsed.path.rstrip("/") or "/public/blobs/internal/nico/os-library"
        return urlunsplit(
            (
                parsed.scheme or "http",
                f"{values['material_http_address']}:{values['material_http_port']}",
                path,
                "",
                "",
            )
        )
    def _set_material_http_endpoint(self, values):
        endpoint = self._material_http_endpoint_for(values)
        self.app.config.setdefault("os_library", {})["public_base_url"] = endpoint
        return endpoint

    @staticmethod
    def _patch_kea(configmap, values):
        try:
            config = json.loads(configmap["data"]["kea_config.json"])
            dhcp = config["Dhcp4"]
        except (KeyError, TypeError, ValueError):
            raise ValueError("Kea ConfigMap 格式无效；未写入运行配置。") from None
        option_data = [
            row
            for row in dhcp.get("option-data", [])
            if row.get("name") != "dhcp-server-identifier"
        ]
        option_data.append(
            {"name": "dhcp-server-identifier", "data": values["dhcp_address"], "always-send": True}
        )
        dhcp["option-data"] = option_data
        libraries = dhcp.get("hooks-libraries", [])
        hook = next(
            (
                row
                for row in libraries
                if "nico-provisioning-server-ipv4" in row.get("parameters", {})
                or "carbide-provisioning-server-ipv4" in row.get("parameters", {})
            ),
            None,
        )
        if not hook:
            raise ValueError("Kea 配置缺少 NICo DHCP hook；未写入运行配置。")
        parameters = hook.setdefault("parameters", {})
        for key in ("nico-provisioning-server-ipv4", "carbide-provisioning-server-ipv4"):
            parameters[key] = values["pxe_address"]
        for key in ("nico-nameservers", "carbide-nameservers"):
            parameters[key] = values["dns_address"]
        for key in ("nico-ntpserver", "carbide-ntpserver"):
            parameters[key] = values["ntp_address"]
        return json.dumps(config, ensure_ascii=False, indent=2) + "\n"

    def _wait_for_dhcp(self, deployment):
        name = deployment["metadata"]["name"]
        deadline = time.monotonic() + 75
        while time.monotonic() < deadline:
            row = self.cluster.get("deployments", name, self.namespace()) or {}
            status = row.get("status", {})
            if status.get("availableReplicas", 0) >= 1 and status.get("updatedReplicas", 0) >= 1:
                return row
            time.sleep(3)
        raise ValueError("DHCP Deployment 未在限定时间内恢复 Ready；请查看 Pod 事件和 Kea 日志。")

    def summary(self):
        current = self.state.get("current") or {}
        return {
            "state": current.get("status", "unconfigured"),
            "revision": current.get("revision"),
            "applied_at": current.get("applied_at"),
            "values": current.get("values"),
            "detail": current.get("detail", "尚未配置物理引导服务地址。"),
        }

    def view(self):
        result = self.summary()
        result["namespace"] = self.namespace()
        result["material_http_endpoint"] = self._material_http_endpoint()
        try:
            discovered = self._discover()
            result["values"] = self._values_from_kea(discovered["configmap"])
            result["dhcp_configmap"] = discovered["configmap"]["metadata"]["name"]
            result["dhcp_deployment"] = discovered["deployment"]["metadata"]["name"]
            result["cluster_ready"] = True
        except (ClusterError, ValueError) as error:
            result["cluster_ready"] = False
            result["cluster_error"] = str(error)
        return result

    def preview(self, body):
        values = self.normalize(body)
        discovered = self._discover()
        resources = {
            "configmap": discovered["configmap"]["metadata"]["name"],
            "deployment": discovered["deployment"]["metadata"]["name"],
        }
        return {
            "values": values,
            "material_http_endpoint": self._material_http_endpoint_for(values),
            "namespace": discovered["namespace"],
            "resources": resources,
            "dhcp_configmap": discovered["configmap"]["metadata"]["name"],
            "dhcp_deployment": discovered["deployment"]["metadata"]["name"],
            "effects": [
                "按用户填写的地址更新 Kea DHCP 下发参数；不检查或修改外部 Service。",
                "更新 Kea DHCP Option 54、PXE 引导地址、DNS 与 NTP 下发参数。",
                "将 DHCP Deployment 缩放至 1 并执行一次受控滚动更新。",
                "不会修改 HostInband 网段、DHCP 地址池、设备规划或已有安装任务。",
                "保存材料 HTTP 地址与端口，供后续新建 OS 版本使用；不会改写既有 OS 定义。",
            ],
        }

    def apply(self, body, actor):
        values = self.normalize(body)
        if self.app.store.incomplete():
            raise ValueError("存在活动安装任务；请在维护窗口完成或结束任务后再修改引导服务地址。")
        with self.lock:
            discovered = self._discover()
            preview = self.preview(values)
            revision = uuid.uuid4().hex
            resources = preview["resources"]
            event = {
                "revision": revision,
                "values": values,
                "actor": actor,
                "started_at": time.time(),
                "resources": resources,
                "status": "applying",
            }
            self.state.setdefault("history", []).append(event)
            self.state["history"] = self.state["history"][-10:]
            self.state["current"] = event
            self._save()
            try:
                configmap = discovered["configmap"]
                rendered = self._patch_kea(configmap, values)
                self.cluster.patch(
                    "configmaps",
                    configmap["metadata"]["name"],
                    {"data": {"kea_config.json": rendered}},
                    discovered["namespace"],
                )
                deployment = discovered["deployment"]
                self.cluster.patch(
                    "deployments",
                    deployment["metadata"]["name"],
                    {
                        "spec": {
                            "replicas": 1,
                            "template": {
                                "metadata": {
                                    "annotations": {
                                        "pxeye.daocloud.io/site-boot-network-revision": revision
                                    }
                                }
                            },
                        }
                    },
                    discovered["namespace"],
                )
                ready = self._wait_for_dhcp(deployment)
                material_endpoint = self._set_material_http_endpoint(values)
                event.update(
                    status="applied",
                    applied_at=time.time(),
                    detail="已应用 Kea 配置并保存材料 HTTP 端点；仍需从引导网络完成 DHCP/PXE 验证。",
                    dhcp_deployment_generation=ready.get("metadata", {}).get("generation"),
                    material_http_endpoint=material_endpoint,
                )
                self._save()
                return self.view()
            except Exception as error:
                event.update(status="needs_attention", detail=str(error), failed_at=time.time())
                self._save()
                raise
