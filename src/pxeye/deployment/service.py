"""Persistent Helm orchestration, live service status and explicit site handoff."""

import copy
import base64
import json
import os
import shlex
import shutil
import ssl
import subprocess
import threading
import time
import tomllib
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor

import yaml

from pxeye.common import atomic_json, atomic_text
from pxeye.deployment.components import REQUIRED, WORKLOADS, project, readiness
from pxeye.deployment.kubernetes import ClusterError, CurrentCluster
from pxeye.deployment.packages import Packages, configuration, substitute
from pxeye.deployment.renderer import validate_workload
from pxeye.deployment.sources import Sources, DEFAULT_CHART_URL

GROUP_RESOURCES = {
    "ServiceAccount": ("", "serviceaccounts"),
    "ConfigMap": ("", "configmaps"),
    "Secret": ("", "secrets"),
    "Service": ("", "services"),
    "PersistentVolumeClaim": ("", "persistentvolumeclaims"),
    "Deployment": ("apps", "deployments"),
    "StatefulSet": ("apps", "statefulsets"),
    "DaemonSet": ("apps", "daemonsets"),
    "Job": ("batch", "jobs"),
    "CronJob": ("batch", "cronjobs"),
    "Pod": ("", "pods"),
    "Endpoints": ("", "endpoints"),
    "Role": ("rbac.authorization.k8s.io", "roles"),
    "RoleBinding": ("rbac.authorization.k8s.io", "rolebindings"),
    "ClusterRole": ("rbac.authorization.k8s.io", "clusterroles"),
    "ClusterRoleBinding": ("rbac.authorization.k8s.io", "clusterrolebindings"),
    "CustomResourceDefinition": ("apiextensions.k8s.io", "customresourcedefinitions"),
    "Certificate": ("cert-manager.io", "certificates"),
    "Issuer": ("cert-manager.io", "issuers"),
    "ClusterIssuer": ("cert-manager.io", "clusterissuers"),
    "NetworkPolicy": ("networking.k8s.io", "networkpolicies"),
    "Ingress": ("networking.k8s.io", "ingresses"),
    "Lease": ("coordination.k8s.io", "leases"),
    "PodDisruptionBudget": ("policy", "poddisruptionbudgets"),
    "MutatingWebhookConfiguration": (
        "admissionregistration.k8s.io",
        "mutatingwebhookconfigurations",
    ),
    "ValidatingWebhookConfiguration": (
        "admissionregistration.k8s.io",
        "validatingwebhookconfigurations",
    ),
}
CLUSTER_KINDS = {
    "ClusterRole",
    "ClusterRoleBinding",
    "CustomResourceDefinition",
    "ClusterIssuer",
    "MutatingWebhookConfiguration",
    "ValidatingWebhookConfiguration",
}
OBSERVATIONS = WORKLOADS | {
    "Pod": "pods",
    "Service": "services",
    "Job": "jobs",
    "Certificate": "certificates",
    "PersistentVolumeClaim": "persistentvolumeclaims",
}


class NicoDeployment:
    def __init__(self, app):
        self.app = app
        self.settings = app.config.get("nico_deployment", {})
        self.directory = app.adapter.data / "nico-deployment"
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.cluster = CurrentCluster(self.settings, self.directory)
        self.packages = Packages(self.settings.get("packages_directory", "/nico-packages"))
        self.sources = Sources(self.directory, self.packages)
        self.lock = threading.RLock()
        self.busy = False
        self.observing = False
        self.observed = {"components": project([]), "checked_at": None, "error": "", "objects": []}
        self.current = self._read()
        if self.current and self.current["status"] in ("checking", "deploying", "connecting"):
            self.current.update(
                status="needs_attention",
                error="PXEye 已重启；请先核对 Helm 发布和服务状态，再继续。",
            )
            for phase in self.current.get("phases", []):
                if phase["state"] == "running":
                    phase.update(state="unknown", detail="服务重启时阶段仍在执行，需核对发布状态")
            self._save()

    def _read(self):
        path = self.directory / "current.json"
        return json.loads(path.read_text()) if path.exists() else None

    def _save(self):
        self.current["updated_at"] = time.time()
        atomic_json(self.directory / "current.json", self.current)
        atomic_json(self.directory / (self.current["id"] + ".json"), self.current)

    def _event(self, message, command=None, exit_code=None):
        with self.lock:
            self.current.setdefault("events", []).append(
                {
                    "at": time.time(),
                    "message": message,
                    **({"command": command} if command else {}),
                    **({"exit_code": exit_code} if exit_code is not None else {}),
                }
            )
            self._save()

    def _background(self, function):
        def work():
            try:
                function()
            except Exception as error:
                with self.lock:
                    message = (
                        str(error)
                        if isinstance(error, ValueError)
                        else "部署执行失败；请核对当前阶段、Helm 发布和 Pod 状态。"
                    )
                    self.current.update(status="needs_attention", error=message)
                    for phase in self.current.get("phases", []):
                        if phase["state"] == "running":
                            phase.update(state="failed", detail=message, finished_at=time.time())
                    self._save()
            finally:
                with self.lock:
                    self.busy = False

        threading.Thread(target=work, name="nico-deployment", daemon=True).start()

    def view(self, *, refresh=False):
        with self.lock:
            observation = copy.deepcopy(self.observed)
            observation.pop("objects", None)
            if observation.get("error") or (
                observation.get("checked_at") and time.time() - observation["checked_at"] > 45
            ):
                for component in observation["components"]:
                    if component["workloads"]:
                        component["state"] = "unknown"
                        for workload in component["workloads"]:
                            workload.update(state="unknown", detail="上次读取记录，当前状态待确认")
            current = copy.deepcopy(self.current)
            if current:
                current.pop("rendered", None)
                # Values may contain credentials. Only the operator's local form shows its input.
                current.get("configuration", {}).pop("values_yaml", None)
            result = {
                "namespace": self.cluster.namespace,
                "cluster_available": self.cluster.available,
                "enabled": bool(self.settings.get("enabled", False)),
                "packages": self.sources.list(),
                "source_defaults": {
                    "source_type": "url",
                    "chart_source": self.settings.get("online_chart_url", DEFAULT_CHART_URL),
                },
                "operation": current,
                "busy": self.busy,
                "observing": self.observing,
                "site_connected": self.app.readiness()["business_available"],
                **observation,
            }
            # Stale observations never permit site handoff.
            result["ready"] = bool(
                observation.get("checked_at")
                and not observation.get("error")
                and time.time() - observation["checked_at"] < 45
                and all(c["state"] == "ready" for c in observation["components"] if c["required"])
                and observation.get("initialization_ready")
                and observation.get("boot_ready")
            )
            if (
                not self.observing
                and self.cluster.available
                and (
                    refresh
                    or not self.observed.get("checked_at")
                    or time.time() - self.observed["checked_at"] > 8
                )
            ):
                self.observing = True
                threading.Thread(target=self._observe_background, daemon=True).start()
            result["observing"] = self.observing
            return result

    def _observe_background(self):
        try:
            self.observe()
        except Exception as error:
            with self.lock:
                self.observed["error"] = (
                    str(error)
                    if isinstance(error, ValueError)
                    else "读取集群状态失败，当前显示上次记录。"
                )
                self.observed["error_at"] = time.time()
        finally:
            with self.lock:
                self.observing = False

    def observe(self):
        namespaces = self.cluster.namespaces
        bindings = []
        current = copy.deepcopy(self.current)
        if current:
            bindings = current.get("bindings", [])
            namespaces = list(dict.fromkeys(namespaces + [b["namespace"] for b in bindings]))

        def fetch(pair):
            namespace, kind = pair
            return [
                row | {"kind": kind} for row in self.cluster.list(OBSERVATIONS[kind], namespace)
            ]

        with ThreadPoolExecutor(max_workers=6) as pool:
            groups = list(
                pool.map(fetch, [(ns, kind) for ns in namespaces for kind in OBSERVATIONS])
            )
        objects = [obj for group in groups for obj in group]
        jobs = []
        dependencies = []
        boot_ready = False
        if current:
            for target in current.get("dependencies", []):
                found = next(
                    (
                        o
                        for o in objects
                        if o["kind"] == target["kind"]
                        and o["metadata"]["name"] == target["name"]
                        and o["metadata"]["namespace"] == target["namespace"]
                    ),
                    None,
                )
                phase = next(p for p in current["phases"] if p["id"] == target["phase"])
                if found:
                    state = readiness(found)
                elif target.get("hook") and phase["state"] == "ready":
                    state = {"state": "ready", "detail": "Helm hook 已完成并清理"}
                else:
                    state = {"state": "missing", "detail": "资源尚未创建"}
                record = {**target, **state}
                (jobs if target["kind"] == "Job" else dependencies).append(record)
            boot_ready = (
                self._boot_probe(current.get("boot_checks", []))
                if all(p["state"] == "ready" for p in current["phases"])
                else False
            )
        components = project(objects, bindings)
        if (
            current
            and current.get("connection")
            and (jobs or current.get("profile") == "helm")
            and all(j["state"] == "ready" for j in jobs)
        ):
            vault = next(c for c in components if c["id"] == "vault")
            if vault["state"] == "ready" and not self._vault_probe(current, components):
                vault["state"] = "starting"
                for workload in vault["workloads"]:
                    workload.update(state="starting", detail="等待 Vault 解封与健康检查")
        result = {
            "checked_at": time.time(),
            "error": "",
            "components": components,
            "objects": objects,
            "jobs": jobs,
            "dependencies": dependencies,
            "initialization_ready": bool(
                current
                and (jobs or current.get("profile") == "helm")
                and all(p["state"] == "ready" for p in current.get("phases", []))
                and all(j["state"] == "ready" for j in jobs)
                and all(d["state"] == "ready" for d in dependencies)
            ),
            "boot_ready": boot_ready,
            "ready_count": sum(c["state"] == "ready" for c in components if c["required"]),
            "required_count": len(REQUIRED),
        }
        with self.lock:
            self.observed = result
        return result

    def _vault_probe(self, current, components):
        source = current["connection"]
        try:
            ca = self.cluster.get("secrets", source["ca_secret"], source.get("namespace"))
            context = ssl.create_default_context(
                cadata=base64.b64decode(
                    ca["data"][source.get("ca_key", "tls.crt")], validate=True
                ).decode()
            )
            binding = next((b for b in current["bindings"] if b["id"] == "vault"), None)
            if not binding:
                vault = next(c for c in components if c["id"] == "vault")
                if len(vault["workloads"]) != 1:
                    return False
                binding = vault["workloads"][0]
            address = source.get(
                "vault_url", f"https://{binding['name']}.{binding['namespace']}.svc:8200"
            )
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context)
            )
            with opener.open(address + "/v1/sys/health?standbyok=true", timeout=3) as response:
                result = json.load(response)
                return (
                    response.status == 200
                    and result.get("initialized")
                    and not result.get("sealed")
                )
        except (OSError, ValueError, KeyError, TypeError):
            return False

    @staticmethod
    def _boot_probe(checks):
        if not checks:
            return False
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for row in checks:
            request = urllib.request.Request(row["url"], method="HEAD")
            try:
                with opener.open(request, timeout=5) as response:
                    if response.status != 200 or int(
                        response.headers.get("Content-Length", "0")
                    ) < row.get("min_bytes", 1):
                        return False
            except (OSError, ValueError):
                return False
        return True

    def _run(self, argv, *, timeout=120, public=True, render_plan=None):
        if public:
            command = shlex.join(argv)
            if render_plan:
                command = "NICO_RENDER_PLAN=" + shlex.quote(str(render_plan)) + " " + command
            self._event("执行 Helm 命令", command)
        try:
            result = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={
                    **os.environ,
                    "HELM_CACHE_HOME": str(self.directory / "helm/cache"),
                    "HELM_CONFIG_HOME": str(self.directory / "helm/config"),
                    "HELM_DATA_HOME": str(self.directory / "helm/data"),
                    **({"NICO_RENDER_PLAN": str(render_plan)} if render_plan else {}),
                },
            )
        except subprocess.TimeoutExpired:
            if public:
                self._event("命令超时；保留发布和数据，请核对实际状态", exit_code=124)
            raise ClusterError("Helm 阶段超时，请核对发布状态和未就绪组件。") from None
        # Full outputs can contain chart notes or rendered credentials; retain privately only.
        log = self.directory / self.current["id"] / (uuid.uuid4().hex + ".private.log")
        atomic_text(log, result.stdout + "\n" + result.stderr)
        if public:
            self._event(
                "命令已完成" if result.returncode == 0 else "命令失败，请查看服务异常与初始化状态",
                exit_code=result.returncode,
            )
        if result.returncode:
            raise ClusterError(
                f"Helm 返回退出码 {result.returncode}；请核对 Chart 配置、发布状态与服务异常。"
            )
        return result.stdout

    def _helm(self):
        helm = self.settings.get("helm", "/usr/local/bin/helm")
        if not shutil.which(helm):
            raise ClusterError("PXEye 镜像未包含 Helm，请补齐 Linux Helm 3 工具。")
        return [helm, "--kubeconfig", str(self.cluster.kubeconfig())]

    def preflight(self, body):
        if not self.settings.get("enabled"):
            raise ValueError("集群部署未启用，请配置 nico_deployment.enabled 和 ServiceAccount。")
        settings = configuration(body, self.cluster.namespace)
        settings["pxeye_node"] = os.environ.get("POD_NODE_NAME", "")
        with self.lock:
            if self.busy:
                raise ValueError("已有部署操作正在执行。")
            if (
                self.current
                and self.current.get("started_at")
                and self.current["status"] not in ("connected", "installed")
            ):
                raise ValueError("存在未结束的部署记录，请先刷新并继续原部署。")
            if self.app.store.incomplete():
                raise ValueError("存在未完成的安装任务，不能部署或切换控制面。")
            self.busy = True
            self.current = {
                "id": str(uuid.uuid4()),
                "status": "checking",
                "configuration": settings,
                "phases": [{"id": "preflight", "name": "检查集群与部署材料", "state": "running"}],
                "events": [],
                "error": "",
                "created_at": time.time(),
            }
            self._save()
        self._background(lambda: self._preflight(settings))
        return {"status": "accepted", "detail": "已启动后台部署预检。", "id": self.current["id"]}

    def _preflight(self, settings):
        self.cluster.request("/version")
        base = self._helm()
        package = self.sources.prepare(
            settings, lambda args, **kwargs: self._run(base + args, **kwargs), self._event
        )
        simple = package["manifest"].get("profile") == "helm"
        self._event("Chart 与 values 已准备" if simple else "部署包摘要与服务清单已核对")
        if simple and package["manifest"]["name"] == "nico":
            package["manifest"]["phases"][0]["pod_overrides"] = [
                {
                    "kind": "Deployment",
                    "name": "mmzhou-nico-pxe",
                    "fsGroup": 1000,
                    "nodeSelector": {"kubernetes.io/hostname": settings["pxeye_node"]}
                    if settings["pxeye_node"]
                    else {},
                    "volumes": [
                        {
                            "name": "pxeye-os-materials",
                            "persistentVolumeClaim": {
                                "claimName": self.settings.get(
                                    "materials_claim", "mmzhou-pxeye-materials"
                                )
                            },
                        }
                    ],
                    "containers": [
                        {
                            "name": "mmzhou-nico-pxe",
                            "volumeMounts": [
                                {
                                    "name": "pxeye-os-materials",
                                    "mountPath": "/forge-boot-artifacts/blobs/internal/nico/os-library",
                                    "readOnly": True,
                                }
                            ],
                        }
                    ],
                }
            ]
        objects = self.observe()["objects"]
        rendered = []
        phases = []
        permissions = set()
        for phase in package["manifest"]["phases"]:
            release = substitute(phase["release"], settings)
            existing = [
                c
                for c in self.observed["components"]
                if c["id"] in phase.get("reuse_components", [])
            ]
            reuse = bool(
                existing
                and len(existing) == len(phase.get("reuse_components", []))
                and all(c["state"] == "ready" for c in existing)
            )
            row = {
                "id": phase["id"],
                "name": phase["name"],
                "release": release,
                "state": "ready" if reuse else "pending",
                "reused": reuse,
                "detail": "复用现有健康服务" if reuse else "等待部署",
                "timeout_seconds": phase.get("timeout_seconds", 600),
            }
            phases.append(row)
            if reuse:
                for component in existing:
                    binding = next(b for b in package["bindings"] if b["id"] == component["id"])
                    if len(component["workloads"]) != 1:
                        raise ValueError("共享组件存在多个部署，请明确观察命名空间和组件映射。")
                    workload = component["workloads"][0]
                    binding.update(
                        name=workload["name"],
                        namespace=workload["namespace"],
                        kind=workload["kind"],
                        external=True,
                    )
                continue
            phase_dir = self.directory / self.current["id"] / phase["id"]
            phase_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            values = []
            for index, value in enumerate(self.packages.values(package, phase, settings)):
                target = phase_dir / f"values-{index}.yaml"
                atomic_text(target, yaml.safe_dump(value, allow_unicode=True))
                values.extend(["-f", str(target)])
            chart = phase_dir / "chart.tgz"
            shutil.copyfile(self.packages.file(package["root"], phase["chart"]), chart)
            chart.chmod(0o600)
            plan = phase_dir / "render-plan.json"
            atomic_json(
                plan,
                {
                    "namespace": settings["namespace"],
                    "prefix": "mmzhou" if simple else settings["release_prefix"],
                    "overrides": substitute(phase.get("pod_overrides", []), settings),
                },
            )
            renderer = self.settings.get("post_renderer", "pxeye-render-nico")
            if not shutil.which(renderer):
                raise ClusterError("PXEye 运行环境未安装 pxeye-render-nico。")
            raw = self._run(
                base
                + [
                    "template",
                    release,
                    str(chart),
                    "-n",
                    settings["namespace"],
                    "--include-crds",
                    "--post-renderer",
                    renderer,
                ]
                + values,
                render_plan=plan,
            )
            docs = [obj for obj in yaml.safe_load_all(raw) if obj]
            if any(o.get("kind") == "List" for o in docs):
                docs = [x for o in docs for x in (o["items"] if o.get("kind") == "List" else [o])]
            for obj in docs:
                validate_workload(
                    obj, settings["namespace"], "mmzhou" if simple else settings["release_prefix"]
                )
                if obj.get("kind") == "ConfigMap":
                    for name, content in obj.get("data", {}).items():
                        if name.endswith("-site-config.toml"):
                            site = tomllib.loads(content)
                            explorer = site.get("site_explorer", {})
                            if (
                                explorer.get("enabled")
                                or explorer.get("create_machines")
                                or site.get("firmware_global", {}).get("autoupdate")
                            ):
                                raise ValueError(
                                    "初始部署必须关闭自动发现接管与固件自动更新，避免启动真实设备流程。"
                                )
                metadata = obj.setdefault("metadata", {})
                cluster_scoped = obj["kind"] in CLUSTER_KINDS
                if cluster_scoped and not self.settings.get("allow_cluster_resources", False):
                    raise ValueError(
                        "Chart 包含集群级资源；请复用现有组件，或由管理员明确启用 allow_cluster_resources。"
                    )
                if not cluster_scoped:
                    metadata.setdefault("namespace", settings["namespace"])
                    if metadata["namespace"] != settings["namespace"]:
                        raise ValueError(
                            "Chart 渲染到了其他命名空间，请修正 namespaceOverride 和内部服务引用。"
                        )
                if obj["kind"] not in GROUP_RESOURCES:
                    raise ValueError(
                        f"Chart 包含未支持的资源类型 {obj['kind']}，需要补齐权限与部署适配。"
                    )
                group, resource = GROUP_RESOURCES[obj["kind"]]
                ns = None if cluster_scoped else settings["namespace"]
                for verb in ("get", "create", "update", "patch", "delete"):
                    permission = (verb, resource, group, ns)
                    if permission in permissions:
                        continue
                    if not self.cluster.allowed(verb, resource, group, ns):
                        raise ValueError(f"缺少 {resource} 的 {verb} 权限，请检查部署 RBAC。")
                    permissions.add(permission)
                # Existing non-Helm .50 resources are observed, never taken over.
                conflict = next(
                    (
                        o
                        for o in objects
                        if o["kind"] == obj["kind"]
                        and o["metadata"]["name"] == metadata.get("name")
                        and o["metadata"]["namespace"] == metadata.get("namespace")
                    ),
                    None,
                )
                if conflict:
                    raise ValueError(
                        f"资源已存在：{metadata['name']}；本页不会接管已有部署，请连接现有站点。"
                    )
                api = "/api/v1" if obj["apiVersion"] == "v1" else "/apis/" + obj["apiVersion"]
                resource_path = (
                    api + (f"/namespaces/{ns}" if ns else "") + f"/{resource}/{metadata['name']}"
                )
                if self.cluster.request(resource_path):
                    raise ValueError(f"资源已存在：{metadata['name']}；请核对归属，未执行部署。")
                rendered.append(
                    {
                        "kind": obj["kind"],
                        "name": metadata.get("name", ""),
                        "namespace": metadata.get("namespace"),
                        "phase": phase["id"],
                        "hook": metadata.get("annotations", {}).get("helm.sh/hook", ""),
                    }
                )
            if phase["id"] in package["manifest"].get("initialization", {}).values() and not any(
                o["kind"] == "Job" for o in docs
            ):
                raise ValueError(
                    f"{phase['name']} 未包含初始化 Job / Helm hook，不能作为完整部署阶段。"
                )
            self._event(f"{phase['name']} 渲染与权限检查完成")
        if simple:
            # Recognize services from the rendered Chart; no user-maintained component manifest.
            projected = project(docs)
            package["bindings"] = [
                {
                    "id": c["id"],
                    "kind": w["kind"],
                    "name": w["name"],
                    "namespace": w["namespace"],
                    "phase": "helm",
                }
                for c in projected
                if len(c["workloads"]) == 1
                for w in c["workloads"]
            ]
            pxe = next((b for b in package["bindings"] if b["id"] == "pxe"), None)
            if not pxe:
                existing_pxe = next(c for c in self.observed["components"] if c["id"] == "pxe")
                if len(existing_pxe["workloads"]) == 1:
                    workload = existing_pxe["workloads"][0]
                    pxe = {
                        "id": "pxe",
                        "kind": workload["kind"],
                        "name": workload["name"],
                        "namespace": workload["namespace"],
                        "phase": "helm",
                        "external": True,
                    }
                    package["bindings"].append(pxe)
            source = package["connection"] = {
                "namespace": settings["namespace"],
                "client_secret": settings.get("client_secret") or "mmzhou-nico-admin-client",
                "ca_secret": settings.get("ca_secret") or "mmzhou-nico-site-ca",
            }
            if pxe:
                source["pxe_internal_url"] = f"http://{pxe['name']}.{pxe['namespace']}.svc:8080"
                architectures = (
                    ("x86_64", "aarch64")
                    if settings.get("architecture", "both") == "both"
                    else (settings["architecture"],)
                )
                package["boot_checks"] = [
                    {
                        "architecture": arch,
                        "url": source["pxe_internal_url"] + f"/public/blobs/internal/{arch}/{name}",
                        "min_bytes": size,
                    }
                    for arch in architectures
                    for name, size in (
                        ("ipxe.efi", 100000),
                        ("scout.efi", 100000),
                        ("scout.squashfs", 100000000),
                    )
                ]
        for binding in package["bindings"]:
            phase = next(p for p in phases if p["id"] == binding["phase"])
            found = any(
                o["kind"] == binding["kind"]
                and o["name"] == binding["name"]
                and o["namespace"] == binding["namespace"]
                for o in rendered
            )
            if not phase["reused"] and not binding.get("external") and not found:
                raise ValueError(f"Chart 未渲染服务 {binding['id']}，请修正组件映射或 values。")
        dependencies = [
            o for o in rendered if o["kind"] in ("Job", "Certificate", "PersistentVolumeClaim")
        ]
        with self.lock:
            self.current.update(
                status="prepared",
                revision=package["revision"],
                configuration=settings,
                profile="helm" if simple else "recipe",
                bindings=package["bindings"],
                phases=phases,
                dependencies=dependencies,
                connection=package["connection"],
                boot_checks=package["boot_checks"],
                prepared_at=time.time(),
                commands=[
                    "NICO_RENDER_PLAN="
                    + shlex.quote(
                        str(self.directory / self.current["id"] / p["id"] / "render-plan.json")
                    )
                    + " "
                    + shlex.join(self._install_arguments(settings, p))
                    for p in phases
                    if not p["reused"]
                ],
                error="",
            )
            self._save()
        self._event("预检完成，确认后按当前配置部署")

    def _install_arguments(self, settings, phase):
        path = self.directory / self.current["id"] / phase["id"]
        values = [arg for p in sorted(path.glob("values-*.yaml")) for arg in ("-f", str(p))]
        return (
            self._helm()
            + [
                "upgrade",
                "--install",
                phase["release"],
                str(path / "chart.tgz"),
                "-n",
                settings["namespace"],
                "--wait",
                "--wait-for-jobs",
                "--timeout",
                str(phase["timeout_seconds"]) + "s",
                "--post-renderer",
                self.settings.get("post_renderer", "pxeye-render-nico"),
            ]
            + values
        )

    def start(self, body):
        if not self.settings.get("enabled"):
            raise ValueError("集群部署已禁用，未执行 Helm 写操作。")
        if set(body) != {"id", "confirm"} or body["confirm"] is not True:
            raise ValueError("请确认在当前集群部署 NICo。")
        with self.lock:
            if self.busy or not self.current or self.current["id"] != body["id"]:
                raise ValueError("部署记录已变化或正在执行，请刷新。")
            if self.current["status"] not in (
                "prepared",
                "needs_attention",
            ) or not self.current.get("revision"):
                raise ValueError("请先完成部署预检。")
            if (
                not self.current.get("started_at")
                and time.time() - self.current["prepared_at"] > 600
            ):
                raise ValueError("预检已超过 10 分钟，请重新检查。")
            if self.app.store.incomplete():
                raise ValueError("存在未完成的安装任务，暂不能部署。")
            package = self.sources.load(self.current["configuration"])
            if package["revision"] != self.current["revision"]:
                raise ValueError("部署包或配置已变化，未继续执行。")
            self.busy = True
            self.current.update(
                status="deploying", started_at=self.current.get("started_at", time.time()), error=""
            )
            self._save()
        self._background(self._deploy)
        return {"status": "accepted", "detail": "已启动后台 Helm 部署。"}

    def _deploy(self):
        settings = self.current["configuration"]
        base = self._helm()
        for phase in self.current["phases"]:
            if phase["state"] == "ready":
                continue
            path = self.directory / self.current["id"] / phase["id"]
            # Helm history is read before resuming any uncertain write.
            releases = json.loads(
                self._run(
                    base + ["list", "-n", settings["namespace"], "--all", "-o", "json"],
                )
            )
            existing = next((r for r in releases if r["name"] == phase["release"]), None)
            if existing:
                status = existing["status"]
                if status.startswith("pending") or status == "uninstalling":
                    raise ClusterError(
                        f"发布 {phase['release']} 仍在 {status}；请核对 Helm 状态，系统不会重放。"
                    )
                if not phase.get("attempted_at"):
                    raise ClusterError(f"发布 {phase['release']} 已存在，不能接管其他部署。")
                if status == "deployed":
                    actual = (
                        json.loads(
                            self._run(
                                base
                                + [
                                    "get",
                                    "values",
                                    phase["release"],
                                    "-n",
                                    settings["namespace"],
                                    "-o",
                                    "json",
                                ]
                            )
                        )
                        or {}
                    )
                    expected = {}

                    def merge(target, value):
                        for key, item in value.items():
                            if isinstance(item, dict) and isinstance(target.get(key), dict):
                                merge(target[key], item)
                            else:
                                target[key] = copy.deepcopy(item)

                    for value_file in sorted(path.glob("values-*.yaml")):
                        merge(expected, yaml.safe_load(value_file.read_text()) or {})
                    if actual != expected:
                        raise ClusterError(
                            f"发布 {phase['release']} 的 values 与本次记录不符；请核对外部修改，未继续执行。"
                        )
                    phase.update(
                        state="ready", detail="已核对 Helm 发布完成", finished_at=time.time()
                    )
                    self._save()
                    continue
            phase.update(state="running", attempted_at=time.time(), detail="正在应用 Helm Chart")
            self._save()
            self._run(
                self._install_arguments(settings, phase),
                timeout=phase["timeout_seconds"] + 30,
                render_plan=path / "render-plan.json",
            )
            phase.update(state="ready", detail="Helm 发布已完成", finished_at=time.time())
            self._save()
        observation = self.observe()
        healthy = all(c["state"] == "ready" for c in observation["components"] if c["required"])
        with self.lock:
            ready = healthy and observation["initialization_ready"] and observation["boot_ready"]
            simple = self.current.get("profile") == "helm"
            self.current.update(
                status="ready" if ready else "installed" if simple else "needs_attention",
                error=""
                if ready or simple
                else "Helm 已完成；仍有服务、初始化资源或 Boot HTTP 材料未就绪，请刷新查看。",
            )
            self._save()

    def connect(self, body):
        if (
            not {"id", "confirm"} <= set(body)
            or set(body) - {"id", "confirm", "core_url", "pxe_url"}
            or body["confirm"] is not True
        ):
            raise ValueError("请确认将部署结果应用到站点。")
        with self.lock:
            if self.busy or not self.current or self.current["id"] != body["id"]:
                raise ValueError("部署记录已变化，请刷新。")
            if not all(p["state"] == "ready" for p in self.current["phases"]):
                raise ValueError("部署阶段尚未全部完成。")
            if "core_url" in body or "pxe_url" in body:
                from pxeye.deployment.sources import source_url
                from urllib.parse import urlsplit

                updates = {}
                for key in ("core_url", "pxe_url"):
                    value = source_url(
                        body.get(key, self.current["configuration"].get(key, ""))
                    ).rstrip("/")
                    parsed = urlsplit(value)
                    if parsed.path or (key == "core_url" and parsed.scheme != "https"):
                        raise ValueError("Core 使用 HTTPS，服务地址不带路径。")
                    updates[key] = value
                self.current["configuration"].update(updates)
            if not self.current["configuration"].get("core_url") or not self.current[
                "configuration"
            ].get("pxe_url"):
                raise ValueError("应用到站点前需要填写 Core HTTPS 和 PXE 对外地址。")
            self.busy = True
            self.current.update(status="connecting", error="")
            self._save()

        def work():
            observed = self.observe()
            if (
                not all(c["state"] == "ready" for c in observed["components"] if c["required"])
                or not observed["initialization_ready"]
                or not observed["boot_ready"]
            ):
                raise ValueError("必要服务、初始化资源或 Boot 材料未就绪，未更新站点。")
            self.app.connect_deployed_site(self.current)
            with self.lock:
                self.current.update(status="connected", connected_at=time.time(), error="")
                self._save()
            self._event("客户端身份与 Core API 已验证，站点信息已应用")

        self._background(work)
        return {"status": "accepted", "detail": "正在验证 Core 身份并应用站点信息。"}
