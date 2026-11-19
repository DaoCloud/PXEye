"""Rack unit positions: strict import, revision check, comparison and the site switch."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from pxeye import read_only
from pxeye.api.commands import CommandRoutes
from pxeye.api.queries import QueryRoutes
from pxeye.persistence.store import Store
from pxeye.services import rack_units

TOPOLOGY = Path(__file__).resolve().parents[2] / "src/pxeye/web/pages/topology.js"
HARNESS = r"""
const vm = require("vm");
const fs = require("fs");
const noop = () => {};
const ctx = { state: {}, registerPage: noop, registerActions: noop, registerHook: noop, observeUI: noop,
  window: { addEventListener: noop }, esc: String };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), ctx);
process.stdout.write(JSON.stringify(vm.runInContext(process.argv[2], ctx)));
"""

DEVICES = [
    {"serial": "SN-A", "rack_id": "RACK-1", "kind": "server"},
    {"serial": "SN-B", "rack_id": "RACK-1", "kind": "server"},
    {"serial": "SN-C", "rack_id": "", "kind": "server"},
    {"serial": "SN-X", "rack_id": "RACK-9", "kind": "server", "address_only": True},
]


class Equipment:
    def __init__(self):
        self.calls = 0

    def view(self, snapshot):
        self.calls += 1
        return {"devices": DEVICES}


class Addresses:
    def snapshot(self):
        return {}


class App:
    def __init__(self, enabled, store):
        self.config = {"rack_operations": enabled}
        self.store = store
        self.equipment = Equipment()
        self.management_addresses = Addresses()
        self.nico_deployment = type("Deployment", (), {"preflight": 0, "start": 0, "connect": 0})()

    def readiness(self):
        return {"business_available": True}


class Route(QueryRoutes, CommandRoutes):
    def __init__(self, app, path):
        self.app, self.path, self.result = app, path, None

    def session(self):
        return {"csrf": "x"}

    def respond(self, code, payload, headers=None):
        self.result = (code, payload)


class ParseTests(unittest.TestCase):
    def errors(self, text):
        with self.assertRaises(rack_units.RackUnitsInvalid) as caught:
            rack_units.parse(text)
        return caught.exception.errors

    def test_three_and_four_columns(self):
        self.assertEqual(
            rack_units.parse("\ufeffserial,rack,unit\nSN-A,RACK-1,10\n\n"),
            [{"serial": "SN-A", "rack": "RACK-1", "unit": 10, "height": 1}],
        )
        rows = rack_units.parse("serial,rack,unit,height\nSN-A,RACK-1,10,2\nSN-B,RACK-1,12,1\n")
        self.assertEqual([r["height"] for r in rows], [2, 1])
        self.assertEqual(rack_units.parse(""), [])

    def test_bad_header(self):
        self.assertEqual(self.errors("sn,rack,u\nSN-A,R,1\n")[0]["field"], "header")

    def test_every_error_is_reported_with_its_line(self):
        errors = self.errors(
            "serial,rack,unit,height\n"
            ",R,1,1\n"  # 2 empty serial
            "SN-A,R,0,1\n"  # 3 unit out of range
            "SN-B,R,x,1\n"  # 4 unit not a number
            "SN-C,R,5,61\n"  # 5 height out of range
            "SN-D,R,59,3\n"  # 6 beyond U60
            "SN-E,R,10,2\n"  # 7
            "SN-E,R,20,1\n"  # 8 duplicate serial
            "SN-F,R,11,1\n"  # 9 overlaps SN-E
            "SN-G,Q,11,1\n"  # 10 other rack: fine
            "SN-H,R,1\n"  # 11 wrong column count
        )
        self.assertEqual(
            [(e["line"], e["field"]) for e in errors],
            [
                (2, "serial"),
                (3, "unit"),
                (4, "unit"),
                (5, "height"),
                (6, "height"),
                (8, "serial"),
                (9, "unit"),
                (11, "csv"),
            ],
        )
        self.assertTrue(all(e["message"] for e in errors))

    def test_blank_rack_rows_do_not_overlap(self):
        self.assertEqual(len(rack_units.parse("serial,rack,unit\nSN-A,,5\nSN-B,,5\n")), 2)

    def test_topology_keeps_manual_order_while_editing(self):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node is not installed")
        expr = (
            "state.rackOperations = true;"
            "state.rackUnits = {positions: [{serial: 'A', unit: 1, height: 1},"
            " {serial: 'B', unit: 9, height: 1}]};"
            "const rows = [{kind: 'server', serial: 'A'}, {kind: 'server', serial: 'B'}];"
            "const sorted = topologyByUnit(rows).map((r) => r.serial);"
            "state.topologyEditing = true;"
            "[sorted, topologyByUnit(rows).map((r) => r.serial)]"
        )
        out = subprocess.run(
            [node, "-e", HARNESS, str(TOPOLOGY), expr], capture_output=True, text=True, check=True
        )
        self.assertEqual(json.loads(out.stdout), [["B", "A"], ["A", "B"]])

    def test_row_limit(self):
        text = "serial,rack,unit\n" + "".join(f"S{i},R{i},1\n" for i in range(2001))
        self.assertEqual(self.errors(text)[0]["field"], "csv")
        rack_units.parse("serial,rack,unit\n" + "".join(f"S{i},R{i},1\n" for i in range(2000)))

    def test_csv_round_trip(self):
        rows = rack_units.parse('serial,rack,unit,height\nSN-A,"R,1",10,2\n')
        self.assertEqual(rack_units.parse(rack_units.to_csv(rows)), rows)


class StoreRouteTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.dir.name) / "pxeye.db")

    def tearDown(self):
        self.dir.cleanup()

    def call(self, method, path, body=None, enabled=True):
        route = Route(App(enabled, self.store), path)
        if method == "GET":
            route.get_request()
        else:
            route.dispatch_command(path, body, {"csrf": "x"})
        return route.result

    def test_import_compare_and_conflict(self):
        code, empty = self.call("GET", "/api/rack-units")
        self.assertEqual((code, empty["positions"], empty["revision"]), (200, [], ""))
        text = "serial,rack,unit,height\nSN-A,RACK-1,10,2\nSN-C,RACK-2,1,1\nSN-Z,RACK-1,1,1\n"
        code, saved = self.call("POST", "/api/rack-units", {"csv": text, "revision": ""})
        self.assertEqual(code, 200)
        self.assertEqual(
            saved["mismatches"],
            [{"serial": "SN-C", "recorded_rack": "RACK-2", "device_rack": ""}],
        )
        self.assertEqual(saved["unknown"], ["SN-Z"])
        self.assertEqual(self.call("GET", "/api/rack-units")[1]["revision"], saved["revision"])
        code, conflict = self.call("POST", "/api/rack-units", {"csv": text, "revision": ""})
        self.assertEqual(code, 409)
        self.assertEqual(self.store.rack_units()["revision"], saved["revision"])

    def test_invalid_import_saves_nothing(self):
        body = {"csv": "serial,rack,unit\nSN-A,R,99\n", "revision": ""}
        code, payload = self.call("POST", "/api/rack-units", body)
        self.assertEqual(code, 400)
        self.assertEqual(payload["errors"][0]["line"], 2)
        self.assertEqual(self.store.rack_units()["positions"], [])
        self.assertEqual(self.call("POST", "/api/rack-units", {"csv": ""})[0], 400)

    def test_routes_do_not_exist_with_the_switch_off(self):
        for enabled in (False, None, "true"):
            route = Route(App(enabled, self.store), "/api/rack-units")
            route.get_request()
            self.assertEqual(route.result[0], 404)
            self.assertEqual(route.app.equipment.calls, 0)
            route.dispatch_command("/api/rack-units", {"csv": "", "revision": ""}, {})
            self.assertEqual(route.result[0], 404)
        self.assertEqual(self.store.rack_units()["revision"], "")

    def test_read_only_observer_refuses_the_import(self):
        self.assertFalse(read_only.command_allowed({"read_only": True}, "/api/rack-units"))


if __name__ == "__main__":
    unittest.main()
