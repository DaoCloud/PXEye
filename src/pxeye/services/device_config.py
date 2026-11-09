"""Device installation intent; credentials are referenced by immutable private files."""

import copy
import ipaddress
import json
import re
import uuid

from pxeye.clients.process import run
from pxeye.common import sha
from pxeye.common import atomic_json, digest


class DeviceConfig:
    def __init__(self, adapter, resources):
        self.adapter, self.resources = adapter, resources
        self.directory = adapter.data / "config" / "device-intents"

    def get(self, serial):
        from pxeye.services.device_plans import DevicePlans

        saved = DevicePlans(self.adapter, self.resources).get(serial)
        if saved:
            return copy.deepcopy(saved["intent"])
        path = self.directory / (sha(serial) + ".json")
        return json.loads(path.read_text()) if path.exists() else {}

    def save(self, body, proposed=None, validate_only=False):
        if set(body) != {"serial", "revision", "intent"}:
            raise ValueError("设备安装配置字段无效。")
        from pxeye.services.onboarding import Onboarding

        row = (
            proposed
            if proposed is not None
            else Onboarding(self.adapter, None, self.resources).inventory_row(body["serial"])
        )
        old = self.get(body["serial"])
        if digest(old) != body["revision"] and not (not old and body["revision"] == ""):
            raise ValueError("安装配置已变化，请刷新后编辑。")
        intent = copy.deepcopy(body["intent"])
        allowed = {
            "hostname",
            "profile_id",
            "os_id",
            "username",
            "login_mode",
            "password",
            "network_bindings",
        }
        if set(intent) - allowed:
            raise ValueError("未知安装配置字段。")
        if intent.get("hostname") and not re.fullmatch(
            r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", intent["hostname"]
        ):
            raise ValueError("hostname 格式无效。")
        self.validate_networks(intent.get("network_bindings", {}), row)
        if not intent.get("profile_id"):
            if set(intent) != {"network_bindings"}:
                raise ValueError("网络规划独立保存时不能携带安装账户。")
            if not validate_only:
                atomic_json(self.directory / (sha(body["serial"]) + ".json"), intent)
                self.resources.invalidate()
            return {"passed": True} if validate_only else self.public(body["serial"])
        profile = next(
            (
                p
                for p in self.adapter.config.get("first_install_profiles", [])
                if p["id"] == intent.get("profile_id")
            ),
            None,
        )
        if not profile:
            raise ValueError("请选择本站安装方案。")
        if intent.get("os_id"):
            from pxeye.services.os_library import OSLibrary

            OSLibrary(self.adapter).usable(intent["os_id"], profile["architecture"])
        known_device = next(
            (d for d in self.adapter.config.get("devices", []) if d["serial"] == body["serial"]),
            None,
        )
        if known_device and not known_device.get("first_install_profile"):
            raise ValueError("历史专用方案设备请先迁移到通用安装方案；当前只保存原设备声明。")
        username = intent.get("username") or profile["ssh_user"]
        if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", username) or username == "root":
            raise ValueError("请使用有效的普通 OS 登录用户名。")
        mode = intent.get("login_mode", "password")
        if mode not in ("password", "key"):
            raise ValueError("登录方式无效。")
        password = intent.pop("password", "")
        if not isinstance(password, str):
            raise ValueError("密码格式无效。")
        if mode == "password":
            if password:
                if not 8 <= len(password) <= 128 or any(c in password for c in "\n\r\x00"):
                    raise ValueError("OS 密码需为 8–128 字符，不能包含换行。")
                if validate_only:
                    intent["login_ref"] = "validated"
                else:
                    self.save_login(intent, username, password)
            elif old.get("login_mode") == "password" and old.get("username") == username:
                intent["login_ref"] = old["login_ref"]
            else:
                raise ValueError("请为此 OS 登录账户设置密码。")
        intent.update(username=username, login_mode=mode, serial=body["serial"])
        if validate_only:
            return {"passed": True}
        atomic_json(self.directory / (sha(body["serial"]) + ".json"), intent)
        self.resources.invalidate()
        return self.public(body["serial"])

    def prepare_draft(self, incoming, old):
        if not isinstance(incoming, dict) or set(incoming) - {
            "hostname",
            "profile_id",
            "os_id",
            "username",
            "login_mode",
            "password",
            "network_bindings",
            "override_modes",
            "authorized_keys",
            "credential_action",
            "disk_serial",
        }:
            raise ValueError("未知安装规划字段。")
        intent = copy.deepcopy(incoming)
        if intent.get("hostname") and not re.fullmatch(
            r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", intent["hostname"]
        ):
            raise ValueError("hostname 格式无效。")
        modes = intent.get("override_modes")
        if modes is not None:
            from pxeye.services.profiles import OVERRIDABLE

            if (
                not isinstance(modes, dict)
                or set(modes) != set(OVERRIDABLE)
                or any(v not in ("inherit", "override") for v in modes.values())
            ):
                raise ValueError("字段继承/覆盖状态无效。")
        if "authorized_keys" in intent:
            keys = intent["authorized_keys"]
            if not isinstance(keys, list) or any(
                not isinstance(k, str)
                or not re.fullmatch(
                    r"(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp\d+) [A-Za-z0-9+/=]+(?: .*?)?", k
                )
                for k in keys
            ):
                raise ValueError("用户SSH公钥格式无效。")
        if intent.get("disk_serial") and (
            not isinstance(intent["disk_serial"], str)
            or len(intent["disk_serial"]) > 128
            or any(c in intent["disk_serial"] for c in "*?[]\n\r")
        ):
            raise ValueError("系统盘序列号无效。")
        username = intent.get("username", "")
        if username and (
            not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", username) or username == "root"
        ):
            raise ValueError("请使用有效的普通 OS 登录用户名。")
        mode = intent.get("login_mode", "password")
        if mode not in ("password", "key"):
            raise ValueError("登录方式无效。")
        bindings = intent.get("network_bindings", {})
        if not isinstance(bindings, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in bindings.items()
        ):
            raise ValueError("网络规划引用格式无效。")
        password = intent.pop("password", "")
        if not isinstance(password, str):
            raise ValueError("OS 密码格式无效。")
        if password:
            if not 8 <= len(password) <= 128 or any(c in password for c in "\n\r\x00"):
                raise ValueError("OS 密码需为 8–128 字符，不能包含换行。")
            effective_user = username
            if (
                modes is not None
                and modes.get("username") == "inherit"
                and intent.get("profile_id")
            ):
                from pxeye.services.profiles import InstallProfiles

                effective_user = InstallProfiles(self.adapter).get(
                    intent["profile_id"], executable=False
                )["settings"]["username"]
            if not effective_user:
                raise ValueError("设置密码前请填写或继承用户名。")
            self.save_login(intent, effective_user, password)
        elif old.get("login_ref"):
            effective_user = username
            effective_mode = mode
            if modes is not None and intent.get("profile_id"):
                from pxeye.services.profiles import InstallProfiles

                settings = (
                    InstallProfiles(self.adapter)
                    .get(intent["profile_id"], executable=False)
                    .get("settings", {})
                )
                if modes.get("username") == "inherit":
                    effective_user = settings.get("username", "")
                if modes.get("login_mode") == "inherit":
                    effective_mode = settings.get("login_mode", "password")
            cred = json.loads(
                (
                    self.adapter.data
                    / "config"
                    / "logins"
                    / (str(uuid.UUID(old["login_ref"])) + ".json")
                ).read_text()
            )
            if effective_mode == "password" and effective_user == cred["username"]:
                intent["login_ref"] = old["login_ref"]
        action = intent.pop("credential_action", "keep")
        if action not in ("keep", "clear"):
            raise ValueError("凭据动作无效。")
        if action == "clear" or modes is not None and modes.get("credential") == "inherit":
            intent.pop("login_ref", None)
        return intent

    def save_login(self, intent, username, password):
        key = str(uuid.uuid4())
        hashed = run(
            ["openssl", "passwd", "-6", "-stdin"], text=password + "\n", timeout=10
        ).strip()
        atomic_json(
            self.adapter.data / "config" / "logins" / (key + ".json"),
            {"username": username, "password": password, "password_hash": hashed},
        )
        intent["login_ref"] = key

    def validate_networks(self, bindings, row, *, networks=None):
        # References constrain declarations; they do not configure the physical switch.
        if not isinstance(bindings, dict):
            raise ValueError("网卡网络引用格式无效。")
        networks = {n["id"]: n for n in (self.resources.networks() if networks is None else networks)}
        nics = {n.get("mac_address", "").lower(): n for n in row.get("interfaces", [])}
        for mac, key in bindings.items():
            network, nic = networks.get(key), nics.get(mac.lower())
            if not network or not nic:
                raise ValueError("网络引用或网卡 MAC 已变化。")
            is_bmc = nic.get("role") == "host_bmc"
            if network["segment_type"] != ("UNDERLAY" if is_bmc else "HOST_INBAND"):
                raise ValueError("BMC/主机网卡用途与所选网络不匹配。")
            if nic.get("fixed_ip"):
                address = ipaddress.ip_address(nic["fixed_ip"])
                prefixes = [ipaddress.ip_network(p["prefix"]) for p in network["prefixes"]]
                if not any(
                    address in p and address not in (p.network_address, p.broadcast_address)
                    for p in prefixes
                ):
                    raise ValueError("固定 IP 不属于所选网络或为保留地址。")
                if nic.get("fixed_mask") and not any(
                    ipaddress.ip_network("0.0.0.0/" + nic["fixed_mask"]).prefixlen == p.prefixlen
                    for p in prefixes
                    if address in p
                ):
                    raise ValueError("网卡掩码与所选子网不同。")
                gateways = [
                    p.get("gateway")
                    for p in network["prefixes"]
                    if address in ipaddress.ip_network(p["prefix"])
                ]
                if nic.get("fixed_gateway") and nic["fixed_gateway"] not in gateways:
                    raise ValueError("网卡网关与所选子网不同。")

    def public(self, serial):
        row = self.get(serial)
        result = {k: v for k, v in row.items() if k != "login_ref"} | {
            "password_present": bool(row.get("login_ref")),
            "revision": digest(row),
        }
        if row.get("profile_id"):
            from pxeye.services.profiles import InstallProfiles

            try:
                effective = InstallProfiles(self.adapter).resolve(row)
                values = {k: v for k, v in effective["values"].items() if k != "login_ref"}
                result["effective"] = {
                    "values": values,
                    "sources": {
                        ("credential" if k == "login_ref" else k): v
                        for k, v in effective["sources"].items()
                    },
                    "problems": effective["problems"],
                    "password_present": bool(effective["values"].get("login_ref")),
                }
            except (ValueError, OSError):
                result["effective"] = {
                    "values": {},
                    "sources": {},
                    "problems": ["方案或默认凭据暂不可读取"],
                }
        return result

    def bind(self, plan, device):
        intent = self.get(device["serial"])
        if not intent:
            intent = {"profile_id": device.get("first_install_profile")}
        if not intent.get("profile_id"):
            if intent.get("network_bindings"):
                row = next(
                    (
                        r
                        for r in self.resources.planned_inventory()
                        if r["chassis_serial_number"] == device["serial"]
                    ),
                    None,
                )
                if row is None:
                    raise ValueError("设备声明已变化。")
                self.validate_networks(intent["network_bindings"], row)
            return
        row = next(
            (
                r
                for r in self.resources.planned_inventory()
                if r["chassis_serial_number"] == device["serial"]
            ),
            None,
        )
        if row is None:
            raise ValueError("设备声明已变化。")
        self.validate_networks(intent.get("network_bindings", {}), row)
        if intent.get("profile_id") != device.get("first_install_profile"):
            raise ValueError("任务方案与设备保存的方案不同，请先更新设备规划。")
        from pxeye.services.profiles import InstallProfiles

        library = InstallProfiles(self.adapter)
        resolved = library.resolve(intent, require=True)
        values, profile = resolved["values"], resolved["profile"]
        planned_disk = intent.get("disk_serial")
        current_disk = device.get("disk_serial")
        if planned_disk and planned_disk != device.get("disk_serial"):
            plan.update(
                previous_disk_serial=current_disk,
                disk_change=True,
            )
            device["disk_serial"] = planned_disk
        if device.get("disk_serial"):
            plan["disk_serial"] = device["disk_serial"]
        plan.update(intent_revision=digest(self.get(device["serial"])))
        if profile.get("managed"):
            from pxeye.installation.storage_policy import normalize_storage

            device["storage"] = normalize_storage(profile["settings"].get("storage"))
            plan.update(
                profile_revision=resolved["profile_revision"],
                profile_version=profile["version"],
                effective_config=copy.deepcopy(
                    {k: v for k, v in values.items() if k != "login_ref"}
                ),
                effective_sources={
                    ("credential" if k == "login_ref" else k): v
                    for k, v in resolved["sources"].items()
                },
                password_present=bool(values.get("login_ref")),
            )
            device.update(
                profile_revision=resolved["profile_revision"],
                profile_version=profile["version"],
                timezone=values["timezone"],
                dns_checks=values["dns_checks"],
                http_checks=values["http_checks"],
            )
        device.update(
            ssh_user=values["username"],
            login_mode=values["login_mode"],
            login_ref=values.get("login_ref"),
            authorized_keys=values.get("authorized_keys"),
        )
        # Migrated profiles already reference the existing material baseline.
        if values.get("os_id") and (
            values["os_id"] != profile.get("settings", {}).get("os_id")
            or not profile.get("legacy_os", True)
            or (
                self.adapter.data / "config" / "operating-systems" / (values["os_id"] + ".json")
            ).exists()
        ):
            os_record = library.compatible_os(values["os_id"], profile)
            plan.update(os_revision=digest(os_record), os_id=os_record["id"])
            device.update(
                os_id=os_record["id"],
                os_release=os_record["os_release"],
                materials=copy.deepcopy(os_record["materials"]),
            )
