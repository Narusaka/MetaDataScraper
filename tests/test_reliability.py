import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from src.batch.scraper import BatchMediaScraper
from src.batch.organizer import MediaOrganizer
from src.core.artwork import ArtworkDownloader
from src.core.directory_lock import DirectoryLock, DirectoryLockError
from src.core.filesystem import FileSystemManager
from src.core.operation_manifest import OperationManifest, rollback_manifest
from src.pipeline.pipeline import MediaPipeline
from src.server.job_manager import JobManager
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
            self.assertEqual(restored["status"], "stopped")
            self.assertEqual(restored["summary"]["total"], 1)
            self.assertEqual(restored["rollback"]["status"], "completed")
            self.assertEqual(restored["items"]["Example.S01E01.mkv"]["status"], "stopped")
            self.assertEqual(restored["items"]["Example.S01E01.mkv"]["result"], "已回滚")
            self.assertEqual(
                restored["items"]["Example.S01E01.mkv"]["match"]["confidence"],
                "high",
            )
            self.assertGreaterEqual(len(restored["events"]), 4)

    def test_rollback_event_persists_item_state_for_refresh(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            storage_path = Path(temp_dir) / "task_events.json"
            store = TaskEventStore(storage_path=str(storage_path))
            task = store.create_task("/tmp/media", {"enable_organize": True})
            task_id = task["id"]

            store.emit(task_id, "task.started", {"input_dir": "/tmp/media"})
            store.emit(task_id, "task.scan.completed", {"total": 1})
            store.emit(task_id, "item.completed", {"name": "Movie", "result": "任务成功"}, item_id="/tmp/media/Movie")
            store.emit(task_id, "task.completed", {"summary": {"total": 1, "completed": 1, "failed": 0}})
            store.emit(task_id, "task.rollback_completed", {"status": "completed", "operations": []})

            restored = TaskEventStore(storage_path=str(storage_path)).get_task(task_id)
            item = restored["items"]["/tmp/media/Movie"]

            self.assertEqual(restored["status"], "stopped")
            self.assertEqual(item["status"], "stopped")
            self.assertEqual(item["result"], "已回滚")
            self.assertEqual(item["rollback"]["status"], "completed")

    def test_task_partial_status_is_persisted_with_summary(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            storage_path = Path(temp_dir) / "task_events.json"
            store = TaskEventStore(storage_path=str(storage_path))
            task = store.create_task("/tmp/media", {"dry_run": False})
            task_id = task["id"]

            store.emit(task_id, "task.started", {"input_dir": "/tmp/media"})
            store.emit(task_id, "task.scan.completed", {"total": 2})
            store.emit(task_id, "item.completed", {"name": "ok"}, item_id="ok")
            store.emit(task_id, "item.failed", {"name": "bad", "error": "No candidate"}, item_id="bad")
            store.emit(task_id, "task.partial", {"summary": {"total": 2, "completed": 1, "failed": 1}})

            restored = TaskEventStore(storage_path=str(storage_path)).get_task(task_id)

            self.assertEqual(restored["status"], "partial")
            self.assertEqual(restored["summary"]["total"], 2)
            self.assertEqual(restored["summary"]["completed"], 1)
            self.assertEqual(restored["summary"]["failed"], 1)

    def test_plan_ready_writes_auditable_plan_artifact(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            storage_path = Path(temp_dir) / "task_events.json"
            store = TaskEventStore(storage_path=str(storage_path))
            task = store.create_task("/tmp/media", {"dry_run": True})
            task_id = task["id"]
            plan = {
                "summary": {"actions": 1, "metadata_writes": 1},
                "actions": [{"type": "create_file", "destination": "/tmp/media/movie.nfo", "kind": "main_nfo"}],
            }

            event = store.emit(task_id, "item.plan_ready", {"plan": plan}, item_id="/tmp/media/Movie")
            restored = store.get_task(task_id)
            plan_path = Path(restored["items"]["/tmp/media/Movie"]["plan_path"])
            artifact = json.loads(plan_path.read_text(encoding="utf-8"))

            self.assertEqual(event["payload"]["plan_path"], str(plan_path))
            self.assertTrue(plan_path.exists())
            self.assertEqual(artifact["task_id"], task_id)
            self.assertEqual(artifact["item_id"], "/tmp/media/Movie")
            self.assertEqual(artifact["plan"]["summary"]["metadata_writes"], 1)
            self.assertFalse(plan_path.with_suffix(plan_path.suffix + ".tmp").exists())

            api_payload = store.read_plan_artifact(task_id, "/tmp/media/Movie")
            self.assertEqual(api_payload["plan"]["actions"][0]["kind"], "main_nfo")

    def test_plan_ready_compacts_snapshot_but_preserves_full_artifact(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            storage_path = Path(temp_dir) / "task_events.json"
            store = TaskEventStore(storage_path=str(storage_path))
            task = store.create_task("/tmp/media", {"dry_run": True})
            task_id = task["id"]
            full_actions = [
                {"type": "create_file", "destination": f"/tmp/media/file-{index}.nfo", "kind": "episode_nfo"}
                for index in range(12)
            ]
            plan = {
                "summary": {"actions": len(full_actions), "metadata_writes": len(full_actions)},
                "actions": full_actions,
                "risks": [{"level": "warning", "code": f"risk-{index}", "message": "risk"} for index in range(8)],
                "conflicts": [],
                "missing_episodes": [f"S01E{index:02d}" for index in range(30)],
            }

            event = store.emit(task_id, "item.plan_ready", {"plan": plan}, item_id="/tmp/media/Movie")
            snapshot = store.get_task(task_id)
            item = snapshot["items"]["/tmp/media/Movie"]

            self.assertTrue(item["plan"]["compact"])
            self.assertEqual(item["plan"]["summary"]["actions"], 12)
            self.assertEqual(len(item["plan"]["actions"]), 5)
            self.assertEqual(len(item["plan"]["risks"]), 5)
            self.assertEqual(len(item["plan"]["missing_episodes"]), 20)
            self.assertEqual(len(event["payload"]["plan"]["actions"]), 5)

            artifact = store.read_plan_artifact(task_id, "/tmp/media/Movie")
            self.assertEqual(len(artifact["plan"]["actions"]), 12)
            self.assertEqual(len(artifact["plan"]["risks"]), 8)
            self.assertEqual(len(artifact["plan"]["missing_episodes"]), 30)

            restored = TaskEventStore(storage_path=str(storage_path)).get_task(task_id)
            self.assertTrue(restored["items"]["/tmp/media/Movie"]["plan"]["compact"])
            self.assertEqual(len(restored["events"][-1]["payload"]["plan"]["actions"]), 5)

    def test_task_store_prunes_old_tasks(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            storage_path = Path(temp_dir) / "task_events.json"
            store = TaskEventStore(storage_path=str(storage_path), max_tasks=2)
            first = store.create_task("/tmp/one")
            second = store.create_task("/tmp/two")
            third = store.create_task("/tmp/three")

            task_ids = {task["id"] for task in store.list_tasks()}

            self.assertNotIn(first["id"], task_ids)
            self.assertIn(second["id"], task_ids)
            self.assertIn(third["id"], task_ids)
            self.assertEqual(len(task_ids), 2)

    def test_compact_rewrites_persisted_ledger(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            storage_path = Path(temp_dir) / "task_events.json"
            store = TaskEventStore(storage_path=str(storage_path))
            task = store.create_task("/tmp/media")
            task_id = task["id"]
            plan = {
                "summary": {"actions": 9},
                "actions": [{"type": "create_file", "destination": f"/tmp/{index}.nfo"} for index in range(9)],
            }
            store.emit(task_id, "item.plan_ready", {"plan": plan}, item_id="/tmp/media/Movie")

            payload_before = json.loads(storage_path.read_text(encoding="utf-8"))
            payload_before["tasks"][task_id]["items"]["/tmp/media/Movie"]["plan"]["actions"] = plan["actions"]
            storage_path.write_text(json.dumps(payload_before), encoding="utf-8")

            restored = TaskEventStore(storage_path=str(storage_path))
            restored.compact()
            payload_after = json.loads(storage_path.read_text(encoding="utf-8"))

            item_plan = payload_after["tasks"][task_id]["items"]["/tmp/media/Movie"]["plan"]
            self.assertTrue(item_plan["compact"])
            self.assertEqual(len(item_plan["actions"]), 5)
            self.assertEqual(len(restored.read_plan_artifact(task_id, "/tmp/media/Movie")["plan"]["actions"]), 9)


class JobManagerFinalStatusTest(unittest.TestCase):
    def test_worker_slot_reservation_is_exclusive_until_released(self):
        manager = JobManager()

        self.assertTrue(manager.reserve_start())
        self.assertTrue(manager.is_running)
        self.assertFalse(manager.reserve_start())

        manager.release_reservation()

        self.assertFalse(manager.is_running)
        self.assertTrue(manager.reserve_start())
        manager.release_reservation()

    def test_final_event_classifies_result_strictly(self):
        manager = JobManager()

        self.assertEqual(manager._final_event_for_results({"total": 0, "completed": 0, "failed": 0})[0], "task.failed")
        self.assertEqual(manager._final_event_for_results({"total": 2, "completed": 0, "failed": 2})[0], "task.failed")
        self.assertEqual(manager._final_event_for_results({"total": 2, "completed": 1, "failed": 1})[0], "task.partial")
        self.assertEqual(manager._final_event_for_results({"total": 2, "completed": 2, "failed": 0})[0], "task.completed")
        self.assertEqual(manager._final_event_for_results({"total": 2, "completed": 1, "failed": 0, "stopped": True})[0], "task.stopped")

    def test_stop_during_auto_prescan_emits_stopped_event(self):
        manager = JobManager()
        events = []

        class FakeEventStore:
            def emit(self, task_id, event_type, payload=None, item_id=None):
                events.append((task_id, event_type, payload or {}, item_id))

        class FakeItem:
            name = "Movie"
            suffix = ""

            def is_dir(self):
                return True

            def is_file(self):
                return False

        class FakePath:
            def __init__(self, _path):
                pass

            def exists(self):
                return True

            def is_dir(self):
                return True

            def iterdir(self):
                manager.stop_signal.set()
                yield FakeItem()

        with patch("src.server.job_manager.Path", FakePath), patch("src.server.job_manager.task_event_store", FakeEventStore()):
            manager._run_scraper_sync(
                input_dir="/media",
                config_path="config/config.yaml",
                workers=1,
                dry_run=True,
                inplace=False,
                copy=False,
                output_dir=None,
                use_local_nfo=False,
                extra_images=False,
                media_type=None,
                tmdb_id=None,
                search_mode="smart",
                enable_fallback=True,
                multi_mode=None,
                fresh=False,
                enable_organize=False,
                overwrite_images=False,
                rename_parent_dir=False,
                task_id="task-stop",
            )

        self.assertIn(("task-stop", "task.stopped", {"stage": "during_pre_scan"}, None), events)


class ServerStartTaskValidationTest(unittest.IsolatedAsyncioTestCase):
    def test_task_start_request_rejects_invalid_contract_values(self):
        from src.server.main import TaskStartRequest

        invalid_payloads = [
            {"input_dir": "/tmp/media", "search_mode": "google"},
            {"input_dir": "/tmp/media", "media_type": "anime"},
            {"input_dir": "/tmp/media", "workers": 0},
            {"input_dir": "/tmp/media", "workers": 17},
            {"input_dir": "/tmp/media", "tmdb_id": -1},
            {"input_dir": ""},
        ]

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    TaskStartRequest(**payload)

    async def test_start_task_rejects_missing_input_path(self):
        from src.server.main import TaskStartRequest, start_task

        request = TaskStartRequest(input_dir="/private/tmp/metadata-missing-input")

        with self.assertRaises(HTTPException) as raised:
            await start_task(request)

        self.assertEqual(raised.exception.status_code, 404)
        self.assertIn("Input path not found", raised.exception.detail)

    async def test_start_task_normalizes_zero_tmdb_id(self):
        from src.server import main

        class DummyTaskStore:
            def create_task(self, input_dir, config):
                self.config = config
                return {"id": "task-zero"}

        class DummyJobManager:
            is_running = False

            def reserve_start(self):
                self.is_running = True
                return True

            def release_reservation(self):
                self.is_running = False

            async def start_batch_scan(self, **kwargs):
                self.kwargs = kwargs
                self.release_reservation()

        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            task_store = DummyTaskStore()
            job_manager = DummyJobManager()
            request = main.TaskStartRequest(input_dir=temp_dir, tmdb_id=0)

            with patch.object(main, "task_event_store", task_store), patch.object(main, "job_manager", job_manager):
                response = await main.start_task(request)
                await asyncio.sleep(0)

            self.assertEqual(response["task_id"], "task-zero")
            self.assertIsNone(task_store.config["tmdb_id"])
            self.assertIsNone(job_manager.kwargs["tmdb_id"])


class OperationManifestRollbackTest(unittest.TestCase):
    def test_manifest_flush_is_complete_json_without_tmp_leftover(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            manifest_dir = root / "manifests"
            manifest = OperationManifest("task-atomic", manifest_dir=str(manifest_dir))

            manifest.record("create_dir", None, root / "Season 01")
            manifest.record("copy_file", root / "source.mkv", root / "Season 01" / "copy.mkv")

            data = (manifest_dir / "task-atomic.json").read_text(encoding="utf-8")
            self.assertIn('"task_id": "task-atomic"', data)
            self.assertFalse((manifest_dir / "task-atomic.json.tmp").exists())

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

    def test_rollback_restores_overwritten_file_from_backup(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            target = root / "movie.nfo"
            target.write_text("old metadata", encoding="utf-8")

            manifest_dir = root / "manifests"
            manifest = OperationManifest("overwrite-task", manifest_dir=str(manifest_dir))
            backup_path = manifest.backup_file(target)
            target.write_text("new metadata", encoding="utf-8")
            manifest.record("overwrite_file", None, target, extra={"backup_path": str(backup_path)})

            rollback = rollback_manifest("overwrite-task", manifest_dir=str(manifest_dir))

            self.assertEqual(rollback["status"], "completed")
            self.assertEqual(target.read_text(encoding="utf-8"), "old metadata")
            self.assertEqual(rollback["operations"][0]["status"], "restored_backup")
            self.assertTrue((manifest_dir / "overwrite-task.backups").exists())

    def test_manifest_records_destination_fingerprint_for_file_writes(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            target = root / "movie.nfo"
            target.write_text("metadata", encoding="utf-8")

            manifest_dir = root / "manifests"
            manifest = OperationManifest("fingerprint-task", manifest_dir=str(manifest_dir))
            manifest.record("create_file", None, target)

            operation = manifest.operations[0]
            self.assertEqual(operation["destination_size"], len("metadata"))
            self.assertEqual(len(operation["destination_sha256"]), 64)

    def test_rollback_does_not_remove_created_file_modified_after_manifest(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            target = root / "movie.nfo"
            target.write_text("created by scraper", encoding="utf-8")

            manifest_dir = root / "manifests"
            manifest = OperationManifest("modified-create", manifest_dir=str(manifest_dir))
            manifest.record("create_file", None, target)
            target.write_text("user changed it", encoding="utf-8")

            rollback = rollback_manifest("modified-create", manifest_dir=str(manifest_dir))

            self.assertEqual(rollback["status"], "partial")
            self.assertEqual(rollback["operations"][0]["status"], "current_modified")
            self.assertEqual(target.read_text(encoding="utf-8"), "user changed it")

    def test_rollback_does_not_restore_backup_over_file_modified_after_manifest(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            target = root / "movie.nfo"
            target.write_text("old metadata", encoding="utf-8")

            manifest_dir = root / "manifests"
            manifest = OperationManifest("modified-overwrite", manifest_dir=str(manifest_dir))
            backup_path = manifest.backup_file(target)
            target.write_text("new metadata", encoding="utf-8")
            manifest.record("overwrite_file", None, target, extra={"backup_path": str(backup_path)})
            target.write_text("user edited after scrape", encoding="utf-8")

            rollback = rollback_manifest("modified-overwrite", manifest_dir=str(manifest_dir))

            self.assertEqual(rollback["status"], "partial")
            self.assertEqual(rollback["operations"][0]["status"], "current_modified")
            self.assertEqual(target.read_text(encoding="utf-8"), "user edited after scrape")


class AtomicFileWriteTest(unittest.TestCase):
    def test_nfo_write_uses_atomic_temp_file_without_leftover(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            media_dir = Path(temp_dir) / "Movie"

            nfo_path = FileSystemManager.write_nfo_file(str(media_dir), "movie.nfo", "<movie>ok</movie>")

            self.assertEqual(Path(nfo_path).read_text(encoding="utf-8"), "<movie>ok</movie>")
            self.assertEqual(list(media_dir.glob("*.tmp")), [])

    def test_atomic_write_replaces_existing_content(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            path = Path(temp_dir) / "tvshow.nfo"
            path.write_text("old", encoding="utf-8")

            FileSystemManager.write_text_atomic(str(path), "new")

            self.assertEqual(path.read_text(encoding="utf-8"), "new")
            self.assertEqual(list(Path(temp_dir).glob("*.tmp")), [])


class DirectoryLockTest(unittest.TestCase):
    def test_directory_lock_blocks_second_owner_and_cleans_up(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            target = Path(temp_dir) / "Example"
            target.mkdir()
            first_lock = DirectoryLock(target, owner="task-one").acquire()

            try:
                with self.assertRaises(DirectoryLockError) as raised:
                    DirectoryLock(target, owner="task-two").acquire()

                self.assertEqual(raised.exception.owner["owner"], "task-one")
                self.assertTrue(first_lock.lock_path.exists())
            finally:
                first_lock.release()

            self.assertFalse(first_lock.lock_path.exists())

    def test_stale_directory_lock_can_be_replaced(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            target = Path(temp_dir) / "Example"
            target.mkdir()
            stale_lock = DirectoryLock(target, owner="old-task", stale_after_seconds=0)
            stale_lock.lock_path.parent.mkdir(parents=True, exist_ok=True)
            stale_lock.lock_path.write_text(json.dumps({"owner": "old-task", "created_at": 1}), encoding="utf-8")

            fresh_lock = DirectoryLock(target, owner="new-task", stale_after_seconds=0).acquire()
            try:
                self.assertEqual(json.loads(fresh_lock.lock_path.read_text(encoding="utf-8"))["owner"], "new-task")
            finally:
                fresh_lock.release()


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

    def test_plan_includes_metadata_and_artwork_writes(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            movie_path = Path(temp_dir) / "Example Movie (2026)"
            movie_path.mkdir()
            (movie_path / "Example.Movie.2026.mkv").write_text("video", encoding="utf-8")
            existing_nfo = movie_path / "Example Movie (2026).nfo"
            existing_nfo.write_text("old", encoding="utf-8")
            existing_poster = movie_path / "poster.jpg"
            existing_poster.write_bytes(b"old poster")

            metadata = {
                "normalized": {
                    "media_type": "movie",
                    "title": "Example Movie",
                    "title_zh": "Example Movie",
                    "year": 2026,
                },
                "source_data": {},
                "nfo": {"xml": "<movie />"},
            }

            organizer = MediaOrganizer(enable_organize=False)
            plan = organizer.build_plan(movie_path, metadata)
            actions = plan["actions"]

            self.assertGreaterEqual(plan["summary"]["metadata_writes"], 7)
            self.assertTrue(any(action.get("kind") == "main_nfo" and action["type"] == "overwrite_file" and action["destination"] == str(existing_nfo) for action in actions))
            self.assertTrue(any(action.get("kind") == "artwork:poster" and action["type"] == "overwrite_file" and action["destination"] == str(existing_poster) for action in actions))
            self.assertTrue(any(action.get("kind") == "artwork_manifest" and action["type"] == "create_file" for action in actions))
            self.assertTrue(all(action.get("reversible") for action in actions if action.get("kind") in {"main_nfo", "artwork:poster", "artwork_manifest"}))


class ExecutionPlanGuardTest(unittest.TestCase):
    def test_real_execution_stops_before_organize_when_plan_has_conflicts(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            show_path = Path(temp_dir) / "Example Movie (2026)"
            show_path.mkdir()
            (show_path / "Example.Movie.2026.mkv").write_text("video", encoding="utf-8")

            class FakePipeline:
                calls = []

                def run(self, input_data):
                    self.calls.append(input_data.copy())
                    if input_data.get("plan_only"):
                        return {
                            "status": "plan_ready",
                            "candidate": {"id": 1, "title": "Example Movie", "media_type": "movie"},
                            "match": {"provider": "tmdb", "confidence": "high"},
                            "normalized": {"media_type": "movie", "title": "Example Movie", "year": 2026},
                            "source_data": {},
                            "nfo": {},
                        }
                    return {
                        "status": "completed",
                        "candidate": {"id": 1, "title": "Example Movie", "media_type": "movie"},
                        "match": {"provider": "tmdb", "confidence": "high"},
                        "normalized": {"media_type": "movie", "title": "Example Movie", "year": 2026},
                        "source_data": {},
                    }

            class FakeOrganizer:
                organize_called = False

                def build_plan(self, *args, **kwargs):
                    return {
                        "summary": {"blocked": 1, "conflicts": 1},
                        "conflicts": [{"reason": "destination_exists"}],
                    }

                def has_blockers(self, plan):
                    return True

                def organize(self, *args, **kwargs):
                    self.organize_called = True

            scraper = object.__new__(BatchMediaScraper)
            scraper.dry_run = False
            scraper.media_type = "movie"
            scraper.inplace_rename = True
            scraper.output_dir = None
            scraper.extra_images = False
            scraper.overwrite_images = False
            scraper.search_mode = "tmdb_only"
            scraper.enable_fallback = True
            scraper.fresh = False
            scraper.pipeline = FakePipeline()
            scraper.organizer = FakeOrganizer()
            scraper.stop_event = None
            scraper.task_id = None

            success, reason = scraper._process_directory(show_path, None, task_media_type="movie")

            self.assertFalse(success)
            self.assertIn("执行计划存在冲突", reason)
            self.assertFalse(scraper.organizer.organize_called)
            self.assertEqual(len(scraper.pipeline.calls), 1)
            self.assertTrue(scraper.pipeline.calls[0]["plan_only"])
            self.assertFalse(scraper.pipeline.calls[0]["audit_only"])

    def test_real_execution_stops_when_target_is_locked(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            show_path = Path(temp_dir) / "Example Movie (2026)"
            show_path.mkdir()
            (show_path / "Example.Movie.2026.mkv").write_text("video", encoding="utf-8")

            class FakePipeline:
                calls = []

                def run(self, input_data):
                    self.calls.append(input_data.copy())
                    if input_data.get("plan_only"):
                        return {
                            "status": "plan_ready",
                            "candidate": {"id": 1, "title": "Example Movie", "media_type": "movie"},
                            "match": {"provider": "tmdb", "confidence": "high"},
                            "normalized": {"media_type": "movie", "title": "Example Movie", "year": 2026},
                            "source_data": {},
                            "nfo": {},
                        }
                    return {"status": "completed"}

            class FakeOrganizer:
                organize_called = False

                def build_plan(self, path, *args, **kwargs):
                    return {
                        "target_root": str(path),
                        "summary": {"blocked": 0, "conflicts": 0},
                        "conflicts": [],
                    }

                def has_blockers(self, plan):
                    return False

                def organize(self, *args, **kwargs):
                    self.organize_called = True

            scraper = object.__new__(BatchMediaScraper)
            scraper.dry_run = False
            scraper.media_type = "movie"
            scraper.inplace_rename = True
            scraper.output_dir = None
            scraper.extra_images = False
            scraper.overwrite_images = False
            scraper.search_mode = "tmdb_only"
            scraper.enable_fallback = True
            scraper.fresh = False
            scraper.pipeline = FakePipeline()
            scraper.organizer = FakeOrganizer()
            scraper.stop_event = None
            scraper.task_id = "current-task"
            scraper._emit = lambda *args, **kwargs: None

            blocking_lock = DirectoryLock(show_path, owner="other-task").acquire()
            try:
                success, reason = scraper._process_directory(show_path, None, task_media_type="movie")
            finally:
                blocking_lock.release()

            self.assertFalse(success)
            self.assertIn("目标目录正在被其他任务处理", reason)
            self.assertFalse(scraper.organizer.organize_called)
            self.assertEqual(len(scraper.pipeline.calls), 1)
            self.assertTrue(scraper.pipeline.calls[0]["plan_only"])
            self.assertFalse(scraper.pipeline.calls[0]["audit_only"])


class ArtworkAuditResultTest(unittest.TestCase):
    def test_plan_only_pipeline_generates_metadata_without_writing_files(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            pipeline = object.__new__(MediaPipeline)
            pipeline.inplace = False
            pipeline._log = lambda *args, **kwargs: None
            pipeline._step_search = lambda input_data: {
                "selected": {"id": 123, "title": "Example Movie", "media_type": "movie", "release_date": "2026-01-01"},
                "match": {"provider": "tmdb", "confidence": "high"},
            }
            pipeline._step_fetch = lambda tmdb_id, media_type: {"main": {}, "credits": {}, "keywords": {}}
            pipeline._step_normalize = lambda source_data, media_type, input_data: {
                "tmdb_id": 123,
                "media_type": "movie",
                "title": "Example Movie",
                "year": 2026,
            }
            pipeline._step_translate = lambda source_data, normalized, media_type, input_data: {
                "translated": normalized,
                "translated_episodes": [],
            }
            pipeline._step_generate_nfo = lambda normalized, media_type, source_data: {"xml": "<movie />"}

            result = pipeline.run({"query": "Example Movie", "media_type": "movie", "output_dir": temp_dir, "plan_only": True})

            self.assertEqual(result["status"], "plan_ready")
            self.assertEqual(result["nfo"]["xml"], "<movie />")
            self.assertFalse((Path(temp_dir) / "Movies").exists())

    def test_pipeline_returns_auditable_artwork_summary(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            class FakeArtwork:
                def download_all_images(self, media_type, tmdb_id, output_dir, **kwargs):
                    self.call = {
                        "media_type": media_type,
                        "tmdb_id": tmdb_id,
                        "output_dir": output_dir,
                        "kwargs": kwargs,
                    }
                    return {
                        "poster": ["poster.jpg"],
                        "fanart": ["fanart.jpg"],
                        "banner": ["banner.jpg"],
                        "logo": [],
                        "clearart": [],
                        "poster_extra": ["Extra/posters/poster-01.jpg"],
                    }

            pipeline = object.__new__(MediaPipeline)
            pipeline.artwork = FakeArtwork()
            pipeline.verbose = False
            pipeline.config = {"output": {"image_limit": {"posters": 2}}}
            pipeline._log = lambda *args, **kwargs: None

            result = pipeline._step_download_images(
                {"tmdb_id": 123, "media_type": "movie"},
                temp_dir,
                {"extra_images": True, "overwrite_images": False},
            )

            self.assertEqual(result["status"], "downloaded")
            self.assertEqual(result["total"], 4)
            self.assertEqual(result["counts"]["poster"], 1)
            self.assertEqual(result["counts"]["poster_extra"], 1)
            self.assertIn("logo", result["missing_core"])
            self.assertEqual(pipeline.artwork.call["media_type"], "movie")
            self.assertTrue(pipeline.artwork.call["kwargs"]["extra_images"])

    def test_image_download_validates_content_before_replace(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            class FakeResponse:
                headers = {"content-type": "image/png"}

                def raise_for_status(self):
                    return None

                def iter_content(self, chunk_size=8192):
                    yield b"\x89PNG\r\n\x1a\n" + (b"\0" * 64)

            class FakeSession:
                def get(self, *args, **kwargs):
                    return FakeResponse()

            manifest = OperationManifest("image-valid", manifest_dir=str(Path(temp_dir) / "manifests"))
            downloader = ArtworkDownloader("tmdb", manifest=manifest)
            downloader.session = FakeSession()
            dest = Path(temp_dir) / "poster.png"

            downloaded = downloader.download_image(str(dest), "https://image.tmdb.org/t/p/original/poster.png", max_retries=1)

            self.assertTrue(downloaded)
            self.assertTrue(dest.exists())
            self.assertFalse(Path(str(dest) + ".download").exists())
            self.assertTrue(any(op["destination"] == str(dest) and op["kind"] == "artwork" for op in manifest.operations))

    def test_invalid_image_download_does_not_replace_existing_file(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            class FakeResponse:
                headers = {"content-type": "text/html"}

                def raise_for_status(self):
                    return None

                def iter_content(self, chunk_size=8192):
                    yield b"<html>not an image</html>" * 4

            class FakeSession:
                def get(self, *args, **kwargs):
                    return FakeResponse()

            downloader = ArtworkDownloader("tmdb")
            downloader.session = FakeSession()
            dest = Path(temp_dir) / "poster.jpg"
            dest.write_bytes(b"\xff\xd8\xff" + (b"old" * 20))

            downloaded = downloader.download_image(str(dest), "https://image.tmdb.org/t/p/original/poster.jpg", max_retries=1)

            self.assertFalse(downloaded)
            self.assertEqual(dest.read_bytes(), b"\xff\xd8\xff" + (b"old" * 20))
            self.assertFalse(Path(str(dest) + ".download").exists())

    def test_overwritten_artwork_is_rollbackable(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            class FakeResponse:
                headers = {"content-type": "image/png"}

                def raise_for_status(self):
                    return None

                def iter_content(self, chunk_size=8192):
                    yield b"\x89PNG\r\n\x1a\n" + (b"new" * 20)

            class FakeSession:
                def get(self, *args, **kwargs):
                    return FakeResponse()

            root = Path(temp_dir)
            dest = root / "poster.png"
            old_bytes = b"\x89PNG\r\n\x1a\n" + (b"old" * 20)
            dest.write_bytes(old_bytes)
            manifest = OperationManifest("artwork-overwrite", manifest_dir=str(root / "manifests"))
            downloader = ArtworkDownloader("tmdb", manifest=manifest)
            downloader.session = FakeSession()

            self.assertTrue(downloader.download_image(str(dest), "https://image.tmdb.org/t/p/original/poster.png", max_retries=1))
            self.assertNotEqual(dest.read_bytes(), old_bytes)

            rollback = rollback_manifest("artwork-overwrite", manifest_dir=str(root / "manifests"))

            self.assertEqual(rollback["status"], "completed")
            self.assertEqual(dest.read_bytes(), old_bytes)

    def test_pipeline_output_files_are_manifested_and_rollbackable(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            manifest = OperationManifest("pipeline-output", manifest_dir=str(Path(temp_dir) / "manifests"))
            pipeline = object.__new__(MediaPipeline)
            pipeline.inplace = False
            pipeline.manifest = manifest

            result = pipeline._step_write_output(
                {"media_type": "movie", "title": "Example Movie", "year": 2026},
                {"xml": "<movie />"},
                {},
                {"output_dir": temp_dir},
            )

            media_dir = Path(result["media_dir"])
            nfo_path = media_dir / "Example Movie (2026).nfo"
            self.assertTrue(nfo_path.exists())
            self.assertTrue(any(op["action"] == "create_file" and op["destination"] == str(nfo_path) for op in manifest.operations))

            rollback = rollback_manifest("pipeline-output", manifest_dir=str(Path(temp_dir) / "manifests"))

            self.assertEqual(rollback["status"], "completed")
            self.assertFalse(nfo_path.exists())
            self.assertFalse(media_dir.exists())

    def test_pipeline_overwritten_nfo_is_rollbackable(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            media_dir = root / "Example Movie (2026)"
            media_dir.mkdir()
            nfo_path = media_dir / "Example Movie (2026).nfo"
            nfo_path.write_text("<movie>old</movie>", encoding="utf-8")

            manifest = OperationManifest("pipeline-overwrite", manifest_dir=str(root / "manifests"))
            pipeline = object.__new__(MediaPipeline)
            pipeline.inplace = True
            pipeline.manifest = manifest

            pipeline._step_write_output(
                {"media_type": "movie", "title": "Example Movie", "year": 2026},
                {"xml": "<movie>new</movie>"},
                {},
                {"output_dir": str(media_dir)},
            )

            self.assertEqual(nfo_path.read_text(encoding="utf-8"), "<movie>new</movie>")

            rollback = rollback_manifest("pipeline-overwrite", manifest_dir=str(root / "manifests"))

            self.assertEqual(rollback["status"], "completed")
            self.assertEqual(nfo_path.read_text(encoding="utf-8"), "<movie>old</movie>")

    def test_derived_artwork_file_is_recorded_in_manifest(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            source = root / "fanart.jpg"
            destination = root / "banner.jpg"
            source.write_bytes(b"image")
            manifest = OperationManifest("artwork-derived", manifest_dir=str(root / "manifests"))
            downloader = ArtworkDownloader("tmdb", manifest=manifest)

            copied = downloader._copy_companion(str(source), str(destination), overwrite=False)

            self.assertTrue(copied)
            self.assertTrue(destination.exists())
            self.assertTrue(any(op["action"] == "create_file" and op["destination"] == str(destination) for op in manifest.operations))

    def test_artwork_manifest_records_downloaded_and_derived_assets(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            class FakeResponse:
                def __init__(self, payload):
                    self.payload = payload

                def raise_for_status(self):
                    return None

                def json(self):
                    return self.payload

            class FakeSession:
                def get(self, url, **kwargs):
                    return FakeResponse(
                        {
                            "posters": [
                                {"file_path": "/poster-main.jpg", "iso_639_1": "en", "width": 1000, "height": 1500, "vote_average": 8.0, "vote_count": 10},
                                {"file_path": "/poster-extra.jpg", "iso_639_1": "zh", "width": 900, "height": 1350},
                            ],
                            "backdrops": [
                                {"file_path": "/fanart-main.jpg", "width": 1920, "height": 1080},
                            ],
                            "logos": [
                                {"file_path": "/logo-main.png", "iso_639_1": "en", "width": 800, "height": 310},
                            ],
                        }
                    )

            manifest = OperationManifest("artwork-manifest", manifest_dir=str(Path(temp_dir) / "manifests"))
            downloader = ArtworkDownloader("tmdb-key", manifest=manifest)
            downloader.session = FakeSession()

            def fake_download(image_path, url, max_retries=3, overwrite=True):
                path = Path(image_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"image")
                if downloader.manifest:
                    downloader.manifest.record("create_file", None, path, extra={"kind": "artwork", "url": url})
                return True

            downloader.download_image = fake_download
            result = downloader.download_all_images("movie", 123, temp_dir, extra_images=True, image_limits={"posters": 1, "backdrops": 0, "logos": 0})
            manifest_path = Path(temp_dir) / "artwork-manifest.json"
            data = json.loads(manifest_path.read_text(encoding="utf-8"))

            self.assertEqual(result["poster"], ["poster.jpg"])
            self.assertTrue(manifest_path.exists())
            self.assertEqual(data["media_type"], "movie")
            self.assertEqual(data["tmdb_id"], 123)
            self.assertEqual(data["summary"]["poster"], 1)
            self.assertTrue(any(asset["path"] == "poster.jpg" and asset["url"].endswith("/poster-main.jpg") for asset in data["assets"]))
            self.assertTrue(any(asset["path"] == "banner.jpg" and asset["derived_from"] == "fanart.jpg" for asset in data["assets"]))
            self.assertTrue(any(op["destination"] == str(manifest_path) and op["kind"] == "artwork_manifest" for op in manifest.operations))


if __name__ == "__main__":
    unittest.main()
