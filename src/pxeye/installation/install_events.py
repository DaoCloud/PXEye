"""Task-bound, authenticated installer observations; no credentials on the event wire."""

import hashlib
import hmac
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

from pxeye.common import atomic_json


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def event_key(adapter, binding):
    context = {k: binding[k] for k in ("task_id", "attempt", "serial", "instance_id")}
    return hmac.new(
        (adapter.identity / "ssh_key").read_bytes(),
        b"nico-installer-v1:" + canonical(context),
        hashlib.sha256,
    ).hexdigest()


def inject(adapter, ai, device, task):
    if not task["id"].startswith("UI-"):
        return None
    url = adapter.config.get("installer_events_url", "")
    parsed = urlsplit(url)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path != "/api/installer-events"
    ):
        raise ValueError(
            "站点缺少有效的 installer_events_url；请配置安装环境可达的内部事件接收地址。"
        )
    binding = {
        "task_id": task["id"],
        "attempt": str((task.get("retry_attempt") or {}).get("number", 0)),
        "serial": device["serial"],
        "instance_id": device["instance_id"],
        "disk_serial": device.get("disk_serial"),
    }
    config = binding | {
        "url": url,
        "key": event_key(adapter, binding),
        "serial_console": adapter.config.get("serial_consoles", {}).get(device["serial"], ""),
        "timeout": adapter.config.get("task_timeout_seconds", 2400) + 600,
    }
    if config["serial_console"] and not re.fullmatch(
        r"(?:ttyS|ttyAMA|hvc|ttyTHS)\d+", config["serial_console"]
    ):
        raise ValueError("站点串口配置格式无效。")
    ai.setdefault("user-data", {})["nico-ui-observer"] = config
    source = Path(__file__).with_name("installer_runtime.py").read_text()
    # Read the signing secret from the delivered file, not from a logged command.
    bootstrap = "from pathlib import Path\nimport subprocess,yaml\n"
    bootstrap += "live=Path('/autoinstall.yaml')\ndata=yaml.safe_load(live.read_text())\nai=data.get('autoinstall',data)\n"
    bootstrap += "metadata=ai['user-data'].pop('nico-ui-observer')\nlive.write_text(yaml.safe_dump(data,sort_keys=False))\n"
    bootstrap += (
        "p=Path('/run/nico-ui-observer.py')\np.write_text('CONFIG = ' + repr(metadata) + '\\n' + "
        + repr(source)
        + ")\np.chmod(0o600)\n"
    )
    unit = (
        "[Unit]\nDescription=NICo installation observer\nBefore=shutdown.target\n"
        "After=network.target\n[Service]\nType=simple\nExecStart=/usr/bin/python3 /run/nico-ui-observer.py\n"
        "ExecStop=/usr/bin/python3 /run/nico-ui-observer.py shutdown\nTimeoutStopSec=15\n"
    )
    bootstrap += (
        "Path('/run/systemd/system/nico-ui-observer.service').write_text(" + repr(unit) + ")\n"
    )
    bootstrap += "subprocess.run(['systemctl','daemon-reload'],check=True)\nsubprocess.run(['systemctl','start','nico-ui-observer.service'],check=True)\n"
    ai.setdefault("early-commands", []).insert(
        0, "python3 - <<'NICO_OBSERVER'\n" + bootstrap + "\nNICO_OBSERVER"
    )
    late = "python3 /run/nico-ui-observer.py identity # NICO_UI_HOSTKEY " + task["id"]
    ai.setdefault("late-commands", []).append(late)
    return binding


def freeze(adapter, binding, user_data):
    if binding:
        folder = adapter.data / "tasks" / binding["task_id"]
        folder.mkdir(parents=True, mode=0o700, exist_ok=True)
        atomic_json(
            folder / "event-binding.json",
            binding | {"user_data_sha256": hashlib.sha256(user_data.encode()).hexdigest()},
        )


def receive(adapter, store, body):
    if set(body) != {"event", "signature"} or not isinstance(body["event"], dict):
        raise ValueError("安装事件格式无效。")
    event = body["event"]
    if not re.fullmatch(r"UI-[0-9]{8}-[a-f0-9]{10}", str(event.get("task_id", ""))):
        raise ValueError("安装事件任务无效。")
    task = store.get(event["task_id"])
    if not task or task["status"] not in ("running", "needs_attention"):
        raise ValueError("安装事件任务已结束或未执行。")
    binding = json.loads((adapter.data / "tasks" / task["id"] / "event-binding.json").read_text())
    if (
        task.get("user_data_sha256") != binding["user_data_sha256"]
        or any(
            event.get(k) != binding[k]
            for k in ("task_id", "attempt", "serial", "instance_id", "disk_serial")
        )
        or event.get("stage") not in ("started", "identity", "installed", "shutdown", "failed")
    ):
        raise ValueError("安装事件与本轮冻结配置不一致。")
    signature = hmac.new(
        bytes.fromhex(event_key(adapter, binding)), canonical(event), hashlib.sha256
    ).hexdigest()
    if not isinstance(body["signature"], str) or not hmac.compare_digest(
        signature, body["signature"]
    ):
        raise ValueError("安装事件认证失败。")
    if not re.fullmatch(r"[0-9a-f-]{36}", str(event.get("boot_id", ""))):
        raise ValueError("安装事件启动身份无效。")
    if event["stage"] in ("identity", "installed", "shutdown"):
        if not re.fullmatch(
            r"ssh-ed25519 [A-Za-z0-9+/=]+(?: [^\r\n]*)?", str(event.get("host_key", ""))
        ):
            raise ValueError("安装事件缺少主机身份。")
    if event["stage"] in ("installed", "shutdown") and event.get("completion_stages") != [
        "Late/run",
        "Install/install",
    ]:
        raise ValueError("安装事件缺少成功收尾证据。")
    with store.db() as db:
        prior = db.execute(
            "SELECT payload FROM installer_events WHERE task_id=? AND attempt=? LIMIT 1",
            (task["id"], binding["attempt"]),
        ).fetchone()
        if prior and json.loads(prior["payload"])["boot_id"] != event["boot_id"]:
            raise ValueError("同一安装尝试出现不同启动身份，拒绝复用旧完成证据。")
        db.execute(
            "INSERT OR IGNORE INTO installer_events VALUES (?,?,?,?,?)",
            (task["id"], binding["attempt"], event["stage"], json.dumps(event), time.time()),
        )
    return {"accepted": True}


def observations(adapter, store, task):
    path = adapter.data / "tasks" / task["id"] / "event-binding.json"
    if not path.exists():
        return {}
    binding = json.loads(path.read_text())
    if binding.get("user_data_sha256") != task.get("user_data_sha256"):
        return {}
    with store.db() as db:
        rows = db.execute(
            "SELECT stage,payload,received FROM installer_events WHERE task_id=? AND attempt=?",
            (task["id"], binding["attempt"]),
        ).fetchall()
    return {r["stage"]: json.loads(r["payload"]) | {"received_at": r["received"]} for r in rows}
