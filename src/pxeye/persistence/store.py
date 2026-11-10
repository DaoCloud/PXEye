"""Persistent task, session, and preflight state for a single execution service."""

import json
import sqlite3
import time
import threading
from contextlib import contextmanager
from pathlib import Path

ACTIVE = ("queued", "running", "needs_attention")
_stores = {}
_stores_lock = threading.RLock()


def get_store(path):
    """Share repository initialization, keeping connections scoped per operation."""
    key = str(Path(path).resolve())
    with _stores_lock:
        if key not in _stores:
            _stores[key] = Store(key)
        return _stores[key]


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS device_plans (serial TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS equipment_records (
                    bucket TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL,
                    PRIMARY KEY(bucket, id)
                );
                CREATE TABLE IF NOT EXISTS equipment_planning (
                    id TEXT PRIMARY KEY, serial TEXT NOT NULL UNIQUE, data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS install_profiles (id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS device_plan_versions (revision TEXT PRIMARY KEY, serial TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, device TEXT NOT NULL, status TEXT NOT NULL,
                    data TEXT NOT NULL, created REAL NOT NULL, request_key TEXT UNIQUE NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS active_device ON tasks(device)
                    WHERE status IN ('queued','running','needs_attention');
                CREATE TABLE IF NOT EXISTS preflights (
                    id TEXT PRIMARY KEY, data TEXT NOT NULL, expires REAL NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS batches (
                    id TEXT PRIMARY KEY, data TEXT NOT NULL, created REAL NOT NULL,
                    request_key TEXT UNIQUE NOT NULL
                );
                CREATE TABLE IF NOT EXISTS installer_events (
                    task_id TEXT NOT NULL, attempt TEXT NOT NULL, stage TEXT NOT NULL,
                    payload TEXT NOT NULL, received REAL NOT NULL,
                    PRIMARY KEY (task_id,attempt,stage)
                );
                CREATE TABLE IF NOT EXISTS topology_layout (
                    id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL, updated REAL NOT NULL
                );
            """)
            db.execute(
                "INSERT OR IGNORE INTO schema_migrations(version,applied) VALUES(1,?)",
                (time.time(),),
            )
            db.execute(
                "INSERT OR IGNORE INTO schema_migrations(version,applied) VALUES(2,?)",
                (time.time(),),
            )

        Path(self.path).chmod(0o600)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def tasks(self):
        with self.db() as db:
            return [
                json.loads(x["data"])
                for x in db.execute("SELECT data FROM tasks ORDER BY created DESC LIMIT 100")
            ]

    def topology_layout(self):
        with self.db() as db:
            row = db.execute("SELECT data,updated FROM topology_layout WHERE id=1").fetchone()
            if not row:
                return {"racks": [], "updated_at": None}
            result = json.loads(row["data"])
            result["updated_at"] = row["updated"]
            return result

    def save_topology_layout(self, layout):
        saved = {"racks": layout["racks"]}
        updated = time.time()
        with self.db() as db:
            db.execute(
                """INSERT INTO topology_layout(id,data,updated) VALUES(1,?,?)
                          ON CONFLICT(id) DO UPDATE SET data=excluded.data,updated=excluded.updated""",
                (json.dumps(saved, ensure_ascii=False), updated),
            )
        return {"racks": saved["racks"], "updated_at": updated}

    def get(self, task_id):
        with self.db() as db:
            row = db.execute("SELECT data FROM tasks WHERE id=?", (task_id,)).fetchone()
            return json.loads(row["data"]) if row else None

    def save(self, data):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM tasks WHERE id=?", (data["id"],)).fetchone()
            if row:
                # Operator skips are monotonic and may arrive while a worker holds an older task.
                skips = json.loads(row["data"]).get("acceptance_skips", {})
                if skips:
                    data["acceptance_skips"] = skips
                    if data.get("receipt"):
                        data["receipt"]["acceptance_skips"] = skips
            db.execute(
                "UPDATE tasks SET status=?,data=? WHERE id=?",
                (data["status"], json.dumps(data), data["id"]),
            )

    def active(self, device):
        with self.db() as db:
            row = db.execute(
                "SELECT data FROM tasks WHERE device=? AND status IN ('queued','running','needs_attention')",
                (device,),
            ).fetchone()
            return json.loads(row["data"]) if row else None

    def batch(self, key):
        with self.db() as db:
            row = db.execute(
                "SELECT data FROM batches WHERE id=? OR request_key=?", (key, key)
            ).fetchone()
            if not row:
                return None
            result = json.loads(row["data"])
            children = [
                json.loads(r["data"])
                for r in db.execute(
                    "SELECT data FROM tasks WHERE id IN ("
                    + ",".join("?" for _ in result["task_ids"])
                    + ")",
                    result["task_ids"],
                )
            ]
        by_id = {t["id"]: t for t in children}
        result["tasks"] = [by_id[k] for k in result["task_ids"]]
        result["counts"] = {
            status: sum(t["status"] == status for t in children)
            for status in ACTIVE + ("completed", "cancelled")
        }
        result["status"] = (
            "running"
            if result["counts"]["running"] or result["counts"]["queued"]
            else "needs_attention"
            if result["counts"]["needs_attention"]
            else "cancelled"
            if result["counts"]["cancelled"] and not result["counts"]["completed"]
            else "completed"
        )
        return result

    def batches(self):
        with self.db() as db:
            ids = [
                r["id"]
                for r in db.execute("SELECT id FROM batches ORDER BY created DESC LIMIT 100")
            ]
        return [self.batch(key) for key in ids]

    def queued(self):
        with self.db() as db:
            return [
                json.loads(r["data"])
                for r in db.execute(
                    "SELECT data FROM tasks WHERE status='queued' ORDER BY created,id"
                )
            ]

    def incomplete(self):
        with self.db() as db:
            return [
                json.loads(r["data"])
                for r in db.execute(
                    "SELECT data FROM tasks WHERE status IN ('queued','running','needs_attention')"
                )
            ]

    def claim_batch(self, check_id, batch, tasks, request_key, owner):
        """Persist every child and its reservations atomically before any remote action."""
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT id FROM batches WHERE request_key=?", (request_key,)
            ).fetchone()
            if existing:
                return existing["id"], False
            row = db.execute("SELECT * FROM preflights WHERE id=?", (check_id,)).fetchone()
            if not row or row["used"] or row["expires"] < time.time():
                raise ValueError("批量预检已失效，请重新检查。")
            check = json.loads(row["data"])
            if (
                check["owner"] != owner
                or not check["passed"]
                or check["mode"] != batch["mode"]
                or len(check["checks"]) != len(tasks)
            ):
                raise ValueError("批量预检与提交内容不匹配或存在阻断项。")
            try:
                for index, (candidate, task) in enumerate(zip(check["checks"], tasks)):
                    if any(
                        candidate[k] != task[k] for k in ("device", "hostname", "installation_plan")
                    ):
                        raise ValueError("逐机配置或规划在预检后发生变化。")
                    task["preflight"] = candidate
                    db.execute(
                        "INSERT INTO tasks VALUES (?,?,?,?,?,?)",
                        (
                            task["id"],
                            task["device"],
                            task["status"],
                            json.dumps(task),
                            time.time() + index / 1000,
                            request_key + ":" + str(index),
                        ),
                    )
                db.execute(
                    "INSERT INTO batches VALUES (?,?,?,?)",
                    (batch["id"], json.dumps(batch), time.time(), request_key),
                )
            except sqlite3.IntegrityError:
                raise ValueError("至少一台设备已有任务；本批未提交，请刷新。") from None
            db.execute("UPDATE preflights SET used=1 WHERE id=?", (check_id,))
            return batch["id"], True

    def preflight(self, key, data, lifetime=300):
        with self.db() as db:
            db.execute(
                "INSERT INTO preflights(id,data,expires) VALUES (?,?,?)",
                (key, json.dumps(data), time.time() + lifetime),
            )

    def claim(self, check_id, task, request_key):
        """Consume the check and claim a device in one transaction; duplicates do not reboot."""
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT data FROM tasks WHERE request_key=?", (request_key,)
            ).fetchone()
            if old:
                return json.loads(old["data"]), False
            row = db.execute("SELECT * FROM preflights WHERE id=?", (check_id,)).fetchone()
            if not row or row["used"] or row["expires"] < time.time():
                raise ValueError("预检已失效或已提交，请重新检查。")
            check = json.loads(row["data"])
            if check["device"] != task["device"] or check["hostname"] != task["hostname"]:
                raise ValueError("设备或 hostname 与预检不一致。")
            if not check["passed"]:
                raise ValueError("存在预检阻断项。")
            if task.get("installation_plan") != check.get("installation_plan"):
                raise ValueError("设备或网络规划在预检后发生变化，请重新检查。")
            task["preflight"] = check
            try:
                db.execute(
                    "INSERT INTO tasks VALUES (?,?,?,?,?,?)",
                    (
                        task["id"],
                        task["device"],
                        task["status"],
                        json.dumps(task),
                        time.time(),
                        request_key,
                    ),
                )
            except sqlite3.IntegrityError:
                raise ValueError("设备已有活动任务；不能重复提交。") from None
            db.execute("UPDATE preflights SET used=1 WHERE id=?", (check_id,))
            return task, True
