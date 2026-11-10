"""Task-scoped operator waivers; skipped checks are never reported as verified."""

import copy

CHECKS = {
    "installer": "安装器成功",
    "identity": "主机配置",
    "disk": "系统盘与 EFI 分区验证",
    "network": "网络配置",
    "ssh": "SSH 连通",
    "services": "DNS / HTTP / NTP 连通",
    "gpu_environment": "GPU 环境检查",
    "normal_reboot": "重启验收",
}


def refresh_skips(executor, task):
    current = executor.store.get(task["id"])
    task["acceptance_skips"] = (current or {}).get("acceptance_skips", {})
    return task["acceptance_skips"]


def apply_skips(result, task):
    report = result.get("report")
    if report is None:
        return result  # A waiver cannot supply missing SSH/collection evidence.
    skips = copy.deepcopy(task.get("acceptance_skips", {}))
    report["acceptance_skips"] = skips
    checks = report.setdefault("checks", {})
    errors = report.setdefault("check_errors", {})
    for name in skips:
        checks[name] = None
        errors.pop(name, None)
        if name == "disk":
            checks["partitions"] = None
    result["passed"] = not errors
    result["error"] = "；".join(message for messages in errors.values() for message in messages)
    return result
