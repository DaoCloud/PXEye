"""PXEye-owned application of physical boot-service endpoints.

NICo retains DHCP allocation and PXE behavior.  This service owns only the
operator-selected Service VIPs and the Kea hook values that advertise them.
It deliberately discovers target workloads from live Kubernetes resources so
the operator never enters Helm release names into the browser.
"""

import copy
import ipaddress
import json
import threading
import time
import uuid

from pxeye.common import atomic_json
from pxeye.deployment.kubernetes import ClusterError


MANAGED_BY = "app.kubernetes.io/managed-by"
MANAGER = "pxeye-site-boot-network"
ROLE_LABEL = "pxeye.daocloud.io/site-boot-role"
VIP_ANNOTATION = "metallb.universe.tf/loadBalancerIPs"
SHARED_ANNOTATION = "metallb.universe.tf/allow-shared-ip"


class SiteBootNetwork:
    """Versioned site endpoints and their bounded Kubernetes projection."""

    def __init__(self, app):
        self.app = app
        self.cluster = app.nico_deployment.cluster
        self.path = app.adapter.data / "config" / "site-boot-network.json"
        self.lock = threading.RLock()
        self.state = self._load()

    def _load(self):
        try:
            value = json.loads(self.path.read_text())
        except (OSError, ValueError):
            value = {}
        return value if isinstance(value, dict) else {}

    def _save(self):
        atomic_json(self.path, self.state)

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
            "dhcp_vip",
            "pxe_vip",
            "pxe_port",
            "dns_vip",
            "ntp_vip",
            "topology",
            "relay_address",
        }
        if set(body) != required:
            raise ValueError("引导网络配置字段无效。")
        port = body["pxe_port"]
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("PXE HTTP 端口应为 1–65535。")
        topology = str(body["topology"])
        if topology not in ("same_l2", "relay"):
            raise ValueError("DHCP 拓扑只能是同二层或 Relay。")
        relay = cls._ipv4(body["relay_address"], "Relay 地址", required=topology == "relay")
        return {
            "dhcp_vip": cls._ipv4(body["dhcp_vip"], "DHCP VIP"),
            "pxe_vip": cls._ipv4(body["pxe_vip"], "PXE HTTP VIP"),
            "pxe_port": port,
            "dns_vip": cls._ipv4(body["dns_vip"], "DNS VIP"),
            "ntp_vip": cls._ipv4(body["ntp_vip"], "NTP VIP"),
            "topology": topology,
            "relay_address": relay,
        }

    @staticmethod
    def _port_matches(service, port, protocol):
        return any(
            int(item.get("port", 0)) == port
            and str(item.get("protocol", "TCP")).upper() == protocol
            for item in service.get("spec", {}).get("ports", [])
        )

    @classmethod
    def _source_service(cls, services, role, port, protocol, hints):
        candidates = [
            row
            for row in services
            if row.get("spec", {}).get("selector")
            and row.get("metadata", {}).get("labels", {}).get(MANAGED_BY) != MANAGER
            and cls._port_matches(row, port, protocol)
            and "metrics" not in row.get("metadata", {}).get("name", "").lower()
            and any(hint in row.get("metadata", {}).get("name", "").lower() for hint in hints)
        ]
        if len(candidates) != 1:
            names = ", ".join(sorted(x["metadata"]["name"] for x in candidates)) or "无"
            raise ValueError(
                f"无法唯一识别 {role} 的集群内 Service（候选：{names}）。"
                "请核对 NICo 服务是否已就绪，不会创建或修改未知目标。"
            )
        return candidates[0]

    def _discover(self):
        namespace = self.namespace()
        services = self.cluster.list("services", namespace)
        targets = {
            "dhcp": self._source_service(services, "DHCP", 67, "UDP", ("dhcp",)),
            "pxe": self._source_service(services, "PXE", 8080, "TCP", ("pxe",)),
            "dns": self._source_service(services, "DNS", 53, "UDP", ("dns", "resolver")),
            "ntp": self._source_service(services, "NTP", 123, "UDP", ("ntp",)),
        }
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
            "targets": targets,
            "configmap": configmap,
            "deployment": mounts[0],
        }

    @staticmethod
    def _ports_for(role, service, pxe_port):
        wanted = {
            "dhcp": {(67, "UDP")},
            "dns": {(53, "UDP"), (53, "TCP")},
            "ntp": {(123, "UDP")},
        }.get(role)
        ports = []
        for item in service.get("spec", {}).get("ports", []):
            key = (int(item.get("port", 0)), str(item.get("protocol", "TCP")).upper())
            if role == "pxe":
                if key != (8080, "TCP"):
                    continue
            elif key not in wanted:
                continue
            copied = {
                key: item[key]
                for key in ("name", "targetPort", "protocol", "appProtocol")
                if key in item
            }
            copied["protocol"] = str(item.get("protocol", "TCP")).upper()
            copied["port"] = pxe_port if role == "pxe" else key[0]
            ports.append(copied)
        if not ports:
            raise ValueError(f"{role} Service 缺少预期端口；未创建外部 Service。")
        return ports

    @staticmethod
    def _shared_groups(values):
        groups = {}
        for role, vip in (
            ("dhcp", values["dhcp_vip"]),
            ("pxe", values["pxe_vip"]),
            ("dns", values["dns_vip"]),
            ("ntp", values["ntp_vip"]),
        ):
            groups.setdefault(vip, []).append(role)
        return groups

    @classmethod
    def _validate_port_collisions(cls, values):
        seen = set()
        groups = cls._shared_groups(values)
        ports = {
            "dhcp": ((67, "UDP"),),
            "pxe": ((values["pxe_port"], "TCP"),),
            "dns": ((53, "UDP"), (53, "TCP")),
            "ntp": ((123, "UDP"),),
        }
        for vip, roles in groups.items():
            for role in roles:
                for port in ports[role]:
                    token = (vip,) + port
                    if token in seen:
                        raise ValueError("同一 VIP 的 Service 端口和协议不能重复。")
                    seen.add(token)

    def _service_body(self, role, source, values):
        vip = values[role + "_vip"] if role != "pxe" else values["pxe_vip"]
        groups = self._shared_groups(values)
        annotations = {VIP_ANNOTATION: vip}
        if len(groups[vip]) > 1:
            annotations[SHARED_ANNOTATION] = "pxeye-site-" + vip.replace(".", "-")
        base_spec = source.get("spec", {})
        return {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": "pxeye-site-" + role,
                "namespace": self.namespace(),
                "labels": {MANAGED_BY: MANAGER, ROLE_LABEL: role},
                "annotations": annotations,
            },
            "spec": {
                "type": "LoadBalancer",
                "ipFamilyPolicy": "SingleStack",
                "ipFamilies": ["IPv4"],
                "selector": copy.deepcopy(base_spec["selector"]),
                "ports": self._ports_for(role, source, values["pxe_port"]),
                **(
                    {"externalTrafficPolicy": base_spec["externalTrafficPolicy"]}
                    if base_spec.get("externalTrafficPolicy")
                    else {}
                ),
            },
        }

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
            {"name": "dhcp-server-identifier", "data": values["dhcp_vip"], "always-send": True}
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
            parameters[key] = values["pxe_vip"]
        for key in ("nico-nameservers", "carbide-nameservers"):
            parameters[key] = values["dns_vip"]
        for key in ("nico-ntpserver", "carbide-ntpserver"):
            parameters[key] = values["ntp_vip"]
        return json.dumps(config, ensure_ascii=False, indent=2) + "\n"

    @staticmethod
    def _assigned_vip(service):
        ingress = service.get("status", {}).get("loadBalancer", {}).get("ingress", [])
        return next((str(row.get("ip")) for row in ingress if row.get("ip")), "")

    def _wait_for_vips(self, resources, values):
        expected = {
            "dhcp": values["dhcp_vip"],
            "pxe": values["pxe_vip"],
            "dns": values["dns_vip"],
            "ntp": values["ntp_vip"],
        }
        deadline = time.monotonic() + 30
        pending = set(expected)
        while pending and time.monotonic() < deadline:
            for role in tuple(pending):
                row = self.cluster.get("services", resources[role], self.namespace())
                if self._assigned_vip(row or {}) == expected[role]:
                    pending.remove(role)
            if pending:
                time.sleep(2)
        if pending:
            raise ValueError("MetalLB 尚未分配预期 VIP：" + "、".join(sorted(pending)) + "。")

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
        try:
            discovered = self._discover()
            result["targets"] = {
                role: row["metadata"]["name"] for role, row in discovered["targets"].items()
            }
            result["dhcp_configmap"] = discovered["configmap"]["metadata"]["name"]
            result["dhcp_deployment"] = discovered["deployment"]["metadata"]["name"]
            result["cluster_ready"] = True
        except (ClusterError, ValueError) as error:
            result["cluster_ready"] = False
            result["cluster_error"] = str(error)
        return result

    def preview(self, body):
        values = self.normalize(body)
        self._validate_port_collisions(values)
        discovered = self._discover()
        resources = {
            role: "pxeye-site-" + role for role in ("dhcp", "pxe", "dns", "ntp")
        }
        return {
            "values": values,
            "namespace": discovered["namespace"],
            "resources": resources,
            "source_services": {
                role: item["metadata"]["name"] for role, item in discovered["targets"].items()
            },
            "dhcp_configmap": discovered["configmap"]["metadata"]["name"],
            "dhcp_deployment": discovered["deployment"]["metadata"]["name"],
            "effects": [
                "创建或更新四个 PXEye 管理的 LoadBalancer Service。",
                "更新 Kea DHCP Option 54、PXE、DNS 与 NTP 下发参数。",
                "将 DHCP Deployment 缩放至 1 并执行一次受控滚动更新。",
                "不会修改 HostInband 网段、DHCP 地址池、设备规划或已有安装任务。",
                "不会自动改写 OS 定义；公开材料 URL 迁移将在 NICo 契约验证后单独提供。",
            ],
        }

    def apply(self, body, actor):
        values = self.normalize(body)
        self._validate_port_collisions(values)
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
                for role, source in discovered["targets"].items():
                    name = resources[role]
                    body = self._service_body(role, source, values)
                    existing = self.cluster.get("services", name, discovered["namespace"])
                    if existing and existing.get("metadata", {}).get("labels", {}).get(MANAGED_BY) != MANAGER:
                        raise ValueError("拒绝覆盖非 PXEye 管理的 Service：" + name)
                    if existing:
                        annotations = dict(body["metadata"]["annotations"])
                        if SHARED_ANNOTATION not in annotations:
                            # A JSON merge patch needs an explicit null to remove a
                            # sharing group left by a previous same-VIP revision.
                            annotations[SHARED_ANNOTATION] = None
                        self.cluster.patch(
                            "services",
                            name,
                            {
                                "metadata": body["metadata"] | {"annotations": annotations},
                                "spec": body["spec"],
                            },
                            discovered["namespace"],
                        )
                    else:
                        self.cluster.create("services", body, discovered["namespace"])
                self._wait_for_vips(resources, values)
                configmap = discovered["configmap"]
                rendered = self._patch_kea(configmap, values)
                self.cluster.patch(
                    "configmaps",
                    configmap["metadata"]["name"],
                    {
                        "metadata": {"labels": {MANAGED_BY: MANAGER}},
                        "data": {"kea_config.json": rendered},
                    },
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
                event.update(
                    status="applied",
                    applied_at=time.time(),
                    detail="服务 VIP 与 Kea 配置已应用；仍需从引导网络完成 DHCP/PXE 验证。",
                    dhcp_deployment_generation=ready.get("metadata", {}).get("generation"),
                )
                self._save()
                return self.view()
            except Exception as error:
                event.update(status="needs_attention", detail=str(error), failed_at=time.time())
                self._save()
                raise
