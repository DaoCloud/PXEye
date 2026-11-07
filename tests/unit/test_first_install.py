"""Exercise new-host admission, real task persistence and allocation requests with fake I/O."""

import copy
import hashlib
import json
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import yaml

from pxeye.services.execution import Adapter
from pxeye.common import sha
from pxeye.installation.executor import Executor
from pxeye.services.onboarding import Onboarding, scout_boot_guard, preparation_message
from pxeye.installation.profile_template import generic_ubuntu
from pxeye.services.resources import Resources
from pxeye.common import digest
from pxeye.domain.machines import machine_rpc
from pxeye.bootstrap import Application
from pxeye.persistence.store import Store


class FakeSite(Adapter):
    def __init__(self, root, number=10):
        self.rows, self.machines, self.instances, self.links, self.writes = [], [], [], [], []
        self.fail_allocation = set()
        self.boot_overrides = {}
        self.gates = {}
        (root / "ssh_key").write_text("TEST_KEY")
        (root / "ssh_key.pub").write_text("ssh-ed25519 VEVTVA== console-test")
        (root / "known_hosts").write_text("")
        (root / "auth.json").write_text(
            json.dumps({"password_sha256": hashlib.sha256(b"test-only-password").hexdigest()})
        )
        source = {
            "variant": {"OperatingSystemId": str(uuid.uuid4())},
            "user_data": yaml.safe_dump(
                {
                    "autoinstall": {
                        "ssh": {"authorized-keys": ["ssh-ed25519 T1BTS0VZ operator"]},
                        "apt": {"geoip": False},
                        "identity": {"hostname": "OLD"},
                        "early-commands": ["OLD_CHASSIS"],
                        "late-commands": ["OLD_WWN"],
                    }
                }
            ),
        }
        template = generic_ubuntu(source, "ops", "192.0.2.53", "UTC", "192.0.2.54")
        (root / "generic.json").write_text(json.dumps(template))
        self.profile_config = {
            "id": "ubuntu-generic",
            "name": "Ubuntu 通用",
            "architecture": "x86_64",
            "os_release": "24.04",
            "network_mode": "flat",
            "ssh_user": "ops",
            "dns": "192.0.2.53",
            "timezone": "UTC",
            "dns_checks": ["example.test"],
            "http_checks": ["http://192.0.2.50/"],
            "baseline_file": "generic.json",
            "allocation": {
                "tenant": {"tenant_organization_id": "test-org"},
                "network": {"auto_config": {"vpc_id": {"value": str(uuid.uuid4())}}},
            },
        }
        config = {
            "devices": [],
            "first_install_profiles": [self.profile_config],
            "materials": [],
            "core_url": "https://api.example.test",
            "network": {},
            "site": {
                "name": "TEST",
                "namespace": "mmzhou",
                "deployment": "mmzhou-os-install-console",
            },
            "task_timeout_seconds": 1,
        }
        super().__init__(config, root, root / "data")
        self.segment = {
            "id": {"value": str(uuid.uuid4())},
            "metadata": {"name": "inband"},
            "config": {
                "segmentType": "HOST_INBAND",
                "mtu": 1500,
                "prefixes": [{"prefix": "192.0.2.0/24", "gateway": "192.0.2.1", "reserveFirst": 5}],
            },
            "status": {"tenantState": "READY"},
        }
        for i in range(number):
            serial, mac, hostmac = (
                "NEW-%02d" % (i + 1),
                "02:00:00:00:00:%02x" % (i + 1),
                "02:00:00:00:01:%02x" % (i + 1),
            )
            row = {
                "id": str(uuid.uuid4()),
                "chassis_serial_number": serial,
                "bmc_mac_address": mac,
                "bmc_ip_address": "198.51.100." + str(i + 10),
                "bmc_username": "ops",
                "bmc_password": "TEST_SECRET",
                "bmc_retain_credentials": True,
                "default_pause_ingestion_and_poweron": True,
                "dpu_policy": "ignore",
                "dpf_enabled": False,
                "interfaces": [
                    {
                        "mac_address": hostmac,
                        "role": "host",
                        "primary": True,
                        "ip_allocation": "fixed",
                        "fixed_ip": "192.0.2." + str(i + 10),
                        "fixed_mask": "255.255.255.0",
                        "fixed_gateway": "192.0.2.1",
                    }
                ],
            }
            machine = {
                "id": "machine-" + str(i),
                "state": "Ready",
                "machine_type": "HOST",
                "bmc_info": {"ip": row["bmc_ip_address"], "mac": mac},
                "status": {
                    "associated_dpu_machine_ids": [],
                    "discovery_info": {
                        "machine_arch": 1,
                        "dmi_data": {"product_serial": serial},
                        "network_interfaces": [{"mac_address": hostmac}],
                        "block_devices": [
                            {
                                "model": "TEST_DISK",
                                "serial": "SCOUT-DISK-" + str(i),
                                "device_type": "disk",
                            }
                        ],
                    },
                },
            }
            self.rows.append(row)
            self.machines.append(machine)
            self.links += [
                {
                    "id": {"value": str(uuid.uuid4())},
                    "macAddress": hostmac,
                    "machineId": {"id": machine["id"]},
                    "segmentId": self.segment["id"],
                    "primaryInterface": True,
                    "address": ["192.0.2." + str(i + 10)],
                },
                {
                    "id": {"value": str(uuid.uuid4())},
                    "isBmc": True,
                    "macAddress": mac,
                    "machineId": {"id": machine["id"]},
                },
            ]
            self.gates[mac] = "WaitingForIngestion"

    def core(self, args, data=False):
        if args[:2] == ["expected-machine", "show"]:
            return {"expected_machines": [machine_rpc(row) for row in self.rows]}
        if args[:2] == ["machine", "show"]:
            return {"machines": copy.deepcopy(self.machines)}
        if args[:2] == ["instance", "show"]:
            return {"instances": copy.deepcopy(self.instances)}
        if args[:2] == ["machine-interfaces", "show-addresses"]:
            nic = next(n for n in self.links if n["id"]["value"] == args[2])
            return [{"address": ip, "allocation_type": "Static"} for ip in nic["address"]]
        raise AssertionError("Unexpected CLI call: " + str(args))

    def rpc(self, method, body):
        if method == "FindNetworkSegmentIds":
            return {"networkSegmentsIds": [self.segment["id"]]}
        if method == "FindNetworkSegmentsByIds":
            return {"networkSegments": [copy.deepcopy(self.segment)]}
        if method == "FindInterfaces":
            return {"interfaces": copy.deepcopy(self.links)}
        if method == "GetMachineBootOverride":
            return copy.deepcopy(self.boot_overrides.get(body["value"], {}))
        if method == "FindVpcsByIds":
            return {
                "vpcs": [
                    {
                        "id": body["vpc_ids"][0],
                        "config": {
                            "networkVirtualizationType": "FLAT",
                            "tenantOrganizationId": "test-org",
                        },
                    }
                ]
            }
        if method == "GetBMCMetaData":
            return {
                "user": "ops",
                "password": "TEST_SECRET",
                "ip": body["bmc_endpoint_request"]["ip_address"],
                "mac": body["bmc_endpoint_request"]["mac_address"],
            }
        if method == "DetermineMachineIngestionState":
            return {"machineIngestionState": self.gates[body["mac_address"].lower()]}
        self.writes.append((method, copy.deepcopy(body)))
        if method == "AllowIngestionAndPowerOn":
            self.gates[body["mac_address"].lower()] = "IngestionMachineNotCreated"
            return {}
        if method == "AssignStaticAddress":
            nic = next(n for n in self.links if n["id"] == body["interface_id"])
            nic["address"] = [body["ip_address"]]
            return {"ipAddress": body["ip_address"], "interfaceId": body["interface_id"]}
        if method == "SetPrimaryInterface":
            for nic in self.links:
                if nic.get("machineId") == body["host_machine_id"] and not nic.get("isBmc"):
                    nic["primaryInterface"] = nic["id"] == body["interface_id"]
            return {}
        if method == "AllocateInstance":
            if body["machine_id"]["id"] in self.fail_allocation:
                raise RuntimeError("INJECTED_ALLOCATION_TIMEOUT")
            instance = {
                "id": body["instance_id"]["value"],
                "machine_id": body["machine_id"]["id"],
                "config_version": "v1",
                "config": body["config"],
            }
            self.instances.append(copy.deepcopy(instance))
            next(m for m in self.machines if m["id"] == instance["machine_id"])["state"] = (
                "Assigned/Ready"
            )
            return {"id": body["instance_id"]}
        raise AssertionError("Unexpected RPC " + method)

    def redfish(self, device, suffix="", method="GET", body=None):
        assert method == "GET", "Unexpected BMC mutation"
        if device["redfish_system"] == "/redfish/v1/Systems":
            return {"Members": [{"@odata.id": "/redfish/v1/Systems/1"}]}
        return {
            "SerialNumber": device["serial"],
            "PowerState": "Off",
            "Boot": {"BootSourceOverrideEnabled": "Disabled"},
        }

    def ssh(self, *args, **kwargs):
        raise AssertionError("Fresh preflight must never require existing OS SSH")

    def check_materials(self):
        pass


class FirstInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.adapter = FakeSite(self.root)
        self.store = Store(self.adapter.data / "console.sqlite3")
        self.resources = Resources(self.adapter, self.store)
        self.onboarding = Onboarding(self.adapter, self.store, self.resources)
        self.app = Application.__new__(Application)
        self.app.adapter = self.adapter
        self.app.store = self.store
        self.app.resources = self.resources
        self.app.onboarding = self.onboarding
        self.app.config = self.adapter.config
        self.app.executor = Executor(self.adapter, self.store)
        self.app.worker_lock = threading.Lock()

    def tearDown(self):
        self.tmp.cleanup()

    def batch_body(self, number=10):
        return {
            "mode": "first_install",
            "profile_id": "ubuntu-generic",
            "devices": [
                {
                    "serial": row["chassis_serial_number"],
                    "hostname": "nico-%02d" % (i + 1),
                    "disk_serial": "SCOUT-DISK-" + str(i),
                }
                for i, row in enumerate(self.adapter.rows[:number])
            ],
        }

    def prepare(self, number=10):
        check = self.app.batch_preflight(self.batch_body(number), "owner")
        body = {
            "preflight_id": check["id"],
            "request_key": uuid.uuid4().hex,
            "confirm_serials": [c["device"] for c in check["checks"]],
            "confirm_disk": True,
            "confirm_reboot": True,
            "cleanup_scope": "all_disks",
        }
        with patch.object(self.app, "start_queue"):
            batch = self.app.submit_batch(body, "owner", "operator")
        return check, body, batch

    def test_ten_empty_hosts_pass_preflight_without_prior_records_or_ssh(self):
        check = self.app.batch_preflight(self.batch_body(), "owner")
        self.assertTrue(check["passed"])
        self.assertEqual(len(check["checks"]), 10)
        self.assertEqual(self.store.tasks(), [])
        self.assertEqual(self.adapter.writes, [])
        self.assertTrue(
            all(
                "host" not in c["snapshot"] and c["scope"]["instance_id"] is None
                for c in check["checks"]
            )
        )

    def test_csv_inventory_discovery_ready_is_available_for_first_install(self):
        devices = self.resources.devices()
        self.assertEqual(len(devices), 10)
        self.assertTrue(all(d["first_install_ready"] and not d["executable"] for d in devices))
        self.assertNotIn("TEST_SECRET", json.dumps(devices))
        self.adapter.machines[0]["state"] = "HostInit/Discovering"
        self.assertFalse(self.resources.devices()[0]["first_install_ready"])

    def test_selected_unready_host_can_queue_without_remote_writes(self):
        self.adapter.machines[0]["state"] = "HostInit/Discovering"
        check = self.app.batch_preflight(self.batch_body(1), "owner")
        self.assertTrue(check["passed"])
        self.assertTrue(check["checks"][0]["deferred_first_install"])
        body = {
            "preflight_id": check["id"],
            "request_key": uuid.uuid4().hex,
            "confirm_serials": [check["checks"][0]["device"]],
            "confirm_disk": True,
            "confirm_reboot": True,
            "cleanup_scope": "all_disks",
        }
        with patch.object(self.app, "start_queue"):
            batch = self.app.submit_batch(body, "owner", "operator")
        self.assertEqual(len(batch["tasks"]), 1)
        self.assertEqual(self.adapter.writes, [])
        self.assertTrue(batch["tasks"][0]["deferred_bootstrap"])

    def deferred_task(self, disk="SCOUT-DISK-0", absent=False):
        self.adapter.machines[0]["state"] = "HostInit/Discovering"
        if absent:
            self.adapter.machines = []
        body = self.batch_body(1)
        body["devices"][0]["disk_serial"] = disk
        check = self.app.batch_preflight(body, "owner")
        with patch.object(self.app, "start_queue"):
            batch = self.app.submit_batch(
                {
                    "preflight_id": check["id"],
                    "request_key": uuid.uuid4().hex,
                    "confirm_serials": ["NEW-01"],
                    "confirm_disk": True,
                    "confirm_reboot": True,
                    "cleanup_scope": "all_disks",
                },
                "owner",
                "operator",
            )
        return batch["tasks"][0]

    def test_queued_missing_machine_has_no_invented_ids_and_accepts_own_lock(self):
        task = self.deferred_task(absent=True)
        self.assertIsNone(task["instance_id"])
        self.assertIsNone(task["execution_device"])
        self.adapter.config["discovery_timeout_seconds"] = 0
        # Keep the configuration revision bound to the changed timeout.
        task["installation_plan"]["execution_revision"] = digest(self.adapter.config)
        self.app.executor.run(task)
        self.assertEqual(task["status"], "needs_attention")
        self.assertTrue(task["prepare_available"])
        self.assertEqual([w[0] for w in self.adapter.writes], ["AllowIngestionAndPowerOn"])
        self.app.executor.run(task)
        self.assertEqual([w[0] for w in self.adapter.writes], ["AllowIngestionAndPowerOn"])
        self.assertEqual(self.adapter.instances, [])

    def test_ready_transitions_freeze_real_identity_before_allocation(self):
        task = self.deferred_task()

        def ready(*args):
            self.adapter.machines[0]["state"] = "Ready"

        with patch("pxeye.installation.executor.time.sleep", side_effect=ready):
            self.app.executor.bootstrap_first(task, self.adapter.data)
        self.assertFalse(task["deferred_bootstrap"])
        self.assertEqual(task["execution_device"]["machine_id"], "machine-0")
        self.assertEqual(str(uuid.UUID(task["instance_id"])), task["instance_id"])
        self.assertEqual(self.adapter.writes, [])
        self.assertEqual(self.adapter.instances, [])

    def test_scout_guard_pauses_existing_host_before_any_write(self):
        task = self.deferred_task()
        ident = self.adapter.links[0]["id"]["value"]
        self.adapter.boot_overrides[ident] = {
            "customPxe": "kernel scout.efi systemd.mask=forge-scout.service\nboot"
        }
        self.app.executor.run(task)
        self.assertEqual(task["status"], "needs_attention")
        self.assertTrue(task["prepare_available"])
        self.assertIn("停用了 forge-scout.service", task["error"])
        self.assertIn("磁盘范围", task["error"])
        self.assertIsNone(task["instance_id"])
        self.assertEqual(self.adapter.writes, [])

    def test_guard_added_while_waiting_blocks_ready_allocation(self):
        task = self.deferred_task()

        def ready(*args):
            self.adapter.machines[0]["state"] = "Ready"
            self.adapter.boot_overrides[self.adapter.links[0]["id"]["value"]] = {
                "customUserData": "#cloud-config\nbootcmd:\n - [systemctl, mask, --runtime, --now, forge-scout.service]"
            }

        with patch("pxeye.installation.executor.time.sleep", side_effect=ready):
            self.app.executor.run(task)
        self.assertEqual(task["status"], "needs_attention")
        self.assertIsNone(task["instance_id"])
        self.assertEqual(self.adapter.writes, [])

    def test_wrong_planned_mac_does_not_hide_bound_machine_guard(self):
        row = self.onboarding.inventory_row("NEW-01")
        row["interfaces"][0]["mac_address"] = "02:00:00:ff:ff:ff"
        self.adapter.boot_overrides[self.adapter.links[0]["id"]["value"]] = {
            "customPxe": "kernel scout.efi systemd.mask=forge-scout.service"
        }
        with self.assertRaisesRegex(ValueError, "停用了 forge-scout.service"):
            self.onboarding.check_scout_boot_guard(row, self.adapter.machines[0])
        self.assertEqual(self.adapter.writes, [])

    def test_another_machines_boot_guard_is_not_used_for_target(self):
        row = self.onboarding.inventory_row("NEW-01")
        self.adapter.boot_overrides[self.adapter.links[2]["id"]["value"]] = {
            "customPxe": "kernel scout.efi systemd.mask=forge-scout.service"
        }
        self.onboarding.check_scout_boot_guard(row, self.adapter.machines[0])
        row["interfaces"][0]["mac_address"] = self.adapter.links[2]["macAddress"]
        with self.assertRaisesRegex(ValueError, "另一台 Machine"):
            self.onboarding.check_scout_boot_guard(row, self.adapter.machines[0])
        self.assertEqual(self.adapter.writes, [])

    def test_failed_machine_stops_without_waiting_for_timeout(self):
        task = self.deferred_task()
        self.adapter.machines[0]["state"] = "Failed/HardwareValidation"
        with patch(
            "pxeye.installation.executor.time.sleep",
            side_effect=AssertionError("Must stop before sleeping"),
        ):
            self.app.executor.run(task)
        self.assertIn("NICo 设备准备失败", task["error"])
        self.assertEqual(self.adapter.writes, [])

    def test_multi_disk_waits_for_selection_and_resumes_same_task(self):
        task = self.deferred_task(disk=None)
        self.adapter.machines[0]["status"]["discovery_info"]["block_devices"].append(
            {"serial": "OTHER", "device_type": "disk"}
        )
        self.adapter.machines[0]["state"] = "Ready"
        self.app.executor.run(task)
        self.assertTrue(task["prepare_available"])
        self.assertIn("多块磁盘", task["error"])
        self.assertEqual(self.adapter.writes, [])
        task["disk_serial"] = "SCOUT-DISK-0"
        # Simulate the user's newly saved disk plan, and explicitly check/continue.
        self.store.save(task)
        check = self.app.preparation_preflight(task["id"], "owner")
        with patch.object(self.app, "start_queue"):
            resumed = self.app.continue_preparation(
                task["id"],
                {
                    "preflight_id": check["id"],
                    "confirm_serial": task["device"],
                    "confirm_reboot": True,
                    "cleanup_scope": "all_disks",
                },
                "owner",
                "operator",
            )
        self.assertEqual(resumed["id"], task["id"])
        self.assertEqual(resumed["disk_serial"], "SCOUT-DISK-0")
        self.app.executor.bootstrap_first(resumed, self.adapter.data)
        self.assertFalse(resumed["deferred_bootstrap"])
        self.assertEqual(len(self.store.tasks()), 1)
        self.assertEqual(self.adapter.writes, [])

    def test_single_scout_disk_is_resolved_only_after_ready(self):
        task = self.deferred_task(disk=None)
        self.adapter.machines[0]["state"] = "Ready"
        self.app.executor.bootstrap_first(task, self.adapter.data)
        self.assertEqual(task["disk_serial"], "SCOUT-DISK-0")
        self.assertEqual(self.adapter.writes, [])

    def test_reinstall_batch_does_not_require_first_install_profile_field(self):
        # An ordinary reinstall preflight has no profile_id field.
        device = self.onboarding.plan("NEW-01", "ubuntu-generic", "SCOUT-DISK-0")[1]
        device["instance_id"] = str(uuid.uuid4())
        plan = self.resources.execution_plan("NEW-01", device=device)
        check = {
            "device": "NEW-01",
            "hostname": "nico-01",
            "passed": True,
            "installation_plan": plan,
            "snapshot": {},
            "checks": [],
        }
        with (
            patch.object(self.adapter, "device", return_value=device),
            patch.object(self.adapter, "preflight", return_value=check),
        ):
            preview = self.app.batch_preflight(
                {
                    "mode": "reinstall",
                    "profile_id": None,
                    "devices": [{"serial": "NEW-01", "hostname": "nico-01", "disk_serial": None}],
                },
                "owner",
            )
            with patch.object(self.app, "start_queue"):
                batch = self.app.submit_batch(
                    {
                        "preflight_id": preview["id"],
                        "request_key": uuid.uuid4().hex,
                        "confirm_serials": ["NEW-01"],
                        "confirm_disk": True,
                        "confirm_reboot": True,
                        "cleanup_scope": "all_disks",
                    },
                    "owner",
                    "operator",
                )
        self.assertEqual(batch["tasks"][0]["instance_id"], device["instance_id"])
        self.assertEqual(batch["tasks"][0]["profile"], "ubuntu-generic")
        self.assertEqual(self.adapter.writes, [])

    def test_pending_plan_change_blocks_submit_before_any_write(self):
        self.adapter.machines[0]["state"] = "HostInit/Discovering"
        check = self.app.batch_preflight(self.batch_body(1), "owner")
        self.adapter.rows[0]["interfaces"][0]["fixed_ip"] = "192.0.2.99"
        with self.assertRaisesRegex(ValueError, "变化"):
            self.app.submit_batch(
                {
                    "preflight_id": check["id"],
                    "request_key": uuid.uuid4().hex,
                    "confirm_serials": ["NEW-01"],
                    "confirm_disk": True,
                    "confirm_reboot": True,
                    "cleanup_scope": "all_disks",
                },
                "owner",
                "operator",
            )
        self.assertEqual(self.adapter.writes, [])
        self.assertEqual(self.store.tasks(), [])

    def test_wrong_bmc_stops_before_admission_and_unknown_request_not_replayed(self):
        task = self.deferred_task(absent=True)
        with patch.object(
            self.adapter, "redfish", return_value={"Members": [], "SerialNumber": "OTHER"}
        ):
            self.app.executor.run(task)
        self.assertIn("序列号", task["error"])
        self.assertEqual(self.adapter.writes, [])
        atomic = __import__("resources").atomic_json
        atomic(
            self.onboarding.directory / (self.adapter.rows[0]["id"] + ".json"),
            {"status": "requesting", "bmc_mac": self.adapter.rows[0]["bmc_mac_address"]},
        )
        self.app.executor.run(task)
        self.assertIn("结果待核对", task["error"])
        self.assertEqual(self.adapter.writes, [])

    def test_continuation_rejects_allocation_attempt_and_other_owner(self):
        task = self.deferred_task()
        task["status"] = "needs_attention"
        self.store.save(task)
        check = self.app.preparation_preflight(task["id"], "owner")
        body = {
            "preflight_id": check["id"],
            "confirm_serial": task["device"],
            "confirm_reboot": True,
            "cleanup_scope": "all_disks",
        }
        with self.assertRaises(ValueError):
            self.app.continue_preparation(task["id"], body, "other", "operator")
        task["allocation_requested"] = True
        self.store.save(task)
        with self.assertRaises(ValueError):
            self.app.continue_preparation(task["id"], body, "owner", "operator")
        self.assertEqual(self.adapter.writes, [])

    def test_target_hostname_ip_disk_and_instance_are_unique_and_frozen(self):
        _, _, batch = self.prepare()
        self.assertEqual(len({t["instance_id"] for t in batch["tasks"]}), 10)
        rendered = [
            yaml.safe_load(self.adapter.render(t["execution_device"], t)["user_data"])[
                "autoinstall"
            ]
            for t in batch["tasks"]
        ]
        self.assertEqual(len({a["identity"]["hostname"] for a in rendered}), 10)
        self.assertEqual(
            len({a["network"]["ethernets"]["management"]["addresses"][0] for a in rendered}), 10
        )
        self.assertEqual(len({a["storage"]["config"][0]["match"]["serial"] for a in rendered}), 10)
        self.assertNotIn("OLD_CHASSIS", json.dumps(rendered))
        self.assertNotIn("OLD_WWN", json.dumps(rendered))
        for ai in rendered:
            self.assertIn("ID_SERIAL_SHORT", "\n".join(ai["early-commands"]))
            self.assertIn("/autoinstall.yaml", ai["early-commands"][0])
            self.assertIn("ssh-ed25519 T1BTS0VZ operator", ai["ssh"]["authorized-keys"])

    def test_duplicate_submit_returns_same_batch_and_ten_reservations(self):
        _, body, batch = self.prepare()
        again = self.app.submit_batch(body, "owner", "operator")
        self.assertEqual(again["id"], batch["id"])
        self.assertEqual(len(self.store.tasks()), 10)
        self.assertEqual(self.adapter.writes, [])
        with self.assertRaises(ValueError):
            self.app.submit_batch(body, "other-owner", "operator")

    def test_first_delivery_persists_reinstall_entry_and_original_scout_disk_identity(self):
        _, _, batch = self.prepare(1)
        task = batch["tasks"][0]
        device = task["execution_device"]
        self.adapter.instances = [{"id": device["instance_id"], "machine_id": device["machine_id"]}]
        self.adapter.machines[0]["state"] = "Assigned/Ready"
        self.adapter.remember_connection(device, task)
        row = self.resources.devices()[0]
        self.assertTrue(row["executable"])
        self.assertFalse(row["first_install_ready"])
        self.assertEqual(row["disk_serial"], "SCOUT-DISK-0")
        self.assertEqual(row["instance_id"], task["instance_id"])
        rendered = self.adapter.render(
            self.adapter.device(task["device"]), dict(task, mode="reinstall")
        )
        self.assertIn("SCOUT-DISK-0", rendered["user_data"])

    def test_stale_plan_and_occupied_host_block_entire_batch_before_writes(self):
        check = self.app.batch_preflight(self.batch_body(), "owner")
        self.adapter.rows[3]["interfaces"][0]["fixed_ip"] = "192.0.2.90"
        body = {
            "preflight_id": check["id"],
            "request_key": uuid.uuid4().hex,
            "confirm_serials": [c["device"] for c in check["checks"]],
            "confirm_disk": True,
            "confirm_reboot": True,
            "cleanup_scope": "all_disks",
        }
        with self.assertRaises(ValueError):
            self.app.submit_batch(body, "owner", "operator")
        self.assertEqual(self.store.tasks(), [])
        self.assertEqual(self.adapter.writes, [])

    def test_invalid_disk_architecture_mac_and_flat_dpu_are_blocked(self):
        for mutation in ["disk", "arch", "mac", "dpu", "assigned"]:
            with self.subTest(mutation=mutation):
                original = copy.deepcopy(self.adapter.machines[0])
                body = self.batch_body(1)
                if mutation == "disk":
                    body["devices"][0]["disk_serial"] = "NOT_DISCOVERED"
                if mutation == "arch":
                    self.adapter.machines[0]["status"]["discovery_info"]["machine_arch"] = 0
                if mutation == "mac":
                    self.adapter.links[0]["macAddress"] = "02:00:00:00:ff:ff"
                if mutation == "dpu":
                    self.adapter.machines[0]["status"]["associated_dpu_machine_ids"] = ["dpu"]
                if mutation == "assigned":
                    self.adapter.machines[0]["state"] = "Assigned/Ready"
                if mutation == "assigned":
                    with self.assertRaises(ValueError):
                        self.app.batch_preflight(body, "owner")
                else:
                    self.assertFalse(self.app.batch_preflight(body, "owner")["passed"])
                self.adapter.machines[0] = original
                self.adapter.links[0]["macAddress"] = self.adapter.rows[0]["interfaces"][0][
                    "mac_address"
                ]
        self.assertEqual(self.adapter.writes, [])

    def test_admission_is_scoped_once_and_unknown_outcome_is_not_replayed(self):
        self.adapter.machines = []
        preview = self.onboarding.admission_preview({"serials": ["NEW-01", "NEW-02"]}, "owner")
        self.assertTrue(preview["passed"])
        self.assertEqual(self.adapter.writes, [])
        body = {
            "preflight_id": preview["id"],
            "confirm_serials": ["NEW-01", "NEW-02"],
            "confirm_ingestion": True,
            "cleanup_scope": "all_disks",
        }
        result = self.onboarding.admit_batch(body, "owner", "operator")
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(len(self.adapter.writes), 2)
        with self.assertRaises(ValueError):
            self.onboarding.admit_batch(body, "owner", "operator")
        self.assertEqual(len(self.adapter.writes), 2)
        self.assertEqual(
            (self.adapter.data / "config/expected-machines.json").stat().st_mode & 0o777, 0o600
        )

    def test_admission_gate_phases_explain_wait_without_replaying(self):
        self.adapter.machines = []
        mac = self.adapter.rows[0]["bmc_mac_address"]
        for gate, phase in [
            ("WaitingForIngestion", "approval"),
            ("NotDiscovered", "blocked"),
            ("IngestionMachineNotCreated", "waiting"),
            ("IngestionMachineCreated", "waiting"),
        ]:
            with self.subTest(gate=gate):
                self.adapter.gates[mac] = gate
                result = self.onboarding.admission_preview({"serials": ["NEW-01"]}, "owner")
                c = result["checks"][0]
                self.assertEqual(c["phase"], phase)
                self.assertEqual(result["passed"], gate == "WaitingForIngestion")
                self.assertEqual(
                    {i["key"] for i in c["items"]},
                    {
                        "scope",
                        "credentials",
                        "bmc_address",
                        "boot_interface",
                        "boot_network",
                        "identity",
                        "gate",
                        "scout",
                    },
                )
                if not result["passed"]:
                    with self.assertRaises(ValueError):
                        self.onboarding.admit_batch(
                            {
                                "preflight_id": result["id"],
                                "confirm_serials": ["NEW-01"],
                                "confirm_ingestion": True,
                                "cleanup_scope": "all_disks",
                            },
                            "owner",
                            "operator",
                        )
        self.assertEqual(self.adapter.writes, [])

    def test_admission_check_collects_failures_and_skips_dependent_network(self):
        self.adapter.machines = []
        self.adapter.rows[0]["interfaces"] = []
        with patch.object(self.adapter, "redfish", return_value={"Members": []}):
            c = self.onboarding.admission_preview({"serials": ["NEW-01"]}, "owner")["checks"][0]
        items = {i["key"]: i for i in c["items"]}
        self.assertEqual(items["boot_interface"]["status"], "fail")
        self.assertEqual(items["boot_network"]["status"], "skipped")
        self.assertEqual(items["identity"]["status"], "fail")
        self.assertFalse(c["passed"])
        self.assertEqual(self.adapter.writes, [])

    def test_admission_preview_and_view_use_current_contact_endpoint(self):
        self.adapter.machines = []
        row = self.adapter.rows[0]
        original = self.adapter.rpc
        endpoints = []

        def rpc(method, body):
            if method == "DetermineMachineIngestionState":
                endpoints.append(body["ip_address"])
            return original(method, body)

        self.adapter.rpc = rpc
        with patch(
            "pxeye.services.bmc_addresses.BMCAddresses.view",
            return_value={"current_ip": "198.51.100.99", "status": "verified"},
        ):
            c = self.onboarding.admission_preview({"serials": ["NEW-01"]}, "owner")["checks"][0]
            self.onboarding.view("NEW-01")
        self.assertEqual(c["bmc_ip"], "198.51.100.99")
        self.assertEqual(endpoints, ["198.51.100.99", "198.51.100.99"])
        self.assertEqual(self.adapter.writes, [])

    def test_not_discovered_bmc_and_wrong_identity_never_admit(self):
        self.adapter.machines = []
        self.adapter.gates[self.adapter.rows[0]["bmc_mac_address"]] = "NotDiscovered"
        self.assertFalse(
            self.onboarding.admission_preview({"serials": ["NEW-01"]}, "owner")["passed"]
        )
        with patch.object(self.adapter, "redfish", return_value={"Members": []}):
            self.assertFalse(
                self.onboarding.admission_preview({"serials": ["NEW-02"]}, "owner")["passed"]
            )
        self.assertEqual(self.adapter.writes, [])

    def test_duplicate_hostnames_and_ips_rejected_before_batch_submission(self):
        body = self.batch_body(2)
        body["devices"][1]["hostname"] = body["devices"][0]["hostname"]
        with self.assertRaises(ValueError):
            self.app.batch_preflight(body, "owner")
        self.adapter.rows[1]["interfaces"][0]["fixed_ip"] = "192.0.2.10"
        self.assertFalse(self.app.batch_preflight(self.batch_body(2), "owner")["passed"])
        self.assertEqual(self.store.tasks(), [])

    def test_atomic_reservations_rollback_on_last_busy_device(self):
        check, body, batch = self.prepare(1)
        # Bypass API's earlier validation to prove the SQLite transaction rolls back all children.
        candidates = self.app.batch_preflight(
            {
                "mode": "first_install",
                "profile_id": "ubuntu-generic",
                "devices": self.batch_body(3)["devices"][1:],
            },
            "owner",
        )
        tasks = []
        for c in candidates["checks"]:
            tasks.append(
                {
                    "id": uuid.uuid4().hex,
                    "device": c["device"],
                    "hostname": c["hostname"],
                    "status": "queued",
                    "installation_plan": c["installation_plan"],
                }
            )
        with self.store.db() as db:
            db.execute(
                "INSERT INTO tasks VALUES (?,?,?,?,?,?)",
                (
                    "busy",
                    "NEW-03",
                    "needs_attention",
                    json.dumps({"id": "busy", "device": "NEW-03", "status": "needs_attention"}),
                    0,
                    "busy-key",
                ),
            )
        with self.assertRaises(ValueError):
            self.store.claim_batch(
                candidates["id"],
                {"id": "batch-two", "mode": "first_install"},
                tasks,
                uuid.uuid4().hex,
                "owner",
            )
        self.assertIsNone(self.store.active("NEW-02"))

    def test_expired_batch_and_template_drift_never_allocate(self):
        check, body, batch = self.prepare(1)
        template = json.loads((self.root / "generic.json").read_text())
        template["phone_home_enabled"] = True
        (self.root / "generic.json").write_text(json.dumps(template))
        self.app.executor.run(batch["tasks"][0])
        self.assertEqual(self.store.get(batch["tasks"][0]["id"])["status"], "needs_attention")
        self.assertEqual(self.adapter.writes, [])

    def test_queue_single_failure_does_not_block_other_hosts(self):
        _, _, batch = self.prepare()
        order = []

        def run(task):
            order.append(task["device"])
            task["status"] = "needs_attention" if task["device"] == "NEW-04" else "completed"
            self.store.save(task)

        with patch.object(self.app.executor, "run", side_effect=run):
            self.app.start_queue()
            for _ in range(100):
                if not self.app.worker_lock.locked():
                    break
                time.sleep(0.01)
        result = self.store.batch(batch["id"])
        self.assertEqual(result["counts"]["completed"], 9)
        self.assertEqual(result["counts"]["needs_attention"], 1)
        self.assertEqual(len(order), 10)
        self.assertIsNotNone(self.store.active("NEW-04"))
        self.assertIsNone(self.store.active("NEW-05"))

    def test_first_allocation_does_not_update_or_reboot_existing_instance(self):
        _, _, batch = self.prepare(1)
        task = batch["tasks"][0]
        executor = self.app.executor
        with (
            patch("pxeye.installation.executor.Console") as console,
            patch.object(executor, "verify_materials"),
        ):
            console.return_value.text = "SOL Session operational"
            executor.start_first(task, task["execution_device"], self.adapter.data)
        requests = [b for m, b in self.adapter.writes if m == "AllocateInstance"]
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["machine_id"]["id"], "machine-0")
        self.assertEqual(requests[0]["instance_id"]["value"], task["instance_id"])
        self.assertFalse(requests[0]["config"]["os"]["run_provisioning_instructions_on_every_boot"])
        self.assertEqual(requests[0]["config"]["tenant"]["hostname"], task["hostname"])
        self.assertEqual(task["native_allocation_requests"], 1)
        self.assertEqual(len(self.adapter.instances), 1)

    def test_allocation_timeout_keeps_planned_id_and_never_replays(self):
        _, _, batch = self.prepare(1)
        task = batch["tasks"][0]
        executor = self.app.executor
        self.adapter.fail_allocation.add("machine-0")
        with (
            patch("pxeye.installation.executor.Console") as console,
            patch.object(executor, "verify_materials"),
        ):
            console.return_value.text = "SOL Session operational"
            executor.run(task)
        saved = self.store.get(task["id"])
        self.assertEqual(saved["status"], "needs_attention")
        self.assertTrue(saved["allocation_requested"])
        self.assertEqual(saved["instance_id"], task["instance_id"])
        self.assertIsNotNone(self.store.active("NEW-01"))
        self.assertEqual(sum(m == "AllocateInstance" for m, _ in self.adapter.writes), 1)
        self.assertFalse(executor.can_resume(saved))


if __name__ == "__main__":
    unittest.main()


class ScoutPreparationTests(unittest.TestCase):
    def test_masks_are_recognized_and_metadata_is_not_a_command(self):
        for override in (
            {"customPxe": "kernel /scout.efi systemd.mask=forge-scout.service ||\nboot"},
            {"custom_pxe": "kernel /scout.efi systemd.mask=forge-scout"},
            {
                "customUserData": yaml.safe_dump(
                    {
                        "bootcmd": [
                            ["sh", "-c", "systemctl mask --runtime --now forge-scout.service"]
                        ]
                    }
                )
            },
            {
                "custom_user_data": yaml.safe_dump(
                    {"runcmd": ["systemctl --runtime mask forge-scout.service"]}
                )
            },
        ):
            with self.subTest(override=override):
                self.assertTrue(scout_boot_guard(override))
        for override in (
            {},
            {"customPxe": "# systemd.mask=forge-scout.service"},
            {"customPxe": "kernel /scout.efi systemd.mask=some-other.service"},
            {
                "customUserData": yaml.safe_dump(
                    {
                        "notes": "systemctl mask forge-scout.service",
                        "runcmd": ["systemctl unmask forge-scout.service"],
                    }
                )
            },
        ):
            with self.subTest(override=override):
                self.assertFalse(scout_boot_guard(override))

    def test_cleanup_message_does_not_claim_current_scout_is_online(self):
        message = preparation_message(
            {
                "state": "WaitingForCleanup/HostCleanup { boss_controller_id: None }",
                "scout_received": True,
            }
        )
        self.assertIn("等待 Scout", message)
        self.assertIn("尚未下发 ISO", message)
        self.assertIn("不代表 Scout 当前在线", message)

    def test_invalid_cloud_init_is_reported_without_exposing_its_contents(self):
        with self.assertRaises(ValueError) as caught:
            scout_boot_guard({"customUserData": "password: [TEST_SECRET"})
        self.assertNotIn("TEST_SECRET", str(caught.exception))


class FirstAcceptanceTests(unittest.TestCase):
    def setUp(self):
        import accept_host
        import disk_identity

        self.module = accept_host
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.device = {
            "serial": "EMPTY-HOST",
            "hostname": "nico-01",
            "os_release": "24.04",
            "architecture": "x86_64",
            "boot_mac": "02:00:00:00:01:01",
            "management_ip": "192.0.2.10",
            "prefixlen": 24,
            "gateway": "192.0.2.1",
            "dns": "192.0.2.53",
            "timezone": "UTC",
            "dns_checks": [],
            "http_checks": [],
            "disk_serial": "UDEV-SERIAL",
            "instance_id": "new-instance",
        }
        self.task = {"id": "UI-EMPTY", "hostname": "nico-01", "preflight": {"snapshot": {}}}
        self.key = "ssh-ed25519 VEVTVA=="
        self.receipt = {
            "source": "nico-ui",
            "task_id": "UI-EMPTY",
            "serial": "EMPTY-HOST",
            "hostname": "nico-01",
            "instance_id": "new-instance",
            "disk_serial": "UDEV-SERIAL",
        }
        self.disks = [
            {
                "name": "sda",
                "type": "disk",
                "serial": "DIFFERENT_LSBLK_SERIAL",
                "wwn": "0xTARGET",
                "fstype": None,
            },
            {"name": "sdb", "type": "disk", "serial": "OTHER", "wwn": "0xOTHER", "fstype": "ext4"},
        ]
        files = {
            "/sys/class/dmi/id/product_serial": "EMPTY-HOST",
            "/etc/os-release": 'VERSION_ID="24.04"',
            "/var/log/nico-installation/task.json": json.dumps(self.receipt),
            "/etc/nico-installation.json": json.dumps(self.receipt),
            "/etc/ssh/ssh_host_ed25519_key.pub": self.key,
            "/sys/class/net/eno1/address": self.device["boot_mac"],
            "/var/log/installer/subiquity-server-debug.log": "finish: subiquity/Late/run: SUCCESS: ok\nfinish: subiquity/Install/install: SUCCESS: ok\nUI-EMPTY NICO_UI_HOSTKEY ",
            "/var/log/installer/autoinstall-user-data": yaml.safe_dump(
                {"autoinstall": {"identity": {"hostname": "nico-01"}}}
            ),
            "/var/lib/cloud/data/status.json": json.dumps(
                {
                    "v1": {
                        k: {"finished": 1, "errors": []}
                        for k in ["init-local", "init", "modules-config", "modules-final"]
                    }
                }
            ),
            "/var/lib/cloud/data/result.json": json.dumps({"v1": {"errors": []}}),
            "/proc/sys/kernel/random/boot_id": "boot-one",
            "/var/log/nico-installation/disks.before.json": json.dumps(
                {
                    "task_id": "UI-EMPTY",
                    "serial": "EMPTY-HOST",
                    "disk_serial": "UDEV-SERIAL",
                    "target_name": "sda",
                    "disks": self.disks,
                }
            ),
        }
        for path, value in files.items():
            p = self.root / path.lstrip("/")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(value)
        (self.root / "dev").mkdir()
        (self.root / "dev/sda").touch()
        mapping = {
            ("hostname",): "nico-01",
            ("uname", "-m"): "x86_64",
            ("findmnt", "-J", "/"): json.dumps(
                {"filesystems": [{"source": "/dev/sda2", "fstype": "ext4"}]}
            ),
            ("lsblk", "-no", "PKNAME", "/dev/sda2"): "sda",
            ("lsblk", "-no", "PKNAME", "/dev/sda1"): "sda",
            ("blkid", "-s", "UUID", "-o", "value", "/dev/sda2"): "new-root",
            ("findmnt", "-no", "SOURCE", "/boot/efi"): "/dev/sda1",
            ("blkid", "-s", "PARTUUID", "-o", "value", "/dev/sda1"): "new-esp",
            ("ip", "-j", "-4", "addr", "show", "eno1"): json.dumps(
                [{"addr_info": [{"local": "192.0.2.10", "prefixlen": 24}]}]
            ),
            ("ip", "-j", "-4", "route", "show", "default"): json.dumps(
                [{"gateway": "192.0.2.1", "dev": "eno1"}]
            ),
            ("netplan", "get"): "dhcp4: false\nnameservers:\n  addresses: [192.0.2.53]",
            ("timedatectl", "show", "-p", "Timezone", "--value"): "UTC",
            ("/usr/sbin/sshd", "-T"): "passwordauthentication no",
            ("systemctl", "--failed", "--no-legend", "--plain"): "",
            ("timedatectl", "show", "-p", "NTPSynchronized", "--value"): "yes",
            ("efibootmgr",): "BootOrder: 0001",
            ("ssh-keygen", "-lf", "/etc/ssh/ssh_host_ed25519_key.pub"): "SHA256:TEST",
        }

        def cmd(argv):
            if argv == ["lsblk", "-J", "-o", "NAME,TYPE,FSTYPE,WWN,SERIAL,MOUNTPOINTS"]:
                return json.dumps({"blockdevices": self.disks})
            return mapping[tuple(argv)]

        self.patches = [
            patch.object(accept_host, "Path", side_effect=lambda p: self.root / str(p).lstrip("/")),
            patch.object(accept_host, "command", side_effect=cmd),
            patch.object(
                accept_host, "resolve_disk", create=True, return_value=self.root / "dev/sda"
            ),
            patch.object(
                accept_host, "disk_layout", create=True, side_effect=disk_identity.disk_layout
            ),
        ]
        for p in self.patches:
            p.start()
        self.ctx = {"device": self.device, "task": self.task, "trusted_key": self.key}

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_first_boot_accepts_blank_host_without_old_uuid_and_checks_normal_reboot(self):
        initial = self.module.collect(self.ctx)
        self.assertTrue(initial["checks"]["disk"])
        self.assertEqual(initial["root_uuid"], "new-root")
        (self.root / "proc/sys/kernel/random/boot_id").write_text("boot-two")
        after = self.module.collect(self.ctx | {"initial": initial})
        self.assertTrue(after["checks"]["normal_reboot"])
        self.assertEqual(after["host_key"], initial["host_key"])

    def test_unrelated_disk_change_or_wrong_key_blocks_first_acceptance(self):
        self.disks[1]["fstype"] = "xfs"
        with self.assertRaisesRegex(AssertionError, "OTHER_DISK_LAYOUT_CHANGED"):
            self.module.collect(self.ctx)
        self.disks[1]["fstype"] = "ext4"
        with self.assertRaisesRegex(AssertionError, "TRUSTED_SOL_KEY_MISMATCH"):
            self.module.collect(self.ctx | {"trusted_key": "ssh-ed25519 WRONG"})

    def test_foreign_guard_record_and_receipt_are_rejected(self):
        path = self.root / "var/log/nico-installation/disks.before.json"
        record = json.loads(path.read_text())
        record["task_id"] = "OLD-TASK"
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(AssertionError, "DISK_GUARD_RECORD_MISMATCH"):
            self.module.collect(self.ctx)


class RestartQueueTests(unittest.TestCase):
    def test_restart_retains_queued_children_and_marks_interrupted_child_attention(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = FakeSite(root, number=0)
            store = Store(site.data / "console.sqlite3")
            for task_id, status in [
                ("waiting", "queued"),
                ("interrupted", "running"),
                ("installer-failed", "running"),
            ]:
                task = {
                    "id": task_id,
                    "device": task_id,
                    "status": status,
                    "batch_id": "batch",
                    "events": [],
                }
                with store.db() as db:
                    db.execute(
                        "INSERT INTO tasks VALUES (?,?,?,?,?,?)",
                        (task_id, task_id, status, json.dumps(task), time.time(), task_id),
                    )
            executed = []

            def run(task):
                executed.append(task["id"])
                task["status"] = "completed"
                store.save(task)

            with (
                patch("pxeye.bootstrap.Adapter", return_value=site),
                patch("pxeye.bootstrap.Executor") as executor,
            ):
                executor.return_value.attempt_text.side_effect = (
                    lambda task: "start: subiquity/ErrorReporter/123.install_fail/add_info: \n"
                    if task["id"] == "installer-failed"
                    else ""
                )
                executor.return_value.can_resume.return_value = False
                executor.return_value.can_prepare.return_value = False
                executor.return_value.can_retry_install.return_value = False
                executor.return_value.can_restart_preinstall.return_value = False
                executor.return_value.run.side_effect = run
                app = Application(site.config, root, site.data, root)
                for _ in range(100):
                    if not app.worker_lock.locked():
                        break
                    time.sleep(0.01)
                self.assertEqual(executed, ["waiting"])
                self.assertEqual(store.get("interrupted")["status"], "needs_attention")
                self.assertIsNotNone(store.active("interrupted"))
                self.assertEqual(
                    store.get("installer-failed")["installer_failure"]["kind"], "installer_failed"
                )
                self.assertIn("安装失败", store.get("installer-failed")["error"])
                app.lockfile.close()


class InstallBootInterfaceTests(unittest.TestCase):
    def test_confirmed_first_install_selects_owned_scout_nic_once(self):
        with tempfile.TemporaryDirectory() as directory:
            site = FakeSite(Path(directory), 1)
            store = Store(site.data / "console.sqlite3")
            executor = Executor(site, store)
            task = {
                "id": "boot-selection",
                "device": "NEW-01",
                "mode": "first_install",
                "status": "running",
                "events": [],
            }
            site.links[0]["primaryInterface"] = False
            self.assertTrue(
                executor.select_install_boot_interface(
                    task, Onboarding(site, store), site.rows[0], site.machines[0]
                )
            )
            self.assertEqual(task["boot_interface_selection"]["status"], "verified")
            self.assertFalse(
                executor.select_install_boot_interface(
                    task, Onboarding(site, store), site.rows[0], site.machines[0]
                )
            )
            self.assertEqual([w[0] for w in site.writes], ["SetPrimaryInterface"])

    def test_wrong_owner_and_unknown_write_outcome_block_without_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            site = FakeSite(Path(directory), 1)
            store = Store(site.data / "console.sqlite3")
            executor = Executor(site, store)
            task = {
                "id": "blocked-selection",
                "device": "NEW-01",
                "mode": "first_install",
                "status": "running",
                "events": [],
            }
            site.links[0]["primaryInterface"] = False
            site.links[0]["machineId"] = {"id": "other-host"}
            with self.assertRaisesRegex(RuntimeError, "不属于"):
                executor.select_install_boot_interface(
                    task, Onboarding(site, store), site.rows[0], site.machines[0]
                )
            self.assertEqual(site.writes, [])
            site.links[0]["machineId"] = {"id": site.machines[0]["id"]}
            with patch.object(
                site,
                "rpc",
                side_effect=lambda method, body: {"interfaces": copy.deepcopy(site.links)}
                if method == "FindInterfaces"
                else (_ for _ in ()).throw(RuntimeError("UNCERTAIN_RESULT")),
            ):
                with self.assertRaisesRegex(RuntimeError, "UNCERTAIN_RESULT"):
                    executor.select_install_boot_interface(
                        task, Onboarding(site, store), site.rows[0], site.machines[0]
                    )
            self.assertEqual(task["boot_interface_selection"]["status"], "requesting")
            with self.assertRaisesRegex(RuntimeError, "不自动重放"):
                executor.select_install_boot_interface(
                    task, Onboarding(site, store), site.rows[0], site.machines[0]
                )
            self.assertEqual(site.writes, [])


class DiskIdentityTests(unittest.TestCase):
    def test_scout_udev_identity_wins_over_lsblk_serial_and_ambiguous_disks_fail(self):
        import disk_identity

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "dev/disk/by-id").mkdir(parents=True)
            (root / "dev/sdb").touch()
            (root / "dev/sdc").touch()
            (root / "dev/disk/by-id/wwn-0xRAID").symlink_to(root / "dev/sdb")
            rows = [
                {"name": "sdb", "type": "disk", "rm": False, "serial": "LSBLK_DIFF"},
                {"name": "sdc", "type": "disk", "rm": False},
            ]
            values = {"sdb": "SCOUT_UDEV", "sdc": "OTHER"}
            with (
                patch.object(
                    disk_identity, "Path", side_effect=lambda p: root / str(p).lstrip("/")
                ),
                patch.object(
                    disk_identity.subprocess,
                    "check_output",
                    return_value=json.dumps({"blockdevices": rows}),
                ),
                patch.object(
                    disk_identity,
                    "properties",
                    side_effect=lambda p: {"ID_SERIAL_SHORT": values[p.name]},
                ),
            ):
                self.assertEqual(
                    disk_identity.resolve_disk("SCOUT_UDEV"), root / "dev/disk/by-id/wwn-0xRAID"
                )
                values["sdc"] = "SCOUT_UDEV"
                with self.assertRaisesRegex(RuntimeError, "AMBIGUOUS"):
                    disk_identity.resolve_disk("SCOUT_UDEV")
                with self.assertRaisesRegex(RuntimeError, "ABSENT"):
                    disk_identity.resolve_disk("UNKNOWN")


class CredentialPolicyTests(unittest.TestCase):
    def test_retained_and_rotated_credentials_use_explicit_sources_without_internal_rbac(self):
        with tempfile.TemporaryDirectory() as directory:
            site = FakeSite(Path(directory), 1)
            row = site.rows[0]
            device = {
                "credential_source": "managed",
                "serial": row["chassis_serial_number"],
                "expected_id": row["id"],
                "bmc_mac": row["bmc_mac_address"],
                "bmc_ip": row["bmc_ip_address"],
                "bmc_retain_credentials": True,
            }
            self.assertEqual(site.credentials(device)["password"], "TEST_SECRET")
            self.assertEqual(site.writes, [])
            device["bmc_retain_credentials"] = False
            with self.assertRaisesRegex(RuntimeError, "轮换"):
                site.credentials(device)
            (site.secrets / "site-bmc.json").write_text(
                json.dumps({"username": "site-ops", "password": "ROTATED_TEST_SECRET"})
            )
            site.config["bmc_site_credential_file"] = "site-bmc.json"
            self.assertEqual(site.credentials(device)["username"], "site-ops")
            self.assertEqual(site.credentials(device)["password"], "ROTATED_TEST_SECRET")
            self.assertEqual(site.writes, [])

    def test_missing_post_rotation_credentials_blocks_admission_before_bmc_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            site = FakeSite(Path(directory), 1)
            site.rows[0]["bmc_retain_credentials"] = False
            site.machines = []
            store = Store(site.data / "db.sqlite")
            onboarding = Onboarding(site, store)
            result = onboarding.admission_preview({"serials": ["NEW-01"]}, "owner")
            self.assertFalse(result["passed"])
            self.assertIn("凭据", result["checks"][0]["detail"])
            self.assertEqual(site.writes, [])

    def test_configured_but_missing_or_incomplete_site_credentials_block_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            site = FakeSite(Path(directory), 1)
            site.rows[0]["bmc_retain_credentials"] = False
            site.machines = []
            site.config["bmc_site_credential_file"] = "missing-site-bmc.json"
            onboarding = Onboarding(site, Store(site.data / "db.sqlite"))
            for content in [None, {"username": "ops"}]:
                if content is not None:
                    (site.secrets / "missing-site-bmc.json").write_text(json.dumps(content))
                result = onboarding.admission_preview({"serials": ["NEW-01"]}, "owner")
                self.assertFalse(result["passed"])
                self.assertIn("凭据", result["checks"][0]["detail"])
                self.assertEqual(site.writes, [])


class MaterialFailureTests(unittest.TestCase):
    def test_unavailable_material_is_a_per_device_preflight_block(self):
        with tempfile.TemporaryDirectory() as directory:
            site = FakeSite(Path(directory), 1)
            site.config["materials"] = [
                {"name": "ISO", "url": "http://192.0.2.50/install.iso", "size": 123}
            ]
            onboarding = Onboarding(site, Store(site.data / "db.sqlite"))
            with (
                patch.object(
                    site, "check_materials", side_effect=lambda: Adapter.check_materials(site)
                ),
                patch(
                    "pxeye.services.execution.urllib.request.OpenerDirector.open",
                    side_effect=OSError("unreachable"),
                ),
            ):
                result = onboarding.preflight("NEW-01", "nico-01", "ubuntu-generic", "SCOUT-DISK-0")
            self.assertFalse(result["passed"])
            self.assertIn("安装材料无法访问", result["checks"][-1]["detail"])
            self.assertEqual(site.writes, [])
