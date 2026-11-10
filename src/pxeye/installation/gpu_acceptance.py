"""Read-only, bounded acceptance of a deployment-owned GPU state file."""

import datetime
import hashlib
import json
import time

from pxeye.installation.acceptance_skips import refresh_skips

TIMEOUT_SECONDS = 3600
POLL_SECONDS = 10
READ_SCRIPT = """import json
from pathlib import Path
path = Path('/var/lib/metal-deployer/state.json')
try:
    with path.open('rb') as stream:
        raw = stream.read(262145)
    if len(raw) > 262144:
        raise ValueError('state.json exceeds 256 KiB')
    state = json.loads(raw)
    print(json.dumps({'state': state, 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}))
except FileNotFoundError:
    print(json.dumps({'waiting': True}))
except (ValueError, UnicodeError, PermissionError):
    print(json.dumps({'invalid': True}))
"""


def timestamp(value):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("GPU 状态时间格式无效。")
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.timestamp()
    except (ValueError, OverflowError):
        raise ValueError("GPU 状态时间需为带时区的 ISO 8601 时间。") from None


def text(value, field):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 256
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError("GPU 状态字段无效：" + field)
    return value


def validate_state(payload, task, initial):
    state = payload.get("state")
    if not isinstance(state, dict) or type(state.get("schema")) is not int or state["schema"] != 1:
        raise ValueError("GPU 状态 schema 不受支持，应为 1。")
    if payload.get("boot_id") != initial["boot_id"] or state.get("boot_id") != initial["boot_id"]:
        raise ValueError("GPU 状态不属于本轮首启 boot_id。")
    # task_id is optional for existing producers, but must match when provided.
    if "task_id" in state and state["task_id"] != task["id"]:
        raise ValueError("GPU 状态 task_id 与本轮任务不符。")
    text(state.get("iso_version"), "iso_version")
    start, updated = timestamp(state.get("started_at")), timestamp(state.get("updated_at"))
    if start < task["created_at"] - 300 or updated < start or updated > time.time() + 300:
        raise ValueError("GPU 状态时间不属于本轮安装，或节点时钟异常。")
    overall = state.get("overall")
    if overall not in ("pending", "running", "success", "failed"):
        raise ValueError("GPU overall 状态无效。")
    stages = state.get("stages")
    if not isinstance(stages, list) or not 1 <= len(stages) <= 100:
        raise ValueError("GPU 阶段清单无效或为空。")
    clean, names = [], set()
    for stage in stages:
        if not isinstance(stage, dict):
            raise ValueError("GPU 阶段格式无效。")
        name = text(stage.get("name"), "stage.name")
        status = stage.get("status")
        if name in names or status not in ("pending", "running", "success", "failed"):
            raise ValueError("GPU 阶段重复或状态无效。")
        names.add(name)
        item = {"name": name, "status": status}
        if "rc" in stage:
            if type(stage["rc"]) is not int:
                raise ValueError("GPU 阶段 rc 应为整数。")
            item["rc"] = stage["rc"]
        if status in ("success", "failed") and "rc" not in item:
            raise ValueError("GPU 结束阶段缺少退出码。")
        if status == "success" and item["rc"] != 0:
            raise ValueError("GPU 阶段成功状态与退出码不一致。")
        for field in ("start", "end"):
            if field in stage:
                timestamp(stage[field])
                item[field] = stage[field]
        if "log" in stage:
            item["log"] = text(stage["log"], "stage.log")
        clean.append(item)
    current = state.get("current_stage", "")
    if not isinstance(current, str) or current and current not in names:
        raise ValueError("GPU current_stage 不在阶段清单中。")
    if overall == "success" and any(s["status"] != "success" for s in clean):
        raise ValueError("GPU overall 成功但仍有未成功阶段。")
    return {
        "status": "failed"
        if overall == "failed" or any(s["status"] == "failed" or s.get("rc", 0) != 0 for s in clean)
        else overall,
        "schema": 1,
        "iso_version": state["iso_version"],
        "boot_id": state["boot_id"],
        "current_stage": current,
        "started_at": state["started_at"],
        "updated_at": state["updated_at"],
        "stages": clean,
        "state_sha256": hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest(),
    }


def wait_for_gpu_environment(executor, task, device, known, initial, console):
    enabled = task.get("gpu_environment_check", False)
    initial.setdefault("checks", {})

    def manually_skipped():
        skips = refresh_skips(executor, task)
        if "gpu_environment" not in skips:
            return False
        task["gpu_check"] = {"status": "skipped", "detail": "操作员手动跳过。"}
        initial["checks"]["gpu_environment"] = None
        initial["acceptance_skips"] = skips
        executor.store.save(task)
        return True

    if manually_skipped():
        return
    if not enabled:
        task["gpu_check"] = {"status": "skipped", "detail": "安装方案未启用 GPU 环境检查。"}
        initial["checks"]["gpu_environment"] = None
        executor.store.save(task)
        return
    if not initial.get("boot_id"):
        raise ValueError("无法读取首启 boot_id，不能核对 GPU 状态。")
    existing = task.get("gpu_check", {})
    if existing.get("status") == "success" and existing.get("boot_id") == initial["boot_id"]:
        initial["checks"]["gpu_environment"] = True
        initial["gpu_environment"] = existing
        return
    if task.get("normal_reboot_requested"):
        raise ValueError("缺少重启前 GPU 成功回执，不能通过最终验收。")
    executor.event(task, "gpu_check", "开始 GPU 环境检查：只读等待部署状态，完成后再进行重启验收。")
    deadline = time.monotonic() + TIMEOUT_SECONDS
    last = None
    try:
        while time.monotonic() < deadline:
            if manually_skipped():
                return
            executor.check_bound(device, task)
            console.poll()
            try:
                payload = json.loads(
                    executor.adapter.ssh(device, READ_SCRIPT, known=known, timeout=20)
                )
            except RuntimeError as error:
                if "主机密钥" in str(error) or "认证失败" in str(error):
                    raise ValueError("GPU 检查 SSH 身份或认证失败，请核对后继续验收。") from None
                payload = {"waiting": True}
            except (TimeoutError, OSError):
                payload = {"waiting": True}
            if manually_skipped():
                return
            if not isinstance(payload, dict) or payload.get("invalid"):
                raise ValueError("GPU 状态文件格式、大小或读取权限无效。")
            if payload.get("waiting"):
                result = {"status": "waiting", "detail": "等待可信 SSH 和 GPU 状态文件。"}
            else:
                result = validate_state(payload, task, initial)
            result["observed_at"] = time.time()
            task["gpu_check"] = result
            initial["checks"]["gpu_environment"] = result["status"] == "success"
            executor.store.save(task)
            marker = (result["status"], result.get("current_stage"))
            if marker != last:
                executor.event(
                    task,
                    "gpu_check",
                    "GPU 环境检查："
                    + result["status"]
                    + (" · " + result["current_stage"] if result.get("current_stage") else ""),
                )
                last = marker
            if result["status"] == "failed":
                failed = [
                    s["name"] + " rc=" + str(s.get("rc", "未知"))
                    for s in result["stages"]
                    if s["status"] == "failed" or s.get("rc", 0) != 0
                ]
                raise ValueError(
                    "GPU 环境检查失败："
                    + ("；".join(failed) or result.get("current_stage") or "部署报告失败")
                )
            if result["status"] == "success":
                initial["gpu_environment"] = result
                return
            time.sleep(min(POLL_SECONDS, max(0, deadline - time.monotonic())))
        raise TimeoutError("GPU 环境检查等待超过 60 分钟；保留现场，可继续本轮验收。")
    except (ValueError, TimeoutError) as error:
        task["gpu_check"] = {
            **task.get("gpu_check", {}),
            "status": "failed",
            "detail": str(error),
            "observed_at": time.time(),
        }
        initial["checks"]["gpu_environment"] = False
        executor.store.save(task)
        raise
