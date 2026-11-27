"""Site-wide install limit: one queue, per-task ownership, nothing waits for another batch."""

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from pxeye.persistence.store import Store
from pxeye.services.tasks import TaskCoordinator


def wait_until(condition, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


class Executor:
    """Stands in for the installation executor; every run waits for the test to release it."""

    def __init__(self, store):
        self.store = store
        self.lock = threading.Lock()
        self.runs, self.resumes, self.closed = [], [], []
        self.gates, self.outcomes = {}, {}

    def gate(self, task_id):
        with self.lock:
            return self.gates.setdefault(task_id, threading.Event())

    def release(self, *task_ids):
        for task_id in task_ids:
            self.gate(task_id).set()

    def run(self, task):
        if self.outcomes.get(task["id"]) == "escapes":
            with self.lock:
                self.runs.append(task["id"])
            raise RuntimeError("boom")
        # Recorded as started only once the status says so, as tests read both.
        task["status"] = "running"
        self.store.save(task)
        with self.lock:
            self.runs.append(task["id"])
        self.gate(task["id"]).wait(10)
        if (self.store.get(task["id"]) or {}).get("close_request"):
            return self.finish_close_requested(task)
        task["status"] = self.outcomes.get(task["id"], "completed")
        self.store.save(task)

    def resume(self, task):
        with self.lock:
            self.resumes.append(task["id"])
        self.gate(task["id"]).wait(10)
        task["status"] = "completed"
        self.store.save(task)

    def finish_close_requested(self, task):
        current = self.store.get(task["id"]) or task
        request = current.get("close_request")
        if request and request.get("state") == "requested":
            request["state"] = "completed"
            current["status"] = "cancelled"
            self.store.save(current)
            with self.lock:
                self.closed.append(current["id"])
        return current

    def recovery_step(self, *args):
        pass

    def can_resume(self, task):
        return True

    can_prepare = can_retry_install = can_restart_preinstall = lambda self, task: False


class Resources:
    def __init__(self):
        self.applied = []

    def apply_network(self, sid):
        self.applied.append(sid)
        return {"status": "applied"}


class InstallQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = Store(root / "console.sqlite3")
        self.executor = Executor(self.store)
        self.resources = Resources()
        self.config = {"default_install_concurrency": 2}
        self.coordinator = TaskCoordinator(
            config=self.config,
            adapter=SimpleNamespace(data=root, config=self.config),
            store=self.store,
            executor=self.executor,
            resources=self.resources,
            onboarding=None,
            device_config=None,
            os_library=None,
        )
        self.created = 0

    def tearDown(self):
        # Let every worker finish before the database goes away.
        self.executor.release(*[r[0] for r in self.rows()])
        wait_until(lambda: not self.coordinator.owned)
        self.tmp.cleanup()

    def rows(self):
        with self.store.db() as db:
            return [(r["id"], r["status"]) for r in db.execute("SELECT id,status FROM tasks")]

    def add(self, task_id, status="queued", batch="b1"):
        self.created += 1
        task = {"id": task_id, "device": "SN-" + task_id, "status": status, "batch_id": batch}
        with self.store.db() as db:
            db.execute(
                "INSERT INTO tasks(id,device,status,data,created,request_key) VALUES(?,?,?,?,?,?)",
                (task_id, task["device"], status, json.dumps(task), self.created, "key-" + task_id),
            )
        return task

    def status(self, task_id):
        return self.store.get(task_id)["status"]

    def started(self, *task_ids):
        return wait_until(lambda: set(task_ids) <= set(self.executor.runs))

    def test_runs_up_to_the_limit_then_refills_oldest_first(self):
        for task_id in ("t1", "t2", "t3", "t4"):
            self.add(task_id)
        self.coordinator.start_queue()
        self.assertTrue(self.started("t1", "t2"))
        time.sleep(0.1)
        self.assertEqual(set(self.executor.runs), {"t1", "t2"})
        self.executor.release("t1")
        self.assertTrue(self.started("t3"))
        time.sleep(0.1)
        self.assertNotIn("t4", self.executor.runs)
        self.executor.release("t2")
        self.assertTrue(self.started("t4"))

    def test_a_later_batch_uses_a_free_slot_without_waiting_for_the_first(self):
        self.add("t1", batch="first")
        self.coordinator.start_queue()
        self.assertTrue(self.started("t1"))
        self.add("t2", batch="second")
        self.coordinator.start_queue()
        self.assertTrue(self.started("t2"))
        self.assertEqual(self.status("t1"), "running")

    def test_a_device_that_needs_attention_gives_up_its_slot(self):
        self.config["default_install_concurrency"] = 1
        self.add("t1")
        self.add("t2")
        self.executor.outcomes["t1"] = "needs_attention"
        self.coordinator.start_queue()
        self.assertTrue(self.started("t1"))
        self.executor.release("t1")
        self.assertTrue(self.started("t2"))
        self.assertEqual(self.status("t1"), "needs_attention")

    def test_a_task_is_never_started_twice(self):
        self.add("t1")
        threads = [threading.Thread(target=self.coordinator.start_queue) for _ in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertTrue(self.started("t1"))
        time.sleep(0.1)
        self.assertEqual(self.executor.runs.count("t1"), 1)

    def test_a_raised_limit_applies_to_devices_already_waiting(self):
        self.config["default_install_concurrency"] = 1
        self.add("t1")
        self.add("t2")
        self.coordinator.start_queue()
        self.assertTrue(self.started("t1"))
        time.sleep(0.1)
        self.assertNotIn("t2", self.executor.runs)
        self.config["default_install_concurrency"] = 2
        self.coordinator.start_queue()
        self.assertTrue(self.started("t2"))

    def test_a_failure_that_escapes_the_executor_parks_the_task(self):
        self.config["default_install_concurrency"] = 1
        self.add("t1")
        self.add("t2")
        self.executor.outcomes["t1"] = "escapes"
        self.coordinator.start_queue()
        self.assertTrue(self.started("t2"))
        self.assertEqual(self.executor.runs.count("t1"), 1)
        self.assertEqual(self.status("t1"), "needs_attention")
        self.assertIn("任务未能启动", self.store.get("t1")["error"])

    def test_acceptance_can_continue_while_other_devices_install(self):
        self.config["default_install_concurrency"] = 1
        self.add("t1")
        self.add("t2")
        self.add("paused", status="needs_attention")
        self.coordinator.start_queue()
        self.assertTrue(self.started("t1"))
        body = {"confirm_serial": "SN-paused", "confirm_reboot": True}
        self.coordinator.resume("paused", body, "operator")
        self.assertTrue(wait_until(lambda: self.executor.resumes == ["paused"]))
        # The same task cannot be continued twice, and it takes no install slot.
        self.store.save({**self.store.get("paused"), "status": "needs_attention"})
        with self.assertRaisesRegex(ValueError, "正在执行中"):
            self.coordinator.resume("paused", body, "operator")
        self.assertEqual(self.status("t1"), "running")
        self.assertNotIn("t2", self.executor.runs)
        self.executor.release("paused")
        self.assertTrue(wait_until(lambda: "paused" not in self.coordinator.owned))
        self.assertNotIn("t2", self.executor.runs)

    def test_a_paused_task_closes_at_once_while_other_devices_install(self):
        self.add("t1")
        self.add("paused", status="needs_attention")
        self.coordinator.start_queue()
        self.assertTrue(self.started("t1"))
        result = self.coordinator.close_task("paused", {"confirm_serial": "SN-paused"}, "operator")
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(self.status("t1"), "running")

    def test_a_waiting_task_can_be_closed_and_is_never_started(self):
        self.config["default_install_concurrency"] = 1
        self.add("t1")
        self.add("t2")
        self.coordinator.start_queue()
        self.assertTrue(self.started("t1"))
        result = self.coordinator.close_task("t2", {"confirm_serial": "SN-t2"}, "operator")
        self.assertEqual(result["status"], "cancelled")
        self.executor.release("t1")
        self.assertTrue(wait_until(lambda: not self.coordinator.owned))
        self.assertNotIn("t2", self.executor.runs)

    def test_closing_a_running_task_waits_only_for_its_own_worker(self):
        self.add("t1")
        self.add("t2")
        self.coordinator.start_queue()
        self.assertTrue(self.started("t1", "t2"))
        self.assertTrue(wait_until(lambda: self.status("t1") == self.status("t2") == "running"))
        result = self.coordinator.close_task("t1", {"confirm_serial": "SN-t1"}, "operator")
        self.assertEqual(result["status"], "running")
        self.executor.release("t1")
        self.assertTrue(wait_until(lambda: self.status("t1") == "cancelled"))
        self.assertEqual(self.status("t2"), "running")

    def test_site_configuration_waits_until_nothing_installs_or_waits(self):
        self.config["default_install_concurrency"] = 1
        self.add("t1")
        self.add("t2")
        self.coordinator.start_queue()
        self.assertTrue(self.started("t1"))
        with self.assertRaisesRegex(ValueError, "已有安装或资源操作执行中"):
            self.coordinator.configure(lambda: "changed")
        with self.assertRaisesRegex(ValueError, "已有安装或资源应用任务执行中"):
            self.coordinator.apply_network("segment")
        # Steps of installing itself are not held back by other devices.
        self.assertEqual(
            self.coordinator.configure(lambda: "checked", during_installs=True), "checked"
        )
        self.executor.release("t1", "t2")
        self.assertTrue(wait_until(lambda: not self.coordinator.installs_busy()))
        self.assertEqual(self.coordinator.configure(lambda: "changed"), "changed")
        self.assertEqual(self.coordinator.apply_network("segment"), {"status": "applied"})
        self.assertEqual(self.resources.applied, ["segment"])

    def test_one_check_or_claim_at_a_time(self):
        entered, leave = threading.Event(), threading.Event()

        def slow():
            entered.set()
            leave.wait(5)
            return "done"

        worker = threading.Thread(
            target=lambda: self.coordinator.configure(slow, during_installs=True)
        )
        worker.start()
        self.assertTrue(entered.wait(5))
        with self.assertRaisesRegex(ValueError, "已有核对或配置操作执行中"):
            self.coordinator.configure(lambda: "second", during_installs=True)
        self.add("paused", status="needs_attention")
        with self.assertRaisesRegex(ValueError, "已有核对或配置操作执行中"):
            self.coordinator.resume(
                "paused", {"confirm_serial": "SN-paused", "confirm_reboot": True}, "operator"
            )
        self.assertNotIn("paused", self.coordinator.owned)
        leave.set()
        worker.join()

    def test_interrupted_tasks_are_picked_up_side_by_side_after_a_restart(self):
        self.add("r1", status="needs_attention")
        self.add("r2", status="needs_attention")
        self.add("t1")
        seen, leave = [], threading.Event()

        def recover_one(task_id, auto_repair):
            seen.append(task_id)
            leave.wait(5)

        self.coordinator.recover_one = recover_one
        self.coordinator.start_recovered(["r1", "r2"])
        self.assertTrue(wait_until(lambda: set(seen) == {"r1", "r2"}))
        # They count against the limit of two, so the waiting task holds back.
        time.sleep(0.1)
        self.assertNotIn("t1", self.executor.runs)
        leave.set()
        self.assertTrue(self.started("t1"))


if __name__ == "__main__":
    unittest.main()
