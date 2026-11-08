"""Real transport input and recovery boundaries for pre-install planning failures."""

import copy
import json
import subprocess
import threading
import time
import unittest
from unittest.mock import patch

from tests.unit import test_device_plans
from pxeye.services.execution import Adapter
from pxeye.clients.errors import RPCRequestError
from pxeye.clients.process import run
from pxeye.services.device_plans import DevicePlans
from pxeye.installation.executor import Executor
from pxeye.common import atomic_json, digest
from pxeye.domain.machines import machine_rpc
from pxeye.bootstrap import Application


class WireTests(unittest.TestCase):
    def test_native_readback_nulls_are_omitted_but_explicit_values_survive(self):
        row = {
            "id": "id",
            "dpf_enabled": False,
            "host_lifecycle_profile": {"disable_lockdown": False},
            "interfaces": [
                {
                    "mac_address": "02:00:00:00:00:01",
                    "nic_type": None,
                    "fixed_ip": None,
                    "fixed_mask": None,
                    "fixed_gateway": None,
                    "primary": False,
                    "role": "host_bmc",
                    "ip_allocation": "unspecified",
                    "physical_ifname": "",
                }
            ],
            "metadata": {"name": "", "labels": []},
        }
        original = copy.deepcopy(row)
        body = machine_rpc(row)
        adapter = Adapter.__new__(Adapter)
        adapter.config = {"core_url": "https://core.test"}
        from pathlib import Path

        adapter.secrets = Path("/test-secrets")
        adapter.check_core_certificate = lambda: None
        with patch(
            "pxeye.clients.process.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, "{}", ""),
        ) as proc:
            adapter.rpc(
                "PatchExpectedMachines",
                {"patches": [{"expected_machine": body, "update_mask": {"paths": ["host_nics"]}}]},
            )
        wire = json.loads(proc.call_args.kwargs["input"])
        nic = wire["patches"][0]["expected_machine"]["host_nics"][0]
        self.assertNotIn("nic_type", nic)
        self.assertNotIn("fixed_mask", nic)
        self.assertFalse(nic["primary"])
        self.assertEqual(nic["physical_ifname"], "")
        self.assertEqual(nic["ip_allocation"], 0)
        self.assertFalse(body["is_dpf_enabled"])
        self.assertEqual(body["metadata"]["labels"], [])
        self.assertEqual(row, original)
        # This deployed grpcurl uses object encoding for FieldMask. Preserve it.
        self.assertEqual(wire["patches"][0]["update_mask"], {"paths": ["host_nics"]})

    def test_local_parse_failure_is_safe_and_does_not_expose_stderr(self):
        result = subprocess.CompletedProcess(
            [],
            1,
            "",
            'Error invoking method "forge.Forge/PatchExpectedMachines": error getting request data: SECRET field null',
        )
        with patch("pxeye.clients.process.subprocess.run", return_value=result):
            with self.assertRaises(RPCRequestError) as error:
                run(["/bin/grpcurl", "forge.Forge/PatchExpectedMachines"])
        self.assertTrue(error.exception.request_not_sent)
        self.assertNotIn("SECRET", str(error.exception))
        self.assertIn("PatchExpectedMachines", str(error.exception))

    def test_remote_failure_is_not_classified_as_unsent(self):
        result = subprocess.CompletedProcess([], 1, "", "Code: Unavailable; SECRET")
        with patch("pxeye.clients.process.subprocess.run", return_value=result):
            with self.assertRaises(RuntimeError) as error:
                run(["/bin/grpcurl", "forge.Forge/PatchExpectedMachines"])
        self.assertFalse(getattr(error.exception, "request_not_sent", False))
        self.assertNotIn("SECRET", str(error.exception))


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_device_plans.DevicePlanTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        f = self.fixture
        self.site, self.store, self.plans = f.site, f.store, f.plans
        self.plan = {
            "device_plan_revision": digest(self.plans.get(f.serial)),
            "management_ip": "192.0.2.91",
        }
        self.snapshot = {
            "baseline_sha256": "baseline",
            "live_sha256": "live",
            "config_version": "v1",
        }
        self.fresh = {
            "passed": True,
            "checks": [{"name": "identity", "passed": True}],
            "installation_plan": self.plan,
            "snapshot": self.snapshot,
        }
        self.site.preflight = lambda *a: copy.deepcopy(self.fresh)
        self.task = {
            "id": "UI-sync",
            "device": f.serial,
            "mode": "reinstall",
            "status": "needs_attention",
            "stage": "planning",
            "hostname": "test",
            "instance_id": "instance",
            "management_ip": "192.0.2.91",
            "current_management_ip": "192.0.2.90",
            "disk_serial": "DISK",
            "error": "old",
            "events": [{"stage": "preflight"}],
            "installation_plan": self.plan,
            "preflight": copy.deepcopy(self.fresh),
        }
        with self.store.db() as db:
            db.execute(
                "INSERT INTO tasks VALUES (?,?,?,?,?,?)",
                (
                    self.task["id"],
                    f.serial,
                    "needs_attention",
                    json.dumps(self.task),
                    time.time(),
                    "sync-test",
                ),
            )
        self.executor = Executor(self.site, self.store)
        self.app = Application.__new__(Application)
        self.app.executor, self.app.store = self.executor, self.store
        self.app.worker_lock = threading.Lock()

    def ledger(self, status):
        path = (
            self.site.data
            / "config"
            / "plan-sync"
            / (
                digest(
                    {
                        "serial": self.task["device"],
                        "revision": digest(self.plans.get(self.task["device"])),
                        "scope": "hardware",
                    }
                )
                + ".json"
            )
        )
        atomic_json(path, {"status": status})

    def test_preflight_is_read_only_and_unknown_sync_is_blocked(self):
        self.ledger("not_sent")
        self.assertTrue(self.executor.restart_preflight(self.task)["passed"])
        self.assertEqual(self.site.writes, [])
        for state in ("requesting", "needs_attention"):
            self.ledger(state)
            with self.assertRaisesRegex(ValueError, "结果未知"):
                self.executor.restart_preflight(self.task)

    def test_install_config_or_boot_action_disables_restart(self):
        self.assertTrue(self.executor.can_restart_preinstall(self.task))
        for key in (
            "reinstall_config_requested",
            "reinstall_boot_requested",
            "user_data_sha256",
            "config_version",
            "address_assignment_requested",
            "native_reinstall_requests",
            "allocation_requested",
        ):
            self.assertFalse(self.executor.can_restart_preinstall(self.task | {key: True}), key)
        self.assertFalse(
            self.executor.can_restart_preinstall(self.task | {"mode": "first_install"})
        )
        self.assertFalse(
            self.executor.can_restart_preinstall(self.task | {"events": [{"stage": "boot"}]})
        )

    def test_changed_os_config_or_planning_cannot_continue(self):
        for key in ("live_sha256", "baseline_sha256", "config_version"):
            old = self.snapshot[key]
            self.snapshot[key] = "changed"
            with self.assertRaises(ValueError):
                self.executor.restart_preflight(self.task)
            self.snapshot[key] = old
        self.task["installation_plan"] = self.plan | {"device_plan_revision": "missing"}
        with self.assertRaises(ValueError):
            self.executor.restart_preflight(self.task)

    def test_confirmation_is_session_bound_single_use_and_reuses_task(self):
        check = self.app.restart_preflight(self.task["id"], "owner")
        body = {
            "preflight_id": check["id"],
            "confirm_serial": self.task["device"],
            "confirm_reboot": True,
        }
        with self.assertRaises(ValueError):
            self.app.restart_install(self.task["id"], body, "other", "operator")
        with patch.object(self.app, "start_queue") as queue:
            result = self.app.restart_install(self.task["id"], body, "owner", "operator")
        queue.assert_called_once()
        self.assertEqual(result["id"], self.task["id"])
        self.assertEqual(result["status"], "queued")
        self.assertEqual(len(self.store.tasks()), 1)
        with self.assertRaises(ValueError):
            self.app.restart_install(self.task["id"], body, "owner", "operator")
        self.assertEqual(self.site.writes, [])

    def test_failed_checks_expiry_and_task_change_cannot_claim(self):
        check = self.app.restart_preflight(self.task["id"], "owner")
        body = {
            "preflight_id": check["id"],
            "confirm_serial": self.task["device"],
            "confirm_reboot": True,
        }
        self.fresh["passed"] = False
        with self.assertRaises(ValueError):
            self.app.restart_install(self.task["id"], body, "owner", "operator")
        self.fresh["passed"] = True
        with self.store.db() as db:
            db.execute("UPDATE preflights SET expires=0 WHERE id=?", (check["id"],))
        with self.assertRaises(ValueError):
            self.app.restart_install(self.task["id"], body, "owner", "operator")
        check = self.app.restart_preflight(self.task["id"], "owner")
        body["preflight_id"] = check["id"]
        task = self.store.get(self.task["id"])
        task["events"].append({"stage": "planning", "message": "changed"})
        self.store.save(task)
        with self.assertRaises(ValueError):
            self.app.restart_install(self.task["id"], body, "owner", "operator")

    def test_synchronize_marks_only_local_parse_failures_as_not_sent(self):
        f = self.fixture
        record = self.plans.get(f.serial)
        record["machine"].setdefault("metadata", {})["name"] = "updated"
        with self.store.db() as db:
            self.plans.put(db, f.serial, record)
        with patch.object(self.site, "rpc", side_effect=RPCRequestError("parse failed")):
            with self.assertRaises(RPCRequestError):
                self.plans.synchronize(f.serial)
        self.assertEqual(self.plans.synchronization_state(f.serial), "not_sent")
        with patch.object(self.site, "rpc", side_effect=RuntimeError("timeout")):
            with self.assertRaises(RuntimeError):
                self.plans.synchronize(f.serial)
        self.assertEqual(self.plans.synchronization_state(f.serial), "needs_attention")

    def test_confirmed_address_sync_does_not_invalidate_its_own_plan(self):
        self.plan.update(boot_addresses=["192.0.2.90"], binding_revision="old-binding")
        task = self.store.get(self.task["id"])
        task["installation_plan"] = copy.deepcopy(self.plan)
        task["preflight"]["installation_plan"] = copy.deepcopy(self.plan)
        task["execution_device"] = {"serial": task["device"], "management_ip": "192.0.2.91"}
        self.store.save(task)
        native = copy.deepcopy(self.plan)

        def synchronize(*args):
            native.update(boot_addresses=["192.0.2.91"], binding_revision="new-binding")
            self.fresh["installation_plan"] = copy.deepcopy(native)

        self.site.installation_plan = lambda *a: copy.deepcopy(native)
        with (
            patch.object(DevicePlans, "synchronize", side_effect=synchronize),
            patch.object(
                self.executor, "verify_materials", side_effect=RuntimeError("material unavailable")
            ) as materials,
        ):
            self.executor.run(task)
        materials.assert_called_once()
        updated = self.store.get(task["id"])
        self.assertEqual(updated["error"], "material unavailable")
        self.assertEqual(updated["synchronized_plan"]["boot_addresses"], ["192.0.2.91"])
        self.assertTrue(self.executor.restart_preflight(updated)["passed"])
        self.assertEqual(self.site.writes, [])

    def test_sync_cannot_accept_unplanned_address_or_interface_change(self):
        self.plan.update(
            boot_addresses=["192.0.2.90"], binding_revision="binding", interface_id="nic"
        )
        for change in (
            {"boot_addresses": ["192.0.2.92"]},
            {"interface_id": "other"},
            {"segment_id": "other"},
            {"management_ip": "192.0.2.92"},
            {"boot_addresses": []},
        ):
            with self.assertRaises(RuntimeError):
                self.executor.bind_synchronized_plan(self.task, self.plan | change)
