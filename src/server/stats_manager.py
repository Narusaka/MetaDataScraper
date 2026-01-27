
import sqlite3
from pathlib import Path
from datetime import datetime

class StatsManager:
    def __init__(self, db_path: str = "logs/stats.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    input_dir TEXT,
                    total_items INTEGER,
                    successful_items INTEGER,
                    failed_items INTEGER,
                    duration_seconds REAL
                )
            """)

    def record_task(self, input_dir: str, total: int, successful: int, failed: int, duration: float):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO task_stats (input_dir, total_items, successful_items, failed_items, duration_seconds) VALUES (?, ?, ?, ?, ?)",
                    (input_dir, total, successful, failed, duration)
                )
        except Exception as e:
            print(f"Error recording stats: {e}")

    def get_summary(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT 
                        COUNT(*) as total_tasks,
                        SUM(total_items) as total_media,
                        SUM(successful_items) as total_success,
                        SUM(failed_items) as total_failed,
                        SUM(duration_seconds) as total_duration
                    FROM task_stats
                """)
                return dict(cursor.fetchone())
        except Exception as e:
            print(f"Error reading stats: {e}")
            return {}

stats_manager = StatsManager()
