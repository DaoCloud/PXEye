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


def acceptance_summary(task, *, services_required=False):
    """Aggregate stored evidence without collecting or inventing new verification."""
    report = (
        task.get("after_reboot") or task.get("installation_checks") or task.get("initial") or {}
    )
    checks, errors = report.get("checks", {}), report.get("check_errors", {})
    skips = task.get("acceptance_skips", {})
    items = {}
    for name in CHECKS:
        if name in skips or (name == "gpu_environment" and not task.get("gpu_environment_check")):
            items[name] = "skipped"
        elif errors.get(name):
            items[name] = "failed"
        elif name == "gpu_environment":
            status = (task.get("gpu_check") or {}).get("status")
            items[name] = {"success": "passed", "failed": "failed"}.get(status, "pending")
        elif checks.get(name) is True:
            items[name] = "passed"
        elif name == "services" and checks.get(name) is False and not services_required:
            items[name] = "warning"
        else:
            items[name] = "failed" if checks.get(name) is False else "pending"
    # Unknown errors must not disappear merely because the displayed items were waived.
    extra_errors = [key for key, messages in errors.items() if messages and key not in CHECKS]
    state = (
        "failed"
        if extra_errors or "failed" in items.values()
        else "pending"
        if "pending" in items.values()
        else "completed"
    )
    return {"state": state, "items": items, "extra_errors": extra_errors}
