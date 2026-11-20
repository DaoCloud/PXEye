#!/usr/bin/env python3
"""Run the console against a capture made by tools/core-capture.py, without a Core.

The real backend and frontend run; only the transport is replaced. Every Core RPC,
Core CLI call and Redfish request is answered with the response recorded at the
site, keyed by method and request. A request that was not recorded fails loudly and
is listed, which is how drift between the code and the capture shows up.

    PYTHONPATH=src python3 tools/core-replay.py serve <capture.json> [--port 18930]
        [--host 127.0.0.1] [--writable] [--password-file FILE]
    PYTHONPATH=src python3 tools/core-replay.py check <capture.json>
    PYTHONPATH=src python3 tools/core-replay.py check <capture.json> --write <new.json>

`serve` prints the address and password of a local console for manual or browser
checks. `check` requests the same API reads the capture recorded and compares the
responses with the recorded ones, ignoring times that change on every read. It exits
non-zero when a response differs or a request was not recorded.

The replayed console is read-only, like the observer the capture was made in. With
`--writable` it stays read-only except for the PXEye-local imports of the rack
operations pages (switch labels, rack units), kept in the replay's temporary data
directory until it stops; every other command is refused as on an observer. Core and
Redfish writes are impossible in any case, because the replay only answers recorded
requests and a capture records reads. `--host` chooses the listening address (default
127.0.0.1). `--password-file` sets the sign-in password instead of a random one. The
console has a password, but a site capture holds site data, so listen beyond loopback
only on a trusted network.

After a change that is meant to alter what the console returns, `--write` saves a copy
whose expected responses are the replayed ones. Review the differences it reported
first: the Core responses in the copy stay exactly as recorded at the site.

Run it from the repository root. The capture holds site data; keep it outside the
repository.
"""

import argparse
import builtins
import copy
import http.cookiejar
import importlib
import json
import re
import secrets
import shutil
import sys
import tempfile
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

SENSITIVE = re.compile(r"pass(word)?|secret|token|credential|private|^key$|_key$", re.I)
# Values that change on every read, not with the data.
VOLATILE = {
    "observed_at",
    "checked_at",
    "updated_at",
    "request_id",
    "csrf",
    "at",
    "power_state_updated_at",
    "duration_seconds",
    "last_checked",
    # Digests (here and in every *_revision) cover declarations that include credentials,
    # which the capture redacts.
    "revision",
}


def redact(value):
    """Hide credential text. Flags such as bmc_retain_credentials stay: they are settings."""
    if isinstance(value, dict):
        return {
            k: ("<redacted>" if SENSITIVE.search(k) and isinstance(v, str) and v else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def recorded_error(error):
    """The error the site raised: same class, message and attributes, so the console
    maps it to the same response. An unknown class becomes RuntimeError."""
    module, _, name = error["type"].rpartition(".")
    kind = RuntimeError
    if module:
        try:
            found = getattr(importlib.import_module(module), name)
            if isinstance(found, type) and issubclass(found, Exception):
                kind = found
        except (ImportError, AttributeError):
            pass
    elif isinstance(getattr(builtins, name, None), type):
        kind = getattr(builtins, name)
    instance = kind.__new__(kind)
    Exception.__init__(instance, error["message"])
    for attribute, value in (error.get("attributes") or {}).items():
        setattr(instance, attribute, value)
    return instance


def key(kind, **parts):
    return json.dumps({"kind": kind, **parts}, sort_keys=True, separators=(",", ":"))


class Recorded:
    """Responses by request; the last recording of a request wins."""

    def __init__(self, calls):
        self.answers, self.missing, self.lock = {}, [], threading.Lock()
        for call in calls:
            self.answers[self.call_key(call)] = call

    @staticmethod
    def call_key(call):
        if call["kind"] == "rpc":
            return key("rpc", method=call["method"], request=call["request"])
        if call["kind"] == "cli":
            return key("cli", args=call["args"], data=call["data"])
        return key("redfish", host=call["host"], path=call["path"], method=call["method"])

    def answer(self, request_key, label):
        call = self.answers.get(request_key)
        if call is None:
            with self.lock:
                self.missing.append(label)
            print("UNRECORDED " + label, file=sys.stderr, flush=True)
            raise RuntimeError("回放中没有这个请求的记录：" + label)
        if "error" in call:
            raise recorded_error(call["error"])
        return copy.deepcopy(call["response"])


def prepare(capture, work, password=None):
    """A data directory holding the captured local inputs and a placeholder identity."""
    data = work / "data"
    for relative, text in capture["inputs"]["files"].items():
        path = data / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    identity = work / "identity"
    identity.mkdir()
    for name in ("ca.crt", "client.crt", "client.key"):
        (identity / name).write_text("replay\n")
    from pxeye.persistence.store import get_store

    store = get_store(data / "console.sqlite3")
    with store.db() as db:
        for table, rows in capture["inputs"]["tables"].items():
            for row in rows:
                columns = ", ".join(row)
                marks = ", ".join("?" for _ in row)
                db.execute(
                    f"INSERT OR REPLACE INTO {table} ({columns}) VALUES ({marks})",
                    list(row.values()),
                )
    config = {
        "site": {"name": capture["site"]["name"] or "Replay", "namespace": "", "deployment": ""}
    }
    deployed = data / "config" / "deployment-site.json"
    if deployed.exists():
        config.update(json.loads(deployed.read_text()))
        deployed.unlink()
    for name in ("core_identity_source", "site_bootstrap", "site_credentials"):
        config.pop(name, None)
    config.update(
        core_url=capture["core_url"],
        core_identity_directory=str(identity),
        read_only=True,
        rack_operations=True,
        nico_deployment={"enabled": False, "namespace": "replay"},
    )
    password = password or secrets.token_urlsafe(12)
    secret_dir = work / "secrets"
    secret_dir.mkdir()
    import hashlib

    (secret_dir / "auth.json").write_text(
        json.dumps({"password_sha256": hashlib.sha256(password.encode()).hexdigest()})
    )
    return config, data, secret_dir, password


# The only commands --writable admits: PXEye-local data owned by rack operations pages.
WRITABLE_PATHS = ("/api/switch-labels", "/api/rack-units")


def start(capture, port, host="127.0.0.1", writable=False, password=None):
    from pxeye.api.http import Handler
    from pxeye.bootstrap import Application
    from pxeye.clients.core import CoreClient
    from pxeye.clients.redfish import RedfishClient
    from pxeye import read_only
    from pxeye.deployment import kubernetes

    recorded = Recorded(capture["core_calls"])

    def rpc(self, method, body):
        return recorded.answer(
            key("rpc", method=method, request=redact(body)), f"rpc {method} {json.dumps(body)}"
        )

    def cli(self, args, *, data=False):
        return recorded.answer(key("cli", args=list(args), data=data), f"cli {' '.join(args)}")

    def redfish(self, ip, path, credential, *, method="GET", body=None):
        return recorded.answer(
            key("redfish", host=ip, path=path, method=method), f"redfish {method} {ip}{path}"
        )

    def no_cluster(self, *args, **kwargs):
        raise kubernetes.ClusterError("回放中没有 Kubernetes。")

    CoreClient.rpc, CoreClient.core = rpc, cli
    CoreClient.check_core_certificate = lambda self: None
    RedfishClient.redfish_request = redfish
    kubernetes.CurrentCluster.request = no_cluster
    if writable:
        allowed = read_only.command_allowed
        read_only.command_allowed = lambda config, path: (
            path in WRITABLE_PATHS or allowed(config, path)
        )

    work = Path(tempfile.mkdtemp(prefix="pxeye-replay-"))
    config, data, secret_dir, password = prepare(capture, work, password)
    static = Path(__file__).resolve().parent.parent / "src" / "pxeye" / "web"
    app = Application(config, str(secret_dir), data, str(static))
    server = ThreadingHTTPServer((host, port), Handler)
    server.app = app
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, password, recorded, work


def strip(value):
    if isinstance(value, dict):
        return {
            k: strip(v)
            for k, v in value.items()
            if k not in VOLATILE and not k.endswith("_revision")
        }
    if isinstance(value, list):
        return [strip(v) for v in value]
    return value


def differences(expected, actual, path="", out=None):
    out = [] if out is None else out
    if isinstance(expected, dict) and isinstance(actual, dict):
        for k in sorted(set(expected) | set(actual)):
            if k not in actual:
                out.append(f"{path}.{k}: missing in replay")
            elif k not in expected:
                out.append(f"{path}.{k}: only in replay")
            else:
                differences(expected[k], actual[k], f"{path}.{k}", out)
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            out.append(f"{path}: {len(expected)} items recorded, {len(actual)} in replay")
        for i, (a, b) in enumerate(zip(expected, actual)):
            differences(a, b, f"{path}[{i}]", out)
    elif expected != actual:
        out.append(
            f"{path}: recorded {json.dumps(expected, ensure_ascii=False)[:80]}, "
            f"replay {json.dumps(actual, ensure_ascii=False)[:80]}"
        )
    return out


def check(capture, server, password, out, replayed=None):
    base = f"http://127.0.0.1:{server.server_address[1]}"
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar)
    )
    login = urllib.request.Request(
        base + "/api/login",
        data=json.dumps({"password": password}).encode(),
        headers={"Content-Type": "application/json", "Origin": base},
        method="POST",
    )
    opener.open(login, timeout=30).read()
    failures = 0
    for path, recorded in capture["pxeye_responses"].items():
        if recorded.get("status") is None:
            # The read itself failed at the site (timeout, connection); nothing to compare.
            print(f"SKIP {path}: {recorded.get('error', '')}", file=out)
            continue
        try:
            with opener.open(base + path, timeout=120) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read()
        try:
            body = json.loads(raw or b"null")
        except ValueError:
            body = {"raw": raw.decode("utf-8", "replace")}
        if "raw" in recorded:
            recorded = dict(recorded, body={"raw": recorded["raw"]})
        found = (
            []
            if status == recorded.get("status")
            else [f"status: recorded {recorded.get('status')}, replay {status}"]
        )
        found += differences(strip(recorded.get("body")), strip(body))
        print(("OK   " if not found else "DIFF ") + path, file=out)
        for line in found[:8]:
            print("       " + line, file=out)
        if len(found) > 8:
            print(f"       … {len(found) - 8} more", file=out)
        failures += bool(found)
        if replayed is not None:
            replayed[path] = {"status": status, "body": body}
    return failures


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("mode", choices=("serve", "check"))
    parser.add_argument("capture")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--host", default="127.0.0.1", help="listening address")
    parser.add_argument(
        "--writable",
        action="store_true",
        help="allow the PXEye-local imports (switch labels, rack units); everything else "
        "stays read-only, and Core and Redfish writes are impossible",
    )
    parser.add_argument("--password-file", help="serve: read the sign-in password from this file")
    parser.add_argument(
        "--write",
        metavar="FILE",
        help="check: also save a copy of the capture whose expected console responses are "
        "the replayed ones, after an intended change of output",
    )
    options = parser.parse_args()
    # The console logs every request to standard output; keep that for results.
    out, sys.stdout = sys.stdout, sys.stderr
    capture = json.loads(Path(options.capture).read_text())
    if capture.get("format") != 1:
        sys.exit("Unknown capture format.")
    fixed = Path(options.password_file).read_text().strip() if options.password_file else None
    server, password, recorded, work = start(
        capture, options.port, options.host, options.writable, fixed
    )
    try:
        if options.mode == "check":
            replayed = {}
            failures = check(capture, server, password, out, replayed)
            if options.write:
                updated = dict(capture, pxeye_responses=replayed)
                Path(options.write).write_text(
                    json.dumps(updated, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
                )
                Path(options.write).chmod(0o600)
                print(f"wrote {options.write}", file=out)
            missing = sorted(set(recorded.missing))
            for label in missing:
                print("UNRECORDED " + label, file=out)
            print(
                f"{len(capture['pxeye_responses'])} reads, {failures} differ, {len(missing)} unrecorded requests",
                file=out,
            )
            sys.exit(1 if failures or missing else 0)
        print(
            f"Replay console: http://{options.host}:{server.server_address[1]}  "
            + (f"password: {password}" if not fixed else "password: from --password-file")
            + ("  (writable: local imports only)" if options.writable else ""),
            file=out,
            flush=True,
        )
        print("Ctrl-C to stop.", file=out, flush=True)
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
