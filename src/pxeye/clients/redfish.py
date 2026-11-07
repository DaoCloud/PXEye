"""Transport client with explicit target and authentication inputs."""

import base64
import json
import re
import ssl
import time
import urllib.request
from contextvars import ContextVar
from pxeye.clients.errors import RedfishRequestError

REDFISH_DEADLINE = ContextVar("redfish_deadline", default=None)


class RedfishClient:
    def redfish_read(self, ip, path, credential):
        return self.redfish_request(ip, path, credential)["data"]

    def redfish_request(self, ip, path, credential, *, method="GET", body=None):
        import ipaddress

        ipaddress.IPv4Address(ip)
        if not isinstance(path, str) or not re.fullmatch(r"/redfish/v1(?:/[A-Za-z0-9_.-]+)+", path):
            raise ValueError("BMC 返回了无效的 Redfish 路径。")

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                raise ValueError("BMC 认证读取不接受重定向。")

        context = (
            ssl._create_unverified_context()
            if self.config.get("bmc_accept_self_signed", True)
            else ssl.create_default_context()
        )
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            NoRedirect(),
            urllib.request.HTTPSHandler(context=context),
        )
        auth = base64.b64encode(
            (credential["username"] + ":" + credential["password"]).encode()
        ).decode()
        if method not in ("GET", "OPTIONS", "PATCH", "POST"):
            raise ValueError("不支持的 Redfish 操作。")
        request = urllib.request.Request(
            "https://" + ip + path,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "Basic " + auth, "Content-Type": "application/json"},
        )
        try:
            deadline = REDFISH_DEADLINE.get()
            remaining = deadline - time.monotonic() if deadline is not None else 15
            if remaining <= 0:
                raise TimeoutError("Redfish observation deadline")
            with opener.open(request, timeout=min(15, remaining)) as response:
                raw = response.read(4 * 1024**2 + 1)
                if len(raw) > 4 * 1024**2:
                    raise ValueError("BMC 响应超限。")
                return {
                    "data": json.loads(raw) if raw.strip() else {},
                    "allow": [
                        x.strip().upper() for x in response.headers.get("Allow", "").split(",")
                    ],
                    "status": response.status,
                    "location": response.headers.get("Location", ""),
                }
        except Exception as error:
            raise RedfishRequestError(
                f"BMC {method} 失败（{getattr(error, 'code', type(error).__name__)}）。",
                getattr(error, "code", None),
            ) from None
