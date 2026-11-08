"""Same-origin HTTP transport, authentication and safe API errors."""

import hashlib
import hmac
import json
import secrets
import time
import uuid
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit
from pxeye.api.queries import QueryRoutes
from pxeye.api.commands import CommandRoutes
from pxeye.api.errors import failure
from pxeye import __version__


class Handler(QueryRoutes, CommandRoutes, BaseHTTPRequestHandler):
    server_version = "PXEye/" + __version__

    @property
    def app(self):
        return self.server.app

    def respond(self, code, payload, headers=None):
        def public(value):
            if isinstance(value, dict):
                return {
                    k: public(v)
                    for k, v in value.items()
                    if k
                    not in (
                        "login_ref",
                        "password_hash",
                        "bmc_password",
                        "nvos_password",
                        "credentials",
                    )
                }
            if isinstance(value, list):
                return [public(v) for v in value]
            return value

        data = json.dumps(public(payload), ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def session(self):
        try:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            token = cookie["nico_session"].value
        except (KeyError, ValueError):
            return None
        with self.app.store.db() as db:
            row = db.execute(
                "SELECT * FROM sessions WHERE token=? AND expires>?",
                (hashlib.sha256(token.encode()).hexdigest(), time.time()),
            ).fetchone()
            return dict(row) if row else None

    def same_origin(self):
        origin = self.headers.get("Origin")
        return (
            origin is not None
            and urlsplit(origin).netloc == self.headers.get("Host")
            and urlsplit(origin).scheme in ("http", "https")
        )

    def error_response(self, error):
        status, body = failure(
            error,
            method=self.command,
            path=urlsplit(self.path).path,
            request_id=getattr(self, "request_id", None),
        )
        return self.respond(status, body, {"X-Request-ID": body["request_id"]})

    def do_GET(self):
        self.request_id = uuid.uuid4().hex
        try:
            return self.get_request()
        except Exception as error:
            return self.error_response(error)

    def do_POST(self):
        self.request_id = uuid.uuid4().hex
        try:
            path = urlsplit(self.path).path
            if path != "/api/installer-events" and not self.same_origin():
                return self.respond(403, {"error": "请求来源不匹配。"})
            length = int(self.headers.get("Content-Length", "0"))
            if length < 2 or length > (
                2 * 1024 * 1024
                if urlsplit(self.path).path.startswith(
                    ("/api/devices", "/api/device-plans", "/api/equipment")
                )
                else 2 * 1024**2
                if urlsplit(self.path).path == "/api/nico-deployment/preflight"
                else 16384
            ):
                return self.respond(413, {"error": "请求大小超限。"})
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.respond(415, {"error": "请提交 JSON。"})
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("无效请求。")
            path = urlsplit(self.path).path
            if path == "/api/installer-events":
                from pxeye.installation.install_events import receive

                return self.respond(200, receive(self.app.adapter, self.app.store, body))
            if path == "/api/login":
                address = self.client_address[0]
                failures = [t for t in self.app.failures.get(address, []) if t > time.time() - 300]
                if len(failures) >= 8:
                    return self.respond(429, {"error": "登录尝试过多，请稍后重试。"})
                if not isinstance(body.get("password"), str) or not hmac.compare_digest(
                    hashlib.sha256(body["password"].encode()).hexdigest(),
                    self.app.auth["password_sha256"],
                ):
                    self.app.failures[address] = failures + [time.time()]
                    return self.respond(401, {"error": "口令不正确。"})
                self.app.failures.pop(address, None)
                token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
                with self.app.store.db() as db:
                    db.execute(
                        "INSERT INTO sessions VALUES (?,?,?)",
                        (hashlib.sha256(token.encode()).hexdigest(), csrf, time.time() + 28800),
                    )
                return self.respond(
                    200,
                    {"operator": "站点操作员", "csrf": csrf},
                    {
                        "Set-Cookie": "nico_session="
                        + token
                        + "; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800"
                    },
                )
            session = self.session()
            if session is None:
                return self.respond(401, {"error": "请先登录。"})
            if not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), session["csrf"]):
                return self.respond(403, {"error": "会话校验失败，请刷新页面。"})
            return self.dispatch_command(path, body, session)
        except Exception as error:
            return self.error_response(error)

    def log_message(self, fmt, *args):
        # No request bodies, passwords, cookies or CLI arguments.
        print(
            json.dumps(
                {
                    "at": time.time(),
                    "client": self.client_address[0],
                    "method": self.command,
                    "path": urlsplit(self.path).path,
                    "status": args[1],
                    "request_id": getattr(self, "request_id", None),
                }
            ),
            flush=True,
        )

    def do_PUT(self):
        self.request_id = uuid.uuid4().hex
        try:
            from urllib.parse import parse_qs

            path = urlsplit(self.path)
            match = __import__("re").fullmatch(
                r"/api/operating-systems/([a-f0-9-]{36})/content", path.path
            )
            if not self.same_origin():
                return self.respond(403, {"error": "请求来源不匹配。"})
            session = self.session()
            if not session:
                return self.respond(401, {"error": "请先登录。"})
            if not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), session["csrf"]):
                return self.respond(403, {"error": "会话校验失败。"})
            if path.path == "/api/nico-deployment/material":
                from pxeye.deployment.sources import ARCHIVE_LIMIT

                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= ARCHIVE_LIMIT:
                    return self.respond(413, {"error": "部署材料最大 128 MiB。"})
                if self.headers.get("Content-Type") != "application/octet-stream":
                    return self.respond(415, {"error": "请选择 Chart 或部署包文件。"})
                self.connection.settimeout(120)
                filename = parse_qs(path.query).get("filename", ["deployment.tgz"])[0]
                return self.respond(
                    200, self.app.nico_deployment.sources.upload(self.rfile, length, filename)
                )
            if not match:
                return self.respond(404, {"error": "上传接口不存在。"})
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= 8 * 1024**2:
                return self.respond(413, {"error": "上传块最大 8 MiB。"})
            if self.headers.get("Content-Type") != "application/octet-stream":
                return self.respond(415, {"error": "上传块格式无效。"})
            self.connection.settimeout(60)
            offset = int(parse_qs(path.query)["offset"][0])
            return self.respond(
                200, self.app.os_library.chunk(match[1], "operator", offset, self.rfile, length)
            )
        except Exception as error:
            return self.error_response(error)
