"""Pre-write recovery boundaries and installer kernel-path regression."""

import copy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import call, patch

import yaml

from pxeye.common import sha
from pxeye.installation.executor import (
    Executor,
    prewrite_disk_failure,
    verified_installation_identity,
)
from pxeye.services.onboarding import Onboarding
from pxeye.services.resources import Resources
from pxeye.bootstrap import Application
from pxeye.persistence.store import Store
from tests.unit.test_first_install import FakeSite

FAILURE = "finish: subiquity/apply_autoinstall_config: {'path': '/dev/disk/by-id/nvme-test'} matched no disk\n"


class InstallRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.site = FakeSite(self.root, 1)
        self.store = Store(self.site.data / "console.sqlite3")
        resources = Resources(self.site, self.store)
        check = Onboarding(self.site, self.store, resources).preflight(
            "NEW-01", "nico-new", "ubuntu-generic", "SCOUT-DISK-0"
        )
        self.assertTrue(check["passed"])
        device = check["execution_device"]
        device["instance_id"] = "instance-1"
        task = {
            "id": "UI-retry",
            "mode": "first_install",
            "device": "NEW-01",
            "hostname": "nico-new",
            "actor": "test",
            "status": "needs_attention",
            "events": [],
            "preflight": check,
            "installation_plan": check["installation_plan"],
            "execution_device": device,
            "native_allocation_requests": 1,
            "config_version": "v1",
        }
        config = self.site.render(device, task)
        task["user_data_sha256"] = sha(config["user_data"])
        self.site.instances = [
            {
                "id": device["instance_id"],
                "machine_id": device["machine_id"],
                "config_version": "v1",
                "config": {"os": config},
                "status": {
                    "network": {
                        "interfaces": [
                            {
                                "mac_address": device["boot_mac"],
                                "addresses": [device["management_ip"]],
                                "virtual_function_id": None,
                            }
                        ]
                    }
                },
            }
        ]
        self.site.machines[0]["state"] = "Assigned/Ready"
        folder = self.site.data / "tasks" / task["id"]
        folder.mkdir(parents=True)
        (folder / "console.raw").write_text(FAILURE)
        with self.store.db() as db:
            db.execute(
                "INSERT INTO tasks VALUES (?,?,?,?,?,?)",
                (
                    task["id"],
                    task["device"],
                    task["status"],
                    json.dumps(task),
                    time.time(),
                    "request-retry",
                ),
            )
        self.task, self.folder = task, folder
        self.executor = Executor(self.site, self.store)
        self.app = Application.__new__(Application)
        self.app.store, self.app.executor = self.store, self.executor
        self.app.worker_lock = threading.Lock()

    def tearDown(self):
        self.temp.cleanup()

    def test_delivery_requires_same_mac_address_instance_and_config(self):
        device = self.task["execution_device"]
        proof = self.site.verify_install_delivery(device, self.task)
        self.assertEqual(proof["management_ip"], device["management_ip"])
        original = copy.deepcopy(self.site.instances[0])
        for change in ("address", "mac", "config"):
            with self.subTest(change=change):
                self.site.instances[0] = copy.deepcopy(original)
                instance = self.site.instances[0]
                if change == "address":
                    instance["status"]["network"]["interfaces"][0]["addresses"] = ["192.0.2.99"]
                elif change == "mac":
                    instance["status"]["network"]["interfaces"][0]["mac_address"] = (
                        "00:00:00:00:00:ff"
                    )
                else:
                    instance["config"]["os"]["user_data"] = "{}"
                with self.assertRaises(RuntimeError):
                    self.site.verify_install_delivery(device, self.task)
        self.assertEqual(self.site.writes, [])

    def test_interactive_reinstall_can_retry_only_before_installation(self):
        from pxeye.installation.executor import interactive_installer_failure

        self.task.update(mode="reinstall", native_reinstall_requests=1)
        screen = "\x0f  Network configuration              [ Help ]\n"
        (self.folder / "console.raw").write_text(screen)
        self.assertIsNotNone(interactive_installer_failure(screen))
        self.assertTrue(self.executor.can_retry_install(self.task))
        for text in (
            "Starting systemd-networkd.service - Network Configuration...",
            screen + "start: subiquity/Install/install: \n",
            screen + "start: curtin/partitioning: \n",
            screen + "NICO_UI_HOSTKEY UI-retry ssh-ed25519 TEST\n",
        ):
            with self.subTest(text=text):
                (self.folder / "console.raw").write_text(text)
                self.assertFalse(self.executor.can_retry_install(self.task))

    def test_delivery_failure_stops_retry_before_pxe(self):
        self.site.instances[0]["status"]["network"]["interfaces"][0]["addresses"] = ["192.0.2.99"]
        original_core = self.site.core

        def native(args, data=False):
            if "update-os" in args:
                self.site.instances[0]["config"]["os"] = json.loads(args[-1])
                return ""
            if args[:2] in (["instance", "show"], ["machine-interfaces", "show-addresses"]):
                return original_core(args, data=data)
            raise AssertionError("PXE must not be sent: " + str(args))

        with (
            patch.object(self.site, "core", side_effect=native),
            patch("pxeye.installation.executor.Console") as console,
            patch.object(self.executor, "install_retry_preflight", return_value={}),
            patch.object(self.executor, "verify_materials"),
            patch.object(self.executor, "check_bound"),
        ):
            console.return_value.text = "SOL Session operational"
            with self.assertRaisesRegex(RuntimeError, "地址未同步"):
                self.executor.start_install_retry(
                    self.task, self.task["execution_device"], self.folder
                )
        self.assertFalse(self.task.get("retry_boot_requested", False))
        self.assertTrue(console.return_value.detach.called)

    def test_retry_preflight_rejects_address_drift_before_writes(self):
        self.site.instances[0]["status"]["network"]["interfaces"][0]["addresses"] = ["192.0.2.99"]
        with self.assertRaisesRegex(ValueError, "地址未同步"):
            self.executor.install_retry_preflight(self.task)
        self.assertEqual(self.site.writes, [])

    def test_only_terminal_prewrite_error_is_retryable(self):
        self.assertTrue(self.executor.can_retry_install(self.task))
        for text in (
            "start: subiquity/Filesystem/convert: matched no disk\n",
            FAILURE + "start: curtin/partitioning: \n",
            FAILURE + "start: subiquity/Install/curtin_install: \n",
            FAILURE
            + "start: subiquity/Install/install/curtin_install/run_curtin_step: partitioning\n",
            FAILURE + "NICO_UI_HOSTKEY UI-retry ssh-ed25519 TEST\n",
        ):
            (self.folder / "console.raw").write_text(text)
            self.assertFalse(self.executor.can_retry_install(self.task))
        (self.folder / "console.raw").write_text(FAILURE)
        self.task["retry_config_requested"] = True
        self.assertFalse(self.executor.can_retry_install(self.task))

    def test_attempt_offset_excludes_historic_error(self):
        (self.folder / "console.raw").write_text(FAILURE + "SOL Session operational\n")
        self.task["console_attempt_offset"] = len(FAILURE.encode())
        self.assertFalse(self.executor.can_retry_install(self.task))

    def test_new_prewrite_error_can_retry_after_accepted_attempt_but_not_unknown_request(self):
        self.task["native_retry_requests"] = 1
        self.task["retry_attempt"] = {"number": 1, "state": "accepted"}
        self.task["retry_config_requested"] = True
        self.task["retry_boot_requested"] = True
        failure = "finish: subiquity/apply_autoinstall_config: autoinstall config did not create needed bootloader partition\n"
        (self.folder / "console.raw").write_text(failure)
        self.assertTrue(self.executor.can_retry_install(self.task))
        self.task["retry_attempt"]["state"] = "boot_requesting"
        self.assertFalse(self.executor.can_retry_install(self.task))
        self.task["retry_attempt"]["state"] = "config_requesting"
        self.assertFalse(self.executor.can_retry_install(self.task))
        self.task["retry_attempt"]["state"] = "accepted"
        (self.folder / "console.raw").write_text("start: curtin/partitioning: \n" + failure)
        self.assertFalse(self.executor.can_retry_install(self.task))

    def test_uefi_marks_esp_including_old_saved_template(self):
        original = self.site.baseline(self.task["execution_device"])
        original = copy.deepcopy(original)
        ai = yaml.safe_load(original["user_data"])
        disk = ai["autoinstall"]["storage"]["config"][0]
        disk["grub_device"] = True
        ai["autoinstall"]["storage"]["config"][1].pop("grub_device", None)
        original["user_data"] = yaml.safe_dump(ai)
        with patch.object(self.site, "baseline", return_value=original):
            ai = yaml.safe_load(
                self.site.render(self.task["execution_device"], self.task)["user_data"]
            )["autoinstall"]
        disks = [p for p in ai["storage"]["config"] if p["type"] == "disk"]
        esps = [
            p
            for p in ai["storage"]["config"]
            if p["type"] == "partition" and p.get("flag") == "boot"
        ]
        self.assertEqual(len(esps), 1)
        self.assertFalse(disks[0]["grub_device"])
        self.assertTrue(esps[0]["grub_device"])
        self.assertEqual(esps[0]["device"], disks[0]["id"])

    def test_retry_preflight_checks_instance_and_does_not_write(self):
        check = self.executor.install_retry_preflight(self.task)
        self.assertEqual(check["instance_id"], "instance-1")
        self.assertEqual(self.site.writes, [])
        self.site.instances[0]["machine_id"] = "different-host"
        with self.assertRaisesRegex(ValueError, "关联"):
            self.executor.install_retry_preflight(self.task)

    def test_frozen_template_preserves_console_bound_key_on_first_boot(self):
        original = copy.deepcopy(self.site.baseline(self.task["execution_device"]))
        data = yaml.safe_load(original["user_data"])
        data["autoinstall"].setdefault("user-data", {})["ssh_deletekeys"] = True
        original["user_data"] = yaml.safe_dump(data)
        with patch.object(self.site, "baseline", return_value=original):
            rendered = yaml.safe_load(
                self.site.render(self.task["execution_device"], self.task)["user_data"]
            )
        self.assertIs(rendered["autoinstall"]["user-data"]["ssh_deletekeys"], False)
        self.assertEqual(
            rendered["autoinstall"]["user-data"]["timezone"],
            data["autoinstall"]["user-data"]["timezone"],
        )

    def test_retry_claim_is_bound_to_session_and_consumed_once(self):
        check = self.app.retry_install_preflight(self.task["id"], "owner")
        body = {"preflight_id": check["id"], "confirm_serial": "NEW-01", "confirm_reboot": True}
        with self.assertRaisesRegex(ValueError, "会话"):
            self.app.retry_install(self.task["id"], body, "different-owner", "operator")
        with patch.object(self.app, "start_queue"):
            result = self.app.retry_install(self.task["id"], body, "owner", "operator")
        self.assertEqual(result["id"], self.task["id"])
        self.assertEqual(len(self.store.tasks()), 1)
        self.assertTrue(result["retry_existing_install"])
        with self.assertRaises(ValueError):
            self.app.retry_install(self.task["id"], body, "owner", "operator")
        self.assertEqual(self.site.writes, [])

    def test_task_mirror_repair_changes_only_apt_and_runs_check_before_disk_guard(self):
        device = self.task["execution_device"]
        before = yaml.safe_load(self.site.render(device, self.task)["user_data"])["autoinstall"]
        self.task["apt_repair"] = {
            "apt": {
                "geoip": False,
                "primary": [{"arches": ["default"], "uri": "https://mirror.example/ubuntu"}],
            },
            "actor": "operator",
            "reason": "validated dependency closure",
        }
        after = yaml.safe_load(self.site.render(device, self.task)["user_data"])["autoinstall"]
        self.assertEqual(after["apt"], self.task["apt_repair"]["apt"])
        self.assertEqual(after["storage"], before["storage"])
        self.assertEqual(after["identity"], before["identity"])
        self.assertIn("NICO_APT_PRECHECK_FAILED", after["early-commands"][0])
        self.assertIn("NICO_UI_DISK_GUARD_PASSED", after["early-commands"][1])

    def test_install_controller_initialization_does_not_claim_disk_writes(self):
        text = "start: subiquity/Install/install: \nstart: subiquity/ErrorReporter/123.install_fail/add_info: \n"
        (self.folder / "console.raw").write_text(text)
        check = self.app.retry_install_preflight(self.task["id"], "owner")
        self.assertFalse(check["requires_disk_confirmation"])
        self.assertEqual(check["failure_kind"], "installer_failed_before_write")

    def test_failed_install_requires_fresh_preflight_and_disk_confirmation(self):
        text = "start: subiquity/Install/install/curtin_install: \nstart: subiquity/ErrorReporter/123.install_fail/add_info: \n"
        (self.folder / "console.raw").write_text(text)
        self.assertTrue(self.executor.can_retry_install(self.task))
        check = self.app.retry_install_preflight(self.task["id"], "owner")
        self.assertTrue(check["requires_disk_confirmation"])
        body = {"preflight_id": check["id"], "confirm_serial": "NEW-01", "confirm_reboot": True}
        with self.assertRaisesRegex(ValueError, "序列号"):
            self.app.retry_install(self.task["id"], body, "owner", "operator")
        self.assertEqual(self.store.get(self.task["id"])["status"], "needs_attention")
        body["confirm_disk_serial"] = check["disk_serial"]
        with patch.object(self.app, "start_queue"):
            result = self.app.retry_install(self.task["id"], body, "owner", "operator")
        self.assertEqual(result["status"], "queued")
        self.assertEqual(
            result["installation_retries"][-1]["confirmed_disk_serial"], check["disk_serial"]
        )
        self.assertEqual(self.site.writes, [])

    def test_early_guard_passes_resolved_path_to_installer(self):
        device = self.task["execution_device"]
        config = yaml.safe_load(self.site.render(device, self.task)["user_data"])
        code = (
            next(c for c in config["autoinstall"]["early-commands"] if "<<'NICO_GUARD'" in c)
            .split("\n", 1)[1]
            .rsplit("\nNICO_GUARD", 1)[0]
        )
        root = self.root / "runtime"
        for directory in (
            "run",
            "dev/disk/by-id",
            "sys/class/dmi/id",
            "sys/firmware/efi",
            "sys/class/net/eth0",
        ):
            (root / directory).mkdir(parents=True, exist_ok=True)
        (root / "dev/nvme7n1").touch()
        alias = root / "dev/disk/by-id/nvme-test"
        alias.symlink_to(root / "dev/nvme7n1")
        (root / "sys/class/dmi/id/product_serial").write_text("NEW-01")
        (root / "sys/class/net/eth0/address").write_text(device["boot_mac"])
        path = root / "autoinstall.yaml"
        path.write_text(yaml.safe_dump(config))
        real_path = Path

        def runtime_path(value):
            value = str(value)
            return real_path(value) if value.startswith(str(root)) else root / value.lstrip("/")

        def output(argv, **kwargs):
            if argv[0] == "udevadm":
                return "ID_SERIAL_SHORT=SCOUT-DISK-0\n"
            return json.dumps({"blockdevices": [{"name": "nvme7n1", "type": "disk", "rm": False}]})

        with (
            patch("pathlib.Path", side_effect=runtime_path),
            patch("subprocess.check_output", side_effect=output),
        ):
            exec(code, {})
        disk = yaml.safe_load(path.read_text())["autoinstall"]["storage"]["config"][0]
        # Subiquity's probed disk path equals the resolved kernel device.
        self.assertEqual(disk["path"], str((root / "dev/nvme7n1").resolve()))
        self.assertNotEqual(disk["path"], str(alias))
        self.assertEqual(
            json.loads((root / "run/nico-disks-before.json").read_text())["target"], str(alias)
        )

    def test_native_retry_reuses_instance_and_does_not_allocate_or_assign(self):
        original = self.site.core
        calls = []

        def core(argv, **kwargs):
            if "update-os" in argv:
                calls.append("update-os")
                self.site.instances[0]["config"]["os"] = json.loads(argv[argv.index("--os") + 1])
                self.site.instances[0]["config_version"] = "v2"
                return "{}"
            if argv[:2] == ["instance", "reboot"]:
                calls.append("custom-pxe")
                return "{}"
            return original(argv, **kwargs)

        class AttachedConsole:
            text = "SOL Session operational"

            def __init__(self, *args):
                pass

            def attach(self):
                pass

            def poll(self):
                pass

            def detach(self):
                pass

        with (
            patch.object(self.site, "core", side_effect=core),
            patch("pxeye.installation.executor.Console", AttachedConsole),
        ):
            self.executor.start_install_retry(self.task, self.task["execution_device"], self.folder)
        self.assertEqual(calls, ["update-os", "custom-pxe"])
        self.assertEqual(len(self.site.instances), 1)
        self.assertEqual(self.task["native_allocation_requests"], 1)
        self.assertEqual(self.site.writes, [])
        self.assertFalse(self.executor.can_retry_install(self.task))

    def test_verified_config_can_continue_without_replaying_config_update(self):
        self.task.update(
            retry_config_requested=True,
            retry_boot_requested=False,
            retry_attempt={"number": 1, "state": "config_verified", "source_offset": 0},
            console_attempt_offset=len(FAILURE.encode()),
        )
        with (self.folder / "console.raw").open("a") as log:
            log.write("SOL Session operational\n")
        self.store.save(self.task)
        self.assertTrue(self.executor.can_retry_install(self.task))
        check = self.app.retry_install_preflight(self.task["id"], "owner")
        with patch.object(self.app, "start_queue"):
            task = self.app.retry_install(
                self.task["id"],
                {
                    "preflight_id": check["id"],
                    "confirm_serial": self.task["device"],
                    "confirm_reboot": True,
                },
                "owner",
                "operator",
            )
        self.assertEqual(task["retry_attempt"]["state"], "config_verified")
        self.assertTrue(task["retry_config_requested"])
        original, calls = self.site.core, []

        def core(argv, **kwargs):
            if "update-os" in argv:
                self.fail("verified configuration must not be sent again")
            if argv[:2] == ["instance", "reboot"]:
                calls.append("custom-pxe")
                return "{}"
            return original(argv, **kwargs)

        class AttachedConsole:
            text = "SOL Session operational"

            def __init__(self, *args):
                pass

            def attach(self):
                pass

            def poll(self):
                pass

            def detach(self):
                pass

        with (
            patch.object(self.site, "core", side_effect=core),
            patch("pxeye.installation.executor.Console", AttachedConsole),
        ):
            self.executor.start_install_retry(task, task["execution_device"], self.folder)
        self.assertEqual(calls, ["custom-pxe"])
        self.assertEqual(task["native_retry_requests"], 1)
        self.assertEqual(task["config_version"], "v1")
        self.assertEqual(self.site.writes, [])
        self.assertFalse(self.executor.can_retry_install(task))

    def test_changed_template_or_network_blocks_retry(self):
        self.site.links[0]["address"] = ["192.0.2.99"]
        with self.assertRaisesRegex(ValueError, "网络"):
            self.executor.install_retry_preflight(self.task)

        self.site.links[0]["address"] = ["192.0.2.10"]
        config = copy.deepcopy(self.site.baseline(self.task["execution_device"]))
        config["user_data"] += "\n# changed\n"
        with (
            patch.object(self.site, "baseline", return_value=config),
            self.assertRaisesRegex(ValueError, "模板"),
        ):
            self.executor.install_retry_preflight(self.task)

    def disk_exit_fixture(self):
        device = self.task["execution_device"]
        text = (
            "NICO_UI_HOSTKEY UI-retry ssh-ed25519 VEVTVA==\nfinish: subiquity/Late/run:\n"
            "finish: subiquity/Install/install:\nreboot: Restarting system\n"
        )
        (self.folder / "console.raw").write_text(text)
        (self.folder / "known_hosts").write_text(
            device["management_ip"] + " ssh-ed25519 VEVTVA==\n"
        )
        system = {
            "SerialNumber": device["serial"],
            "Oem": {"Lenovo": {"SystemStatus": "SystemRunningInUEFI"}},
        }
        settings = {
            "@odata.type": "#LenovoBootManager.v1_0_0.LenovoBootManager",
            "BootOrderSupported": ["Network", "Hard Disk", "CD/DVD Rom", "USB Storage"],
            "BootOrderNext": ["Network", "USB Storage", "Hard Disk", "CD/DVD Rom"],
        }
        return device, system, settings

    def test_observed_oem_disk_exit_recovery_preserves_other_order_and_reboots_once(self):
        device, system, settings = self.disk_exit_fixture()
        writes = []

        def redfish(device, suffix="", method="GET", body=None):
            if not suffix:
                return system
            if method == "GET":
                return copy.deepcopy(settings)
            writes.append((suffix, method, body))
            if method == "PATCH":
                settings.update(body)
            return {}

        with (
            patch.object(self.site, "redfish", side_effect=redfish),
            patch.object(self.executor, "ssh_open", return_value=False),
        ):
            self.assertTrue(self.executor.recover_disk_boot(self.task, device, system))
            self.assertFalse(self.executor.recover_disk_boot(self.task, device, system))
        self.assertEqual(
            writes[0][2]["BootOrderNext"], ["Hard Disk", "Network", "USB Storage", "CD/DVD Rom"]
        )
        self.assertEqual(len(writes), 2)
        self.assertEqual(writes[1][2], {"ResetType": "ForceRestart"})
        self.assertTrue(self.task["disk_exit_compatibility"]["reboot_accepted"])
        self.assertEqual(self.site.writes, [])

    def test_boot_observation_read_failure_waits_without_repeating_writes(self):
        device, system, settings = self.disk_exit_fixture()
        with (
            patch.object(
                self.site,
                "redfish",
                side_effect=[
                    RuntimeError("Redfish GET 失败（500）。"),
                    RuntimeError("Redfish GET 失败（500）。"),
                    system,
                ],
            ),
            patch.object(self.executor, "event") as event,
        ):
            self.assertIsNone(self.executor.observe_boot_system(self.task, device))
            self.assertIsNone(self.executor.observe_boot_system(self.task, device))
            self.assertEqual(self.executor.observe_boot_system(self.task, device), system)
            event.assert_called_once()
        with (
            patch.object(
                self.site, "redfish", side_effect=RuntimeError("Redfish GET 失败（500）。")
            ) as api,
            patch.object(self.executor, "ssh_open", return_value=False),
        ):
            self.assertFalse(self.executor.recover_disk_boot(self.task, device, system))
            self.assertEqual(
                api.call_args_list,
                [
                    call(device, "/Oem/Lenovo/BootSettings/BootOrder.BootOrder"),
                    call(device, "/Oem/Lenovo/BootSettings"),
                ],
            )
        self.assertFalse(self.task.get("disk_exit_recovery_requested", False))
        self.assertEqual(self.site.writes, [])

    def test_disk_exit_recovery_requires_current_installation_evidence(self):
        device, system, settings = self.disk_exit_fixture()
        (self.folder / "console.raw").write_text("UEFI menu\n")
        with (
            patch.object(self.executor, "ssh_open", return_value=False),
            patch.object(self.site, "redfish") as api,
        ):
            with self.assertRaisesRegex(RuntimeError, "本轮安装结束"):
                self.executor.recover_disk_boot(self.task, device, system)
            api.assert_not_called()
        self.assertFalse(self.task.get("disk_exit_recovery_requested", False))
        self.task["normal_reboot_requested"] = True
        self.assertFalse(self.executor.recover_disk_boot(self.task, device, system))
        self.task["normal_reboot_requested"] = False
        self.task["native_allocation_requests"] = 0
        self.assertFalse(self.executor.recover_disk_boot(self.task, device, system))

    def test_uncertain_boot_order_write_never_reboots_or_replays(self):
        device, system, settings = self.disk_exit_fixture()
        writes = []

        def redfish(device, suffix="", method="GET", body=None):
            if not suffix:
                return system
            if method == "GET":
                return copy.deepcopy(settings)
            writes.append(method)
            return {}

        with (
            patch.object(self.site, "redfish", side_effect=redfish),
            patch.object(self.executor, "ssh_open", return_value=False),
        ):
            with self.assertRaisesRegex(RuntimeError, "未读回"):
                self.executor.recover_disk_boot(self.task, device, system)
            self.assertFalse(self.executor.recover_disk_boot(self.task, device, system))
        self.assertEqual(writes, ["PATCH"])

    def test_console_recovered_key_requires_original_installation_and_new_console_evidence(self):
        device, _, _ = self.disk_exit_fixture()
        text = (self.folder / "console.raw").read_text()
        original_key, new_key = "ssh-ed25519 VEVTVA==", "ssh-ed25519 TkVX"
        self.task["console_identity_recovery"] = {
            "source": "authenticated-bmc-console",
            "serial": device["serial"],
            "task_id": self.task["id"],
            "host_key": new_key,
            "installer_host_key": original_key,
        }
        self.assertFalse(verified_installation_identity(text, self.task, new_key))
        evidence = text + "NICO_UI_IDENTITY_RECOVERY UI-retry NEW-01 " + new_key + "\n"
        self.assertTrue(verified_installation_identity(evidence, self.task, new_key))
        self.assertTrue(
            verified_installation_identity(
                evidence.replace(new_key, new_key[:15] + "\n" + new_key[15:]), self.task, new_key
            )
        )
        self.assertFalse(
            verified_installation_identity(
                evidence.replace("finish: subiquity/Install/install:", "failed:"),
                self.task,
                new_key,
            )
        )
        self.task["console_identity_recovery"]["serial"] = "another-host"
        self.assertFalse(verified_installation_identity(evidence, self.task, new_key))
        self.task["console_identity_recovery"]["serial"] = device["serial"]
        self.task["console_identity_recovery"]["source"] = "ssh-keyscan"
        self.assertFalse(verified_installation_identity(evidence, self.task, new_key))


if __name__ == "__main__":
    unittest.main()
