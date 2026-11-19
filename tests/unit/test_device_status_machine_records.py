"""Health history and hardware validation of one machine, read from Core without writing."""

import unittest

from pxeye.api.queries import QueryRoutes
from pxeye.services.device_status import (
    machine_health_history,
    machine_validation,
    validation_status,
)

MACHINE = "machine0"
ALERT = {
    "id": "PoweredOff",
    "target": "203.0.113.10",
    "inAlertSince": "2026-01-01T01:00:00.123456789Z",
    "message": "power state is Off",
    "classifications": ["PreventAllocations", "Hardware"],
}
HEALTH = {
    "histories": {
        MACHINE: {
            "records": [
                # Out of order on purpose.
                {"health": {"source": "agg"}, "time": "2026-01-01T03:00:00Z"},
                {"health": {"alerts": [ALERT]}, "time": "2026-01-01T01:00:01Z"},
                {
                    "health": {"alerts": [ALERT | {"message": "still off"}, {"id": "Fan"}]},
                    "time": "2026-01-01T02:00:00Z",
                },
                {"health": {"alerts": [{"id": "Fan"}]}, "time": "2026-01-01T04:00:00Z"},
                {"health": "bad", "time": "not a time"},
            ]
        }
    }
}
RUN = {
    "validationId": {"value": "run-1"},
    "machineId": {"id": MACHINE},
    "startTime": "2026-01-01T00:00:00Z",
    "endTime": "2026-01-01T00:00:02Z",
    "name": "Test_run",
    "context": "Discovery",
    "status": {"completed": "Skipped"},
    "durationToComplete": "2s",
}


class Core:
    def __init__(self, responses):
        self.responses, self.calls = responses, []

    def rpc(self, method, body):
        self.calls.append((method, body))
        return self.responses.get(method)


class HealthHistoryTests(unittest.TestCase):
    def test_alert_periods_are_derived_from_the_records(self):
        core = Core({"FindMachineHealthHistories": HEALTH})
        data = machine_health_history(core, MACHINE)
        self.assertEqual(
            core.calls, [("FindMachineHealthHistories", {"machineIds": [{"id": MACHINE}]})]
        )
        self.assertEqual(data["record_count"], 4)
        self.assertEqual(data["first_record"], "2026-01-01T01:00:01Z")
        self.assertEqual(data["last_record"], "2026-01-01T04:00:00Z")
        fan, fan_before, power = data["alerts"]
        self.assertEqual(
            power,
            {
                "id": "PoweredOff",
                "target": "203.0.113.10",
                "since": "2026-01-01T01:00:00.123456789Z",
                "last_seen": "2026-01-01T02:00:00Z",
                "message": "still off",
                "classifications": ["PreventAllocations", "Hardware"],
                "active": False,
            },
        )
        # Without inAlertSince the first record showing it is the start. The healthy
        # record at 03:00 ends the first Fan period; its return at 04:00 is a new one.
        self.assertEqual(
            (fan_before["since"], fan_before["last_seen"], fan_before["active"]),
            ("2026-01-01T02:00:00Z", "2026-01-01T02:00:00Z", False),
        )
        self.assertEqual(fan["since"], "2026-01-01T04:00:00Z")
        self.assertEqual((fan["target"], fan["classifications"], fan["active"]), ("", [], True))

    def test_healthy_or_missing_history_has_no_alerts(self):
        healthy = {
            "histories": {MACHINE: {"records": [{"health": {}, "time": "2026-01-01T00:00:00Z"}]}}
        }
        self.assertEqual(
            machine_health_history(Core({"FindMachineHealthHistories": healthy}), MACHINE)[
                "alerts"
            ],
            [],
        )
        for response in (None, {}, {"histories": {}}, {"histories": {"other": HEALTH}}):
            data = machine_health_history(Core({"FindMachineHealthHistories": response}), MACHINE)
            self.assertEqual(
                (data["record_count"], data["alerts"], data["first_record"]), (0, [], "")
            )

    def test_an_invalid_id_is_refused_before_any_call(self):
        for bad in ("", "Machine0", "a-b", "a/b", "x" * 129, None):
            core = Core({})
            with self.assertRaises(ValueError):
                machine_health_history(core, bad)
            self.assertEqual(core.calls, [])


class ValidationTests(unittest.TestCase):
    def test_runs_and_results_are_read_with_history(self):
        result = {
            "name": "CpuTest",
            "validationId": {"value": "run-1"},
            "stdOut": "x" * 5000,
            "startTime": "2026-01-01T00:00:01Z",
        }
        core = Core(
            {
                "GetMachineValidationRuns": {"runs": [RUN]},
                "GetMachineValidationResults": {"results": [result, result | {"exitCode": 3}]},
            }
        )
        data = machine_validation(core, MACHINE)
        body = {"machineId": {"id": MACHINE}, "includeHistory": True}
        self.assertEqual(
            core.calls,
            [("GetMachineValidationRuns", body), ("GetMachineValidationResults", body)],
        )
        (run,) = data["runs"]
        self.assertEqual(run["validation_id"], "run-1")
        self.assertEqual(
            (run["name"], run["context"], run["duration_seconds"]), ("Test_run", "Discovery", 2.0)
        )
        self.assertEqual((run["status"]["phase"], run["status"]["text"]), ("completed", "Skipped"))
        self.assertEqual(run["status_raw"], {"completed": "Skipped"})
        first, second = data["results"]["run-1"]
        self.assertEqual(len(first["std_out"]), 2000)
        self.assertEqual((first["exit_code"], second["exit_code"], first["std_err"]), (0, 3, ""))

    def test_no_runs_or_results(self):
        for runs, results in ((None, None), ({}, {}), ({"runs": []}, {})):
            data = machine_validation(
                Core({"GetMachineValidationRuns": runs, "GetMachineValidationResults": results}),
                MACHINE,
            )
            self.assertEqual((data["runs"], data["results"]), ([], {}))

    def test_status_variants(self):
        self.assertEqual(validation_status({"inProgress": None})["phase"], "in_progress")
        self.assertEqual(validation_status({"completed": None})["outcome"], "Success")
        self.assertEqual(validation_status({"total": 4})["phase"], "")
        self.assertEqual(validation_status(None)["text"], "")

    def test_an_invalid_id_is_refused_before_any_call(self):
        for bad in ("", "A", "a b", None):
            core = Core({})
            with self.assertRaises(ValueError):
                machine_validation(core, bad)
            self.assertEqual(core.calls, [])


class Route(QueryRoutes):
    def __init__(self, path, enabled):
        self.path, self.result = path, None
        self.core = Core(
            {
                "FindMachineHealthHistories": HEALTH,
                "GetMachineValidationRuns": {"runs": [RUN]},
                "GetMachineValidationResults": {},
            }
        )
        self.app = type(
            "App",
            (),
            {
                "config": {"rack_operations": enabled},
                "adapter": self.core,
                "readiness": lambda _: {"business_available": True},
            },
        )()

    def session(self):
        return {"csrf": "x"}

    def respond(self, code, payload, headers=None):
        self.result = (code, payload)


class RouteTests(unittest.TestCase):
    def test_routes_read_when_the_switch_is_on(self):
        route = Route(f"/api/device-status/machines/{MACHINE}/health", True)
        route.get_request()
        self.assertEqual((route.result[0], route.result[1]["record_count"]), (200, 4))
        route = Route(f"/api/device-status/machines/{MACHINE}/validation", True)
        route.get_request()
        self.assertEqual((route.result[0], len(route.result[1]["runs"])), (200, 1))

    def test_routes_do_not_exist_with_the_switch_off_or_a_bad_id(self):
        for path, enabled in (
            (f"/api/device-status/machines/{MACHINE}/health", False),
            (f"/api/device-status/machines/{MACHINE}/validation", False),
            ("/api/device-status/machines/Bad-Id/health", True),
            ("/api/device-status/machines/Bad-Id/validation", True),
        ):
            route = Route(path, enabled)
            route.get_request()
            self.assertEqual(route.result[0], 404)
            self.assertEqual(route.core.calls, [])


if __name__ == "__main__":
    unittest.main()
