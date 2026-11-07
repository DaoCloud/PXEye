"""Expose actionable SSH categories without leaking raw command output."""

import subprocess
import unittest
from unittest.mock import patch

from pxeye.clients.process import run


class SSHErrorTests(unittest.TestCase):
    def test_identity_change_and_authentication_errors_are_safe(self):
        for stderr, message in [
            ("REMOTE HOST IDENTIFICATION HAS CHANGED! secret-value", "主机密钥"),
            ("Permission denied secret-value", "认证失败"),
        ]:
            with patch(
                "pxeye.clients.process.subprocess.run",
                return_value=subprocess.CompletedProcess([], 255, "", stderr),
            ):
                with self.assertRaisesRegex(RuntimeError, message) as error:
                    run(["ssh", "private-argument"])
                self.assertNotIn("secret-value", str(error.exception))
                self.assertNotIn("private-argument", str(error.exception))
