"""The demo capture is complete, replays exactly, and gives every page content.

tools/demo-capture.py authors placeholder data and records it with the real
tools/core-capture.py; tools/core-replay.py then serves it without a Core.
"""

import contextlib
import importlib.util
import io
import json
import shutil
import unittest
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2] / "tools"


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DemoCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The replay patches the clients for the whole process; restore them afterwards.
        from pxeye import read_only
        from pxeye.bootstrap import Application
        from pxeye.clients.core import CoreClient
        from pxeye.services import rack_actions
        from pxeye.clients.redfish import RedfishClient
        from pxeye.deployment import kubernetes

        patched = [
            (CoreClient, "rpc"),
            (CoreClient, "core"),
            (CoreClient, "check_core_certificate"),
            (RedfishClient, "redfish_request"),
            (kubernetes.CurrentCluster, "request"),
        ]
        saved = [(owner, name, owner.__dict__[name]) for owner, name in patched]
        saved.append((read_only, "command_allowed", read_only.command_allowed))
        saved.append((rack_actions, "enabled", rack_actions.enabled))
        saved.append((Application, "readiness", Application.readiness))
        cls.addClassCleanup(lambda: [setattr(o, n, v) for o, n, v in saved])
        cls.demo = load("demo-capture")
        cls.capture, cls.code, _, cls.unanswered = cls.demo.capture()

    def read(self, path):
        return self.capture["pxeye_responses"][path]["body"]

    def test_the_capture_is_a_complete_demo(self):
        self.assertEqual(self.code, 0)
        self.assertIs(self.capture["demo"], True)
        self.assertEqual(self.capture["site"]["name"], "演示站点（示例数据）")
        summary = self.capture["summary"]
        self.assertTrue(summary["complete"])
        # No deliberate failures: every Core call answers; failures are shown as data
        # (exploration errors, alerts, a server Core has not created).
        self.assertEqual(summary["failed_calls"], [])
        self.assertEqual(summary["failed_reads"], {})
        self.assertEqual(summary["reads_with_errors"], {})
        # Only reads the rack operations pages do not use are answered empty.
        self.assertEqual(
            self.unanswered,
            [
                "FindNetworkSegmentDhcpRanges",
                "FindNetworkSegmentIds",
                "FindOperatingSystemIds",
                "cli instance show",
                "cli machine show --hosts",
            ],
        )
        self.assertNotIn("demo-placeholder", json.dumps(self.capture))

    def test_each_page_read_has_the_authored_content(self):
        devices = self.read("/api/equipment")["devices"]
        kinds = [d["kind"] for d in devices]
        self.assertEqual(
            (kinds.count("server"), kinds.count("switch"), kinds.count("power_shelf")), (8, 2, 1)
        )
        # Switches and the power shelf are joined to their Core objects.
        self.assertTrue(all(d["native_id"] for d in devices if d["kind"] != "server"))
        self.assertEqual(
            sorted(d["serial"] for d in devices if d["kind"] == "server" and not d["rack_id"]),
            ["DEMO-SRV-008"],
        )

        status = self.read("/api/device-status")
        self.assertEqual(status["errors"], [])
        servers = status["servers"]
        self.assertEqual(
            (len(servers), len(status["switches"]), len(status["power_shelves"])), (9, 2, 1)
        )
        hosts = [s for s in servers.values() if s["type"] == "host"]
        self.assertEqual(len(hosts), 7)  # DEMO-SRV-007 has no Core machine
        self.assertEqual(sum(1 for s in hosts if s["dpu_ids"]), 2)
        states = sorted(s["lifecycle"]["state"] for s in hosts)
        self.assertIn("Failed/NVMECleanFailed", states)
        self.assertEqual(sum(1 for s in hosts if s["lifecycle"]["above_sla"]), 2)
        alerts = [
            a["id"]
            for kind in ("servers", "switches", "power_shelves")
            for row in status[kind].values()
            for a in row["health"]["alerts"]
        ]
        self.assertEqual(sorted(alerts), ["FanSpeed", "PowerSupply", "PoweredOff", "Temperature"])
        links = [link for s in hosts for link in s["lldp"]]
        self.assertEqual(len(links), 16)
        ports = [(link["switch_id"], link["remote_port"]) for link in links]
        self.assertEqual(len(ports) - len(set(ports)), 1)  # one port conflict
        self.assertEqual(sum(1 for s in hosts if not s["lldp"]), 1)
        fabric = sorted(s["fabric_manager"]["state"] for s in status["switches"].values())
        self.assertEqual(fabric, ["not_ok", "ok"])

        exploration = self.read("/api/exploration")
        self.assertEqual(len(exploration["endpoints"]), 9)
        self.assertEqual(sum(1 for e in exploration["endpoints"] if e["failed"]), 3)
        self.assertEqual(exploration["last_run"]["succeeded"], 6)

        labels = self.read("/api/switch-labels")
        self.assertEqual((len(labels["switches"]), len(labels["ports"])), (2, 13))
        units = self.read("/api/rack-units")
        self.assertEqual((len(units["positions"]), len(units["mismatches"])), (6, 1))
        self.assertEqual(units["unknown"], [])

        machine = self.demo.mid(1)
        base = f"/api/device-status/machines/{machine}/"
        self.assertGreater(len(self.read(base + "history")["records"]), 5)
        self.assertEqual(len(self.read(base + "firmware")["entries"]), 15)
        runs = self.read(base + "validation")
        self.assertEqual(len(runs["runs"]), 2)
        self.assertEqual(sorted(r["exit_code"] for r in sum(runs["results"].values(), [])), [0, 1])
        recurring = self.read(f"/api/device-status/machines/{self.demo.mid(2)}/health")["alerts"]
        self.assertEqual([a["active"] for a in recurring], [True, False])

    def test_replay_matches_and_only_local_imports_are_writable(self):
        replay = load("core-replay")
        for writable in (False, True):
            with self.subTest(writable=writable):
                with (
                    contextlib.redirect_stdout(io.StringIO()),
                    contextlib.redirect_stderr(io.StringIO()),
                ):
                    server, password, recorded, work = replay.start(
                        self.capture, 0, writable=writable
                    )
                    try:
                        report = io.StringIO()
                        failures = replay.check(self.capture, server, password, report)
                        status, other = self.import_units(server, password)
                    finally:
                        server.shutdown()
                        server.server_close()
                        shutil.rmtree(work, ignore_errors=True)
                self.assertEqual(
                    (failures, sorted(set(recorded.missing))), (0, []), report.getvalue()
                )
                self.assertEqual(status == 200, writable)
                # Writable admits the local imports only; any other command stays refused.
                self.assertEqual(other, 403)

    def serve(self, capture, **options):
        from pxeye import read_only
        from pxeye.bootstrap import Application
        from pxeye.services import rack_actions

        patched = [
            (read_only, "command_allowed", read_only.command_allowed),
            (rack_actions, "enabled", rack_actions.enabled),
            (Application, "readiness", Application.readiness),
        ]
        self.addCleanup(lambda: [setattr(o, n, v) for o, n, v in patched])
        replay = load("core-replay")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            server, password, recorded, work = replay.start(capture, 0, **options)

        def stop():
            server.shutdown()
            server.server_close()
            shutil.rmtree(work, ignore_errors=True)

        self.addCleanup(stop)
        return server, password, recorded

    def test_demo_writes_are_refused_for_a_site_capture(self):
        replay = load("core-replay")
        site = dict(self.capture)
        site.pop("demo")
        with self.assertRaises(replay.DemoWritesRefused):
            replay.start(site, 0, demo_writes=True)

    def test_demo_writes_run_rack_actions_in_memory(self):
        machine = self.demo.mid(1)
        body = {
            "action": "maintenance_enable",
            "targets": [machine],
            "params": {"reference": "演示工单"},
        }
        # Without the flag the replay is an observer: the routes are refused.
        server, password, _ = self.serve(self.capture)
        send = self.client(server, password)
        self.assertEqual(send("/api/rack-actions/preview", body)[0], 403)
        self.assertEqual(send("/api/rack-actions/catalog")[0], 404)
        self.assertIs(send("/api/readiness")[1]["rack_actions"], False)

        server, password, recorded = self.serve(self.capture, demo_writes=True)
        send = self.client(server, password)
        readiness = send("/api/readiness")[1]
        self.assertIs(readiness["rack_actions"], True)
        self.assertIs(readiness["read_only"], True)
        status, catalog = send("/api/rack-actions/catalog")
        self.assertEqual(status, 200)
        self.assertEqual(
            catalog["rms"], {"reachable": True, "version": "0.0.0-demo-rms", "error": ""}
        )
        racks = send("/api/racks")[1]
        self.assertEqual([r["id"] for r in racks["racks"]], ["DEMO-R01"])
        self.assertEqual(racks["racks"][0]["profile"], "GB200 NVL72")
        self.assertEqual(
            {k: len(v) for k, v in racks["racks"][0]["devices"].items()},
            {"machines": 4, "switches": 2, "power_shelves": 1},
        )

        status, preview = send("/api/rack-actions/preview", body)
        self.assertEqual(status, 200, preview)
        self.assertTrue(preview["targets"][0]["eligible"], preview)
        status, result = send(
            "/api/rack-actions/execute", {"preview_token": preview["preview_token"]}
        )
        self.assertEqual(status, 200, result)
        self.assertEqual(result["results"][0]["status"], "succeeded", result)
        self.assertEqual(recorded.demo.sent[0]["method"], "SetMaintenance")
        records = send("/api/rack-actions/records")[1]["records"]
        self.assertEqual(
            [(r["action"], r["status"]) for r in records], [("maintenance_enable", "succeeded")]
        )
        # A high-risk rack action reads back through the rack state.
        status, preview = send(
            "/api/rack-actions/preview",
            {
                "action": "rack_maintenance",
                "targets": ["DEMO-R01"],
                "params": {"activities": ["power_sequence"]},
            },
        )
        self.assertEqual(status, 200, preview)
        result = send(
            "/api/rack-actions/execute",
            {
                "preview_token": preview["preview_token"],
                "confirm_serials": {"DEMO-R01": "DEMO-R01"},
            },
        )[1]
        self.assertEqual(result["results"][0]["status"], "succeeded", result)
        # Everything else is still refused, and no read went unrecorded.
        self.assertEqual(send("/api/tasks", {"devices": []})[0], 403)
        self.assertEqual(sorted(set(recorded.missing)), [])

    def client(self, server, password):
        base = f"http://127.0.0.1:{server.server_address[1]}"
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(CookieJar())
        )
        token = {}

        def send(path, body=None):
            request = urllib.request.Request(
                base + path,
                data=None if body is None else json.dumps(body).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Origin": base,
                    "X-CSRF-Token": token.get("csrf", ""),
                },
                method="GET" if body is None else "POST",
            )
            try:
                with opener.open(request, timeout=60) as response:
                    return response.status, json.loads(response.read())
            except urllib.error.HTTPError as error:
                return error.code, None

        token.update(send("/api/login", {"password": password})[1])
        return send

    def import_units(self, server, password):
        base = f"http://127.0.0.1:{server.server_address[1]}"
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(CookieJar())
        )

        token = {}

        def send(path, body=None):
            request = urllib.request.Request(
                base + path,
                data=None if body is None else json.dumps(body).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Origin": base,
                    "X-CSRF-Token": token.get("csrf", ""),
                },
                method="GET" if body is None else "POST",
            )
            try:
                with opener.open(request, timeout=60) as response:
                    return response.status, json.loads(response.read())
            except urllib.error.HTTPError as error:
                return error.code, None

        token.update(send("/api/login", {"password": password})[1])
        _, current = send("/api/rack-units")
        status, _ = send(
            "/api/rack-units",
            {"csv": "serial,rack,unit\nDEMO-SRV-008,,10\n", "revision": current["revision"]},
        )
        refused, _ = send("/api/tasks", {"devices": []})
        return status, refused


if __name__ == "__main__":
    unittest.main()
