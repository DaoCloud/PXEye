"""Focused external-DHCP acceptance; no network or hardware operations."""

import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pxeye.installation.executor import Executor
from pxeye.common import atomic_json, digest
from pxeye.persistence.store import Store
from pxeye.services.boot_transport import BootTransport, external_boot, site_boot_snapshot
from pxeye.services.execution import Adapter
from pxeye.services.onboarding import Onboarding
from pxeye.services.site_boot_network import SiteBootNetwork
from pxeye.services.tasks import TaskCoordinator


class Cluster:
    namespace = "test-site"

    def __init__(self):
        self.patches = []
        self.configmap = {
            "metadata": {"name": "site-kea"},
            "data": {
                "kea_config.json": json.dumps(
                    {
                        "Dhcp4": {
                            "hooks-libraries": [
                                {"parameters": {"nico-provisioning-server-ipv4": "192.0.2.10"}}
                            ]
                        }
                    }
                )
            },
        }
        self.deployment = {
            "metadata": {"name": "site-dhcp", "generation": 1},
            "spec": {
                "replicas": 1,
                "template": {"spec": {"volumes": [{"configMap": {"name": "site-kea"}}]}},
            },
            "status": {
                "observedGeneration": 1,
                "replicas": 1,
                "availableReplicas": 1,
                "updatedReplicas": 1,
            },
        }

    def list(self, resource, namespace):
        return [copy.deepcopy(self.configmap if resource == "configmaps" else self.deployment)]

    def get(self, resource, name, namespace):
        return copy.deepcopy(self.deployment)

    def patch(self, resource, name, body, namespace):
        self.patches.append((resource, name, copy.deepcopy(body)))
        if resource == "configmaps":
            self.configmap["data"].update(body["data"])
        else:
            count = body["spec"]["replicas"]
            self.deployment["spec"]["replicas"] = count
            self.deployment["status"].update(
                replicas=count, readyReplicas=count, availableReplicas=count, updatedReplicas=count
            )


class ExternalBootAcceptance(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.cluster = Cluster()
        self.adapter = SimpleNamespace(data=self.path, config={})
        self.app = SimpleNamespace(
            adapter=self.adapter,
            config=self.adapter.config,
            store=SimpleNamespace(incomplete=lambda: [], save=lambda _: None),
            nico_deployment=SimpleNamespace(cluster=self.cluster),
        )
        self.values = {
            "dhcp_mode": "external",
            "dhcp_address": "",
            "pxe_address": "",
            "pxe_http_endpoint": "http://boot.example.test:8080",
            "material_http_address": "192.0.2.10",
            "material_http_port": 8080,
            "dns_address": "192.0.2.11",
            "ntp_address": "192.0.2.12",
        }

    def test_external_mode_stops_kea_without_changing_allocation_and_native_can_resume(self):
        service = SiteBootNetwork(self.app)
        original = copy.deepcopy(self.cluster.configmap)
        result = service.apply(self.values, "operator")
        self.assertEqual(self.cluster.configmap, original)
        self.assertEqual(self.cluster.deployment["spec"]["replicas"], 0)
        self.assertEqual(result["values"]["pxe_http_endpoint"], self.values["pxe_http_endpoint"])
        frozen = site_boot_snapshot(self.adapter)
        native = self.values | {
            "dhcp_mode": "nico",
            "dhcp_address": "192.0.2.14",
            "pxe_address": "192.0.2.15",
        }
        service.apply(native, "operator")
        self.assertEqual(self.cluster.deployment["spec"]["replicas"], 1)
        self.assertEqual(frozen["dhcp_mode"], "external")
        self.assertEqual(site_boot_snapshot(self.adapter)["dhcp_mode"], "nico")
        advertised = json.loads(self.cluster.configmap["data"]["kea_config.json"])["Dhcp4"]
        self.assertEqual(advertised["option-data"][0]["data"], "192.0.2.14")

    def test_active_task_blocks_mode_change_before_any_write(self):
        service = SiteBootNetwork(self.app)
        self.app.store.incomplete = lambda: [{"id": "active"}]
        with self.assertRaises(ValueError):
            service.apply(self.values, "operator")
        self.assertEqual(self.cluster.patches, [])
        self.assertFalse(service.path.exists())

    def test_restart_reuses_exact_intent_and_does_not_issue_bmc_operations(self):
        row = {
            "id": "d50fb4eb-747f-4f4e-9f1d-7dc5dd329b0b",
            "interfaces": [
                {
                    "primary": True,
                    "role": "host",
                    "mac_address": "02:00:00:00:00:01",
                    "fixed_ip": "192.0.2.20",
                }
            ],
        }
        task = {
            "device": "example",
            "boot_network": {
                "dhcp_mode": "external",
                "pxe_http_endpoint": self.values["pxe_http_endpoint"],
            },
        }
        saved, calls = [], []
        store = SimpleNamespace(save=lambda value: saved.append(copy.deepcopy(value)))

        def rpc(method, body):
            self.assertEqual(saved[-1]["host_boot_intents"]["DISCOVERY:0"]["request"], body)
            calls.append((method, copy.deepcopy(body)))
            return {"generation": body["generation"], "phase": "HOST_BOOT_PHASE_PENDING"}

        self.adapter.rpc = rpc
        with patch("pxeye.services.boot_transport.BootMedia") as media:
            media.return_value.prepare.return_value = {
                "url": "http://media.example.test/boot.iso",
                "sha256": "a" * 64,
            }
            BootTransport(self.adapter, store).prepare(task, "DISCOVERY", row=row)
            restored = copy.deepcopy(saved[-1])
            BootTransport(self.adapter, store).prepare(restored, "DISCOVERY", row=row)
            self.assertEqual(media.return_value.prepare.call_count, 1)
        self.assertEqual(calls[0], calls[1])
        self.assertEqual({name for name, _ in calls}, {"SetHostBootIntent"})

    def test_installer_evidence_for_other_generation_never_reaches_core(self):
        calls = []
        self.adapter.rpc = lambda method, body: calls.append((method, body))
        task = {"boot_network": {"dhcp_mode": "external"}, "host_boot_intents": {}}
        with self.assertRaises(ValueError):
            BootTransport(self.adapter, SimpleNamespace(save=lambda _: None)).acknowledge(
                task, {"host_boot": {"generation": "previous", "token": "old"}}
            )
        self.assertEqual(calls, [])

    def test_lost_set_response_keeps_active_generation_for_retry_or_safe_cancel(self):
        row = {
            "id": "expected",
            "interfaces": [
                {"primary": True, "mac_address": "02:00:00:00:00:01", "fixed_ip": "192.0.2.20"}
            ],
        }
        task = {
            "device": "SERVER",
            "boot_network": {
                "dhcp_mode": "external",
                "pxe_http_endpoint": self.values["pxe_http_endpoint"],
            },
        }
        saved, calls, declared = [], [], {}

        def rpc(method, body):
            calls.append((method, copy.deepcopy(body)))
            if method == "SetHostBootIntent":
                declared.update(body)
                raise RuntimeError("RESPONSE_LOST_AFTER_COMMIT")
            if method == "GetHostBootIntent":
                return {"generation": declared["generation"], "cleanup_complete": False}
            return {"generation": body["generation"], "cleanup_complete": True}

        self.adapter.rpc = rpc
        store = SimpleNamespace(save=lambda value: saved.append(copy.deepcopy(value)))
        transport = BootTransport(self.adapter, store)
        with patch("pxeye.services.boot_transport.BootMedia") as media:
            media.return_value.prepare.return_value = {
                "url": "http://media.example.test/boot.iso",
                "sha256": "a" * 64,
            }
            with self.assertRaisesRegex(RuntimeError, "RESPONSE_LOST"):
                transport.prepare(task, "DISCOVERY", row=row)
            restored = copy.deepcopy(saved[-1])
            self.assertEqual(restored["active_host_boot_intent"], "DISCOVERY:0")
            with self.assertRaisesRegex(RuntimeError, "RESPONSE_LOST"):
                transport.prepare(restored, "DISCOVERY", row=row)
            self.assertEqual(media.return_value.prepare.call_count, 1)
        self.assertEqual(calls[0], calls[1])
        transport.cancel(restored)
        self.assertEqual(calls[-1][0], "CancelHostBoot")
        self.assertEqual(calls[-1][1]["generation"], declared["generation"])

    def test_cancel_never_touches_another_generation_and_allows_absent_policy(self):
        task = self.admission_record()
        calls = []
        status = {"generation": "replacement", "cleanup_complete": True}

        def rpc(method, body):
            calls.append(method)
            return copy.deepcopy(status)

        self.adapter.rpc = rpc
        transport = BootTransport(self.adapter, SimpleNamespace(save=lambda _: None))
        with self.assertRaisesRegex(ValueError, "其他代次"):
            transport.cancel(task)
        status.clear()
        transport.cancel(task)
        self.assertEqual(calls, ["GetHostBootIntent", "GetHostBootIntent"])

    def test_worker_waits_for_async_local_disk_handoff_without_redeclaring_it(self):
        task = self.admission_record()
        device = {
            "architecture": "x86_64",
            "boot_mac": "02:00:00:00:00:01",
            "management_ip": "192.0.2.20",
        }
        row = {
            "id": "d50fb4eb-747f-4f4e-9f1d-7dc5dd329b0b",
            "interfaces": [
                {
                    "primary": True,
                    "mac_address": device["boot_mac"],
                    "fixed_ip": device["management_ip"],
                }
            ],
        }
        status = {
            "generation": "discovery-1",
            "purpose": "HOST_BOOT_PURPOSE_DISCOVERY",
            "cleanup_complete": True,
        }
        calls, reads = [], 0

        def rpc(method, body):
            nonlocal reads
            calls.append(method)
            if method == "SetHostBootIntent":
                status.update(
                    generation=body["generation"], purpose=body["purpose"], cleanup_complete=False
                )
            else:
                reads += 1
                if reads >= 3:
                    status["cleanup_complete"] = True
            return copy.deepcopy(status)

        self.adapter.rpc = rpc
        transport = BootTransport(self.adapter, SimpleNamespace(save=lambda _: None))
        transport.row = lambda _: row
        with patch("pxeye.services.boot_transport.time.sleep") as sleep:
            result = transport.wait_for_handoff(task, device)
        self.assertEqual(result["purpose"], "HOST_BOOT_PURPOSE_LOCAL_DISK")
        self.assertTrue(result["cleanup_complete"])
        self.assertEqual(calls.count("SetHostBootIntent"), 1)
        self.assertEqual(sleep.call_count, 2)

    def test_worker_handoff_wait_has_a_deadline(self):
        task = self.admission_record()
        self.adapter.rpc = lambda method, body: {
            "generation": "discovery-1",
            "purpose": "HOST_BOOT_PURPOSE_DISCOVERY",
            "cleanup_complete": False,
        }
        transport = BootTransport(self.adapter, SimpleNamespace(save=lambda _: None))
        with patch("pxeye.services.boot_transport.time.monotonic", side_effect=[0, 76]):
            with patch("pxeye.services.boot_transport.time.sleep") as sleep:
                with self.assertRaises(TimeoutError):
                    transport.wait_for_handoff(task, {})
                sleep.assert_not_called()

    def test_existing_unready_machine_gets_discovery_policy_without_replaying_ingestion(self):
        row = {
            "id": "d50fb4eb-747f-4f4e-9f1d-7dc5dd329b0b",
            "bmc_mac_address": "02:00:00:00:00:10",
            "interfaces": [
                {"primary": True, "mac_address": "02:00:00:00:00:01", "fixed_ip": "192.0.2.20"}
            ],
        }
        self.adapter.config["discovery_timeout_seconds"] = 0
        calls = []

        def rpc(method, body):
            calls.append(method)
            return {"generation": body["generation"]}

        self.adapter.rpc = rpc
        executor = Executor(self.adapter, SimpleNamespace(save=lambda _: None))
        executor.event = lambda *a, **k: None
        for ready in (False, True):
            with self.subTest(ready=ready):
                calls.clear()
                task = {
                    "id": "task",
                    "device": "SERVER",
                    "hostname": "host",
                    "profile": "flat",
                    "installation_plan": {},
                    "preflight": {"snapshot": {}},
                    "impact_authorization": {
                        "policy_revision": "policy",
                        "cleanup_scope": "all_disks",
                    },
                    "boot_network": {
                        "dhcp_mode": "external",
                        "pxe_http_endpoint": self.values["pxe_http_endpoint"],
                    },
                }
                with patch("pxeye.services.onboarding.Onboarding") as onboarding:
                    service = onboarding.return_value
                    service.deferred_preflight.return_value = {
                        "installation_plan": {},
                        "snapshot": {},
                    }
                    service.inventory_row.return_value = row
                    service.observed.return_value = {
                        "SERVER": {
                            "machine": {"id": "machine", "state": "Ready" if ready else "HostInit"},
                            "instances": [],
                            "first_install_ready": ready,
                        }
                    }
                    service.admission.return_value = self.admission_record()
                    service.probe.return_value = ({"bmc_ip": "192.0.2.90"}, {})
                    with patch(
                        "pxeye.domain.workflow.authorize_impact",
                        return_value={"policy_revision": "policy"},
                    ):
                        with patch("pxeye.services.boot_transport.BootMedia") as media:
                            media.return_value.prepare.return_value = {
                                "url": "http://media.example.test/boot.iso",
                                "sha256": "a" * 64,
                            }
                            with self.assertRaises(TimeoutError):
                                executor.bootstrap_first(task, self.path)
                    service.admit.assert_not_called()
                self.assertEqual(calls, [] if ready else ["SetHostBootIntent"])

    def test_external_tasks_never_enter_direct_pxe_or_disk_recovery(self):
        task = {
            "boot_network": {"dhcp_mode": "external"},
            "native_reinstall_requests": 1,
            "status": "running",
            "stage": "boot",
        }
        executor = Executor(self.adapter, SimpleNamespace(save=lambda _: None))
        self.assertFalse(executor.can_start_automatic_recovery(task))
        self.assertFalse(executor.request_standard_pxe_boot(task, "Assigned/Ready", "test"))
        self.assertFalse(executor.recover_disk_boot(task, {}, {}))
        self.assertFalse(external_boot({}))
        self.assertEqual(site_boot_snapshot(self.adapter), {"dhcp_mode": "nico"})

    def admission_record(self, generation="discovery-1"):
        return {
            "serial": "SERVER",
            "device": "SERVER",
            "bmc_mac": "02:00:00:00:00:10",
            "status": "accepted",
            "boot_network": {"dhcp_mode": "external"},
            "external_boot": True,
            "ingestion_requested": True,
            "active_host_boot_intent": "DISCOVERY:0",
            "host_boot_intents": {
                "DISCOVERY:0": {
                    "request": {
                        "expected_machine_id": {"value": "d50fb4eb-747f-4f4e-9f1d-7dc5dd329b0b"},
                        "generation": generation,
                        "purpose": "HOST_BOOT_PURPOSE_DISCOVERY",
                    }
                }
            },
        }

    def test_standalone_admission_blocks_mode_change_until_core_is_ready_or_cancelled(self):
        service = SiteBootNetwork(self.app)
        record = self.admission_record()
        atomic_json(self.path / "config/admissions/admission.json", record)
        status = {"generation": "discovery-1", "cleanup_complete": True}
        self.adapter.rpc = lambda method, body: copy.deepcopy(status)
        machine = {"bmc_info": {"mac": record["bmc_mac"]}, "state": "HostInit/WaitingForCleanup"}
        self.adapter.core = lambda *a, **k: {"machines": [copy.deepcopy(machine)]}
        with self.assertRaisesRegex(ValueError, "Ready"):
            service.apply(self.values, "operator")
        self.assertEqual(self.cluster.patches, [])
        self.assertFalse(service.path.exists())
        machine["state"] = "Ready"
        service.apply(self.values, "operator")
        self.assertEqual(self.cluster.deployment["spec"]["replicas"], 0)
        machine["state"] = "HostInit/WaitingForCleanup"
        status["cancelled"] = True
        service.apply(self.values, "operator")

    def test_unknown_standalone_generation_and_missing_cleanup_never_change_network(self):
        record = self.admission_record()
        atomic_json(self.path / "config/admissions/admission.json", record)
        self.adapter.core = lambda *a, **k: {
            "machines": [{"bmc_info": {"mac": record["bmc_mac"]}, "state": "Ready"}]
        }
        for status in (
            {"generation": "replacement", "cleanup_complete": True},
            {"generation": "discovery-1", "cleanup_complete": False},
        ):
            with self.subTest(status=status):
                self.adapter.rpc = lambda method, body: copy.deepcopy(status)
                with self.assertRaises(ValueError):
                    SiteBootNetwork(self.app).apply(self.values, "operator")
                self.assertEqual(self.cluster.patches, [])

    def test_native_release_matches_any_recorded_generation_and_never_releases_replacement(self):
        store = Store(self.path / "console.sqlite3")
        atomic_json(self.path / "config/admissions/a.json", self.admission_record("old"))
        atomic_json(self.path / "config/admissions/b.json", self.admission_record("current"))
        calls = []
        generation = "replacement"

        def rpc(method, body):
            calls.append((method, copy.deepcopy(body)))
            return {"generation": generation, "cleanup_complete": True}

        self.adapter.rpc = rpc
        transport = BootTransport(self.adapter, store)
        with self.assertRaisesRegex(ValueError, "其他代次"):
            transport.release_for_native({"device": "SERVER"})
        self.assertEqual([name for name, _ in calls], ["GetHostBootIntent"])
        calls.clear()
        generation = "current"
        transport.release_for_native({"device": "SERVER"})
        self.assertEqual(
            [name for name, _ in calls], ["GetHostBootIntent", "ReleaseHostBootPolicy"]
        )
        self.assertEqual(calls[-1][1]["generation"], "current")

    def test_cancelled_standalone_can_be_explicitly_readmitted_in_either_mode(self):
        store = Store(self.path / "console.sqlite3")
        resources = SimpleNamespace(store=store, inventory=lambda **_: None)
        service = Onboarding(self.adapter, store, resources)
        row = {
            "id": "d50fb4eb-747f-4f4e-9f1d-7dc5dd329b0b",
            "chassis_serial_number": "SERVER",
            "bmc_mac_address": "02:00:00:00:00:10",
            "bmc_retain_credentials": True,
            "interfaces": [
                {"primary": True, "mac_address": "02:00:00:00:00:01", "fixed_ip": "192.0.2.20"}
            ],
        }
        record = self.admission_record()
        record.update(revision=digest(row))
        service.inventory_row = lambda _: row
        service.observed = lambda _: {"SERVER": {"machine": None, "instances": []}}
        service.check_preparation = lambda _: None
        service.probe = lambda _: ({"bmc_ip": "192.0.2.90"}, {})
        for mode in ("nico", "external"):
            with self.subTest(mode=mode):
                atomic_json(service.directory / (row["id"] + ".json"), record)
                calls = []

                def rpc(method, body):
                    calls.append(method)
                    if method == "GetHostBootIntent":
                        return {
                            "generation": "discovery-1",
                            "cleanup_complete": True,
                            "cancelled": True,
                        }
                    if method == "DetermineMachineIngestionState":
                        return {"machineIngestionState": "WaitingForIngestion"}
                    if method == "SetHostBootIntent":
                        return {"generation": body["generation"]}
                    return {}

                self.adapter.rpc = rpc
                snapshot = {
                    "dhcp_mode": mode,
                    "pxe_http_endpoint": self.values["pxe_http_endpoint"],
                }
                with patch("pxeye.services.onboarding.site_boot_snapshot", return_value=snapshot):
                    with patch("pxeye.services.device_plans.DevicePlans.synchronize"):
                        with patch("pxeye.services.boot_transport.BootMedia") as media:
                            media.return_value.prepare.return_value = {
                                "url": "http://media.example.test/boot.iso",
                                "sha256": "a" * 64,
                            }
                            result = service.admit(
                                {
                                    "serial": "SERVER",
                                    "revision": digest(row),
                                    "confirm_serial": "SERVER",
                                    "confirm_ingestion": True,
                                    "cleanup_scope": "all_disks",
                                },
                                "operator",
                            )
                self.assertEqual(result["status"], "accepted")
                if mode == "nico":
                    self.assertLess(
                        calls.index("ReleaseHostBootPolicy"),
                        calls.index("AllowIngestionAndPowerOn"),
                    )
                    self.assertNotIn("SetHostBootIntent", calls)
                    self.assertFalse(external_boot(result))
                else:
                    self.assertNotIn("ReleaseHostBootPolicy", calls)
                    self.assertLess(
                        calls.index("SetHostBootIntent"), calls.index("AllowIngestionAndPowerOn")
                    )
                    request = result["host_boot_intents"][result["active_host_boot_intent"]][
                        "request"
                    ]
                    self.assertNotEqual(request["generation"], "discovery-1")
        history = list((service.directory / "history").glob("*.json"))
        self.assertEqual(len(history), 2)
        self.assertTrue(all(json.loads(path.read_text()) == record for path in history))

    def test_readmission_rejects_uncancelled_unclean_or_replaced_policy(self):
        record = self.admission_record()
        row = {"id": "d50fb4eb-747f-4f4e-9f1d-7dc5dd329b0b"}
        transport = BootTransport(self.adapter, SimpleNamespace(save=lambda _: None))
        for status in (
            {"generation": "discovery-1", "cleanup_complete": True},
            {"generation": "discovery-1", "cancelled": True, "cleanup_complete": False},
            {"generation": "replacement", "cancelled": True, "cleanup_complete": True},
        ):
            with self.subTest(status=status):
                self.adapter.rpc = lambda method, body: copy.deepcopy(status)
                with self.assertRaisesRegex(ValueError, "不能重新接管"):
                    transport.check_readmission(record, row)
        self.adapter.rpc = lambda method, body: {}
        transport.check_readmission(record, row)

    def test_admission_preview_allows_only_clean_cancelled_external_request_without_writes(self):
        store = Store(self.path / "console.sqlite3")
        service = Onboarding(self.adapter, store, SimpleNamespace(store=store))
        record = self.admission_record()
        row = {
            "id": "d50fb4eb-747f-4f4e-9f1d-7dc5dd329b0b",
            "bmc_mac_address": record["bmc_mac"],
            "bmc_retain_credentials": True,
        }
        atomic_json(service.directory / (row["id"] + ".json"), record)
        service.inventory_row = lambda _: row
        service.observed = lambda _: {
            "SERVER": {"machine": None, "instances": [], "first_install_ready": False}
        }
        service.preparation_checks = lambda _: []
        service.probe = lambda _: ({"bmc_ip": "192.0.2.90"}, {})
        calls = []
        status = {"generation": "discovery-1", "cancelled": True, "cleanup_complete": True}

        def rpc(method, body):
            calls.append(method)
            if method == "GetHostBootIntent":
                return copy.deepcopy(status)
            return {"machineIngestionState": "WaitingForIngestion"}

        self.adapter.rpc = rpc
        self.assertTrue(service.admission_preview({"serials": ["SERVER"]}, "session")["passed"])
        status["cancelled"] = False
        self.assertFalse(service.admission_preview({"serials": ["SERVER"]}, "session")["passed"])
        self.assertEqual(set(calls), {"GetHostBootIntent", "DetermineMachineIngestionState"})
        self.assertEqual(
            json.loads((service.directory / (row["id"] + ".json")).read_text()), record
        )
        self.assertFalse((service.directory / "history").exists())

    def test_external_scope_rejects_dpu_profiles_plans_and_observed_dpus(self):
        profile = {"architecture": "x86_64", "network_mode": "flat"}
        BootTransport.check_scope(profile)
        for candidate, machine, row in (
            (profile | {"network_mode": "dpu"}, None, None),
            (profile | {"architecture": "aarch64"}, None, None),
            (profile, {"status": {"associated_dpu_machine_ids": ["dpu"]}}, None),
            (profile, None, {"dpu_policy": "manage"}),
        ):
            with self.subTest(profile=candidate, machine=machine, row=row):
                with self.assertRaisesRegex(ValueError, "Flat"):
                    BootTransport.check_scope(candidate, machine, row=row)

    def test_deferred_external_preflight_rejects_dpu_before_material_or_ingestion_work(self):
        service = Onboarding(
            self.adapter,
            SimpleNamespace(active=lambda _: None, save=lambda _: None),
            SimpleNamespace(),
        )
        service.inventory_row = lambda _: {}
        service.profile = lambda _: {"architecture": "x86_64", "network_mode": "dpu"}
        with patch.object(BootTransport, "check", return_value={"dhcp_mode": "external"}):
            with self.assertRaisesRegex(ValueError, "Flat"):
                service.deferred_preflight("SERVER", "host", "dpu-profile", None)

    def test_native_existing_instance_preflight_does_not_read_hostboot_or_planned_row(self):
        device = {
            "serial": "SERVER",
            "architecture": "x86_64",
            "profile": "legacy",
            "machine_id": "machine",
            "instance_id": "instance",
            "disk_wwn": "disk",
            "management_ip": "192.0.2.20",
            "bmc_ip": "192.0.2.90",
        }
        adapter = SimpleNamespace(
            data=self.path,
            config={"materials": []},
            resources=SimpleNamespace(store=SimpleNamespace()),
            device=lambda *a, **k: copy.deepcopy(device),
            installation_plan=lambda _: None,
            machine=lambda _: {"state": "Assigned/Ready"},
            instance=lambda _: {"config_version": "v1", "config": {"os": {"user_data": "data"}}},
            baseline=lambda _: {},
            redfish=lambda _: {"SerialNumber": "SERVER", "PowerState": "On"},
        )
        with patch.object(BootTransport, "row", side_effect=AssertionError("unexpected row")):
            result = Adapter.preflight(adapter, "SERVER", "host")
        self.assertTrue(result["passed"], result["checks"])


class ExternalManualAcceptance(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.store = Store(self.path / "console.sqlite3")
        self.calls = []
        self.status = {
            "generation": "disk-1",
            "purpose": "HOST_BOOT_PURPOSE_LOCAL_DISK",
            "cleanup_complete": False,
        }

        def rpc(method, body):
            self.calls.append(method)
            # A read-only Core query must run before the DB write transaction.
            with self.store.db() as db:
                db.execute("BEGIN IMMEDIATE")
            return copy.deepcopy(self.status)

        self.adapter = SimpleNamespace(data=self.path, config={}, rpc=rpc)
        self.coordinator = TaskCoordinator.__new__(TaskCoordinator)
        self.coordinator.adapter = self.adapter
        self.coordinator.store = self.store
        self.coordinator.worker_lock = threading.Lock()
        self.task = {
            "id": "task",
            "device": "SERVER",
            "status": "needs_attention",
            "stage": "firstboot",
            "boot_network": {"dhcp_mode": "external"},
            "acceptance_skips": {
                name: {}
                for name in (
                    "installer",
                    "identity",
                    "disk",
                    "network",
                    "ssh",
                    "services",
                    "normal_reboot",
                )
            },
            "active_host_boot_intent": "LOCAL_DISK:0",
            "host_boot_intents": {
                "LOCAL_DISK:0": {
                    "request": {
                        "generation": "disk-1",
                        "purpose": "HOST_BOOT_PURPOSE_LOCAL_DISK",
                        "expected_machine_id": {"value": "expected"},
                    }
                }
            },
        }
        with self.store.db() as db:
            db.execute(
                "INSERT INTO tasks VALUES(?,?,?,?,?,?)",
                ("task", "SERVER", "needs_attention", json.dumps(self.task), 1, "request"),
            )

    def test_skips_wait_for_current_local_disk_cleanup_and_recheck_after_core_changes(self):
        result = self.coordinator.reconcile_acceptance_skips(self.task)
        self.assertEqual(result["status"], "needs_attention")
        self.assertEqual(result["acceptance_summary"]["state"], "pending")
        self.assertIsNotNone(self.store.active("SERVER"))
        self.status["cleanup_complete"] = True
        result = self.coordinator.reconcile_acceptance_skips(result)
        self.assertEqual(result["status"], "completed")
        self.assertIsNone(self.store.active("SERVER"))
        self.assertEqual(self.calls, ["GetHostBootIntent", "GetHostBootIntent"])

    def test_stale_failed_cancelled_or_wrong_purpose_status_cannot_complete(self):
        for status in (
            {"generation": "other"},
            {"cancelled": True},
            {"phase": "HOST_BOOT_PHASE_FAILED"},
            {"purpose": "HOST_BOOT_PURPOSE_INSTALLATION"},
        ):
            with self.subTest(status=status):
                self.status.update(cleanup_complete=True)
                self.status.update(status)
                result = self.coordinator.reconcile_acceptance_skips(self.task)
                self.assertEqual(result["status"], "needs_attention")
                self.assertNotIn("receipt", result)
                self.status = {
                    "generation": "disk-1",
                    "purpose": "HOST_BOOT_PURPOSE_LOCAL_DISK",
                    "cleanup_complete": False,
                }
        self.assertEqual(set(self.calls), {"GetHostBootIntent"})

    def test_installation_intent_cannot_be_waived_into_local_disk_handoff(self):
        self.task["host_boot_intents"]["LOCAL_DISK:0"]["request"]["purpose"] = (
            "HOST_BOOT_PURPOSE_INSTALLATION"
        )
        self.store.save(self.task)
        result = self.coordinator.reconcile_acceptance_skips(self.task)
        self.assertEqual(result["status"], "needs_attention")
        self.assertEqual(self.calls, [])

    def test_generation_change_during_read_is_fenced_before_completion(self):
        self.status["cleanup_complete"] = True
        original_rpc = self.adapter.rpc

        def replaced(method, body):
            result = original_rpc(method, body)
            current = self.store.get("task")
            current["host_boot_intents"]["LOCAL_DISK:0"]["request"]["generation"] = "disk-2"
            self.store.save(current)
            return result

        self.adapter.rpc = replaced
        result = self.coordinator.reconcile_acceptance_skips(self.task)
        self.assertEqual(result["status"], "needs_attention")
        self.assertIn("已变化", result["error"])


if __name__ == "__main__":
    unittest.main()
