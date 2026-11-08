"""Sent over strict SSH to the installed OS. CTX is injected by the executor."""

import datetime
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pxeye.installation.disk_identity import resolve_disk, disk_layout

    CTX = {}  # Injected alongside the disk identity helpers by the executor.


def command(args):
    return subprocess.check_output(args, text=True, timeout=25).strip()


def collect(context):
    device, task = context["device"], context["task"]
    old = task["preflight"]["snapshot"].get("host")
    serials = [
        p.read_text().strip()
        for p in (
            Path("/sys/class/dmi/id/product_serial"),
            Path("/sys/class/dmi/id/chassis_serial"),
        )
        if p.exists()
    ]
    assert device["serial"] in serials, "SERIAL_MISMATCH"
    assert command(["hostname"]) == task["hostname"], "HOSTNAME_MISMATCH"
    assert device["os_release"] in Path("/etc/os-release").read_text(), "OS_VERSION_MISMATCH"
    assert command(["uname", "-m"]) == device["architecture"], "ARCH_MISMATCH"
    receipt = json.loads(Path("/var/log/nico-installation/task.json").read_text())
    assert receipt["source"] == "nico-ui" and receipt["task_id"] == task["id"], (
        "TASK_RECEIPT_MISMATCH"
    )
    assert receipt == json.loads(Path("/etc/nico-installation.json").read_text()), (
        "RECEIPT_COPY_MISMATCH"
    )
    assert receipt["serial"] == device["serial"] and receipt["hostname"] == task["hostname"], (
        "RECEIPT_IDENTITY_MISMATCH"
    )
    assert receipt["instance_id"] == device["instance_id"], "RECEIPT_INSTANCE_MISMATCH"
    if device.get("disk_serial"):
        assert receipt["disk_serial"] == device["disk_serial"], "RECEIPT_DISK_MISMATCH"
    root = json.loads(command(["findmnt", "-J", "/"]))["filesystems"][0]
    if device.get("disk_serial"):
        target = resolve_disk(device["disk_serial"]).resolve(strict=True)
    else:
        target = Path("/dev/disk/by-id/wwn-" + device["disk_wwn"]).resolve(strict=True)
    assert (
        Path("/dev/" + command(["lsblk", "-no", "PKNAME", root["source"]])).resolve() == target
    ), "WRONG_ROOT_DISK"
    storage = device.get("storage") or {}
    expected_fstype = storage.get("root_fstype", "ext4")
    assert root["fstype"] == expected_fstype, "ROOT_FILESYSTEM_MISMATCH"
    root_uuid = command(["blkid", "-s", "UUID", "-o", "value", root["source"]])
    if old:
        assert root_uuid != old["root_uuid"], "OLD_ROOT_REUSED"
    esp = command(["findmnt", "-no", "SOURCE", "/boot/efi"])
    assert Path("/dev/" + command(["lsblk", "-no", "PKNAME", esp])).resolve() == target, (
        "WRONG_ESP_DISK"
    )
    esp_uuid = command(["blkid", "-s", "PARTUUID", "-o", "value", esp])
    partition_layout = {
        "root_fstype": root["fstype"],
        "root_bytes": int(command(["blockdev", "--getsize64", root["source"]])),
        "efi_bytes": int(command(["blockdev", "--getsize64", esp])),
        "disk_bytes": int(command(["blockdev", "--getsize64", str(target)])),
        "ptable": command(["lsblk", "-dnro", "PTTYPE", str(target)]),
    }
    assert partition_layout["ptable"] == "gpt", "PARTITION_TABLE_MISMATCH"
    if storage:
        assert partition_layout["efi_bytes"] == storage.get("efi_mib", 1024) * 1024**2, (
            "EFI_SIZE_MISMATCH"
        )
        if storage.get("root_gib") is not None:
            assert (
                abs(partition_layout["root_bytes"] - int(storage["root_gib"] * 1024**3)) <= 1024**2
            ), "ROOT_SIZE_MISMATCH"
        else:
            unused = (
                partition_layout["disk_bytes"]
                - partition_layout["efi_bytes"]
                - partition_layout["root_bytes"]
            )
            assert 0 <= unused <= 8 * 1024**2, "ROOT_REMAINING_SPACE_MISMATCH"
    if old:
        assert esp_uuid != old["esp_partuuid"], "OLD_ESP_REUSED"
    key = Path("/etc/ssh/ssh_host_ed25519_key.pub").read_text().strip()
    if old:
        assert key.split()[:2] != old["host_key"].split()[:2], "OLD_SSH_IDENTITY_REUSED"
    assert key.split()[:2] == context["trusted_key"].split()[:2], "TRUSTED_SOL_KEY_MISMATCH"
    interfaces = [
        p.parent.name
        for p in Path("/sys/class/net").glob("*/address")
        if p.read_text().strip().lower() == device["boot_mac"].lower()
    ]
    assert len(interfaces) == 1, "BOOT_MAC_MISMATCH"
    interface = interfaces[0]
    addresses = json.loads(command(["ip", "-j", "-4", "addr", "show", interface]))[0]["addr_info"]
    assert any(
        a["local"] == device["management_ip"] and a["prefixlen"] == device["prefixlen"]
        for a in addresses
    ), "MANAGEMENT_IP_MISMATCH"
    routes = json.loads(command(["ip", "-j", "-4", "route", "show", "default"]))
    assert any(
        r.get("gateway") == device["gateway"] and r.get("dev") == interface for r in routes
    ), "DEFAULT_ROUTE_MISMATCH"
    netplan_yaml = command(["netplan", "get"])
    folder = Path("/var/log/installer")
    logpath = folder / "subiquity-server-debug.log"
    log = logpath.read_text()
    for stage in ["Late/run", "Install/install"]:
        assert re.search(r"finish: subiquity/" + stage + r": SUCCESS:", log), (
            "INSTALLER_NOT_SUCCESS_" + stage
        )
    installer_yaml = (folder / "autoinstall-user-data").read_text()
    # Subiquity's normalized export omits commands; the executed command is in its debug log.
    assert task["id"] in log and "NICO_UI_HOSTKEY " in log, "INSTALLER_TASK_NOT_BOUND"
    stages = json.loads(Path("/var/lib/cloud/data/status.json").read_text())["v1"]
    assert all(
        stages[k]["finished"] is not None and not stages[k]["errors"]
        for k in ["init-local", "init", "modules-config", "modules-final"]
    ), "FIRSTBOOT_NOT_CONVERGED"
    assert not json.loads(Path("/var/lib/cloud/data/result.json").read_text())["v1"]["errors"], (
        "CLOUD_INIT_FAILED"
    )
    assert command(["timedatectl", "show", "-p", "Timezone", "--value"]) == device["timezone"], (
        "TIMEZONE_NOT_CONVERGED"
    )
    expected_password = "yes" if device.get("login_mode") == "password" else "no"
    assert "passwordauthentication " + expected_password in command(["/usr/sbin/sshd", "-T"]), (
        "SSH_LOGIN_POLICY_MISMATCH"
    )
    failed = json.loads(
        command(
            ["systemctl", "list-units", "--all", "--state=failed", "--output=json", "--no-pager"]
        )
    )
    # Metadata refresh is optional on isolated sites; never hide other failures.
    optional_units = {"fwupd-refresh.service": "固件更新元数据刷新失败（fwupd-refresh.service）"}
    critical = [unit["unit"] for unit in failed if unit["unit"] not in optional_units]
    assert not critical, "关键系统服务失败：" + "、".join(critical)
    system_warnings = [
        optional_units[unit["unit"]] for unit in failed if unit["unit"] in optional_units
    ]
    service_checks = []

    def service(name, action):
        try:
            if action() is False:
                raise RuntimeError("not_ready")
            service_checks.append({"name": name, "passed": True})
        except Exception as error:
            service_checks.append({"name": name, "passed": False, "error": type(error).__name__})

    service(
        "NTP同步",
        lambda: command(["timedatectl", "show", "-p", "NTPSynchronized", "--value"]) == "yes",
    )
    for hostname in device["dns_checks"]:
        service("DNS解析 " + hostname, lambda h=hostname: bool(command(["getent", "ahostsv4", h])))
    import urllib.request

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def http_check(url):
        with opener.open(url, timeout=15) as response:
            response.read(1024)
            return response.status == 200

    for url in device["http_checks"]:
        service("HTTP访问 " + url, lambda u=url: http_check(u))
    boot_next = list(Path("/sys/firmware/efi/efivars").glob("BootNext-*"))
    assert not boot_next, "BOOTNEXT_STILL_SET"
    disks = json.loads(command(["lsblk", "-J", "-o", "NAME,TYPE,FSTYPE,WWN,SERIAL,MOUNTPOINTS"]))[
        "blockdevices"
    ]
    others = []

    def signature(disk):
        return {k: disk.get(k) for k in ["type", "fstype", "wwn", "serial", "mountpoints"]} | {
            "children": [signature(c) for c in disk.get("children", [])]
        }

    if old:
        before_disks = old["disks"]
        target_before = old["root_parent"]
    else:
        before_record = json.loads(Path("/var/log/nico-installation/disks.before.json").read_text())
        assert (
            before_record["task_id"] == task["id"]
            and before_record["serial"] == device["serial"]
            and before_record["disk_serial"] == device["disk_serial"]
        ), "DISK_GUARD_RECORD_MISMATCH"
        before_disks, target_before = before_record["disks"], before_record["target_name"]
    for before in before_disks:
        if before.get("type") != "disk" or before.get("name") == target_before:
            continue
        matches = [
            d
            for d in disks
            if (
                d.get("wwn") == before.get("wwn")
                if before.get("wwn")
                else d.get("serial") == before.get("serial")
            )
        ]
        compare = signature if old else disk_layout
        assert len(matches) == 1 and compare(matches[0]) == compare(before), (
            "OTHER_DISK_LAYOUT_CHANGED"
        )
        others.append(matches[0])
    report = {
        "checked_at": datetime.datetime.now().astimezone().isoformat(),
        "serial": device["serial"],
        "hostname": command(["hostname"]),
        "root_uuid": root_uuid,
        "esp_partuuid": esp_uuid,
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "host_key": key,
        "hostkey_fingerprint": command(["ssh-keygen", "-lf", "/etc/ssh/ssh_host_ed25519_key.pub"]),
        "task_receipt": receipt,
        "addresses": addresses,
        "routes": routes,
        "efi": {"boot_next_present": False, "source": "efivarfs"},
        "installer_log_sha256": hashlib.sha256(logpath.read_bytes()).hexdigest(),
        "other_disks_layout_unchanged": others,
        "other_disks_bytewise_compared": False,
        "management_interface": interface,
        "service_checks": service_checks,
        "partition_layout": partition_layout,
        "noncritical_failed_units": [unit["unit"] for unit in failed],
        "checks": {k: True for k in ["installer", "identity", "disk", "partitions", "ssh"]},
    }
    report["checks"]["services"] = all(c["passed"] for c in service_checks)
    report["warnings"] = system_warnings + [
        c["name"] + "未通过" for c in service_checks if not c["passed"]
    ]
    first = context.get("initial")
    if first:
        assert report["boot_id"] != first["boot_id"], "NORMAL_REBOOT_NOT_OBSERVED"
        assert all(
            report[k] == first[k] for k in ["root_uuid", "esp_partuuid", "host_key", "hostname"]
        ), "IDENTITY_CHANGED_ON_REBOOT"
        report["checks"]["normal_reboot"] = True
    # YAML parsing and the remaining configuration checks run in the UI backend.
    return report, {"netplan": netplan_yaml, "installer": installer_yaml}


if __name__ == "__main__":
    try:
        report, config_yaml = collect(CTX)
        print(json.dumps({"passed": True, "report": report, "_config_yaml": config_yaml}))
    except Exception as error:
        print(json.dumps({"passed": False, "error": str(error), "type": type(error).__name__}))
