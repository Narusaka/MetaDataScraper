import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List


class SQLiteTaskLedger:
    """Transactional persistence for task snapshots and their event history."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS task_snapshots (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    input_dir TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_task_snapshots_created
                    ON task_snapshots(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_task_snapshots_status
                    ON task_snapshots(status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS task_events (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    item_id TEXT,
                    timestamp TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES task_snapshots(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_task_events_task_time
                    ON task_events(task_id, timestamp, id);
                """
            )

    def load_tasks(self, max_events_per_task: int) -> Dict[str, Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, snapshot_json FROM task_snapshots ORDER BY created_at DESC"
            ).fetchall()
            tasks = {
                str(row["id"]): json.loads(row["snapshot_json"])
                for row in rows
            }
            if not tasks:
                return {}

            event_rows = connection.execute(
                """
                SELECT id, task_id, event_type, item_id, timestamp, payload_json
                FROM task_events
                ORDER BY task_id, timestamp, id
                """
            ).fetchall()

        for task in tasks.values():
            task["events"] = []
        for row in event_rows:
            task = tasks.get(str(row["task_id"]))
            if not task:
                continue
            event = {
                "id": row["id"],
                "task_id": row["task_id"],
                "type": row["event_type"],
                "timestamp": row["timestamp"],
                "payload": json.loads(row["payload_json"]),
            }
            if row["item_id"]:
                event["item_id"] = row["item_id"]
            task["events"].append(event)

        for task in tasks.values():
            task["events"] = task["events"][-max_events_per_task:]
        return tasks

    def persist_tasks(self, tasks: Iterable[Dict[str, Any]]) -> None:
        task_list = list(tasks)
        task_ids = [str(task["id"]) for task in task_list]
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for task in task_list:
                self._persist_task(connection, task)

            if task_ids:
                placeholders = ",".join("?" for _ in task_ids)
                connection.execute(
                    f"DELETE FROM task_snapshots WHERE id NOT IN ({placeholders})",
                    task_ids,
                )
            else:
                connection.execute("DELETE FROM task_snapshots")

    def persist_task(self, task: Dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._persist_task(connection, task)

    def retain_tasks(self, task_ids: Iterable[str]) -> None:
        retained = [str(task_id) for task_id in task_ids]
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if retained:
                placeholders = ",".join("?" for _ in retained)
                connection.execute(
                    f"DELETE FROM task_snapshots WHERE id NOT IN ({placeholders})",
                    retained,
                )
            else:
                connection.execute("DELETE FROM task_snapshots")

    def _persist_task(self, connection: sqlite3.Connection, task: Dict[str, Any]) -> None:
        snapshot = dict(task)
        events: List[Dict[str, Any]] = list(snapshot.pop("events", []))
        connection.execute(
            """
            INSERT INTO task_snapshots (
                id, status, input_dir, created_at, updated_at, snapshot_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status = excluded.status,
                input_dir = excluded.input_dir,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                snapshot_json = excluded.snapshot_json
            """,
            (
                task["id"],
                task.get("status") or "created",
                task.get("input_dir") or "",
                task.get("created_at") or "",
                task.get("updated_at") or task.get("created_at") or "",
                json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
            ),
        )
        connection.execute("DELETE FROM task_events WHERE task_id = ?", (task["id"],))
        connection.executemany(
            """
            INSERT INTO task_events (
                id, task_id, event_type, item_id, timestamp, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    event["id"],
                    task["id"],
                    event.get("type") or "unknown",
                    event.get("item_id"),
                    event.get("timestamp") or "",
                    json.dumps(event.get("payload") or {}, ensure_ascii=False, sort_keys=True),
                )
                for event in events
            ],
        )

    def count_tasks(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM task_snapshots").fetchone()
        return int(row["count"])

    def count_events(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM task_events").fetchone()
        return int(row["count"])
