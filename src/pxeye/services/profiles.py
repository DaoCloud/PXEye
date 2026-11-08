"""Versioned installation defaults. Saving profiles never calls hardware APIs."""

import copy
import json
import re
import time
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from pxeye.common import atomic_json, digest
from pxeye.persistence.store import get_store
from pxeye.installation.storage_policy import (
    normalize_storage,
    storage_label,
    selection_label,
    apply_partition_layout,
)
from pxeye.installation.profile_template import apply_offline_install

OVERRIDABLE = ("os_id", "username", "login_mode", "authorized_keys", "credential")


class InstallProfiles:
    def __init__(self, adapter, store=None):
        self.adapter = adapter
        self.store = store or get_store(adapter.data / "console.sqlite3")

    def import_legacy(self):
        """Import initial templates once at application bootstrap, never in list reads."""
        with self.store.db() as db:
            for p in self.adapter.config.get("first_install_profiles", []):
                if db.execute("SELECT 1 FROM install_profiles WHERE id=?", (p["id"],)).fetchone():
                    continue
                path = self.adapter.secrets / p["baseline_file"]
                if not path.exists():
                    continue
                template = json.loads(path.read_text())
                ai = yaml.safe_load(template["user_data"])["autoinstall"]
                settings = {
                    "os_id": (template.get("variant") or {}).get("OperatingSystemId", ""),
                    "username": ai["identity"]["username"],
                    "login_mode": "password" if ai["ssh"].get("allow-pw") else "key",
                    "authorized_keys": ai["ssh"].get("authorized-keys", []),
                    "timezone": ai.get("user-data", {}).get("timezone", p["timezone"]),
                    "ntp": ai.get("user-data", {}).get("ntp", {}).get("servers", []),
                    "packages": ai.get("packages", []),
                    "apt": ai.get("apt", {}),
                    "dns_checks": p.get("dns_checks", []),
                    "http_checks": p.get("http_checks", []),
                    "allow_overrides": dict.fromkeys(OVERRIDABLE, True),
                }
                row = copy.deepcopy(p) | {
                    "managed": True,
                    "family_id": p["id"],
                    "version": 1,
                    "status": "published",
                    "active": True,
                    "description": "",
                    "settings": settings,
                    "template": template,
                    "legacy_os": True,
                    "created_at": time.time(),
                }
                self.put(db, row)

    def rows(self):
        with self.store.db() as db:
            return [json.loads(r["data"]) for r in db.execute("SELECT data FROM install_profiles")]

    def get(self, key, *, executable=True):
        with self.store.db() as db:
            row = db.execute("SELECT data FROM install_profiles WHERE id=?", (key,)).fetchone()
        if not row:
            matches = [
                p for p in self.adapter.config.get("first_install_profiles", []) if p["id"] == key
            ]
            if len(matches) != 1:
                raise ValueError("安装方案不存在。")
            return copy.deepcopy(matches[0])
        p = json.loads(row["data"])
        # Frozen runs may finish after a profile is disabled; new preflights cannot.
        from pxeye.services.device_plans import EXECUTING

        if executable and not EXECUTING.get() and (p["status"] != "published" or not p["active"]):
            raise ValueError("安装方案未发布或已停用，请在设备规划中选择可用版本。")
        return p

    @staticmethod
    def revision(row):
        return digest({k: v for k, v in row.items() if k not in ("checked", "export_error")})

    def public(self, row):
        settings = copy.deepcopy(row["settings"])
        settings.pop("login_ref", None)
        settings.pop("allow_overrides", None)
        settings["storage"] = normalize_storage(settings.get("storage"))
        settings.pop("packages", None)
        settings.pop("apt", None)
        return {
            k: row[k]
            for k in (
                "id",
                "family_id",
                "version",
                "name",
                "description",
                "status",
                "active",
                "architecture",
                "network_mode",
                "os_release",
            )
        } | {
            "settings": settings,
            "ssh_user": settings["username"],
            "revision": self.revision(row),
            "password_present": bool(row["settings"].get("login_ref")),
            "references": self.references(row["id"]),
            "layout": storage_label(settings["storage"]),
            "disk_selection": selection_label(settings["storage"]),
            "boot_mode": "UEFI",
            "software_mode": "offline",
            "validation": row.get("checked"),
            "evidence": "技术配置；实机适用范围以独立安装回执为准",
        }

    def list(self):
        return {
            "profiles": [
                self.public(r)
                for r in sorted(self.rows(), key=lambda r: (r["name"], -r["version"], r["id"]))
            ]
        }

    def selectable(self):
        migrated = {p["id"] for p in self.rows()}
        return [
            self.public(p) for p in self.rows() if p["status"] == "published" and p["active"]
        ] + [
            copy.deepcopy(p)
            for p in self.adapter.config.get("first_install_profiles", [])
            if p["id"] not in migrated
        ]

    def references(self, key):
        with self.store.db() as db:
            devices = [
                r["serial"]
                for r in db.execute("SELECT serial,data FROM device_plans")
                if json.loads(r["data"]).get("intent", {}).get("profile_id") == key
            ]
            tasks = sum(
                json.loads(r["data"]).get("profile") == key
                for r in db.execute("SELECT data FROM tasks")
            )
        return {"devices": devices, "tasks": tasks}

    @staticmethod
    def put(db, row):
        db.execute(
            "INSERT OR REPLACE INTO install_profiles VALUES (?,?)", (row["id"], json.dumps(row))
        )

    def export(self, row):
        # DB is authoritative. Export failure is reported separately.
        try:
            atomic_json(
                self.adapter.data / "config" / "install-profiles" / (digest(row["id"]) + ".json"),
                row,
            )
            return None
        except OSError:
            return "数据库已保存；配置文件导出失败，请检查存储。"

    def normalize(self, config, previous):
        fields = {
            "name",
            "description",
            "os_id",
            "username",
            "login_mode",
            "password",
            "credential_action",
            "authorized_keys",
            "timezone",
            "ntp",
            "packages",
            "apt",
            "dns_checks",
            "http_checks",
            "allow_overrides",
            "storage",
        }
        if not isinstance(config, dict) or set(config) - fields:
            raise ValueError("方案含未知配置。")
        s = copy.deepcopy(previous["settings"])
        name, description = (
            config.get("name", previous["name"]),
            config.get("description", previous.get("description", "")),
        )
        if (
            not isinstance(name, str)
            or not name.strip()
            or len(name) > 100
            or not isinstance(description, str)
            or len(description) > 1000
        ):
            raise ValueError("请填写有效方案名称和说明。")
        for k in fields - {"name", "description", "password", "credential_action"}:
            if k in config:
                s[k] = copy.deepcopy(config[k])
        if s.get("os_id"):
            try:
                s["os_id"] = str(uuid.UUID(s["os_id"]))
            except (ValueError, AttributeError, TypeError):
                raise ValueError("OS版本ID无效。") from None
        if s.get("username") and (
            not isinstance(s["username"], str)
            or not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", s["username"])
            or s["username"] == "root"
        ):
            raise ValueError("请使用有效的普通 OS 用户名。")
        if s["login_mode"] not in ("password", "key"):
            raise ValueError("登录方式无效。")
        try:
            ZoneInfo(s["timezone"])
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            raise ValueError("时区无效。") from None
        for k in ("authorized_keys", "ntp", "packages", "dns_checks", "http_checks"):
            if (
                not isinstance(s[k], list)
                or len(s[k]) > 100
                or any(
                    not isinstance(x, str)
                    or not x
                    or len(x) > 2048
                    or any(c in x for c in "\n\r\x00")
                    for x in s[k]
                )
            ):
                raise ValueError("方案列表字段格式无效：" + k)
        if any(
            not re.fullmatch(
                r"(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp\d+) [A-Za-z0-9+/=]+(?: .*?)?", k
            )
            for k in s["authorized_keys"]
        ):
            raise ValueError("SSH 公钥格式无效。")
        if any(not re.fullmatch(r"[a-z0-9][a-z0-9+.-]*(?::[a-z0-9_]+)?", x) for x in s["packages"]):
            raise ValueError("软件包名称无效。")
        for k in ("ntp", "dns_checks"):
            if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,252}", x) for x in s[k]):
                raise ValueError("域名或地址无效。")
        from urllib.parse import urlsplit

        for x in s["http_checks"]:
            u = urlsplit(x)
            if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
                raise ValueError("检查 URL 必须为不含凭据的 HTTP/HTTPS 地址。")
        # Only a supported APT mirror schema is editable, never arbitrary commands.
        if not isinstance(s["apt"], dict) or set(s["apt"]) - {
            "geoip",
            "preserve_sources_list",
            "primary",
            "security",
        }:
            raise ValueError("APT 只支持镜像源配置。")
        for k in ("geoip", "preserve_sources_list"):
            if k in s["apt"] and not isinstance(s["apt"][k], bool):
                raise ValueError("APT 开关需为布尔值。")
        for k in ("primary", "security"):
            if k in s["apt"]:
                if not isinstance(s["apt"][k], list) or not s["apt"][k]:
                    raise ValueError("APT镜像格式无效。")
                for entry in s["apt"][k]:
                    if (
                        not isinstance(entry, dict)
                        or set(entry) != {"arches", "uri"}
                        or not isinstance(entry["arches"], list)
                        or not entry["arches"]
                        or any(a not in ("default", "amd64", "arm64") for a in entry["arches"])
                    ):
                        raise ValueError("APT镜像格式无效。")
                    u = urlsplit(entry["uri"])
                    if (
                        u.scheme not in ("http", "https")
                        or not u.hostname
                        or u.username
                        or u.password
                    ):
                        raise ValueError("APT镜像地址无效。")
        s["allow_overrides"] = dict.fromkeys(OVERRIDABLE, True)
        s["storage"] = normalize_storage(s.get("storage"))
        # Legacy profile versions may retain online fields in SQLite. They are
        # accepted for compatibility but cannot affect newly rendered tasks.
        s["packages"] = []
        s["apt"] = {}
        password = config.get("password", "")
        if not isinstance(password, str):
            raise ValueError("密码格式无效。")
        action = config.get("credential_action", "keep")
        if action not in ("keep", "clear"):
            raise ValueError("凭据动作无效。")
        if (
            action == "clear"
            or s["username"] != previous["settings"]["username"]
            or s["login_mode"] != previous["settings"]["login_mode"]
        ):
            s.pop("login_ref", None)
        if password:
            if (
                not s["username"]
                or not 8 <= len(password) <= 128
                or any(c in password for c in "\n\r\x00")
            ):
                raise ValueError("先填写用户名；密码需为8–128字符且无换行。")
            from pxeye.services.device_config import DeviceConfig

            DeviceConfig(self.adapter, None).save_login(s, s["username"], password)
        return name.strip(), description, s

    def save(self, body):
        if set(body) != {"id", "revision", "source_id", "config"}:
            raise ValueError("方案保存字段不完整。")
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if body["id"]:
                old = self.get(body["id"], executable=False)
                if old.get("status") != "draft" or body["revision"] != self.revision(old):
                    raise ValueError("只能编辑当前草稿；已发布版本请创建新版本。")
            else:
                source = self.get(body["source_id"], executable=False)
                if not source.get("managed") or source["network_mode"] != "flat":
                    raise ValueError("请选择已支持的通用Flat方案作为基础。")
                old = copy.deepcopy(source)
                old.update(
                    id=str(uuid.uuid4()),
                    family_id=str(uuid.uuid4()),
                    version=1,
                    status="draft",
                    active=False,
                )
                if body["revision"]:
                    raise ValueError("新草稿不能携带旧版本。")
            name, description, settings = self.normalize(body["config"], old)
            row = old | {
                "name": name,
                "description": description,
                "settings": settings,
                "status": "draft",
                "active": False,
                "legacy_os": False,
            }
            row.pop("checked", None)
            self.put(db, row)
        error = self.export(row)
        return self.public(row) | {"export_error": error}

    def new_version(self, body):
        if set(body) != {"id", "revision"}:
            raise ValueError("版本字段无效。")
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = self.get(body["id"], executable=False)
            if old.get("status") != "published" or body["revision"] != self.revision(old):
                raise ValueError("请刷新后从已发布版本创建新版本。")
            versions = [r["version"] for r in self.rows() if r["family_id"] == old["family_id"]]
            row = copy.deepcopy(old) | {
                "id": str(uuid.uuid4()),
                "version": max(versions) + 1,
                "status": "draft",
                "active": False,
                "legacy_os": False,
            }
            row.pop("checked", None)
            self.put(db, row)
        self.export(row)
        return self.public(row)

    def check(self, key):
        p = self.get(key, executable=False)
        s = p["settings"]
        problems = []
        if not s["username"] or not s["os_id"] or not s["ntp"]:
            problems.append("请补齐OS、用户名和NTP服务。")
        os_record = None
        try:
            os_record = self.compatible_os(s["os_id"], p)
            template = self.template(p)
            ai = yaml.safe_load(template["user_data"])["autoinstall"]
            if len([x for x in ai["storage"]["config"] if x["type"] == "disk"]) != 1:
                raise ValueError("安装方案必须仅声明一个系统盘。")
        except (ValueError, RuntimeError, OSError) as error:
            problems.append(str(error))
        return {"passed": not problems, "problems": problems, "os_record": os_record}

    def compatible_os(self, key, profile):
        from pxeye.services.os_library import OSLibrary

        o = OSLibrary(self.adapter).usable(key, profile["architecture"])
        if o.get("installer") != "ubuntu-server":
            raise ValueError("OS与Ubuntu autoinstall方案不兼容，请选择兼容方案。")
        return o

    def action(self, body, action):
        expected = {"id", "revision"} | ({"active"} if action == "active" else set())
        if set(body) != expected:
            raise ValueError("方案操作字段无效。")
        checked = self.check(body["id"]) if action == "publish" else None
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            p = self.get(body["id"], executable=False)
            if self.revision(p) != body["revision"]:
                raise ValueError("方案版本已变化，请刷新。")
            if action == "publish":
                if p["status"] != "draft" or not checked["passed"]:
                    raise ValueError("方案检查未通过：" + "；".join(checked["problems"]))
                o = checked["os_record"]
                p.update(
                    status="published",
                    active=True,
                    os_release=o["os_release"],
                    architecture=o["architecture"],
                    checked={"passed": True, "at": time.time(), "kind": "technical"},
                    os_revision=digest(o),
                )
                p.update(
                    ssh_user=p["settings"]["username"],
                    timezone=p["settings"]["timezone"],
                    dns_checks=p["settings"]["dns_checks"],
                    http_checks=p["settings"]["http_checks"],
                )
            elif action == "active":
                if p["status"] != "published" or not isinstance(body["active"], bool):
                    raise ValueError("仅已发布方案支持启用/停用。")
                p["active"] = body["active"]
            elif action == "delete":
                refs = self.references(p["id"])
                if p["status"] != "draft" or refs["devices"] or refs["tasks"]:
                    raise ValueError("仅无引用草稿可以删除。")
                db.execute("DELETE FROM install_profiles WHERE id=?", (p["id"],))
                path = (
                    self.adapter.data / "config" / "install-profiles" / (digest(p["id"]) + ".json")
                )
                path.unlink(missing_ok=True)
                return {"status": "deleted"}
            self.put(db, p)
        return self.public(p) | {"export_error": self.export(p)}

    def template(self, p):
        s = p["settings"]
        result = copy.deepcopy(p["template"])
        ai = yaml.safe_load(result["user_data"])["autoinstall"]
        old = ai["identity"]["username"]
        ai["identity"].update(username=s["username"], password="!")
        ai["ssh"]["authorized-keys"] = copy.deepcopy(s["authorized_keys"])
        ai["ssh"]["allow-pw"] = s["login_mode"] == "password"
        ai["late-commands"] = [
            c.replace(old + " ALL=", s["username"] + " ALL=") for c in ai.get("late-commands", [])
        ]
        ai["timezone"] = s["timezone"]
        ai.setdefault("user-data", {}).update(
            timezone=s["timezone"], ntp={"enabled": True, "servers": s["ntp"]}
        )
        apply_offline_install(ai)
        if "storage" in s:
            apply_partition_layout(ai, s["storage"])
        result["variant"] = {"OperatingSystemId": s["os_id"]}
        result["user_data"] = "#cloud-config\n" + yaml.safe_dump(
            {"autoinstall": ai}, sort_keys=False
        )
        result["run_provisioning_instructions_on_every_boot"] = False
        return result

    def resolve(self, intent, *, require=False):
        if not intent.get("profile_id"):
            if require:
                raise ValueError("请先在设备规划选择安装方案。")
            return {"values": {}, "sources": {}, "problems": ["尚未选择安装方案"]}
        p = self.get(intent["profile_id"], executable=require)
        if not p.get("managed"):
            return {"values": intent, "sources": {}, "problems": [], "profile": p}
        s = p["settings"]
        modes = intent.get("override_modes")
        if modes is None:
            modes = {k: "override" if intent.get(k) else "inherit" for k in OVERRIDABLE}
            modes["credential"] = "override" if intent.get("login_ref") else "inherit"
        values, sources, problems = {}, {}, []
        for k in OVERRIDABLE:
            mode = modes.get(k, "inherit")
            target = "login_ref" if k == "credential" else k
            values[target] = intent.get(target) if mode == "override" else s.get(target)
            sources[target] = "设备覆盖" if mode == "override" else "方案 v" + str(p["version"])
        values.update(
            timezone=s["timezone"], dns_checks=s["dns_checks"], http_checks=s["http_checks"]
        )
        if require:
            if problems:
                raise ValueError("；".join(problems))
            if (
                not values["username"]
                or values["login_mode"] == "password"
                and not values.get("login_ref")
                or values["login_mode"] == "key"
                and not values.get("authorized_keys")
            ):
                raise ValueError("请补齐最终OS登录账户与密码/公钥。")
            if values.get("login_ref") and values["login_mode"] == "password":
                cred = json.loads(
                    (
                        self.adapter.data
                        / "config"
                        / "logins"
                        / (str(uuid.UUID(values["login_ref"])) + ".json")
                    ).read_text()
                )
                if cred["username"] != values["username"]:
                    raise ValueError("OS凭据与最终用户名不同，请为设备设置密码。")
            if values["os_id"] != s["os_id"] or not p.get("legacy_os"):
                o = self.compatible_os(values["os_id"], p)
                if values["os_id"] == s["os_id"] and p.get("os_revision") != digest(o):
                    raise ValueError("方案引用OS已变化，请发布新版本。")
        return {
            "values": values,
            "sources": sources,
            "problems": problems,
            "profile": p,
            "profile_revision": digest(p["settings"]),
        }
