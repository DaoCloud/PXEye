"""The site exploration report is reduced to a diagnostic summary without inventing data."""

import unittest
from unittest import mock

from pxeye.api.queries import QueryRoutes
from pxeye.services.exploration import duration_seconds, error_type, exploration, last_run

FAILED = {
    "address": "192.0.2.20",
    "report": {
        "endpointType": "Unknown",
        "lastExplorationError": '{"Type":"ConnectionRefused","Details":"url: <address>"}',
        "lastExplorationLatency": "10.003920396s",
        "lastExplorationErrorSchema": {
            "errorCode": "NICO-SITEEXPLORER-101",
            "mitigation": "Verify endpoint network reachability.",
            "text": "the connection to the endpoint was refused",
        },
    },
    "reportVersion": "V1-T1",
    "preingestionState": "Initial",
    "lastRedfishBmcReset": "no timestamp available",
}
EXPLORED = {
    "address": "192.0.2.10",
    "report": {
        "endpointType": "Bmc",
        "vendor": "examplevendor",
        "lastExplorationLatency": "1.5s",
        "systems": [{"id": "1", "serialNumber": "SN-PLACEHOLDER", "model": "MODEL-X"}],
        "service": [{"id": "FirmwareInventory", "inventories": [{"id": "BMC"}]}],
        "chassis": [{"id": "1", "model": "CHASSIS"}],
    },
    "reportVersion": "V2-T2",
    "preingestionState": "Complete",
}
REPORT = {
    "endpoints": [EXPLORED, FAILED],
    "managedHosts": [{"hostBmcIp": "192.0.2.10"}, {}],
    "lastRun": {
        "startedAt": "2026-01-01T00:00:00+00:00",
        "finishedAt": "2026-01-01T00:00:19+00:00",
        "success": True,
        "endpointExplorations": "2",
        "endpointExplorationsSuccess": "1",
        "endpointExplorationsFailed": "1",
    },
}


class Core:
    def __init__(self, response):
        self.response, self.calls = response, []

    def rpc(self, method, payload):
        self.calls.append((method, payload))
        return self.response


class Routes(QueryRoutes):
    def __init__(self, path, config, adapter):
        self.path = path
        self.app = mock.Mock()
        self.app.config = config
        self.app.adapter = adapter
        self.app.readiness.return_value = {"business_available": True}

    def session(self):
        return {"csrf": "x"}

    def respond(self, code, payload, headers=None):
        return code, payload


class ExplorationTests(unittest.TestCase):
    def test_summary_keeps_failed_first_and_drops_the_inventory(self):
        core = Core(REPORT)
        data = exploration(core)
        self.assertEqual(core.calls, [("GetSiteExplorationReport", {})])
        failed, explored = data["endpoints"]
        self.assertEqual(failed["address"], "192.0.2.20")
        self.assertTrue(failed["failed"])
        self.assertEqual(failed["error"]["code"], "NICO-SITEEXPLORER-101")
        self.assertEqual(failed["error"]["type"], "ConnectionRefused")
        self.assertEqual(failed["latency_seconds"], 10.003920396)
        self.assertEqual(failed["last_redfish_bmc_reset"], "no timestamp available")
        self.assertFalse(failed["managed_host"])
        self.assertEqual(failed["serial"], "")
        self.assertFalse(explored["failed"])
        self.assertIsNone(explored["error"])
        self.assertTrue(explored["managed_host"])
        self.assertEqual((explored["serial"], explored["model"]), ("SN-PLACEHOLDER", "MODEL-X"))
        self.assertEqual(explored["vendor"], "examplevendor")
        for key in ("service", "chassis", "systems", "managers"):
            self.assertNotIn(key, explored)
        self.assertEqual(data["last_run"]["explorations"], 2)
        self.assertEqual(data["last_run"]["failed"], 1)
        self.assertTrue(data["last_run"]["success"])

    def test_empty_or_missing_response(self):
        for response in ({}, None, {"endpoints": [None, "x"]}):
            data = exploration(Core(response))
            self.assertEqual(data["endpoints"], [])
            self.assertIsNone(data["last_run"])

    def test_missing_report_fields_are_empty_not_assumed(self):
        data = exploration(Core({"endpoints": [{"address": "192.0.2.30"}]}))
        row = data["endpoints"][0]
        self.assertFalse(row["failed"])
        self.assertEqual(row["endpoint_type"], "")
        self.assertIsNone(row["latency_seconds"])

    def test_error_text_that_is_not_json_is_kept(self):
        self.assertEqual(error_type("plain failure"), "plain failure")
        self.assertEqual(error_type('["x"]'), '["x"]')
        self.assertEqual(error_type(None), "")
        row = exploration(
            Core({"endpoints": [{"address": "a", "report": {"lastExplorationError": "boom"}}]})
        )
        self.assertTrue(row["endpoints"][0]["failed"])
        self.assertEqual(row["endpoints"][0]["error"]["code"], "")

    def test_durations_and_counts(self):
        self.assertEqual(duration_seconds("2s"), 2.0)
        for bad in ("", "2", "xs", None, 3):
            self.assertIsNone(duration_seconds(bad))
        run = last_run({"startedAt": "t", "endpointExplorations": "nope"})
        self.assertIsNone(run["explorations"])
        self.assertEqual(run["failed"], 0)
        self.assertFalse(run["success"])
        self.assertIsNone(last_run(None))

    def test_route_reads_when_the_switch_is_on(self):
        core = Core(REPORT)
        code, payload = Routes("/api/exploration", {"rack_operations": True}, core).get_request()
        self.assertEqual(code, 200)
        self.assertEqual(len(payload["endpoints"]), 2)

    def test_route_does_not_exist_with_the_gate_off(self):
        core = Core(REPORT)
        for config in ({}, {"rack_operations": False}, {"rack_operations": "true"}):
            code, _ = Routes("/api/exploration", config, core).get_request()
            self.assertEqual(code, 404)
        self.assertEqual(core.calls, [])


if __name__ == "__main__":
    unittest.main()
