"""New OS/candidate/intent paths with real persistence and fault injection."""

import copy
import io
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import yaml

from pxeye.services.device_config import DeviceConfig
from pxeye.services.discovery import Discovery
from pxeye.services.os_library import OSLibrary
from pxeye.services.onboarding import Onboarding
from pxeye.services.resources import Resources
from pxeye.common import digest
from pxeye.domain.machines import machine_from_rpc
from pxeye.persistence.store import Store
from tests.unit.test_first_install import FakeSite


class ManagementSite(FakeSite):
    def __init__(self, root, number=2):
        super().__init__(root, number)
        self.original_rows = copy.deepcopy(self.rows)
        self.original_machines = copy.deepcopy(self.machines)
        self.rows = []
        self.machines = []
        self.native_os = {}
        self.oob = copy.deepcopy(self.segment)
        self.oob["id"] = {"value": str(uuid.uuid4())}
        self.oob["config"]["segmentType"] = "UNDERLAY"
        self.oob["config"]["prefixes"] = [{"prefix": "198.51.100.0/24", "gateway": "198.51.100.1"}]
        self.links = [
            {
                "id": {"value": str(uuid.uuid4())},
                "segmentId": self.oob["id"],
                "macAddress": r["bmc_mac_address"],
                "address": [r["bmc_ip_address"]],
                "lastDhcp": "2026-11-05T00:00:00Z",
            }
            for r in self.original_rows
        ]
        self.config["network_allocation_strategies"] = {
            self.oob["id"]["value"]: "DYNAMIC",
            self.segment["id"]["value"]: "DYNAMIC",
        }
        self.config["os_library"] = {
            "directory": str(root / "media"),
            "public_base_url": "http://pxe.test/os",
        }
        self.switches = []
        self.shelves = []
        self.endpoints = []

    def rpc(self, method, body):
        if method == "FindOperatingSystemIds":
            return {"ids": [{"value": k} for k in self.native_os]}
        if method == "FindOperatingSystemsByIds":
            return {"operatingSystems": [self.native_os[x["value"]] for x in body["ids"]]}
        if method == "CreateOperatingSystem":
            self.writes.append((method, copy.deepcopy(body)))
            self.native_os[body["id"]["value"]] = {
                "id": body["id"],
                "name": body["name"],
                "isActive": body["is_active"],
                "ipxeTemplateId": body["ipxe_template_id"],
                "ipxeTemplateParameters": body["ipxe_template_parameters"],
                "ipxeTemplateArtifacts": body["ipxe_template_artifacts"],
            }
            return self.native_os[body["id"]["value"]]
        if method == "UpdateOperatingSystem":
            self.native_os[body["id"]["value"]]["isActive"] = body["is_active"]
            return self.native_os[body["id"]["value"]]
        if method == "GetOperatingSystem":
            return self.native_os[body["value"]]
        if method == "FindExploredEndpointIds":
            return {"endpointIds": [e["address"] for e in self.endpoints]}
        if method == "FindExploredEndpointsByIds":
            return {"endpoints": copy.deepcopy(self.endpoints)}
        if method == "GetAllExpectedSwitches":
            return {"expectedSwitches": copy.deepcopy(self.switches)}
        if method == "GetAllExpectedPowerShelves":
            return {"expectedPowerShelves": copy.deepcopy(self.shelves)}
        if method == "FindNetworkSegmentIds":
            return {"networkSegmentsIds": [self.segment["id"], self.oob["id"]]}
        if method == "FindNetworkSegmentsByIds":
            return {
                "networkSegments": [
                    copy.deepcopy(n)
                    for n in [self.segment, self.oob]
                    if n["id"] in body["network_segments_ids"]
                ]
            }
        if method == "CreateExpectedMachines":
            self.rows.extend(
                machine_from_rpc(r) for r in body["expected_machines"]["expected_machines"]
            )
            self.writes.append((method, copy.deepcopy(body)))
            return {
                "results": [
                    {"success": True} for r in body["expected_machines"]["expected_machines"]
                ]
            }
        return super().rpc(method, body)

    def redfish_read(self, ip, path, credential):
        if credential["password"] != "BMC_TEST_PASSWORD":
            raise RuntimeError("认证失败")
        row = next(r for r in self.original_rows if r["bmc_ip_address"] == ip)
        if path == "/redfish/v1/Systems":
            return {"Members": [{"@odata.id": "/redfish/v1/Systems/1"}]}
        if path == "/redfish/v1/Systems/1":
            return {
                "SerialNumber": row["chassis_serial_number"],
                "Model": "TEST",
                "EthernetInterfaces": {"@odata.id": "/redfish/v1/Systems/1/EthernetInterfaces"},
            }
        if path == "/redfish/v1/Managers":
            return {"Members": [{"@odata.id": "/redfish/v1/Managers/1"}]}
        if path == "/redfish/v1/Managers/1":
            return {
                "EthernetInterfaces": {"@odata.id": "/redfish/v1/Managers/1/EthernetInterfaces"}
            }
        if path.endswith("EthernetInterfaces"):
            return {"Members": [{"@odata.id": path + "/1"}]}
        return {
            "MACAddress": row["bmc_mac_address"]
            if "/Managers/" in path
            else row["interfaces"][0]["mac_address"]
        }


class ManagementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.site = ManagementSite(self.root)
        self.store = Store(self.site.data / "console.sqlite3")
        self.resources = Resources(self.site, self.store)
        self.discovery = Discovery(
            self.site, self.resources, Onboarding(self.site, self.store, self.resources)
        )
        self.os = OSLibrary(self.site)

    def tearDown(self):
        self.tmp.cleanup()

    def upload(self):
        row = self.os.begin(
            {"name": "Ubuntu test", "filename": "test.iso", "size": 32768, "sha256": ""}, "owner"
        )
        self.os.chunk(row["id"], "owner", 0, io.BytesIO(b"0" * 32768), 32768)
        return self.os.read(row["id"])

    def prepared(self):
        row = self.upload()
        row.update(
            status="prepared",
            architecture="x86_64",
            os_release="Ubuntu Server amd64",
            installer="ubuntu-server",
            materials=[
                {"name": n, "url": "http://pxe.test/" + n, "size": 100, "sha256": "a" * 64}
                for n in ["iso", "kernel", "initrd"]
            ],
        )
        self.os.save(row)
        return row

    def test_chunks_bind_offset_and_owner(self):
        row = self.upload()
        with self.assertRaises(ValueError):
            self.os.chunk(row["id"], "other", 32768, io.BytesIO(b"x"), 1)
        with self.assertRaises(ValueError):
            self.os.chunk(row["id"], "owner", 0, io.BytesIO(b"x"), 1)
        self.assertEqual((self.os.root / row["id"] / "install.iso").stat().st_size, 32768)

    def test_interrupted_chunk_can_resume(self):
        row = self.os.begin(
            {"name": "test", "filename": "test.iso", "size": 32768, "sha256": ""}, "owner"
        )
        with self.assertRaises(ValueError):
            self.os.chunk(row["id"], "owner", 0, io.BytesIO(b"partial"), 100)
        self.assertEqual(self.os.read(row["id"])["received"], 0)
        self.os.chunk(row["id"], "owner", 0, io.BytesIO(b"x" * 32768), 32768)
        self.assertEqual(self.os.read(row["id"])["received"], 32768)

    def test_checksum_mismatch_never_registers(self):
        row = self.upload()
        row["expected_sha256"] = "f" * 64
        self.os.extract(row)
        self.assertEqual(self.os.read(row["id"])["status"], "failed")
        self.assertEqual(self.site.writes, [])

    def test_register_inactive_then_enable(self):
        row = self.prepared()
        self.os.register({"id": row["id"], "revision": digest(row)})
        with self.assertRaises(ValueError):
            self.os.usable(row["id"], "x86_64")
        self.os.activate({"id": row["id"], "active": True})
        self.assertEqual(self.os.usable(row["id"], "x86_64")["id"], row["id"])
        with self.assertRaises(ValueError):
            self.os.usable(row["id"], "aarch64")
        request = self.site.writes[0][1]
        self.assertNotIn("user_data", request)
        self.assertIn("ds=nocloud-net", request["ipxe_template_parameters"][0]["value"])

    def test_stale_or_replayed_os_registration_blocked(self):
        row = self.prepared()
        with self.assertRaises(ValueError):
            self.os.register({"id": row["id"], "revision": "old"})
        self.os.register({"id": row["id"], "revision": digest(row)})
        with self.assertRaises(ValueError):
            self.os.register({"id": row["id"], "revision": digest(row)})
        self.assertEqual(len(self.site.writes), 1)

    def test_uncertain_registration_does_not_replay(self):
        row = self.prepared()
        with patch.object(self.site, "rpc", side_effect=RuntimeError("timeout")):
            with self.assertRaises(RuntimeError):
                self.os.register({"id": row["id"], "revision": digest(row)})
        self.assertEqual(self.os.read(row["id"])["status"], "needs_attention")

    def test_unknown_candidates_do_not_require_csv_or_write_core(self):
        rows = self.discovery.candidates()["candidates"]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(not c["registered"] and c["source"] == "dhcp" for c in rows))
        self.assertEqual(self.site.writes, [])

    def test_host_interface_is_not_bmc_candidate(self):
        self.site.links[0]["segmentId"] = self.site.segment["id"]
        self.assertEqual(len(self.discovery.candidates()["candidates"]), 1)

    def test_core_anonymous_data_lease_can_be_authenticated_without_declaration(self):
        for link in self.site.links:
            link.update(interfaceType="INTERFACE_TYPE_DATA", isBmc=False)
        self.assertEqual(len(self.discovery.candidates()["candidates"]), 2)
        self.authenticate()
        self.assertTrue(all(c["authenticated"] for c in self.discovery.candidates()["candidates"]))
        self.assertEqual(self.site.rows, [])
        self.assertEqual(self.site.writes, [])

    def test_owned_interfaces_never_become_unknown_candidates(self):
        for owner in ("machineId", "attachedDpuMachineId", "switchId", "powerShelfId"):
            for kind in ("INTERFACE_TYPE_DATA", "INTERFACE_TYPE_BMC"):
                with self.subTest(owner=owner, kind=kind):
                    self.site.links[0].update(interfaceType=kind, isBmc=kind.endswith("BMC"))
                    self.site.links[0][owner] = {"id": "existing-owner"}
                    self.assertEqual(len(self.discovery.candidates()["candidates"]), 1)
                    del self.site.links[0][owner]

    def test_declared_non_host_endpoints_are_excluded_before_ownership(self):
        mac = self.site.links[0]["macAddress"]
        cases = [
            ("host", {"interfaces": [{"mac_address": mac, "role": "host"}]}),
            ("dpu_os", {"interfaces": [{"mac_address": mac, "role": "dpu_os"}]}),
            ("dpu_bmc", {"interfaces": [{"mac_address": mac, "role": "dpu_bmc"}]}),
            ("switch_bmc", {"bmcMacAddress": mac}),
            ("switch_nvos", {"nvosInterfaces": [{"macAddress": mac}]}),
            ("shelf_bmc", {"bmcMacAddress": mac}),
        ]
        for role, declaration in cases:
            with self.subTest(role=role):
                self.site.rows = []
                self.site.switches = []
                self.site.shelves = []
                if role in ("host", "dpu_os", "dpu_bmc"):
                    self.site.rows = [self.site.original_rows[0] | declaration]
                elif role == "shelf_bmc":
                    self.site.shelves = [declaration]
                else:
                    self.site.switches = [declaration]
                self.assertEqual(len(self.discovery.candidates()["candidates"]), 1)

    def test_system_network_and_non_bmc_report_are_excluded(self):
        self.site.oob["metadata"]["name"] = "static-assignments"
        self.assertEqual(self.discovery.candidates()["candidates"], [])
        self.site.oob["metadata"]["name"] = "dedicated-bmc"
        self.site.endpoints = [
            {"address": self.site.links[0]["address"][0], "report": {"endpointType": "Switch"}}
        ]
        self.assertEqual(len(self.discovery.candidates()["candidates"]), 1)

    def authenticate(self):
        ids = [r["id"] for r in self.discovery.candidates()["candidates"]]
        result = self.discovery.authenticate(
            {"ids": ids, "username": "ops", "password": "BMC_TEST_PASSWORD"}, "owner"
        )
        self.assertTrue(all(r["passed"] for r in result["results"]))
        return ids

    def test_authentication_is_read_only_and_redacted(self):
        self.authenticate()
        rows = self.discovery.candidates()["candidates"]
        self.assertTrue(all(r["authenticated"] for r in rows))
        self.assertNotIn("BMC_TEST_PASSWORD", json.dumps(rows))
        self.assertEqual(self.site.writes, [])

    def test_authentication_failure_stays_per_candidate(self):
        ids = [r["id"] for r in self.discovery.candidates()["candidates"]]
        result = self.discovery.authenticate(
            {"ids": ids, "username": "ops", "password": "bad"}, "owner"
        )
        self.assertFalse(any(r["passed"] for r in result["results"]))
        self.assertFalse(any(r["authenticated"] for r in self.discovery.candidates()["candidates"]))

    def test_dhcp_observation_change_invalidates_authentication(self):
        self.authenticate()
        self.site.links[0]["lastDhcp"] = "2026-11-05T01:00:00Z"
        self.assertFalse(self.discovery.candidates()["candidates"][0]["authenticated"])

    def test_unknown_selection_cannot_inject_address(self):
        with self.assertRaises(ValueError):
            self.discovery.authenticate(
                {"ids": ["injected"], "username": "ops", "password": "BMC_TEST_PASSWORD"}, "owner"
            )
        self.assertEqual(self.site.writes, [])

    def test_candidate_registration_uses_csv_pipeline_without_admission(self):
        ids = self.authenticate()
        body = {"ids": ids, "confirm_registration": True}
        result = self.discovery.enroll(body, "owner", "test")
        self.assertEqual(result["status"], "registered")
        self.assertEqual(len(self.site.rows), 2)
        self.assertTrue(all(r["default_pause_ingestion_and_poweron"] for r in self.site.rows))
        self.assertTrue(
            all(not any(n.get("primary") for n in r["interfaces"]) for r in self.site.rows)
        )
        with self.assertRaises(ValueError):
            self.discovery.enroll(body, "owner", "test")
        self.assertEqual(sum(m == "AllowIngestionAndPowerOn" for m, b in self.site.writes), 0)

    def test_registration_does_not_require_scout_network(self):
        ids = self.authenticate()
        self.site.config["network_allocation_strategies"][self.site.segment["id"]["value"]] = (
            "RESERVED"
        )
        self.assertEqual(
            self.discovery.enroll({"ids": ids, "confirm_registration": True}, "owner", "test")[
                "status"
            ],
            "registered",
        )
        self.assertFalse(any(m == "AllowIngestionAndPowerOn" for m, b in self.site.writes))

    def test_registration_accepts_core_inferred_bmc_policy(self):
        ids = self.authenticate()
        original = self.site.rpc

        def rpc(method, body):
            result = original(method, body)
            if method == "CreateExpectedMachines":
                for row in self.site.rows:
                    for nic in row["interfaces"]:
                        if nic["role"] == "host_bmc":
                            nic.pop("ip_allocation")
            return result

        self.site.rpc = rpc
        result = self.discovery.enroll({"ids": ids, "confirm_registration": True}, "owner", "test")
        self.assertEqual(result["status"], "registered")
        self.assertEqual(len(self.site.rows), 2)
        self.assertEqual([method for method, body in self.site.writes], ["CreateExpectedMachines"])
        self.assertTrue(all(row["default_pause_ingestion_and_poweron"] for row in self.site.rows))

    def test_password_intent_stores_private_ref_and_renders_account(self):
        self.site.rows = copy.deepcopy(self.site.original_rows)
        config = DeviceConfig(self.site, self.resources)
        body = {
            "serial": self.site.rows[0]["chassis_serial_number"],
            "revision": digest({}),
            "intent": {
                "profile_id": "ubuntu-generic",
                "username": "newops",
                "login_mode": "password",
                "password": "OS_TEST_PASSWORD",
                "hostname": "nico-test",
                "network_bindings": {},
            },
        }
        result = config.save(body)
        self.assertNotIn("OS_TEST_PASSWORD", json.dumps(result))
        self.assertNotIn("login_ref", result)
        row = config.get(body["serial"])
        cred = self.site.data / "config/logins" / (row["login_ref"] + ".json")
        self.assertEqual(cred.stat().st_mode & 0o777, 0o600)
        device = {
            "serial": body["serial"],
            "first_install_profile": "ubuntu-generic",
            "architecture": "x86_64",
            "ssh_user": "ops",
            "baseline_file": "generic.json",
            "disk_serial": "SCOUT-DISK-0",
            "disk_wwn": None,
            "boot_mac": self.site.rows[0]["interfaces"][0]["mac_address"],
            "management_ip": "192.0.2.10",
            "prefixlen": 24,
            "gateway": "192.0.2.1",
            "profile": "ubuntu-generic",
            "instance_id": "test",
        }
        plan = {}
        config.bind(plan, device)
        rendered = self.site.render(
            device,
            {"id": "TEST", "hostname": "nico-test", "actor": "test", "installation_plan": {}},
        )
        ai = yaml.safe_load(rendered["user_data"])["autoinstall"]
        self.assertEqual(ai["identity"]["username"], "newops")
        self.assertTrue(ai["ssh"]["allow-pw"])
        self.assertTrue(ai["identity"]["password"].startswith("$6$"))
        self.assertNotIn("OS_TEST_PASSWORD", rendered["user_data"])
        self.assertEqual(device["ssh_user"], "newops")

    def test_subnet_reference_rejects_wrong_role(self):
        self.site.rows = copy.deepcopy(self.site.original_rows)
        config = DeviceConfig(self.site, self.resources)
        with self.assertRaises(ValueError):
            config.save(
                {
                    "serial": self.site.rows[0]["chassis_serial_number"],
                    "revision": digest({}),
                    "intent": {
                        "profile_id": "ubuntu-generic",
                        "username": "ops",
                        "login_mode": "key",
                        "network_bindings": {
                            self.site.rows[0]["interfaces"][0]["mac_address"]: self.site.oob["id"][
                                "value"
                            ]
                        },
                    },
                }
            )

    def test_cancel_stopped_unregistered_upload_removes_materials(self):
        row = self.upload()
        self.os.cancel({"id": row["id"], "revision": digest(row)}, "owner")
        self.assertFalse((self.os.root / row["id"]).exists())
        with self.assertRaises(ValueError):
            self.os.read(row["id"])

    def test_cancel_registered_os_is_blocked(self):
        row = self.prepared()
        self.os.register({"id": row["id"], "revision": digest(row)})
        with self.assertRaises(ValueError):
            self.os.cancel({"id": row["id"], "revision": digest(self.os.read(row["id"]))}, "owner")
        self.assertTrue((self.os.root / row["id"]).exists())

    def test_uncertain_registration_reconciles_absence_without_writing(self):
        row = self.prepared()
        row.update(status="needs_attention", pending_operation="register")
        self.os.save(row)
        self.os.recover({"id": row["id"], "revision": digest(row)}, "owner")
        self.assertEqual(self.os.read(row["id"])["status"], "prepared")
        self.assertEqual(self.site.writes, [])

    def test_network_reference_saves_without_os_account(self):
        self.site.rows = copy.deepcopy(self.site.original_rows)
        config = DeviceConfig(self.site, self.resources)
        serial = self.site.rows[0]["chassis_serial_number"]
        mac = self.site.rows[0]["interfaces"][0]["mac_address"]
        result = config.save(
            {
                "serial": serial,
                "revision": "",
                "intent": {"network_bindings": {mac: self.site.segment["id"]["value"]}},
            }
        )
        self.assertEqual(result["network_bindings"][mac], self.site.segment["id"]["value"])
        self.assertFalse(result["password_present"])

    def test_validation_does_not_write_password_or_intent(self):
        self.site.rows = copy.deepcopy(self.site.original_rows)
        config = DeviceConfig(self.site, self.resources)
        body = {
            "serial": self.site.rows[0]["chassis_serial_number"],
            "revision": "",
            "intent": {
                "profile_id": "ubuntu-generic",
                "username": "ops",
                "password": "OS_TEST_PASSWORD",
            },
        }
        self.assertTrue(config.save(body, validate_only=True)["passed"])
        self.assertEqual(config.get(body["serial"]), {})
        self.assertFalse((self.site.data / "config/logins").exists())

    def test_invalid_subnet_never_leaves_orphan_password(self):
        self.site.rows = copy.deepcopy(self.site.original_rows)
        config = DeviceConfig(self.site, self.resources)
        with self.assertRaises(ValueError):
            config.save(
                {
                    "serial": self.site.rows[0]["chassis_serial_number"],
                    "revision": "",
                    "intent": {
                        "profile_id": "ubuntu-generic",
                        "username": "ops",
                        "password": "OS_TEST_PASSWORD",
                        "network_bindings": {"00:11:22:33:44:55": "unknown"},
                    },
                }
            )
        self.assertFalse((self.site.data / "config/logins").exists())

    def test_saved_subnet_rechecked_when_declaration_changes(self):
        self.site.rows = copy.deepcopy(self.site.original_rows)
        config = DeviceConfig(self.site, self.resources)
        serial = self.site.rows[0]["chassis_serial_number"]
        mac = self.site.rows[0]["interfaces"][0]["mac_address"]
        config.save(
            {
                "serial": serial,
                "revision": "",
                "intent": {"network_bindings": {mac: self.site.segment["id"]["value"]}},
            }
        )
        self.site.rows[0]["interfaces"][0]["fixed_ip"] = "203.0.113.2"
        with self.assertRaises(ValueError):
            config.bind({}, {"serial": serial})

    def test_wrong_mask_is_blocked_against_selected_subnet(self):
        self.site.rows = copy.deepcopy(self.site.original_rows)
        config = DeviceConfig(self.site, self.resources)
        nic = self.site.rows[0]["interfaces"][0]
        nic["fixed_mask"] = "255.255.0.0"
        with self.assertRaises(ValueError):
            config.validate_networks(
                {nic["mac_address"]: self.site.segment["id"]["value"]}, self.site.rows[0]
            )

    def test_publish_directory_explicitly_traversable_under_private_umask(self):
        private_umask = os.umask(0o077)
        try:
            row = self.upload()
            folder = self.os.root / row["id"]

            def extract(argv, **kwargs):
                target = Path(argv[-1])
                target.write_text(
                    "Ubuntu Server 24.04 amd64" if target.name == "info.txt" else "fixture"
                )

            with (
                patch("pxeye.services.os_library.subprocess.run", side_effect=extract),
                patch("pxeye.services.os_library.urllib.request.build_opener") as opener,
            ):
                response = opener.return_value.open.return_value.__enter__.return_value
                response.headers.get.side_effect = lambda key, default: str(
                    32768
                    if opener.return_value.open.call_args[0][0].full_url.endswith("install.iso")
                    else 7
                )
                self.os.extract(row)
            self.assertEqual(self.os.read(row["id"])["status"], "registered")
            self.assertEqual(folder.stat().st_mode & 0o777, 0o755)
            for name in ("install.iso", "kernel", "initrd"):
                self.assertEqual((folder / name).stat().st_mode & 0o777, 0o644)
        finally:
            os.umask(private_umask)

    def test_native_os_artifact_drift_blocks_new_task(self):
        row = self.prepared()
        self.os.register({"id": row["id"], "revision": digest(row)})
        self.os.activate({"id": row["id"], "active": True})
        self.site.native_os[row["id"]]["ipxeTemplateArtifacts"][0]["url"] = (
            "http://wrong.example/kernel"
        )
        with self.assertRaises(ValueError):
            self.os.usable(row["id"], "x86_64")


if __name__ == "__main__":
    unittest.main()
