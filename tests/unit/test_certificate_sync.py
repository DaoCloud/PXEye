"""Keep non-TLS credentials intact and refuse invalid renewal material."""

import base64
import json
import unittest
from unittest.mock import patch

from pxeye.clients.certificate_sync import sync


def encoded(text):
    return base64.b64encode(text.encode()).decode()


class CertificateSyncTests(unittest.TestCase):
    def run_sync(self, *, mismatch=False, invalid=False, unchanged=False):
        calls = []
        desired = {
            "client.crt": encoded("new-chain"),
            "client.key": encoded("new-key"),
            "ca.crt": encoded("root"),
        }

        def command(argv, *, data=None):
            calls.append((argv, data))
            if argv[0] == "kubectl" and "get" in argv:
                name = argv[argv.index("secret") + 1]
                if name == "nico-admin-client":
                    result = {
                        "data": {
                            "tls.crt": desired["client.crt"],
                            "tls.key": desired["client.key"],
                        },
                        "metadata": {"resourceVersion": "22"},
                    }
                elif name == "nico-site-ca":
                    result = {"data": {"tls.crt": desired["ca.crt"]}}
                else:
                    result = {
                        "data": (desired if unchanged else {})
                        | {"auth.json": encoded("private-operator")},
                        "metadata": {"resourceVersion": "11"},
                    }
                return json.dumps(result).encode()
            if argv[0] == "openssl":
                if "verify" in argv and invalid:
                    raise RuntimeError("invalid trust")
                if "-pubkey" in argv:
                    return b"public-key"
                if "-pubout" in argv:
                    return b"mismatch" if mismatch else b"public-key"
                return b"notAfter=future"
            return b""

        with (
            patch("pxeye.clients.certificate_sync.command", side_effect=command),
            patch("builtins.print"),
        ):
            if mismatch or invalid:
                with self.assertRaises(RuntimeError):
                    sync("test", "nico-system", "mmzhou")
            else:
                sync("test", "nico-system", "mmzhou")
        return calls

    def test_patch_only_tls_fields_and_uses_stdin(self):
        calls = self.run_sync()
        writes = [(argv, data) for argv, data in calls if "patch" in argv]
        self.assertEqual(len(writes), 1)
        argv, data = writes[0]
        self.assertIn("--patch-file=/dev/stdin", argv)
        self.assertEqual(set(json.loads(data)["data"]), {"client.crt", "client.key", "ca.crt"})
        self.assertEqual(json.loads(data)["metadata"]["resourceVersion"], "11")
        self.assertTrue(any("annotate" in argv for argv, _ in calls))
        self.assertNotIn("private-operator", str(calls))

    def test_invalid_pair_or_trust_never_writes(self):
        for options in ({"mismatch": True}, {"invalid": True}):
            calls = self.run_sync(**options)
            self.assertFalse(any("patch" in argv or "annotate" in argv for argv, _ in calls))

    def test_unchanged_secret_is_not_patched_but_mount_refresh_is_retried(self):
        calls = self.run_sync(unchanged=True)
        self.assertFalse(any("patch" in argv for argv, _ in calls))
        self.assertTrue(any("annotate" in argv for argv, _ in calls))
