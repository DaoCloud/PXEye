"""Observe and explicitly initialize the site's default Flat instance network."""

import base64
import copy
import json
import os
import shutil
import time
import uuid
from pathlib import Path
from threading import RLock
from types import SimpleNamespace

from pxeye.clients.core import CoreClient
from pxeye.clients.process import run
from pxeye.common import atomic_json, digest, value_id
from pxeye.common import atomic_text
from pxeye.deployment.kubernetes import CurrentCluster


DEFAULT_TENANT = "physical-install"
DEFAULT_VPC = "physical-install-flat"


class SiteNetworkContext:
    def __init__(self, app):
        self.app = app
        self.path = app.adapter.data / "config" / "site-network-context.json"

    def _desired(self):
        saved = {}
        persisted = False
        try:
            if self.path.exists():
                saved = json.loads(self.path.read_text())
                persisted = isinstance(saved, dict)
        except (OSError, ValueError, TypeError):
            saved = {}
        return {
            "tenant_organization_id": saved.get("tenant_organization_id") or DEFAULT_TENANT,
            "tenant_name": saved.get("tenant_name") or DEFAULT_TENANT,
            "vpc_name": saved.get("vpc_name") or DEFAULT_VPC,
            "vpc_id": saved.get("vpc_id") or "",
            "persisted": persisted,
        }

    @staticmethod
    def _vpc_id(row):
        return value_id(row.get("id")) or ""

    def _initializer_available(self):
        source = self.app.config.get("site_initializer_source") or {}
        try:
            namespace = source.get("namespace", self.app.nico_deployment.cluster.namespace)
            return bool(
                source.get("client_secret")
                and source.get("ca_secret")
                and self.app.nico_deployment.cluster.get(
                    "secrets", source["client_secret"], namespace
                )
                and self.app.nico_deployment.cluster.get(
                    "secrets", source["ca_secret"], namespace
                )
            )
        except (OSError, RuntimeError, ValueError, KeyError, TypeError):
            return False

    def _observe(self, client=None):
        client = client or self.app.adapter
        wanted = self._desired()
        tenant_reply = client.rpc(
            "FindTenantsByOrganizationIds",
            {"organization_ids": [wanted["tenant_organization_id"]]},
        )
        tenants = [
            row
            for row in tenant_reply.get("tenants", [])
            if row.get("organizationId") == wanted["tenant_organization_id"]
        ]

        if wanted["vpc_id"]:
            ids = [{"value": wanted["vpc_id"]}]
        else:
            found = client.rpc(
                "FindVpcIds",
                {
                    "name": wanted["vpc_name"],
                    "tenant_org_id": wanted["tenant_organization_id"],
                },
            )
            ids = found.get("vpcIds", [])
        vpcs = []
        if ids:
            reply = client.rpc("FindVpcsByIds", {"vpc_ids": ids})
            vpcs = [row for row in reply.get("vpcs", []) if not row.get("deleted")]
        matching_vpcs = [
            row
            for row in vpcs
            if row.get("metadata", {}).get("name") == wanted["vpc_name"]
        ]

        conflict = []
        if len(tenants) > 1:
            conflict.append("租户记录不唯一")
        elif tenants and tenants[0].get("metadata", {}).get("name") not in (
            "",
            wanted["tenant_name"],
        ):
            conflict.append("租户名称与站点默认不一致")
        if len(matching_vpcs) > 1:
            conflict.append("Flat VPC 记录不唯一")
        elif matching_vpcs:
            config = matching_vpcs[0].get("config", {})
            if config.get("networkVirtualizationType") != "FLAT":
                conflict.append("同名 VPC 不是 Flat 类型")
            if config.get("tenantOrganizationId") != wanted["tenant_organization_id"]:
                conflict.append("同名 VPC 属于其他租户")
            if wanted["vpc_id"] and self._vpc_id(matching_vpcs[0]) != wanted["vpc_id"]:
                conflict.append("VPC ID 与站点记录不一致")
        elif vpcs:
            conflict.append("VPC ID 指向的资源名称不一致")

        missing = []
        if not tenants:
            missing.append("tenant")
        if not matching_vpcs:
            missing.append("vpc")
        vpc = matching_vpcs[0] if len(matching_vpcs) == 1 else None
        result = {
            **wanted,
            "vpc_id": self._vpc_id(vpc) if vpc else wanted["vpc_id"],
            "state": "conflict" if conflict else "missing" if missing else "ready",
            "missing": missing,
            "problems": conflict,
            "initializer_available": self._initializer_available(),
            "checked_at": time.time(),
        }
        result["revision"] = digest(
            {
                "core": self.app.config.get("core_url"),
                "identity": self.app.config.get("core_identity_revision"),
            "desired": {k: v for k, v in wanted.items() if k != "persisted"},
                "state": result["state"],
                "missing": missing,
                "problems": conflict,
            }
        )
        return result

    def view(self):
        if not self.app.config.get("core_url"):
            return {"state": "unknown", "detail": "尚未连接 NICo Core。"}
        try:
            result = self._observe()
            if result["state"] == "missing" and not result["initializer_available"]:
                result["detail"] = "实例网络尚未初始化，且部署未提供站点初始化身份。"
            elif result["state"] == "conflict":
                result["detail"] = "；".join(result["problems"])
            return result
        except (OSError, RuntimeError, ValueError, KeyError, TypeError):
            return {
                "state": "unknown",
                "detail": "无法核验站点 Tenant 与 Flat VPC，请检查 Core 连接和读取权限。",
                "checked_at": time.time(),
            }

    def _initializer(self):
        source = copy.deepcopy(self.app.config.get("site_initializer_source") or {})
        if not source:
            raise ValueError("部署未配置站点初始化身份，不能创建 Tenant 或 Flat VPC。")
        directory, _ = self.app._core_identity(source)
        client = CoreClient()
        client.config = self.app.config
        client.core_secrets = Path(directory)
        return client, Path(directory)

    def _persist(self, status):
        record = {
            "tenant_organization_id": status["tenant_organization_id"],
            "tenant_name": status["tenant_name"],
            "vpc_name": status["vpc_name"],
            "vpc_id": status["vpc_id"],
            "updated_at": time.time(),
        }
        atomic_json(self.path, record)
        self.app.config["site_network_context"] = record

    def initialize(self, body):
        if (
            not isinstance(body, dict)
            or set(body) != {"confirm", "revision"}
            or body.get("confirm") is not True
        ):
            raise ValueError("请先确认初始化本站点的默认 Tenant 与 Flat VPC。")
        with self.app.connection_lock:
            before = self._observe()
            if before["state"] == "ready":
                self._persist(before)
                return before
            if before["state"] != "missing" or body["revision"] != before["revision"]:
                raise ValueError("实例网络状态已变化或存在冲突，请刷新后重新核对。")
            client, directory = self._initializer()
            try:
                if "tenant" in before["missing"]:
                    try:
                        client.rpc(
                            "CreateTenant",
                            {
                                "organization_id": before["tenant_organization_id"],
                                "metadata": {"name": before["tenant_name"]},
                            },
                        )
                    except (OSError, RuntimeError, ValueError):
                        observed = self._observe()
                        if "tenant" in observed.get("missing", []):
                            raise ValueError(
                                "Tenant 创建结果无法确认；请刷新状态，确认缺失后再重试。"
                            ) from None
                current = self._observe()
                if current["state"] == "conflict":
                    raise ValueError("Tenant 创建后发现资源冲突，请刷新核对。")
                if "vpc" in current["missing"]:
                    try:
                        client.rpc(
                            "CreateVpc",
                            {
                                "tenantOrganizationId": current["tenant_organization_id"],
                                "metadata": {
                                    "name": current["vpc_name"],
                                    "description": "Default Flat network for physical host installation",
                                },
                                "network_virtualization_type": "FLAT",
                            },
                        )
                    except (OSError, RuntimeError, ValueError):
                        observed = self._observe()
                        if "vpc" in observed.get("missing", []):
                            raise ValueError(
                                "Flat VPC 创建结果无法确认；请刷新状态，确认缺失后再重试。"
                            ) from None
                after = self._observe()
                if after["state"] != "ready":
                    raise ValueError("实例网络尚未就绪，请刷新查看具体状态。")
                self._persist(after)
                return after
            finally:
                shutil.rmtree(directory, ignore_errors=True)


def _installed_config():
    root = Path(os.environ.get("CONSOLE_DATA", "/data"))
    config = json.loads(Path(os.environ.get("CONSOLE_CONFIG", "/config/site.json")).read_text())
    for path in (root / "config/deployment-site.json", root / "config/site-settings.json"):
        if path.exists():
            config.update(json.loads(path.read_text()))
    return root, config


def _initializer_identity(root, cluster, source):
    try:
        namespace = source.get("namespace", cluster.namespace)
        client = cluster.get("secrets", source["client_secret"], namespace)
        ca = cluster.get("secrets", source["ca_secret"], namespace)
    except (KeyError, TypeError):
        raise ValueError("站点初始化身份引用不完整。") from None
    if not client or not ca:
        raise ValueError("站点初始化身份尚未生成。")
    directory = root / "core-identity" / uuid.uuid4().hex
    directory.mkdir(parents=True, mode=0o700)
    values = {
        "client.crt": client["data"][source.get("client_cert_key", "tls.crt")],
        "client.key": client["data"][source.get("client_private_key", "tls.key")],
        "ca.crt": ca["data"][source.get("ca_key", "tls.crt")],
    }
    try:
        for name, value in values.items():
            atomic_text(directory / name, base64.b64decode(value, validate=True).decode())
        certificate = str(directory / "client.crt")
        private_key = str(directory / "client.key")
        root_ca = str(directory / "ca.crt")
        run(["openssl", "x509", "-in", certificate, "-checkend", "300", "-noout"])
        run(
            [
                "openssl",
                "verify",
                "-purpose",
                "sslclient",
                "-CAfile",
                root_ca,
                "-untrusted",
                certificate,
                certificate,
            ]
        )
        if run(["openssl", "x509", "-in", certificate, "-pubkey", "-noout"]) != run(
            ["openssl", "pkey", "-in", private_key, "-pubout"]
        ):
            raise ValueError("站点初始化证书与私钥不匹配。")
        return directory
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise ValueError("站点初始化身份校验失败。") from None


def initialize_new_site():
    """Create only a missing default Tenant/Flat VPC for an explicit new-site install."""
    root, config = _installed_config()
    source = config.get("site_initializer_source") or {}
    if not source:
        print("SITE_NETWORK_CONTEXT missing-initializer")
        return False
    cluster = CurrentCluster(config.get("nico_deployment") or {}, root / "nico-deployment")
    directory = _initializer_identity(root, cluster, source)
    core = CoreClient()
    core.config = config
    core.core_secrets = Path(config.get("core_identity_directory", "/secrets"))
    core.data = root
    app = SimpleNamespace(
        adapter=core,
        config=config,
        connection_lock=RLock(),
        nico_deployment=SimpleNamespace(cluster=cluster),
        _core_identity=lambda _source: (directory, {}),
    )
    service = SiteNetworkContext(app)
    try:
        before = service.view()
        print("SITE_NETWORK_CONTEXT", before.get("state", "unknown"))
        if before.get("state") == "ready":
            return True
        if before.get("state") != "missing":
            return False
        after = service.initialize({"confirm": True, "revision": before["revision"]})
        print("SITE_NETWORK_CONTEXT", after.get("state", "unknown"))
        return after.get("state") == "ready"
    finally:
        shutil.rmtree(directory, ignore_errors=True)
