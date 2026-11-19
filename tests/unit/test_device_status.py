"""Core's operational state is reshaped for the device pages without inventing data."""

import unittest

from pxeye.api.queries import QueryRoutes
from pxeye.services.device_status import (
    DeviceStatus,
    health,
    lifecycle,
    machine_firmware,
    state_text,
)

MACHINE = {
    "id": {"id": "fm100h-host"},
    "state": "Ready",
    "machineType": "HOST",
    "rackId": {"value": "rack-a01"},
    "placementInRack": {"slotNumber": 12, "trayIndex": 3},
    "bmc": {"ip": "192.0.2.10", "mac": "AA:BB:CC:00:00:01"},
    "config": {"hwSku": "gpu.8x", "maintenanceReference": "TICKET-1"},
    "status": {
        "lifecycle": {
            "state": '{"state":"hostinit","machine_state":{"state":"waitingfordiscovery"}}',
            "stateReason": {"outcome": "ERROR", "outcomeMsg": "scout timeout"},
            "sla": {"timeInStateAboveSla": True},
        },
        "health": {
            "observedAt": "2026-11-19T08:00:00Z",
            "alerts": [
                {
                    "id": "FanSpeed",
                    "target": "fan3",
                    "message": "below threshold",
                    "inAlertSince": "2026-11-19T07:00:00Z",
                    "classifications": ["PreventAllocations"],
                }
            ],
        },
        "bmcStatus": {"firmwareVersion": "2.44"},
        "capabilities": {"gpu": [{"name": "H100", "count": 8, "capacity": "80 GiB"}]},
        "quarantine": {"mode": "BLOCK_ALL_TRAFFIC", "reason": "sku mismatch"},
        "associatedDpuMachineIds": [{"id": "fm100d-dpu"}],
        "lldpNeighbors": [
            {
                "macAddress": "AA:BB:CC:00:00:02",
                "lldp": {
                    "name": "leaf-1",
                    "localPort": "ens2f0np0",
                    "idValue": "60:db:15:b6:cb:3e",
                    "remotePortType": "mac",
                    "remotePortValue": "60:db:15:b6:cb:8c",
                    "medInventory": {"serial": "SW123", "manufacturer": "H3C", "model": "S6520X"},
                },
            }
        ],
    },
}
DPU = {"id": {"id": "fm100d-dpu"}, "machineType": "DPU", "status": {}}
SWITCH = {
    "id": {"value": "sw-1"},
    "isPrimary": True,
    "bmcInfo": {"ip": "192.0.2.20", "mac": "aa:bb:cc:00:00:10", "firmwareVersion": "1.9"},
    "status": {
        "healthStatus": "warning",
        "health": {"alerts": [{"id": "Psu", "message": "psu2 missing"}]},
        "powerState": "ON",
        "controllerState": "ready",
        "fabricManagerStatusDetails": {"fabricManagerState": "FABRIC_MANAGER_STATE_NOT_OK"},
        "nvosPorts": [
            {
                "mac": "AA:BB:CC:00:00:11",
                "isPrimary": True,
                "addresses": [{"address": "192.0.2.21"}],
            }
        ],
    },
}
SHELF = {
    "id": {"value": "ps-1"},
    "config": {"capacity": 33000, "voltage": 48},
    "status": {"powerState": "on", "controllerState": "ready"},
}


class Core:
    def __init__(self, failing=()):
        self.failing = failing

    def rpc(self, method, body):
        if method in self.failing:
            raise RuntimeError("unavailable")
        return {
            "FindMachineIds": {"machineIds": [{"id": "fm100h-host"}, {"id": "fm100d-dpu"}]},
            "FindMachinesByIds": {"machines": [MACHINE, DPU]},
            "FindSwitches": {"switches": [SWITCH, {"id": {"value": "gone"}, "deleted": "t"}]},
            "FindPowerShelves": {"powerShelves": [SHELF]},
        }[method]


class DeviceStatusTests(unittest.TestCase):
    def test_state_is_read_as_text_or_as_a_nested_document(self):
        self.assertEqual(state_text("Ready"), "Ready")
        self.assertEqual(state_text('{"state":"ready"}'), "ready")
        self.assertEqual(
            state_text('{"state":"hostinit","machine_state":{"state":"waiting"}}'),
            "hostinit/waiting",
        )
        self.assertEqual(state_text(None), "")
        self.assertEqual(state_text('{"other":1}'), '{"other":1}')

    def test_an_absent_health_report_is_unknown_not_healthy(self):
        self.assertEqual(health({"status": {}})["level"], "unknown")
        self.assertEqual(health({"status": {"health": {}}})["level"], "ok")
        self.assertEqual(health({})["level"], "unknown")
        self.assertEqual(lifecycle({})["state"], "")

    def test_each_kind_keeps_its_core_identifier_and_reported_state(self):
        view = DeviceStatus(Core()).view()
        self.assertEqual(view["errors"], [])
        host = view["servers"]["fm100h-host"]
        self.assertEqual(host["type"], "host")
        self.assertEqual(
            host["lifecycle"],
            {
                "state": "hostinit/waitingfordiscovery",
                "outcome": "error",
                "reason": "scout timeout",
                "above_sla": True,
            },
        )
        self.assertEqual(host["health"]["level"], "alert")
        self.assertEqual(host["health"]["alerts"][0]["target"], "fan3")
        self.assertEqual(
            host["bmc"],
            {
                "ip": "192.0.2.10",
                "mac": "aa:bb:cc:00:00:01",
                "version": "",
                "firmware_version": "2.44",
            },
        )
        self.assertEqual(host["placement"], {"slot": 12, "tray": 3})
        self.assertEqual(host["rack_id"], "rack-a01")
        self.assertEqual(host["sku"]["id"], "gpu.8x")
        self.assertEqual(host["quarantine"]["reason"], "sku mismatch")
        self.assertEqual(host["dpu_ids"], ["fm100d-dpu"])
        self.assertEqual(host["capabilities"]["gpu"][0]["count"], 8)
        self.assertEqual(
            host["lldp"],
            [
                {
                    "mac_address": "aa:bb:cc:00:00:02",
                    "local_port": "ens2f0np0",
                    "switch": "leaf-1",
                    "switch_id": "60:db:15:b6:cb:3e",
                    "switch_model": "S6520X",
                    "switch_serial": "SW123",
                    "remote_port": "60:db:15:b6:cb:8c",
                    "remote_port_type": "mac",
                    "description": "",
                }
            ],
        )
        self.assertEqual(view["servers"]["fm100d-dpu"]["type"], "dpu")
        self.assertEqual(view["servers"]["fm100d-dpu"]["health"]["level"], "unknown")

        switch = view["switches"]["sw-1"]
        self.assertNotIn("gone", view["switches"])
        self.assertEqual(switch["health"]["level"], "warning")
        self.assertEqual(switch["power_state"], "on")
        self.assertEqual(switch["lifecycle"]["state"], "ready")
        self.assertEqual(switch["fabric_manager"]["state"], "not_ok")
        self.assertEqual(switch["bmc"]["firmware_version"], "1.9")
        self.assertEqual(
            switch["nvos_ports"],
            [
                {
                    "mac": "aa:bb:cc:00:00:11",
                    "primary": True,
                    "service_port": None,
                    "addresses": ["192.0.2.21"],
                }
            ],
        )

        shelf = view["power_shelves"]["ps-1"]
        self.assertEqual((shelf["capacity_watts"], shelf["voltage"]), (33000, 48))
        self.assertEqual(shelf["health"]["level"], "unknown")

    def test_one_unreadable_kind_is_reported_and_does_not_hide_the_others(self):
        view = DeviceStatus(Core(failing=("FindSwitches",))).view()
        self.assertEqual(view["switches"], {})
        self.assertEqual(len(view["errors"]), 1)
        self.assertIn("交换机", view["errors"][0])
        self.assertIn("fm100h-host", view["servers"])
        self.assertIn("ps-1", view["power_shelves"])

    def test_a_site_without_machines_reads_as_empty(self):
        class Empty(Core):
            def rpc(self, method, body):
                return {}

        view = DeviceStatus(Empty()).view()
        self.assertEqual(
            (view["servers"], view["switches"], view["power_shelves"], view["errors"]),
            ({}, {}, {}, []),
        )


INVENTORY = {
    "entries": [
        {
            "result": {"componentId": "machine0"},
            "report": {
                "endpointType": "Bmc",
                "vendor": "VendorA",
                "chassis": [
                    {"id": "0", "model": ""},
                    {"id": "1", "model": "Model-1", "partNumber": "PN-1", "manufacturer": "MakerA"},
                ],
                "service": [
                    {"id": "Other", "inventories": [{"id": "ignored", "version": "9"}]},
                    {
                        "id": "FirmwareInventory",
                        "inventories": [
                            {
                                "id": "VendorBmc",
                                "description": "Management controller firmware.",
                                "version": "1.0",
                                "releaseDate": "2026-01-01T00:00:00Z",
                            },
                            {
                                "id": "Slot_1.Bundle",
                                "description": "Adapter",
                                "version": "",
                                "releaseDate": None,
                            },
                        ],
                    },
                ],
                "secureBootStatus": {},
                "lockdownStatus": {"message": "Lockdown disabled"},
            },
        }
    ]
}


class Inventory:
    def __init__(self, response):
        self.response, self.calls = response, []

    def rpc(self, method, body):
        self.calls.append((method, body))
        return self.response


class FirmwareTests(unittest.TestCase):
    def test_the_inventory_is_listed_as_reported(self):
        core = Inventory(INVENTORY)
        data = machine_firmware(core, "machine0")
        self.assertEqual(
            core.calls,
            [("GetComponentInventory", {"machineIds": {"machineIds": [{"id": "machine0"}]}})],
        )
        self.assertTrue(data["reported"])
        self.assertEqual((data["vendor"], data["endpoint_type"]), ("VendorA", "Bmc"))
        self.assertEqual(
            data["chassis"], {"model": "Model-1", "part_number": "PN-1", "manufacturer": "MakerA"}
        )
        self.assertEqual((data["lockdown"], data["secure_boot"]), ("Lockdown disabled", {}))
        self.assertEqual(
            data["entries"],
            [
                {
                    "id": "VendorBmc",
                    "description": "Management controller firmware.",
                    "version": "1.0",
                    "release_date": "2026-01-01T00:00:00Z",
                },
                {
                    "id": "Slot_1.Bundle",
                    "description": "Adapter",
                    "version": "",
                    "release_date": "",
                },
            ],
        )

    def test_a_missing_report_is_empty_with_a_note(self):
        for response in ({}, {"entries": []}, {"entries": [{"result": {}}]}, None):
            data = machine_firmware(Inventory(response), "machine0")
            self.assertFalse(data["reported"])
            self.assertEqual(data["entries"], [])
            self.assertTrue(data["note"])
            self.assertIsNone(data["secure_boot"])

    def test_an_invalid_id_is_refused_before_any_call(self):
        for bad in ("", "Machine0", "a-b", "a/b", "x" * 129, None):
            core = Inventory(INVENTORY)
            with self.assertRaises(ValueError):
                machine_firmware(core, bad)
            self.assertEqual(core.calls, [])


class Route(QueryRoutes):
    def __init__(self, path, enabled):
        self.path, self.result = path, None
        self.core = Inventory(INVENTORY)
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


class FirmwareRouteTests(unittest.TestCase):
    PATH = "/api/device-status/machines/machine0/firmware"

    def test_the_route_reads_when_the_switch_is_on(self):
        route = Route(self.PATH, True)
        route.get_request()
        self.assertEqual(route.result[0], 200)
        self.assertEqual(len(route.result[1]["entries"]), 2)

    def test_the_route_does_not_exist_when_the_switch_is_off(self):
        route = Route(self.PATH, False)
        route.get_request()
        self.assertEqual(route.result[0], 404)
        self.assertEqual(route.core.calls, [])

    def test_an_invalid_id_is_not_found(self):
        route = Route("/api/device-status/machines/Bad-Id/firmware", True)
        route.get_request()
        self.assertEqual(route.result[0], 404)
        self.assertEqual(route.core.calls, [])


if __name__ == "__main__":
    unittest.main()
