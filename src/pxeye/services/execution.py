"""Core mTLS, authenticated Redfish, and strict SSH adapters; no browser credentials."""

import base64
import copy
import json
import os
import re
import shlex
import shutil
import ssl
import time
import urllib.request
from pathlib import Path

import yaml
from pxeye.clients.core import CoreClient
from pxeye.clients.redfish import RedfishClient
from pxeye.clients.ssh import SSHClient
from pxeye.clients.process import run
from pxeye.installation.storage_policy import scout_disks, select_disk
from pxeye.installation.scripts import script_source
from pxeye.common import sha, atomic_json


class Adapter(CoreClient, RedfishClient, SSHClient):
    def __init__(self, config, secret_dir, data_dir):
        self.config = config
        self.resources = self.device_config = self.profiles = None
        self.secrets = Path(secret_dir)
        self.core_secrets = Path(config.get("core_identity_directory", secret_dir))
        self.data = Path(data_dir)
        self.identity = self.data / "identity"
        self.identity.mkdir(mode=0o700, parents=True, exist_ok=True)
        if (self.secrets / "ssh_key").is_file():
            shutil.copyfile(self.secrets / "ssh_key", self.identity / "ssh_key")
        elif not (self.identity / "ssh_key").exists():
            from pxeye.clients.process import run

            run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(self.identity / "ssh_key")])
        (self.identity / "ssh_key").chmod(0o600)

    def device(self, serial, *, bind_intent=True):
        devices = list(self.config.get("devices", []))
        saved_device = self.data / "config" / "execution" / (sha(serial) + ".json")
        if saved_device.exists() and not any(d["serial"] == serial for d in devices):
            devices.append(json.loads(saved_device.read_text()))
        for device in devices:
            if serial == device["serial"]:
                current = copy.deepcopy(device)
                bmc_record = self.data / "config" / "bmc-addresses" / (sha(serial) + ".json")
                if bmc_record.exists():
                    address = json.loads(bmc_record.read_text())
                    if (
                        address.get("status") == "verified"
                        and address.get("current_ip")
                        and address.get("bmc_mac") == current.get("bmc_mac", "").lower()
                    ):
                        current["bmc_ip"] = address["current_ip"]
                saved = self.identity / (serial + ".connection.json")
                if saved.exists():
                    state = json.loads(saved.read_text())
                    if (
                        state["instance_id"] != device["instance_id"]
                        or state["boot_mac"].lower() != device["boot_mac"].lower()
                    ):
                        raise RuntimeError("已保存连接身份与执行配置不一致。")
                    current.update({k: state[k] for k in ("management_ip", "prefixlen", "gateway")})
                if bind_intent and current.get("first_install_profile"):
                    config = self.device_config
                    if config is None:
                        raise RuntimeError("执行服务尚未绑定设备规划解析器。")
                    wanted = config.get(serial).get("profile_id")
                    if wanted and wanted != current["first_install_profile"]:
                        profile = self.profiles.get(wanted)
                        if not profile or profile["architecture"] != current["architecture"]:
                            raise ValueError("新的安装方案不存在或与设备架构不兼容。")
                        current.update(
                            {
                                k: profile[k]
                                for k in (
                                    "architecture",
                                    "os_release",
                                    "ssh_user",
                                    "dns",
                                    "timezone",
                                    "dns_checks",
                                    "http_checks",
                                    "baseline_file",
                                )
                            }
                        )
                        current.update(profile=wanted, first_install_profile=wanted)
                        for k in ("os_id", "materials", "login_ref", "login_mode"):
                            current.pop(k, None)
                    config.bind({}, current)
                return current
        raise ValueError("设备未登记到本服务允许的执行范围。")

    def remember_connection(self, device, task):
        atomic_json(
            self.identity / (device["serial"] + ".connection.json"),
            {
                k: device[k]
                for k in ("management_ip", "prefixlen", "gateway", "instance_id", "boot_mac")
            }
            | {"task_id": task["id"]},
        )
        if device.get("first_install_profile"):
            atomic_json(
                self.data / "config" / "execution" / (sha(device["serial"]) + ".json"), device
            )

    def credentials(self, device):
        if device.get("credential_source") == "managed":
            if device.get("bmc_retain_credentials"):
                return self.credentials(device | {"credential_source": "expected"})
            filename = self.config.get("bmc_site_credential_file")
            if not filename:
                raise RuntimeError(
                    "此设备会轮换 BMC 凭据；站点尚未配置轮换后的 BMC 凭据文件。请在接管前配置，或明确选择保留 BMC 凭据。"
                )
            try:
                cred = json.loads((self.secrets / filename).read_text())
            except (OSError, ValueError):
                raise RuntimeError("站点 BMC 凭据文件缺失、不可读取或格式无效。") from None
            if not cred.get("username") or not cred.get("password"):
                raise RuntimeError("站点 BMC 凭据文件缺少用户名/密码。")
            return cred
        if device.get("credential_source") == "expected":
            if self.resources is None:
                raise RuntimeError("执行服务尚未绑定资源读取器。")
            matches = [
                r
                for r in self.resources.inventory()
                if r["id"] == device["expected_id"]
                and r["bmc_mac_address"].lower() == device["bmc_mac"].lower()
            ]
            if len(matches) != 1:
                raise RuntimeError("BMC 凭据与设备登记不匹配。")
            return {"username": matches[0]["bmc_username"], "password": matches[0]["bmc_password"]}
        return json.loads((self.secrets / device["bmc_credential_file"]).read_text())

    def installation_plan(self, serial):
        if self.resources is None:
            raise RuntimeError("执行服务尚未绑定规划解析器。")
        return self.resources.execution_plan(serial)

    def target_device(self, serial, plan):
        return self.device(serial) | {
            k: plan[k] for k in ("management_ip", "prefixlen", "gateway", "boot_mac")
        }

    def assign_install_address(self, plan):
        """Only the confirmed executor calls this once; a timeout is not replayed."""
        result = self.rpc(
            "AssignStaticAddress",
            {"interface_id": {"value": plan["interface_id"]}, "ip_address": plan["management_ip"]},
        )
        if (
            result.get("ipAddress") != plan["management_ip"]
            or result.get("interfaceId", {}).get("value") != plan["interface_id"]
        ):
            raise RuntimeError("NICo 固定地址写入回执不匹配，请核对现场。")
        addresses = self.core(
            ["machine-interfaces", "show-addresses", plan["interface_id"]], data=True
        )
        if not any(
            a["address"] == plan["management_ip"] and a["allocation_type"].lower() == "static"
            for a in addresses
        ):
            raise RuntimeError("NICo 固定地址读回不匹配，停止启动。")
        return {"assignment": result, "addresses": addresses}

    def verify_install_delivery(self, device, task):
        """The boot address must select this Instance and its frozen installer data."""
        instance = self.instance(device)
        os_config = instance.get("config", {}).get("os", {})
        if (
            instance.get("machine_id") != device["machine_id"]
            or sha(os_config.get("user_data", "")) != task["user_data_sha256"]
        ):
            raise RuntimeError("安装配置与原 Instance 不一致，未发送 PXE。")
        links = [
            n
            for n in instance.get("status", {}).get("network", {}).get("interfaces", [])
            if n.get("mac_address", "").lower() == device["boot_mac"].lower()
            and n.get("virtual_function_id") is None
        ]
        if len(links) != 1 or device["management_ip"] not in links[0].get("addresses", []):
            raise RuntimeError(
                "NICo 主启动地址与 Instance 地址未同步；安装器将无法获取自动安装配置。请修复地址关联后继续原任务，未发送 PXE。"
            )
        addresses = self.core(
            ["machine-interfaces", "show-addresses", task["installation_plan"]["interface_id"]],
            data=True,
        )
        if not any(n.get("address") == device["management_ip"] for n in addresses):
            raise RuntimeError("NICo 主启动接口未持有本次安装地址，未发送 PXE。")
        return {
            "instance_id": instance["id"],
            "management_ip": device["management_ip"],
            "boot_mac": device["boot_mac"],
            "user_data_sha256": task["user_data_sha256"],
        }

    def instance(self, device):
        result = self.core(["instance", "show"], data=True)
        matches = [x for x in result["instances"] if x["id"] == device["instance_id"]]
        if len(matches) != 1:
            raise RuntimeError("未找到唯一匹配的既有 Instance。")
        return matches[0]

    def machine(self, device):
        matches = [
            x
            for x in self.core(["machine", "show"], data=True)["machines"]
            if x["id"] == device["machine_id"]
        ]
        if len(matches) != 1 or matches[0].get("bmc_info", {}).get("ip") != device["bmc_ip"]:
            raise RuntimeError("Machine 与登记 BMC 身份不匹配。")
        return matches[0]

    def redfish(self, device, suffix="", method="GET", body=None):
        cred = self.credentials(device)
        context = (
            ssl._create_unverified_context()
            if device.get("bmc_accept_self_signed")
            else ssl.create_default_context()
        )
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context)
        )
        # The URL and paths come from operator configuration, never HTTP request bodies.
        auth = base64.b64encode((cred["username"] + ":" + cred["password"]).encode()).decode()
        req = urllib.request.Request(
            "https://" + device["bmc_ip"] + device["redfish_system"] + suffix,
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={"Authorization": "Basic " + auth, "Content-Type": "application/json"},
        )
        try:
            with opener.open(req, timeout=25) as response:
                raw = response.read()
                return json.loads(raw) if raw.strip() else {}
        except Exception as error:
            raise RuntimeError(
                f"Redfish {method} 失败（{getattr(error, 'code', type(error).__name__)}）。"
            ) from None

    def login_credential(self, device):
        key = str(__import__("uuid").UUID(device["login_ref"]))
        return json.loads((self.data / "config" / "logins" / (key + ".json")).read_text())

    def verify_password_login(self, device, known):
        credential = self.login_credential(device)
        env = dict(os.environ, SSHPASS=credential["password"])
        result = run(
            [
                "sshpass",
                "-e",
                "ssh",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                "ConnectTimeout=5",
                "-o",
                "PreferredAuthentications=password",
                "-o",
                "PubkeyAuthentication=no",
                "-o",
                "UserKnownHostsFile=" + str(known),
                device["ssh_user"] + "@" + device["management_ip"],
                "id -un",
            ],
            timeout=20,
            env=env,
        ).strip()
        if result != device["ssh_user"]:
            raise RuntimeError("OS SSH 密码登录返回账户不匹配。")

    def host_snapshot(self, device, known=None):
        script = """import json,subprocess
from pathlib import Path
def cmd(a):return subprocess.check_output(a,text=True,timeout=20).strip()
root=json.loads(cmd(['findmnt','-J','/']))['filesystems'][0]
print(json.dumps({'serial':Path('/sys/class/dmi/id/product_serial').read_text().strip(),
 'hostname':cmd(['hostname']),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
 'root_uuid':cmd(['blkid','-s','UUID','-o','value',root['source']]),
 'esp_partuuid':cmd(['blkid','-s','PARTUUID','-o','value',cmd(['findmnt','-no','SOURCE','/boot/efi'])]),
 'root_parent':cmd(['lsblk','-no','PKNAME',root['source']]),
 'disks':json.loads(cmd(['lsblk','-J','-o','NAME,TYPE,FSTYPE,WWN,SERIAL,MOUNTPOINTS']))['blockdevices'],
 'host_key':Path('/etc/ssh/ssh_host_ed25519_key.pub').read_text().strip(),
 'interfaces':json.loads(cmd(['ip','-j','address']))}))
"""
        host = json.loads(self.ssh(device, script, known=known))
        if host["serial"] != device["serial"]:
            raise RuntimeError("SSH 返回的主机 SN 与登记不匹配。")
        if device.get("disk_serial"):
            resolver = (
                script_source("disk_identity.py")
                + "\nprint(resolve_disk("
                + repr(device["disk_serial"])
                + ").resolve().name)\n"
            )
            target_name = self.ssh(device, resolver, known=known).strip()
            disks = [x for x in host["disks"] if x["name"] == target_name]
        else:
            disks = [x for x in host["disks"] if x.get("wwn") == device["disk_wwn"]]
        if len(disks) != 1 or disks[0]["name"] != host["root_parent"]:
            raise RuntimeError("当前根系统未位于登记的目标系统盘。")
        return host

    def baseline(self, device):
        os_config = json.loads((self.secrets / device["baseline_file"]).read_text())
        if device.get("first_install_profile"):
            library = self.profiles
            profile = library.get(device["first_install_profile"])
            if profile.get("managed"):
                os_config = library.template(profile)
        ai = yaml.safe_load(os_config["user_data"])["autoinstall"]
        disks = [x for x in ai["storage"]["config"] if x["type"] == "disk"]
        if device.get("first_install_profile"):
            if len(disks) != 1 or disks[0].get("path") or disks[0].get("preserve") is not False:
                raise RuntimeError("通用模板必须只声明一个待绑定系统盘。")
        elif len(disks) != 1 or disks[0]["path"] != "/dev/disk/by-id/wwn-" + device["disk_wwn"]:
            raise RuntimeError("基线安装配置的写盘范围不匹配。")
        if os_config.get("run_provisioning_instructions_on_every_boot"):
            raise RuntimeError("禁止 everyboot 安装。")
        if device.get("os_id"):
            os_config["variant"] = {"OperatingSystemId": device["os_id"]}
        return os_config

    def check_materials(self, device=None):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for material in (device or {}).get("materials", self.config["materials"]):
            try:
                with opener.open(
                    urllib.request.Request(
                        material.get("verification_url", material["url"]), method="HEAD"
                    ),
                    timeout=15,
                ) as result:
                    if int(result.headers.get("Content-Length", 0)) != material["size"]:
                        raise RuntimeError("材料长度变化：" + material["name"])
            except OSError:
                raise RuntimeError("安装材料无法访问：" + material["name"]) from None

    def preflight(self, serial, hostname, *, native_observation=None):
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", hostname):
            raise ValueError("hostname 使用 1–63 位小写字母、数字和短横线。")
        device = self.device(serial, bind_intent=False)
        target = self.device(serial)
        checks = []
        snapshot = {}
        disk_selection = None
        hardware_checked_at = None

        def check(name, action):
            try:
                result = action()
                checks.append({"name": name, "passed": True, "detail": "实际检查通过"})
                return result
            except Exception as error:
                checks.append({"name": name, "passed": False, "detail": str(error)})

        plan = check("设备规划、已接管接口、子网与地址占用", lambda: self.installation_plan(serial))

        def core_check():
            nonlocal disk_selection, hardware_checked_at
            if native_observation is None:
                machine = self.machine(device)
                instance = self.instance(device)
            else:
                machine = native_observation.get("machine") or {}
                bmc = machine.get("bmc") or machine.get("bmc_info") or {}
                if machine.get("id") != device["machine_id"] or bmc.get("ip") != device["bmc_ip"]:
                    raise RuntimeError("Machine 与登记 BMC 身份不匹配。")
                instances = [
                    item
                    for item in native_observation.get("instances", [])
                    if item.get("id") == device["instance_id"]
                ]
                if len(instances) != 1:
                    raise RuntimeError("未找到唯一匹配的既有 Instance。")
                instance = instances[0]
            if machine["state"] != "Assigned/Ready":
                raise RuntimeError("Machine 当前不是 Assigned/Ready。")
            if instance["config"]["os"].get("run_provisioning_instructions_on_every_boot"):
                raise RuntimeError("当前 Instance 仍启用 everyboot。")
            snapshot.update(
                config_version=instance["config_version"],
                live_sha256=sha(instance["config"]["os"]["user_data"]),
            )
            if target.get("disk_serial"):
                from pxeye.services.onboarding import discovery_info

                disks = scout_disks(discovery_info(machine))
                disk_selection = select_disk(
                    disks,
                    target.get("storage"),
                    target["disk_serial"],
                )
                disk_selection["source"] = (
                    "设备规划"
                    if target["disk_serial"] != device.get("disk_serial")
                    else "当前系统盘"
                )
                plan.update(
                    disk_serial=disk_selection["serial"],
                    disk_selection=disk_selection,
                )
                if disk_selection["serial"] != device.get("disk_serial"):
                    plan.update(
                        previous_disk_serial=device.get("disk_serial"),
                        disk_change=True,
                    )
                snapshot["discovery_sha256"] = sha(json.dumps(disks, sort_keys=True))
                hardware_checked_at = time.time()
            snapshot["baseline_sha256"] = sha(json.dumps(self.baseline(target), sort_keys=True))

        check("Core mTLS、既有 Instance 与目标盘基线", core_check)

        def bmc_check():
            system = self.redfish(device)
            if system.get("SerialNumber") != serial or system.get("PowerState") != "On":
                raise RuntimeError("BMC SN 或电源状态不符合预期。")
            snapshot["bmc_boot"] = system.get("Boot")

        check("BMC 认证与序列号", bmc_check)
        if plan:

            def network_check():
                rendered = self.render(
                    self.target_device(serial, plan),
                    {
                        "id": "PREFLIGHT",
                        "hostname": hostname,
                        "actor": "preflight",
                        "installation_plan": plan,
                    },
                )
                snapshot["rendered_network"] = yaml.safe_load(rendered["user_data"])["autoinstall"][
                    "network"
                ]

            check("管理地址与下一次安装网络配置", network_check)

        def material_check():
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for material in target.get("materials", self.config["materials"]):
                with opener.open(
                    urllib.request.Request(
                        material.get("verification_url", material["url"]), method="HEAD"
                    ),
                    timeout=15,
                ) as result:
                    if int(result.headers.get("Content-Length", 0)) != material["size"]:
                        raise RuntimeError("材料长度变化：" + material["name"])

        check("安装材料 HTTP 与固定长度（执行前另做完整摘要校验）", material_check)
        return {
            "device": serial,
            "hostname": hostname,
            "disk_serial": target.get("disk_serial"),
            "disk_selection": disk_selection,
            "hardware_checked_at": hardware_checked_at,
            "passed": all(c["passed"] for c in checks),
            "checked_at": time.time(),
            "checks": checks,
            "snapshot": snapshot,
            "installation_plan": plan,
            "execution_device": target,
            "scope": {
                "disk_wwn": device["disk_wwn"],
                "disk_serial": target.get("disk_serial"),
                "current_management_ip": device["management_ip"],
                "management_ip": (plan or {}).get("management_ip", device["management_ip"]),
                "instance_id": device["instance_id"],
                "profile": device["profile"],
            },
        }

    def current_known(self, device):
        saved = self.identity / (device["serial"] + ".known_hosts")
        return saved if saved.exists() else self.secrets / "known_hosts"

    def render(self, device, task):
        config = copy.deepcopy(self.baseline(device))
        data = yaml.safe_load(config["user_data"])
        ai = data["autoinstall"]
        # The authenticated installer console binds this key to the task. Keep
        # it across cloud-init's first boot so strict SSH verifies that identity.
        ai.setdefault("user-data", {}).update(ssh_deletekeys=False, timezone=device["timezone"])
        ai["timezone"] = device["timezone"]
        # Cloud-init may update localtime after timedated cached the live image's
        # zone. Reapply through the service on first boot before acceptance.
        timezone_command = ["timedatectl", "set-timezone", device["timezone"]]
        firstboot_commands = ai["user-data"].setdefault("runcmd", [])
        if timezone_command not in firstboot_commands:
            firstboot_commands.append(timezone_command)
        ai["identity"]["hostname"] = task["hostname"]
        if device.get("authorized_keys") is not None:
            ai["ssh"]["authorized-keys"] = copy.deepcopy(device["authorized_keys"])
        if device.get("login_mode"):
            old_user = ai["identity"]["username"]
            ai["identity"]["username"] = device["ssh_user"]
            ai["identity"]["password"] = (
                self.login_credential(device)["password_hash"]
                if device["login_mode"] == "password"
                else "!"
            )
            ai["ssh"]["allow-pw"] = device["login_mode"] == "password"
            ai["late-commands"] = [
                c.replace(old_user + " ALL=", device["ssh_user"] + " ALL=")
                for c in ai["late-commands"]
            ]
        if device.get("first_install_profile"):
            self.render_discovered_device(ai, device, task)
        if task.get("installation_plan"):
            plan = task["installation_plan"]
            network = ai["network"]
            matches = [
                n
                for n in network.get("ethernets", {}).values()
                if n.get("match", {}).get("macaddress", "").lower() == plan["boot_mac"].lower()
            ]
            if len(matches) != 1:
                raise RuntimeError("安装模板没有唯一按 MAC 匹配的管理接口，不能覆盖网络。")
            nic = matches[0]
            if nic.get("dhcp4") is not False or len(nic.get("addresses", [])) != 1:
                raise RuntimeError("管理接口模板必须为单 IPv4 静态地址。")
            routes = [r for r in nic.get("routes", []) if r.get("to") in ("default", "0.0.0.0/0")]
            if len(routes) != 1:
                raise RuntimeError("安装模板缺少唯一管理默认路由。")
            nic["addresses"] = [plan["management_ip"] + "/" + str(plan["prefixlen"])]
            routes[0]["via"] = plan["gateway"]
            if plan.get("dns_servers"):
                nic["nameservers"] = {"addresses": plan["dns_servers"]}
            if "network" in data:
                raise RuntimeError("模板同时存在顶层 network，请先统一网络来源。")
            from pxeye.installation.network_interfaces import render_interfaces

            render_interfaces(network, plan.get("os_interfaces", []))
        key = (self.secrets / "ssh_key.pub").read_text().strip()
        if key not in ai["ssh"]["authorized-keys"]:
            ai["ssh"]["authorized-keys"].append(key)
        receipt = {
            "schema_version": 1,
            "source": "nico-ui",
            "task_id": task["id"],
            "serial": device["serial"],
            "hostname": task["hostname"],
            "instance_id": device["instance_id"],
            "disk_wwn": device["disk_wwn"],
            "boot_mac": device["boot_mac"],
            "profile": device["profile"],
            "submitted_by": task["actor"],
            "profile_version": device.get("profile_version"),
            "profile_revision": device.get("profile_revision"),
            "installation_mode": task.get("mode", "reinstall"),
            "disk_serial": device.get("disk_serial"),
        }
        ai["late-commands"] = [
            c for c in ai["late-commands"] if "/var/log/nico-installation/task.json" not in c
        ]
        command = (
            "mkdir -p /target/var/log/nico-installation && printf %s "
            + shlex.quote(json.dumps(receipt))
            + " > /target/var/log/nico-installation/task.json && cp /target/var/log/nico-installation/task.json /target/etc/nico-installation.json"
        )
        ai["late-commands"].append(command)
        from pxeye.installation.install_events import inject, freeze

        binding = inject(self, ai, device, task)
        config["user_data"] = "#cloud-config\n" + yaml.safe_dump(data, sort_keys=False, width=1000)
        freeze(self, binding, config["user_data"])
        config["run_provisioning_instructions_on_every_boot"] = False
        return config

    def render_discovered_device(self, ai, device, task):
        """Bind only hardware variables; commands are generated by the service."""
        disk = next(x for x in ai["storage"]["config"] if x["type"] == "disk")
        esps = [
            p
            for p in ai["storage"]["config"]
            if p["type"] == "partition"
            and p.get("device") == disk["id"]
            and p.get("flag") == "boot"
        ]
        if disk.get("ptable") != "gpt" or len(esps) != 1:
            raise RuntimeError("UEFI 通用安装方案需要指定系统盘上的唯一 EFI 分区。")
        # Older saved templates marked the whole disk for BIOS GRUB installation.
        # UEFI installs need the ESP itself selected, including frozen old profiles.
        disk["grub_device"] = False
        esps[0]["grub_device"] = True
        disk["match"] = {"serial": device["disk_serial"]}
        disk.pop("path", None)
        nics = ai["network"].get("ethernets", {})
        if len(nics) != 1:
            raise RuntimeError("通用模板需要唯一管理接口占位。")
        nic = next(iter(nics.values()))
        nic["match"] = {"macaddress": device["boot_mac"]}
        guard_context = {
            "task_id": task["id"],
            "serial": device["serial"],
            "disk_serial": device["disk_serial"],
            "boot_mac": device["boot_mac"],
            "disk_id": disk["id"],
            "minimum_bytes": int(
                ((device.get("storage", {}).get("root_gib") or 20) * 1024**3)
                + ((device.get("storage", {}).get("efi_mib", 1024) + 8) * 1024**2)
            ),
        }
        code = (
            script_source("disk_identity.py")
            + "\nimport yaml\nCTX = "
            + repr(guard_context)
            + """
assert Path('/sys/class/dmi/id/product_serial').read_text().strip()==CTX['serial'], 'SERIAL_MISMATCH'
assert Path('/sys/firmware/efi').is_dir(), 'UEFI_REQUIRED'
assert any(p.read_text().strip().lower()==CTX['boot_mac'].lower() for p in Path('/sys/class/net').glob('*/address')), 'BOOT_MAC_MISSING'
target=resolve_disk(CTX['disk_serial'])
assert int(subprocess.check_output(['blockdev','--getsize64',str(target)],text=True,timeout=20)) >= CTX['minimum_bytes'], 'SYSTEM_DISK_TOO_SMALL_FOR_PARTITIONS'
disks=json.loads(subprocess.check_output(['lsblk','-J','-o','NAME,TYPE,FSTYPE,WWN,SERIAL'],text=True,timeout=20))['blockdevices']
before={'task_id':CTX['task_id'],'serial':CTX['serial'],'disk_serial':CTX['disk_serial'],'target':str(target),'target_name':target.resolve().name,'disks':disks}
Path('/run/nico-disks-before.json').write_text(json.dumps(before))
path=Path('/autoinstall.yaml'); config=yaml.safe_load(path.read_text())
ai=config.get('autoinstall',config)
disk=next(d for d in ai['storage']['config'] if d['id']==CTX['disk_id'])
# Subiquity matches the probed kernel path, not a /dev/disk/by-id alias.
# Resolve only after the unique Scout serial and persistent ID were verified.
disk.pop('match',None);disk['path']=str(target.resolve(strict=True))
path.write_text(yaml.safe_dump(config,sort_keys=False))
print('NICO_UI_DISK_GUARD_PASSED',CTX['task_id'])
"""
        )
        ai["early-commands"] = ["python3 - <<'NICO_GUARD'\n" + code + "\nNICO_GUARD"]
        ai.setdefault("late-commands", []).append(
            "mkdir -p /target/var/log/nico-installation && cp /run/nico-disks-before.json /target/var/log/nico-installation/disks.before.json"
        )
