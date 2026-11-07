"""Hardware read-model identity, cached evidence, change handling and no hardware writes."""

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tests.unit.test_first_install import FakeSite
from pxeye.services.resources import Resources
from pxeye.common import digest
from pxeye.persistence.store import Store
from pxeye.services.hardware import Hardware, facts


class HardwareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.site = FakeSite(Path(self.tmp.name), 1)
        self.store = Store(self.site.data / "console.sqlite3")
        self.resources = Resources(self.site, self.store)
        self.resources.devices()
        self.hardware = Hardware(self.site, self.resources)

    def tearDown(self):
        self.tmp.cleanup()

    def test_ready_automatic_binding_and_read_never_writes_hardware_or_plans(self):
        before = digest(self.resources.planned_inventory())
        result = self.hardware.read("NEW-01")
        self.assertEqual(result["phase"], "ready")
        self.assertTrue(result["identity_matches"])
        self.assertTrue(all(m["complete"] for m in result["milestones"]))
        self.assertEqual(result["hardware"]["disks"][0]["serial"], "SCOUT-DISK-0")
        self.assertEqual(digest(self.resources.planned_inventory()), before)
        self.assertEqual(self.site.writes, [])

    def test_ip_fallback_never_verifies_a_different_mac_or_serial(self):
        m = self.site.machines[0]
        for mutation in ("mac", "serial"):
            with self.subTest(mutation=mutation):
                original = copy.deepcopy(m)
                if mutation == "mac":
                    m["bmc_info"]["mac"] = "02:00:00:00:ff:ff"
                else:
                    m["status"]["discovery_info"]["dmi_data"]["product_serial"] = "OTHER-SN"
                result = self.hardware.read("NEW-01")
                self.assertEqual(result["phase"], "identity_conflict")
                self.assertFalse(result["identity_matches"])
                self.assertFalse(result["milestones"][1]["complete"])
                self.assertFalse(result["milestones"][2]["complete"])
                self.assertIsNone(result["hardware"])
                self.assertFalse(self.hardware.path("NEW-01").exists())
                self.assertFalse(self.resources.devices()[0]["first_install_ready"])
                m.clear()
                m.update(original)

    def test_missing_machine_is_waiting_not_claimed_collecting_or_ready(self):
        self.site.machines = []
        for gate, can in [
            ("WaitingForIngestion", True),
            ("IngestionMachineNotCreated", False),
            ("NotDiscovered", False),
        ]:
            self.site.gates[self.site.rows[0]["bmc_mac_address"]] = gate
            result = self.hardware.read("NEW-01")
            self.assertEqual(result["can_prepare"], can)
            self.assertFalse(result["auto_refresh"])
            self.assertFalse(result["milestones"][1]["complete"])
        self.assertEqual(self.site.writes, [])

    def test_observation_failure_keeps_evidence_but_cannot_report_ready(self):
        first = self.hardware.read("NEW-01")
        original = self.site.core

        def fail(args, data=False):
            if args[:2] == ["machine", "show"]:
                raise RuntimeError("Core offline")
            return original(args, data)

        with patch.object(self.site, "core", side_effect=fail):
            result = self.hardware.read("NEW-01")
        self.assertEqual(result["hardware"], first["hardware"])
        self.assertFalse(result["available"])
        self.assertEqual(result["phase"], "unavailable")
        self.assertFalse(result["auto_refresh"])
        self.assertEqual(result["hardware_read_at"], first["hardware_read_at"])

    def test_hardware_change_records_added_removed_parts_without_changing_plan(self):
        self.hardware.read("NEW-01")
        before = digest(self.resources.planned_inventory())
        info = self.site.machines[0]["status"]["discovery_info"]
        info["network_interfaces"] = [{"mac_address": "02:00:00:00:09:09"}]
        info["block_devices"][0]["serial"] = "REPLACED-DISK"
        result = self.hardware.read("NEW-01")
        self.assertTrue(any("网卡不再回报" in x for x in result["changes"]))
        self.assertTrue(any("磁盘新增" in x for x in result["changes"]))
        self.assertTrue(any("规划网卡" in x for x in result["conflicts"]))
        self.assertEqual(digest(self.resources.planned_inventory()), before)
        self.assertEqual(self.site.writes, [])

    def test_memory_groups_preferred_and_capacity_only_from_native_nvme_field(self):
        m = copy.deepcopy(self.site.machines[0])
        info = m["status"]["discovery_info"]
        info.update(
            cpu_info=[{"model": "TEST", "sockets": 2, "cores": 64, "threads": 128}],
            memory_device_groups=[{"size_mb": 32768, "count": 2}],
            memory_devices=[{"size_mb": 1024}],
            nvme_devices=[{"serial": "SCOUT-DISK-0", "size_mb": 1000000}],
        )
        result = facts(m)
        self.assertEqual(result["memory_mb"], 65536)
        self.assertEqual(result["disks"][0]["size_mb"], 1000000)
        info["memory_device_groups"] = []
        self.assertEqual(facts(m)["memory_mb"], 1024)


if __name__ == "__main__":
    unittest.main()
