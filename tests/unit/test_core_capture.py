"""A capture replays into the same console responses, and drift is reported.

The round trip runs the real backend twice: once against a stand-in Core while
tools/core-capture.py records, once from the recording alone with tools/core-replay.py.
"""

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from pxeye.clients.core import CoreClient
from pxeye.clients.redfish import RedfishClient
from pxeye.deployment import kubernetes
from tests.unit import test_device_status as samples

TOOLS = Path(__file__).resolve().parents[2] / "tools"
MACHINE_ID = "fm100hexample0"
HISTORY = {
    "histories": {
        MACHINE_ID: {
            "records": [
                {"event": '{"state": "created"}', "time": "2026-01-01T00:00:00.123456789Z"},
                {
                    "event": '{"state": "hostinit", "machine_state": {"state": "waitingforlockdown"}}',
                    "time": "2026-01-01T00:05:00Z",
                },
                {"event": '{"state": "ready"}', "time": "2026-01-01T01:00:00Z"},
            ]
        }
    }
}
INVENTORY = {
    "entries": [
        {
            "result": {"componentId": MACHINE_ID},
            "report": {
                "endpointType": "Bmc",
                "chassis": [{"id": "1", "model": "Model-X", "partNumber": "PN-1"}],
                "service": [
                    {
                        "id": "FirmwareInventory",
                        "inventories": [
                            {"id": "BMC-Primary", "description": "BMC", "version": "1.0"}
                        ],
                    }
                ],
                "lockdownStatus": {"message": "placeholder"},
                "secureBootStatus": {},
            },
        }
    ]
}
SECRET = "must-not-appear-in-a-capture"


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stand_in_core():
    machine = copy.deepcopy(samples.MACHINE)
    machine["id"] = {"id": MACHINE_ID}
    answers = {
        "FindMachineIds": {"machineIds": [{"id": MACHINE_ID}]},
        "FindMachinesByIds": {"machines": [machine]},
        "FindSwitches": {"switches": [samples.SWITCH]},
        "FindPowerShelves": {"powerShelves": [samples.SHELF]},
        "FindMachineStateHistories": HISTORY,
        "GetComponentInventory": INVENTORY,
    }
    expected = {
        "expected_machines": [
            {
                "bmc_mac_address": "aa:bb:cc:00:00:01",
                "chassis_serial_number": "SN-0001",
                "bmc_username": "admin",
                "bmc_password": SECRET,
                "host_nics": [],
            }
        ]
    }

    def rpc(self, method, body):
        return copy.deepcopy(answers.get(method, {}))

    def cli(self, args, *, data=False):
        if list(args[:2]) == ["expected-machine", "show"]:
            return copy.deepcopy(expected)
        return {} if data else ""

    return rpc, cli


class CaptureReplayTests(unittest.TestCase):
    def setUp(self):
        patched = [
            (CoreClient, "rpc"),
            (CoreClient, "core"),
            (CoreClient, "check_core_certificate"),
            (RedfishClient, "redfish_request"),
            (kubernetes.CurrentCluster, "request"),
        ]
        saved = [(owner, name, owner.__dict__[name]) for owner, name in patched]
        self.addCleanup(lambda: [setattr(owner, name, value) for owner, name, value in saved])
        self.work = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.work, True)
        saved_env = {
            k: os.environ.get(k) for k in ("CONSOLE_CONFIG", "CONSOLE_DATA", "CONSOLE_SECRETS")
        }
        self.addCleanup(
            lambda: [
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
                for k, v in saved_env.items()
            ]
        )

    def capture(self):
        CoreClient.rpc, CoreClient.core = stand_in_core()
        CoreClient.check_core_certificate = lambda self: None
        data, secrets = self.work / "data", self.work / "secrets"
        (data / "config").mkdir(parents=True)
        secrets.mkdir()
        (secrets / "bootstrap-password").write_text("placeholder\n")
        (secrets / "auth.json").write_text(
            json.dumps({"password_sha256": hashlib.sha256(b"placeholder").hexdigest()})
        )
        for name in ("ca.crt", "client.crt", "client.key"):
            (secrets / name).write_text("placeholder")
        site = {
            "site": {"name": "Test", "namespace": "", "deployment": ""},
            "core_url": "https://core.example:1079",
            "nico_deployment": {"enabled": False, "namespace": "test"},
        }
        (self.work / "site.json").write_text(json.dumps(site))
        os.environ.update(
            CONSOLE_CONFIG=str(self.work / "site.json"),
            CONSOLE_DATA=str(data),
            CONSOLE_SECRETS=str(secrets),
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            load("core-capture").main()
        return json.loads(output.getvalue())

    def replay(self, capture):
        replay = load("core-replay")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            server, password, recorded, work = replay.start(capture, 0)
            try:
                report = io.StringIO()
                failures = replay.check(capture, server, password, report)
            finally:
                server.shutdown()
                shutil.rmtree(work, ignore_errors=True)
        return failures, sorted(set(recorded.missing)), report.getvalue()

    def test_a_capture_replays_into_the_responses_it_recorded(self):
        capture = self.capture()
        self.assertNotIn(SECRET, json.dumps(capture))
        responses = capture["pxeye_responses"]
        self.assertEqual(
            responses[f"/api/device-status/machines/{MACHINE_ID}/history"]["status"], 200
        )
        self.assertEqual(
            responses[f"/api/device-status/machines/{MACHINE_ID}/firmware"]["status"], 200
        )
        methods = {call.get("method") for call in capture["core_calls"]}
        self.assertTrue(
            {"FindMachinesByIds", "FindMachineStateHistories", "GetComponentInventory"} <= methods
        )

        failures, missing, report = self.replay(capture)
        self.assertEqual((failures, missing), (0, []), report)

        changed = copy.deepcopy(capture)
        for call in changed["core_calls"]:
            if call.get("method") == "FindMachineStateHistories":
                call["response"]["histories"][MACHINE_ID]["records"].append(
                    {"event": '{"state": "assigned"}', "time": "2026-01-01T02:00:00Z"}
                )
        failures, missing, report = self.replay(changed)
        self.assertEqual(failures, 1, report)
        self.assertIn("/history", report)

        removed = copy.deepcopy(capture)
        removed["core_calls"] = [
            call for call in removed["core_calls"] if call.get("method") != "GetComponentInventory"
        ]
        failures, missing, report = self.replay(removed)
        self.assertEqual(failures, 1, report)
        self.assertEqual(len(missing), 1)
        self.assertIn("GetComponentInventory", missing[0])


if __name__ == "__main__":
    unittest.main()
