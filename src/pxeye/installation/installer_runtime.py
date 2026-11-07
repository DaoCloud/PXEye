"""Runs only in the Ubuntu live installer; CONFIG is supplied by the UI renderer."""

import hashlib
import hmac
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    CONFIG = {}  # Injected by install_events before this standalone source.

STATE = Path("/run/nico-ui-observer-state.json")
LOG = Path("/var/log/installer/subiquity-server-debug.log")


def console_device():
    explicit = CONFIG.get("serial_console")
    if explicit and (Path("/dev") / explicit).exists():
        return explicit
    # Linux's active list reflects its runtime platform console, including ARM/hvc.
    try:
        active = Path("/sys/class/tty/console/active").read_text().split()
    except OSError:
        active = []
    serial = [x for x in active if re.fullmatch(r"(?:ttyS|ttyAMA|hvc|ttyTHS)\d+", x)]
    return serial[-1] if serial else "console"


def emit(stage, completed=False):
    serials = [
        p.read_text().strip()
        for p in (
            Path("/sys/class/dmi/id/product_serial"),
            Path("/sys/class/dmi/id/chassis_serial"),
        )
        if p.exists()
    ]
    if CONFIG["serial"] not in serials:
        raise RuntimeError("INSTALLER_SERIAL_MISMATCH")
    event = {k: CONFIG[k] for k in ("task_id", "attempt", "serial", "instance_id", "disk_serial")}
    event.update(
        stage=stage,
        boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        console=console_device(),
    )
    key = Path("/target/etc/ssh/ssh_host_ed25519_key.pub")
    if not key.exists():
        key = Path("/run/nico-ui-host-key")
    if key.exists():
        event["host_key"] = key.read_text().strip()
    if completed:
        event.update(
            completion_stages=["Late/run", "Install/install"],
            log_sha256=hashlib.sha256(LOG.read_bytes()).hexdigest(),
        )
    payload = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    signature = hmac.new(bytes.fromhex(CONFIG["key"]), payload, hashlib.sha256).hexdigest()
    data = json.dumps({"event": event, "signature": signature}).encode()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(
        CONFIG["url"], data=data, headers={"Content-Type": "application/json"}
    )
    for _ in range(3):
        try:
            with opener.open(request, timeout=3) as response:
                if response.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(1)
    return False


def completed():
    if not LOG.exists():
        return False
    text = LOG.read_text(errors="replace")
    return not re.search(
        r"(?<!\S)finish: subiquity/Install/install: (?:FAIL|ERROR):", text
    ) and all(
        re.search(r"(?<!\S)finish: subiquity/" + stage + r": SUCCESS:", text)
        for stage in ("Late/run", "Install/install")
    )


def console_write(text):
    try:
        fd = os.open("/dev/" + console_device(), os.O_WRONLY | os.O_NONBLOCK | os.O_NOCTTY)
        try:
            os.write(fd, text.encode()[:4096])
        finally:
            os.close(fd)
    except OSError:
        pass


def identity():
    # Choose the runtime console once; use it for the marker and installed GRUB.
    port = console_device()
    key = Path("/target/etc/ssh/ssh_host_ed25519_key.pub").read_text().strip()
    Path("/run/nico-ui-host-key").write_text(key)
    marker = "NICO_UI_HOSTKEY " + CONFIG["task_id"] + " " + key + "\n"
    try:
        fd = os.open("/dev/" + port, os.O_WRONLY | os.O_NONBLOCK | os.O_NOCTTY)
        try:
            os.write(fd, marker.encode())
        finally:
            os.close(fd)
    except OSError:
        pass  # The authenticated event is the independent identity channel.
    if port != "console":
        folder = Path("/target/etc/default/grub.d")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "99-nico-console.cfg").write_text(
            'GRUB_CMDLINE_LINUX_DEFAULT="console=tty0 console=' + port + ',115200n8"\n'
        )
        subprocess.run(
            ["curtin", "in-target", "--target=/target", "--", "update-grub"], check=True, timeout=60
        )
    # Identity reporting never means installation completed.
    emit("identity")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "watch"
    if mode == "identity":
        identity()
        return
    if mode == "shutdown":
        if completed():
            emit("shutdown", completed=True)
        return
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    began = time.monotonic()
    started = False
    installed = False
    offset = 0
    while time.monotonic() - began < CONFIG["timeout"]:
        if not started:
            started = emit("started")
        if LOG.exists():
            with LOG.open(errors="replace") as stream:
                stream.seek(offset)
                lines = stream.readlines()
                offset = stream.tell()
            for line in lines:
                # Commands are echoed into this log too; only emit real event records.
                match = re.search(
                    r"(?<!\S)(?:start: subiquity/(?:Install/install|Late/run)(?:/[A-Za-z0-9_./-]+)?:[^\r\n]*"
                    r"|finish: subiquity/(?:Install/install|Late/run)(?:/[A-Za-z0-9_./-]+)?: (?:SUCCESS|FAIL|ERROR):[^\r\n]*)$",
                    line.rstrip(),
                )
                if match:
                    console_write(match.group(0) + "\n")
        if completed() and not installed:
            installed = emit("installed", completed=True)
        if LOG.exists() and re.search(
            r"(?<!\S)finish: subiquity/Install/install: (?:FAIL|ERROR):",
            LOG.read_text(errors="replace"),
        ):
            emit("failed")
            return
        time.sleep(3)


if __name__ == "__main__":
    main()
