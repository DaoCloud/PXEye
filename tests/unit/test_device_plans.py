"""Planning persistence, offline safety and explicit execution boundaries."""

import copy
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pxeye.services.device_config import DeviceConfig
from pxeye.services.device_plans import DevicePlans, frozen_plan, bmc_choice
from pxeye.services.resources import Resources
from pxeye.common import digest
from pxeye.persistence.store import Store
from tests.unit.test_management import ManagementSite
from tests.unit import test_device_planning


class DevicePlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.site = ManagementSite(Path(self.tmp.name), number=2)
        self.store = Store(self.site.data / "console.sqlite3")
        self.resources = Resources(self.site, self.store)
        # Reuse the existing arrival fixture, but test a separate planning service.
        fixture = test_device_planning.PlanningTests()
        fixture.site, fixture.store, fixture.resources = self.site, self.store, self.resources
        from pxeye.services.discovery import Discovery
        from pxeye.services.onboarding import Onboarding

        fixture.discovery = Discovery(
            self.site, self.resources, Onboarding(self.site, self.store, self.resources)
        )
        fixture.register()
        self.plans = DevicePlans(self.site, self.resources)
        self.resources.devices()
        self.serial = self.site.rows[0]["chassis_serial_number"]
        self.site.writes.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def body(self):
        record = self.plans.get(self.serial)
        return {
            "id": record["machine"]["id"],
            "revision": digest(record),
            "machine": copy.deepcopy(record["machine"]),
            "intent": {
                "hostname": "",
                "profile_id": "",
                "os_id": "",
                "username": "",
                "login_mode": "password",
                "network_bindings": {},
            },
        }

    def test_save_bmc_change_and_partial_os_without_native_io(self):
        body = self.body()
        body["machine"]["bmc_ip_address"] = "198.51.100.100"
        body["machine"]["interfaces"][0]["fixed_ip"] = "198.51.100.100"
        body["intent"].update(hostname="next-install", os_id="not-ready-yet")
        original = copy.deepcopy(self.site.rows)
        self.site.core = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline"))
        self.site.rpc = self.site.core
        result = self.plans.save(body)
        self.assertEqual(result["status"], "saved")
        self.assertEqual(self.site.rows, original)
        self.assertEqual(self.site.writes, [])
        restarted = DevicePlans(
            self.site, Resources(self.site, Store(self.site.data / "console.sqlite3"))
        )
        self.assertEqual(restarted.get(self.serial)["intent"]["hostname"], "next-install")
        self.assertEqual(restarted.get(self.serial)["machine"]["bmc_ip_address"], "198.51.100.100")
        self.assertTrue(self.plans.public(self.serial)["planning_missing"])

    def test_offline_device_list_keeps_saved_plan(self):
        self.plans.save(self.body())
        self.site.core = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline"))
        self.site.rpc = self.site.core
        rows = self.resources.devices()
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0]["plan_saved"])
        self.assertFalse(rows[0]["first_install_ready"])

    def test_save_allowed_during_unknown_address_result_and_task(self):
        from pxeye.services.bmc_addresses import BMCAddresses

        BMCAddresses(self.site, self.resources).save(self.serial, {"status": "needs_attention"})
        self.store.active = lambda serial: {"status": "running"}
        self.plans.save(self.body())
        self.assertEqual(self.site.writes, [])

    def test_stale_revision_does_not_overwrite(self):
        body = self.body()
        self.plans.save(body)
        with self.assertRaisesRegex(ValueError, "规划已被修改"):
            self.plans.save(body)

    def test_conflicting_other_device_ip_is_rejected(self):
        body = self.body()
        body["machine"]["bmc_ip_address"] = self.site.rows[1]["bmc_ip_address"]
        body["machine"]["interfaces"][0]["fixed_ip"] = body["machine"]["bmc_ip_address"]
        with self.assertRaisesRegex(ValueError, "规划 IP"):
            self.plans.save(body)

    def test_fixed_missing_ip_is_draft_not_execution_ready(self):
        body = self.body()
        host = body["machine"]["interfaces"][1]
        host.update(ip_allocation="fixed", primary=True)
        host.pop("fixed_ip", None)
        self.plans.save(body)
        self.assertEqual(self.site.writes, [])
        with self.assertRaisesRegex(ValueError, "fixed_ip"):
            self.plans.synchronize(self.serial)

    def test_secret_preserved_hidden_and_reference_bound_to_version(self):
        body = self.body()
        body["machine"]["bmc_password"] = ""
        body["intent"].update(username="ops", password="PRIVATE_OS_SECRET")
        self.plans.save(body)
        record = self.plans.get(self.serial)
        self.assertEqual(record["machine"]["bmc_password"], "BMC_TEST_PASSWORD")
        public = self.resources.devices()
        self.assertNotIn("PRIVATE_OS_SECRET", json.dumps(public))
        self.assertNotIn("BMC_TEST_PASSWORD", json.dumps(public))
        self.assertNotIn("login_ref", public[0]["intent"])
        self.assertEqual((self.site.data / "console.sqlite3").stat().st_mode & 0o777, 0o600)

    def test_file_export_failure_keeps_database_commit(self):
        body = self.body()
        with patch("pxeye.services.device_plans.atomic_json", side_effect=OSError("full")):
            result = self.plans.save(body)
        self.assertFalse(result["exported"])
        self.assertEqual(self.plans.get(self.serial)["source"], "ui")
        self.assertTrue(self.plans.export())

    def test_frozen_task_reads_old_plan_and_intent(self):
        body = self.body()
        body["intent"]["hostname"] = "old-host"
        result = self.plans.save(body)
        task = {
            "device": self.serial,
            "installation_plan": {"device_plan_revision": result["revision"]},
        }
        body = self.body()
        body["intent"]["hostname"] = "next-host"
        self.plans.save(body)
        plans = self.plans

        class Worker:
            @frozen_plan
            def run(self, task):
                return plans.get(task["device"])["intent"]["hostname"]

        self.assertEqual(Worker().run(task), "old-host")
        self.assertEqual(self.plans.get(self.serial)["intent"]["hostname"], "next-host")

    def test_csv_preview_and_import_preserve_intent_and_do_not_write_core(self):
        body = self.body()
        body["intent"].update(hostname="csv-host", username="ops", password="PRIVATE_OS_SECRET")
        self.plans.save(body)
        machine = self.body()["machine"]
        machine["metadata"] = {"name": "from-csv"}
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=list(machine))
        writer.writeheader()
        writer.writerow(
            {
                k: json.dumps(v) if isinstance(v, (dict, list, bool)) else v
                for k, v in machine.items()
            }
        )
        result = self.plans.preview_csv(output.getvalue(), "owner")
        self.plans.import_csv(result["preview_id"], "owner")
        self.assertEqual(self.plans.get(self.serial)["intent"]["hostname"], "csv-host")
        self.assertTrue(self.plans.get(self.serial)["intent"].get("login_ref"))
        self.assertEqual(self.plans.get(self.serial)["machine"]["metadata"]["name"], "from-csv")
        self.assertEqual(self.site.writes, [])
        with self.assertRaises(ValueError):
            self.plans.import_csv(result["preview_id"], "owner")

    def test_bmc_sync_only_updates_bmc_fields_and_preserves_host_plan(self):
        body = self.body()
        body["machine"]["bmc_username"] = "newops"
        body["machine"]["interfaces"][1].update(primary=True, ip_allocation="fixed")
        self.plans.save(body)
        original_rpc = self.site.rpc

        def rpc(method, body):
            if method != "PatchExpectedMachines":
                return original_rpc(method, body)
            from pxeye.domain.machines import machine_from_rpc

            self.site.writes.append((method, copy.deepcopy(body)))
            changed = machine_from_rpc(body["patches"][0]["expected_machine"])
            changed.pop("dpf_enabled", None)
            self.site.rows[0].update(changed)
            return {}

        self.site.rpc = rpc
        hosts_before = copy.deepcopy(
            [n for n in self.site.rows[0]["interfaces"] if n["role"] != "host_bmc"]
        )
        self.plans.synchronize(self.serial, "bmc")
        self.assertEqual([m for m, _ in self.site.writes], ["PatchExpectedMachines"])
        native = self.site.writes[0][1]["patches"][0]
        self.assertEqual(
            set(native["update_mask"]["paths"]),
            {"bmc_ip_address", "bmc_ip_allocation", "bmc_username", "bmc_password", "host_nics"},
        )
        self.assertEqual(
            [n for n in self.site.rows[0]["interfaces"] if n["role"] != "host_bmc"], hosts_before
        )

    def test_current_bmc_choice_keeps_planned_target_and_validates_identity(self):
        body = self.body()
        body["machine"]["bmc_ip_address"] = "198.51.100.100"
        body["machine"]["interfaces"][0]["fixed_ip"] = "198.51.100.100"
        self.plans.save(body)
        from pxeye.services.onboarding import Onboarding

        onboarding = Onboarding(self.site, self.store, self.resources)
        row = self.plans.get(self.serial)["machine"]
        with self.assertRaises(ValueError):
            onboarding.probe(row)
        with bmc_choice(self.serial, "use_current"):
            device, _ = onboarding.probe(row)
        self.assertEqual(device["bmc_ip"], "198.51.100.10")
        self.assertEqual(self.plans.get(self.serial)["machine"]["bmc_ip_address"], "198.51.100.100")
        self.assertEqual(self.site.writes, [])

    def test_current_bmc_choice_cannot_bypass_unknown_operation(self):
        from pxeye.services.bmc_addresses import BMCAddresses
        from pxeye.services.onboarding import Onboarding

        BMCAddresses(self.site, self.resources).save(self.serial, {"status": "needs_attention"})
        with bmc_choice(self.serial, "use_current"):
            with self.assertRaises(ValueError):
                Onboarding(self.site, self.store, self.resources).probe(
                    self.plans.get(self.serial)["machine"]
                )

    def test_invalid_field_keeps_old_plan(self):
        body = self.body()
        body["intent"]["hostname"] = "BAD HOST"
        before = self.plans.get(self.serial)
        with self.assertRaises(ValueError):
            self.plans.save(body)
        self.assertEqual(before, self.plans.get(self.serial))

    def test_identity_and_pause_cannot_be_changed(self):
        body = self.body()
        body["machine"]["bmc_mac_address"] = "aa:aa:aa:aa:aa:aa"
        with self.assertRaises(ValueError):
            self.plans.save(body)
        body = self.body()
        body["machine"]["default_pause_ingestion_and_poweron"] = False
        with self.assertRaises(ValueError):
            self.plans.save(body)

    def test_hardware_sources_preserved(self):
        self.assertEqual(
            self.plans.public(self.serial)["inventory_sources"][
                self.site.rows[0]["interfaces"][1]["mac_address"].lower()
            ]["source"],
            "bmc",
        )

    def test_unknown_sync_not_replayed(self):
        body = self.body()
        body["machine"]["bmc_username"] = "newops"
        self.plans.save(body)
        self.site.rpc = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("timeout"))
        with self.assertRaises(RuntimeError):
            self.plans.synchronize(self.serial, "bmc")
        with self.assertRaisesRegex(ValueError, "不自动重放"):
            self.plans.synchronize(self.serial, "bmc")


if __name__ == "__main__":
    unittest.main()
