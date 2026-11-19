#!/usr/bin/env python3
"""Capture what a PXEye instance reads from NICo Core, as Core returned it.

Run inside a PXEye container. It starts a second, private copy of the console on a
loopback port, over a copy of the instance's persisted data, with every Core RPC,
Core CLI call and Redfish request recorded. It then requests the pages' API reads
from that copy and prints one JSON document to standard output:

    kubectl -n <namespace> exec -i deploy/<pxeye> -c pxeye -- python3 - < tools/core-capture.py > capture.json

The document holds every request and response verbatim, the console's own API
responses (the expected output when the capture is replayed), and the persisted
inputs those pages depend on. Values of fields whose names look like credentials are
replaced with "<redacted>"; nothing else is changed. The result still contains site
addresses, serial numbers and identifiers: keep it outside the repository, with
restricted access.

Safety: the private copy runs read-only (Core and Redfish accept reads only), cannot
write to Kubernetes, works on a copy of the data with queued and running tasks
cancelled, and is stopped when the capture ends. The running instance is not touched.
"""

import copy
import hashlib
import http.cookiejar
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

FORMAT = 1
SENSITIVE = re.compile(r"pass(word)?|secret|token|credential|private|^key$|_key$", re.I)
SKIP_FILES = re.compile(r"core-identity|credential|\.(key|crt|pem)$", re.I)
# Reads the console makes when its device pages load, in the order the browser asks.
# Site settings are left out: they read Kubernetes, which a capture does not record.
PAGE_READS = [
    "/api/readiness",
    "/api/resources",
    "/api/tasks",
    "/api/batches",
    "/api/networks",
    "/api/topology-layout",
    "/api/equipment",
    "/api/equipment-planning",
    "/api/instances",
    "/api/operating-systems",
    "/api/install-profiles",
    "/api/device-status",
]
TABLES = [
    "device_plans",
    "equipment_records",
    "equipment_planning",
    "install_profiles",
    "topology_layout",
    "tasks",
    "batches",
]


def redact(value):
    if isinstance(value, dict):
        return {
            k: ("<redacted>" if SENSITIVE.search(k) and v not in (None, "", {}, []) else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def site_config(data):
    config = json.loads(Path(os.environ.get("CONSOLE_CONFIG", "/config/site.json")).read_text())
    config.setdefault("site", {"name": "PXEye", "namespace": "", "deployment": ""})
    for name in ("deployment-site.json", "site-settings.json"):
        path = data / "config" / name
        if path.exists():
            saved = json.loads(path.read_text())
            if name == "site-settings.json":
                if isinstance(saved.get("core_url"), str):
                    config["site"]["name"] = saved.get("name", config["site"]["name"])
                    config["core_url"] = saved["core_url"]
            else:
                config.update(saved)
    return config


def copy_data(source, target):
    """The persisted inputs of the pages, without key material; tasks cannot resume."""
    for path in (source / "config").rglob("*"):
        if path.is_file() and not SKIP_FILES.search(str(path.relative_to(source))):
            destination = target / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
    database = source / "console.sqlite3"
    if database.exists():
        reader = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        writer = sqlite3.connect(target / "console.sqlite3")
        reader.backup(writer)
        reader.close()
        writer.execute("DELETE FROM sessions")
        writer.execute(
            "UPDATE tasks SET status='cancelled' WHERE status IN ('queued','running','needs_attention')"
        )
        writer.commit()
        writer.close()


def snapshot_inputs(data):
    """Persisted inputs, redacted, so a replay starts from the same local state."""
    files = {}
    for path in sorted((data / "config").rglob("*")):
        if path.is_file():
            text = path.read_text(errors="replace")
            try:
                text = json.dumps(redact(json.loads(text)), ensure_ascii=False)
            except ValueError:
                pass
            files[str(path.relative_to(data))] = text
    tables = {}
    database = data / "console.sqlite3"
    if database.exists():
        db = sqlite3.connect(database)
        db.row_factory = sqlite3.Row
        names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in TABLES:
            if table not in names:
                continue
            rows = []
            for row in db.execute(f"SELECT * FROM {table}"):
                row = dict(row)
                if isinstance(row.get("data"), str):
                    try:
                        row["data"] = json.dumps(
                            redact(json.loads(row["data"])), ensure_ascii=False
                        )
                    except ValueError:
                        pass
                rows.append(row)
            tables[table] = rows
        db.close()
    return {"files": files, "tables": tables}


def main():
    # The console logs to standard output; keep it for the document alone.
    output, sys.stdout = sys.stdout, sys.stderr
    from pxeye.api.http import Handler
    from pxeye.bootstrap import Application
    from pxeye.clients.core import CoreClient
    from pxeye.clients.redfish import RedfishClient
    from pxeye.deployment import kubernetes

    source = Path(os.environ.get("CONSOLE_DATA", "/data"))
    secrets = Path(os.environ.get("CONSOLE_SECRETS", "/secrets"))
    config = site_config(source)
    if not config.get("core_url"):
        sys.exit("This PXEye instance is not connected to a Core.")
    config["read_only"] = True
    config["rack_operations"] = True

    calls, lock = [], threading.Lock()

    def recorded(kind, original, describe):
        def wrapper(self, *args, **kwargs):
            started = time.time()
            entry = {"kind": kind, **describe(*args, **kwargs), "at": started}
            try:
                result = original(self, *args, **kwargs)
            except Exception as error:  # recorded, then raised as before
                entry.update(
                    error={"type": type(error).__name__, "message": str(error)},
                    seconds=round(time.time() - started, 3),
                )
                with lock:
                    calls.append(entry)
                raise
            entry.update(
                response=redact(copy.deepcopy(result)), seconds=round(time.time() - started, 3)
            )
            with lock:
                calls.append(entry)
            return result

        return wrapper

    CoreClient.rpc = recorded(
        "rpc", CoreClient.rpc, lambda method, body: {"method": method, "request": redact(body)}
    )
    CoreClient.core = recorded(
        "cli", CoreClient.core, lambda args, data=False: {"args": list(args), "data": data}
    )
    RedfishClient.redfish_request = recorded(
        "redfish",
        RedfishClient.redfish_request,
        lambda ip, path, credential, method="GET", body=None: {
            "host": ip,
            "path": path,
            "method": method,
        },
    )
    allowed = kubernetes.CurrentCluster.request

    def cluster_reads_only(self, path, body=None, *, method=None, **kwargs):
        if body is not None or method not in (None, "GET"):
            raise kubernetes.ClusterError("capture copy: Kubernetes writes are refused")
        return allowed(self, path, None, method=method, **kwargs)

    kubernetes.CurrentCluster.request = cluster_reads_only

    work = Path(tempfile.mkdtemp(prefix="pxeye-capture-"))
    try:
        data = work / "data"
        data.mkdir()
        copy_data(source, data)
        inputs = snapshot_inputs(data)
        import pxeye

        static = Path(pxeye.__file__).with_name("web")
        app = Application(copy.deepcopy(config), str(secrets), data, str(static))
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.app = app
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar)
        )
        password = (secrets / "bootstrap-password").read_text().strip()
        login = urllib.request.Request(
            base + "/api/login",
            data=json.dumps({"password": password}).encode(),
            headers={"Content-Type": "application/json", "Origin": base},
            method="POST",
        )
        opener.open(login, timeout=30).read()

        responses = {}

        def read(path):
            try:
                with opener.open(base + path, timeout=180) as response:
                    responses[path] = {
                        "status": response.status,
                        "body": json.loads(response.read() or b"null"),
                    }
            except urllib.error.HTTPError as error:
                responses[path] = {
                    "status": error.code,
                    "body": json.loads(error.read() or b"null"),
                }
            except Exception as error:
                responses[path] = {"status": None, "error": f"{type(error).__name__}: {error}"}

        for path in PAGE_READS:
            read(path)
        status = responses.get("/api/device-status", {}).get("body") or {}
        for machine in sorted((status.get("servers") or {}).keys()):
            read(f"/api/device-status/machines/{machine}/history")
            read(f"/api/device-status/machines/{machine}/firmware")
        server.shutdown()
        document = {
            "format": FORMAT,
            "captured_at": time.time(),
            "pxeye_version": getattr(pxeye, "__version__", ""),
            "core_url": config["core_url"],
            "site": {"name": config.get("site", {}).get("name", "")},
            "inputs": inputs,
            "core_calls": calls,
            "pxeye_responses": responses,
        }
        text = json.dumps(document, ensure_ascii=False, indent=1, sort_keys=True)
        output.write(text + "\n")
        output.flush()
        counts = {}
        for call in calls:
            counts[call["kind"]] = counts.get(call["kind"], 0) + 1
        print(
            f"captured: {counts} calls, {len(responses)} API reads, "
            f"{sum(1 for c in calls if 'error' in c)} failed calls, sha256 {hashlib.sha256(text.encode()).hexdigest()[:16]}",
            file=sys.stderr,
        )
    except Exception:
        traceback.print_exc()
        sys.exit(1)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
