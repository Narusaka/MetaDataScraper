import tempfile
import unittest
from pathlib import Path

from src.batch.organizer import MediaOrganizer
from src.core.operation_manifest import OperationManifest, rollback_manifest
from src.server.task_events import TaskEventStore


class TaskEventStorePersistenceTest(unittest.TestCase):
    def test_task_snapshot_survives_store_restart(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            storage_path = Path(temp_dir) / "task_events.json"
            store = TaskEventStore(storage_path=str(storage_path))
            task = store.create_task("/tmp/media", {"dry_run": True, "search_mode": "tmdb_only"})
            task_id = task["id"]

            store.emit(task_id, "task.started", {"input_dir": "/tmp/media"})
            store.emit(task_id, "task.scan.completed", {"total": 1})
            store.emit(
                task_id,
                "candidate.selected",
                {
                    "title": "Example",
                    "tmdb_id": 123,
                    "match": {"confidence": "high", "score": 0.97},
                },
                item_id="Example.S01E01.mkv",
            )
            store.emit(task_id, "task.rollback_completed", {"status": "completed"})

            restored_store = TaskEventStore(storage_path=str(storage_path))
            restored = restored_store.get_task(task_id)

            self.assertIsNotNone(restored)
            self.assertEqual(restored["status"], "running")
            self.assertEqual(restored["summary"]["total"], 1)
            self.assertEqual(restored["rollback"]["status"], "completed")
            self.assertEqual(
                restored["items"]["Example.S01E01.mkv"]["match"]["confidence"],
                "high",
            )
            self.assertGreaterEqual(len(restored["events"]), 4)


class OperationManifestRollbackTest(unittest.TestCase):
    def test_rollback_restores_moved_file(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            source = root / "source.mkv"
            destination = root / "Season 01" / "renamed.mkv"
            destination.parent.mkdir()
            source.write_text("video", encoding="utf-8")
            destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            source.unlink()

            manifest_dir = root / "manifests"
            manifest = OperationManifest("task-1", manifest_dir=str(manifest_dir))
            manifest.record("move_file", source, destination)

            result = rollback_manifest("task-1", manifest_dir=str(manifest_dir))

            self.assertEqual(result["status"], "completed")
            self.assertTrue(source.exists())
            self.assertFalse(destination.exists())
            self.assertEqual(source.read_text(encoding="utf-8"), "video")


class OrganizerPlanTest(unittest.TestCase):
    def test_plan_marks_destination_conflict_and_missing_episode(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            show_path = Path(temp_dir) / "Example"
            season_path = show_path / "Season 01"
            season_path.mkdir(parents=True)
            source = show_path / "Example.S01E01.mkv"
            source.write_text("source", encoding="utf-8")
            conflict = season_path / "Example Show - S01E01 - Pilot.mkv"
            conflict.write_text("existing", encoding="utf-8")

            metadata = {
                "normalized": {
                    "media_type": "tv",
                    "title": "Example Show",
                    "title_zh": "Example Show",
                    "year": 2026,
                },
                "source_data": {
                    "translated_episodes": [
                        {"season_number": 1, "episode_number": 1, "name": "Pilot"},
                        {"season_number": 1, "episode_number": 2, "name": "Second"},
                    ]
                },
            }

            organizer = MediaOrganizer(enable_organize=True)
            plan = organizer.build_plan(show_path, metadata)

            self.assertEqual(plan["summary"]["blocked"], 1)
            self.assertEqual(plan["summary"]["conflicts"], 1)
            self.assertEqual(plan["summary"]["missing_episodes"], 1)
            self.assertIn("S01E02", plan["missing_episodes"])
            self.assertEqual(plan["actions"][0]["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
