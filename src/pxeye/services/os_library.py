"""Immutable installation media, bounded upload and native NICo OS definitions."""

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import threading
import time
import uuid
import urllib.request
from pathlib import Path

from pxeye.common import atomic_json, digest, value_id


def ubuntu_boot_parameters(iso_url, *, serial_console=True):
    value = (
        "ip=dhcp BOOTIF=01-${netX/mac:hexhyp} autoinstall cloud-config-url=/dev/null url="
        + iso_url
        + " ds=nocloud-net;s=${tenant-cloudinit-url}"
    )
    # The generic kernel-initrd template defines ${console} from Core's hardware value.
    return value + (
        " console=tty0 console=${console},115200n8 initrd=initrd" if serial_console else ""
    )


class OSLibrary:
    def __init__(self, adapter, recover=False, store=None):
        self.adapter = adapter
        self.store = store
        self.directory = adapter.data / "config" / "operating-systems"
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.settings = adapter.config.get("os_library", {})
        self.root = Path(self.settings.get("directory", adapter.data / "os-library"))
        self.lock = threading.RLock()
        for path in self.directory.glob("*.json") if recover else []:
            row = json.loads(path.read_text())
            if row["status"] in ("importing", "preparing", "registering"):
                row.update(
                    status="needs_attention",
                    error="服务重启；请核对材料或 NICo 登记结果，未自动重放。",
                )
                atomic_json(path, row)

    def read(self, key):
        key = str(uuid.UUID(key))
        path = self.directory / (key + ".json")
        if not path.exists():
            raise ValueError("OS 版本不存在。")
        return json.loads(path.read_text())

    def save(self, row):
        row["updated_at"] = time.time()
        atomic_json(self.directory / (row["id"] + ".json"), row)

    def public(self, row):
        return {k: v for k, v in row.items() if k != "owner"} | {"revision": digest(row)}

    def list(self):
        ids = self.adapter.rpc("FindOperatingSystemIds", {}).get("ids", [])
        native = (
            self.adapter.rpc("FindOperatingSystemsByIds", {"ids": ids}).get("operatingSystems", [])
            if ids
            else []
        )
        rows = [self.public(json.loads(p.read_text())) for p in self.directory.glob("*.json")]
        for row in rows:
            row["native"] = next(
                (
                    {
                        "id": value_id(n["id"]),
                        "name": n["name"],
                        "is_active": n.get("isActive", False),
                        "status": n.get("status"),
                    }
                    for n in native
                    if value_id(n["id"]) == row["id"]
                ),
                None,
            )
        known = {r["id"] for r in rows}
        rows += [
            {
                "id": value_id(n["id"]),
                "name": n["name"],
                "status": "external",
                "architecture": "未登记材料",
                "native": {
                    "id": value_id(n["id"]),
                    "is_active": n.get("isActive", False),
                    "status": n.get("status"),
                },
                "materials": [],
            }
            for n in native
            if value_id(n["id"]) not in known
        ]
        usage = self.task_usage()
        for row in rows:
            row["usage"] = usage.get(row["id"], [])
            row["disable_reason"] = self.usage_reason(row["usage"])
        return {
            "operating_systems": sorted(rows, key=lambda r: r.get("updated_at", 0), reverse=True),
            "upload_enabled": bool(self.settings.get("public_base_url")),
            "max_size": self.settings.get("max_size", 16 * 1024**3),
        }

    def task_usage(self):
        usage = {}
        for task in self.store.incomplete() if self.store else []:
            plan = task.get("installation_plan") or {}
            device = task.get("execution_device") or {}
            ids = {
                plan.get("os_id"),
                (plan.get("effective_config") or {}).get("os_id"),
                device.get("os_id"),
            }
            # Legacy tasks may only identify their OS in the frozen rendered configuration.
            if not any(ids):
                frozen = self.adapter.data / "tasks" / task["id"] / "rendered-os.json"
                if frozen.exists():
                    config = json.loads(frozen.read_text())
                elif device.get("baseline_file"):
                    config = self.adapter.baseline(device)
                else:
                    config = {}
                ids.add((config.get("variant") or {}).get("OperatingSystemId"))
            for key in ids - {None, ""}:
                usage.setdefault(key, []).append(
                    {k: task.get(k) for k in ("id", "device", "status")}
                )
        return usage

    @staticmethod
    def usage_reason(tasks):
        return (
            (
                "此 OS 被活动安装任务引用："
                + "、".join(t["id"] for t in tasks)
                + "。任务结束前不能停用、重新准备或取消此版本。"
            )
            if tasks
            else ""
        )

    def operate(self, action, body, owner):
        # Share only this short resource lock with task reservation, never the installer lifetime lock.
        with self.lock:
            if action != "import":
                key = str(uuid.UUID(body["id"]))
                if action != "activate" or body.get("active") is not True:
                    reason = self.usage_reason(self.task_usage().get(key, []))
                    if reason:
                        raise ValueError(reason)
            if action == "import":
                return self.begin_import(body, owner)
            if action in ("recover", "cancel"):
                return getattr(self, action)(body, owner)
            if action in ("register", "activate"):
                return getattr(self, action)(body)
            raise ValueError("OS 操作无效。")

    def sources(self):
        sources = []
        for source in self.settings.get("sources", []):
            entry = {"id": source["id"], "name": source["name"], "files": []}
            try:
                with os.scandir(source["directory"]) as files:
                    for item in files:
                        if (
                            item.is_symlink()
                            or not item.is_file(follow_symlinks=False)
                            or not item.name.lower().endswith(".iso")
                        ):
                            continue
                        with self.open_source(source["id"], item.name) as stream:
                            info = os.fstat(stream.fileno())
                        if 32768 <= info.st_size <= self.settings.get("max_size", 16 * 1024**3):
                            entry["files"].append(
                                {
                                    "filename": item.name,
                                    "size": info.st_size,
                                    "modified_at": info.st_mtime,
                                    "fingerprint": source_fingerprint(info),
                                }
                            )
                        if len(entry["files"]) >= 1000:
                            entry["note"] = "最多列出 1000 个 ISO；请将来源按目录拆分。"
                            break
                entry["files"].sort(key=lambda f: f["filename"])
            except (OSError, ValueError):
                entry["error"] = "来源目录或文件不可读取，请管理员检查只读挂载及权限后刷新。"
            sources.append(entry)
        return {"sources": sources, "import_enabled": bool(self.settings.get("public_base_url"))}

    def open_source(self, source_id, filename):
        source = next((s for s in self.settings.get("sources", []) if s["id"] == source_id), None)
        if (
            source is None
            or not isinstance(filename, str)
            or "/" in filename
            or "\\" in filename
            or "\x00" in filename
            or not filename.lower().endswith(".iso")
        ):
            raise ValueError("请选择配置来源目录中的 ISO 文件。")
        directory = os.open(source["directory"], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            descriptor = os.open(
                filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
            )
        finally:
            os.close(directory)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise ValueError("来源必须是普通 ISO 文件，不能是链接或设备。")
        return os.fdopen(descriptor, "rb")

    def begin_import(self, body, owner):
        if set(body) != {"name", "source_id", "filename", "fingerprint", "sha256"}:
            raise ValueError("请提供版本名称、来源文件和可选 SHA256。")
        with self.lock:
            if any(
                json.loads(p.read_text())["status"] == "importing"
                for p in self.directory.glob("*.json")
            ):
                raise ValueError("已有服务器 ISO 正在导入，请完成后再导入下一份。")
            try:
                with self.open_source(body["source_id"], body["filename"]) as stream:
                    info = os.fstat(stream.fileno())
                if source_fingerprint(info) != body["fingerprint"]:
                    raise ValueError("来源 ISO 已改变，请刷新并重新选择。")
            except OSError as error:
                raise ValueError("来源 ISO 不可读取，请刷新或检查挂载及权限。") from error
            source = next(s for s in self.settings["sources"] if s["id"] == body["source_id"])
            row = self.begin(
                {
                    "name": body["name"],
                    "size": info.st_size,
                    "filename": body["filename"],
                    "sha256": body["sha256"],
                },
                owner,
            )
            row.pop("revision", None)
            row["owner"] = owner
            row.update(
                status="importing",
                pending_operation="import",
                source={
                    "id": source["id"],
                    "name": source["name"],
                    "filename": body["filename"],
                    "fingerprint": body["fingerprint"],
                },
            )
            self.save(row)
        threading.Thread(
            target=self.copy_source, args=(row,), daemon=True, name="iso-import-" + row["id"]
        ).start()
        return self.public(row)

    def copy_source(self, row):
        try:
            source = row["source"]
            with self.open_source(source["id"], source["filename"]) as stream:
                if source_fingerprint(os.fstat(stream.fileno())) != source["fingerprint"]:
                    raise ValueError("来源 ISO 已改变，请取消此版本并刷新后重新选择。")
                row.update(received=0, status="importing", pending_operation="import")
                deadline = time.monotonic() + 1800
                last_saved = 0
                with (self.root / row["id"] / "install.iso").open("wb") as out:
                    while block := stream.read(8 * 1024**2):
                        if time.monotonic() > deadline:
                            raise ValueError("复制超过 30 分钟截止时间，请检查存储后重新准备。")
                        if row["received"] + len(block) > row["size"]:
                            raise ValueError("来源 ISO 大小已改变，请重新选择。")
                        out.write(block)
                        row["received"] += len(block)
                        if time.monotonic() - last_saved >= 1:
                            self.save(row)
                            last_saved = time.monotonic()
                    out.flush()
                    os.fsync(out.fileno())
                if (
                    row["received"] != row["size"]
                    or source_fingerprint(os.fstat(stream.fileno())) != source["fingerprint"]
                ):
                    raise ValueError("复制期间来源 ISO 已改变，请重新选择。")
            with self.open_source(source["id"], source["filename"]) as current:
                if source_fingerprint(os.fstat(current.fileno())) != source["fingerprint"]:
                    raise ValueError("复制期间来源 ISO 被替换，请重新选择。")
            row.update(status="preparing", pending_operation="prepare")
            self.save(row)
        except Exception as error:
            row.update(
                status="failed",
                error=str(error)
                if isinstance(error, ValueError)
                else "来源 ISO 复制失败；检查只读挂载、权限和材料空间。",
            )
            self.save(row)
            return
        self.extract(row)

    def begin(self, body, owner):
        if set(body) != {"name", "size", "filename", "sha256"}:
            raise ValueError("请提供 OS 名称、ISO 文件及可选 SHA256。")
        if not self.settings.get("public_base_url"):
            raise ValueError("站点尚未配置原生 PXE 材料目录与外部发布地址。")
        if not isinstance(body["name"], str) or not 1 <= len(body["name"].strip()) <= 100:
            raise ValueError("OS 名称需为 1–100 字符。")
        if type(body["size"]) is not int or not 32768 <= body["size"] <= self.settings.get(
            "max_size", 16 * 1024**3
        ):
            raise ValueError("ISO 大小无效或超过站点上限。")
        if not isinstance(body["filename"], str) or not body["filename"].lower().endswith(".iso"):
            raise ValueError("请选择 ISO 文件。")
        if body["sha256"] and not re.fullmatch("[a-fA-F0-9]{64}", body["sha256"]):
            raise ValueError("SHA256 必须为 64 位十六进制。")
        self.root.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(self.root).free < body["size"] * 2 + 256 * 1024**2:
            raise ValueError("材料目录剩余空间不足，请先扩容或清理已确认不用的材料。")
        row = {
            "id": str(uuid.uuid4()),
            "name": body["name"].strip(),
            "size": body["size"],
            "filename": Path(body["filename"]).name,
            "expected_sha256": body["sha256"].lower(),
            "owner": owner,
            "status": "uploading",
            "received": 0,
            "created_at": time.time(),
            "auto_register": True,
            "materials": [],
        }
        (self.root / row["id"]).mkdir(mode=0o700)
        (self.root / row["id"] / "install.iso").touch(mode=0o644)
        self.save(row)
        return self.public(row)

    def chunk(self, key, owner, offset, stream, length):
        if not 1 <= length <= 8 * 1024**2:
            raise ValueError("分块大小需为 1 字节至 8 MiB。")
        with self.lock:
            row = self.read(key)
            if (
                row["owner"] != owner
                or row["status"] != "uploading"
                or row["received"] != offset
                or offset + length > row["size"]
            ):
                raise ValueError("上传偏移、会话或状态不匹配；请查询已接收位置后继续。")
            path = self.root / row["id"] / "install.iso"
            with path.open("r+b") as out:
                out.seek(offset)
                remaining = length
                while remaining:
                    block = stream.read(min(remaining, 1024**2))
                    if not block:
                        out.truncate(offset)
                        raise ValueError("上传中断，可从本块起点继续。")
                    out.write(block)
                    remaining -= len(block)
                out.truncate(offset + length)
                out.flush()
                os.fsync(out.fileno())
            row["received"] += length
            self.save(row)
            return self.public(row)

    def prepare(self, key, owner):
        with self.lock:
            row = self.read(key)
            if (
                row["owner"] != owner
                or row["status"] != "uploading"
                or row["received"] != row["size"]
            ):
                raise ValueError("ISO 尚未完整上传或请求已发送。")
            row.update(status="preparing", pending_operation="prepare")
            row.pop("error", None)
            self.save(row)
        threading.Thread(target=self.extract, args=(row,), daemon=True, name="iso-" + key).start()
        return self.public(row)

    def extract(self, row):
        folder = self.root / row["id"]
        try:
            for name in ("kernel", "initrd", "info.txt"):
                (folder / name).unlink(missing_ok=True)
            iso = folder / "install.iso"
            checksum = file_sha(iso)
            if row["expected_sha256"] and checksum != row["expected_sha256"]:
                raise ValueError("ISO SHA256 与预期不匹配。")
            subprocess.run(
                [
                    "xorriso",
                    "-osirrox",
                    "on",
                    "-indev",
                    str(iso),
                    "-extract",
                    "/.disk/info",
                    str(folder / "info.txt"),
                ],
                check=True,
                capture_output=True,
                timeout=60,
            )
            info = (folder / "info.txt").read_text().strip()
            if "ubuntu" not in info.lower() or "server" not in info.lower():
                raise ValueError(
                    "此 ISO 未匹配 Ubuntu Server 安装器；需要相应安装器适配后才能启用自动安装。"
                )
            release = re.search(r"(?i)ubuntu(?:[- ]server)?\s+(\d+\.\d+)", info)
            if not release:
                raise ValueError("无法从 ISO 元数据识别 Ubuntu 发行版本。")
            arch = "x86_64" if "amd64" in info else "aarch64" if "arm64" in info else None
            if not arch:
                raise ValueError("无法从 ISO 元数据识别支持的 CPU 架构。")
            for src, dst in [("/casper/vmlinuz", "kernel"), ("/casper/initrd", "initrd")]:
                subprocess.run(
                    [
                        "xorriso",
                        "-osirrox",
                        "on",
                        "-indev",
                        str(iso),
                        "-extract",
                        src,
                        str(folder / dst),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=180,
                )
            materials = []
            for name, filename in [
                ("iso", "install.iso"),
                ("kernel", "kernel"),
                ("initrd", "initrd"),
            ]:
                path = folder / filename
                path.chmod(0o644)
                materials.append(
                    {
                        "name": name,
                        "url": self.settings["public_base_url"].rstrip("/")
                        + "/"
                        + row["id"]
                        + "/"
                        + filename,
                        "verification_url": self.settings.get(
                            "verification_base_url", self.settings["public_base_url"]
                        ).rstrip("/")
                        + "/"
                        + row["id"]
                        + "/"
                        + filename,
                        "size": path.stat().st_size,
                        "sha256": checksum if name == "iso" else file_sha(path),
                    }
                )
            # The service runs with umask 077: chmod explicitly only after immutable files are complete.
            folder.chmod(0o755)
            client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for material in materials:
                for url in {material["verification_url"]}:
                    with client.open(
                        urllib.request.Request(url, method="HEAD"), timeout=30
                    ) as response:
                        if int(response.headers.get("Content-Length", 0)) != material["size"]:
                            raise ValueError("PXE 发布材料长度不匹配。")
            row.pop("pending_operation", None)
            row.update(
                status="prepared",
                architecture=arch,
                os_release=release.group(1),
                iso_info=info,
                installer="ubuntu-server",
                materials=materials,
            )
        except Exception as error:
            row.update(
                status="failed",
                error=str(error)
                if isinstance(error, ValueError)
                else "ISO 读取/提取失败；检查 ISO 格式和站点工具。",
            )
        self.save(row)
        if row["status"] == "prepared" and row.get("auto_register"):
            try:
                self.register({"id": row["id"], "revision": digest(row)})
            except Exception:
                # register persists the exact pending stage; never re-extract or replay here.
                pass

    def register(self, body):
        with self.lock:
            return self._register(body)

    def _register(self, body):
        if set(body) != {"id", "revision"}:
            raise ValueError("请刷新并选择已准备的 OS。")
        row = self.read(body["id"])
        if row["status"] != "prepared" or digest(row) != body["revision"]:
            raise ValueError("材料尚未准备或版本已变化。")
        iso = next(m for m in row["materials"] if m["name"] == "iso")
        request = {
            "id": {"value": row["id"]},
            "name": row["name"],
            "description": row.get("iso_info", row["os_release"]),
            "is_active": False,
            "allow_override": True,
            "phone_home_enabled": False,
            "ipxe_template_id": {"value": "c4b1d4f6-69ba-5f55-90cd-ab2acd002475"},
            "ipxe_template_parameters": [
                {"name": "kernel_params", "value": ubuntu_boot_parameters(iso["url"])}
            ],
            "ipxe_template_artifacts": [
                {"name": m["name"], "url": m["url"], "sha": m["sha256"], "cache_strategy": 1}
                for m in row["materials"]
                if m["name"] != "iso"
            ],
        }
        row.update(status="registering", pending_operation="register")
        self.save(row)
        try:
            ids = {
                value_id(i) for i in self.adapter.rpc("FindOperatingSystemIds", {}).get("ids", [])
            }
            result = (
                self.adapter.rpc("GetOperatingSystem", {"value": row["id"]})
                if row["id"] in ids
                else self.adapter.rpc("CreateOperatingSystem", request)
            )
            if value_id(result.get("id")) != row["id"]:
                raise RuntimeError("OS 登记回执不匹配。")
            native = self.adapter.rpc("GetOperatingSystem", {"value": row["id"]})
            self.verify_native(row, native)
            row["status"] = "registered"
            row.pop("pending_operation", None)
            row.pop("error", None)
            self.save(row)
            return self.public(row)
        except Exception:
            row["status"] = "needs_attention"
            row["error"] = "NICo 登记结果需核对，未自动重试。"
            self.save(row)
            raise

    def verify_native(self, row, native):
        expected = {
            (m["name"], m["url"], m["sha256"]) for m in row["materials"] if m["name"] != "iso"
        }
        actual = {(m["name"], m["url"], m["sha"]) for m in native.get("ipxeTemplateArtifacts", [])}
        iso = next(m for m in row["materials"] if m["name"] == "iso")
        params = native.get("ipxeTemplateParameters", [])
        # Existing immutable definitions remain valid; never rewrite an OS used by a task.
        allowed = [
            [
                {
                    "name": "kernel_params",
                    "value": ubuntu_boot_parameters(iso["url"], serial_console=serial),
                }
            ]
            for serial in (True, False)
        ]
        if (
            native.get("name") != row["name"]
            or expected != actual
            or value_id(native.get("ipxeTemplateId")) != "c4b1d4f6-69ba-5f55-90cd-ab2acd002475"
            or params not in allowed
        ):
            raise ValueError("NICo记录与同源ISO、kernel/initrd或启动参数不一致，未覆盖原生记录。")

    def activate(self, body):
        if set(body) != {"id", "active"} or type(body["active"]) is not bool:
            raise ValueError("OS 启用参数无效。")
        key = str(uuid.UUID(body["id"]))
        row = self.read(key)
        if row["status"] != "registered":
            raise ValueError("仅允许启用已经完整准备并登记的 OS 版本。")
        result = self.adapter.rpc(
            "UpdateOperatingSystem", {"id": {"value": key}, "is_active": body["active"]}
        )
        if result.get("isActive", False) != body["active"]:
            raise RuntimeError("OS 启用状态读回不匹配。")
        return {"id": key, "active": body["active"]}

    def recover(self, body, owner):
        if set(body) != {"id", "revision"}:
            raise ValueError("请刷新后核对 OS。")
        with self.lock:
            row = self.read(body["id"])
            if digest(row) != body["revision"] or row["owner"] != owner:
                raise ValueError("OS 版本或操作员已变化。")
            if row["status"] not in ("failed", "needs_attention"):
                raise ValueError("该状态无需恢复。")
            if row.get("pending_operation") == "register":
                ids = {
                    value_id(i)
                    for i in self.adapter.rpc("FindOperatingSystemIds", {}).get("ids", [])
                }
                if row["id"] in ids:
                    native = self.adapter.rpc("GetOperatingSystem", {"value": row["id"]})
                    self.verify_native(row, native)
                    row["status"] = "registered"
                else:
                    row["status"] = "prepared"
                row.pop("pending_operation", None)
                row.pop("error", None)
                self.save(row)
                return self.public(row)
            if row.get("pending_operation") == "import":
                if any(
                    json.loads(p.read_text())["status"] == "importing"
                    for p in self.directory.glob("*.json")
                ):
                    raise ValueError("已有服务器 ISO 正在导入，请完成后再重新准备。")
                row.update(status="importing")
                row.pop("error", None)
                self.save(row)
                threading.Thread(
                    target=self.copy_source,
                    args=(row,),
                    daemon=True,
                    name="iso-import-" + row["id"],
                ).start()
                return self.public(row)
            if row["received"] != row["size"]:
                raise ValueError("ISO 不完整，请继续上传或取消。")
            row.update(status="preparing", pending_operation="prepare")
            row.pop("error", None)
            self.save(row)
        threading.Thread(
            target=self.extract, args=(row,), daemon=True, name="iso-" + row["id"]
        ).start()
        return self.public(row)

    def cancel(self, body, owner):
        if set(body) != {"id", "revision"}:
            raise ValueError("请刷新后取消未登记上传。")
        with self.lock:
            row = self.read(body["id"])
            if row["owner"] != owner or digest(row) != body["revision"]:
                raise ValueError("OS 版本或操作员已变化。")
            if row["status"] not in ("uploading", "failed", "prepared") and not (
                row["status"] == "needs_attention" and row.get("pending_operation") == "import"
            ):
                raise ValueError("只能取消已停止且未登记的上传；不删除已登记 OS。")
            ids = {
                value_id(i) for i in self.adapter.rpc("FindOperatingSystemIds", {}).get("ids", [])
            }
            if row["id"] in ids:
                raise ValueError("NICo 已有此 OS 记录，不能删除材料。")
            shutil.rmtree(self.root / row["id"])
            (self.directory / (row["id"] + ".json")).unlink()
            return {"id": row["id"], "status": "cancelled"}

    def usable(self, key, arch):
        row = self.read(key)
        native = self.adapter.rpc("GetOperatingSystem", {"value": row["id"]})
        if (
            row["status"] != "registered"
            or row.get("architecture") != arch
            or not native.get("isActive")
        ):
            raise ValueError("目标 OS 未启用、材料未准备或架构不兼容。")
        expected = {
            (m["name"], m["url"], m["sha256"]) for m in row["materials"] if m["name"] != "iso"
        }
        actual = {(m["name"], m["url"], m["sha"]) for m in native.get("ipxeTemplateArtifacts", [])}
        iso_url = next(m["url"] for m in row["materials"] if m["name"] == "iso")
        params = next(
            (
                p.get("value", "")
                for p in native.get("ipxeTemplateParameters", [])
                if p["name"] == "kernel_params"
            ),
            "",
        )
        if (
            expected != actual
            or value_id(native.get("ipxeTemplateId")) != "c4b1d4f6-69ba-5f55-90cd-ab2acd002475"
            or "url=" + iso_url + " " not in params
        ):
            raise ValueError("NICo OS 原生定义与固定材料不同，需重新核对。")
        row["native_revision"] = digest(
            {
                k: native.get(k)
                for k in (
                    "name",
                    "type",
                    "allowOverride",
                    "phoneHomeEnabled",
                    "userData",
                    "ipxeScript",
                    "ipxeTemplateId",
                    "ipxeTemplateParameters",
                    "ipxeTemplateArtifacts",
                    "ipxeTemplateDefinitionHash",
                )
            }
        )
        return row


def file_sha(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b""):
            result.update(block)
    return result.hexdigest()


def source_fingerprint(info):
    return digest([info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns])
