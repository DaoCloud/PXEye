"""Complete NICo service catalog and Kubernetes readiness projection."""

import re

# These are independent services, not the managers embedded in the Core binary.
CATALOG = (
    ("core", "NICo Core", "控制面", "资源 API 与装机状态机", r"(?:nico|carbide)-api$"),
    ("bmc-proxy", "BMC Proxy", "控制面", "管理控制器代理", r"(?:nico|carbide)-bmc-proxy$"),
    ("dhcp", "DHCP", "网络与引导", "地址分配与 PXE 引导参数", r"(?:nico|carbide)-dhcp$"),
    ("pxe", "PXE / HTTP", "网络与引导", "EFI、Scout、ISO 与安装配置", r"(?:nico|carbide)-pxe$"),
    ("dns", "权威 DNS", "网络与引导", "NICo 主机与租户域名", r"(?:nico|carbide)-dns$"),
    ("resolver", "DNS Resolver", "网络与引导", "内部域转发与外部解析", r"site-resolver$|unbound$"),
    ("ntp", "NTP", "网络与引导", "主机与 DPU 时间同步", r"(?:nico|carbide)-ntp$|chrony$"),
    (
        "hardware-health",
        "Hardware Health",
        "控制面",
        "BMC 硬件健康采集",
        r"(?:nico|carbide)-hardware-health$",
    ),
    ("ssh-console", "SSH Console", "控制面", "BMC 串口访问与日志", r"ssh-console(?:-rs)?$"),
    ("postgres", "PostgreSQL", "基础服务", "NICo 资源与工作流数据", r"(?:postgres|postgresql)$"),
    ("vault", "Vault", "基础服务", "凭据存储与机器证书", r"vault$"),
    ("cert-manager", "cert-manager", "基础服务", "服务证书签发与续期", r"cert-manager$"),
    ("cert-cainjector", "CA Injector", "基础服务", "证书 CA 注入", r"cert-manager-cainjector$"),
    ("cert-webhook", "Certificate Webhook", "基础服务", "证书资源校验", r"cert-manager-webhook$"),
    ("rest-api", "REST API", "REST 与工作流", "REST 资源接口", r"nico-rest-api$"),
    (
        "rest-cert-manager",
        "REST Certificate Manager",
        "REST 与工作流",
        "REST 内部客户端身份",
        r"nico-rest-cert-manager$",
    ),
    ("site-manager", "Site Manager", "REST 与工作流", "站点登记与连接", r"nico-rest-site-manager$"),
    (
        "site-agent",
        "Site Agent",
        "REST 与工作流",
        "站点 Core 与 REST 桥接",
        r"nico-rest-site-agent$",
    ),
    (
        "cloud-worker",
        "Cloud Worker",
        "REST 与工作流",
        "云侧工作流",
        r"cloud-worker$|workflow-cloud$",
    ),
    ("site-worker", "Site Worker", "REST 与工作流", "站点资源同步", r"site-worker$|workflow-site$"),
    (
        "temporal-frontend",
        "Temporal Frontend",
        "REST 与工作流",
        "工作流访问入口",
        r"temporal-frontend$",
    ),
    (
        "temporal-history",
        "Temporal History",
        "REST 与工作流",
        "工作流事件历史",
        r"temporal-history$",
    ),
    (
        "temporal-matching",
        "Temporal Matching",
        "REST 与工作流",
        "工作流任务分派",
        r"temporal-matching$",
    ),
    (
        "temporal-worker",
        "Temporal Worker",
        "REST 与工作流",
        "Temporal 内部任务",
        r"temporal-worker$",
    ),
    ("keycloak", "Keycloak", "REST 与工作流", "REST 用户认证", r"keycloak$"),
    ("machine-a-tron", "Machine-a-Tron", "可选组件", "模拟主机与设备", r"machine-a-tron"),
    ("flow", "NICo Flow", "可选组件", "网络设备任务编排", r"nico-flow$"),
    ("dpf", "DPF", "可选组件", "BlueField DPU 管理", r"dpf.*controller|dpf-operator"),
    ("exchange", "DSX Exchange", "可选组件", "外部设备消息消费", r"dsx-exchange-consumer$"),
    ("postgres-exporter", "Postgres Exporter", "可选组件", "数据库指标", r"postgres-exporter$"),
)
REQUIRED = {row[0] for row in CATALOG if row[2] != "可选组件"}
WORKLOADS = {"Deployment": "deployments", "StatefulSet": "statefulsets", "DaemonSet": "daemonsets"}
RESOURCES = WORKLOADS | {
    "Job": "jobs",
    "Service": "services",
    "Certificate": "certificates",
    "PersistentVolumeClaim": "persistentvolumeclaims",
}


def matches(row, selector):
    metadata = row.get("metadata", {})
    return all(metadata.get("labels", {}).get(k) == v for k, v in selector.items())


def readiness(row, pods=()):
    spec, status = row.get("spec", {}), row.get("status", {})
    kind = row["kind"]
    conditions = {c["type"]: c for c in status.get("conditions", [])}
    if kind == "Job":
        failed = conditions.get("Failed", {}).get("status") == "True"
        done = conditions.get("Complete", {}).get("status") == "True"
        return {
            "state": "failed" if failed else "ready" if done else "starting",
            "ready": int(done),
            "desired": 1,
            "detail": "初始化失败" if failed else "初始化完成" if done else "初始化中",
        }
    if kind == "Certificate":
        ready = conditions.get("Ready", {}).get("status") == "True"
        return {
            "state": "ready" if ready else "starting",
            "ready": int(ready),
            "desired": 1,
            "detail": "证书已签发" if ready else "等待证书签发",
        }
    if kind == "PersistentVolumeClaim":
        ready = status.get("phase") == "Bound"
        return {
            "state": "ready" if ready else "starting",
            "ready": int(ready),
            "desired": 1,
            "detail": "存储已绑定" if ready else "等待存储绑定",
        }
    desired = (
        status.get("desiredNumberScheduled", 0) if kind == "DaemonSet" else spec.get("replicas", 1)
    )
    count = status.get("numberReady", 0) if kind == "DaemonSet" else status.get("readyReplicas", 0)
    observed = status.get("observedGeneration", 0) >= row.get("metadata", {}).get("generation", 1)
    updated = (
        status.get("updatedNumberScheduled", 0)
        if kind == "DaemonSet"
        else status.get("updatedReplicas", 0)
    )
    if kind == "StatefulSet":
        observed = observed and status.get("currentRevision") == status.get("updateRevision")
    ready = desired > 0 and count == desired and updated == desired and observed
    reason = ""
    for pod in pods:
        for c in pod.get("status", {}).get("initContainerStatuses", []) + pod.get("status", {}).get(
            "containerStatuses", []
        ):
            waiting = c.get("state", {}).get("waiting", {})
            terminated = c.get("state", {}).get("terminated", {})
            if waiting.get("reason") in (
                "CrashLoopBackOff",
                "ImagePullBackOff",
                "ErrImagePull",
                "CreateContainerConfigError",
            ):
                reason = waiting["reason"]
            if terminated.get("exitCode", 0):
                reason = f"容器退出 {terminated['exitCode']}"
        if pod.get("status", {}).get("phase") == "Failed":
            reason = "Pod Failed"
    failed = conditions.get("Progressing", {}).get("reason") == "ProgressDeadlineExceeded"
    return {
        "state": "ready" if ready else "failed" if reason or failed else "starting",
        "ready": count,
        "desired": desired,
        "detail": "副本已就绪"
        if ready
        else reason or ("部署超过期限" if failed else "等待调度 / 启动"),
    }


def project(objects, bindings=()):
    workloads = [o for o in objects if o.get("kind") in WORKLOADS]
    pods = [o for o in objects if o.get("kind") == "Pod"]
    services = [o for o in objects if o.get("kind") == "Service"]
    by_id = {b["id"]: b for b in bindings}
    result = []
    for key, name, group, role, pattern in CATALOG:
        binding = by_id.get(key)
        selected = (
            [
                o
                for o in workloads
                if (
                    o["metadata"]["name"] == binding.get("name")
                    and o["metadata"]["namespace"] == binding.get("namespace")
                    and o["kind"] == binding.get("kind")
                )
            ]
            if binding
            else [o for o in workloads if re.search(pattern, o["metadata"]["name"])]
        )
        # Core cert-manager and the REST manager use different identities.
        if not binding and key == "cert-manager":
            selected = [o for o in selected if "rest-cert-manager" not in o["metadata"]["name"]]
        # A simulator's release name may describe its lab rather than the executable.
        if not binding and key == "machine-a-tron":
            selected = [
                o
                for o in workloads
                if re.search(pattern, o["metadata"]["name"])
                or any(
                    c["image"].rsplit("/", 1)[-1].split("@", 1)[0].split(":", 1)[0]
                    == "machine-a-tron"
                    for c in o["spec"]["template"]["spec"].get("containers", [])
                )
            ]
        row = {
            "id": key,
            "name": name,
            "group": group,
            "role": role,
            "required": key in REQUIRED,
            "workloads": [],
            "endpoints": [],
            "images": [],
        }
        for obj in selected:
            ns = obj["metadata"]["namespace"]
            selector = obj["spec"].get("selector", {}).get("matchLabels", {})
            owned_pods = [
                p
                for p in pods
                if p["metadata"]["namespace"] == ns and selector and matches(p, selector)
            ]
            state = readiness(obj, owned_pods)
            row["workloads"].append(
                {"name": obj["metadata"]["name"], "namespace": ns, "kind": obj["kind"], **state}
            )
            containers = obj["spec"]["template"]["spec"]
            row["images"] += [c["image"] for c in containers.get("containers", [])]
            row.setdefault("init_images", []).extend(
                c["image"] for c in containers.get("initContainers", [])
            )
            for service in services:
                svc_selector = service.get("spec", {}).get("selector", {})
                labels = obj["spec"]["template"].get("metadata", {}).get("labels", {})
                if (
                    service["metadata"]["namespace"] == ns
                    and svc_selector
                    and all(labels.get(k) == v for k, v in svc_selector.items())
                ):
                    ports = [
                        f"{p['port']}/{p.get('protocol', 'TCP')}"
                        + (f" → {p['nodePort']}" if p.get("nodePort") else "")
                        for p in service["spec"].get("ports", [])
                    ]
                    row["endpoints"].append(
                        {
                            "name": service["metadata"]["name"],
                            "namespace": ns,
                            "address": service["spec"].get("clusterIP", ""),
                            "ports": ports,
                        }
                    )
        states = [w["state"] for w in row["workloads"]]
        row.update(
            state="missing"
            if not states
            else "failed"
            if "failed" in states
            else "ready"
            if all(s == "ready" for s in states)
            else "starting",
            ready=sum(w["ready"] for w in row["workloads"]),
            desired=sum(w["desired"] for w in row["workloads"]),
        )
        row["images"] = list(dict.fromkeys(row["images"]))
        result.append(row)
    return result
