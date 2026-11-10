"""Transport client with explicit target and authentication inputs."""

import copy
import json
import os
import ssl
import time
from pxeye.clients.process import run
from pxeye.clients.errors import CoreConnectionError


class CoreClient:
    def update_instance_os(self, instance_id, os_config):
        """Use stdin RPC, preserving the CLI's read/modify/version-match semantics."""
        os_config = copy.deepcopy(os_config)
        variant = os_config.pop("variant", None)
        if variant:
            if not isinstance(variant, dict) or len(variant) != 1:
                raise ValueError("安装OS类型无效。")
            name, value = next(iter(variant.items()))
            if name in ("OperatingSystemId", "OsImageId"):
                os_config[
                    "operating_system_id" if name == "OperatingSystemId" else "os_image_id"
                ] = {"value": value}
            elif name == "Ipxe":
                os_config["ipxe"] = value
            else:
                raise ValueError("不支持的安装OS类型。")
        instances = self.rpc("FindInstancesByIds", {"instance_ids": [{"value": instance_id}]}).get(
            "instances", []
        )
        if len(instances) != 1 or instances[0].get("id", {}).get("value") != instance_id:
            raise RuntimeError("无法唯一读取目标Instance，未更新安装配置。")
        instance = instances[0]
        config, metadata = (
            copy.deepcopy(instance.get("config")),
            copy.deepcopy(instance.get("metadata")),
        )
        version = instance.get("configVersion")
        if not isinstance(config, dict) or not isinstance(metadata, dict) or not version:
            raise RuntimeError("Instance缺少配置、元数据或版本，未更新安装配置。")
        config["os"] = os_config
        metadata["labels"] = [
            label
            for label in metadata.get("labels", [])
            if label.get("key") not in ("cloud-unsafe-op", "admin-cli-last-modified-by")
        ] + [
            {"key": "cloud-unsafe-op"},
            {
                "key": "admin-cli-last-modified-by",
                "value": self.config.get("unsafe_operation_reason", "PXEye OS installation"),
            },
        ]
        # A concurrent modification fails rather than replaying a potentially sent write.
        return self.rpc(
            "UpdateInstanceConfig",
            {
                "instance_id": {"value": instance_id},
                "if_version_match": version,
                "config": config,
                "metadata": metadata,
            },
        )

    def check_core_certificate(self):
        path = self.core_secrets / "client.crt"
        try:
            info = path.stat()
            revision = (info.st_ino, info.st_mtime_ns, info.st_size)
            if getattr(self, "_core_certificate_revision", None) != revision:
                dates = run(["openssl", "x509", "-in", str(path), "-dates", "-noout"], timeout=3)
                parsed = dict(line.split("=", 1) for line in dates.splitlines() if "=" in line)
                validity = tuple(
                    ssl.cert_time_to_seconds(parsed[k]) for k in ("notBefore", "notAfter")
                )
                self._core_certificate_validity = validity
                self._core_certificate_revision = revision
            start, end = self._core_certificate_validity
        except (OSError, ValueError, KeyError, RuntimeError):
            raise CoreConnectionError(
                "NICo 客户端证书无法读取，请检查控制台证书配置。", "core_certificate_invalid"
            ) from None
        now = time.time()
        if now >= end:
            raise CoreConnectionError(
                "NICo 客户端证书已过期，请检查证书续期同步后刷新。", "core_certificate_expired"
            )
        if now < start:
            raise CoreConnectionError(
                "NICo 客户端证书尚未生效，请检查服务端时间与证书配置。",
                "core_certificate_not_yet_valid",
            )

    def core(self, args, *, data=False):
        self.check_core_certificate()
        base = [
            self.config.get("cli", "/usr/local/bin/nico-admin-cli"),
            "-a",
            self.config["core_url"],
            "--root-ca-path",
            str(self.core_secrets / "ca.crt"),
            "--client-cert-path",
            str(self.core_secrets / "client.crt"),
            "--client-key-path",
            str(self.core_secrets / "client.key"),
        ]
        if data:
            base += ["-f", "json"]
        env = {
            k: v
            for k, v in os.environ.items()
            if k.lower() not in ("http_proxy", "https_proxy", "all_proxy")
        }
        output = run(base + args, timeout=60, env=env)
        return json.loads(output) if data else output

    def rpc(self, method, body):
        self.check_core_certificate()
        endpoint = self.config["core_url"].removeprefix("https://")
        env = {
            k: v
            for k, v in os.environ.items()
            if k.lower() not in ("http_proxy", "https_proxy", "all_proxy")
        }
        argv = [
            self.config.get("grpcurl", "/usr/local/bin/grpcurl"),
            "-connect-timeout",
            "5",
            "-max-time",
            "45",
            "-cacert",
            str(self.core_secrets / "ca.crt"),
            "-cert",
            str(self.core_secrets / "client.crt"),
            "-key",
            str(self.core_secrets / "client.key"),
            "-d",
            "@",
            endpoint,
            "forge.Forge/" + method,
        ]
        return json.loads(run(argv, text=json.dumps(body), timeout=55, env=env))
