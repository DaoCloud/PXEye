"""Meaningful defaults/override, immutable version and rendered-data regressions."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from pxeye.services.profiles import InstallProfiles, OVERRIDABLE
from pxeye.services.device_config import DeviceConfig
from pxeye.services.device_plans import DevicePlans, EXECUTING
from pxeye.services.resources import Resources
from pxeye.common import digest
from tests.unit.test_first_install import FakeSite
from tests.unit.test_management import ManagementSite
from pxeye.persistence.store import Store


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.site = ManagementSite(self.root, number=1)
        self.store = Store(self.site.data / "console.sqlite3")
        self.resources = Resources(self.site, self.store)
        fixture = __import__("test_management").ManagementTests()
        fixture.site, fixture.os = self.site, __import__("os_library").OSLibrary(self.site)
        record = fixture.prepared()
        fixture.os.register({"id": record["id"], "revision": digest(record)})
        fixture.os.activate({"id": record["id"], "active": True})
        self.os_id = record["id"]
        self.library = InstallProfiles(self.site)
        self.base = self.library.rows()[0]
        self.site.writes.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def draft(self, **settings):
        return self.library.save(
            {
                "id": "",
                "revision": "",
                "source_id": self.base["id"],
                "config": {
                    "name": "通用方案",
                    "os_id": self.os_id,
                    "login_mode": "password",
                    "password": "TEST_PASSWORD_ONLY",
                    **settings,
                },
            }
        )

    def published(self, **settings):
        p = self.draft(**settings)
        return self.library.action({"id": p["id"], "revision": p["revision"]}, "publish")

    def intent(self, p, **overrides):
        return {
            "profile_id": p["id"],
            "override_modes": dict.fromkeys(OVERRIDABLE, "inherit"),
            **overrides,
        }

    def test_save_and_publish_have_no_hardware_side_effects(self):
        p = self.published(timezone="Asia/Shanghai", ntp=["192.0.2.77"])
        self.assertEqual(self.site.writes, [])
        self.assertNotIn("TEST_PASSWORD_ONLY", json.dumps(p))
        self.assertNotIn("login_ref", json.dumps(p))
        self.assertTrue(p["password_present"])
        self.assertTrue(p["validation"]["passed"])

    def test_inherited_credentials_are_used_and_not_public(self):
        p = self.published()
        e = self.library.resolve(self.intent(p), require=True)
        self.assertEqual(e["values"]["username"], "ops")
        self.assertEqual(e["values"]["login_mode"], "password")
        self.assertTrue(e["values"]["login_ref"])
        self.assertEqual(e["sources"]["username"], "方案 v1")

    def test_username_override_requires_matching_password(self):
        p = self.published()
        i = self.intent(p, username="admin")
        i["override_modes"]["username"] = "override"
        with self.assertRaisesRegex(ValueError, "用户名"):
            self.library.resolve(i, require=True)

    def test_explicit_override_and_restore_default(self):
        p = self.published()
        i = self.intent(
            p, username="admin", login_mode="key", authorized_keys=["ssh-ed25519 VEVTVA== admin"]
        )
        i["override_modes"].update(
            username="override", login_mode="override", authorized_keys="override"
        )
        self.assertEqual(self.library.resolve(i, require=True)["values"]["username"], "admin")
        i["override_modes"]["username"] = "inherit"
        self.assertEqual(self.library.resolve(i, require=True)["values"]["username"], "ops")

    def test_locked_override_conflict_is_visible_and_blocks_execution(self):
        allow = dict.fromkeys(OVERRIDABLE, True)
        allow["username"] = False
        p = self.published(allow_overrides=allow)
        i = self.intent(p, username="admin")
        i["override_modes"]["username"] = "override"
        self.assertTrue(self.library.resolve(i)["problems"])
        with self.assertRaisesRegex(ValueError, "不允许"):
            self.library.resolve(i, require=True)

    def test_published_version_cannot_be_edited(self):
        p = self.published()
        with self.assertRaisesRegex(ValueError, "草稿"):
            self.library.save(
                {
                    "id": p["id"],
                    "revision": p["revision"],
                    "source_id": "",
                    "config": {"username": "ops2"},
                }
            )

    def test_new_version_leaves_old_defaults_unchanged(self):
        p = self.published()
        v2 = self.library.new_version({"id": p["id"], "revision": p["revision"]})
        v2 = self.library.save(
            {
                "id": v2["id"],
                "revision": v2["revision"],
                "source_id": "",
                "config": {"username": "newops", "password": "NEW_PASSWORD_ONLY"},
            }
        )
        self.library.action({"id": v2["id"], "revision": v2["revision"]}, "publish")
        self.assertEqual(
            self.library.resolve(self.intent(p), require=True)["values"]["username"], "ops"
        )
        self.assertEqual(v2["version"], 2)

    def test_disable_blocks_new_runs_but_retains_version(self):
        p = self.published()
        self.library.action({"id": p["id"], "revision": p["revision"], "active": False}, "active")
        with self.assertRaisesRegex(ValueError, "停用"):
            self.library.resolve(self.intent(p), require=True)
        token = EXECUTING.set({"TEST": "frozen"})
        try:
            self.assertEqual(
                self.library.resolve(self.intent(p), require=True)["values"]["username"], "ops"
            )
        finally:
            EXECUTING.reset(token)

    def test_stale_draft_update_does_not_overwrite(self):
        p = self.draft()
        self.library.save(
            {"id": p["id"], "revision": p["revision"], "source_id": "", "config": {"name": "new"}}
        )
        with self.assertRaises(ValueError):
            self.library.save(
                {
                    "id": p["id"],
                    "revision": p["revision"],
                    "source_id": "",
                    "config": {"name": "stale"},
                }
            )

    def test_missing_default_password_allowed_when_device_can_provide(self):
        p = self.draft(password="", credential_action="clear")
        self.assertTrue(self.library.check(p["id"])["passed"])
        p = self.library.action({"id": p["id"], "revision": p["revision"]}, "publish")
        with self.assertRaisesRegex(ValueError, "登录"):
            self.library.resolve(self.intent(p), require=True)

    def test_locked_missing_password_cannot_publish(self):
        allow = dict.fromkeys(OVERRIDABLE, True)
        allow["credential"] = False
        p = self.draft(password="", credential_action="clear", allow_overrides=allow)
        self.assertFalse(self.library.check(p["id"])["passed"])

    def test_os_installer_mismatch_rejected(self):
        p = self.draft()
        with patch(
            "pxeye.services.os_library.OSLibrary.usable", return_value={"installer": "kickstart"}
        ):
            with self.assertRaisesRegex(ValueError, "不兼容"):
                self.library.compatible_os(self.os_id, self.library.get(p["id"], executable=False))

    def test_published_os_drift_blocks_execution(self):
        p = self.published()
        from pxeye.services.os_library import OSLibrary

        lib = OSLibrary(self.site)
        row = lib.read(self.os_id)
        row["os_release"] = "CHANGED"
        lib.save(row)
        with self.assertRaisesRegex(ValueError, "OS已变化"):
            self.library.resolve(self.intent(p), require=True)

    def test_blank_password_keeps_immutable_secret(self):
        p = self.published()
        original = self.library.get(p["id"])["settings"]["login_ref"]
        v2 = self.library.new_version({"id": p["id"], "revision": p["revision"]})
        self.library.save(
            {
                "id": v2["id"],
                "revision": v2["revision"],
                "source_id": "",
                "config": {"password": ""},
            }
        )
        self.assertEqual(
            self.library.get(v2["id"], executable=False)["settings"]["login_ref"], original
        )

    def test_template_and_settings_are_consistent_and_deterministic(self):
        p = self.published(
            timezone="Asia/Shanghai",
            ntp=["192.0.2.77"],
            packages=["curl"],
            apt={
                "geoip": False,
                "primary": [{"arches": ["default"], "uri": "https://mirror.example/ubuntu"}],
            },
        )
        row = self.library.get(p["id"])
        one = self.library.template(row)
        self.assertEqual(one, self.library.template(row))
        ai = yaml.safe_load(one["user_data"])["autoinstall"]
        self.assertEqual(ai["user-data"]["timezone"], "Asia/Shanghai")
        self.assertEqual(ai["timezone"], "Asia/Shanghai")
        self.assertEqual(ai["user-data"]["ntp"]["servers"], ["192.0.2.77"])
        self.assertIn("curl", ai["packages"])
        self.assertIn("sudo", ai["packages"])
        self.assertEqual(ai["apt"]["primary"][0]["uri"], "https://mirror.example/ubuntu")
        self.assertFalse(one["run_provisioning_instructions_on_every_boot"])

    def test_rendered_data_uses_real_disk_mac_address_and_profile_defaults(self):
        p = self.published()
        from pxeye.services.onboarding import Onboarding

        self.site.rows = copy.deepcopy(self.site.original_rows)
        self.site.machines = copy.deepcopy(self.site.original_machines)
        # The discovery fixture carries BMC+host interfaces; first install selects host.
        row = self.site.rows[0]
        serial = row["chassis_serial_number"]
        row["interfaces"] = [
            {
                "role": "host",
                "primary": True,
                "mac_address": self.site.machines[0]["status"]["discovery_info"][
                    "network_interfaces"
                ][0]["mac_address"],
                "ip_allocation": "fixed",
                "fixed_ip": "192.0.2.10",
                "fixed_mask": "255.255.255.0",
                "fixed_gateway": "192.0.2.1",
            }
        ]
        self.site.links = [
            {
                "id": {"value": "host-interface"},
                "segmentId": self.site.segment["id"],
                "machineId": {"id": self.site.machines[0]["id"]},
                "macAddress": row["interfaces"][0]["mac_address"],
                "primaryInterface": True,
                "address": ["192.0.2.10"],
            },
            {
                "id": {"value": "bmc-interface"},
                "machineId": {"id": self.site.machines[0]["id"]},
                "macAddress": row["bmc_mac_address"],
                "isBmc": True,
            },
        ]
        plans = DevicePlans(self.site, self.resources)
        plans.seed(self.site.rows)
        saved = plans.get(serial)
        plans.save(
            {
                "id": row["id"],
                "revision": digest(saved),
                "machine": row,
                "intent": self.intent(p, hostname="installed-by-profile"),
            }
        )
        plan, device, _ = Onboarding(self.site, self.store, self.resources).plan(
            serial, p["id"], "SCOUT-DISK-0"
        )
        plan["dns_servers"] = ["192.0.2.99"]
        device["instance_id"] = "test-instance"
        frozen = copy.deepcopy(plan)
        data = self.site.render(
            device,
            {
                "id": "TEST",
                "hostname": "installed-by-profile",
                "actor": "test",
                "installation_plan": plan,
            },
        )
        self.assertEqual(plan, frozen)
        ai = yaml.safe_load(data["user_data"])["autoinstall"]
        self.assertEqual(ai["identity"]["username"], "ops")
        self.assertTrue(ai["identity"]["password"].startswith("$6$"))
        self.assertEqual(ai["identity"]["hostname"], "installed-by-profile")
        nic = next(iter(ai["network"]["ethernets"].values()))
        self.assertEqual(nic["nameservers"]["addresses"], ["192.0.2.99"])
        self.assertEqual(nic["addresses"], ["192.0.2.10/24"])
        self.assertNotIn("pending", data["user_data"])
        self.assertIn("SCOUT-DISK-0", data["user_data"])
        self.assertEqual(plan["effective_sources"]["username"], "方案 v1")

    def test_task_form_selection_saves_legacy_intent_without_native_write(self):
        p = self.published()
        self.site.rows = copy.deepcopy(self.site.original_rows)
        plans = DevicePlans(self.site, self.resources)
        plans.seed(self.site.rows)
        serial = self.site.rows[0]["chassis_serial_number"]
        record = plans.get(serial)
        record["intent"] = self.intent(p, serial=serial)
        with plans.store.db() as db:
            plans.put(db, serial, record)
        revision = digest(record)
        plans.installation_selection(serial, "saved-task-host", p["id"], "SCOUT-DISK-0", revision)
        current = plans.get(serial)
        self.assertEqual(current["intent"]["hostname"], "saved-task-host")
        self.assertEqual(current["intent"]["disk_serial"], "SCOUT-DISK-0")
        self.assertEqual(self.site.writes, [])
        with self.assertRaisesRegex(ValueError, "规划已变化"):
            plans.installation_selection(serial, "stale", p["id"], "SCOUT-DISK-0", revision)

    def test_default_network_dns_comes_from_site_network_not_profile(self):
        self.site.config["network"] = {"management": {"网段": "192.0.2.0/24", "DNS": "192.0.2.99"}}
        n = next(n for n in self.resources.networks() if n["segment_type"] == "HOST_INBAND")
        self.assertEqual(n["services"]["dns_servers"], ["192.0.2.99"])
        self.assertEqual(n["services"]["source"], "站点网络默认")

    def test_saved_disk_cannot_be_silently_ignored(self):
        p = self.published()
        self.site.rows = copy.deepcopy(self.site.original_rows)
        plans = DevicePlans(self.site, self.resources)
        plans.seed(self.site.rows)
        serial = self.site.rows[0]["chassis_serial_number"]
        record = plans.get(serial)
        record["intent"] = self.intent(p, disk_serial="OTHER-DISK")
        with plans.store.db() as db:
            plans.put(db, serial, record)
        device = {
            "serial": serial,
            "first_install_profile": p["id"],
            "disk_serial": "ORIGINAL-DISK",
        }
        with self.assertRaisesRegex(ValueError, "系统盘与设备规划不一致"):
            DeviceConfig(self.site, self.resources).bind({}, device)
        self.assertEqual(self.site.writes, [])

    def test_arbitrary_script_and_invalid_packages_rejected(self):
        with self.assertRaises(ValueError):
            self.draft(late_commands=["touch /tmp/x"])
        with self.assertRaises(ValueError):
            self.draft(packages=["curl;reboot"])

    def test_delete_only_unreferenced_draft(self):
        p = self.draft()
        self.assertEqual(
            self.library.action({"id": p["id"], "revision": p["revision"]}, "delete")["status"],
            "deleted",
        )
        p = self.published()
        with self.assertRaises(ValueError):
            self.library.action({"id": p["id"], "revision": p["revision"]}, "delete")

    def test_network_dns_saves_without_native_change(self):
        net = next(n for n in self.resources.networks() if n["segment_type"] == "HOST_INBAND")
        result = self.resources.save_network_services(
            {
                "id": net["id"],
                "revision": net["services"]["revision"],
                "dns_servers": ["192.0.2.99"],
            }
        )
        self.assertEqual(result["status"], "saved")
        self.assertEqual(self.site.writes, [])
        self.assertEqual(
            next(n for n in self.resources.networks() if n["id"] == net["id"])["services"][
                "dns_servers"
            ],
            ["192.0.2.99"],
        )
        with self.assertRaises(ValueError):
            self.resources.save_network_services(
                {
                    "id": net["id"],
                    "revision": net["services"]["revision"],
                    "dns_servers": ["192.0.2.100"],
                }
            )


if __name__ == "__main__":
    unittest.main()
