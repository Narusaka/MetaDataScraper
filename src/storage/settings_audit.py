import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


class SettingsAuditStore:
    """Persist value-free configuration change evidence."""

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS settings_revisions (
                    revision INTEGER PRIMARY KEY AUTOINCREMENT,
                    changed_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    changed_paths TEXT NOT NULL,
                    config_fingerprint TEXT NOT NULL
                )
                """
            )

    def record(self, actor: str, changed_paths: List[str], config_fingerprint: str) -> Dict[str, Any]:
        changed_at = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO settings_revisions (
                    changed_at, actor, changed_paths, config_fingerprint
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    changed_at,
                    str(actor or "system").strip() or "system",
                    json.dumps(sorted(set(changed_paths)), ensure_ascii=False),
                    config_fingerprint,
                ),
            )
            revision = int(cursor.lastrowid)
        return {
            "revision": revision,
            "changed_at": changed_at,
            "actor": str(actor or "system").strip() or "system",
            "changed_paths": sorted(set(changed_paths)),
            "config_fingerprint": config_fingerprint,
        }

    def list_recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 100))
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT revision, changed_at, actor, changed_paths, config_fingerprint
                FROM settings_revisions
                ORDER BY revision DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [
            {
                "revision": int(row["revision"]),
                "changed_at": row["changed_at"],
                "actor": row["actor"],
                "changed_paths": json.loads(row["changed_paths"]),
                "config_fingerprint": row["config_fingerprint"],
            }
            for row in rows
        ]

    def current_revision(self) -> int:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(revision), 0) AS revision FROM settings_revisions"
            ).fetchone()
        return int(row["revision"])
