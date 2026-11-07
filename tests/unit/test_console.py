"""Offline boundary checks. No Core/BMC/SSH or physical reboot is called."""

import copy
import hashlib
import http.client
import json
import tempfile
import subprocess
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from pxeye.services.execution import Adapter
from pxeye.clients.process import run
from pxeye.bootstrap import Application
from pxeye.api.http import Handler
from pxeye.__main__ import ThreadingHTTPServer
from pxeye.persistence.store import Store
from pxeye.installation.executor import (
    installer_exit_evidence,
    installer_execution_started,
    terminal_installer_failure,
    boot_progress,
    Executor,
)


class CommandTests(unittest.TestCase):
    def test_timeout_does_not_expose_installation_arguments(self):
        argv = ["test-cli", "--os", "SENSITIVE_INSTALLATION_PAYLOAD"]
        with patch(
            "pxeye.clients.process.subprocess.run",
            side_effect=subprocess.TimeoutExpired(argv, 1),
        ):
            with self.assertRaises(RuntimeError) as caught:
                run(argv, timeout=1)
        self.assertNotIn("SENSITIVE", str(caught.exception))
        self.assertIn("超时", str(caught.exception))


class ExitEvidenceTests(unittest.TestCase):
    def test_install_progress_accepts_child_events_without_parent_event(self):
        cases = [
            ("start: subiquity/Install/install: \n", True),
            ("start:  subiquity/Install/install/configure_apt: configuring apt\n", True),
            (
                "start:   subiquity/Install/install/curtin_install/run_curtin_step: partitioning\n",
                True,
            ),
            ("echo start: subiquity/Install/install: \n", False),
            ("finish: subiquity/Install/install/configure_apt: \n", False),
            ("start: subiquity/apply_autoinstall_config: \n", False),
            ("Language selection     [ Help ]\n", False),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(installer_execution_started(text), expected)

    def test_terminal_failure_is_distinct_from_error_controller_initialization(self):
        for text, expected in [
            ("start: subiquity/Error/load_autoinstall_data: \n", False),
            ("finish: subiquity/Install/install: \n", False),
            ("start: subiquity/ErrorReporter/123.install_fail/add_info: \n", True),
            ("finish: subiquity/Install/install: FAIL: curtin failed\n", True),
            ("An error occurred. Press enter to start a shell\nroot@ubuntu-server:/# ", True),
        ]:
            with self.subTest(text=text):
                self.assertEqual(bool(terminal_installer_failure(text)), expected)

    def test_boot_progress_does_not_confuse_ipxe_download_with_installer(self):
        self.assertIsNone(boot_progress("Downloading nico.efi... ok\n"))
        waiting = "Current state: Assigned/HostPlatformConfiguration { SetBootOrder }\nCould not continue boot due to invalid state\n"
        self.assertEqual(boot_progress(waiting)[0], "boot")
        self.assertEqual(boot_progress(waiting + "Linux version 6.8.0-generic\n")[0], "pxe")
        self.assertEqual(boot_progress("/casper/vmlinuz... ok\n")[0], "pxe")

    def setUp(self):
        self.key = "ssh-ed25519 TESTKEY"
        self.text = (
            "NICO_UI_HOSTKEY UI-1 "
            + self.key
            + "\nfinish: subiquity/Late/run: \nfinish: subiquity/Install/install: \nreboot: Restarting system\n"
        )

    def test_bare_serial_finish_requires_late_reboot_and_same_task_key(self):
        self.assertTrue(installer_exit_evidence(self.text, "UI-1", self.key))
        for changed in [
            self.text.replace("Late/run", "Other/run"),
            self.text.replace("reboot: Restarting system", ""),
            self.text.replace("UI-1", "UI-2"),
        ]:
            self.assertFalse(installer_exit_evidence(changed, "UI-1", self.key))

    def test_failed_installer_or_command_trace_cannot_qualify(self):
        self.assertFalse(
            installer_exit_evidence(
                self.text.replace("Install/install: ", "Install/install: FAIL: "), "UI-1", self.key
            )
        )
        self.assertFalse(
            installer_exit_evidence(
                self.text.replace(
                    "finish: subiquity/Install/install:", "echo finish: subiquity/Install/install:"
                ),
                "UI-1",
                self.key,
            )
        )
        self.assertFalse(
            installer_exit_evidence(
                self.text + "start: subiquity/ErrorReporter/123.install_fail/add_info: \n",
                "UI-1",
                self.key,
            )
        )

    def test_resume_rejects_unknown_or_already_requested_actions(self):
        fake = type("AdapterStub", (), {"data": Path("/nonexistent-test-path")})()
        e = Executor(fake, None)
        for task in [
            {"native_reinstall_requests": 0},
            {"native_reinstall_requests": 1, "normal_reboot_requested": True},
            {"native_reinstall_requests": 1, "disk_exit_recovery_requested": True},
        ]:
            self.assertFalse(e.can_resume(task))

    def test_exit_recovery_continuation_requires_verified_os_and_never_replays_power(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "tasks" / "UI-1"
            folder.mkdir(parents=True)
            (folder / "known_hosts").write_text("192.0.2.10 " + self.key + "\n")
            (folder / "console.raw").write_text(self.text)
            adapter = unittest.mock.Mock()
            adapter.data = root
            adapter.device.return_value = {"management_ip": "192.0.2.10"}
            executor = Executor(adapter, None)
            task = {
                "id": "UI-1",
                "device": "SERIAL-1",
                "native_reinstall_requests": 1,
                "disk_exit_recovery_requested": True,
            }
            with (
                patch.object(executor, "check_bound") as bound,
                patch.object(executor, "accept", return_value={"passed": False}) as accept,
            ):
                self.assertFalse(executor.can_resume(task))
                accept.return_value = {"passed": True}
                self.assertTrue(executor.can_resume(task))
                self.assertEqual(bound.call_count, 2)
            adapter.redfish.assert_not_called()
            adapter.core.assert_not_called()


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "state.db")
        self.check = {"device": "SERIAL-1", "hostname": "nico", "passed": True}
        self.task = {"id": "TASK-1", "device": "SERIAL-1", "hostname": "nico", "status": "queued"}

    def tearDown(self):
        self.tmp.cleanup()

    def test_consumed_preflight_and_request_idempotency(self):
        self.store.preflight("check", self.check)
        first, created = self.store.claim("check", copy.deepcopy(self.task), "request-unique-001")
        again, created_again = self.store.claim(
            "check", copy.deepcopy(self.task), "request-unique-001"
        )
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first, again)
        self.assertEqual(len(self.store.tasks()), 1)

    def test_expired_preflight_never_claims_device(self):
        self.store.preflight("old", self.check, lifetime=-1)
        with self.assertRaises(ValueError):
            self.store.claim("old", self.task, "request-unique-002")
        self.assertIsNone(self.store.active("SERIAL-1"))

    def test_hostname_change_invalidates_checked_scope(self):
        self.store.preflight("check", self.check)
        with self.assertRaises(ValueError):
            self.store.claim("check", self.task | {"hostname": "other"}, "request-unique-003")

    def test_changed_plan_cannot_claim_or_queue_install(self):
        self.store.preflight(
            "check",
            self.check
            | {"installation_plan": {"management_ip": "192.0.2.90", "segment_revision": "v1"}},
        )
        with self.assertRaisesRegex(ValueError, "规划"):
            self.store.claim(
                "check",
                self.task
                | {"installation_plan": {"management_ip": "192.0.2.91", "segment_revision": "v1"}},
                "request-unique-plan",
            )
        self.assertEqual(self.store.tasks(), [])

    def test_failed_checks_never_claim_device(self):
        self.store.preflight("check", self.check | {"passed": False})
        with self.assertRaises(ValueError):
            self.store.claim("check", self.task, "request-unique-004")

    def test_attention_keeps_lock_and_other_device_remains_independent(self):
        self.store.preflight("one", self.check)
        task, _ = self.store.claim("one", copy.deepcopy(self.task), "request-unique-005")
        task["status"] = "needs_attention"
        self.store.save(task)
        self.store.preflight("two", self.check)
        with self.assertRaises(ValueError):
            self.store.claim("two", self.task | {"id": "TASK-2"}, "request-unique-006")
        self.assertIsNone(self.store.active("SERIAL-2"))

    def test_two_simultaneous_requests_get_one_device(self):
        for key in ["one", "two"]:
            self.store.preflight(key, self.check)
        barrier = threading.Barrier(2)
        results = []

        def claim(key):
            barrier.wait()
            try:
                self.store.claim(key, self.task | {"id": key}, key * 10)
                results.append(True)
            except ValueError:
                results.append(False)

        threads = [threading.Thread(target=claim, args=(k,)) for k in ["one", "two"]]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(results), [False, True])


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "ssh_key").write_text("FAKE_TEST_KEY_NOT_A_PRIVATE_KEY")
        (self.root / "ssh_key.pub").write_text("ssh-ed25519 TESTPUB console")
        self.device = {
            "serial": "SERIAL-1",
            "disk_wwn": "0xTEST",
            "instance_id": "instance-1",
            "profile": "test-profile",
            "boot_mac": "02:00:00:00:00:01",
            "baseline_file": "baseline.json",
            "timezone": "Asia/Shanghai",
        }
        self.os = {
            "run_provisioning_instructions_on_every_boot": False,
            "user_data": yaml.safe_dump(
                {
                    "autoinstall": {
                        "identity": {"hostname": "old", "username": "ops", "password": "!"},
                        "ssh": {"authorized-keys": ["ssh-ed25519 ORIGINAL operator"]},
                        "storage": {
                            "config": [{"type": "disk", "path": "/dev/disk/by-id/wwn-0xTEST"}]
                        },
                        "network": {"version": 2, "ethernets": {"port": {"dhcp4": False}}},
                        "late-commands": ["old /var/log/nico-installation/task.json", "echo keep"],
                    }
                }
            ),
        }
        (self.root / "baseline.json").write_text(json.dumps(self.os))
        self.adapter = Adapter({"devices": [self.device]}, self.root, self.root / "data")

    def tearDown(self):
        self.tmp.cleanup()

    def test_render_binds_ui_hostname_and_preserves_storage_network_user_key(self):
        rendered = self.adapter.render(
            self.device, {"id": "UI-TEST-1", "hostname": "nico", "actor": "operator"}
        )
        new = yaml.safe_load(rendered["user_data"])["autoinstall"]
        self.assertEqual(new["timezone"], "Asia/Shanghai")
        self.assertEqual(new["user-data"]["timezone"], "Asia/Shanghai")
        self.assertIn(["timedatectl", "set-timezone", "Asia/Shanghai"], new["user-data"]["runcmd"])
        old = yaml.safe_load(self.os["user_data"])["autoinstall"]
        self.assertEqual(new["identity"]["hostname"], "nico")
        self.assertEqual(new["identity"]["username"], "ops")
        for key in ["storage", "network"]:
            self.assertEqual(new[key], old[key])
        self.assertIn("ssh-ed25519 ORIGINAL operator", new["ssh"]["authorized-keys"])
        self.assertIn("ssh-ed25519 TESTPUB console", new["ssh"]["authorized-keys"])
        self.assertIn('"source": "nico-ui"', new["late-commands"][-1])
        self.assertIn("NICO_UI_HOSTKEY UI-TEST-1", new["late-commands"][-1])
        self.assertNotIn("old /var/log", "\n".join(new["late-commands"]))
        self.assertFalse(rendered["run_provisioning_instructions_on_every_boot"])

    def test_timezone_convergence_preserves_other_firstboot_commands(self):
        data = yaml.safe_load(self.os["user_data"])
        existing = [["touch", "/var/lib/example-firstboot"]]
        data["autoinstall"]["user-data"] = {"runcmd": existing}
        self.os["user_data"] = yaml.safe_dump(data)
        (self.root / "baseline.json").write_text(json.dumps(self.os))
        self.device["timezone"] = "Europe/Berlin"
        rendered = self.adapter.render(
            self.device, {"id": "UI-TEST-1", "hostname": "nico", "actor": "operator"}
        )
        ai = yaml.safe_load(rendered["user_data"])["autoinstall"]
        self.assertEqual(ai["user-data"]["runcmd"][0], existing[0])
        self.assertEqual(
            ai["user-data"]["runcmd"][-1], ["timedatectl", "set-timezone", "Europe/Berlin"]
        )
        self.assertEqual(ai["timezone"], ai["user-data"]["timezone"])

    def test_wrong_disk_baseline_is_rejected(self):
        self.device["disk_wwn"] = "0xOTHER"
        with self.assertRaises(RuntimeError):
            self.adapter.baseline(self.device)

    def network_fixture(self):
        data = yaml.safe_load(self.os["user_data"])
        data["autoinstall"]["network"]["ethernets"]["port"] = {
            "match": {"macaddress": self.device["boot_mac"]},
            "set-name": "eno1",
            "dhcp4": False,
            "addresses": ["192.0.2.10/24"],
            "routes": [{"to": "default", "via": "192.0.2.1"}],
            "nameservers": {"addresses": ["192.0.2.53"]},
        }
        data["autoinstall"]["network"]["ethernets"]["business"] = {"dhcp4": True}
        self.os["user_data"] = yaml.safe_dump(data)
        (self.root / "baseline.json").write_text(json.dumps(self.os))
        self.plan = {
            "management_ip": "192.0.2.90",
            "prefixlen": 24,
            "gateway": "192.0.2.1",
            "boot_mac": self.device["boot_mac"],
            "current_management_ip": "192.0.2.10",
        }

    def test_render_target_address_preserves_other_nics_storage_and_dns(self):
        self.network_fixture()
        task = {
            "id": "UI-TEST-1",
            "hostname": "nico",
            "actor": "operator",
            "installation_plan": self.plan,
        }
        new = yaml.safe_load(self.adapter.render(self.device, task)["user_data"])["autoinstall"]
        old = yaml.safe_load(self.os["user_data"])["autoinstall"]
        nic = new["network"]["ethernets"]["port"]
        self.assertEqual(nic["addresses"], ["192.0.2.90/24"])
        self.assertEqual(nic["nameservers"], old["network"]["ethernets"]["port"]["nameservers"])
        self.assertEqual(
            new["network"]["ethernets"]["business"], old["network"]["ethernets"]["business"]
        )
        self.assertEqual(new["storage"], old["storage"])

    def test_saved_connection_and_historic_task_use_their_own_addresses(self):
        self.device.update(management_ip="192.0.2.10", prefixlen=24, gateway="192.0.2.1")
        self.adapter.remember_connection(
            self.device | {"management_ip": "192.0.2.90"}, {"id": "UI-new"}
        )
        self.assertEqual(self.adapter.device("SERIAL-1")["management_ip"], "192.0.2.90")
        old = {"device": "SERIAL-1", "management_ip": "192.0.2.10"}
        executor = Executor(self.adapter, None)
        self.assertEqual(executor.task_device(old)["management_ip"], "192.0.2.10")
        new = old | {"execution_device": self.device | {"management_ip": "192.0.2.91"}}
        self.assertEqual(executor.task_device(new)["management_ip"], "192.0.2.91")

    def test_acceptance_connects_to_frozen_target(self):
        self.device["management_ip"] = "192.0.2.90"
        with patch.object(self.adapter, "ssh", return_value='{"passed":true}') as ssh:
            Executor(self.adapter, None).accept(
                self.device, {"id": "UI-TEST-1"}, "ssh-ed25519 TEST", self.root / "known"
            )
            self.assertEqual(ssh.call_args.args[0]["management_ip"], "192.0.2.90")

    def test_preflight_inspects_current_ip_and_renders_target(self):
        self.network_fixture()
        self.device.update(management_ip="192.0.2.10", prefixlen=24, gateway="192.0.2.1")
        self.adapter.config["materials"] = []
        host = {
            "interfaces": [
                {"address": self.device["boot_mac"], "addr_info": [{"local": "192.0.2.10"}]}
            ]
        }
        with (
            patch.object(self.adapter, "installation_plan", return_value=self.plan),
            patch.object(self.adapter, "machine", return_value={"state": "Assigned/Ready"}),
            patch.object(
                self.adapter,
                "instance",
                return_value={"config_version": "v1", "config": {"os": self.os}},
            ),
            patch.object(
                self.adapter,
                "redfish",
                return_value={"SerialNumber": "SERIAL-1", "PowerState": "On"},
            ),
            patch.object(self.adapter, "host_snapshot", return_value=host) as snapshot,
        ):
            result = self.adapter.preflight("SERIAL-1", "nico")
        self.assertTrue(result["passed"], result["checks"])
        self.assertEqual(snapshot.call_args.args[0]["management_ip"], "192.0.2.10")
        self.assertEqual(result["scope"]["management_ip"], "192.0.2.90")
        self.assertEqual(
            result["snapshot"]["rendered_network"]["ethernets"]["port"]["addresses"],
            ["192.0.2.90/24"],
        )

    def test_executor_stops_before_core_write_when_plan_drifts(self):
        from unittest.mock import Mock

        self.device["management_ip"] = "192.0.2.10"
        old = {"live_sha256": "sha", "host": {"root_uuid": "root"}, "baseline_sha256": "baseline"}
        task = {
            "id": "UI-TEST-1",
            "device": "SERIAL-1",
            "hostname": "nico",
            "installation_plan": {"management_ip": "192.0.2.90"},
            "preflight": {"snapshot": old},
        }
        executor = Executor(self.adapter, Mock())
        with (
            patch.object(
                self.adapter,
                "preflight",
                return_value={
                    "passed": True,
                    "snapshot": old,
                    "installation_plan": {"management_ip": "192.0.2.91"},
                },
            ),
            patch.object(self.adapter, "core") as core,
            patch.object(executor, "verify_materials") as materials,
        ):
            executor.run(task)
        self.assertEqual(task["status"], "needs_attention")
        self.assertIn("发生变化", task["error"])
        core.assert_not_called()
        materials.assert_not_called()

    def test_address_assignment_is_single_write_then_static_readback(self):
        plan = {"interface_id": "interface-1", "management_ip": "192.0.2.90"}
        with (
            patch.object(
                self.adapter,
                "rpc",
                return_value={"ipAddress": "192.0.2.90", "interfaceId": {"value": "interface-1"}},
            ) as rpc,
            patch.object(
                self.adapter,
                "core",
                return_value=[{"address": "192.0.2.90", "allocation_type": "Static"}],
            ),
        ):
            self.adapter.assign_install_address(plan)
            rpc.assert_called_once_with(
                "AssignStaticAddress",
                {"interface_id": {"value": "interface-1"}, "ip_address": "192.0.2.90"},
            )
        with patch.object(self.adapter, "rpc", side_effect=RuntimeError("timeout")) as rpc:
            with self.assertRaises(RuntimeError):
                self.adapter.assign_install_address(plan)
            self.assertEqual(rpc.call_count, 1)

    def test_everyboot_baseline_is_rejected(self):
        (self.root / "baseline.json").write_text(
            json.dumps(self.os | {"run_provisioning_instructions_on_every_boot": True})
        )
        with self.assertRaises(RuntimeError):
            self.adapter.baseline(self.device)

    def test_unknown_device_or_invalid_hostname_never_calls_core(self):
        with patch.object(self.adapter, "core") as core:
            for serial, name in [
                ("OTHER", "nico"),
                ("SERIAL-1", "nico;reboot"),
                ("SERIAL-1", "-bad"),
                ("SERIAL-1", "a" * 64),
            ]:
                with self.assertRaises(ValueError):
                    self.adapter.preflight(serial, name)
            core.assert_not_called()


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "auth.json").write_text(
            json.dumps({"password_sha256": hashlib.sha256(b"test-only-password").hexdigest()})
        )
        with patch("pxeye.bootstrap.Adapter") as adapter:
            adapter.return_value = object()
            self.app = Application({"devices": []}, root, root / "data", root)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.app = self.app
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host = "127.0.0.1:" + str(self.server.server_address[1])

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.app.lockfile.close()
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection(self.host, timeout=5)
        hdr = {"Content-Type": "application/json", "Origin": "http://" + self.host} | (
            headers or {}
        )
        conn.request(method, path, json.dumps(body) if body is not None else None, hdr)
        response = conn.getresponse()
        result = response.status, json.loads(response.read()), dict(response.getheaders())
        conn.close()
        return result

    def test_unauthenticated_api_and_cross_origin_write_are_rejected(self):
        self.assertEqual(self.request("GET", "/api/tasks")[0], 401)
        self.assertEqual(
            self.request(
                "POST",
                "/api/login",
                {"password": "test-only-password"},
                {"Origin": "https://other.invalid"},
            )[0],
            403,
        )

    def test_login_cookie_and_csrf(self):
        status, data, headers = self.request(
            "POST", "/api/login", {"password": "test-only-password"}
        )
        self.assertEqual(status, 200)
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        cookie = headers["Set-Cookie"].split(";")[0]
        self.assertEqual(self.request("POST", "/api/tasks", {}, {"Cookie": cookie})[0], 403)
        status, _, _ = self.request(
            "POST", "/api/tasks", {}, {"Cookie": cookie, "X-CSRF-Token": data["csrf"]}
        )
        self.assertEqual(status, 400)
        self.assertEqual(self.app.store.tasks(), [])

    def test_wrong_password_and_arbitrary_file_are_rejected(self):
        self.assertEqual(self.request("POST", "/api/login", {"password": "wrong"})[0], 401)
        self.assertEqual(self.request("GET", "/../../secrets/auth.json")[0], 404)


if __name__ == "__main__":
    unittest.main()
