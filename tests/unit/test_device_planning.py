"""Arrival identity, delayed planning and BMC migration fault boundaries."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from pxeye.services.bmc_addresses import BMCAddresses
from pxeye.services.discovery import Discovery
from pxeye.services.onboarding import Onboarding
from pxeye.services.resources import Resources
from pxeye.common import atomic_json, digest
from pxeye.persistence.store import Store
from tests.unit.test_management import ManagementSite


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.site = ManagementSite(Path(self.tmp.name), number=10)
        self.store = Store(self.site.data / "console.sqlite3")
        self.resources = Resources(self.site, self.store)
        self.onboarding = Onboarding(self.site, self.store, self.resources)
        self.discovery = Discovery(self.site, self.resources, self.onboarding)
        self.addresses = BMCAddresses(self.site, self.resources)

    def tearDown(self):
        self.tmp.cleanup()

    def register(self):
        ids = [c["id"] for c in self.discovery.candidates()["candidates"]]
        self.discovery.authenticate(
            {"ids": ids, "username": "ops", "password": "BMC_TEST_PASSWORD"}, "owner"
        )
        self.discovery.enroll({"ids": ids, "confirm_registration": True}, "owner", "test")
        self.site.writes.clear()
        return self.site.rows[0]

    def report(self):
        link = self.site.links[0]
        self.site.endpoints = [
            {
                "address": link["address"][0],
                "reportVersion": "V10-TEST",
                "report": {
                    "endpointType": "Bmc",
                    "systems": [{"serialNumber": "NEW-01", "model": ""}],
                    "managers": [{"ethernetInterfaces": [{"macAddress": link["macAddress"]}]}],
                },
            }
        ]

    def test_existing_report_shows_sn_but_cannot_register_without_password(self):
        self.report()
        row = self.discovery.candidates()["candidates"][0]
        self.assertEqual(row["serial"], "NEW-01")
        self.assertEqual(row["identity_source"], "nico-report")
        self.assertFalse(row["authenticated"])
        with self.assertRaises(ValueError):
            self.discovery.enroll(
                {"ids": [row["id"]], "confirm_registration": True}, "owner", "test"
            )
        self.assertEqual(self.site.writes, [])

    def test_report_mac_conflict_and_multiple_systems_require_identity(self):
        self.report()
        self.site.endpoints[0]["report"]["managers"][0]["ethernetInterfaces"][0]["macAddress"] = (
            "00:00:00:00:00:00"
        )
        self.assertIsNone(self.discovery.candidates()["candidates"][0]["serial"])
        self.report()
        self.site.endpoints[0]["report"]["systems"].append({"serialNumber": "OTHER"})
        self.assertIsNone(self.discovery.candidates()["candidates"][0]["serial"])

    def test_ten_devices_can_stay_registered_across_service_restart(self):
        row = self.register()
        Discovery(self.site, self.resources, self.onboarding)
        devices = self.resources.devices()
        self.assertEqual(len(devices), 10)
        self.assertTrue(all(not d["first_install_ready"] for d in devices))
        self.assertTrue(all(not d["boot_mac"] for d in devices))
        self.assertEqual(self.addresses.view(row)["current_ip"], row["bmc_ip_address"])
        self.assertEqual(self.site.writes, [])
        self.assertNotIn("BMC_TEST_PASSWORD", json.dumps(devices))

    def test_identity_survives_expiry_but_registration_requires_current_proof(self):
        ids = [c["id"] for c in self.discovery.candidates()["candidates"]]
        self.discovery.authenticate(
            {"ids": ids, "username": "ops", "password": "BMC_TEST_PASSWORD"}, "owner"
        )
        path = self.discovery.directory / (ids[0] + ".json")
        proof = json.loads(path.read_text())
        proof["verified_at"] = 1
        atomic_json(path, proof)
        candidate = self.discovery.candidates()["candidates"][0]
        self.assertEqual(candidate["serial"], "NEW-01")
        self.assertFalse(candidate["authenticated"])
        with self.assertRaises(ValueError):
            self.discovery.enroll({"ids": [ids[0]], "confirm_registration": True}, "owner", "test")

    def test_ip_change_preserves_candidate_id_and_invalidates_authentication(self):
        ids = [c["id"] for c in self.discovery.candidates()["candidates"]]
        self.discovery.authenticate(
            {"ids": ids, "username": "ops", "password": "BMC_TEST_PASSWORD"}, "owner"
        )
        self.site.links[0]["address"] = ["198.51.100.100"]
        row = self.discovery.candidates()["candidates"][0]
        self.assertEqual(row["id"], ids[0])
        self.assertEqual(row["serial"], "NEW-01")
        self.assertFalse(row["authenticated"])

    def test_registration_cannot_use_another_session_proof(self):
        ids = [c["id"] for c in self.discovery.candidates()["candidates"]]
        self.discovery.authenticate(
            {"ids": ids, "username": "ops", "password": "BMC_TEST_PASSWORD"}, "owner"
        )
        with self.assertRaises(ValueError):
            self.discovery.enroll({"ids": ids, "confirm_registration": True}, "other", "test")
        self.assertEqual(self.site.writes, [])

    def test_old_enrollment_contract_cannot_start_power(self):
        with self.assertRaises(ValueError):
            self.discovery.enroll(
                {
                    "ids": ["old"],
                    "confirm_ingestion": True,
                    "boot_network_id": "old",
                    "boot_macs": {},
                    "retain_credentials": True,
                },
                "owner",
                "test",
            )
        self.assertEqual(self.site.writes, [])

    def test_hardware_preparation_requires_explicit_boot_selection(self):
        row = self.register()
        result = self.onboarding.admission_preview(
            {"serials": [row["chassis_serial_number"]]}, "owner"
        )
        self.assertFalse(result["passed"])
        self.assertIn("启动 MAC", result["checks"][0]["detail"])
        self.assertEqual(self.site.writes, [])

    def test_clear_pause_through_inventory_is_blocked(self):
        row = self.register()
        with self.assertRaises(ValueError):
            self.resources.edit(
                {
                    "id": row["id"],
                    "revision": digest(row),
                    "machine": {"default_pause_ingestion_and_poweron": False},
                },
                "owner",
            )
        self.assertEqual(self.site.writes, [])

    def test_fix_current_address_is_single_explicit_write_with_identity(self):
        row = self.register()
        check = self.addresses.preview({"serial": row["chassis_serial_number"]}, "owner")
        self.assertTrue(check["passed"])
        self.assertEqual(self.site.writes, [])
        result = self.addresses.apply(
            {"preflight_id": check["id"], "confirm_serial": row["chassis_serial_number"]},
            "owner",
            "test",
        )
        self.assertEqual(result["status"], "verified")
        self.assertEqual([m for m, _ in self.site.writes], ["AssignStaticAddress"])
        with self.assertRaises(ValueError):
            self.addresses.apply(
                {"preflight_id": check["id"], "confirm_serial": row["chassis_serial_number"]},
                "owner",
                "test",
            )

    def test_only_saving_target_does_not_change_current_or_allow_preparation(self):
        row = self.register()
        old = row["bmc_ip_address"]
        row["bmc_ip_address"] = "198.51.100.100"
        row["interfaces"][0]["fixed_ip"] = row["bmc_ip_address"]
        view = self.addresses.view(row)
        self.assertEqual(view["current_ip"], old)
        self.assertEqual(view["status"], "planned")
        with self.assertRaises(ValueError):
            self.onboarding.check_preparation(row)
        self.assertEqual(self.site.writes, [])

    def test_unprotected_old_address_blocks_migration_but_keeps_plan(self):
        row = self.register()
        row["bmc_ip_address"] = "198.51.100.100"
        check = self.addresses.preview({"serial": row["chassis_serial_number"]}, "owner")
        self.assertFalse(check["passed"])
        self.assertIn("旧 BMC 地址", check["detail"])
        self.assertEqual(self.site.writes, [])

    def migration(self):
        row = self.register()
        row["bmc_ip_address"] = "198.51.100.100"
        row["interfaces"][0]["fixed_ip"] = row["bmc_ip_address"]
        self.site.oob["config"]["prefixes"][0]["reserveFirst"] = 20
        check = self.addresses.preview({"serial": row["chassis_serial_number"]}, "owner")
        self.assertTrue(check["passed"])
        return row, {"preflight_id": check["id"], "confirm_serial": row["chassis_serial_number"]}

    def test_native_assignment_does_not_mean_bmc_client_has_switched(self):
        row, body = self.migration()
        original = self.site.redfish_read

        def read(ip, path, credential):
            if ip == row["bmc_ip_address"]:
                raise RuntimeError("BMC 尚未采用新地址")
            return original(ip, path, credential)

        self.site.redfish_read = read
        result = self.addresses.apply(body, "owner", "test")
        self.assertEqual(result["status"], "waiting_address")
        self.assertEqual(result["current_ip"], "198.51.100.10")
        with self.assertRaises(ValueError):
            self.onboarding.check_preparation(row)
        with self.assertRaises(ValueError):
            self.resources.check_address_operation(row)
        self.assertEqual([m for m, _ in self.site.writes], ["AssignStaticAddress"])
        self.site.original_rows[0]["bmc_ip_address"] = row["bmc_ip_address"]
        self.site.redfish_read = original
        verified = self.addresses.verify({"serial": row["chassis_serial_number"]}, "test")
        self.assertEqual(verified["status"], "verified")
        self.assertEqual(verified["current_ip"], row["bmc_ip_address"])
        self.assertEqual([m for m, _ in self.site.writes], ["AssignStaticAddress"])

    def test_assignment_timeout_is_persisted_and_never_replayed(self):
        row, body = self.migration()
        original = self.site.rpc

        def rpc(method, data):
            result = original(method, data)
            if method == "AssignStaticAddress":
                raise RuntimeError("INJECTED_TIMEOUT")
            return result

        self.site.rpc = rpc
        with self.assertRaises(RuntimeError):
            self.addresses.apply(body, "owner", "test")
        self.assertEqual(
            self.addresses.record(row["chassis_serial_number"])["status"], "needs_attention"
        )
        with self.assertRaises(ValueError):
            self.addresses.apply(body, "owner", "test")
        self.assertEqual([m for m, _ in self.site.writes], ["AssignStaticAddress"])

    def test_stale_network_or_wrong_session_never_assigns(self):
        row = self.register()
        check = self.addresses.preview({"serial": row["chassis_serial_number"]}, "owner")
        with self.assertRaises(ValueError):
            self.addresses.apply(
                {"preflight_id": check["id"], "confirm_serial": row["chassis_serial_number"]},
                "other",
                "test",
            )
        self.site.oob["config"]["mtu"] = 9000
        with self.assertRaises(ValueError):
            self.addresses.apply(
                {"preflight_id": check["id"], "confirm_serial": row["chassis_serial_number"]},
                "owner",
                "test",
            )
        self.assertEqual(self.site.writes, [])

    def test_target_conflict_and_cross_subnet_are_explained(self):
        row = self.register()
        for target in (self.site.rows[1]["bmc_ip_address"], "203.0.113.10", "198.51.100.1"):
            row["bmc_ip_address"] = target
            self.assertFalse(
                self.addresses.preview({"serial": row["chassis_serial_number"]}, "owner")["passed"]
            )
        self.assertEqual(self.site.writes, [])
