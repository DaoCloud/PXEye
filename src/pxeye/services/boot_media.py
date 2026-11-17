"""Immutable external-DHCP UEFI media; hardware actions belong to NICo Core."""

import hashlib
import ipaddress
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from pxeye.common import atomic_json, digest


_SCRIPT = """#!ipxe
# External DHCP supplies addressing only. Never use its boot server or filename.
iseq ${platform} efi || goto failed
set pxeye-pxe-base @PXE_BASE@
set pxeye-boot-mac @BOOT_MAC@
set pxeye-index:int32 0
:find_interface
iseq ${net${pxeye-index}/mac} ${pxeye-boot-mac} && goto interface_found ||
inc pxeye-index || goto failed
iseq ${pxeye-index} 256 && goto missing_interface || goto find_interface
:interface_found
set pxeye-interface net${pxeye-index}
ifclose ||
ifconf -c dhcp ${pxeye-interface} || goto failed
echo PXEye boot interface ${pxeye-interface} MAC ${pxeye-boot-mac}
imgfree nico-boot ||
set nico-retry-provisioning 0
chain --name nico-boot ${pxeye-pxe-base}/api/v0/pxe/boot?buildarch=${buildarch}&platform=${platform}&manufacturer=${manufacturer}&product=${product}&serial=${serial} && goto exit_to_firmware || goto retry_nico_boot
:retry_nico_boot
iseq ${nico-retry-provisioning} 1 || goto failed
imgstat nico-boot || goto failed
sleep 30
imgexec nico-boot && goto exit_to_firmware || goto retry_nico_boot
:missing_interface
echo PXEye planned boot MAC ${pxeye-boot-mac} was not found
goto exit_to_firmware
:failed
echo PXEye explicit NICo boot failed; check the planned MAC, fixed lease and HTTP endpoint
:exit_to_firmware
ifclose ||
exit 1
"""


def file_sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def boot_base_url(value):
    """Validate text inserted into an iPXE command without shell interpretation."""
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 2048
        or any(ord(c) <= 32 or ord(c) >= 127 for c in value)
        or any(c in value for c in "\\$;{}'\"<>|&#")
    ):
        raise ValueError("请提供完整的 PXE HTTP 基址，包含协议和实际服务端口。")
    try:
        parsed = urlsplit(value)
        port = parsed.port
        host = parsed.hostname
        if (
            parsed.scheme not in ("http", "https")
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or (port is not None and not 1 <= port <= 65535)
        ):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if len(host) > 253 or not all(
                re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                for label in host.rstrip(".").split(".")
            ):
                raise ValueError
    except ValueError as error:
        raise ValueError("PXE HTTP 基址无效；不能包含认证信息、查询参数或片段。") from error
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def boot_mac_address(value):
    value = str(value or "").lower().replace("-", ":")
    if (
        not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", value)
        or int(value[:2], 16) & 1
        or value == "00:00:00:00:00:00"
    ):
        raise ValueError("请先在设备规划中设置有效的启动网卡 MAC 和外部 DHCP 固定租约。")
    return value


class BootMedia:
    """Publish a small ISO from packaged assets, never compile on the site."""

    def __init__(self, adapter, *, assets_directory="/usr/share/pxeye/boot-media"):
        self.adapter = adapter
        self.assets = Path(assets_directory)
        self.records = adapter.data / "config" / "boot-media"
        self.lock = threading.RLock()

    @staticmethod
    def script(pxe_base_url, *, boot_mac):
        base = boot_base_url(pxe_base_url)
        mac = boot_mac_address(boot_mac)
        return _SCRIPT.replace("@PXE_BASE@", base).replace("@BOOT_MAC@", mac)

    def prepare(self, pxe_base_url, *, boot_mac, architecture="x86_64"):
        """Return the immutable material reference to freeze in a Core request."""
        if architecture != "x86_64":
            raise ValueError("外部 DHCP 引导介质当前仅支持无 DPU 的 x86_64 UEFI 服务器。")
        base = boot_base_url(pxe_base_url)
        mac = boot_mac_address(boot_mac)
        script = self.script(base, boot_mac=mac)
        settings = self.adapter.config.get("os_library", {})
        if not settings.get("public_base_url"):
            raise ValueError("站点尚未配置安装材料 HTTP 发布地址，不能发布 BMC 引导 ISO。")
        public_base = boot_base_url(settings.get("public_base_url", ""))
        verification_base = boot_base_url(settings.get("verification_base_url") or public_base)
        assets = self._assets(architecture)
        root = Path(settings.get("directory", self.adapter.data / "os-library")) / "boot-media"
        spec = {
            "schema_version": 1,
            "architecture": architecture,
            "pxe_base_url": base,
            "boot_mac": mac,
            "public_base_url": public_base,
            "script_sha256": hashlib.sha256(script.encode()).hexdigest(),
            "esp_sha256": assets["esp_sha256"],
        }
        with self.lock:
            self.records.mkdir(parents=True, exist_ok=True, mode=0o700)
            root.mkdir(parents=True, exist_ok=True, mode=0o755)
            root.chmod(0o755)
            record_path = self.records / (digest(spec) + ".json")
            if record_path.exists():
                row = json.loads(record_path.read_text())
                if row.get("spec") == spec and self._matches(root, row):
                    self._verify_publication(verification_base, row)
                    return self._public(row)
            row = self._generate(root, assets, script, spec)
            # Keep completed immutable files even when their publication route is
            # unavailable. Retrying only verifies delivery; it does not rebuild.
            atomic_json(record_path, row)
            self._verify_publication(verification_base, row)
            return self._public(row)

    def _assets(self, architecture):
        path = self.assets / architecture
        try:
            manifest = json.loads((path / "manifest.json").read_text())
            if (
                manifest["schema_version"] != 1
                or manifest["architecture"] != architecture
                or manifest["embedded_script"] is not False
                or not re.fullmatch("[0-9a-f]{40}", manifest["ipxe_revision"])
                or file_sha256(path / "ipxe.efi") != manifest["efi_sha256"]
                or file_sha256(path / "esp.img") != manifest["esp_sha256"]
                or type(manifest["source_date_epoch"]) is not int
            ):
                raise ValueError
        except (OSError, KeyError, TypeError, ValueError) as error:
            raise ValueError(
                "镜像未携带有效的通用 UEFI 引导器；请使用标准 make images 构建。"
            ) from error
        if not all(shutil.which(command) for command in ("mcopy", "xorriso")):
            raise ValueError("PXEye 镜像缺少 mtools 或 xorriso，不能生成引导介质。")
        return manifest | {"directory": path}

    @staticmethod
    def _run(arguments, epoch):
        try:
            subprocess.run(
                arguments,
                check=True,
                capture_output=True,
                timeout=60,
                env=os.environ | {"TZ": "UTC", "SOURCE_DATE_EPOCH": str(epoch)},
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ValueError(
                "UEFI 引导介质生成失败；请检查工具、材料目录权限和剩余空间。"
            ) from error

    def _generate(self, root, assets, script, spec):
        epoch = assets["source_date_epoch"]
        timestamp = datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y%m%d%H%M%S00")
        with tempfile.TemporaryDirectory(prefix=".preparing-", dir=root) as temporary:
            work = Path(temporary)
            tree = work / "iso"
            tree.mkdir()
            esp = tree / "esp.img"
            shutil.copyfile(assets["directory"] / "esp.img", esp)
            autoexec = work / "autoexec.ipxe"
            autoexec.write_text(script)
            os.utime(autoexec, (epoch, epoch))
            self._run(
                ["mcopy", "-m", "-o", "-i", str(esp), str(autoexec), "::/autoexec.ipxe"], epoch
            )
            iso = work / "boot.iso"
            self._run(
                [
                    "xorriso",
                    "-as",
                    "mkisofs",
                    "-r",
                    "-J",
                    "-V",
                    "PXEYE_BOOT",
                    "--modification-date=" + timestamp,
                    "--set_all_file_dates",
                    timestamp,
                    "-c",
                    "boot.catalog",
                    "-e",
                    "esp.img",
                    "-no-emul-boot",
                    "-o",
                    str(iso),
                    str(tree),
                ],
                epoch,
            )
            checksum = file_sha256(iso)
            filename = checksum + ".iso"
            iso.chmod(0o444)
            try:
                os.link(iso, root / filename)
            except FileExistsError:
                if file_sha256(root / filename) != checksum:
                    raise ValueError("已发布的引导介质内容发生变化；请管理员检查材料存储。")
            return {
                "spec": spec,
                "filename": filename,
                "sha256": checksum,
                "size": iso.stat().st_size,
                "architecture": spec["architecture"],
                "boot_mac": spec["boot_mac"],
                "pxe_base_url": spec["pxe_base_url"],
                "boot_url": spec["pxe_base_url"] + "/api/v0/pxe/boot",
                "url": spec["public_base_url"] + "/boot-media/" + filename,
                "efi_sha256": assets["efi_sha256"],
                "ipxe_revision": assets["ipxe_revision"],
                "created_at": time.time(),
            }

    @staticmethod
    def _matches(root, row):
        checksum = row.get("sha256", "")
        if not re.fullmatch("[0-9a-f]{64}", checksum) or row.get("filename") != checksum + ".iso":
            return False
        path = root / row["filename"]
        return (
            path.is_file()
            and not path.is_symlink()
            and path.stat().st_size == row.get("size")
            and file_sha256(path) == checksum
        )

    @staticmethod
    def _verify_publication(base, row):
        client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        url = base + "/boot-media/" + row["filename"]
        try:
            with client.open(urllib.request.Request(url, method="HEAD"), timeout=10) as response:
                if int(response.headers.get("Content-Length", 0)) != row["size"]:
                    raise ValueError
        except (OSError, ValueError) as error:
            raise ValueError(
                "引导 ISO 已生成，但材料 HTTP 发布地址无法确认；修复发布路径后重试。"
            ) from error

    @staticmethod
    def _public(row):
        return {key: value for key, value in row.items() if key not in ("spec", "filename")}
