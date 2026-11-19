"""Switch labels: strict CSV parsing, revision check, gated routes, read-only refusal."""

import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path

from pxeye import read_only
from pxeye.api.commands import CommandRoutes
from pxeye.api.queries import QueryRoutes
from pxeye.persistence.store import Store
from pxeye.services import switch_labels

SWITCHES = (
    "chassis_mac,name,model,serial,management_ip,rack\n"
    "AA-BB-CC-00-00-01,leaf-a,model-x,SN-PLACEHOLDER,192.0.2.10,R1\n"
)
PORTS = "chassis_mac,port_id,port_name\naabb.cc00.0001,swp1,Eth1/1\n"


class ParseTests(unittest.TestCase):
    def test_valid_tables_normalise_mac(self):
        switches, ports = switch_labels.parse({"switches_csv": SWITCHES, "ports_csv": PORTS})
        self.assertEqual(switches[0]["chassis_mac"], "aa:bb:cc:00:00:01")
        self.assertEqual(switches[0]["name"], "leaf-a")
        self.assertEqual(ports[0]["chassis_mac"], "aa:bb:cc:00:00:01")

    def test_empty_table_is_empty(self):
        self.assertEqual(switch_labels.parse({"switches_csv": "", "ports_csv": " "}), ([], []))

    def errors(self, **body):
        with self.assertRaises(switch_labels.SwitchLabelsError) as ctx:
            switch_labels.parse(body)
        return ctx.exception.errors

    def test_header_must_match(self):
        errors = self.errors(switches_csv="mac,name\nx,y\n")
        self.assertEqual(errors[0]["line"], 1)

    def test_every_error_is_reported(self):
        text = (
            "chassis_mac,name,model,serial,management_ip,rack\n"
            "not-a-mac,a,,,,\n"
            "aa:bb:cc:00:00:01,,,,,\n"
            "aa:bb:cc:00:00:02,b,,,,\n"
            "AABBCC000002,c,,,,\n"
            "aa:bb:cc:00:00:03,d\n"
        )
        errors = self.errors(
            switches_csv=text, ports_csv="chassis_mac,port_id,port_name\naa:bb:cc:00:00:01,p1,\n"
        )
        got = [(e["table"], e["line"], e["field"]) for e in errors]
        self.assertEqual(
            got,
            [
                ("switches", 2, "chassis_mac"),
                ("switches", 3, "name"),
                ("switches", 5, "chassis_mac"),
                ("switches", 6, ""),
                ("ports", 2, "port_name"),
            ],
        )
        self.assertTrue(all(e["message"] for e in errors))

    def test_duplicate_port_key(self):
        text = PORTS + "aa:bb:cc:00:00:01,swp1,other\n"
        self.assertEqual(self.errors(ports_csv=text)[0]["line"], 3)

    def test_port_key_matches_page_normalisation(self):
        text = PORTS + "aa:bb:cc:00:00:01,SWP1,other\n"
        self.assertEqual(self.errors(ports_csv=text)[0]["line"], 3)
        mac_ports = (
            "chassis_mac,port_id,port_name\n"
            "aa:bb:cc:00:00:01,02-00-00-BB-00-01,P-1\n"
            "aa:bb:cc:00:00:01,02:00:00:bb:00:01,P-2\n"
        )
        self.assertEqual(self.errors(ports_csv=mac_ports)[0]["line"], 3)
        _, ports = switch_labels.parse(
            {"switches_csv": "", "ports_csv": mac_ports.rsplit("\n", 2)[0] + "\n", "revision": ""}
        )
        self.assertEqual(ports[0]["port_id"], "02:00:00:bb:00:01")

    def test_row_limit(self):
        rows = "".join(f"aa:bb:cc:00:00:01,p{i},n\n" for i in range(2001))
        errors = self.errors(ports_csv="chassis_mac,port_id,port_name\n" + rows)
        self.assertIn("2000", errors[0]["message"])

    def test_unknown_field_rejected(self):
        with self.assertRaises(ValueError):
            switch_labels.parse({"other": 1})


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.dir.name) / "db.sqlite"))

    def tearDown(self):
        self.dir.cleanup()

    def test_save_and_conflict(self):
        self.assertEqual(self.store.switch_labels()["revision"], "")
        saved = switch_labels.save(
            self.store, {"switches_csv": SWITCHES, "ports_csv": PORTS, "revision": ""}
        )
        self.assertTrue(saved["revision"])
        self.assertEqual(self.store.switch_labels(), saved)
        with self.assertRaises(switch_labels.SwitchLabelsConflict):
            switch_labels.save(self.store, {"switches_csv": "", "ports_csv": "", "revision": ""})
        cleared = switch_labels.save(
            self.store, {"switches_csv": "", "ports_csv": PORTS, "revision": saved["revision"]}
        )
        self.assertEqual(cleared["switches"], [])
        self.assertEqual(len(self.store.switch_labels()["ports"]), 1)

    def test_invalid_input_saves_nothing(self):
        with self.assertRaises(switch_labels.SwitchLabelsError):
            switch_labels.save(self.store, {"switches_csv": SWITCHES, "ports_csv": "bad\n"})
        self.assertEqual(self.store.switch_labels()["switches"], [])


class Routes(QueryRoutes, CommandRoutes):
    def __init__(self, path, enabled, store):
        self.path, self.result = path, None
        self.app = type(
            "App",
            (),
            {
                "config": {"rack_operations": enabled},
                "store": store,
                "nico_deployment": SimpleNamespace(preflight=None, start=None, connect=None),
                "readiness": lambda _: {"business_available": True},
            },
        )()

    def session(self):
        return {"csrf": "x", "token": "t"}

    def respond(self, code, payload, headers=None):
        self.result = (code, payload)


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.dir.name) / "db.sqlite"))

    def tearDown(self):
        self.dir.cleanup()

    def post(self, body, enabled=True):
        route = Routes("/api/switch-labels", enabled, self.store)
        route.dispatch_command("/api/switch-labels", body, {"token": "t"})
        return route.result

    def test_post_statuses(self):
        code, saved = self.post({"switches_csv": SWITCHES, "ports_csv": PORTS, "revision": ""})
        self.assertEqual(code, 200)
        code, payload = self.post({"switches_csv": "x\n", "ports_csv": "", "revision": ""})
        self.assertEqual(code, 400)
        self.assertEqual(payload["errors"][0]["line"], 1)
        code, payload = self.post({"switches_csv": "", "ports_csv": "", "revision": "stale"})
        self.assertEqual(code, 409)
        route = Routes("/api/switch-labels", True, self.store)
        route.get_request()
        self.assertEqual(route.result, (200, saved))

    def test_gate_off(self):
        for enabled in (False, None, "true"):
            code, _ = self.post({"switches_csv": "", "ports_csv": ""}, enabled)
            self.assertEqual(code, 404)
            route = Routes("/api/switch-labels", enabled, self.store)
            route.get_request()
            self.assertNotEqual(route.result[0], 200)
        self.assertEqual(self.store.switch_labels()["revision"], "")

    def test_read_only_observer_refuses_the_post(self):
        config = {"read_only": True, "rack_operations": True}
        self.assertFalse(read_only.command_allowed(config, "/api/switch-labels"))


if __name__ == "__main__":
    unittest.main()
