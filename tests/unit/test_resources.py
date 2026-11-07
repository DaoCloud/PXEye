"""Check resource writes, stale previews, credential handling and subnet migration boundaries."""

import copy
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from pxeye.services.resources import Resources, segment_revision, ImportReadbackError
from pxeye.common import digest
from pxeye.domain.machines import machine_rpc, public_machine, validate_machine, confirms_fields
from pxeye.persistence.store import Store

MACHINE = {
    "id": "11111111-1111-4111-8111-111111111111",
    "bmc_mac_address": "02:00:00:00:00:01",
    "bmc_username": "operator",
    "bmc_password": "TEST_SECRET_ONLY",
    "chassis_serial_number": "SERIAL-1",
    "metadata": {"name": "first", "description": "", "labels": []},
    "dpf_enabled": False,
    "default_pause_ingestion_and_poweron": True,
    "dpu_policy": "ignore",
    "interfaces": [
        {
            "mac_address": "02:00:00:00:01:01",
            "role": "host",
            "ip_allocation": "fixed",
            "fixed_ip": "192.0.2.10",
            "fixed_mask": "255.255.255.0",
            "primary": True,
        }
    ],
}


def csv_text(row):
    import csv

    s = io.StringIO()
    w = csv.DictWriter(s, fieldnames=list(row))
    w.writeheader()
    w.writerow(
        {k: json.dumps(v) if isinstance(v, (dict, list, bool)) else v for k, v in row.items()}
    )
    return s.getvalue()


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        self.adapter = Mock()
        self.adapter.data = self.data
        self.adapter.config = {"devices": []}
        self.store = Store(self.data / "db.sqlite")
        self.resources = Resources(self.adapter, self.store)
        self.rows = [copy.deepcopy(MACHINE)]
        self.resources.inventory = Mock(side_effect=lambda persist=False: copy.deepcopy(self.rows))
        self.adapter.rpc.return_value = {}
        self.adapter.device.side_effect = lambda serial: copy.deepcopy(
            next(d for d in self.adapter.config["devices"] if d["serial"] == serial)
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_preview_does_not_write_core_and_redacts_secret(self):
        r = self.resources.preview(csv_text(MACHINE), "owner")
        self.assertEqual(r["counts"]["update"], 1)
        self.assertNotIn("TEST_SECRET_ONLY", json.dumps(r))
        self.adapter.rpc.assert_not_called()
        p = self.data / "config/imports" / (r["preview_id"] + ".json")
        self.assertEqual(p.stat().st_mode & 0o777, 0o600)

    def test_preview_stale_or_other_session_cannot_apply(self):
        r = self.resources.preview(csv_text(MACHINE), "owner")
        with self.assertRaises(ValueError):
            self.resources.apply_import(r["preview_id"], "other")
        self.rows[0]["metadata"]["name"] = "concurrent-change"
        with self.assertRaises(ValueError):
            self.resources.apply_import(r["preview_id"], "owner")
        self.adapter.rpc.assert_not_called()

    def test_active_device_blocks_write_even_after_valid_preview(self):
        r = self.resources.preview(csv_text(MACHINE), "owner")
        with self.store.db() as db:
            db.execute(
                "INSERT INTO tasks VALUES (?,?,?,?,?,?)",
                (
                    "TASK",
                    "SERIAL-1",
                    "running",
                    json.dumps({"device": "SERIAL-1", "status": "running"}),
                    0,
                    "key",
                ),
            )
        with self.assertRaises(ValueError):
            self.resources.apply_import(r["preview_id"], "owner")
        self.adapter.rpc.assert_not_called()

    def test_patch_is_atomic_and_token_cannot_be_replayed(self):
        r = self.resources.preview(csv_text(MACHINE), "owner")
        self.resources.apply_import(r["preview_id"], "owner")
        args = self.adapter.rpc.call_args.args
        self.assertEqual(args[0], "PatchExpectedMachines")
        self.assertIn("host_nics", args[1]["patches"][0]["update_mask"]["paths"])
        with self.assertRaises(ValueError):
            self.resources.apply_import(r["preview_id"], "owner")
        self.assertEqual(self.adapter.rpc.call_count, 1)

    def test_unknown_write_outcome_is_not_replayed(self):
        r = self.resources.preview(csv_text(MACHINE), "owner")
        self.adapter.rpc.side_effect = RuntimeError("timeout")
        with self.assertRaises(RuntimeError):
            self.resources.apply_import(r["preview_id"], "owner")
        self.adapter.rpc.side_effect = None
        with self.assertRaises(ValueError):
            self.resources.apply_import(r["preview_id"], "owner")
        self.assertEqual(self.adapter.rpc.call_count, 1)

    def test_edit_preserves_password_when_ui_sends_blank(self):
        with unittest.mock.patch.object(self.resources, "apply_import", return_value={}) as apply:
            self.resources.edit(
                {
                    "id": MACHINE["id"],
                    "revision": digest(MACHINE),
                    "machine": {
                        "bmc_password": "",
                        "metadata": {"name": "edited", "description": "", "labels": []},
                    },
                },
                "owner",
            )
            token = apply.call_args.args[0]
            p = json.loads((self.data / "config/imports" / (token + ".json")).read_text())
            self.assertEqual(p["plans"][0]["incoming"]["bmc_password"], "TEST_SECRET_ONLY")

    def test_new_node_is_paused_and_duplicate_serial_is_rejected(self):
        row = copy.deepcopy(MACHINE)
        row.pop("id")
        row["bmc_mac_address"] = "02:00:00:00:00:02"
        with self.assertRaises(ValueError):
            self.resources.preview(csv_text(row), "owner")
        row["chassis_serial_number"] = "SERIAL-2"
        row.pop("default_pause_ingestion_and_poweron")
        r = self.resources.preview(csv_text(row), "owner")
        self.assertTrue(r["rows"][0]["default_pause_ingestion_and_poweron"])

    def test_invalid_interfaces_are_rejected_without_sensitive_errors(self):
        for change in [
            {"role": "unknown"},
            {"fixed_ip": "invalid"},
            {"mac_address": "bad"},
            {"primary": "true"},
        ]:
            m = copy.deepcopy(MACHINE)
            m["interfaces"][0].update(change)
            with self.assertRaises(ValueError) as caught:
                validate_machine(m)
            self.assertNotIn("TEST_SECRET_ONLY", str(caught.exception))

    def test_interface_enum_mapping_preserves_false_and_empty(self):
        r = machine_rpc(MACHINE)
        self.assertEqual(r["host_nics"][0]["role"], 1)
        self.assertEqual(r["host_nics"][0]["ip_allocation"], 2)
        self.assertFalse(r["is_dpf_enabled"])
        self.assertEqual(r["dpu_mode"], 3)

    def test_subnet_save_checks_cidr_gateway_and_persists_draft(self):
        c = {
            "name": "mmzhou-test",
            "segment_type": "HOST_INBAND",
            "prefix": "192.0.2.0/24",
            "gateway": "192.0.2.1",
            "mtu": 1500,
            "reserve_first": 5,
            "subdomain_id": MACHINE["id"],
        }
        for prefix, gateway in [("192.0.2.5/24", "192.0.2.1"), ("192.0.2.0/24", "192.0.3.1")]:
            with self.assertRaises(ValueError):
                self.resources.save_network(
                    {
                        "id": None,
                        "revision": None,
                        "config": c | {"prefix": prefix, "gateway": gateway},
                    }
                )
        r = self.resources.save_network({"id": None, "revision": None, "config": c})
        self.assertEqual(r["status"], "saved")
        self.assertTrue((self.data / "config/network-segments.json").exists())
        self.adapter.rpc.assert_not_called()

    def test_occupied_subnet_change_is_saved_as_migration_without_core_write(self):
        n = {
            "id": MACHINE["id"],
            "revision": "rev",
            "name": "mmzhou-test",
            "segment_type": "HOST_INBAND",
            "prefixes": [{"prefix": "192.0.2.0/24", "gateway": "192.0.2.1", "reserveFirst": 5}],
            "mtu": 1500,
            "subdomain_id": MACHINE["id"],
            "interface_count": 1,
            "managed_by_console": True,
        }
        self.resources.networks = Mock(return_value=[n])
        c = {
            "name": n["name"],
            "segment_type": n["segment_type"],
            "prefix": "192.0.3.0/24",
            "gateway": "192.0.3.1",
            "mtu": 1500,
            "reserve_first": 5,
            "subdomain_id": MACHINE["id"],
        }
        self.resources.save_network({"id": n["id"], "revision": "rev", "config": c})
        with self.assertRaises(ValueError):
            self.resources.apply_network(n["id"])
        self.adapter.rpc.assert_not_called()
        p = self.data / "config/networks" / (n["id"] + ".json")
        self.assertEqual(json.loads(p.read_text())["status"], "migration_required")

    def plan_fixture(self):
        self.adapter.config = {
            "devices": [
                {
                    "serial": "SERIAL-1",
                    "management_ip": "192.0.2.20",
                    "boot_mac": "02:00:00:00:01:01",
                    "machine_id": "machine-1",
                    "bmc_ip": "198.51.100.10",
                    "instance_id": "instance-1",
                    "dns": "192.0.2.53",
                }
            ]
        }
        self.rows[0]["interfaces"][0]["fixed_gateway"] = "192.0.2.1"
        self.segments = [
            {
                "id": "segment-1",
                "segment_type": "HOST_INBAND",
                "state": "READY",
                "prefixes": [{"prefix": "192.0.2.0/24", "gateway": "192.0.2.1", "reserveFirst": 5}],
                "revision": "network-1",
            }
        ]
        self.links = [
            {
                "id": {"value": "interface-1"},
                "macAddress": "02:00:00:00:01:01",
                "machineId": {"id": "machine-1"},
                "segmentId": {"value": "segment-1"},
                "primaryInterface": True,
                "address": ["192.0.2.20"],
            },
            {
                "id": {"value": "bmc-1"},
                "isBmc": True,
                "machineId": {"id": "machine-1"},
                "macAddress": MACHINE["bmc_mac_address"],
            },
        ]
        self.resources.networks = Mock(side_effect=lambda: copy.deepcopy(self.segments))
        self.adapter.rpc.side_effect = lambda *a, **k: {"interfaces": copy.deepcopy(self.links)}

    def test_new_plan_uses_old_connection_and_allows_reinstall(self):
        self.plan_fixture()
        row = self.resources.devices()[0]
        self.assertTrue(row["executable"])
        self.assertEqual(row["current_management_ip"], "192.0.2.20")
        self.assertEqual(row["management_ip"], "192.0.2.10")
        self.assertEqual(self.links[0]["address"], ["192.0.2.20"])

    def test_invalid_network_mac_bmc_and_address_conflict_still_block(self):
        self.plan_fixture()
        baseline = copy.deepcopy(self.rows)
        for key, value in [
            ("fixed_ip", "192.0.3.10"),
            ("fixed_ip", "192.0.2.1"),
            ("fixed_mask", "255.0.0.0"),
            ("mac_address", "02:00:00:00:01:99"),
            ("ip_allocation", "dynamic"),
            ("fixed_gateway", None),
        ]:
            self.rows = copy.deepcopy(baseline)
            self.rows[0]["interfaces"][0][key] = value
            self.assertFalse(self.resources.devices()[0]["executable"], (key, value))
        self.rows = copy.deepcopy(baseline)
        self.rows[0]["bmc_ip_address"] = "198.51.100.99"
        self.assertFalse(self.resources.devices()[0]["executable"])
        self.rows = copy.deepcopy(baseline)
        self.links.append({"id": {"value": "other"}, "address": ["192.0.2.10"]})
        self.assertFalse(self.resources.devices()[0]["executable"])

    def test_plan_revision_changes_when_inventory_network_or_binding_changes(self):
        self.plan_fixture()
        old = self.resources.execution_plan("SERIAL-1")
        self.rows[0]["metadata"]["name"] = "changed"
        self.assertNotEqual(old, self.resources.execution_plan("SERIAL-1"))
        self.segments[0]["revision"] = "network-2"
        self.assertNotEqual(
            old["segment_revision"], self.resources.execution_plan("SERIAL-1")["segment_revision"]
        )
        self.links[0]["address"] = ["192.0.2.30"]
        self.assertNotEqual(
            old["binding_revision"], self.resources.execution_plan("SERIAL-1")["binding_revision"]
        )

    def test_readback_rejects_dropped_address_but_allows_default_host_role(self):
        actual = copy.deepcopy(MACHINE)
        actual["interfaces"][0].pop("role")
        self.assertTrue(confirms_fields(actual, MACHINE))
        actual["interfaces"][0]["fixed_ip"] = "192.0.2.99"
        self.assertFalse(confirms_fields(actual, MACHINE))

    def test_core_omitted_false_retention_is_equivalent_but_true_is_not(self):
        self.assertTrue(
            confirms_fields({"bmc_retain_credentials": None}, {"bmc_retain_credentials": False})
        )
        self.assertFalse(
            confirms_fields({"bmc_retain_credentials": None}, {"bmc_retain_credentials": True})
        )
        self.assertFalse(confirms_fields({"dpf_enabled": None}, {"dpf_enabled": False}))

    def test_failed_import_can_be_verified_without_repeating_write(self):
        preview = self.resources.preview(csv_text(MACHINE), "owner")

        def committed_with_wrong_address(*args):
            self.rows[0]["interfaces"][0]["fixed_ip"] = "192.0.2.99"
            return {}

        self.adapter.rpc.side_effect = committed_with_wrong_address
        with self.assertRaises(ImportReadbackError) as caught:
            self.resources.apply_import(preview["preview_id"], "owner")
        self.assertNotIn("TEST_SECRET_ONLY", str(caught.exception))
        path = self.data / "config/imports" / (preview["preview_id"] + ".json")
        self.assertEqual(json.loads(path.read_text())["status"], "needs_attention")
        self.rows[0] = copy.deepcopy(MACHINE)
        calls = self.adapter.rpc.call_count
        result = self.resources.verify_import(preview["preview_id"])
        self.assertEqual(result["status"], "applied")
        self.assertEqual(self.adapter.rpc.call_count, calls)
        self.assertEqual(json.loads(path.read_text())["recovered_from"], "needs_attention")
        with self.assertRaises(ValueError):
            self.resources.apply_import(preview["preview_id"], "owner")

    def test_verification_cannot_accept_wrong_ip_or_credentials(self):
        preview = self.resources.preview(csv_text(MACHINE), "owner")
        self.resources.apply_import(preview["preview_id"], "owner")
        for key, value in [
            ("bmc_password", "WRONG_SECRET"),
            ("bmc_mac_address", "02:00:00:00:00:02"),
        ]:
            self.rows[0] = copy.deepcopy(MACHINE)
            self.rows[0][key] = value
            with self.assertRaises(ImportReadbackError) as caught:
                self.resources.verify_import(preview["preview_id"])
            self.assertNotIn(value, str(caught.exception))

    def test_runtime_ip_counts_do_not_invalidate_network_form_revision(self):
        n = {
            "id": {"value": MACHINE["id"]},
            "config": {"prefixes": [{"prefix": "192.0.2.0/24", "freeIpCount": 200}]},
        }
        other = copy.deepcopy(n)
        other["config"]["prefixes"][0]["freeIpCount"] = 198
        self.assertEqual(segment_revision(n), segment_revision(other))
        other["config"]["prefixes"][0]["prefix"] = "192.0.3.0/24"
        self.assertNotEqual(segment_revision(n), segment_revision(other))

    def test_replacement_waits_for_physical_deletion_and_creates_once(self):
        n = {
            "id": MACHINE["id"],
            "revision": "rev",
            "name": "mmzhou-test",
            "segment_type": "HOST_INBAND",
            "prefixes": [{"prefix": "192.0.2.0/24", "gateway": "192.0.2.1", "reserveFirst": 5}],
            "mtu": 1500,
            "subdomain_id": MACHINE["id"],
            "interface_count": 0,
            "managed_by_console": True,
        }
        self.resources.networks = Mock(return_value=[n])
        c = {
            "name": n["name"],
            "segment_type": n["segment_type"],
            "prefix": "192.0.3.0/24",
            "gateway": "192.0.3.1",
            "mtu": 1500,
            "reserve_first": 5,
            "subdomain_id": MACHINE["id"],
        }
        self.resources.save_network({"id": n["id"], "revision": "rev", "config": c})
        result = self.resources.apply_network(n["id"])
        self.assertEqual(result["status"], "waiting_deletion")
        self.adapter.rpc.assert_called_once_with("DeleteNetworkSegment", {"id": {"value": n["id"]}})
        self.adapter.rpc.reset_mock()
        self.adapter.rpc.side_effect = [
            {"networkSegments": [{"deleted": "timestamp"}]},
            {"networkSegments": []},
        ]
        with (
            unittest.mock.patch("pxeye.services.resources.time.sleep"),
            unittest.mock.patch.object(self.resources, "create_network", return_value={}) as create,
        ):
            self.resources.finish_network_replacement(n["id"])
            create.assert_called_once()
        self.assertEqual(self.adapter.rpc.call_count, 2)

    def test_replacement_timeout_preserves_state_without_create_or_delete_replay(self):
        p = self.data / "config/networks" / (MACHINE["id"] + ".json")
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"id": MACHINE["id"], "status": "waiting_deletion", "deadline": 0}))
        with self.assertRaises(RuntimeError):
            self.resources.finish_network_replacement(MACHINE["id"])
        self.assertEqual(json.loads(p.read_text())["status"], "needs_attention")
        with self.assertRaises(ValueError):
            self.resources.finish_network_replacement(MACHINE["id"])
        self.adapter.rpc.assert_not_called()

    def test_restart_marks_resource_operation_attention_without_replaying(self):
        p = self.data / "config/networks" / (MACHINE["id"] + ".json")
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"id": MACHINE["id"], "status": "waiting_deletion"}))
        self.resources.recover_network_operations()
        self.assertEqual(json.loads(p.read_text())["status"], "needs_attention")
        self.adapter.rpc.assert_not_called()

    def deletion_network(self, **changes):
        row = {
            "id": MACHINE["id"],
            "revision": "rev",
            "name": "mmzhou-unused",
            "segment_type": "UNDERLAY",
            "prefixes": [{"prefix": "198.18.72.0/28"}],
            "interface_count": 0,
            "managed_by_console": True,
            "saved": {"status": "applied", "created_by_console": True},
        }
        row.update(changes)
        self.resources.networks = Mock(return_value=[row])
        return row

    def deletion_body(self, **changes):
        return {"id": MACHINE["id"], "revision": "rev", "confirm_delete": True} | changes

    def test_delete_unused_network_once_and_archive_until_physical_removal(self):
        self.deletion_network()
        p = self.data / "config/networks" / (MACHINE["id"] + ".json")
        p.parent.mkdir(parents=True)
        p.write_text(
            json.dumps(
                {"id": MACHINE["id"], "config": {"name": "mmzhou-unused"}, "status": "applied"}
            )
        )
        result = self.resources.delete_network(self.deletion_body())
        self.assertEqual(result["status"], "deleting")
        self.adapter.rpc.assert_called_once_with(
            "DeleteNetworkSegment", {"id": {"value": MACHINE["id"]}}
        )
        with self.assertRaises(ValueError):
            self.resources.delete_network(self.deletion_body())
        self.adapter.rpc.return_value = {"networkSegments": [{"deleted": "timestamp"}]}
        self.assertEqual(
            self.resources.verify_network_deletion(MACHINE["id"])["status"], "deleting"
        )
        self.adapter.rpc.return_value = {"networkSegments": []}
        self.assertEqual(self.resources.verify_network_deletion(MACHINE["id"])["status"], "deleted")
        self.assertEqual(json.loads(p.read_text())["status"], "deleted")
        self.assertEqual(
            json.loads((self.data / "config/network-segments.json").read_text())[
                "network_segments"
            ],
            [],
        )
        archive = self.data / "config/network-deletions" / (MACHINE["id"] + ".json")
        self.assertEqual(archive.stat().st_mode & 0o777, 0o600)

    def test_delete_rejects_system_site_tenant_occupied_or_pending_network(self):
        for changes in [
            {"name": "static-assignments"},
            {"managed_by_console": False},
            {"segment_type": "TENANT"},
            {"vpc_id": "vpc"},
            {"interface_count": 1},
            {"saved": {"status": "waiting_deletion"}},
            {"saved": {"status": "needs_attention"}},
        ]:
            self.deletion_network(**changes)
            with self.assertRaises(ValueError):
                self.resources.delete_network(self.deletion_body())
        self.adapter.rpc.assert_not_called()

    def test_delete_requires_confirmation_and_current_revision(self):
        self.deletion_network()
        for changes in [{"confirm_delete": False}, {"revision": "old"}, {"id": "../escape"}]:
            with self.assertRaises(ValueError):
                self.resources.delete_network(self.deletion_body(**changes))
        self.adapter.rpc.assert_not_called()

    def test_delete_rejects_saved_plan_binding_and_unsent_addresses(self):
        self.deletion_network(prefixes=[{"prefix": "192.0.2.0/24"}])
        with self.assertRaises(ValueError):
            self.resources.delete_network(self.deletion_body())
        self.deletion_network()
        with unittest.mock.patch(
            "pxeye.services.device_config.DeviceConfig.get",
            return_value={"network_bindings": {"mac": MACHINE["id"]}},
        ):
            with self.assertRaises(ValueError):
                self.resources.delete_network(self.deletion_body())
        self.adapter.rpc.assert_not_called()

    def test_delete_unknown_result_survives_restart_without_replay(self):
        self.deletion_network()
        self.adapter.rpc.side_effect = RuntimeError("timeout")
        with self.assertRaises(RuntimeError):
            self.resources.delete_network(self.deletion_body())
        self.resources.recover_network_operations()
        with self.assertRaises(ValueError):
            self.resources.delete_network(self.deletion_body())
        self.assertEqual(self.adapter.rpc.call_count, 1)
        self.adapter.rpc.side_effect = None
        self.adapter.rpc.return_value = {"networkSegments": []}
        self.assertEqual(self.resources.verify_network_deletion(MACHINE["id"])["status"], "deleted")
        self.assertTrue(
            all(
                c.args[0] == "FindNetworkSegmentsByIds" for c in self.adapter.rpc.call_args_list[1:]
            )
        )

    def test_delete_pending_cannot_edit_or_apply_and_timeout_only_reads(self):
        self.deletion_network()
        self.resources.delete_network(self.deletion_body())
        p = self.data / "config/network-deletions" / (MACHINE["id"] + ".json")
        record = json.loads(p.read_text())
        record["deadline"] = 0
        p.write_text(json.dumps(record))
        self.adapter.rpc.return_value = {"networkSegments": [{"deleted": "timestamp"}]}
        self.assertEqual(
            self.resources.verify_network_deletion(MACHINE["id"])["status"], "delete_unknown"
        )
        with self.assertRaises(ValueError):
            self.resources.apply_network(MACHINE["id"])
        config = {
            "name": "mmzhou-unused",
            "segment_type": "UNDERLAY",
            "prefix": "198.18.72.0/28",
            "mtu": 1500,
            "reserve_first": 2,
        }
        with self.assertRaises(ValueError):
            self.resources.save_network({"id": MACHINE["id"], "revision": "rev", "config": config})
        self.assertEqual(
            sum(c.args[0] == "DeleteNetworkSegment" for c in self.adapter.rpc.call_args_list), 1
        )

    def test_delete_draft_is_local_and_cannot_reappear_or_apply(self):
        self.resources.networks = Mock(return_value=[])
        config = {
            "name": "mmzhou-draft",
            "segment_type": "UNDERLAY",
            "prefix": "198.18.72.0/28",
            "mtu": 1500,
            "reserve_first": 2,
        }
        saved = self.resources.save_network({"id": None, "revision": None, "config": config})
        draft = self.resources.network_list()["drafts"][0]
        self.resources.delete_network(
            {"id": saved["id"], "revision": draft["delete_revision"], "confirm_delete": True}
        )
        self.assertEqual(self.resources.network_list()["drafts"], [])
        with self.assertRaises(ValueError):
            self.resources.apply_network(saved["id"])
        self.adapter.rpc.assert_not_called()

    def test_delete_draft_rejects_changed_or_unknown_execution_state(self):
        self.resources.networks = Mock(return_value=[])
        config = {
            "name": "mmzhou-draft",
            "segment_type": "UNDERLAY",
            "prefix": "198.18.72.0/28",
            "mtu": 1500,
            "reserve_first": 2,
        }
        saved = self.resources.save_network({"id": None, "revision": None, "config": config})
        draft = self.resources.network_list()["drafts"][0]
        with self.assertRaises(ValueError):
            self.resources.delete_network(
                {"id": saved["id"], "revision": "old", "confirm_delete": True}
            )
        p = self.data / "config/networks" / (saved["id"] + ".json")
        record = json.loads(p.read_text())
        record["replacement_id"] = saved["id"]
        p.write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            self.resources.delete_network(
                {"id": saved["id"], "revision": digest(record), "confirm_delete": True}
            )
        self.adapter.rpc.assert_not_called()


class InterfaceDefaultTests(unittest.TestCase):
    def test_core_omitted_fixed_policy_requires_matching_fixed_address(self):
        expected = {"role": "host_bmc", "ip_allocation": "fixed", "fixed_ip": "192.0.2.10"}
        actual = {"role": "host_bmc", "fixed_ip": "192.0.2.10"}
        self.assertTrue(confirms_fields(actual, expected))
        self.assertTrue(confirms_fields(actual | {"ip_allocation": None}, expected))
        self.assertFalse(confirms_fields(actual | {"fixed_ip": "192.0.2.99"}, expected))
        self.assertFalse(confirms_fields({"role": "host_bmc"}, expected))
        self.assertFalse(confirms_fields(actual | {"ip_allocation": "dynamic"}, expected))

    def test_inferred_policies_do_not_accept_non_default_retention(self):
        self.assertTrue(
            confirms_fields({"role": "host_bmc"}, {"role": "host_bmc", "ip_allocation": "retained"})
        )
        self.assertTrue(
            confirms_fields({"role": "host"}, {"role": "host", "ip_allocation": "dynamic"})
        )
        self.assertFalse(
            confirms_fields({"role": "host"}, {"role": "host", "ip_allocation": "retained"})
        )

    def test_core_non_primary_null_is_false_but_not_true(self):
        self.assertTrue(confirms_fields({"primary": None}, {"primary": False}))
        self.assertFalse(confirms_fields({"primary": None}, {"primary": True}))
        self.assertFalse(confirms_fields({"primary": True}, {"primary": False}))


if __name__ == "__main__":
    unittest.main()
