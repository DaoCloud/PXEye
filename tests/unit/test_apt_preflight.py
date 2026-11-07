"""APT readiness must be proven without touching the installer's package database."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pxeye.installation.apt_preflight import check


class AptPreflightTests(unittest.TestCase):
    def test_signed_fresh_indices_and_resolution_use_only_isolated_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {
                "apt": {
                    "primary": [{"arches": ["default"], "uri": "https://mirror.example/ubuntu"}]
                },
                "packages": ["sudo"],
                "kernel": {"package": "linux-generic"},
            }
            with patch("pxeye.installation.apt_preflight.subprocess.run") as run:
                check(config, "noble", "amd64", root)
            calls = [c.args[0] for c in run.call_args_list]
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0][-1], "update")
            self.assertIn("APT::Update::Error-Mode=any", calls[0])
            self.assertIn("--simulate", calls[1])
            self.assertIn("linux-generic", calls[1])
            self.assertIn("Dir::State::status=" + str(root / "status"), calls[1])
            self.assertNotIn("--allow-unauthenticated", calls[0])
            self.assertIn(
                "https://mirror.example/ubuntu noble-updates", (root / "sources.list").read_text()
            )

    def test_broken_dependencies_do_not_produce_success_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch(
                "pxeye.installation.apt_preflight.subprocess.run",
                side_effect=[None, subprocess.CalledProcessError(100, ["apt-get"])],
            ):
                with self.assertRaises(subprocess.CalledProcessError):
                    check({}, "noble", "amd64", root)
            self.assertFalse((root / "result.json").exists())

    def test_unrepresentable_source_configuration_fails_before_network(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("pxeye.installation.apt_preflight.subprocess.run") as run,
        ):
            with self.assertRaises(ValueError):
                check({"apt": {"preserve_sources_list": True}}, "noble", "amd64", Path(directory))
            run.assert_not_called()
