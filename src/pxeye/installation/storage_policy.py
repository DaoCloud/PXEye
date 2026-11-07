"""Resolve shared installation rules to one Scout disk before allocation."""

import fnmatch
import math


DEFAULT_STORAGE = {
    "selection": "unique",
    "serial_pattern": "",
    "model_pattern": "",
    "disk_type": "any",
    "min_gib": None,
    "max_gib": None,
    "efi_mib": 1024,
    "root_gib": None,
    "root_fstype": "ext4",
}


def normalize_storage(value=None):
    if value is None:
        return dict(DEFAULT_STORAGE)
    if not isinstance(value, dict) or set(value) - set(DEFAULT_STORAGE):
        raise ValueError("磁盘规则含未知字段。")
    rule = DEFAULT_STORAGE | value
    if rule["selection"] not in ("unique", "largest", "smallest") or rule["disk_type"] not in (
        "any",
        "nvme",
    ):
        raise ValueError("系统盘选择方式无效。")
    for key in ("serial_pattern", "model_pattern"):
        pattern = rule[key]
        if (
            not isinstance(pattern, str)
            or len(pattern) > 128
            or any(c in pattern for c in "\n\r\x00")
        ):
            raise ValueError("磁盘匹配格式无效。")
        rule[key] = pattern.strip()
    for key in ("min_gib", "max_gib", "root_gib"):
        number = rule[key]
        if number is not None and (
            type(number) not in (int, float)
            or not math.isfinite(number)
            or not 1 <= number <= 1048576
        ):
            raise ValueError("磁盘容量需为1–1048576 GiB，或留空。")
    if (
        rule["min_gib"] is not None
        and rule["max_gib"] is not None
        and rule["min_gib"] > rule["max_gib"]
    ):
        raise ValueError("磁盘最小容量不能大于最大容量。")
    if type(rule["efi_mib"]) is not int or not 512 <= rule["efi_mib"] <= 4096:
        raise ValueError("EFI大小需为512–4096 MiB整数。")
    if rule["root_gib"] is not None and rule["root_gib"] < 20:
        raise ValueError("固定根分区至少20 GiB；留空使用剩余空间。")
    if rule["root_fstype"] not in ("ext4", "xfs"):
        raise ValueError("根分区文件系统仅支持 ext4 或 XFS。")
    return rule


def storage_label(value=None):
    r = normalize_storage(value)
    root = "剩余空间" if r["root_gib"] is None else str(r["root_gib"]) + " GiB"
    return f"GPT · EFI {r['efi_mib']} MiB · {r['root_fstype']} 根分区 {root} · 无 swap"


def selection_label(value=None):
    r = normalize_storage(value)
    parts = [
        {"unique": "唯一匹配磁盘", "largest": "容量最大磁盘", "smallest": "容量最小磁盘"}[
            r["selection"]
        ]
    ]
    if r["disk_type"] == "nvme":
        parts.append("仅 NVMe")
    if r["serial_pattern"]:
        parts.append("序列号 " + r["serial_pattern"])
    if r["model_pattern"]:
        parts.append("型号 " + r["model_pattern"])
    if r["min_gib"] is not None or r["max_gib"] is not None:
        parts.append(
            f"{r['min_gib'] if r['min_gib'] is not None else '不限'}–{r['max_gib'] if r['max_gib'] is not None else '不限'} GiB"
        )
    return " · ".join(parts)


def scout_disks(info):
    nvmes = {d["serial"]: d for d in info.get("nvme_devices", []) if d.get("serial")}
    result = []
    for d in info.get("block_devices", []):
        if d.get("device_type") != "disk" or d.get("serial") in (None, "", "NO_SERIAL"):
            continue
        extra = nvmes.get(d["serial"])
        # The deployed Scout reports NVMe capacity in MiB; generic block devices
        # do not carry capacity. Unknown values never participate as zero.
        size = extra.get("size_mb") if extra else None
        result.append(
            d | {"size_bytes": int(size) * 1024**2 if size else None, "is_nvme": extra is not None}
        )
    return result


def select_disk(disks, storage=None, explicit=None):
    r = normalize_storage(storage)
    if explicit:
        matches = [d for d in disks if d["serial"] == explicit]
        if len(matches) != 1:
            raise ValueError("设备指定系统盘不在 Scout 清单中或序列号不唯一。")
        selected = matches[0]
        source = "设备指定"
    else:
        matches = [
            d
            for d in disks
            if (r["disk_type"] != "nvme" or d.get("is_nvme"))
            and (not r["serial_pattern"] or fnmatch.fnmatchcase(d["serial"], r["serial_pattern"]))
            and (
                not r["model_pattern"]
                or fnmatch.fnmatchcase(d.get("model", ""), r["model_pattern"])
            )
        ]
        needs_size = (
            r["selection"] in ("largest", "smallest")
            or r["min_gib"] is not None
            or r["max_gib"] is not None
        )
        if needs_size and any(not d.get("size_bytes") for d in matches):
            raise ValueError(
                "候选磁盘缺少 Scout 容量信息，无法执行容量规则；请在设备规划指定具体系统盘，或缩小到容量完整的候选盘。"
            )
        if r["min_gib"] is not None:
            matches = [d for d in matches if d["size_bytes"] >= r["min_gib"] * 1024**3]
        if r["max_gib"] is not None:
            matches = [d for d in matches if d["size_bytes"] <= r["max_gib"] * 1024**3]
        if matches and r["selection"] in ("largest", "smallest"):
            extreme = (max if r["selection"] == "largest" else min)(
                d["size_bytes"] for d in matches
            )
            matches = [d for d in matches if d["size_bytes"] == extreme]
        if len(matches) != 1:
            raise ValueError(
                "系统盘规则"
                + ("没有匹配磁盘" if not matches else "匹配多块磁盘（可能容量相同）")
                + "；请调整方案规则或在设备规划指定具体盘。"
            )
        selected, source = matches[0], "方案规则"
    serial = selected["serial"]
    if (
        not isinstance(serial, str)
        or not 1 <= len(serial) <= 128
        or any(c in serial for c in "*?[]\n\r\x00")
    ):
        raise ValueError("选中磁盘缺少安装器可精确匹配的序列号。")
    if sum(d["serial"] == serial for d in disks) != 1:
        raise ValueError("Scout 系统盘序列号不唯一。")
    if selected.get("size_bytes"):
        required = (r["root_gib"] if r["root_gib"] is not None else 20) * 1024**3 + (
            r["efi_mib"] + 8
        ) * 1024**2
        if selected["size_bytes"] < required:
            raise ValueError("选中磁盘容量不足以容纳EFI与根分区。")
    return {
        "serial": serial,
        "model": selected.get("model", ""),
        "size_bytes": selected.get("size_bytes"),
        "source": source,
        "rule": selection_label(r),
    }


def apply_partition_layout(ai, storage):
    r = normalize_storage(storage)
    config = ai["storage"]["config"]
    disks = [x for x in config if x["type"] == "disk"]
    mounts = {x.get("path"): x for x in config if x["type"] == "mount"}
    by_id = {x["id"]: x for x in config}
    if len(disks) != 1 or "/" not in mounts or "/boot/efi" not in mounts:
        raise ValueError("本版分区设置需要单盘GPT、EFI与根分区模板。")
    root_format = by_id[mounts["/"]["device"]]
    efi_format = by_id[mounts["/boot/efi"]["device"]]
    root, efi = by_id[root_format["volume"]], by_id[efi_format["volume"]]
    if (
        root["type"] != "partition"
        or efi["type"] != "partition"
        or root["device"] != disks[0]["id"]
        or efi["device"] != disks[0]["id"]
        or root_format.get("fstype") not in ("ext4", "xfs")
    ):
        raise ValueError("不支持变更非直接分区模板。")
    disks[0]["ptable"] = "gpt"
    efi["size"] = r["efi_mib"] * 1024**2
    root["size"] = -1 if r["root_gib"] is None else int(r["root_gib"] * 1024**3)
    root_format["fstype"] = r["root_fstype"]
    ai["storage"]["swap"] = {"size": 0}
