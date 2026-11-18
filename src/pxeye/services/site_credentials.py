"""Presence-only projection and create-only initialization of Core site defaults."""

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

from pxeye.common import atomic_json, digest


FIELDS = {
    "SiteWideBmcRoot": "bmc_password",
    "HostUefi": "host_uefi_password",
    "DpuUefi": "dpu_uefi_password",
}


class SiteCredentials:
    def __init__(self, app):
        self.app = app

    def _status(self):
        reply = self.app.adapter.rpc("GetSiteCredentialReadiness", {})
        items = {}
        for field, state in (
            ("configured", "ready"),
            ("missing", "missing"),
            ("requiresRecovery", "recovery"),
        ):
            for kind in reply.get(field, []):
                if kind not in FIELDS or kind in items:
                    raise ValueError("Core 返回了无法核对的凭据状态。")
                items[kind] = state
        if set(items) != set(FIELDS):
            raise ValueError("Core 没有返回完整的站点凭据状态。")
        recovery = reply.get("recoverySite", False)
        settings = self.app.config.get("site_credentials") or {}
        target = self.app.config.get("core_url", "").rstrip("/")
        bound = bool(target and settings.get("target", "").rstrip("/") == target)
        supplied = bound and bool(settings.get("use_secret"))
        if settings.get("use_secret") and not bound:
            raise ValueError("站点输入 Secret 与当前 Core 不匹配。")
        missing = "missing" in items.values()
        blocked = "recovery" in items.values() or (missing and recovery and not supplied)
        state = "recovery" if blocked else "missing" if missing else "ready"
        return {
            "state": state,
            "items": items,
            "supplied": supplied,
            "recovery_site": recovery,
            "revision": digest(
                [target, self.app.config.get("core_identity_revision"), items, recovery, supplied]
            ),
        }

    def view(self):
        try:
            return self._status()
        except (RuntimeError, ValueError, OSError):
            return {
                "state": "unknown",
                "items": {},
                "detail": "无法核验凭据。请检查 Core 连接、凭据后端及 Core 是否支持站点凭据接口。",
            }

    def last_scan(self):
        try:
            row = self.app.adapter.rpc("GetSiteExplorerLastRun", {}).get("lastRun")
            if not row:
                return {"state": "none"}
            return {
                "state": "success" if row.get("success") else "failed",
                "finished_at": row.get("finishedAt"),
                "category": row.get("failureCategory"),
            }
        except (RuntimeError, ValueError, OSError):
            return {"state": "unknown"}

    def initialize(self, body):
        if (
            not isinstance(body, dict)
            or set(body) != {"confirm", "revision"}
            or body["confirm"] is not True
        ):
            raise ValueError("请先确认本站点的凭据初始化范围。")
        with self.app.connection_lock:
            before = self._status()
            if before["state"] == "ready":
                return before
            if before["state"] != "missing" or body["revision"] != before["revision"]:
                raise ValueError("站点或凭据状态已变化，或需要恢复原有值；请重新核对。")
            request = {"generate_missing": not before["supplied"]}
            if before["supplied"]:
                for kind, field in FIELDS.items():
                    if before["items"][kind] != "missing":
                        continue
                    try:
                        value = (Path("/site-credential-input") / field).read_text()
                    except (OSError, UnicodeError):
                        raise ValueError("站点输入 Secret 缺少所需字段或无法读取。") from None
                    if (
                        not value
                        or len(value.encode()) > 256
                        or any(ord(char) < 32 for char in value)
                    ):
                        raise ValueError("站点输入 Secret 含空值或无效密码。")
                    request[field] = value
            try:
                self.app.adapter.rpc("InitializeSiteCredentials", request)
            except (OSError, ValueError, RuntimeError):
                raise ValueError(
                    "本次初始化未能确认；请刷新核对各项结果，已写入的项不会被覆盖。"
                ) from None
            after = self._status()
            if after["state"] != "ready":
                raise ValueError("凭据尚未全部就绪，请刷新后查看。")
            return after

    def first_connection(self, target):
        settings = self.app.config.get("site_credentials") or {}
        if not (settings.get("new_site") or settings.get("use_secret")) or settings.get(
            "target", ""
        ).rstrip("/") != target.rstrip("/"):
            return
        marker = (
            self.app.adapter.data / "config" / ("site-credential-init-" + digest(target) + ".json")
        )
        with self.app.connection_lock:
            if marker.exists():
                return
            atomic_json(marker, {"at": time.time(), "state": "checking"})
            try:
                status = self._status()
                if status["state"] == "missing":
                    status = self.initialize({"confirm": True, "revision": status["revision"]})
                outcome = status["state"]
            except (OSError, ValueError, RuntimeError):
                outcome = "needs_attention"
            atomic_json(marker, {"at": time.time(), "state": outcome})


def verify_installed():
    from pxeye.clients.core import CoreClient

    root = Path(os.environ.get("CONSOLE_DATA", "/data"))
    config = json.loads(Path(os.environ.get("CONSOLE_CONFIG", "/config/site.json")).read_text())
    for path in (root / "config/deployment-site.json", root / "config/site-settings.json"):
        if path.exists():
            config.update(json.loads(path.read_text()))
    core = CoreClient()
    core.config = config
    core.core_secrets = Path(
        config.get("core_identity_directory", os.environ.get("CONSOLE_SECRETS", "/secrets"))
    )
    status = SiteCredentials(SimpleNamespace(adapter=core, config=config)).view()
    print("SITE_CREDENTIALS", status["state"])
    return status["state"] == "ready"
