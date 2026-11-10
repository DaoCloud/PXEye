"""Validate profile text files and merge them into target-system cloud-init."""

import copy
import re
from posixpath import normpath

MAX_FILES = 32
MAX_FILE_BYTES = 64 * 1024
MAX_TOTAL_BYTES = 256 * 1024
RESERVED = (
    "/proc",
    "/sys",
    "/dev",
    "/run",
    "/var/run",
    "/var/lib/cloud",
    "/etc/cloud",
    "/etc/netplan",
    "/etc/network",
    "/etc/ssh",
    "/etc/passwd",
    "/etc/shadow",
    "/etc/group",
    "/etc/gshadow",
    "/etc/sudoers",
    "/etc/sudoers.d",
    "/etc/hostname",
    "/etc/hosts",
    "/etc/resolv.conf",
    "/etc/fstab",
    "/etc/crypttab",
    "/etc/nico-installation.json",
    "/var/log/nico-installation",
)


def overlaps(left, right):
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


def normalize_custom_files(files):
    if not isinstance(files, list) or len(files) > MAX_FILES:
        raise ValueError("自定义文件必须为列表，最多32个文件。")
    result, total = [], 0
    for item in files:
        if not isinstance(item, dict) or set(item) - {
            "path",
            "content",
            "owner",
            "permissions",
            "append",
        }:
            raise ValueError("自定义文件含未知字段。")
        path, content = item.get("path"), item.get("content")
        if (
            not isinstance(path, str)
            or not path.startswith("/")
            or len(path) > 4096
            or "\\" in path
            or any(ord(c) < 32 or ord(c) == 127 for c in path)
            or any(part in ("", ".", "..") for part in path[1:].split("/"))
        ):
            raise ValueError("自定义文件路径必须为绝对文件路径，不含空路径段、控制字符或 . / ..。")
        if ".ssh" in path.split("/") or any(overlaps(path, reserved) for reserved in RESERVED):
            raise ValueError(f"自定义文件不能覆盖系统登录、网络、cloud-init或安装身份配置：{path}")
        if any(overlaps(path, row["path"]) for row in result):
            raise ValueError(f"自定义文件路径重复或存在文件与目录冲突：{path}")
        if not isinstance(content, str) or "\x00" in content:
            raise ValueError(f"文件内容必须为无NUL字符的UTF-8文本：{path}")
        try:
            size = len(content.encode("utf-8"))
        except UnicodeError:
            raise ValueError(f"文件内容不是有效UTF-8文本：{path}") from None
        total += size
        if size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise ValueError("单个文件内容最多64 KiB，全部文件内容合计最多256 KiB。")
        owner = item.get("owner", "root:root")
        if not isinstance(owner, str) or not re.fullmatch(
            r"(?:[a-z_][a-z0-9_-]{0,31}|[0-9]+):(?:[a-z_][a-z0-9_-]{0,31}|[0-9]+)", owner
        ):
            raise ValueError(f"所属用户与组格式应为 user:group 或数字UID:GID：{path}")
        permissions = item.get("permissions", "0644")
        if not isinstance(permissions, str) or not re.fullmatch(r"0[0-7]{3}", permissions):
            raise ValueError(f"文件权限必须为四位八进制字符串，例如0644：{path}")
        append = item.get("append", False)
        if type(append) is not bool:
            raise ValueError(f"文件追加开关必须为布尔值：{path}")
        result.append(
            dict(path=path, content=content, owner=owner, permissions=permissions, append=append)
        )
    return result


def apply_custom_files(autoinstall, files):
    files = normalize_custom_files(files)
    if not files:
        return
    cloud = autoinstall.setdefault("user-data", {})
    # Inspect both installer and target-system entries without changing either.
    existing = []
    for entries in (autoinstall.get("write_files", []), cloud.get("write_files", [])):
        if not isinstance(entries, list):
            raise ValueError("基础模板write_files格式无效。")
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                raise ValueError("基础模板write_files缺少文件路径。")
            existing.append(normpath(entry["path"]))
    for row in files:
        if any(overlaps(row["path"], path) for path in existing):
            raise ValueError(f"自定义文件与基础模板文件路径冲突：{row['path']}")
    cloud.setdefault("write_files", []).extend(copy.deepcopy(files))
    for row in cloud["write_files"][-len(files) :]:
        row["defer"] = True
