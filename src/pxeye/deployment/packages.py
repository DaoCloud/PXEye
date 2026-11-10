"""Versioned, local-only Helm deployment packages with complete component bindings."""

import copy
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from pxeye.common import digest
from pxeye.deployment.components import REQUIRED, RESOURCES

TOKEN = re.compile(r"@\{([a-z_]+)\}")
NAME = re.compile(r"[a-z][a-z0-9-]{0,47}[a-z0-9]|[a-z]")
INPUTS = {"site_name", "release_prefix", "namespace", "core_url", "pxe_url"}


def substitute(value, settings):
    if isinstance(value, str):
        return TOKEN.sub(lambda m: str(settings[m[1]]) if m[1] in settings else m[0], value)
    if isinstance(value, dict):
        return {k: substitute(v, settings) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, settings) for v in value]
    return value


def configuration(body, namespace):
    if "mode" in body:
        from pxeye.deployment.sources import source_url

        fields = {
            "mode",
            "package_id",
            "site_name",
            "release_prefix",
            "core_url",
            "pxe_url",
            "source_type",
            "chart_source",
            "repository_url",
            "chart_version",
            "values_yaml",
            "timeout_seconds",
            "client_secret",
            "ca_secret",
            "architecture",
        }
        if set(body) - fields or body.get("mode") not in ("online", "offline"):
            raise ValueError("部署方式或字段无效。")
        values = {k: str(body.get(k, "")).strip() for k in fields - {"timeout_seconds"}}
        if not NAME.fullmatch(values["release_prefix"]):
            raise ValueError(
                "Helm 发布名使用小写字母、数字和连字符，以字母开头，最长 49 字符。"
            )
        if not 1 <= len(values["site_name"]) <= 100:
            raise ValueError("请填写站点名称，最长 100 字符。")
        try:
            timeout = int(body.get("timeout_seconds", 900))
        except (TypeError, ValueError):
            raise ValueError("部署超时应为 60–1800 秒。") from None
        if not 60 <= timeout <= 1800 or len(values["values_yaml"].encode()) > 1024**2:
            raise ValueError("部署超时应为 60–1800 秒，values 不超过 1 MiB。")
        try:
            parsed_values = yaml.safe_load(values["values_yaml"] or "{}")
        except yaml.YAMLError:
            raise ValueError("values YAML 格式错误，请检查缩进和字段。") from None
        if not isinstance(parsed_values, dict):
            raise ValueError("values 应为 YAML 对象。")
        values["architecture"] = values["architecture"] or "both"
        if values["architecture"] not in ("x86_64", "aarch64", "both"):
            raise ValueError("请选择 x86_64、aarch64 或双架构引导材料。")
        for key in ("client_secret", "ca_secret"):
            if values[key] and not NAME.fullmatch(values[key]):
                raise ValueError("客户端和 CA Secret 名称格式无效。")
        if values["mode"] == "online":
            if values["source_type"] not in ("url", "repository", "oci"):
                raise ValueError("请选择在线 Chart 来源类型。")
            if values["source_type"] == "repository":
                values["repository_url"] = source_url(values["repository_url"])
                if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._/-]{0,199}", values["chart_source"]):
                    raise ValueError("请填写仓库中的 Chart 名称。")
            else:
                values["chart_source"] = source_url(
                    values["chart_source"], oci=values["source_type"] == "oci"
                )
                if values["source_type"] == "oci" and not values["chart_source"].startswith(
                    "oci://"
                ):
                    raise ValueError("OCI Chart 使用 oci:// 地址。")
            if values["chart_version"] and not re.fullmatch(
                r"[a-zA-Z0-9][a-zA-Z0-9.+_-]{0,79}", values["chart_version"]
            ):
                raise ValueError("Chart 版本格式无效。")
        elif not values["package_id"]:
            raise ValueError("请上传并选择离线 Chart 或部署包。")
        for field in ("core_url", "pxe_url"):
            if values[field]:
                values[field] = source_url(values[field]).rstrip("/")
                if urlsplit(values[field]).path or (
                    field == "core_url" and not values[field].startswith("https://")
                ):
                    raise ValueError("Core 使用 HTTPS；服务地址不带路径。")
        return values | {"namespace": namespace, "timeout_seconds": timeout}
    if set(body) != {"package_id", "site_name", "release_prefix", "core_url", "pxe_url"}:
        raise ValueError("部署配置字段无效。")
    values = {k: str(v).strip() for k, v in body.items()}
    if not 1 <= len(values["site_name"]) <= 100:
        raise ValueError("站点名称应为 1–100 个字符。")
    if not NAME.fullmatch(values["release_prefix"]):
        raise ValueError("发布名前缀使用小写字母、数字和连字符，最长 49 个字符。")
    for field, schemes in (("core_url", ("https",)), ("pxe_url", ("http", "https"))):
        url = urlsplit(values[field])
        try:
            port = url.port
        except ValueError:
            raise ValueError("服务端口无效。") from None
        if (
            url.scheme not in schemes
            or not url.hostname
            or url.username
            or url.password
            or url.path not in ("", "/")
            or url.query
            or url.fragment
            or port == 0
        ):
            raise ValueError(
                "Core 使用 HTTPS，PXE 使用 HTTP 或 HTTPS；请填写不带路径的完整服务地址。"
            )
        values[field] = values[field].rstrip("/")
    return values | {"namespace": namespace}


class Packages:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def path(self, package_id):
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}", package_id):
            raise ValueError("部署包标识无效。")
        path = (self.root / package_id).resolve()
        if path.parent != self.root or not (path / "deployment.json").is_file():
            raise ValueError("部署材料不存在，请重新选择或上传。")
        return path

    @staticmethod
    def file(root, relative):
        if not isinstance(relative, str) or Path(relative).is_absolute():
            raise ValueError("部署包只允许内部相对文件路径。")
        path = (root / relative).resolve()
        if (
            not path.is_relative_to(root)
            or not path.is_file()
            or path.stat().st_size > 64 * 1024**2
        ):
            raise ValueError("部署文件缺失、越界或超过 64 MiB。")
        return path

    def list(self):
        result = []
        for path in sorted(self.root.glob("*/deployment.json")):
            try:
                manifest = json.loads(path.read_text())
                result.append(
                    {
                        "id": path.parent.name,
                        "name": manifest["name"],
                        "version": manifest["version"],
                        "description": manifest.get("description", ""),
                        "phases": len(manifest.get("phases", [])),
                        "defaults": manifest.get("defaults", {}),
                        "valid": True,
                    }
                )
            except (ValueError, KeyError, OSError):
                result.append(
                    {
                        "id": path.parent.name,
                        "name": path.parent.name,
                        "version": "—",
                        "valid": False,
                        "description": "部署包描述文件无效",
                    }
                )
        return result

    def load(self, settings):
        root = self.path(settings["package_id"])
        manifest = json.loads((root / "deployment.json").read_text())
        if manifest.get("schema_version") != 1:
            raise ValueError("部署包格式版本不受支持。")
        files = manifest.get("files", {})
        if not files or len(files) > 256:
            raise ValueError("部署包必须提供文件 SHA256，最多 256 个文件。")
        for relative, expected in files.items():
            path = self.file(root, relative)
            if (
                not re.fullmatch(r"[a-f0-9]{64}", str(expected))
                or hashlib.sha256(path.read_bytes()).hexdigest() != expected
            ):
                raise ValueError(f"部署包文件摘要不符：{relative}。")
        phases = manifest.get("phases", [])
        if not 1 <= len(phases) <= 16:
            raise ValueError("部署包需要 1–16 个按依赖排序的 Helm 阶段。")
        seen = set()
        releases = set()
        for phase in phases:
            if not NAME.fullmatch(phase["id"]) or phase["id"] in seen:
                raise ValueError("部署阶段标识无效或重复。")
            seen.add(phase["id"])
            release = substitute(phase["release"], settings)
            if not NAME.fullmatch(release) or release in releases:
                raise ValueError("Helm 发布名无效或重复；请缩短发布名前缀。")
            releases.add(release)
            for relative in [phase["chart"]] + phase.get("values", []):
                if relative not in files:
                    raise ValueError("Chart 和 values 必须列入文件摘要表。")
            chart = self.file(root, phase["chart"])
            if not chart.name.endswith(".tgz"):
                raise ValueError("部署 Chart 必须是已包含依赖的本地 .tgz 文件。")
            if not 60 <= phase.get("timeout_seconds", 600) <= 1800:
                raise ValueError("每个阶段的超时应为 60–1800 秒。")
        bindings = substitute(manifest.get("components", []), settings)
        simple = manifest.get("profile") == "helm"
        if not simple and not REQUIRED <= {b["id"] for b in bindings}:
            raise ValueError(
                "部署包未覆盖完整 NICo 服务，请补齐 Core、网络、基础服务和 REST/工作流。"
            )
        if len({b["id"] for b in bindings}) != len(bindings):
            raise ValueError("服务映射标识重复。")
        for binding in bindings:
            if (
                binding["kind"] not in RESOURCES
                or binding["phase"] not in seen
                or not binding["name"]
            ):
                raise ValueError("服务映射的类型、名称或阶段无效。")
            if binding["namespace"] != settings["namespace"] and not binding.get("external"):
                raise ValueError(
                    "应用服务必须部署在当前指定命名空间；共享组件须显式声明 external。"
                )
        if not simple and not {"core", "rest", "temporal", "vault"} <= set(
            manifest.get("initialization", {})
        ):
            raise ValueError("部署包必须声明 Core、REST、Temporal 和 Vault 初始化所在阶段。")
        if not set(manifest["initialization"].values()) <= seen:
            raise ValueError("初始化引用了不存在的部署阶段。")
        credentials = substitute(manifest["connection"], settings)
        if credentials.get("namespace", settings["namespace"]) != settings["namespace"]:
            raise ValueError("Core 客户端身份必须由本部署的命名空间提供。")
        checks = substitute(manifest.get("boot_checks", []), settings)
        if not simple and (
            not checks or any(c.get("architecture") not in ("x86_64", "aarch64") for c in checks)
        ):
            raise ValueError("部署包必须声明 x86_64 / aarch64 引导材料 HTTP 检查。")
        return {
            "root": root,
            "manifest": manifest,
            "bindings": bindings,
            "connection": credentials,
            "boot_checks": checks,
            "revision": digest({"manifest": manifest, "settings": settings}),
        }

    def values(self, package, phase, settings):
        output = []
        for relative in phase.get("values", []):
            values = yaml.safe_load(self.file(package["root"], relative).read_text())
            if not isinstance(values, dict):
                raise ValueError("Helm values 应为 YAML 对象。")
            values = substitute(copy.deepcopy(values), settings)
            if TOKEN.search(json.dumps(values)):
                raise ValueError("Helm values 存在未填写的部署变量。")
            output.append(values)
        return output
