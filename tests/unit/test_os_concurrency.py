"""OS API concurrency and task-scoped protection using real HTTP and SQLite."""

import json
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from pxeye.services.os_library import OSLibrary
from pxeye.common import digest
from tests.unit import test_console
from tests.unit.test_management import ManagementSite


class OSConcurrencyTests(unittest.TestCase):
    request = test_console.ApiTests.request

    def setUp(self):
        test_console.ApiTests.setUp(self)
        self.site = ManagementSite(Path(self.tmp.name))
        self.app.os_library = self.library = OSLibrary(self.site, store=self.app.store)
        source = Path(self.tmp.name) / "incoming"
        source.mkdir()
        (source / "new.iso").write_bytes(b"a" * 32768)
        self.site.config["os_library"]["sources"] = [
            {"id": "local", "name": "ISO", "directory": str(source)}
        ]
        _, data, headers = self.request("POST", "/api/login", {"password": "test-only-password"})
        self.headers = {"Cookie": headers["Set-Cookie"].split(";")[0], "X-CSRF-Token": data["csrf"]}

    def tearDown(self):
        if self.app.worker_lock.locked():
            self.app.worker_lock.release()
        test_console.ApiTests.tearDown(self)

    def post(self, action, body):
        return self.request("POST", "/api/operating-systems/" + action, body, self.headers)

    def prepared(self):
        row = self.library.begin(
            {"name": "New OS", "filename": "new.iso", "size": 32768, "sha256": ""}, "operator"
        )
        row = self.library.read(row["id"])
        row.update(
            status="prepared",
            architecture="x86_64",
            os_release="24.04",
            materials=[
                {
                    "name": n,
                    "url": "http://pxe.test/" + row["id"] + "/" + n,
                    "sha256": n * 16,
                    "size": 32768,
                }
                for n in ("iso", "kernel", "initrd")
            ],
        )
        self.library.save(row)
        return row

    def task(self, os_id, status="running", **fields):
        task = {
            "id": "UI-active",
            "device": "SN-active",
            "status": status,
            "installation_plan": {"os_id": os_id},
            **fields,
        }
        with self.app.store.db() as db:
            db.execute(
                "INSERT OR REPLACE INTO tasks VALUES (?,?,?,?,?,?)",
                (task["id"], task["device"], status, json.dumps(task), 1, "request-key"),
            )

    def register(self, row):
        status, result, _ = self.post("register", {"id": row["id"], "revision": digest(row)})
        self.assertEqual(status, 200, result)
        return self.library.read(row["id"])

    def test_import_upload_prepare_with_busy_installer(self):
        self.task(str(uuid.uuid4()))
        self.app.worker_lock.acquire()
        f = self.library.sources()["sources"][0]["files"][0]
        with patch.object(self.library, "copy_source"):
            status, row, _ = self.post(
                "import",
                {
                    "name": "Other ISO",
                    "source_id": "local",
                    "filename": f["filename"],
                    "fingerprint": f["fingerprint"],
                    "sha256": "",
                },
            )
        self.assertEqual(status, 202, row)
        status, row, _ = self.post(
            "upload", {"name": "Uploaded OS", "filename": "new.iso", "size": 32768, "sha256": ""}
        )
        self.assertEqual(status, 201, row)
        saved = self.library.read(row["id"])
        saved["received"] = saved["size"]
        self.library.save(saved)
        with patch.object(self.library, "extract"):
            status, result, _ = self.post("prepare", {"id": row["id"]})
        self.assertEqual(status, 202, result)

    def test_other_os_register_enable_disable_cancel_recover_with_busy_installer(self):
        self.task(str(uuid.uuid4()))
        self.app.worker_lock.acquire()
        row = self.register(self.prepared())
        for active in (True, False):
            status, result, _ = self.post("activate", {"id": row["id"], "active": active})
            self.assertEqual(status, 200, result)
        failed = self.prepared()
        failed.update(status="failed", received=failed["size"])
        self.library.save(failed)
        with patch.object(self.library, "extract"):
            status, result, _ = self.post(
                "recover", {"id": failed["id"], "revision": digest(failed)}
            )
        self.assertEqual(status, 200, result)
        cancelled = self.prepared()
        status, result, _ = self.post(
            "cancel", {"id": cancelled["id"], "revision": digest(cancelled)}
        )
        self.assertEqual(status, 200, result)
        self.assertFalse((self.library.root / cancelled["id"]).exists())

    def test_protect_all_active_states_and_release_after_completion(self):
        row = self.register(self.prepared())
        self.post("activate", {"id": row["id"], "active": True})
        for state in ("queued", "running", "needs_attention"):
            self.task(row["id"], state)
            actions = [("activate", {"id": row["id"], "active": False})] + [
                (a, {"id": row["id"], "revision": digest(row)})
                for a in ("recover", "cancel", "register")
            ]
            for action, body in actions:
                with self.subTest(state=state, action=action):
                    status, result, _ = self.post(action, body)
                    self.assertEqual(status, 400, result)
                    self.assertIn("UI-active", result["error"])
            self.assertTrue(self.site.native_os[row["id"]]["isActive"])
        self.task(row["id"], "completed")
        self.assertEqual(self.post("activate", {"id": row["id"], "active": False})[0], 200)

    def test_list_explains_frozen_task_reference(self):
        row = self.register(self.prepared())
        self.task(
            None,
            installation_plan={"effective_config": {"os_id": row["id"]}},
            execution_device={"os_id": row["id"]},
        )
        status, data, _ = self.request("GET", "/api/operating-systems", headers=self.headers)
        self.assertEqual(status, 200)
        result = data["operating_systems"][0]
        self.assertEqual(
            result["usage"], [{"id": "UI-active", "device": "SN-active", "status": "running"}]
        )
        self.assertIn("UI-active", result["disable_reason"])

    def test_legacy_rendered_variant_is_protected(self):
        row = self.register(self.prepared())
        self.task(None)
        folder = self.site.data / "tasks" / "UI-active"
        folder.mkdir(parents=True)
        (folder / "rendered-os.json").write_text(
            json.dumps({"variant": {"OperatingSystemId": row["id"]}})
        )
        self.assertEqual(self.post("activate", {"id": row["id"], "active": False})[0], 400)

    def test_reservation_and_disable_share_short_lock(self):
        row = self.register(self.prepared())
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        errors = []

        def reserve():
            def claim():
                entered.set()
                if not release.wait(3):
                    raise RuntimeError("test timeout")
                self.task(row["id"], "queued")

            self.app.configure(claim)

        def disable():
            try:
                self.library.operate("activate", {"id": row["id"], "active": False}, "operator")
            except ValueError as error:
                errors.append(str(error))
            finally:
                finished.set()

        worker = threading.Thread(target=reserve)
        worker.start()
        self.assertTrue(entered.wait(2))
        other = threading.Thread(target=disable)
        other.start()
        try:
            self.assertFalse(finished.wait(0.1))
        finally:
            release.set()
            worker.join(3)
            other.join(3)
        self.assertTrue(finished.is_set())
        self.assertEqual(len(errors), 1)
        self.assertIn("UI-active", errors[0])


if __name__ == "__main__":
    unittest.main()
