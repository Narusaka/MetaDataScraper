import re
import sqlite3
import threading
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def normalize_match_title(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"\s*\(\d{4}\)\s*$", "", text)
    text = re.sub(r"[\W_]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


class MatchMemoryStore:
    """SQLite-backed memory of explicit user match decisions."""

    def __init__(self, db_path: str = "logs/matches.db"):
        self.db_path = Path(db_path)
        self._lock = threading.RLock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS confirmed_matches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    normalized_title TEXT NOT NULL,
                    display_title TEXT NOT NULL,
                    year INTEGER NOT NULL DEFAULT 0,
                    media_type TEXT NOT NULL CHECK(media_type IN ('movie', 'tv')),
                    tmdb_id INTEGER NOT NULL,
                    source_task_id TEXT,
                    source_item_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_used_at TEXT,
                    use_count INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(normalized_title, year, media_type)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_confirmed_matches_lookup "
                "ON confirmed_matches(normalized_title, media_type, year)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS rejected_matches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    normalized_title TEXT NOT NULL,
                    display_title TEXT NOT NULL,
                    year INTEGER NOT NULL DEFAULT 0,
                    media_type TEXT NOT NULL CHECK(media_type IN ('movie', 'tv')),
                    tmdb_id INTEGER NOT NULL,
                    reason TEXT NOT NULL DEFAULT 'user_rejected_candidate',
                    source_task_id TEXT,
                    source_item_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_hit_at TEXT,
                    hit_count INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(normalized_title, year, media_type, tmdb_id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_rejected_matches_lookup "
                "ON rejected_matches(normalized_title, media_type, tmdb_id, year)"
            )

    def remember(
        self,
        title: str,
        tmdb_id: int,
        media_type: str,
        year: Optional[int] = None,
        source_task_id: Optional[str] = None,
        source_item_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_title = normalize_match_title(title)
        if not normalized_title:
            raise ValueError("Match title is required")
        if media_type not in {"movie", "tv"}:
            raise ValueError("Media type must be movie or tv")
        if int(tmdb_id) <= 0:
            raise ValueError("TMDB ID must be positive")

        now = datetime.now(timezone.utc).isoformat()
        normalized_year = int(year or 0)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO confirmed_matches (
                    normalized_title, display_title, year, media_type, tmdb_id,
                    source_task_id, source_item_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(normalized_title, year, media_type) DO UPDATE SET
                    display_title = excluded.display_title,
                    tmdb_id = excluded.tmdb_id,
                    source_task_id = excluded.source_task_id,
                    source_item_id = excluded.source_item_id,
                    updated_at = excluded.updated_at
                """,
                (
                    normalized_title,
                    str(title).strip(),
                    normalized_year,
                    media_type,
                    int(tmdb_id),
                    source_task_id,
                    source_item_id,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM confirmed_matches
                WHERE normalized_title = ? AND year = ? AND media_type = ?
                """,
                (normalized_title, normalized_year, media_type),
            ).fetchone()
            connection.execute(
                """
                DELETE FROM rejected_matches
                WHERE normalized_title = ? AND media_type = ? AND tmdb_id = ?
                  AND (year = ? OR year = 0 OR ? = 0)
                """,
                (
                    normalized_title,
                    media_type,
                    int(tmdb_id),
                    normalized_year,
                    normalized_year,
                ),
            )
        return dict(row)

    def reject(
        self,
        title: str,
        tmdb_id: int,
        media_type: str,
        year: Optional[int] = None,
        reason: str = "user_rejected_candidate",
        source_task_id: Optional[str] = None,
        source_item_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_title = normalize_match_title(title)
        if not normalized_title:
            raise ValueError("Match title is required")
        if media_type not in {"movie", "tv"}:
            raise ValueError("Media type must be movie or tv")
        if int(tmdb_id) <= 0:
            raise ValueError("TMDB ID must be positive")

        now = datetime.now(timezone.utc).isoformat()
        normalized_year = int(year or 0)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO rejected_matches (
                    normalized_title, display_title, year, media_type, tmdb_id,
                    reason, source_task_id, source_item_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(normalized_title, year, media_type, tmdb_id) DO UPDATE SET
                    display_title = excluded.display_title,
                    reason = excluded.reason,
                    source_task_id = excluded.source_task_id,
                    source_item_id = excluded.source_item_id,
                    updated_at = excluded.updated_at
                """,
                (
                    normalized_title,
                    str(title).strip(),
                    normalized_year,
                    media_type,
                    int(tmdb_id),
                    str(reason or "user_rejected_candidate"),
                    source_task_id,
                    source_item_id,
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                DELETE FROM confirmed_matches
                WHERE normalized_title = ? AND year = ? AND media_type = ? AND tmdb_id = ?
                """,
                (normalized_title, normalized_year, media_type, int(tmdb_id)),
            )
            row = connection.execute(
                """
                SELECT * FROM rejected_matches
                WHERE normalized_title = ? AND year = ? AND media_type = ? AND tmdb_id = ?
                """,
                (normalized_title, normalized_year, media_type, int(tmdb_id)),
            ).fetchone()
        return dict(row)

    def is_rejected(
        self,
        title: str,
        tmdb_id: int,
        media_type: str,
        year: Optional[int] = None,
        increment: bool = True,
    ) -> Optional[Dict[str, Any]]:
        normalized_title = normalize_match_title(title)
        if not normalized_title or media_type not in {"movie", "tv"} or int(tmdb_id) <= 0:
            return None

        target_year = int(year or 0)
        year_clause = "AND (year = ? OR year = 0)" if target_year else ""
        params: List[Any] = [normalized_title, media_type, int(tmdb_id)]
        if target_year:
            params.append(target_year)
        with self._lock, self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT * FROM rejected_matches
                WHERE normalized_title = ? AND media_type = ? AND tmdb_id = ?
                {year_clause}
                ORDER BY CASE WHEN year = ? THEN 0 ELSE 1 END, updated_at DESC
                LIMIT 1
                """ if target_year else """
                SELECT * FROM rejected_matches
                WHERE normalized_title = ? AND media_type = ? AND tmdb_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                params + ([target_year] if target_year else []),
            ).fetchone()
            if not row:
                return None
            result = dict(row)
            if increment:
                now = datetime.now(timezone.utc).isoformat()
                connection.execute(
                    """
                    UPDATE rejected_matches
                    SET hit_count = hit_count + 1, last_hit_at = ?
                    WHERE id = ?
                    """,
                    (now, result["id"]),
                )
                result["hit_count"] += 1
                result["last_hit_at"] = now
            return result

    def lookup(
        self,
        title: str,
        year: Optional[int] = None,
        media_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        normalized_title = normalize_match_title(title)
        if not normalized_title:
            return None

        clauses = ["normalized_title = ?"]
        params: List[Any] = [normalized_title]
        if media_type in {"movie", "tv"}:
            clauses.append("media_type = ?")
            params.append(media_type)

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM confirmed_matches WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC",
                params,
            ).fetchall()
            candidates = [dict(row) for row in rows]

            target_year = int(year or 0)
            if target_year:
                exact = [item for item in candidates if item["year"] == target_year]
                candidates = exact or [item for item in candidates if item["year"] == 0]

            unique_targets = {(item["tmdb_id"], item["media_type"]) for item in candidates}
            if len(unique_targets) != 1:
                return None
            selected = candidates[0]
            now = datetime.now(timezone.utc).isoformat()
            connection.execute(
                """
                UPDATE confirmed_matches
                SET use_count = use_count + 1, last_used_at = ?
                WHERE id = ?
                """,
                (now, selected["id"]),
            )
            selected["use_count"] += 1
            selected["last_used_at"] = now
            return selected

    def list_matches(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM confirmed_matches
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 1000)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete(self, match_id: int) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM confirmed_matches WHERE id = ?", (int(match_id),))
            return cursor.rowcount > 0

    def list_rejections(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM rejected_matches
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 1000)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_rejection(self, rejection_id: int) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM rejected_matches WHERE id = ?",
                (int(rejection_id),),
            )
            return cursor.rowcount > 0


match_memory_store = MatchMemoryStore()
