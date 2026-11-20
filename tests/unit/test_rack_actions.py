"""Rack actions: catalog, preview refusals, execution order and the switch."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from pxeye import read_only
from pxeye.api.commands import CommandRoutes
from pxeye.api.queries import QueryRoutes
from pxeye.clients.errors import ReadOnlyModeError
from pxeye.persistence.store import Store
from pxeye.services import rack_actions

ON = {"rack_operations": True, "rack_actions": True}


def machine(mid, serial, state="Ready", maintenance=""):
    return {
        "id": {"id": mid},
        "machineType": "HOST",
        "status": {
            "lifecycle": {"state": state},
            "discoveryInfo": {"dmiData": {"productSerial": serial}},
        },
        "config": {"maintenanceReference": maintenance} if maintenance else {},
    }


class Core:
    def __init__(self, machines, fail=None):
        self.machines = {m["id"]["id"]: m for m in machines}
        self.calls, self.fail = [], fail

    def rpc(self, method, body):
        self.calls.append((method, body))
        if method == "FindMachinesByIds":
            ids = [i["id"] for i in body["machineIds"]]
            return {"machines": [self.machines[i] for i in ids if i in self.machines]}
        if method == "FindMachineIds":
            return {"machineIds": [{"id": i} for i in self.machines]}
        if method == "GetRmsVersion":
            raise RuntimeError("grpcurl 执行失败（退出码 1）。")
        if method == "GetComponentPowerDetails":
            return {"entries": [{"actual": {"state": "COMPONENT_POWER_STATE_ON"}}]}
        if method == self.fail:
            raise RuntimeError("grpcurl 执行超时（55 秒）。")
        if method == "SetMaintenance":
            mid = body["hostId"]["id"]
            self.machines[mid]["config"] = {"maintenanceReference": body.get("reference", "")}
        return {}

    def sent(self, method):
        return [c for c in self.calls if c[0] == method]


class App:
    def __init__(self, store, core, config=ON):
        self.config, self.store, self.adapter = dict(config), store, core
        self.nico_deployment = SimpleNamespace(preflight=None, start=None, connect=None)

    def readiness(self):
        return {"business_available": True}


class Route(QueryRoutes, CommandRoutes):
    client_address = ("10.0.0.9", 1)

    def __init__(self, app, path):
        self.app, self.path, self.result = app, path, None

    def session(self):
        return {"csrf": "x", "token": "t"}

    def respond(self, code, payload, headers=None):
        self.result = (code, payload)


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.dir.name) / "db.sqlite"))
        self.core = Core(
            [machine("m1", "SN1"), machine("m2", "SN2", "HostInit/WaitingForDiscovery")]
        )
        self.app = App(self.store, self.core)

    def tearDown(self):
        self.dir.cleanup()

    def post(self, path, body, app=None):
        route = Route(app or self.app, path)
        route.dispatch_command(path, body, {"token": "t"})
        return route.result

    def get(self, path, app=None):
        route = Route(app or self.app, path)
        route.get_request()
        return route.result

    def busy(self, serial):
        with self.store.db() as db:
            db.execute(
                "INSERT INTO tasks VALUES (?,?,?,?,?,?)",
                ("t-" + serial, serial, "running", "{}", 0, "k-" + serial),
            )


class CatalogTests(Base):
    def test_shape(self):
        code, data = self.get("/api/rack-actions/catalog")
        self.assertEqual(code, 200)
        self.assertEqual(data["rms"]["reachable"], False)
        ids = {a["id"]: a for a in data["actions"]}
        for key in ("power_on", "maintenance_enable", "rack_maintenance", "switch_reset"):
            self.assertTrue(ids[key]["available"])
        for key in ("rack_power_on", "rack_power_off", "rack_cold_reboot"):
            self.assertFalse(ids[key]["available"])
            self.assertTrue(ids[key]["unavailable_reason"])
        for action in data["actions"]:
            self.assertIn(action["kind"], ("machine", "switch", "power_shelf", "rack"))
            self.assertEqual(action["needs_confirm_serial"], action["risk"] == "high")
            self.assertNotIn("build", action)
        self.assertTrue(ids["tray_power_on"]["needs_rms"])
        self.assertFalse(ids["power_on"]["needs_rms"])

    def test_request_builders(self):
        build = rack_actions.ACTIONS
        self.assertEqual(
            build["tray_power_off"]["build"]("m1", {}),
            {
                "machineIds": {"machineIds": [{"id": "m1"}]},
                "action": "SYSTEM_POWER_CONTROL_FORCE_OFF",
            },
        )
        body = build["rack_maintenance"]["build"](
            "r1", {"activities": ["firmware_upgrade", "power_sequence"], "sot_json": "{}"}
        )
        self.assertEqual(
            body["scope"]["activities"],
            [{"firmwareUpgrade": {"firmwareVersion": "{}"}}, {"powerSequence": {}}],
        )


class PreviewTests(Base):
    def preview(self, action, targets, params=None):
        return self.post(
            "/api/rack-actions/preview",
            {"action": action, "targets": targets, "params": params or {}},
        )

    def test_refusals(self):
        self.busy("SN1")
        code, data = self.preview("power_on", ["m1", "m2", "nope"])
        self.assertEqual(code, 200)
        rows = {t["target"]: t for t in data["targets"]}
        self.assertFalse(rows["m1"]["eligible"])
        self.assertIn("安装任务", rows["m1"]["reasons"][0])
        self.assertFalse(rows["m2"]["eligible"])
        self.assertIn("安装相关状态", rows["m2"]["reasons"][0])
        self.assertEqual(rows["nope"]["reasons"], ["NICo 中不存在该对象。"])
        # Maintenance is not refused for the installation state.
        _, data = self.preview("maintenance_enable", ["m2"], {"reference": "T-1"})
        self.assertTrue(data["targets"][0]["eligible"])

    def test_batch_and_params(self):
        code, data = self.preview("power_on", [f"m{i}" for i in range(11)])
        self.assertEqual(code, 400)
        code, data = self.preview("maintenance_enable", ["m1"])
        self.assertEqual(code, 400)
        self.assertIn("缺少参数", data["error"])
        code, _ = self.preview("rack_maintenance", ["r1"], {"activities": ["firmware_upgrade"]})
        self.assertEqual(code, 400)
        code, _ = self.preview("rack_power_on", ["r1"])
        self.assertEqual(code, 400)


class ExecuteTests(Base):
    def run_action(self, action, targets, params=None, confirms=None):
        _, data = self.post(
            "/api/rack-actions/preview",
            {"action": action, "targets": targets, "params": params or {}},
        )
        return self.post(
            "/api/rack-actions/execute",
            {"preview_token": data["preview_token"], "confirm_serials": confirms or {}},
        ), data["preview_token"]

    def test_success_and_single_use(self):
        (code, data), token = self.run_action("maintenance_enable", ["m1"], {"reference": "T-1"})
        self.assertEqual(code, 200)
        self.assertEqual(data["results"][0]["status"], "succeeded")
        code, _ = self.post("/api/rack-actions/execute", {"preview_token": token})
        self.assertEqual(code, 400)
        self.assertEqual(len(self.core.sent("SetMaintenance")), 1)
        code, records = self.get("/api/rack-actions/records?target=SN1")
        self.assertEqual(records["records"][0]["reason"], "T-1")
        self.assertTrue(records["records"][0]["operator"].endswith("@10.0.0.9"))

    def test_sent_recorded_before_core_and_never_resent(self):
        seen = []
        original = self.core.rpc

        def rpc(method, body):
            if method == "AdminPowerControl":
                seen.append([r["status"] for r in self.store.rack_actions()])
            return original(method, body)

        self.core.rpc, self.core.fail = rpc, "AdminPowerControl"
        self.core.machines["m1"]["status"]["lifecycle"]["state"] = "Ready"
        original_power = rack_actions._power_state
        rack_actions._power_state = lambda *a: "OFF"
        try:
            (code, data), _ = self.run_action("power_on", ["m1"])
        finally:
            rack_actions._power_state = original_power
        self.assertEqual(seen, [["sent"]])
        self.assertEqual(data["results"][0]["status"], "unknown")
        self.assertEqual(len(self.core.sent("AdminPowerControl")), 1)
        self.assertEqual(self.store.rack_actions()[0]["status"], "unknown")

    def test_high_risk_needs_serial(self):
        (code, data), _ = self.run_action("force_off", ["m1"])
        self.assertEqual(data["results"][0]["status"], "refused")
        self.assertEqual(self.core.sent("AdminPowerControl"), [])
        (code, data), _ = self.run_action("force_off", ["m1"], confirms={"m1": "SN1"})
        self.assertEqual(len(self.core.sent("AdminPowerControl")), 1)
        self.assertNotEqual(data["results"][0]["status"], "refused")

    def test_execute_rechecks_installation(self):
        _, data = self.post(
            "/api/rack-actions/preview", {"action": "power_on", "targets": ["m1"], "params": {}}
        )
        self.busy("SN1")
        _, result = self.post("/api/rack-actions/execute", {"preview_token": data["preview_token"]})
        self.assertEqual(result["results"][0]["status"], "refused")
        self.assertEqual(self.core.sent("AdminPowerControl"), [])


class GateTests(Base):
    def test_gate_off_is_404(self):
        for config in (
            {"rack_operations": True},
            {"rack_actions": True},
            {"rack_operations": True, "rack_actions": "true"},
            ON | {"read_only": True},
        ):
            app = App(self.store, self.core, config)
            for path in ("/api/rack-actions/catalog", "/api/rack-actions/records", "/api/racks"):
                self.assertEqual(self.get(path, app)[0], 404)
            code, _ = self.post("/api/rack-actions/preview", {"action": "power_on"}, app)
            self.assertEqual(code, 404)
        self.assertEqual(self.core.calls, [])

    def test_read_only_refused(self):
        config = ON | {"read_only": True}
        for path in ("/api/rack-actions/preview", "/api/rack-actions/execute"):
            self.assertFalse(read_only.command_allowed(config, path))
        for entry in rack_actions.CATALOG:
            if entry["available"]:
                with self.assertRaises(ReadOnlyModeError):
                    read_only.require_rpc(config, entry["rpc"])
        read_only.require_rpc(config, "GetComponentPowerDetails")

    def test_racks_empty_on_general_site(self):
        code, data = self.get("/api/racks")
        self.assertEqual(code, 200)
        self.assertEqual((data["racks"], data["expected"]), ([], []))


if __name__ == "__main__":
    unittest.main()
