"""Server ISO import uses bounded file snapshots and the existing native OS pipeline."""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pxeye.services.os_library import OSLibrary, file_sha
from pxeye.common import digest
from tests.unit.test_management import ManagementSite


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.site = ManagementSite(self.root)
        self.source = self.root / "incoming"
        self.source.mkdir()
        self.iso = self.source / "server.iso"
        self.iso.write_bytes(b"a" * 32768)
        self.site.config["os_library"]["sources"] = [
            {"id": "local", "name": "现场 ISO", "directory": str(self.source)}
        ]
        self.library = OSLibrary(self.site)

    def tearDown(self):
        self.temp.cleanup()

    def body(self):
        f = self.library.sources()["sources"][0]["files"][0]
        return {
            "name": "Source ISO",
            "source_id": "local",
            "filename": f["filename"],
            "fingerprint": f["fingerprint"],
            "sha256": "",
        }

    def begin(self):
        with patch("pxeye.services.os_library.threading.Thread"):
            public = self.library.begin_import(self.body(), "owner")
        return self.library.read(public["id"])

    def test_list_only_immediate_regular_iso_and_hide_backend_paths(self):
        (self.source / "text.txt").write_text("x")
        (self.source / "nested").mkdir()
        (self.source / "nested/hidden.iso").write_bytes(b"a" * 32768)
        (self.source / "link.iso").symlink_to(self.iso)
        os.mkfifo(self.source / "fifo.iso")
        result = self.library.sources()
        self.assertEqual([f["filename"] for f in result["sources"][0]["files"]], ["server.iso"])
        self.assertNotIn(str(self.source), json.dumps(result))

    def test_missing_directory_explains_mount_failure(self):
        self.site.config["os_library"]["sources"][0]["directory"] = str(self.root / "missing")
        self.assertIn("error", self.library.sources()["sources"][0])

    def test_arbitrary_paths_and_unconfigured_sources_rejected(self):
        body = self.body()
        for filename in ("../server.iso", "/etc/file.iso", "nested/hidden.iso", "server.iso\x00"):
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                self.library.begin_import(body | {"filename": filename}, "owner")
        with self.assertRaises(ValueError):
            self.library.begin_import(body | {"source_id": "injected"}, "owner")
        self.assertEqual(list(self.library.directory.glob("*.json")), [])

    def test_symlink_and_fifo_cannot_be_selected_by_api(self):
        body = self.body()
        (self.source / "link.iso").symlink_to(self.iso)
        os.mkfifo(self.source / "fifo.iso")
        for filename in ("link.iso", "fifo.iso"):
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                self.library.begin_import(body | {"filename": filename}, "owner")

    def test_changed_selection_rejected_before_allocating_version(self):
        body = self.body()
        self.iso.write_bytes(b"b" * 32768)
        with self.assertRaises(ValueError):
            self.library.begin_import(body, "owner")
        self.assertFalse(list(self.library.directory.glob("*.json")))

    def test_only_one_active_server_copy(self):
        row = self.begin()
        with self.assertRaises(ValueError):
            self.library.begin_import(self.body(), "owner")
        self.assertEqual(self.library.read(row["id"])["status"], "importing")

    def test_source_snapshot_survives_later_changes(self):
        row = self.begin()
        with patch.object(self.library, "extract") as extract:
            self.library.copy_source(row)
        snapshot = self.library.root / row["id"] / "install.iso"
        self.assertEqual(snapshot.read_bytes(), self.iso.read_bytes())
        self.assertEqual(self.library.read(row["id"])["received"], 32768)
        self.assertEqual(extract.call_count, 1)
        self.iso.write_bytes(b"b" * 32768)
        self.assertEqual(snapshot.read_bytes(), b"a" * 32768)

    def test_source_changed_before_worker_fails_without_extraction(self):
        row = self.begin()
        self.iso.write_bytes(b"b" * 32768)
        with patch.object(self.library, "extract") as extract:
            self.library.copy_source(row)
        self.assertEqual(self.library.read(row["id"])["status"], "failed")
        extract.assert_not_called()

    def test_replacement_during_copy_detected(self):
        row = self.begin()
        original = self.library.open_source

        def replace(source_id, filename):
            stream = original(source_id, filename)
            replacement = self.source / "replacement"
            replacement.write_bytes(b"b" * 32768)
            replacement.replace(self.iso)
            return stream

        with (
            patch.object(self.library, "open_source", side_effect=replace),
            patch.object(self.library, "extract") as extract,
        ):
            self.library.copy_source(row)
        self.assertEqual(self.library.read(row["id"])["status"], "failed")
        extract.assert_not_called()

    def test_copy_failure_preserves_source_and_can_cancel(self):
        row = self.begin()
        with patch.object(self.library, "open_source", side_effect=OSError("disk")):
            self.library.copy_source(row)
        failed = self.library.read(row["id"])
        self.assertEqual(failed["pending_operation"], "import")
        self.library.cancel({"id": row["id"], "revision": digest(failed)}, "owner")
        self.assertTrue(self.iso.exists())
        self.assertFalse((self.library.root / row["id"]).exists())

    def test_restart_requires_explicit_recopy_and_clears_partial_bytes(self):
        row = self.begin()
        snapshot = self.library.root / row["id"] / "install.iso"
        snapshot.write_bytes(b"partial")
        library = OSLibrary(self.site, recover=True)
        stopped = library.read(row["id"])
        self.assertEqual(stopped["status"], "needs_attention")
        with patch("pxeye.services.os_library.threading.Thread") as thread:
            library.recover({"id": row["id"], "revision": digest(stopped)}, "owner")
            self.assertEqual(thread.call_args.kwargs["target"], library.copy_source)
        with patch.object(library, "extract"):
            library.copy_source(library.read(row["id"]))
        self.assertEqual(snapshot.read_bytes(), b"a" * 32768)

    def test_restart_import_can_cancel_and_keeps_source(self):
        row = self.begin()
        library = OSLibrary(self.site, recover=True)
        stopped = library.read(row["id"])
        library.cancel({"id": row["id"], "revision": digest(stopped)}, "owner")
        self.assertTrue(self.iso.exists())

    def test_running_import_cannot_cancel(self):
        row = self.begin()
        with self.assertRaises(ValueError):
            self.library.cancel({"id": row["id"], "revision": digest(row)}, "owner")

    def test_recopy_waits_for_other_active_import(self):
        row = self.begin()
        row["status"] = "failed"
        self.library.save(row)
        self.begin()
        with self.assertRaises(ValueError):
            self.library.recover({"id": row["id"], "revision": digest(row)}, "owner")

    def test_prepare_uses_same_extraction_hashes_http_and_native_os(self):
        row = self.begin()

        def xorriso(argv, **kwargs):
            path = Path(argv[-1])
            path.write_bytes(
                {
                    "info.txt": b"Ubuntu-Server 24.04.5 LTS amd64",
                    "kernel": b"kernel",
                    "initrd": b"initrd",
                }[path.name]
            )

        client = MagicMock()

        def head(request, **kwargs):
            response = MagicMock()
            response.__enter__.return_value.headers = {
                "Content-Length": str(
                    (self.library.root / row["id"] / request.full_url.rsplit("/", 1)[1])
                    .stat()
                    .st_size
                )
            }
            return response

        client.open.side_effect = head
        with (
            patch("pxeye.services.os_library.subprocess.run", side_effect=xorriso),
            patch("pxeye.services.os_library.urllib.request.build_opener", return_value=client),
        ):
            self.library.copy_source(row)
        prepared = self.library.read(row["id"])
        self.assertEqual(prepared["status"], "registered")
        self.assertEqual(prepared["os_release"], "24.04")
        self.assertEqual(client.open.call_count, 3)
        self.assertEqual(prepared["materials"][0]["sha256"], file_sha(self.iso))
        self.assertEqual((self.library.root / row["id"]).stat().st_mode & 0o777, 0o755)
        self.assertEqual(len([w for w in self.site.writes if w[0] == "CreateOperatingSystem"]), 1)
        self.library.activate({"id": row["id"], "active": True})
        self.assertEqual(
            self.library.usable(row["id"], "x86_64")["source"]["filename"], "server.iso"
        )

    def test_expected_checksum_failure_never_registers(self):
        body = self.body() | {"sha256": "0" * 64}
        with patch("pxeye.services.os_library.threading.Thread"):
            row = self.library.begin_import(body, "owner")
        self.library.copy_source(self.library.read(row["id"]))
        self.assertEqual(self.library.read(row["id"])["status"], "failed")
        self.assertEqual(self.site.writes, [])


if __name__ == "__main__":
    unittest.main()
