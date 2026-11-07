"""Workflow boundaries: scopes, native reconciliation and atomic planning."""

import copy
import json
import unittest
import uuid
from unittest.mock import patch

from tests.unit import test_first_install
from tests.unit import test_device_plans
from tests.unit import test_management
from pxeye.common import digest


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.f = test_first_install.FirstInstallTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.f.adapter.machines[0]["state"] = "HostInit/Discovering"

    def body(self, check, scope):
        return {
            "preflight_id": check["id"],
            "request_key": uuid.uuid4().hex,
            "confirm_serials": ["NEW-01"],
            "confirm_disk": True,
            "confirm_reboot": True,
            "cleanup_scope": scope,
        }

    def test_selected_disk_authorization_cannot_release_native_cleanup(self):
        f = self.f
        check = f.app.batch_preflight(f.batch_body(1), "owner")
        self.assertTrue(check["passed"])
        for scope in (None, "system_disk", "none"):
            with self.assertRaisesRegex(ValueError, "全部磁盘"):
                f.app.submit_batch(self.body(check, scope), "owner", "operator")
        self.assertEqual(f.adapter.writes, [])
        self.assertEqual(f.store.tasks(), [])

    def test_policy_change_invalidates_final_confirmation_before_writes(self):
        f = self.f
        check = f.app.batch_preflight(f.batch_body(1), "owner")
        f.adapter.config["site_explorer_settings"] = {"new_policy": True}
        with self.assertRaisesRegex(ValueError, "策略已变化"):
            f.app.submit_batch(self.body(check, "all_disks"), "owner", "operator")
        self.assertEqual(f.adapter.writes, [])
        self.assertEqual(f.store.tasks(), [])

    def test_standalone_admission_also_requires_explicit_all_disk_scope(self):
        f = self.f
        row = f.adapter.rows[0]
        with self.assertRaisesRegex(ValueError, "全部磁盘"):
            f.onboarding.admit(
                {
                    "serial": row["chassis_serial_number"],
                    "revision": digest(row),
                    "confirm_serial": row["chassis_serial_number"],
                    "confirm_ingestion": True,
                },
                "operator",
            )
        self.assertEqual(f.adapter.writes, [])

    def test_scout_guard_is_read_before_confirmation(self):
        f = self.f
        f.adapter.boot_overrides[f.adapter.links[0]["id"]["value"]] = {
            "customPxe": "kernel x systemd.mask=forge-scout.service"
        }
        check = f.app.batch_preflight(f.batch_body(1), "owner")
        self.assertFalse(check["passed"])
        self.assertEqual(f.adapter.writes, [])

    def test_missing_legacy_grant_stops_before_admission(self):
        f = self.f
        task = f.deferred_task(absent=True)
        task.pop("impact_authorization")
        f.adapter.writes.clear()
        with self.assertRaisesRegex(ValueError, "全部磁盘"):
            f.app.executor.bootstrap_first(task, f.adapter.data)
        self.assertEqual(f.adapter.writes, [])


class BulkPlanningTests(unittest.TestCase):
    def setUp(self):
        self.f = test_device_plans.DevicePlanTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)

    def request(self):
        return {"serials": [self.f.serial], "profile_id": "ubuntu-generic", "network_id": ""}

    def test_bulk_preview_and_save_preserve_overrides_and_do_not_write_native(self):
        f = self.f
        body = f.body()
        body["intent"].update(hostname="planned-host", username="specific")
        f.plans.save(body)
        original = f.plans.get(f.serial)
        preview = f.plans.bulk_preview(self.request(), "operator")
        self.assertNotIn("TEST_SECRET", json.dumps(preview))
        self.assertEqual(f.plans.get(f.serial), original)
        result = f.plans.bulk_apply({"preview_id": preview["preview_id"]}, "operator")
        self.assertTrue(result["exported"])
        self.assertEqual(f.site.writes, [])
        saved = f.plans.get(f.serial)
        self.assertEqual(saved["intent"]["username"], "specific")
        self.assertEqual(saved["intent"]["hostname"], "planned-host")
        self.assertEqual(saved["machine"], original["machine"])

    def test_bulk_keeps_private_login_reference_without_exposing_password(self):
        f = self.f
        body = f.body()
        body["intent"].update(
            username="specific", login_mode="password", password="TEST_PRIVATE_PASSWORD"
        )
        f.plans.save(body)
        before = f.plans.get(f.serial)["intent"]["login_ref"]
        preview = f.plans.bulk_preview(self.request(), "operator")
        self.assertNotIn(before, json.dumps(preview))
        self.assertNotIn("TEST_PRIVATE_PASSWORD", json.dumps(preview))
        f.plans.bulk_apply({"preview_id": preview["preview_id"]}, "operator")
        self.assertEqual(f.plans.get(f.serial)["intent"]["login_ref"], before)
        self.assertEqual(f.site.writes, [])

    def test_stale_preview_is_atomic_and_owner_bound(self):
        f = self.f
        preview = f.plans.bulk_preview(self.request(), "operator")
        with self.assertRaises(ValueError):
            f.plans.bulk_apply({"preview_id": preview["preview_id"]}, "different")
        f.plans.save(f.body())
        before = copy.deepcopy(f.plans.get(f.serial))
        with self.assertRaisesRegex(ValueError, "整批未保存"):
            f.plans.bulk_apply({"preview_id": preview["preview_id"]}, "operator")
        self.assertEqual(f.plans.get(f.serial), before)
        self.assertEqual(f.site.writes, [])

    def test_duplicate_hostname_is_rejected_across_inventory(self):
        f = self.f
        body = f.body()
        body["intent"]["hostname"] = "unique-host"
        f.plans.save(body)
        other = next(
            s for s in [r["chassis_serial_number"] for r in f.plans.inventory()] if s != f.serial
        )
        record = f.plans.get(other)
        with self.assertRaisesRegex(ValueError, "hostname"):
            f.plans.save(
                {
                    "id": record["machine"]["id"],
                    "revision": digest(record),
                    "machine": record["machine"],
                    "intent": {"hostname": "unique-host"},
                }
            )

    def test_bulk_network_updates_reference_without_reallocating_ip(self):
        f = self.f
        body = f.body()
        body["machine"]["interfaces"][1].update(
            primary=True,
            ip_allocation="fixed",
            fixed_ip="192.0.2.10",
            fixed_mask="255.255.255.0",
            fixed_gateway="192.0.2.1",
        )
        f.plans.save(body)
        old = copy.deepcopy(f.plans.get(f.serial))
        preview = f.plans.bulk_preview(
            self.request() | {"network_id": f.site.segment["id"]["value"]}, "operator"
        )
        f.plans.bulk_apply({"preview_id": preview["preview_id"]}, "operator")
        record = f.plans.get(f.serial)
        host = next(n for n in record["machine"]["interfaces"] if n.get("primary"))
        self.assertEqual(host["fixed_ip"], old["machine"]["interfaces"][1]["fixed_ip"])
        self.assertEqual(
            record["intent"]["network_bindings"][host["mac_address"]], f.site.segment["id"]["value"]
        )
        self.assertEqual(f.site.writes, [])


class NativeRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.f = test_management.ManagementTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)

    def test_readback_of_existing_record_does_not_repeat_create(self):
        f = self.f
        row = f.prepared()
        f.os.register({"id": row["id"], "revision": digest(row)})
        row = f.os.read(row["id"])
        row["status"] = "prepared"
        f.os.save(row)
        f.site.writes.clear()
        f.os.register({"id": row["id"], "revision": digest(row)})
        self.assertEqual(f.site.writes, [])
        self.assertFalse(f.site.native_os[row["id"]]["isActive"])

    def test_registration_unknown_result_reconciles_same_material_without_create(self):
        f = self.f
        row = f.prepared()
        original = f.site.rpc

        def timeout(method, body):
            result = original(method, body)
            if method == "CreateOperatingSystem":
                raise RuntimeError("response lost")
            return result

        with patch.object(f.site, "rpc", side_effect=timeout), self.assertRaises(RuntimeError):
            f.os.register({"id": row["id"], "revision": digest(row)})
        pending = f.os.read(row["id"])
        self.assertEqual(pending["pending_operation"], "register")
        f.site.writes.clear()
        recovered = f.os.recover({"id": row["id"], "revision": digest(pending)}, "owner")
        self.assertEqual(recovered["status"], "registered")
        self.assertEqual(f.site.writes, [])

    def test_mismatched_iso_boot_parameters_cannot_be_marked_registered(self):
        f = self.f
        row = f.prepared()
        f.os.register({"id": row["id"], "revision": digest(row)})
        f.site.native_os[row["id"]]["ipxeTemplateParameters"] = []
        row = f.os.read(row["id"])
        row.update(status="needs_attention", pending_operation="register")
        f.os.save(row)
        with self.assertRaisesRegex(ValueError, "不一致"):
            f.os.recover({"id": row["id"], "revision": digest(row)}, "owner")
