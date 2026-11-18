"""Observe Core discovery independently of its startup configuration."""

import copy
import http.client
import ipaddress
import re
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit


def enabled_config(text):
    original = tomllib.loads(text)
    explorer = original.get("site_explorer", {})
    if (
        explorer.get("create_machines") is not False
        or original.get("firmware_global", {}).get("autoupdate") is not False
    ):
        raise ValueError("请先在 Core 站点配置中明确关闭自动建机和固件自动更新。")
    if explorer.get("enabled") is True:
        return text
    section = re.search(r"(?ms)^\s*\[site_explorer\][ \t]*(?:#[^\n]*)?\n(.*?)(?=^\s*\[|\Z)", text)
    if not section:
        raise ValueError("无法识别 Core 的 site_explorer 配置段。")
    block, count = re.subn(r"(?m)^([ \t]*enabled\s*=\s*)false\b", r"\g<1>true", section[1])
    if not count:
        block = "enabled = true\n" + block
    updated = text[: section.start(1)] + block + text[section.end(1) :]
    expected = copy.deepcopy(original)
    expected["site_explorer"]["enabled"] = True
    if tomllib.loads(updated) != expected:
        raise ValueError("无法仅修改站点发现开关。")
    return updated


def metrics(address):
    ip, port = address
    conn = http.client.HTTPConnection(str(ipaddress.ip_address(ip)), port, timeout=2)
    try:
        conn.request("GET", "/metrics", headers={"Accept": "text/plain"})
        response = conn.getresponse()
        if response.status != 200:
            raise ValueError("Core 指标端点不可用。")
        found = {}
        total = 0
        for line in response:
            total += len(line)
            if total > 16 * 1024**2:
                break
            hit = re.fullmatch(
                rb"carbide_site_explorer_(enabled|create_machines)\s+([01])(?:\.0+)?\s*", line
            )
            if hit:
                found[hit[1]] = hit[2] == b"1"
                if len(found) == 2:
                    return found[b"enabled"], found[b"create_machines"]
        raise ValueError("Core 未返回发现指标。")
    finally:
        conn.close()


class SiteExplorer:
    def __init__(self, app):
        self.app = app
        self.cluster = app.nico_deployment.cluster

    def target(self):
        ns = self.app.site_boot_network.namespace()
        hostname = urlsplit(self.app.config.get("core_url") or "").hostname
        if not hostname:
            raise ValueError("尚未连接 NICo Core。")
        services = self.cluster.list("services", ns)

        def matches(service):
            name = service["metadata"]["name"]
            suffix = f"{name}.{ns}.svc"
            return hostname in {
                name,
                f"{name}.{ns}",
                suffix,
                f"{suffix}.cluster.local",
                service["spec"].get("clusterIP"),
            }

        selectors = [s["spec"].get("selector") for s in services if matches(s)]
        if len(selectors) != 1 or not selectors[0]:
            raise ValueError("无法将本站点 Core 地址关联到当前集群的 Service。")
        targets = [
            s
            for s in services
            if s["metadata"]["name"].endswith("-api-metrics")
            and s["spec"].get("selector") == selectors[0]
        ]
        if len(targets) != 1:
            raise ValueError("无法唯一识别本站点 Core 的指标服务。")
        return ns, selectors[0], targets[0]["metadata"]["name"]

    def observe(self, ns, name):
        endpoints = self.cluster.get("endpoints", name, ns) or {}
        targets = set()
        for subset in endpoints.get("subsets", []):
            ports = [p["port"] for p in subset.get("ports", []) if p.get("name") == "http"]
            if len(ports) != 1:
                raise ValueError("Core 指标端口不明确。")
            targets.update(
                (a["ip"], ports[0])
                for a in subset.get("addresses", [])
                if a.get("targetRef", {}).get("kind") == "Pod"
            )
        if not targets or len(targets) > 32:
            raise ValueError("没有可核对的 Core 就绪副本，或副本数超出范围。")
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = set(pool.map(metrics, targets))
        if len(results) != 1:
            raise ValueError("Core 副本的发现开关不一致。")
        return results.pop()

    def view(self):
        try:
            ns, _, name = self.target()
            enabled, auto_create = self.observe(ns, name)
            return {
                "state": "enabled" if enabled else "paused",
                "create_machines": auto_create,
                "checked_at": time.time(),
            }
        except (ValueError, KeyError, OSError, http.client.HTTPException) as error:
            return {"state": "unknown", "detail": str(error), "checked_at": time.time()}

    def enable(self, body):
        if not isinstance(body, dict) or set(body) != {"confirm"} or body["confirm"] is not True:
            raise ValueError("请确认启用本站点发现并滚动更新 Core。")
        ns, selector, name = self.target()
        enabled, auto_create = self.observe(ns, name)
        if auto_create:
            raise ValueError("当前 Core 已启用自动建机，请先核对站点策略。")
        deployments = [
            d
            for d in self.cluster.list("deployments", ns)
            if all(
                d["spec"]["template"]["metadata"].get("labels", {}).get(k) == v
                for k, v in selector.items()
            )
        ]
        if len(deployments) != 1:
            raise ValueError("无法唯一识别本站点 Core Deployment。")
        dep = deployments[0]
        if dep.get("status", {}).get("observedGeneration") != dep["metadata"].get("generation"):
            raise ValueError("Core 更新尚未被控制器确认，请稍后刷新。")
        if dep.get("status", {}).get("updatedReplicas", 0) != dep["spec"].get(
            "replicas", 1
        ) or dep.get("status", {}).get("readyReplicas", 0) != dep["spec"].get("replicas", 1):
            raise ValueError("Core 正在更新或未全部就绪，请稍后刷新。")
        names = {
            v.get("configMap", {}).get("name", "")
            for v in dep["spec"]["template"]["spec"].get("volumes", [])
        }
        maps = [m for m in names if m.endswith("-site-config-files")]
        if len(maps) != 1:
            raise ValueError("无法唯一识别 Core 挂载的站点 ConfigMap。")
        config = self.cluster.get("configmaps", maps[0], ns)
        if not config:
            raise ValueError("未找到 Core 站点配置。")
        data = {
            k: enabled_config(v)
            for k, v in config.get("data", {}).items()
            if k in ("nico-api-site-config.toml", "carbide-api-site-config.toml")
        }
        if not data:
            raise ValueError("找不到可维护的 Core 站点 TOML。")
        changed = any(v != config["data"][k] for k, v in data.items())
        if enabled and not changed:
            return {"status": "enabled"}
        if any(t["status"] in ("running", "queued") for t in self.app.store.incomplete()):
            raise ValueError("存在正在执行或排队的安装任务，请稍后启用。")
        if changed:
            self.cluster.patch(
                "configmaps",
                maps[0],
                {
                    "metadata": {"resourceVersion": config["metadata"]["resourceVersion"]},
                    "data": data,
                },
                ns,
            )
        try:
            self.cluster.patch(
                "deployments",
                dep["metadata"]["name"],
                {
                    "metadata": {"resourceVersion": dep["metadata"]["resourceVersion"]},
                    "spec": {
                        "template": {
                            "metadata": {
                                "annotations": {
                                    "pxeye.io/discovery-enabled-at": str(time.time_ns())
                                }
                            }
                        }
                    },
                },
                ns,
            )
        except ValueError as error:
            raise ValueError(
                f"发现启动配置已保存，但未能发起 Core 更新；请刷新后重试：{error}"
            ) from None
        return {"status": "applying"}
