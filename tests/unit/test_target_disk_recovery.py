"""Lost serial output can reopen read-only verification, never bypass disk acceptance."""

import copy
import unittest
from unittest.mock import patch
from pxeye.installation.executor import installation_identity_candidate, installer_exit_evidence
from pxeye.services.os_library import ubuntu_boot_parameters
from pxeye.common import digest
from tests.unit import test_install_retry
from tests.unit import test_management


class TargetDiskRecoveryTests(unittest.TestCase):
    def setUp(self):
        fixture = test_install_retry.InstallRetryTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        self.e, self.task, self.folder, self.site = (
            fixture.executor,
            fixture.task,
            fixture.folder,
            fixture.site,
        )
        self.key = "ssh-ed25519 TESTKEY"
        self.text = "NICO_UI_HOSTKEY " + self.task["id"] + " " + self.key + "\n"
        (self.folder / "console.raw").write_text(self.text)
        (self.folder / "known_hosts").write_text(
            self.task["execution_device"]["management_ip"] + " " + self.key + "\n"
        )
        self.report = {
            "checked_at": "2026-11-06T00:00:00Z",
            "installer_log_sha256": "log-digest",
            "hostkey_fingerprint": "fingerprint",
            "root_uuid": "new-root",
        }

    def test_partial_serial_only_opens_verification_not_success(self):
        self.assertTrue(self.e.can_resume(self.task))
        self.assertFalse(installer_exit_evidence(self.text, self.task["id"], self.key))
        self.assertNotIn("installation_evidence", self.task)
        self.assertEqual(self.site.writes, [])

    def test_wrong_task_key_multiple_keys_and_terminal_failure_are_rejected(self):
        for text in (
            self.text.replace(self.task["id"], "other"),
            self.text.replace("TESTKEY", "OTHERKEY"),
            self.text + self.text.replace("TESTKEY", "OTHERKEY"),
            self.text + "finish: subiquity/Late/run: FAIL: command failed\n",
            self.text + "finish: subiquity/Install/install: ERROR: failed\n",
            self.text + "NICO_APT_PRECHECK_FAILED: missing package\n",
        ):
            with self.subTest(text=text):
                self.assertFalse(installation_identity_candidate(text, self.task, self.key))
                (self.folder / "console.raw").write_text(text)
                self.assertFalse(self.e.can_resume(self.task))

    def test_unknown_ssh_identity_cannot_open_continuation(self):
        (self.folder / "known_hosts").write_text("192.0.2.222 " + self.key + "\n")
        self.assertFalse(self.e.can_resume(self.task))

    def test_disk_acceptance_records_audit_then_enters_normal_finish(self):
        with (
            patch("pxeye.installation.executor.Console"),
            patch.object(self.e, "accept", return_value={"passed": True, "report": self.report}),
            patch.object(self.e, "finish") as finish,
        ):
            self.e.resume(self.task)
        finish.assert_called_once()
        proof = self.task["installation_evidence"]
        self.assertEqual(proof["source"], "trusted-ssh-target-disk")
        self.assertEqual(proof["task_id"], self.task["id"])
        self.assertEqual(proof["installer_log_sha256"], "log-digest")
        self.assertEqual((self.folder / "console.raw").read_text(), self.text)
        self.assertEqual(self.site.writes, [])

    def test_failed_disk_acceptance_never_resets_or_finishes(self):
        with (
            patch("pxeye.installation.executor.Console"),
            patch("pxeye.installation.executor.time.monotonic", side_effect=[0, 0, 100, 601]),
            patch.object(
                self.e, "accept", return_value={"passed": False, "error": "TASK_RECEIPT_MISMATCH"}
            ),
            patch.object(self.e, "finish") as finish,
            patch.object(self.e, "recover_disk_boot") as recover,
        ):
            self.e.resume(self.task)
        finish.assert_not_called()
        recover.assert_not_called()
        self.assertEqual(self.task["status"], "needs_attention")
        self.assertNotIn("installation_evidence", self.task)
        self.assertEqual(self.site.writes, [])

    def test_config_drift_blocks_disk_proof_and_reboot(self):
        self.site.instances[0]["config"]["os"]["user_data"] = "changed"
        with (
            patch("pxeye.installation.executor.Console"),
            patch.object(self.e, "accept", return_value={"passed": True, "report": self.report}),
            patch.object(self.e, "finish") as finish,
        ):
            self.e.resume(self.task)
        finish.assert_not_called()
        self.assertEqual(self.task["status"], "needs_attention")
        self.assertNotIn("installation_evidence", self.task)


class BootParameterTests(unittest.TestCase):
    def test_hardware_console_and_legacy_definition_compatibility(self):
        fixture = test_management.ManagementTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        row = fixture.prepared()
        fixture.os.register({"id": row["id"], "revision": digest(row)})
        native = fixture.site.native_os[row["id"]]
        value = native["ipxeTemplateParameters"][0]["value"]
        self.assertIn("console=tty0 console=${console},115200n8 initrd=initrd", value)
        self.assertNotIn("ttyS0", value)
        fixture.os.verify_native(row, native)
        old = copy.deepcopy(native)
        iso = next(m for m in row["materials"] if m["name"] == "iso")
        old["ipxeTemplateParameters"][0]["value"] = ubuntu_boot_parameters(
            iso["url"], serial_console=False
        )
        fixture.os.verify_native(row, old)
        old["ipxeTemplateParameters"][0]["value"] += " bad=extra"
        with self.assertRaises(ValueError):
            fixture.os.verify_native(row, old)


if __name__ == "__main__":
    unittest.main()
