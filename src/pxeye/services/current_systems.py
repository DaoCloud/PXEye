"""Bounded, operator-requested current Linux OS observations; never changes hosts."""

import ipaddress
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from pxeye.clients.process import run
from pxeye.services.bmc_addresses import BMCAddresses


HOST_QUERY = """import json,shlex,subprocess
from pathlib import Path
serials=[p.read_text().strip() for p in (Path('/sys/class/dmi/id/product_serial'),Path('/sys/class/dmi/id/chassis_serial')) if p.exists()]
release={}
for line in Path('/etc/os-release').read_text().splitlines():
 if '=' in line and not line.startswith('#'):
  key,value=line.split('=',1)
  parts=shlex.split(value)
  release[key]=' '.join(parts)
root=json.loads(subprocess.check_output(['findmnt','-J','-o','SOURCE,FSTYPE','/'],text=True,timeout=5))['filesystems'][0]
print(json.dumps({'serials':serials,'os':release.get('PRETTY_NAME') or release.get('NAME'),'temporary':root['fstype'] in ('overlay','tmpfs','ramfs','squashfs','rootfs')}))
"""


class CurrentSystems:
    def __init__(self, adapter, resources, store):
        self.adapter, self.resources, self.store = adapter, resources, store
        self.lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="current-system")
        self.results = {}
        self.pending = set()

    def view(self):
        with self.lock:
            return {"systems": dict(self.results), "pending": sorted(self.pending)}

    def start(self, body):
        serials = body.get("serials")
        if (
            set(body) != {"serials"}
            or not isinstance(serials, list)
            or not 1 <= len(serials) <= 50
            or any(not isinstance(s, str) or not s for s in serials)
            or len(set(serials)) != len(serials)
        ):
            raise ValueError("请选择1–50台已登记设备查询当前系统。")
        rows = {r["chassis_serial_number"]: r for r in self.resources.planned_inventory()}
        if any(s not in rows for s in serials):
            raise ValueError("查询设备已变化，请刷新设备信息。")
        with self.lock:
            new = [s for s in serials if s not in self.pending]
            if len(self.pending) + len(new) > 50:
                raise ValueError("当前查询尚未结束，请稍后再查询。")
            for serial in new:
                self.pending.add(serial)
                self.pool.submit(self._observe, serial, rows[serial])
        return self.view()

    def _connection(self, serial):
        # A frozen installation connection may be newer than the last accepted OS.
        with self.store.db() as db:
            record = db.execute(
                "SELECT data FROM tasks WHERE device=? ORDER BY created DESC LIMIT 1", (serial,)
            ).fetchone()
        task = json.loads(record["data"]) if record else {}
        device = task.get("execution_device")
        if (
            device
            and device.get("serial") == serial
            and re.fullmatch(r"[A-Za-z0-9_-]+", task["id"])
            and (self.adapter.data / "tasks" / task["id"] / "known_hosts").is_file()
        ):
            device = dict(device)
            plan = task.get("installation_plan") or {}
            if plan.get("management_ip"):
                device["management_ip"] = plan["management_ip"]
            return device, self.adapter.data / "tasks" / task["id"] / "known_hosts"
        device = self.adapter.device(serial, bind_intent=False)
        return device, self.adapter.current_known(device)

    def _power(self, row, device):
        ip = BMCAddresses(self.adapter, self.resources).contact(row, [])
        if not ip:
            return None
        if device and (
            (
                device.get("credential_source") == "managed"
                and not device.get("bmc_retain_credentials")
            )
            or device.get("bmc_credential_file")
        ):
            credential = self.adapter.credentials(device)
        else:
            credential = {"username": row.get("bmc_username"), "password": row.get("bmc_password")}
        if not all(credential.values()):
            return None
        path = (device or {}).get("redfish_system")
        if not path or path.rstrip("/") == "/redfish/v1/Systems":
            collection = self.adapter.redfish_read(ip, "/redfish/v1/Systems", credential)
            members = collection.get("Members", [])
            if len(members) != 1:
                return None
            path = members[0]["@odata.id"]
        system = self.adapter.redfish_read(ip, path, credential)
        if str(system.get("SerialNumber", "")).strip() != row["chassis_serial_number"]:
            raise ValueError("BMC identity mismatch")
        return system.get("PowerState")

    def _ssh(self, device, known):
        try:
            return self.adapter.ssh(device, HOST_QUERY, known=known, timeout=15)
        except RuntimeError:
            if device.get("login_mode") != "password" or not device.get("login_ref"):
                raise
        credential = self.adapter.login_credential(device)
        if credential.get("username") != device["ssh_user"] or not credential.get("password"):
            raise ValueError("Credential mismatch")
        return run(
            [
                "sshpass",
                "-e",
                "ssh",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                "ConnectTimeout=5",
                "-o",
                "NumberOfPasswordPrompts=1",
                "-o",
                "PreferredAuthentications=password",
                "-o",
                "PubkeyAuthentication=no",
                "-o",
                "UserKnownHostsFile=" + str(known),
                device["ssh_user"] + "@" + device["management_ip"],
                "sudo -n python3 -",
            ],
            text=HOST_QUERY,
            timeout=15,
            env=dict(os.environ, SSHPASS=credential["password"]),
        )

    def _observe(self, serial, row):
        result = {"status": "unreachable", "label": "无 SSH，无法访问"}
        try:
            try:
                device, known = self._connection(serial)
            except (RuntimeError, ValueError, OSError, KeyError):
                device, known = None, None
            try:
                power = self._power(row, device)
            except (RuntimeError, ValueError, OSError, KeyError, TypeError):
                power = None
            if power == "Off":
                result = {"status": "off", "label": "已关机"}
            elif device:
                # No keyscan or trust-on-first-use, no address or host key mutations.
                ipaddress.ip_address(device["management_ip"])
                if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", device["ssh_user"]):
                    raise ValueError("Invalid SSH user")
                report = json.loads(self._ssh(device, known))
                if serial not in report.get("serials", []) or not isinstance(report.get("os"), str):
                    raise ValueError("SSH identity or OS missing")
                label = "发现 / 安装环境" if report.get("temporary") else report["os"].strip()[:160]
                if not label:
                    raise ValueError("OS missing")
                result = {
                    "status": "temporary" if report.get("temporary") else "os",
                    "label": label,
                }
        except Exception:
            # Never return command output, credential paths or authentication errors.
            result = {"status": "unreachable", "label": "无 SSH，无法访问"}
        finally:
            result["checked_at"] = time.time()
            with self.lock:
                self.results[serial] = result
                self.pending.discard(serial)
