import asyncio
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from src.batch.scraper import BatchMediaScraper
from src.batch.organizer import MediaOrganizer, OrganizerExecutionError
from src.core.artwork import ArtworkDownloader
from src.core.cancellation import OperationCancelled
from src.core.directory_lock import DirectoryLock, DirectoryLockError
from src.core.execution_verifier import ExecutionVerifier
from src.core.filesystem import FileSystemManager
from src.core.operation_manifest import OperationManifest, get_manifest, preview_recovery_manifest, preview_rollback_manifest, rollback_manifest, summarize_manifest
from src.core.plan_integrity import PlanIntegrityError
from src.pipeline.pipeline import MediaPipeline
from src.server.job_manager import JobManager
from src.server.access_control import TrustedOriginPolicy
from src.server.task_events import TaskEventStore
from src.services.library_scan import LibraryScanService
from src.storage.task_ledger import SQLiteTaskLedger


class TaskEventStorePersistenceTest(unittest.TestCase):
    def test_sqlite_task_ledger_survives_restart_with_structured_events(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            storage_path = Path(temp_dir) / "task_events.db"
            store = TaskEventStore(storage_path=str(storage_path), max_tasks=100)
            task = store.create_task("/media/Show", {"dry_run": True})
            task_id = task["id"]
            store.emit(task_id, "task.started", {"input_dir": "/media/Show"})
            store.emit(
                task_id,
                "candidate.selected",
                {
                    "title": "Example Show",
                    "tmdb_id": 123,
                    "media_type": "tv",
                    "match": {"confidence": "high", "score": 0.96},
                },
                item_id="/media/Show",
            )
            store.emit(task_id, "task.completed", {"summary": {"total": 1, "completed": 1}})

            ledger = SQLiteTaskLedger(storage_path)
            restored = TaskEventStore(storage_path=str(storage_path), max_tasks=100).get_task(task_id)

            self.assertEqual(ledger.count_tasks(), 1)
            self.assertEqual(ledger.count_events(), 4)
            self.assertEqual(restored["status"], "completed")
            self.assertEqual(restored["items"]["/media/Show"]["candidate"]["tmdb_id"], 123)
            self.assertEqual(restored["events"][2]["type"], "candidate.selected")
            self.assertEqual(restored["events"][2]["payload"]["match"]["score"], 0.96)

    def test_sqlite_store_imports_legacy_json_ledger_once(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            legacy_path = root / "task_events.json"
            legacy_store = TaskEventStore(storage_path=str(legacy_path), max_tasks=100)
            task = legacy_store.create_task("/media/Legacy", {"dry_run": True})
            legacy_store.emit(task["id"], "task.scan.completed", {"total": 2})

            db_path = root / "task_events.db"
            migrated = TaskEventStore(storage_path=str(db_path), max_tasks=100)
            restored = migrated.get_task(task["id"])

            self.assertTrue(db_path.exists())
            self.assertEqual(restored["input_dir"], "/media/Legacy")
            self.assertEqual(restored["summary"]["total"], 2)
            self.assertEqual(SQLiteTaskLedger(db_path).count_events(), 2)

            legacy_path.write_text('{"version": 1, "tasks": {}}', encoding="utf-8")
            restarted = TaskEventStore(storage_path=str(db_path), max_tasks=100)
            self.assertIsNotNone(restarted.get_task(task["id"]))

    def test_sqlite_retention_and_history_clear_remove_event_rows(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            storage_path = Path(temp_dir) / "task_events.db"
            store = TaskEventStore(storage_path=str(storage_path), max_tasks=2)
            first = store.create_task("/media/One")
            second = store.create_task("/media/Two")
            store.emit(second["id"], "task.completed", {"summary": {"completed": 1}})
            third = store.create_task("/media/Three")

            ledger = SQLiteTaskLedger(storage_path)
            self.assertIsNone(store.get_task(first["id"]))
            self.assertEqual(ledger.count_tasks(), 2)
            self.assertEqual(ledger.count_events(), 3)

            result = store.clear_finished_tasks()
            self.assertEqual(result["task_ids"], [second["id"]])
            self.assertEqual(ledger.count_tasks(), 1)
            self.assertEqual(ledger.count_events(), 1)
            self.assertIsNotNone(store.get_task(third["id"]))

    def test_sqlite_event_retention_matches_configured_window(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            storage_path = Path(temp_dir) / "task_events.db"
            store = TaskEventStore(
                storage_path=str(storage_path),
                max_events_per_task=3,
                max_tasks=10,
            )
            task = store.create_task("/media/Window")
            for index in range(5):
                store.emit(task["id"], "task.scan.completed", {"total": index})

            restored = TaskEventStore(
                storage_path=str(storage_path),
                max_events_per_task=3,
                max_tasks=10,
            ).get_task(task["id"])

            self.assertEqual(len(restored["events"]), 3)
            self.assertEqual(SQLiteTaskLedger(storage_path).count_events(), 3)
            self.assertEqual(restored["events"][-1]["payload"]["total"], 4)

    def test_restart_reconciliation_marks_only_orphaned_tasks_interrupted(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            storage_path = Path(temp_dir) / "task_events.db"
            store = TaskEventStore(storage_path=str(storage_path), max_tasks=10)
            running = store.create_task("/media/Running", {"dry_run": False})
            store.emit(running["id"], "task.started", {"input_dir": "/media/Running"})
            store.emit(
                running["id"],
                "item.started",
                {"name": "Running", "path": "/media/Running"},
                item_id="/media/Running",
            )
            cancelling = store.create_task("/media/Cancelling", {"dry_run": False})
            store.emit(cancelling["id"], "task.cancel_requested", {"stage": "requested"})
            completed = store.create_task("/media/Completed", {"dry_run": False})
            store.emit(
                completed["id"],
                "task.completed",
                {"summary": {"total": 1, "completed": 1}},
            )

            restarted = TaskEventStore(storage_path=str(storage_path), max_tasks=10)
            result = restarted.reconcile_interrupted_tasks()

            self.assertEqual(result["count"], 2)
            self.assertCountEqual(result["task_ids"], [running["id"], cancelling["id"]])
            interrupted = restarted.get_task(running["id"])
            self.assertEqual(interrupted["status"], "interrupted")
            self.assertEqual(interrupted["phase"], "interrupted")
            self.assertEqual(interrupted["error_code"], "PROCESS_INTERRUPTED")
            self.assertTrue(interrupted["interruption"]["recoverable"])
            self.assertEqual(interrupted["items"]["/media/Running"]["status"], "interrupted")
            self.assertEqual(interrupted["events"][-1]["type"], "task.interrupted")
            self.assertEqual(restarted.get_task(cancelling["id"])["status"], "interrupted")
            self.assertEqual(restarted.get_task(completed["id"])["status"], "completed")

            persisted = TaskEventStore(storage_path=str(storage_path), max_tasks=10)
            self.assertEqual(persisted.get_task(running["id"])["status"], "interrupted")


class TaskEventStoreLifecycleTest(unittest.TestCase):
    def test_verification_lifecycle_persists_evidence_and_partial_state(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            store = TaskEventStore(storage_path=str(Path(temp_dir) / "tasks.json"))
            task = store.create_task("/media", {})
            task_id = task["id"]
            item_id = "/media/Movie"
            verification = {
                "status": "partial",
                "checked": 3,
                "passed": 2,
                "failed": 0,
                "warnings": 1,
                "warning_codes": ["artwork_incomplete"],
                "checks": [{"status": "warning", "code": "artwork_incomplete", "message": "Missing artwork types: logo"}],
            }

            store.emit(task_id, "item.verification_started", {"name": "Movie"}, item_id=item_id)
            self.assertEqual(store.get_task(task_id)["items"][item_id]["status"], "verifying")
            store.emit(task_id, "item.verification_completed", {"verification": verification}, item_id=item_id)
            store.emit(task_id, "item.partial", {"result": "warnings", "verification": verification}, item_id=item_id)

            restored = TaskEventStore(storage_path=str(Path(temp_dir) / "tasks.json")).get_task(task_id)
            compact = store.list_tasks(compact=True)[0]["items"][item_id]
            self.assertEqual(restored["items"][item_id]["status"], "partial")
            self.assertEqual(restored["items"][item_id]["verification"]["warning_codes"], ["artwork_incomplete"])
            self.assertEqual(compact["verification"]["checks"][0]["code"], "artwork_incomplete")
            self.assertEqual(restored["summary"]["partial"], 1)

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
            self.assertEqual(restored["items"]["Example.S01E01.mkv"]["status"], "fetching")
            self.assertEqual(
                restored["items"]["Example.S01E01.mkv"]["match"]["confidence"],
                "high",
            )
            self.assertGreaterEqual(len(restored["events"]), 4)

    def test_rollback_event_persists_without_overwriting_task_result(self):
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

            self.assertEqual(restored["status"], "completed")
            self.assertEqual(restored["rollback"]["status"], "completed")
            self.assertEqual(item["status"], "completed")
            self.assertEqual(item["result"], "任务成功")
            self.assertNotIn("rollback", item)

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

    def test_clear_finished_tasks_keeps_running_and_audit_ready_history(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            storage_path = Path(temp_dir) / "task_events.json"
            store = TaskEventStore(storage_path=str(storage_path), max_tasks=10)

            completed = store.create_task("/tmp/completed", {"dry_run": False})
            failed = store.create_task("/tmp/failed", {"dry_run": False})
            running = store.create_task("/tmp/running", {"dry_run": False})
            audit_ready = store.create_task("/tmp/audit", {"dry_run": True})

            store.emit(completed["id"], "task.completed", {"summary": {"total": 1, "completed": 1, "failed": 0}})
            store.emit(failed["id"], "task.failed", {"error": "bad match", "summary": {"total": 1, "completed": 0, "failed": 1}})
            store.emit(running["id"], "task.started", {"input_dir": "/tmp/running"})
            store.emit(audit_ready["id"], "task.scan.completed", {"total": 1})

            result = store.clear_finished_tasks()
            restored = TaskEventStore(storage_path=str(storage_path), max_tasks=10)

            self.assertEqual(result["removed"], 2)
            self.assertIsNone(restored.get_task(completed["id"]))
            self.assertIsNone(restored.get_task(failed["id"]))
            self.assertIsNotNone(restored.get_task(running["id"]))
            self.assertIsNotNone(restored.get_task(audit_ready["id"]))

    def test_history_clear_preserves_protected_tasks_and_removes_stale_plan_artifacts(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            storage_path = root / "task_events.db"
            store = TaskEventStore(storage_path=str(storage_path), max_tasks=10)
            removable = store.create_task("/tmp/removable", {"dry_run": True})
            protected = store.create_task("/tmp/protected", {"dry_run": False})
            store.emit(
                removable["id"],
                "task.completed",
                {"summary": {"total": 1, "completed": 1}},
            )
            store.emit(
                protected["id"],
                "task.interrupted",
                {"error": "restart", "recoverable": True},
            )
            removable_plan = root / "plans" / removable["id"]
            protected_plan = root / "plans" / protected["id"]
            removable_plan.mkdir(parents=True)
            protected_plan.mkdir(parents=True)
            (removable_plan / "plan.json").write_text("{}", encoding="utf-8")
            (protected_plan / "plan.json").write_text("{}", encoding="utf-8")

            protection = {
                protected["id"]: ["recovery_available"],
            }
            preview = store.preview_finished_task_clear(protection)

            self.assertEqual(preview["task_ids"], [removable["id"]])
            self.assertEqual(preview["retained_count"], 1)
            self.assertIsNotNone(store.get_task(removable["id"]))
            self.assertTrue(removable_plan.exists())

            result = store.clear_finished_tasks(protection)

            self.assertEqual(result["task_ids"], [removable["id"]])
            self.assertEqual(result["retained_count"], 1)
            self.assertEqual(
                result["retained"][0],
                {
                    "task_id": protected["id"],
                    "reasons": ["recovery_available"],
                },
            )
            self.assertEqual(result["plan_cleanup_errors"], [])
            self.assertFalse(removable_plan.exists())
            self.assertTrue(protected_plan.exists())
            self.assertIsNone(store.get_task(removable["id"]))
            self.assertIsNotNone(store.get_task(protected["id"]))

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
            self.assertEqual(artifact["version"], 3)
            self.assertEqual(len(artifact["plan_digest"]), 64)
            self.assertEqual(len(artifact["artifact_digest"]), 64)
            self.assertIsInstance(artifact["baseline"], list)
            self.assertEqual(artifact["plan"]["summary"]["metadata_writes"], 1)
            self.assertFalse(plan_path.with_suffix(plan_path.suffix + ".tmp").exists())

            api_payload = store.read_plan_artifact(task_id, "/tmp/media/Movie")
            self.assertEqual(api_payload["plan"]["actions"][0]["kind"], "main_nfo")
            self.assertEqual(api_payload["integrity_status"], "verified")

            artifact["baseline"][0]["exists"] = not artifact["baseline"][0]["exists"]
            plan_path.write_text(json.dumps(artifact), encoding="utf-8")
            with self.assertRaises(PlanIntegrityError):
                store.read_plan_artifact(task_id, "/tmp/media/Movie")

    def test_plan_integrity_detects_source_tree_drift(self):
        from src.core.plan_integrity import build_plan_baseline, detect_plan_drift, plan_digest

        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            source = root / "Movie"
            source.mkdir()
            video = source / "movie.mkv"
            video.write_text("video", encoding="utf-8")
            plan = {
                "source_path": str(source),
                "target_root": str(source),
                "actions": [{"type": "create_file", "destination": str(source / "movie.nfo")}],
            }

            baseline = build_plan_baseline(plan)
            digest = plan_digest(plan)
            self.assertEqual(len(digest), 64)
            self.assertEqual(detect_plan_drift(baseline), [])

            video.write_text("changed-video", encoding="utf-8")
            drift = detect_plan_drift(baseline)
            self.assertTrue(drift)
            self.assertEqual(drift[0]["path"], str(source))

    def test_execution_preflight_estimates_copy_bytes_and_accepts_writable_target(self):
        from src.core.execution_preflight import assess_execution_preflight

        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            video = source / "movie.mkv"
            video.write_bytes(b"x" * 4096)
            result = assess_execution_preflight({
                "source_path": str(source),
                "target_root": str(target),
                "actions": [{
                    "type": "copy_file",
                    "source": str(video),
                    "destination": str(target / "movie.mkv"),
                    "status": "ready",
                }],
            })

            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["required_bytes"], 4096)
            self.assertGreaterEqual(result["free_bytes"], result["required_bytes"])

    def test_execution_preflight_blocks_missing_source_and_insufficient_space(self):
        from src.core.execution_preflight import assess_execution_preflight

        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            target = root / "target"
            target.mkdir()
            plan = {
                "source_path": str(root / "missing"),
                "target_root": str(target),
                "actions": [{
                    "type": "create_file",
                    "destination": str(target / "movie.nfo"),
                    "status": "ready",
                }],
            }
            with patch("src.core.execution_preflight.shutil.disk_usage") as disk_usage:
                disk_usage.return_value.free = 1
                result = assess_execution_preflight(plan)

            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["blocked"], 2)
            self.assertIn("source_missing", {check["code"] for check in result["checks"]})
            self.assertIn("insufficient_disk_space", {check["code"] for check in result["checks"]})

    def test_execution_preflight_blocks_paths_outside_declared_roots(self):
        from src.core.execution_preflight import assess_execution_preflight

        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            outside = root / "outside"
            source.mkdir()
            target.mkdir()
            outside.mkdir()
            video = source / "movie.mkv"
            video.write_bytes(b"video")

            result = assess_execution_preflight({
                "source_path": str(source),
                "target_root": str(target),
                "actions": [{
                    "type": "move_file",
                    "source": str(video),
                    "destination": str(outside / "movie.mkv"),
                    "status": "ready",
                }],
            })

            self.assertEqual(result["status"], "blocked")
            self.assertIn(
                "action_destination_outside_root",
                {check["code"] for check in result["checks"]},
            )

    def test_execution_preflight_blocks_symlink_path_escape(self):
        from src.core.execution_preflight import assess_execution_preflight

        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            outside = root / "outside"
            source.mkdir()
            target.mkdir()
            outside.mkdir()
            video = source / "movie.mkv"
            video.write_bytes(b"video")
            (target / "linked").symlink_to(outside, target_is_directory=True)

            result = assess_execution_preflight({
                "source_path": str(source),
                "target_root": str(target),
                "actions": [{
                    "type": "copy_file",
                    "source": str(video),
                    "destination": str(target / "linked" / "movie.mkv"),
                    "status": "ready",
                }],
            })

            self.assertEqual(result["status"], "blocked")
            self.assertIn(
                "action_destination_outside_root",
                {check["code"] for check in result["checks"]},
            )

    def test_plan_keeps_every_action_beyond_ui_preview_sizes(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            source = Path(temp_dir) / "Incoming"
            source.mkdir()
            files = []
            for index in range(205):
                path = source / f"movie-part-{index:03d}.mkv"
                path.write_bytes(b"video")
                files.append(path)

            organizer = MediaOrganizer(
                dry_run=True,
                inplace_rename=True,
                enable_organize=True,
                conflict_strategy="suffix",
            )
            plan = organizer.build_plan(
                source,
                {
                    "normalized": {
                        "media_type": "movie",
                        "title": "Complete Plan",
                        "year": 2026,
                    },
                    "source_data": {},
                    "nfo": {},
                },
                configured_media_type="movie",
            )

            move_actions = [
                action for action in plan["actions"]
                if action.get("type") in {"move_file", "replace_file"}
            ]
            self.assertEqual(len(move_actions), len(files))
            self.assertIn(str(files[-1]), {action["source"] for action in move_actions})
            self.assertGreater(plan["summary"]["actions"], 200)

    def test_metadata_titles_cannot_create_nested_or_parent_paths(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            source = Path(temp_dir) / "Incoming"
            source.mkdir()
            video = source / "movie.mkv"
            video.write_bytes(b"video")
            organizer = MediaOrganizer(
                dry_run=True,
                inplace_rename=True,
                enable_organize=True,
            )

            plan = organizer.build_plan(
                source,
                {
                    "normalized": {
                        "media_type": "movie",
                        "title": "../../Escaped/Movie",
                        "year": 2026,
                    },
                    "source_data": {},
                    "nfo": {},
                },
                configured_media_type="movie",
            )

            target = Path(plan["target_root"]).resolve()
            for action in plan["actions"]:
                if action.get("status") != "ready" or not action.get("destination"):
                    continue
                Path(action["destination"]).resolve().relative_to(target)
            self.assertNotIn("..", Path(plan["target_root"]).name)

    def test_nfo_written_event_persists_structured_output_evidence(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            store = TaskEventStore(storage_path=str(Path(temp_dir) / "tasks.json"))
            task = store.create_task("/media", {})
            store.emit(
                task["id"],
                "nfo.written",
                {"path": "/media/tvshow.nfo", "kind": "main_nfo", "status": "written", "atomic": True},
                item_id="/media",
            )

            output = store.get_task(task["id"])["items"]["/media"]["nfo_outputs"][0]
            self.assertEqual(output["path"], "/media/tvshow.nfo")
            self.assertEqual(output["kind"], "main_nfo")
            self.assertTrue(output["atomic"])

    def test_quarantined_item_persists_parse_evidence_and_count(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            store = TaskEventStore(storage_path=str(Path(temp_dir) / "tasks.json"))
            task = store.create_task("/media", {})
            store.emit(
                task["id"],
                "item.quarantined",
                {
                    "name": "1080p.x265.mkv",
                    "path": "/media/1080p.x265.mkv",
                    "kind": "quarantined",
                    "reason": "Filename could not be parsed with sufficient confidence.",
                    "parse_confidence": "none",
                    "parse": {"confidence": "none", "reasons": ["no_stable_title"]},
                },
                item_id="/media/1080p.x265.mkv",
            )

            restored = store.get_task(task["id"])
            item = restored["items"]["/media/1080p.x265.mkv"]
            compact = store.list_tasks(compact=True)[0]["items"]["/media/1080p.x265.mkv"]
            self.assertEqual(item["status"], "quarantined")
            self.assertEqual(item["parse"]["confidence"], "none")
            self.assertEqual(restored["summary"]["quarantined"], 1)
            self.assertEqual(compact["parse_confidence"], "none")
            self.assertEqual(compact["parse"]["reasons"], ["no_stable_title"])

    def test_cancellation_lifecycle_persists_requested_and_cancelled_state(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            store = TaskEventStore(storage_path=str(Path(temp_dir) / "tasks.json"))
            task = store.create_task("/media", {})
            task_id = task["id"]
            store.emit(task_id, "task.started", {"input_dir": "/media"})
            store.emit(task_id, "item.started", {"name": "Movie", "path": "/media/Movie"}, item_id="/media/Movie")
            store.emit(task_id, "task.cancel_requested", {"stage": "requested"})

            requested = store.get_task(task_id)
            self.assertEqual(requested["status"], "cancel_requested")

            store.emit(task_id, "item.cancelled", {"stage": "artwork.stream"}, item_id="/media/Movie")
            store.emit(task_id, "task.cancelled", {"stage": "worker_loop", "summary": {"cancelled": 1}})

            restored = TaskEventStore(storage_path=str(Path(temp_dir) / "tasks.json")).get_task(task_id)
            self.assertEqual(restored["status"], "cancelled")
            self.assertEqual(restored["summary"]["cancelled"], 1)
            self.assertEqual(restored["items"]["/media/Movie"]["status"], "cancelled")
            self.assertEqual(restored["items"]["/media/Movie"]["stage"], "artwork.stream")

    def test_execution_phase_and_progress_survive_task_store_restart(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            storage_path = str(Path(temp_dir) / "tasks.json")
            store = TaskEventStore(storage_path=storage_path)
            task = store.create_task(
                "/media/Movie",
                {"dry_run": False, "source_plan_task_id": "audit-task"},
            )
            store.emit(task["id"], "task.started", {"input_dir": "/media/Movie"})
            store.emit(
                task["id"],
                "item.execution_phase",
                {"phase": "organizing", "name": "Movie"},
                item_id="/media/Movie",
            )
            store.emit(
                task["id"],
                "task.progress",
                {"processed": 1, "total": 2, "completed": 1, "failed": 0},
            )

            executions = TaskEventStore(storage_path=storage_path).list_executions()

            self.assertEqual(len(executions), 1)
            self.assertEqual(executions[0]["phase"], "organizing")
            self.assertEqual(executions[0]["progress"]["processed"], 1)
            self.assertEqual(executions[0]["items"]["/media/Movie"]["phase"], "organizing")

    def test_execution_projection_preserves_structured_operation_failure(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            storage_path = str(Path(temp_dir) / "tasks.json")
            store = TaskEventStore(storage_path=storage_path)
            task = store.create_task("/media/Movie", {"dry_run": False})
            operation = {
                "stage": "organize.file_operation",
                "action": "move_file",
                "source": "/media/Movie/source.mkv",
                "destination": "/library/Movie/Movie.mkv",
                "error": "permission denied",
            }
            store.emit(
                task["id"],
                "item.failed",
                {
                    "name": "Movie",
                    "error": "move_file failed at organize.file_operation: permission denied",
                    "error_code": "ORGANIZER_OPERATION_FAILED",
                    "operation": operation,
                },
                item_id="/media/Movie",
            )

            execution = TaskEventStore(storage_path=storage_path).list_executions()[0]
            item = execution["items"]["/media/Movie"]
            failed_event = next(event for event in execution["timeline"] if event["type"] == "item.failed")

            self.assertEqual(item["operation"], operation)
            self.assertEqual(failed_event["payload"]["operation"], operation)

    def test_operation_lifecycle_survives_restart_in_execution_projection(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            storage_path = str(Path(temp_dir) / "tasks.json")
            store = TaskEventStore(storage_path=storage_path)
            task = store.create_task("/media/Movie", {"dry_run": False})
            operation = {
                "stage": "organize.file_operation",
                "action": "move_file",
                "source": "/media/Movie/source.mkv",
                "destination": "/library/Movie/Movie.mkv",
            }
            store.emit(
                task["id"],
                "operation.started",
                {"operation": operation},
                item_id="/media/Movie",
            )

            running = TaskEventStore(storage_path=storage_path).list_executions()[0]
            running_item = running["items"]["/media/Movie"]
            self.assertEqual(running_item["current_operation"]["destination"], operation["destination"])
            self.assertEqual(running_item["operation_summary"]["started"], 1)

            store.emit(
                task["id"],
                "operation.completed",
                {"operation": operation},
                item_id="/media/Movie",
            )
            completed = TaskEventStore(storage_path=storage_path).list_executions()[0]
            completed_item = completed["items"]["/media/Movie"]

            self.assertNotIn("current_operation", completed_item)
            self.assertEqual(completed_item["latest_operation"]["status"], "completed")
            self.assertEqual(completed_item["operation_summary"]["completed"], 1)
            self.assertEqual(completed_item["operation_history"][0]["destination"], operation["destination"])
            self.assertEqual(
                [event["type"] for event in completed["timeline"] if event["type"].startswith("operation.")],
                ["operation.started", "operation.completed"],
            )

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


class TrustedOriginPolicyTest(unittest.TestCase):
    def test_default_policy_accepts_loopback_and_rejects_deceptive_origins(self):
        policy = TrustedOriginPolicy(frozenset(), allow_loopback=True)

        self.assertTrue(policy.allows(None))
        self.assertTrue(policy.allows("http://localhost:5173"))
        self.assertTrue(policy.allows("https://127.0.0.1:9443"))
        self.assertTrue(policy.allows("http://[::1]:5173"))
        self.assertFalse(policy.allows("https://localhost.evil.example"))
        self.assertFalse(policy.allows("https://127.0.0.1.evil.example"))
        self.assertFalse(policy.allows("null"))
        self.assertFalse(policy.allows("file:///tmp/index.html"))

    def test_explicit_remote_origins_are_normalized_and_loopback_can_be_disabled(self):
        with patch.dict(
            "os.environ",
            {
                "WEB_ALLOWED_ORIGINS": (
                    "https://media.example.test/,http://192.168.1.20:5173"
                ),
                "WEB_ALLOW_LOOPBACK_ORIGINS": "0",
            },
            clear=False,
        ):
            policy = TrustedOriginPolicy.from_environment()

        self.assertEqual(
            policy.cors_origins,
            [
                "http://192.168.1.20:5173",
                "https://media.example.test",
            ],
        )
        self.assertTrue(policy.allows("https://media.example.test"))
        self.assertTrue(policy.allows("http://192.168.1.20:5173/"))
        self.assertFalse(policy.allows("http://localhost:5173"))
        self.assertIsNone(policy.cors_origin_regex)

    def test_invalid_explicit_origin_fails_closed(self):
        with patch.dict(
            "os.environ",
            {"WEB_ALLOWED_ORIGINS": "*,javascript:alert(1)"},
            clear=False,
        ):
            with self.assertRaisesRegex(ValueError, "Invalid WEB_ALLOWED_ORIGINS"):
                TrustedOriginPolicy.from_environment()


class LibraryScanServiceTest(unittest.TestCase):
    def test_scan_detects_duplicate_episodes_without_modifying_media(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir) / "Library"
            season = root / "Example Show (2026)" / "Season 01"
            season.mkdir(parents=True)
            first = season / "Example Show - S01E01 - One.mkv"
            second = season / "Example Show - S01E01 - Duplicate.mkv"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            before = {
                str(path): (path.stat().st_size, path.stat().st_mtime_ns)
                for path in root.rglob("*")
                if path.is_file()
            }

            result = LibraryScanService().scan(root, mode="auto")
            after = {
                str(path): (path.stat().st_size, path.stat().st_mtime_ns)
                for path in root.rglob("*")
                if path.is_file()
            }

            self.assertEqual(result["mode"], "batch")
            self.assertEqual(result["summary"]["review"], 1)
            self.assertEqual(result["summary"]["videos"], 2)
            item = result["items"][0]
            self.assertEqual(item["status"], "review")
            duplicate = next(issue for issue in item["issues"] if issue["code"] == "duplicate_episode_files")
            self.assertEqual(duplicate["episode"], "S01E01")
            self.assertEqual(len(duplicate["sources"]), 2)
            self.assertEqual(before, after)

    def test_auto_scan_treats_season_root_as_single_show(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            show = Path(temp_dir) / "Example Show (2026)"
            season = show / "Season 01"
            season.mkdir(parents=True)
            (season / "Example Show - S01E01.mkv").write_text("video", encoding="utf-8")

            result = LibraryScanService().scan(show, mode="auto")

            self.assertEqual(result["mode"], "single")
            self.assertEqual(result["summary"]["items"], 1)
            self.assertEqual(result["items"][0]["path"], str(show.resolve()))
            self.assertEqual(result["items"][0]["media_type"], "tv")

    def test_scan_flags_canonical_artwork_with_mismatched_file_format(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            show = Path(temp_dir) / "Example Show (2026)"
            season = show / "Season 01"
            season.mkdir(parents=True)
            (season / "Example Show - S01E01.mkv").write_bytes(b"video")
            (show / "poster.jpg").write_bytes(b"\xff\xd8\xff" + b"x" * 64)
            invalid_logo = show / "clearlogo.png"
            invalid_logo.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")

            result = LibraryScanService().scan(show, mode="single")

            item = result["items"][0]
            self.assertEqual(item["status"], "review")
            issue = next(issue for issue in item["issues"] if issue["code"] == "invalid_artwork_file")
            self.assertEqual(issue["level"], "warning")
            self.assertEqual(issue["sources"], [str(invalid_logo)])
            self.assertEqual(item["artwork"]["poster"], 1)
            self.assertEqual(item["artwork"]["logo"], 1)

    def test_loose_unparseable_video_is_quarantined(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            (root / "1080p.x265.DTS.mkv").write_text("video", encoding="utf-8")

            result = LibraryScanService().scan(root, mode="batch")

            self.assertEqual(result["summary"]["quarantined"], 1)
            self.assertEqual(result["items"][0]["kind"], "quarantined")
            self.assertEqual(result["items"][0]["issues"][0]["code"], "unparseable_title")


class OperationManifestSummaryTest(unittest.TestCase):
    def test_manifest_summary_counts_reversible_actions(self):
        summary = summarize_manifest(
            {
                "created_at": "2026-06-06T00:00:00Z",
                "operations": [
                    {"action": "move_file"},
                    {"action": "create_file"},
                    {"action": "download_image"},
                    "invalid",
                ],
            }
        )

        self.assertTrue(summary["exists"])
        self.assertEqual(summary["operation_count"], 3)
        self.assertEqual(summary["reversible_count"], 2)
        self.assertEqual(summary["action_counts"]["move_file"], 1)
        self.assertEqual(summary["action_counts"]["download_image"], 1)

    def test_missing_manifest_has_zero_counts(self):
        summary = summarize_manifest(None)

        self.assertFalse(summary["exists"])
        self.assertEqual(summary["operation_count"], 0)
        self.assertEqual(summary["reversible_count"], 0)


class ArtworkPolicyTest(unittest.TestCase):
    def test_image_ranking_prefers_language_before_votes_and_resolution(self):
        downloader = ArtworkDownloader("tmdb")
        policy = downloader._normalize_policy(
            {
                "preferred_languages": ["zh", "en"],
                "min_poster_width": 500,
            }
        )
        ranked = downloader._rank_images(
            [
                {"file_path": "/en.jpg", "iso_639_1": "en", "width": 2000, "height": 3000, "vote_average": 9.8, "vote_count": 1000},
                {"file_path": "/zh.jpg", "iso_639_1": "zh", "width": 600, "height": 900, "vote_average": 6.0, "vote_count": 2},
                {"file_path": "/none.jpg", "iso_639_1": None, "width": 2500, "height": 3750, "vote_average": 10.0, "vote_count": 2000},
            ],
            "poster",
            policy,
        )

        self.assertEqual([item["file_path"] for item in ranked], ["/zh.jpg", "/en.jpg", "/none.jpg"])
        self.assertEqual(ranked[0]["_selection_rank"], 1)

    def test_image_ranking_filters_small_assets_and_marks_total_fallback(self):
        downloader = ArtworkDownloader("tmdb")
        strict = downloader._normalize_policy({"min_logo_width": 500})
        ranked = downloader._rank_images(
            [
                {"file_path": "/small.png", "width": 200, "height": 80},
                {"file_path": "/large.png", "width": 800, "height": 320},
            ],
            "logo",
            strict,
        )
        fallback = downloader._rank_images(
            [{"file_path": "/only-small.png", "width": 200, "height": 80}],
            "logo",
            strict,
        )

        self.assertEqual([item["file_path"] for item in ranked], ["/large.png"])
        self.assertTrue(fallback[0]["_minimum_width_fallback"])

    def test_compact_task_list_keeps_ui_fields_without_heavy_plan_preview(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            storage_path = Path(temp_dir) / "task_events.json"
            store = TaskEventStore(storage_path=str(storage_path), max_tasks=10)
            task = store.create_task("/tmp/media", {"dry_run": True})
            task_id = task["id"]
            plan = {
                "target_root": "/tmp/library/Movie",
                "mode": "metadata_only",
                "rollback_available": False,
                "summary": {"actions": 25, "risks": 20, "metadata_writes": 12},
                "review": {
                    "required": True,
                    "status": "manual_review",
                    "reason_count": 1,
                    "reasons": [{"level": "error", "code": "duplicate_episode_files", "message": "Duplicate episode"}],
                },
                "actions": [{"type": "create_file", "destination": f"/tmp/library/Movie/{index}.nfo"} for index in range(25)],
                "risks": [{"level": "warning", "message": f"risk-{index}"} for index in range(20)],
            }
            store.emit(task_id, "item.plan_ready", {"plan": plan}, item_id="/tmp/media/Movie")
            store.emit(
                task_id,
                "candidate.selected",
                {
                    "title": "Movie",
                    "tmdb_id": 123,
                    "poster_path": "/poster.jpg",
                    "match": {
                        "provider": "tmdb",
                        "confidence": "high",
                        "selected_id": 123,
                        "candidates": [
                            {
                                "id": index,
                                "title": f"Candidate {index}",
                                "score": 0.9,
                                "title_similarity": 0.95,
                                "token_overlap": 1.0,
                                "evidence": {
                                    "schema_version": 1,
                                    "composite_score": 0.9,
                                    "title_similarity": 0.95,
                                    "token_overlap": 1.0,
                                    "dimensions": {
                                        "year": {"score": 1.0, "status": "exact", "target": 2026, "candidate": 2026},
                                        "media_type": {"score": 1.0, "status": "exact"},
                                    },
                                    "hard_blockers": [],
                                    "warnings": [],
                                },
                            }
                            for index in range(10)
                        ],
                    },
                },
                item_id="/tmp/media/Movie",
            )

            compact = store.list_tasks(compact=True)[0]
            full = store.get_task(task_id)
            compact_item = compact["items"]["/tmp/media/Movie"]
            full_item = full["items"]["/tmp/media/Movie"]

            self.assertTrue(compact["compact"])
            self.assertEqual(compact_item["candidate"]["title"], "Movie")
            self.assertEqual(compact_item["plan"]["target_root"], "/tmp/library/Movie")
            self.assertEqual(compact_item["plan"]["summary"]["actions"], 25)
            self.assertEqual(compact_item["plan"]["review"]["status"], "manual_review")
            self.assertNotIn("actions", compact_item["plan"])
            self.assertNotIn("risks", compact_item["plan"])
            self.assertEqual(len(compact_item["match"]["candidates"]), 3)
            self.assertEqual(
                compact_item["match"]["candidates"][0]["evidence"]["dimensions"]["year"]["status"],
                "exact",
            )
            self.assertEqual(compact_item["match"]["candidates"][0]["title_similarity"], 0.95)
            self.assertEqual(len(full_item["plan"]["actions"]), 5)
            self.assertEqual(len(full_item["match"]["candidates"]), 10)

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
        self.assertEqual(manager._final_event_for_results({"total": 1, "completed": 0, "partial": 1, "failed": 0})[0], "task.partial")
        self.assertEqual(manager._final_event_for_results({"total": 1, "completed": 0, "failed": 0, "quarantined": 1})[0], "task.partial")
        self.assertEqual(manager._final_event_for_results({"total": 2, "completed": 2, "failed": 0})[0], "task.completed")
        self.assertEqual(manager._final_event_for_results({"total": 2, "completed": 1, "failed": 0, "stopped": True})[0], "task.cancelled")

    def test_stop_during_auto_prescan_emits_cancelled_event(self):
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

        self.assertIn(("task-stop", "task.cancelled", {"stage": "during_pre_scan"}, None), events)


class ServerStartTaskValidationTest(unittest.IsolatedAsyncioTestCase):
    def test_task_start_request_rejects_invalid_contract_values(self):
        from src.server.main import TaskStartRequest

        invalid_payloads = [
            {"input_dir": "/tmp/media", "search_mode": "google"},
            {"input_dir": "/tmp/media", "media_type": "anime"},
            {"input_dir": "/tmp/media", "operation_scope": "metadata"},
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

    async def test_start_task_applies_operation_scope_to_effective_options(self):
        from src.server import main

        class DummyTaskStore:
            def create_task(self, input_dir, config):
                self.config = config
                return {"id": "task-scope"}

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
            request = main.TaskStartRequest(
                input_dir=temp_dir,
                operation_scope="nfo_only",
                extra_images=True,
                enable_organize=True,
                overwrite_images=True,
                rename_parent_dir=True,
            )

            with patch.object(main, "task_event_store", task_store), patch.object(main, "job_manager", job_manager):
                await main.start_task(request)
                await asyncio.sleep(0)

            for key in ("extra_images", "enable_organize", "overwrite_images", "rename_parent_dir"):
                self.assertFalse(task_store.config[key])
                self.assertFalse(job_manager.kwargs[key])

    def test_batch_scraper_uses_frozen_runtime_config(self):
        from src.batch.scraper import BatchMediaScraper

        runtime_config = {
            "tmdb": {"api_key": "frozen-key"},
            "matching": {"minimum_title_similarity": 0.81},
            "output": {"conflict_strategy": "suffix"},
        }
        with patch.object(BatchMediaScraper, "_load_config", side_effect=AssertionError("disk config must not be read")):
            scraper = BatchMediaScraper(
                runtime_config=runtime_config,
                dry_run=True,
            )

        runtime_config["tmdb"]["api_key"] = "mutated-after-start"
        self.assertEqual(scraper.config["tmdb"]["api_key"], "frozen-key")
        self.assertEqual(scraper.config["matching"]["minimum_title_similarity"], 0.81)
        self.assertEqual(scraper.conflict_strategy, "suffix")


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
            self.assertEqual(list(manifest_dir.glob("*.tmp")), [])

    def test_concurrent_records_are_not_lost_or_corrupted(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            manifest_dir = root / "manifests"
            output_dir = root / "output"
            output_dir.mkdir()
            manifest = OperationManifest("task-concurrent", manifest_dir=str(manifest_dir))
            count = 80

            def record_file(index: int) -> None:
                destination = output_dir / f"{index:03d}.nfo"
                destination.write_text(f"metadata-{index}", encoding="utf-8")
                manifest.record("create_file", None, destination, extra={"index": index})

            with ThreadPoolExecutor(max_workers=12) as executor:
                list(executor.map(record_file, range(count)))

            persisted = json.loads((manifest_dir / "task-concurrent.json").read_text(encoding="utf-8"))
            indexes = sorted(operation["index"] for operation in persisted["operations"])

            self.assertEqual(len(manifest.operations), count)
            self.assertEqual(len(persisted["operations"]), count)
            self.assertEqual(indexes, list(range(count)))
            self.assertEqual(list(manifest_dir.glob("*.tmp")), [])

    def test_concurrent_backups_use_unique_paths(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            target = root / "movie.nfo"
            target.write_text("original", encoding="utf-8")
            manifest = OperationManifest("task-backups", manifest_dir=str(root / "manifests"))

            with ThreadPoolExecutor(max_workers=8) as executor:
                backups = list(executor.map(lambda _: manifest.backup_file(target), range(24)))

            backup_paths = [path for path in backups if path]
            self.assertEqual(len(backup_paths), 24)
            self.assertEqual(len({str(path) for path in backup_paths}), 24)
            self.assertTrue(all(path.read_text(encoding="utf-8") == "original" for path in backup_paths))

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

    def test_rollback_preview_reports_actions_without_changing_files(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            source = root / "source.mkv"
            destination = root / "Season 01" / "renamed.mkv"
            destination.parent.mkdir()
            destination.write_text("video", encoding="utf-8")

            manifest_dir = root / "manifests"
            manifest = OperationManifest("preview-task", manifest_dir=str(manifest_dir))
            manifest.record("move_file", source, destination)

            preview = preview_rollback_manifest("preview-task", manifest_dir=str(manifest_dir))

            self.assertEqual(preview["status"], "preview")
            self.assertTrue(preview["preview"])
            self.assertEqual(preview["operations"][0]["status"], "would_rolled_back")
            self.assertFalse(source.exists())
            self.assertTrue(destination.exists())

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

    def test_nfo_writer_rejects_nested_or_parent_filename(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            media_dir = Path(temp_dir) / "media"
            media_dir.mkdir()

            with self.assertRaises(ValueError):
                FileSystemManager.write_nfo_file(
                    str(media_dir),
                    "../escaped.nfo",
                    "<movie />",
                )

            self.assertFalse((Path(temp_dir) / "escaped.nfo").exists())


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

            self.assertEqual(plan["summary"]["blocked"], 2)
            self.assertEqual(plan["summary"]["conflicts"], 1)
            self.assertEqual(plan["summary"]["missing_episodes"], 1)
            self.assertIn("S01E02", plan["missing_episodes"])
            self.assertEqual(plan["actions"][0]["status"], "blocked")
            self.assertTrue(any(risk.get("code") == "duplicate_episode_files" for risk in plan["risks"]))

    def test_conflict_strategies_are_explicit_and_non_blocking_when_resolved(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            source = root / "episode.mkv"
            destination = root / "library" / "episode.mkv"
            destination.parent.mkdir()
            source.write_text("new", encoding="utf-8")
            destination.write_text("old", encoding="utf-8")

            expected = {
                "error": ("blocked", "move_file", "blocked"),
                "skip": ("skipped", "move_file", "skipped"),
                "suffix": ("ready", "move_file", "renamed"),
                "overwrite": ("ready", "replace_file", "overwrite_with_backup"),
            }
            for strategy, (status, action_type, resolution) in expected.items():
                with self.subTest(strategy=strategy):
                    organizer = MediaOrganizer(enable_organize=True, conflict_strategy=strategy)
                    action, conflict = organizer._resolve_file_action(source, destination, "move_file")
                    self.assertEqual(action["status"], status)
                    self.assertEqual(action["type"], action_type)
                    self.assertEqual(conflict["resolution"], resolution)
                    self.assertEqual(organizer.has_blockers({
                        "summary": {"blocked": 1 if status == "blocked" else 0},
                        "conflicts": [conflict],
                    }), status == "blocked")
                    if strategy == "suffix":
                        self.assertEqual(Path(action["destination"]).name, "episode (1).mkv")

    def test_overwrite_move_restores_both_source_and_original_destination(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            source = root / "incoming.mkv"
            destination = root / "library" / "movie.mkv"
            destination.parent.mkdir()
            source.write_text("new-media", encoding="utf-8")
            destination.write_text("old-media", encoding="utf-8")
            manifest_dir = root / "manifests"

            organizer = MediaOrganizer(enable_organize=True, conflict_strategy="overwrite", task_id="replace-task")
            organizer.manifest = OperationManifest("replace-task", manifest_dir=str(manifest_dir))
            organizer._move_or_copy(source, destination)

            self.assertFalse(source.exists())
            self.assertEqual(destination.read_text(encoding="utf-8"), "new-media")
            manifest = json.loads((manifest_dir / "replace-task.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["operations"][0]["action"], "replace_file")
            self.assertEqual(manifest["operations"][0]["conflict_resolution"], "overwrite_with_backup")

            preview = preview_rollback_manifest("replace-task", manifest_dir=str(manifest_dir))
            self.assertEqual(preview["operations"][0]["status"], "would_restored_replacement")
            rollback = rollback_manifest("replace-task", manifest_dir=str(manifest_dir))

            self.assertEqual(rollback["status"], "completed")
            self.assertEqual(source.read_text(encoding="utf-8"), "new-media")
            self.assertEqual(destination.read_text(encoding="utf-8"), "old-media")

    def test_file_move_emits_auditable_operation_lifecycle(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            source = root / "incoming.mkv"
            destination = root / "library" / "movie.mkv"
            source.write_bytes(b"video")
            store = TaskEventStore(storage_path=str(root / "tasks.json"))
            task = store.create_task(str(root), {"dry_run": False})
            organizer = MediaOrganizer(enable_organize=True, task_id=task["id"])
            organizer.manifest = OperationManifest(task["id"], manifest_dir=str(root / "manifests"))

            with patch("src.server.task_events.task_event_store", store):
                organizer._move_or_copy(source, destination, item_id=str(source))

            restored = TaskEventStore(storage_path=str(root / "tasks.json")).get_task(task["id"])
            operation_events = [
                event for event in restored["events"] if event["type"].startswith("operation.")
            ]
            file_events = [
                event for event in operation_events
                if event["payload"]["operation"]["action"] == "move_file"
            ]

            self.assertEqual([event["type"] for event in file_events], [
                "operation.started",
                "operation.completed",
            ])
            self.assertEqual(file_events[0]["payload"]["operation"]["source"], str(source))
            self.assertEqual(file_events[1]["payload"]["operation"]["destination"], str(destination))
            self.assertFalse(source.exists())
            self.assertTrue(destination.exists())

    def test_failed_copy_stops_and_leaves_only_non_applied_audit_evidence(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            source = root / "incoming.mkv"
            destination = root / "library" / "movie.mkv"
            source.write_bytes(b"video")
            manifest_dir = root / "manifests"
            organizer = MediaOrganizer(
                enable_organize=True,
                copy_files=True,
                task_id="failed-copy",
            )
            organizer.manifest = OperationManifest("failed-copy", manifest_dir=str(manifest_dir))

            with patch("src.batch.organizer.shutil.copy2", side_effect=OSError("disk write failed")):
                with self.assertRaises(OrganizerExecutionError) as caught:
                    organizer._move_or_copy(source, destination)

            self.assertEqual(caught.exception.stage, "organize.file_operation")
            self.assertTrue(source.exists())
            self.assertFalse(destination.exists())
            self.assertEqual(list(destination.parent.glob("*.copying")), [])
            manifest = get_manifest("failed-copy", manifest_dir=str(manifest_dir))
            failed_operation = next(operation for operation in manifest["operations"] if operation["status"] == "failed")
            self.assertEqual(failed_operation["action"], "copy_file")
            summary = summarize_manifest(manifest)
            self.assertEqual(summary["operation_count"], 1)
            self.assertEqual(summary["attempted_count"], 2)
            self.assertEqual(summary["failed_count"], 1)
            self.assertEqual(summary["reversible_count"], 1)
            rollback_preview = preview_rollback_manifest("failed-copy", manifest_dir=str(manifest_dir))
            self.assertEqual(rollback_preview["operations"][0]["action"], "create_dir")
            recovery = preview_recovery_manifest("failed-copy", manifest_dir=str(manifest_dir))
            self.assertEqual(recovery["strategy"], "rollback_then_retry")
            self.assertTrue(recovery["rollback_required"])

    def test_cross_filesystem_move_records_published_copy_when_source_delete_fails(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            source = root / "incoming.mkv"
            destination = root / "library" / "movie.mkv"
            source.write_bytes(b"video")
            manifest_dir = root / "manifests"
            organizer = MediaOrganizer(enable_organize=True, task_id="partial-move")
            organizer.manifest = OperationManifest("partial-move", manifest_dir=str(manifest_dir))
            organizer._same_filesystem = lambda *args: False
            organizer._remove_source_after_copy = lambda *args: (_ for _ in ()).throw(OSError("source delete failed"))

            with self.assertRaises(OrganizerExecutionError):
                organizer._move_or_copy(source, destination)

            self.assertTrue(source.exists())
            self.assertEqual(destination.read_bytes(), b"video")
            manifest = get_manifest("partial-move", manifest_dir=str(manifest_dir))
            self.assertEqual([item["status"] for item in manifest["operations"]], ["done", "done", "failed"])
            published_copy = next(item for item in manifest["operations"] if item["action"] == "copy_file")
            self.assertEqual(published_copy["status"], "done")
            recovery = preview_recovery_manifest("partial-move", manifest_dir=str(manifest_dir))
            self.assertEqual(recovery["strategy"], "rollback_then_retry")
            rollback = rollback_manifest("partial-move", manifest_dir=str(manifest_dir))
            self.assertEqual(rollback["status"], "completed")
            self.assertFalse(destination.exists())
            self.assertTrue(source.exists())

    def test_scraper_surfaces_organizer_failure_and_stops_before_verification(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            show_path = Path(temp_dir) / "Example Movie (2026)"
            show_path.mkdir()
            (show_path / "Example.Movie.2026.mkv").write_text("video", encoding="utf-8")

            class FakePipeline:
                def run(self, input_data):
                    status = "plan_ready" if input_data.get("plan_only") else "completed"
                    return {
                        "status": status,
                        "candidate": {"id": 1, "title": "Example Movie", "media_type": "movie"},
                        "match": {"provider": "tmdb", "confidence": "high"},
                        "normalized": {"media_type": "movie", "title": "Example Movie", "year": 2026},
                        "source_data": {},
                        "nfo": {},
                    }

            class FailingOrganizer:
                def build_plan(self, path, *args, **kwargs):
                    return {
                        "target_root": str(path),
                        "summary": {"blocked": 0, "conflicts": 0},
                        "conflicts": [],
                    }

                def has_blockers(self, plan):
                    return False

                def organize(self, *args, **kwargs):
                    raise OrganizerExecutionError(
                        "organize.file_operation",
                        "move_file",
                        show_path / "Example.Movie.2026.mkv",
                        show_path / "Example Movie (2026).mkv",
                        OSError("permission denied"),
                    )

            events = []
            scraper = object.__new__(BatchMediaScraper)
            scraper.dry_run = False
            scraper.media_type = "movie"
            scraper.inplace_rename = False
            scraper.output_dir = None
            scraper.extra_images = False
            scraper.enable_organize = True
            scraper.overwrite_images = False
            scraper.search_mode = "tmdb_only"
            scraper.enable_fallback = True
            scraper.fresh = False
            scraper.pipeline = FakePipeline()
            scraper.organizer = FailingOrganizer()
            scraper.stop_event = None
            scraper.task_id = None
            scraper._emit = lambda event_type, payload=None, item_id=None: events.append((event_type, payload or {}))

            success, reason = scraper._process_directory(show_path, None, task_media_type="movie")

            self.assertFalse(success)
            self.assertIn("Organizer stopped", reason)
            failed = next(payload for event_type, payload in events if event_type == "item.failed")
            self.assertEqual(failed["error_code"], "ORGANIZER_OPERATION_FAILED")
            self.assertEqual(failed["operation"]["destination"], str(show_path / "Example Movie (2026).mkv"))
            self.assertFalse(any(event_type == "item.verification_started" for event_type, _ in events))

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

    def test_plan_only_writes_episode_nfo_for_local_video_not_remote_missing_episode(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            show_path = Path(temp_dir) / "Example"
            show_path.mkdir()
            (show_path / "Example.S01E01.mkv").write_text("video", encoding="utf-8")
            (show_path / "Example.S01E02.srt").write_text("subtitle only", encoding="utf-8")
            metadata = {
                "normalized": {"media_type": "tv", "title": "Example", "title_zh": "Example", "year": 2026},
                "source_data": {
                    "translated_episodes": [
                        {"season_number": 1, "episode_number": 1, "name": "One"},
                        {"season_number": 1, "episode_number": 2, "name": "Two"},
                    ]
                },
                "nfo": {
                    "policy": {"profile": "universal", "episode_sidecars": "present_only"},
                    "season_nfos": {1: "<season />"},
                    "episode_nfos": {(1, 1): "<episodedetails />", (1, 2): "<episodedetails />"},
                },
            }

            plan = MediaOrganizer(enable_organize=False).build_plan(show_path, metadata)
            episode_actions = [action for action in plan["actions"] if action.get("kind") == "episode_nfo"]

            self.assertEqual(len(episode_actions), 1)
            self.assertIn("S01E01", episode_actions[0]["destination"])
            self.assertNotIn("S01E02", " ".join(action["destination"] for action in episode_actions))
            self.assertEqual(plan["nfo"]["present_episodes"], 1)
            self.assertEqual(plan["summary"]["missing_episodes"], 1)

    def test_plan_reports_duplicate_episode_numbers_as_error_risk(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            show_path = Path(temp_dir) / "Example"
            show_path.mkdir()
            (show_path / "Example.S01E01.first.mkv").write_text("video", encoding="utf-8")
            (show_path / "Example.S01E01.second.mkv").write_text("video", encoding="utf-8")
            metadata = {
                "normalized": {"media_type": "tv", "title": "Example", "year": 2026},
                "source_data": {
                    "translated_episodes": [
                        {"season_number": 1, "episode_number": 1, "name": "One"},
                    ]
                },
                "nfo": {"episode_nfos": {(1, 1): "<episodedetails />"}},
            }

            plan = MediaOrganizer(enable_organize=False).build_plan(show_path, metadata)
            duplicate_risks = [
                risk for risk in plan["risks"]
                if risk.get("code") == "duplicate_episode_files"
            ]

            self.assertEqual(plan["nfo"]["present_episodes"], 1)
            self.assertEqual(len(duplicate_risks), 1)
            self.assertEqual(duplicate_risks[0]["level"], "error")
            self.assertEqual(len(duplicate_risks[0]["sources"]), 2)
            self.assertEqual(plan["summary"]["blocked"], 1)
            self.assertEqual(plan["review"]["status"], "manual_review")
            self.assertEqual(plan["review"]["reason_count"], 1)
            self.assertEqual(plan["review"]["reasons"][0]["code"], "duplicate_episode_files")

    def test_operation_scopes_generate_only_allowed_actions(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            show_path = Path(temp_dir) / "Example"
            show_path.mkdir()
            (show_path / "Example.S01E01.mkv").write_text("video", encoding="utf-8")
            metadata = {
                "normalized": {"media_type": "tv", "title": "Example", "title_zh": "Example", "year": 2026},
                "source_data": {
                    "translated_episodes": [
                        {"season_number": 1, "episode_number": 1, "name": "One"},
                    ]
                },
                "nfo": {
                    "season_nfos": {1: "<season />"},
                    "episode_nfos": {(1, 1): "<episodedetails />"},
                },
            }

            nfo_plan = MediaOrganizer(enable_organize=True, operation_scope="nfo_only").build_plan(show_path, metadata)
            artwork_plan = MediaOrganizer(enable_organize=True, operation_scope="artwork_only").build_plan(show_path, metadata)
            files_plan = MediaOrganizer(enable_organize=True, operation_scope="organize_only").build_plan(show_path, metadata)

            self.assertTrue(nfo_plan["actions"])
            self.assertTrue(all("nfo" in action.get("kind", "") for action in nfo_plan["actions"]))
            self.assertTrue(nfo_plan["rollback_available"])
            self.assertTrue(artwork_plan["actions"])
            self.assertTrue(all(action.get("kind", "").startswith("artwork") for action in artwork_plan["actions"]))
            self.assertTrue(artwork_plan["rollback_available"])
            self.assertTrue(files_plan["actions"])
            self.assertTrue(all(action["type"] in {"move_file", "copy_file", "replace_file", "rename_dir"} for action in files_plan["actions"]))
            self.assertTrue(files_plan["rollback_available"])
            self.assertEqual(files_plan["summary"]["metadata_writes"], 0)

    def test_loose_nfo_scope_is_blocked_without_moving_files(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            base_dir = Path(temp_dir)
            source = base_dir / "Example.S01E01.mkv"
            source.write_text("video", encoding="utf-8")
            metadata = {
                "normalized": {"media_type": "tv", "title": "Example", "title_zh": "Example", "year": 2026},
                "source_data": {"translated_episodes": []},
                "nfo": {},
            }

            plan = MediaOrganizer(enable_organize=False, operation_scope="nfo_only").build_loose_file_plan(
                [source], base_dir, "Example", metadata, "tv"
            )

            self.assertTrue(MediaOrganizer().has_blockers(plan))
            self.assertFalse(plan["rollback_available"])
            self.assertEqual(plan["actions"][0]["type"], "group_loose_files")
            self.assertEqual(plan["actions"][0]["status"], "blocked")
            self.assertTrue(source.exists())


class ExecutionPlanGuardTest(unittest.TestCase):
    def test_real_execution_writes_metadata_to_planned_target_and_rolls_back(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "raw download"
            source_dir.mkdir()
            source_video = source_dir / "raw.download.2026.mkv"
            source_video.write_text("video", encoding="utf-8")
            manifest_dir = root / "manifests"
            task_id = "execution-e2e"

            class FakePipeline:
                config = {"output": {"image_limit": {"posters": 1, "backdrops": 1, "logos": 1}}}
                extra_images = True
                artwork = object()

                def __init__(self, manifest):
                    self.manifest = manifest
                    self.calls = []

                def run(self, input_data):
                    self.calls.append(input_data.copy())
                    result = {
                        "candidate": {"id": 123, "title": "Example Movie", "media_type": "movie", "poster_path": "/poster.jpg"},
                        "match": {"provider": "tmdb", "confidence": "high", "score": 0.99},
                        "normalized": {"tmdb_id": 123, "media_type": "movie", "title": "Example Movie", "year": 2026},
                        "source_data": {},
                        "nfo": {"xml": "<movie><title>Example Movie</title></movie>"},
                    }
                    if input_data.get("plan_only"):
                        return {"status": "plan_ready", **result}

                    output_dir = Path(input_data["output_dir"])
                    output_dir.mkdir(parents=True, exist_ok=True)
                    nfo_path = output_dir / "Example Movie (2026).nfo"
                    nfo_path.write_text(result["nfo"]["xml"], encoding="utf-8")
                    self.manifest.record("create_file", None, nfo_path, extra={"kind": "main_nfo"})
                    poster_path = output_dir / "poster.jpg"
                    poster_path.write_bytes(b"\xff\xd8\xff" + b"poster")
                    self.manifest.record("create_file", None, poster_path, extra={"kind": "artwork"})
                    artwork_manifest = output_dir / "artwork-manifest.json"
                    artwork_manifest.write_text(json.dumps({"summary": {"poster": 1}}), encoding="utf-8")
                    self.manifest.record("create_file", None, artwork_manifest, extra={"kind": "artwork_manifest"})
                    return {
                        "status": "completed",
                        **result,
                        "output": {"media_dir": str(output_dir)},
                        "artwork": {"status": "downloaded", "total": 1, "counts": {"poster": 1}},
                    }

            scraper = BatchMediaScraper(
                config_path=str(root / "missing-config.yaml"),
                inplace_rename=True,
                enable_organize=True,
                media_type="movie",
                search_mode="tmdb_only",
                extra_images=True,
                max_workers=1,
                task_id=task_id,
            )
            scraper.organizer.manifest = OperationManifest(task_id, manifest_dir=str(manifest_dir))
            scraper.pipeline = FakePipeline(scraper.organizer.manifest)
            scraper.organizer.pipeline = scraper.pipeline
            events = []
            scraper._emit = lambda event_type, payload=None, item_id=None: events.append(
                {"type": event_type, "payload": payload or {}, "item_id": item_id}
            )

            success, reason = scraper._process_directory(source_dir, None, task_media_type="movie")
            target_dir = root / "Example Movie (2026)"

            self.assertTrue(success, reason)
            self.assertTrue((target_dir / "Example Movie (2026).mkv").exists())
            self.assertTrue((target_dir / "Example Movie (2026).nfo").exists())
            self.assertTrue((target_dir / "poster.jpg").exists())
            self.assertTrue((target_dir / "artwork-manifest.json").exists())
            self.assertEqual(Path(scraper.pipeline.calls[1]["output_dir"]), target_dir)
            self.assertTrue(any(event["type"] == "item.plan_ready" for event in events))
            self.assertTrue(any(event["type"] == "item.verification_started" for event in events))
            self.assertTrue(any(event["type"] == "item.verification_completed" for event in events))
            self.assertTrue(any(event["type"] == "item.completed" for event in events))

            manifest = json.loads((manifest_dir / f"{task_id}.json").read_text(encoding="utf-8"))
            destinations = {operation["destination"] for operation in manifest["operations"]}
            self.assertIn(str(target_dir / "Example Movie (2026).mkv"), destinations)
            self.assertIn(str(target_dir / "Example Movie (2026).nfo"), destinations)
            self.assertIn(str(target_dir / "poster.jpg"), destinations)

            rollback = rollback_manifest(task_id, manifest_dir=str(manifest_dir))

            self.assertEqual(rollback["status"], "completed")
            self.assertTrue(source_video.exists())
            self.assertFalse((target_dir / "Example Movie (2026).mkv").exists())
            self.assertFalse((target_dir / "Example Movie (2026).nfo").exists())
            self.assertFalse((target_dir / "poster.jpg").exists())


class ExecutionVerifierTest(unittest.TestCase):
    def test_required_nfo_must_exist_and_be_valid_xml(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            nfo_path = Path(temp_dir) / "movie.nfo"
            plan = {
                "actions": [{
                    "type": "create_file",
                    "destination": str(nfo_path),
                    "kind": "main_nfo",
                    "required": True,
                    "status": "ready",
                }]
            }
            verifier = ExecutionVerifier()

            missing = verifier.verify(plan)
            nfo_path.write_text("<movie>", encoding="utf-8")
            malformed = verifier.verify(plan)
            nfo_path.write_text("<movie><title>Example</title></movie>", encoding="utf-8")
            valid = verifier.verify(plan)

            self.assertEqual(missing["status"], "failed")
            self.assertEqual(malformed["status"], "failed")
            self.assertEqual(valid["status"], "passed")

    def test_move_requires_destination_and_source_removal(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            source = root / "source.mkv"
            destination = root / "target.mkv"
            source.write_text("video", encoding="utf-8")
            destination.write_text("video", encoding="utf-8")
            plan = {
                "actions": [{
                    "type": "move_file",
                    "source": str(source),
                    "destination": str(destination),
                    "required": True,
                    "status": "ready",
                }]
            }

            failed = ExecutionVerifier().verify(plan)
            source.unlink()
            passed = ExecutionVerifier().verify(plan)

            self.assertEqual(failed["failure_codes"], ["source_still_exists"])
            self.assertEqual(passed["status"], "passed")

    def test_incomplete_artwork_is_partial_but_downloaded_files_are_verified(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            (root / "poster.jpg").write_bytes(b"\xff\xd8\xffposter")
            (root / "artwork-manifest.json").write_text(json.dumps({"assets": [{"path": "poster.jpg"}]}), encoding="utf-8")
            report = ExecutionVerifier().verify(
                {"target_root": str(root), "actions": []},
                {
                    "status": "downloaded",
                    "total": 1,
                    "files": {"poster": ["poster.jpg"]},
                    "missing_core": ["fanart", "banner", "logo", "clearart"],
                },
            )

            self.assertEqual(report["status"], "partial")
            self.assertEqual(report["failed"], 0)
            self.assertIn("artwork_incomplete", report["warning_codes"])

    def test_metadata_diagnostics_are_not_silently_reported_as_success(self):
        warning = ExecutionVerifier().verify({
            "actions": [],
            "diagnostics": [{
                "level": "warning",
                "code": "provider_season_fetch_failed",
                "stage": "metadata_fetch",
                "season": 2,
                "message": "Failed to fetch TMDB season 2",
            }],
        })
        failed = ExecutionVerifier().verify({
            "actions": [],
            "diagnostics": [{
                "level": "error",
                "code": "episode_nfo_generation_failed",
                "stage": "nfo_generation",
                "season": 1,
                "episode": 3,
                "message": "Failed to generate NFO for S01E03",
            }],
        })

        self.assertEqual(warning["status"], "partial")
        self.assertEqual(warning["warning_codes"], ["provider_season_fetch_failed"])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["failure_codes"], ["episode_nfo_generation_failed"])


class MetadataDiagnosticTest(unittest.TestCase):
    def test_provider_season_fetch_failure_is_structured(self):
        class PartialTMDB:
            def get_tv_details(self, tmdb_id):
                return {"id": tmdb_id, "seasons": [{"season_number": 1}, {"season_number": 2}]}

            def get_credits(self, media_type, tmdb_id):
                return {}

            def get_keywords(self, media_type, tmdb_id):
                return {}

            def get_tv_season_details(self, tmdb_id, season):
                if season == 2:
                    raise TimeoutError("provider timeout")
                return {"season_number": season, "episodes": [{"season_number": season, "episode_number": 1}]}

        pipeline = object.__new__(MediaPipeline)
        pipeline.tmdb = PartialTMDB()
        pipeline._log = lambda *args, **kwargs: None

        result = pipeline._step_fetch(123, "tv")

        self.assertEqual(len(result["episodes"]), 1)
        self.assertEqual(result["issues"][0]["code"], "provider_season_fetch_failed")
        self.assertEqual(result["issues"][0]["season"], 2)

    def test_episode_nfo_generation_failure_is_structured(self):
        class DumpModel:
            def model_dump(self):
                return {}

        class FailingMapper:
            def map_to_tvshow_nfo(self, normalized):
                return DumpModel()

            def map_to_episode_nfo(self, normalized, episode, parent):
                raise ValueError("invalid episode payload")

            def map_to_season_nfo(self, season, normalized):
                return DumpModel()

        pipeline = object.__new__(MediaPipeline)
        pipeline.config = {"output": {"nfo_policy": {}}}
        pipeline.mapper = FailingMapper()
        pipeline._log = lambda *args, **kwargs: None

        with patch("src.pipeline.pipeline.NfoRenderer.render_tvshow_nfo", return_value="<tvshow />"), patch(
            "src.pipeline.pipeline.NfoRenderer.render_season_nfo",
            return_value="<season />",
        ):
            result = pipeline._step_generate_nfo(
                {"tmdb_id": 123, "media_type": "tv", "title": "Example"},
                "tv",
                {
                    "translated_episodes": [{"season_number": 1, "episode_number": 1, "name": "Pilot"}],
                    "present_episode_keys": [[1, 1]],
                    "seasons": [{"season_number": 1}],
                },
            )

        self.assertEqual(result["episode_nfos"], {})
        self.assertEqual(result["season_nfos"], {1: "<season />"})
        self.assertEqual(result["issues"][0]["code"], "episode_nfo_generation_failed")
        self.assertEqual(result["issues"][0]["episode"], 1)

    def test_error_diagnostic_blocks_plan_and_is_visible_in_review(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            show_path = Path(temp_dir) / "Example"
            show_path.mkdir()
            (show_path / "Example.S01E01.mkv").write_text("video", encoding="utf-8")
            plan = MediaOrganizer(enable_organize=False).build_plan(show_path, {
                "normalized": {"media_type": "tv", "title": "Example", "year": 2026},
                "source_data": {
                    "translated_episodes": [{"season_number": 1, "episode_number": 1, "name": "Pilot"}],
                },
                "nfo": {
                    "xml": "<tvshow />",
                    "issues": [{
                        "level": "error",
                        "code": "episode_nfo_generation_failed",
                        "stage": "nfo_generation",
                        "season": 1,
                        "episode": 1,
                        "message": "Failed to generate NFO for S01E01",
                    }],
                },
            })

            self.assertEqual(plan["nfo"]["diagnostic_count"], 1)
            self.assertEqual(plan["diagnostics"][0]["code"], "episode_nfo_generation_failed")
            self.assertEqual(plan["summary"]["blocked"], 1)
            self.assertEqual(plan["review"]["status"], "manual_review")
            self.assertTrue(MediaOrganizer().has_blockers(plan))


class RecoveryManifestTest(unittest.TestCase):
    def test_recovery_retries_directly_when_no_operations_exist(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            preview = preview_recovery_manifest("missing", manifest_dir=temp_dir)

            self.assertEqual(preview["status"], "ready")
            self.assertEqual(preview["strategy"], "retry")
            self.assertFalse(preview["rollback_required"])

    def test_recovery_requires_clean_rollback_before_retry(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            source = root / "source.mkv"
            destination = root / "library" / "movie.mkv"
            destination.parent.mkdir()
            source.write_text("video", encoding="utf-8")
            destination.write_text("video", encoding="utf-8")
            manifest = OperationManifest("recoverable", manifest_dir=temp_dir)
            manifest.record("move_file", source, destination)
            source.unlink()

            preview = preview_recovery_manifest("recoverable", manifest_dir=temp_dir)

            self.assertEqual(preview["status"], "ready")
            self.assertEqual(preview["strategy"], "rollback_then_retry")
            self.assertTrue(preview["rollback_required"])

    def test_recovery_blocks_when_recorded_output_changed(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            source = root / "source.mkv"
            destination = root / "library" / "movie.mkv"
            destination.parent.mkdir()
            source.write_text("video", encoding="utf-8")
            destination.write_text("video", encoding="utf-8")
            manifest = OperationManifest("modified", manifest_dir=temp_dir)
            manifest.record("move_file", source, destination)
            source.unlink()
            destination.write_text("changed after failure", encoding="utf-8")

            preview = preview_recovery_manifest("modified", manifest_dir=temp_dir)

            self.assertEqual(preview["status"], "manual_review")
            self.assertEqual(preview["strategy"], "manual_review")
            self.assertEqual(preview["operations"][0]["status"], "current_modified")

    def test_rollback_preview_keeps_created_directory_for_untracked_content(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            created_dir = root / "library"
            created_dir.mkdir()
            tracked = created_dir / "movie.nfo"
            tracked.write_text("<movie />", encoding="utf-8")
            untracked = created_dir / "user-note.txt"
            untracked.write_text("keep me", encoding="utf-8")
            manifest = OperationManifest("mixed-directory", manifest_dir=temp_dir)
            manifest.record("create_dir", None, created_dir)
            manifest.record("create_file", None, tracked)

            preview = preview_rollback_manifest("mixed-directory", manifest_dir=temp_dir)
            directory_step = next(item for item in preview["operations"] if item["action"] == "create_dir")

            self.assertEqual(preview["status"], "partial")
            self.assertEqual(directory_step["status"], "dir_not_empty")
            self.assertTrue(untracked.exists())

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

    def test_dry_run_builds_full_plan_instead_of_short_audit(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            show_path = Path(temp_dir) / "Example Show"
            show_path.mkdir()
            (show_path / "Example.Show.S01E01.mkv").write_text("video", encoding="utf-8")

            class FakePipeline:
                calls = []

                def run(self, input_data):
                    self.calls.append(input_data.copy())
                    return {
                        "status": "plan_ready",
                        "candidate": {"id": 1, "name": "Example Show", "media_type": "tv"},
                        "match": {"provider": "tmdb", "confidence": "high"},
                        "normalized": {"media_type": "tv", "title": "Example Show", "year": 2026},
                        "source_data": {
                            "translated_episodes": [
                                {"season_number": 1, "episode_number": 1, "name": "Pilot"},
                            ]
                        },
                        "nfo": {"episode_nfos": {(1, 1): "<episodedetails />"}},
                    }

            class FakeOrganizer:
                def build_plan(self, *args, **kwargs):
                    return {
                        "summary": {"blocked": 0, "present_episodes": 1},
                        "nfo": {"present_episodes": 1},
                    }

            events = []
            scraper = object.__new__(BatchMediaScraper)
            scraper.dry_run = True
            scraper.media_type = "tv"
            scraper.inplace_rename = False
            scraper.output_dir = None
            scraper.extra_images = False
            scraper.overwrite_images = False
            scraper.search_mode = "tmdb_only"
            scraper.enable_fallback = False
            scraper.fresh = False
            scraper.pipeline = FakePipeline()
            scraper.organizer = FakeOrganizer()
            scraper.stop_event = None
            scraper.task_id = "plan-task"
            scraper.operation_scope = "full"
            scraper._emit = lambda event_type, payload=None, item_id=None: events.append((event_type, payload or {}))

            success, _ = scraper._process_directory(show_path, 1, task_media_type="tv")

            self.assertTrue(success)
            self.assertEqual(len(scraper.pipeline.calls), 1)
            self.assertTrue(scraper.pipeline.calls[0]["plan_only"])
            self.assertFalse(scraper.pipeline.calls[0]["audit_only"])
            self.assertTrue(any(event_type == "item.plan_ready" for event_type, _ in events))


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

    def test_image_stream_cancellation_removes_partial_download(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            cancel_event = Event()

            class FakeResponse:
                headers = {"content-type": "image/png"}

                def raise_for_status(self):
                    return None

                def iter_content(self, chunk_size=8192):
                    yield b"\x89PNG\r\n\x1a\n" + (b"\0" * 64)
                    cancel_event.set()
                    yield b"more"

            class FakeSession:
                def get(self, *args, **kwargs):
                    return FakeResponse()

            downloader = ArtworkDownloader("tmdb", cancel_event=cancel_event)
            downloader.session = FakeSession()
            dest = Path(temp_dir) / "poster.png"

            with self.assertRaises(OperationCancelled):
                downloader.download_image(str(dest), "https://image.tmdb.org/poster.png", max_retries=1)

            self.assertFalse(dest.exists())
            self.assertFalse(Path(str(dest) + ".download").exists())

    def test_pipeline_cancelled_before_search_performs_no_work(self):
        cancel_event = Event()
        cancel_event.set()
        pipeline = object.__new__(MediaPipeline)
        pipeline.cancel_event = cancel_event
        pipeline._log = lambda *args, **kwargs: None
        pipeline._step_search = lambda input_data: self.fail("search must not run after cancellation")

        result = pipeline.run({"query": "Example", "media_type": "movie"})

        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["stage"], "search")

    def test_organizer_cancelled_before_file_operation_keeps_source_untouched(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            source = root / "source.mkv"
            destination = root / "dest.mkv"
            source.write_bytes(b"video")
            cancel_event = Event()
            cancel_event.set()
            organizer = MediaOrganizer(enable_organize=True, cancel_event=cancel_event)

            with self.assertRaises(OperationCancelled):
                organizer._move_or_copy(source, destination)

            self.assertTrue(source.exists())
            self.assertFalse(destination.exists())

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

    def test_pipeline_does_not_create_nfo_for_episode_without_local_video(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            media_dir = Path(temp_dir) / "Example"
            media_dir.mkdir()
            pipeline = object.__new__(MediaPipeline)
            pipeline.inplace = True
            pipeline.manifest = None

            result = pipeline._step_write_output(
                {"media_type": "tv", "title": "Example", "year": 2026},
                {
                    "xml": "<tvshow />",
                    "season_nfos": {1: "<season />"},
                    "episode_nfos": {
                        (1, 1): "<episodedetails><episode>1</episode></episodedetails>",
                        (1, 2): "<episodedetails><episode>2</episode></episodedetails>",
                    },
                },
                {
                    "translated_episodes": [
                        {"season_number": 1, "episode_number": 1, "name": "One"},
                        {"season_number": 1, "episode_number": 2, "name": "Two"},
                    ],
                    "present_episode_keys": [[1, 1]],
                },
                {"output_dir": str(media_dir)},
            )

            season_dir = Path(result["media_dir"]) / "Season 01"
            self.assertTrue((season_dir / "Example - S01E01 - One.nfo").exists())
            self.assertFalse((season_dir / "Example - S01E02 - Two.nfo").exists())
            self.assertEqual(len(list(season_dir.glob("*.nfo"))), 2)

    def test_pipeline_sanitizes_metadata_titles_before_writing_nfo(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            media_dir = Path(temp_dir) / "Example"
            media_dir.mkdir()
            pipeline = object.__new__(MediaPipeline)
            pipeline.inplace = True
            pipeline.manifest = None

            result = pipeline._step_write_output(
                {
                    "media_type": "movie",
                    "title": "../../Escaped/Movie",
                    "year": 2026,
                },
                {"xml": "<movie />"},
                {},
                {"output_dir": str(media_dir)},
            )

            written = list(Path(result["media_dir"]).glob("*.nfo"))
            self.assertEqual(len(written), 1)
            self.assertEqual(written[0].name, "EscapedMovie (2026).nfo")
            self.assertFalse((Path(temp_dir) / "Escaped").exists())

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
            self.assertTrue(any(asset["path"] == "poster.jpg" and asset["url"].endswith("/poster-extra.jpg") for asset in data["assets"]))
            poster_asset = next(asset for asset in data["assets"] if asset["path"] == "poster.jpg")
            self.assertEqual(poster_asset["iso_639_1"], "zh")
            self.assertEqual(poster_asset["selection_rank"], 1)
            self.assertEqual(data["selection_policy"]["preferred_languages"], ["zh", "en", "ja"])
            self.assertTrue(any(asset["path"] == "banner.jpg" and asset["derived_from"] == "fanart.jpg" for asset in data["assets"]))
            self.assertTrue(any(op["destination"] == str(manifest_path) and op["kind"] == "artwork_manifest" for op in manifest.operations))


if __name__ == "__main__":
    unittest.main()
