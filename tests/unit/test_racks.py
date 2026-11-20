"""机柜: rack list and history reads, behind rack_operations only."""

import json
import subprocess
import shutil
import unittest
from pathlib import Path

from pxeye.services import racks
from tests.unit.test_rack_actions import Base, App, Core

STATE = json.dumps({"state": "maintenance", "maintenance": {"state": "FirmwareUpgrade"}})


class RackCore(Core):
    def __init__(self, fail=()):
        super().__init__([])
        self.failing = fail

    def rpc(self, method, body):
        self.calls.append((method, body))
        if method in self.failing:
            raise RuntimeError("grpcurl 执行失败（退出码 1）。")
        if method == "FindRackStateHistories":
            return {
                "histories": {
                    "r1": {
                        "records": [
                            {"event": STATE, "time": "2026-01-01T01:00:00Z"},
                            {"event": "Ready", "time": "2026-01-01T00:00:00Z"},
                            {"event": "bad", "time": "not a time"},
                        ]
                    }
                }
            }
        if method == "FindRackHealthHistories":
            return {
                "histories": {
                    "r1": {
                        "records": [
                            {"time": "2026-01-01T00:00:00Z", "health": {"alerts": []}},
                            {
                                "time": "2026-01-02T00:00:00Z",
                                "health": {"alerts": [{"id": "PowerShelf", "target": "ps1"}]},
                            },
                        ]
                    }
                }
            }
        if method == "FindRackIds":
            return {"rackIds": []}
        if method == "GetAllExpectedRacks":
            return {"expectedRacks": [{"rackId": {"id": "r9"}, "rackProfileId": {"id": "NVL72"}}]}
        return {}


class HistoryTests(unittest.TestCase):
    def test_timeline_and_health(self):
        data = racks.history(RackCore(), "r1")
        self.assertEqual(
            [s["state"] for s in data["states"]], ["Ready", "maintenance/FirmwareUpgrade"]
        )
        self.assertTrue(data["states"][-1]["current"])
        self.assertEqual(data["health"][0]["alerts"][0]["id"], "PowerShelf")
        self.assertEqual(data["errors"], [])

    def test_each_read_fails_alone(self):
        data = racks.history(RackCore(fail=("FindRackHealthHistories",)), "r1")
        self.assertEqual(len(data["states"]), 2)
        self.assertEqual(data["errors"], ["NICo 未返回机柜健康历史。"])

    def test_invalid_id(self):
        with self.assertRaises(ValueError):
            racks.history(RackCore(), "../x")


class RouteTests(Base):
    def test_reads_need_rack_operations_only(self):
        core = RackCore()
        for config in ({"rack_operations": True}, {"rack_operations": True, "read_only": True}):
            app = App(self.store, core, config)
            code, data = self.get("/api/racks", app)
            self.assertEqual(code, 200)
            self.assertEqual(data["expected"][0]["profile"], "NVL72")
            code, data = self.get("/api/racks/r1/history", app)
            self.assertEqual(code, 200)
            self.assertEqual(self.get("/api/racks/..%2f/history", app)[0], 400)
            self.assertEqual(self.get("/api/racks/r1/other", app)[0], 404)

    def test_switch_off_is_404_without_core(self):
        core = RackCore()
        for config in ({}, {"rack_operations": "true"}, {"rack_actions": True}):
            app = App(self.store, core, config)
            for path in ("/api/racks", "/api/racks/r1/history"):
                self.assertEqual(self.get(path, app)[0], 404)
        self.assertEqual(core.calls, [])


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class PageTests(unittest.TestCase):
    def test_page_logic(self):
        script = Path(__file__).resolve().parents[1] / "web" / "test_racks.cjs"
        result = subprocess.run(["node", str(script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
