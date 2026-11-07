"""Expired client identities fail before network retries; mounted renewal is reread."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pxeye.services.execution import Adapter
from pxeye.clients.errors import CoreConnectionError


class CoreCertificateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.adapter = Adapter.__new__(Adapter)
        self.adapter.secrets = Path(self.temp.name)
        self.path = self.adapter.secrets / "client.crt"
        self.path.write_text("fixture")
        self.dates = "notBefore=Nov  4 00:00:00 2026 GMT\nnotAfter=Nov  5 00:00:00 2026 GMT\n"

    @patch("pxeye.clients.core.run")
    def test_expired_rpc_stops_before_transport(self, run):
        run.return_value = self.dates
        with patch("pxeye.clients.core.time.time", return_value=1793923200):
            with self.assertRaises(CoreConnectionError) as error:
                self.adapter.rpc("FindOperatingSystemIds", {})
        self.assertEqual(error.exception.code, "core_certificate_expired")
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][0], "openssl")

    @patch("pxeye.clients.core.run")
    def test_renewal_refreshes_cached_expiry(self, run):
        run.return_value = self.dates
        with patch("pxeye.clients.core.time.time", return_value=1793750400):
            self.adapter.check_core_certificate()
            self.adapter.check_core_certificate()
            self.assertEqual(run.call_count, 1)
        replacement = self.path.with_suffix(".next")
        replacement.write_text("renewed-fixture")
        replacement.replace(self.path)
        run.return_value = self.dates.replace("Nov  5", "Nov  7")
        with patch("pxeye.clients.core.time.time", return_value=1793923200):
            self.adapter.check_core_certificate()
        self.assertEqual(run.call_count, 2)

    def test_missing_certificate_is_actionable(self):
        self.path.unlink()
        with self.assertRaises(CoreConnectionError) as error:
            self.adapter.check_core_certificate()
        self.assertEqual(error.exception.code, "core_certificate_invalid")
