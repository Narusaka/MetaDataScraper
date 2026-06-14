import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.server import main as server_main
from src.server.settings_manager import SettingsManager
from src.server.task_events import TaskEventStore
from src.storage.match_memory import MatchMemoryStore


class FakeJobManager:
    def __init__(self):
        self.is_running = False
        self.started = None
        self.stopped = False
        self.active_task_id = None
        self.auto_release = True

    def reserve_start(self):
        if self.is_running:
            return False
        self.is_running = True
        return True

    def release_reservation(self):
        self.is_running = False

    async def start_batch_scan(self, **kwargs):
        self.started = kwargs
        self.active_task_id = kwargs.get("task_id")
        if self.auto_release:
            self.release_reservation()

    def stop_task(self, task_id=None):
        if task_id and self.active_task_id and task_id != self.active_task_id:
            return False
        self.stopped = True
        return True


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._payload


class ApiContractsTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.root = Path(self.temp_dir.name)
        self.media_dir = self.root / "media"
        self.media_dir.mkdir()
        self.store = TaskEventStore(storage_path=str(self.root / "task_events.json"))
        self.match_memory = MatchMemoryStore(str(self.root / "matches.db"))
        self.fake_jobs = FakeJobManager()
        self.settings_manager = SettingsManager(config_path=str(self.root / "config.yaml"))

        self.patches = [
            patch.object(server_main, "task_event_store", self.store),
            patch.object(server_main, "job_manager", self.fake_jobs),
            patch.object(server_main, "settings_manager", self.settings_manager),
            patch.object(server_main, "match_memory_store", self.match_memory),
        ]
        for item in self.patches:
            item.start()
        self.client = TestClient(server_main.app)

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp_dir.cleanup()

    def test_filesystem_endpoint_returns_precise_status_codes_and_normalized_paths(self):
        nested = self.media_dir / "Nested"
        nested.mkdir()
        file_path = self.media_dir / "movie.mkv"
        file_path.write_text("video", encoding="utf-8")

        ok = self.client.get("/api/filesystem", params={"path": str(self.media_dir)})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["current"], str(self.media_dir.resolve()))
        self.assertTrue(any(item["name"] == "Nested" and item["is_dir"] for item in ok.json()["items"]))

        missing = self.client.get("/api/filesystem", params={"path": str(self.root / "missing")})
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["detail"], "Path not found")

        file_response = self.client.get("/api/filesystem", params={"path": str(file_path)})
        self.assertEqual(file_response.status_code, 400)
        self.assertEqual(file_response.json()["detail"], "Path is not a directory")

    def test_browser_origin_boundary_applies_to_http_cors_and_websockets(self):
        local_origin = "http://127.0.0.1:5173"
        malicious_origin = "https://metadata-attacker.example"

        allowed = self.client.get(
            "/api/status",
            headers={"Origin": local_origin},
        )
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(
            allowed.headers["access-control-allow-origin"],
            local_origin,
        )

        rejected = self.client.post(
            "/api/tasks/plan",
            headers={
                "Origin": malicious_origin,
                "Content-Type": "application/json",
            },
            json={"input_dir": str(self.media_dir)},
        )
        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(
            rejected.json()["detail"]["code"],
            "UNTRUSTED_ORIGIN",
        )
        self.assertIsNone(self.fake_jobs.started)

        preflight = self.client.options(
            "/api/settings",
            headers={
                "Origin": local_origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        self.assertEqual(preflight.status_code, 200)
        self.assertEqual(
            preflight.headers["access-control-allow-origin"],
            local_origin,
        )
        self.assertNotEqual(
            preflight.headers.get("access-control-allow-origin"),
            "*",
        )

        with self.client.websocket_connect(
            "/ws/events",
            headers={"Origin": local_origin},
        ):
            pass
        with self.assertRaises(WebSocketDisconnect) as rejected_socket:
            with self.client.websocket_connect(
                "/ws/events",
                headers={"Origin": malicious_origin},
            ):
                pass
        self.assertEqual(rejected_socket.exception.code, 1008)

    def test_filesystem_check_expands_user_path_and_reports_directory_flag(self):
        with patch.dict(os.environ, {"HOME": str(self.root)}):
            exists = self.client.get("/api/fs/check", params={"path": "~/media"})
            missing = self.client.get("/api/fs/check", params={"path": "~/missing"})

        self.assertEqual(exists.status_code, 200)
        self.assertTrue(exists.json()["exists"])
        self.assertTrue(exists.json()["is_dir"])
        self.assertEqual(exists.json()["path"], str(self.media_dir.resolve()))
        self.assertEqual(missing.status_code, 200)
        self.assertFalse(missing.json()["exists"])
        self.assertFalse(missing.json()["is_dir"])

    def test_library_scan_returns_read_only_structured_inventory(self):
        show = self.media_dir / "Example Show (2026)"
        season = show / "Season 01"
        season.mkdir(parents=True)
        (show / "tvshow.nfo").write_text(
            "<tvshow><tmdbid>123</tmdbid></tvshow>",
            encoding="utf-8",
        )
        (season / "Example Show - S01E01.mkv").write_text("video", encoding="utf-8")
        (season / "Example Show - S01E01.zh.srt").write_text("subtitle", encoding="utf-8")

        response = self.client.post(
            "/api/library/scan",
            json={"path": str(self.media_dir), "mode": "auto", "use_local_nfo": True},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["mode"], "batch")
        self.assertEqual(payload["summary"]["items"], 1)
        self.assertEqual(payload["summary"]["videos"], 1)
        item = payload["items"][0]
        self.assertEqual(item["tmdb_id"], 123)
        self.assertEqual(item["media_type"], "tv")
        self.assertEqual(item["subtitle_count"], 1)
        self.assertEqual(item["status"], "ready")

    def test_library_scan_rejects_missing_and_file_paths(self):
        file_path = self.media_dir / "movie.mkv"
        file_path.write_text("video", encoding="utf-8")

        missing = self.client.post(
            "/api/library/scan",
            json={"path": str(self.root / "missing")},
        )
        file_response = self.client.post(
            "/api/library/scan",
            json={"path": str(file_path)},
        )

        self.assertEqual(missing.status_code, 404)
        self.assertEqual(file_response.status_code, 400)
        self.assertEqual(file_response.json()["detail"], "Path is not a directory")

    def test_start_task_rejects_missing_path_and_copy_without_output(self):
        missing = self.client.post("/api/tasks/start", json={"input_dir": str(self.root / "missing")})
        self.assertEqual(missing.status_code, 404)
        self.assertIn("Input path not found", missing.json()["detail"])

        no_output = self.client.post(
            "/api/tasks/start",
            json={"input_dir": str(self.media_dir), "copy_mode": True},
        )
        self.assertEqual(no_output.status_code, 400)
        self.assertEqual(no_output.json()["detail"], "Output path is required for copy mode")

    def test_start_task_rejects_invalid_copy_output_paths(self):
        output_file = self.root / "not-a-directory.txt"
        output_file.write_text("not a dir", encoding="utf-8")

        same_path = self.client.post(
            "/api/tasks/start",
            json={"input_dir": str(self.media_dir), "copy_mode": True, "output_dir": str(self.media_dir)},
        )
        file_path = self.client.post(
            "/api/tasks/start",
            json={"input_dir": str(self.media_dir), "copy_mode": True, "output_dir": str(output_file)},
        )
        missing_parent = self.client.post(
            "/api/tasks/start",
            json={"input_dir": str(self.media_dir), "copy_mode": True, "output_dir": str(self.root / "missing" / "library")},
        )

        self.assertEqual(same_path.status_code, 400)
        self.assertEqual(same_path.json()["detail"], "Output path must be different from input path")
        self.assertEqual(file_path.status_code, 400)
        self.assertEqual(file_path.json()["detail"], "Output path is not a directory")
        self.assertEqual(missing_parent.status_code, 400)
        self.assertEqual(missing_parent.json()["detail"], "Output parent directory does not exist")

    def test_start_task_reserves_worker_slot_before_background_task_runs(self):
        self.fake_jobs.auto_release = False

        first = self.client.post("/api/tasks/start", json={"input_dir": str(self.media_dir)})
        second = self.client.post("/api/tasks/start", json={"input_dir": str(self.media_dir)})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 400)
        self.assertEqual(second.json()["detail"], "Task already running")

    def test_start_task_creates_snapshot_and_normalizes_zero_tmdb_id(self):
        response = self.client.post(
            "/api/tasks/start",
            json={
                "input_dir": str(self.media_dir),
                "dry_run": True,
                "workers": 2,
                "tmdb_id": 0,
                "search_mode": "tavily_only",
                "media_type": "movie",
            },
        )

        self.assertEqual(response.status_code, 200)
        task_id = response.json()["task_id"]
        task = self.store.get_task(task_id)

        self.assertIsNotNone(task)
        self.assertEqual(task["config"]["tmdb_id"], None)
        self.assertEqual(task["config"]["search_mode"], "tavily_only")
        self.assertEqual(task["config"]["workers"], 2)
        self.assertEqual(task["config"]["settings_revision"], 0)
        self.assertEqual(len(task["config"]["settings_fingerprint"]), 64)
        self.assertNotIn("api_key", task["config"])
        self.assertEqual(self.fake_jobs.started["task_id"], task_id)
        self.assertEqual(self.fake_jobs.started["tmdb_id"], None)
        self.assertEqual(
            self.fake_jobs.started["runtime_config"]["matching"]["minimum_title_similarity"],
            0.55,
        )

    def test_start_task_snapshot_records_auditable_execution_config(self):
        response = self.client.post(
            "/api/tasks/start",
            json={
                "input_dir": str(self.media_dir),
                "dry_run": True,
                "inplace": False,
                "copy_mode": False,
                "workers": 3,
                "use_local_nfo": True,
                "extra_images": True,
                "fresh": True,
                "enable_fallback": False,
                "enable_organize": True,
                "overwrite_images": True,
                "rename_parent_dir": True,
                "conflict_strategy": "suffix",
                "search_mode": "tmdb_only",
            },
        )

        self.assertEqual(response.status_code, 200)
        task = self.store.get_task(response.json()["task_id"])
        self.assertEqual(task["config"]["strategy"], "audit")
        self.assertTrue(task["config"]["dry_run"])
        self.assertFalse(task["config"]["inplace"])
        self.assertFalse(task["config"]["copy_mode"])
        self.assertIsNone(task["config"]["output_dir"])
        self.assertTrue(task["config"]["use_local_nfo"])
        self.assertTrue(task["config"]["extra_images"])
        self.assertTrue(task["config"]["fresh"])
        self.assertFalse(task["config"]["enable_fallback"])
        self.assertTrue(task["config"]["enable_organize"])
        self.assertTrue(task["config"]["overwrite_images"])
        self.assertTrue(task["config"]["rename_parent_dir"])
        self.assertEqual(task["config"]["conflict_strategy"], "suffix")
        self.assertEqual(task["config"]["search_mode"], "tmdb_only")

    def test_plan_task_preserves_copy_and_organize_strategy_without_writing(self):
        output_dir = self.root / "library"
        output_dir.mkdir()

        copy_response = self.client.post(
            "/api/tasks/plan",
            json={
                "input_dir": str(self.media_dir),
                "dry_run": False,
                "copy_mode": True,
                "output_dir": str(output_dir),
                "enable_organize": True,
                "intended_strategy": "copy",
            },
        )

        self.assertEqual(copy_response.status_code, 200)
        self.assertEqual(copy_response.json()["status"], "planning")
        copy_task = self.store.get_task(copy_response.json()["task_id"])
        self.assertEqual(copy_task["config"]["strategy"], "copy")
        self.assertTrue(copy_task["config"]["dry_run"])
        self.assertTrue(copy_task["config"]["copy_mode"])
        self.assertEqual(copy_task["config"]["output_dir"], str(output_dir))
        self.assertTrue(self.fake_jobs.started["dry_run"])

        organize_response = self.client.post(
            "/api/tasks/plan",
            json={
                "input_dir": str(self.media_dir),
                "dry_run": False,
                "inplace": True,
                "enable_organize": True,
                "intended_strategy": "organize",
            },
        )

        self.assertEqual(organize_response.status_code, 200)
        organize_task = self.store.get_task(organize_response.json()["task_id"])
        self.assertEqual(organize_task["config"]["strategy"], "organize")
        self.assertTrue(organize_task["config"]["dry_run"])
        self.assertTrue(organize_task["config"]["inplace"])
        self.assertFalse(organize_task["config"]["copy_mode"])

    def test_public_start_rejects_direct_execution(self):
        response = self.client.post(
            "/api/tasks/start",
            json={
                "input_dir": str(self.media_dir),
                "dry_run": False,
                "inplace": True,
                "enable_organize": True,
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("Direct execution is disabled", response.json()["detail"])
        self.assertIsNone(self.fake_jobs.started)

    def test_plan_task_rejects_scope_and_strategy_mismatches(self):
        files_only_metadata = self.client.post(
            "/api/tasks/plan",
            json={
                "input_dir": str(self.media_dir),
                "operation_scope": "organize_only",
                "intended_strategy": "audit",
            },
        )
        nfo_organize = self.client.post(
            "/api/tasks/plan",
            json={
                "input_dir": str(self.media_dir),
                "operation_scope": "nfo_only",
                "intended_strategy": "organize",
            },
        )

        self.assertEqual(files_only_metadata.status_code, 400)
        self.assertEqual(nfo_organize.status_code, 400)
        self.assertIsNone(self.fake_jobs.started)

    def test_task_specific_cancel_validates_task_and_active_owner(self):
        task = self.store.create_task(str(self.media_dir), {})
        self.store.emit(task["id"], "task.started", {"input_dir": str(self.media_dir)})
        self.fake_jobs.active_task_id = task["id"]

        response = self.client.post(f"/api/tasks/{task['id']}/cancel")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "cancel_requested")
        self.assertTrue(self.fake_jobs.stopped)

        missing = self.client.post("/api/tasks/missing/cancel")
        self.assertEqual(missing.status_code, 404)

    def test_execution_queue_exposes_only_real_tasks_with_structured_progress(self):
        audit = self.store.create_task(str(self.media_dir), {"dry_run": True})
        execution = self.store.create_task(
            str(self.media_dir),
            {
                "dry_run": False,
                "source_plan_task_id": audit["id"],
                "source_plan_item_id": str(self.media_dir),
            },
        )
        self.store.emit(execution["id"], "task.started", {"input_dir": str(self.media_dir)})
        self.store.emit(execution["id"], "task.scan.completed", {"total": 1})
        self.store.emit(
            execution["id"],
            "item.started",
            {"name": "Media", "path": str(self.media_dir)},
            item_id=str(self.media_dir),
        )
        self.store.emit(
            execution["id"],
            "item.execution_phase",
            {"phase": "metadata", "name": "Media"},
            item_id=str(self.media_dir),
        )
        self.store.emit(
            execution["id"],
            "task.progress",
            {"processed": 0, "total": 1, "completed": 0, "failed": 0},
        )

        response = self.client.get("/api/executions")

        self.assertEqual(response.status_code, 200)
        executions = response.json()["executions"]
        self.assertEqual(len(executions), 1)
        self.assertEqual(executions[0]["id"], execution["id"])
        self.assertEqual(executions[0]["phase"], "metadata")
        self.assertEqual(executions[0]["progress"]["total"], 1)
        self.assertTrue(any(event["type"] == "item.execution_phase" for event in executions[0]["timeline"]))

    def test_interrupted_execution_is_recoverable_history_not_active_work(self):
        execution = self.store.create_task(
            str(self.media_dir),
            {"dry_run": False, "workers": 1},
        )
        self.store.emit(
            execution["id"],
            "task.started",
            {"input_dir": str(self.media_dir)},
        )
        self.store.reconcile_interrupted_tasks()

        executions = self.client.get("/api/executions").json()["executions"]
        history = self.client.get("/api/tasks/history").json()["tasks"]
        dashboard = self.client.get("/api/dashboard/summary").json()

        self.assertEqual(executions[0]["status"], "interrupted")
        self.assertEqual(executions[0]["phase"], "interrupted")
        self.assertEqual(history[0]["status"], "interrupted")
        self.assertEqual(dashboard["queues"]["executions"]["running"], 0)
        self.assertEqual(dashboard["queues"]["executions"]["issues"], 1)
        self.assertEqual(dashboard["queues"]["history"]["failed"], 1)

        recovery_preview = {
            "task_id": execution["id"],
            "status": "ready",
            "strategy": "retry",
            "rollback_required": False,
            "reason": "No operations recorded.",
            "operations": [],
        }
        with patch(
            "src.core.operation_manifest.preview_recovery_manifest",
            return_value=recovery_preview,
        ):
            recovered = self.client.post(f"/api/tasks/{execution['id']}/recover")

        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(recovered.json()["status"], "restarted")
        self.assertEqual(
            self.store.get_task(execution["id"])["recovery"]["status"],
            "restarted",
        )

    def test_dashboard_summary_aggregates_actionable_workflows(self):
        review_task = self.store.create_task(str(self.media_dir), {"dry_run": True})
        self.store.emit(
            review_task["id"],
            "item.failed",
            {
                "name": "Unknown",
                "path": str(self.media_dir),
                "error_code": "MATCH_REVIEW_REQUIRED",
                "match": {"confidence": "low", "review_required": True},
            },
            item_id=str(self.media_dir),
        )

        plan_task = self.store.create_task(str(self.media_dir / "Plan"), {"dry_run": True})
        plan_item = str(self.media_dir / "Plan")
        Path(plan_item).mkdir()
        self.store.emit(
            plan_task["id"],
            "item.plan_ready",
            {
                "plan": {
                    "source_path": plan_item,
                    "target_root": plan_item,
                    "summary": {"actions": 2, "blocked": 0, "conflicts": 0},
                    "actions": [],
                }
            },
            item_id=plan_item,
        )
        self.store.emit(
            plan_task["id"],
            "item.audit_completed",
            {"name": "Plan", "path": plan_item},
            item_id=plan_item,
        )

        execution = self.store.create_task(str(self.media_dir / "Run"), {"dry_run": False})
        self.store.emit(execution["id"], "task.started", {"input_dir": str(self.media_dir / "Run")})
        self.store.emit(execution["id"], "task.failed", {"error": "verification failed"})

        response = self.client.get("/api/dashboard/summary")

        self.assertEqual(response.status_code, 200)
        summary = response.json()
        self.assertEqual(summary["queues"]["match_reviews"], 1)
        self.assertEqual(summary["queues"]["plan_reviews"]["ready"], 1)
        self.assertEqual(summary["queues"]["executions"]["issues"], 1)
        self.assertEqual(summary["queues"]["history"]["failed"], 1)
        self.assertEqual(summary["recent"][0]["id"], execution["id"])
        self.assertIn("tmdb", summary["services"])

    def test_start_task_validates_request_shape_before_execution(self):
        bad_workers = self.client.post(
            "/api/tasks/start",
            json={"input_dir": str(self.media_dir), "workers": 99},
        )
        self.assertEqual(bad_workers.status_code, 422)

        bad_search = self.client.post(
            "/api/tasks/start",
            json={"input_dir": str(self.media_dir), "search_mode": "google"},
        )
        self.assertEqual(bad_search.status_code, 422)

    def test_task_plan_endpoint_returns_full_artifact_or_404(self):
        task = self.store.create_task(str(self.media_dir), {"dry_run": True})
        task_id = task["id"]
        item_id = str(self.media_dir / "Example")
        self.store.emit(
            task_id,
            "item.plan_ready",
            {
                "plan": {
                    "summary": {"actions": 2, "metadata_writes": 1},
                    "actions": [
                        {"type": "create_file", "destination": str(self.media_dir / "movie.nfo")},
                        {"type": "download_image", "destination": str(self.media_dir / "poster.jpg")},
                    ],
                }
            },
            item_id=item_id,
        )

        response = self.client.get(f"/api/tasks/{task_id}/plan", params={"item_id": item_id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["plan"]["summary"]["actions"], 2)
        self.assertEqual(len(response.json()["plan"]["actions"]), 2)

        missing = self.client.get(f"/api/tasks/{task_id}/plan", params={"item_id": "missing"})
        self.assertEqual(missing.status_code, 404)

    def test_plan_review_queue_returns_only_unconfirmed_locked_audits(self):
        ready = self.store.create_task(str(self.media_dir / "ready"), {"dry_run": True})
        ready_item = str(self.media_dir / "ready" / "Movie")
        Path(ready_item).mkdir(parents=True)
        self.store.emit(
            ready["id"],
            "item.plan_ready",
            {"plan": {
                "source_path": ready_item,
                "target_root": ready_item,
                "summary": {"actions": 2, "conflicts": 0, "blocked": 0},
            }},
            item_id=ready_item,
        )
        self.store.emit(
            ready["id"],
            "item.audit_completed",
            {"name": "Movie", "path": ready_item},
            item_id=ready_item,
        )

        blocked = self.store.create_task(str(self.media_dir / "blocked"), {"dry_run": True})
        blocked_item = str(self.media_dir / "blocked" / "Show")
        self.store.emit(
            blocked["id"],
            "item.plan_ready",
            {"plan": {
                "summary": {"actions": 1, "conflicts": 0, "blocked": 1},
                "diagnostics": [{
                    "code": "episode_nfo_generation_failed",
                    "level": "error",
                    "message": "Could not generate episode NFO.",
                    "season": 1,
                    "episode": 3,
                }],
            }},
            item_id=blocked_item,
        )
        self.store.emit(
            blocked["id"],
            "item.audit_completed",
            {"name": "Show", "path": blocked_item},
            item_id=blocked_item,
        )

        executed = self.store.create_task(str(self.media_dir / "executed"), {"dry_run": True})
        executed_item = str(self.media_dir / "executed" / "Done")
        self.store.emit(
            executed["id"],
            "item.plan_ready",
            {"plan": {"summary": {"actions": 1}}},
            item_id=executed_item,
        )
        self.store.emit(
            executed["id"],
            "item.audit_completed",
            {"name": "Done", "path": executed_item},
            item_id=executed_item,
        )
        self.store.emit(
            executed["id"],
            "item.execution_started",
            {"execution_task_id": "execution-task"},
            item_id=executed_item,
        )

        older_ready = self.store.create_task(str(self.media_dir / "older"), {"dry_run": True})
        self.store.emit(
            older_ready["id"],
            "item.plan_ready",
            {"plan": {"summary": {"actions": 99}}},
            item_id=ready_item,
        )
        self.store.emit(
            older_ready["id"],
            "item.audit_completed",
            {"name": "Superseded Movie", "path": ready_item},
            item_id=ready_item,
        )
        self.store._tasks[older_ready["id"]]["updated_at"] = "2000-01-01T00:00:00+00:00"

        response = self.client.get("/api/plans/review")

        self.assertEqual(response.status_code, 200)
        plans = response.json()["plans"]
        self.assertEqual(len(plans), 2)
        self.assertEqual(
            {entry["review_status"] for entry in plans},
            {"ready", "blocked"},
        )
        self.assertTrue(all(entry["item"]["plan_digest"] for entry in plans))
        ready_plan = next(entry for entry in plans if entry["review_status"] == "ready")
        self.assertEqual(ready_plan["item"]["plan"]["preflight"]["status"], "ready")
        self.assertNotIn(executed["id"], {entry["task_id"] for entry in plans})
        self.assertNotIn(older_ready["id"], {entry["task_id"] for entry in plans})
        blocked_plan = next(entry for entry in plans if entry["review_status"] == "blocked")
        self.assertEqual(
            blocked_plan["item"]["plan"]["diagnostics"][0]["code"],
            "episode_nfo_generation_failed",
        )

    def test_task_manifest_endpoint_returns_auditable_operations_or_404(self):
        with patch(
            "src.core.operation_manifest.get_manifest",
            return_value={
                "task_id": "task-1",
                "operations": [
                    {"action": "create_file", "destination": str(self.media_dir / "movie.nfo")},
                    {"action": "move_file", "source": str(self.media_dir / "raw.mkv"), "destination": str(self.media_dir / "movie.mkv")},
                ],
            },
        ):
            response = self.client.get("/api/tasks/task-1/manifest")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["operations"]), 2)
        self.assertEqual(response.json()["operations"][0]["action"], "create_file")

        with patch("src.core.operation_manifest.get_manifest", return_value=None):
            missing = self.client.get("/api/tasks/missing/manifest")

        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["detail"], "Manifest not found")

    def test_task_list_compact_query_returns_lightweight_snapshots(self):
        task = self.store.create_task(str(self.media_dir), {"dry_run": True})
        plan = {
            "target_root": str(self.root / "library" / "Movie"),
            "summary": {"actions": 15, "risks": 12},
            "actions": [{"type": "create_file", "destination": str(self.root / f"{index}.nfo")} for index in range(15)],
            "risks": [{"level": "warning", "message": f"risk-{index}"} for index in range(12)],
        }
        self.store.emit(task["id"], "item.plan_ready", {"plan": plan}, item_id=str(self.media_dir))

        compact = self.client.get("/api/tasks", params={"compact": "true"})
        detail = self.client.get(f"/api/tasks/{task['id']}")

        self.assertEqual(compact.status_code, 200)
        self.assertEqual(detail.status_code, 200)
        compact_item = compact.json()["tasks"][0]["items"][str(self.media_dir)]
        detail_item = detail.json()["items"][str(self.media_dir)]
        self.assertTrue(compact.json()["tasks"][0]["compact"])
        self.assertNotIn("actions", compact_item["plan"])
        self.assertEqual(compact_item["plan"]["summary"]["actions"], 15)
        self.assertEqual(len(detail_item["plan"]["actions"]), 5)

    def _create_audited_task(self, source: Path):
        runtime_context = self.settings_manager.get_runtime_context()
        task = self.store.create_task(
            str(source),
            {
                "dry_run": True,
                "workers": 2,
                "search_mode": "tmdb_only",
                "enable_fallback": True,
                "enable_organize": False,
                "operation_scope": "full",
                "settings_revision": runtime_context["revision"],
                "settings_fingerprint": runtime_context["fingerprint"],
            },
        )
        item_id = str(source)
        plan = {
            "media_type": "movie",
            "source_path": str(source),
            "target_root": str(source),
            "mode": "metadata_only",
            "operation_scope": "full",
            "conflict_strategy": "error",
            "summary": {"actions": 1, "ready": 1, "blocked": 0, "conflicts": 0},
            "actions": [
                {
                    "type": "create_file",
                    "source": None,
                    "destination": str(source / "Movie (2026).nfo"),
                    "kind": "main_nfo",
                    "status": "ready",
                }
            ],
        }
        self.store.emit(
            task["id"],
            "candidate.selected",
            {"title": "Movie", "tmdb_id": 123, "media_type": "movie"},
            item_id=item_id,
        )
        self.store.emit(task["id"], "item.plan_ready", {"plan": plan}, item_id=item_id)
        self.store.emit(
            task["id"],
            "item.audit_completed",
            {"name": "Movie", "path": item_id, "result": "audit_completed"},
            item_id=item_id,
        )
        return task, item_id, self.store.read_plan_artifact(task["id"], item_id)

    def test_confirmed_plan_execution_locks_digest_and_match(self):
        video = self.media_dir / "movie.mkv"
        video.write_text("video", encoding="utf-8")
        task, item_id, artifact = self._create_audited_task(self.media_dir)

        stale = self.client.post(
            f"/api/tasks/{task['id']}/execute",
            json={"item_id": item_id, "plan_digest": "0" * 64},
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["detail"]["message"], "Plan confirmation is stale")

        response = self.client.post(
            f"/api/tasks/{task['id']}/execute",
            json={"item_id": item_id, "plan_digest": artifact["plan_digest"]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source_plan_task_id"], task["id"])
        self.assertEqual(self.fake_jobs.started["expected_plan_digest"], artifact["plan_digest"])
        self.assertEqual(self.fake_jobs.started["tmdb_id"], 123)
        execution_task = self.store.get_task(response.json()["task_id"])
        self.assertEqual(execution_task["config"]["source_plan_task_id"], task["id"])
        self.assertEqual(
            execution_task["config"]["settings_fingerprint"],
            task["config"]["settings_fingerprint"],
        )

    def test_confirmed_plan_execution_rejects_settings_drift(self):
        video = self.media_dir / "movie.mkv"
        video.write_text("video", encoding="utf-8")
        task, item_id, artifact = self._create_audited_task(self.media_dir)
        self.settings_manager.save_settings({
            "matching": {"minimum_title_similarity": 0.66},
        })

        queue = self.client.get("/api/plans/review")
        response = self.client.post(
            f"/api/tasks/{task['id']}/execute",
            json={"item_id": item_id, "plan_digest": artifact["plan_digest"]},
        )

        self.assertEqual(queue.status_code, 200)
        queued = next(entry for entry in queue.json()["plans"] if entry["task_id"] == task["id"])
        self.assertEqual(queued["review_status"], "drifted")
        self.assertEqual(queued["settings_drift"]["expected_revision"], 0)
        self.assertEqual(queued["settings_drift"]["current_revision"], 1)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "SETTINGS_DRIFT")
        item = self.store.get_task(task["id"])["items"][item_id]
        self.assertEqual(item["plan_confirmation"]["status"], "settings_drifted")

    def test_plan_api_rejects_tampered_artifact_envelope(self):
        video = self.media_dir / "movie.mkv"
        video.write_text("video", encoding="utf-8")
        task, item_id, artifact = self._create_audited_task(self.media_dir)
        item = self.store.get_task(task["id"])["items"][item_id]
        plan_path = Path(item["plan_path"])
        artifact["baseline"][0]["exists"] = not artifact["baseline"][0]["exists"]
        plan_path.write_text(json.dumps(artifact), encoding="utf-8")

        detail = self.client.get(
            f"/api/tasks/{task['id']}/plan",
            params={"item_id": item_id},
        )
        execute = self.client.post(
            f"/api/tasks/{task['id']}/execute",
            json={"item_id": item_id, "plan_digest": artifact["plan_digest"]},
        )
        queue = self.client.get("/api/plans/review")

        self.assertEqual(detail.status_code, 409)
        self.assertEqual(detail.json()["detail"]["code"], "PLAN_ARTIFACT_INVALID")
        self.assertEqual(execute.status_code, 409)
        self.assertEqual(execute.json()["detail"]["code"], "PLAN_ARTIFACT_INVALID")
        self.assertEqual(queue.status_code, 200)
        queued = next(entry for entry in queue.json()["plans"] if entry["task_id"] == task["id"])
        self.assertEqual(queued["review_status"], "blocked")
        self.assertEqual(queued["artifact_integrity"]["status"], "invalid")

    def test_confirmed_plan_execution_rejects_filesystem_drift(self):
        video = self.media_dir / "movie.mkv"
        video.write_text("video", encoding="utf-8")
        task, item_id, artifact = self._create_audited_task(self.media_dir)
        video.write_text("changed after audit", encoding="utf-8")

        response = self.client.post(
            f"/api/tasks/{task['id']}/execute",
            json={"item_id": item_id, "plan_digest": artifact["plan_digest"]},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "PLAN_DRIFT")
        item = self.store.get_task(task["id"])["items"][item_id]
        self.assertEqual(item["plan_confirmation"]["status"], "drifted")

    def test_confirmed_plan_execution_rejects_failed_resource_preflight(self):
        video = self.media_dir / "movie.mkv"
        video.write_text("video", encoding="utf-8")
        task, item_id, artifact = self._create_audited_task(self.media_dir)
        blocked_preflight = {
            "status": "blocked",
            "blocked": 1,
            "warnings": 0,
            "required_bytes": 1024,
            "free_bytes": 0,
            "checks": [{
                "code": "insufficient_disk_space",
                "status": "blocked",
                "message": "Not enough space.",
            }],
        }

        with patch(
            "src.core.execution_preflight.assess_execution_preflight",
            return_value=blocked_preflight,
        ):
            response = self.client.post(
                f"/api/tasks/{task['id']}/execute",
                json={"item_id": item_id, "plan_digest": artifact["plan_digest"]},
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "EXECUTION_PREFLIGHT_FAILED")
        item = self.store.get_task(task["id"])["items"][item_id]
        self.assertEqual(item["plan_confirmation"]["status"], "preflight_failed")

    def test_clear_completed_history_rejects_running_jobs_and_removes_finished_tasks(self):
        completed = self.store.create_task(str(self.media_dir / "done"), {"dry_run": False})
        running = self.store.create_task(str(self.media_dir / "running"), {"dry_run": False})
        self.store.emit(completed["id"], "task.completed", {"summary": {"total": 1, "completed": 1, "failed": 0}})
        self.store.emit(running["id"], "task.started", {"input_dir": str(self.media_dir / "running")})

        self.fake_jobs.is_running = True
        blocked = self.client.delete("/api/tasks/history/completed")
        self.assertEqual(blocked.status_code, 409)

        self.fake_jobs.is_running = False
        response = self.client.delete("/api/tasks/history/completed")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["removed"], 1)
        self.assertIsNone(self.store.get_task(completed["id"]))
        self.assertIsNotNone(self.store.get_task(running["id"]))

    def test_history_clear_retains_actionable_match_plan_rollback_and_recovery_evidence(self):
        removable = self.store.create_task(
            str(self.media_dir / "removable"),
            {"dry_run": False},
        )
        self.store.emit(
            removable["id"],
            "task.completed",
            {"summary": {"total": 1, "completed": 1}},
        )

        match_task = self.store.create_task(
            str(self.media_dir / "match"),
            {"dry_run": True},
        )
        self.store.emit(
            match_task["id"],
            "item.failed",
            {
                "name": "Unknown",
                "path": str(self.media_dir / "match"),
                "error_code": "MATCH_REVIEW_REQUIRED",
                "match": {"review_required": True, "confidence": "low"},
            },
            item_id=str(self.media_dir / "match"),
        )
        self.store.emit(match_task["id"], "task.failed", {"error": "review"})

        plan_path = self.media_dir / "plan"
        plan_path.mkdir()
        plan_task = self.store.create_task(str(plan_path), {"dry_run": True})
        self.store.emit(
            plan_task["id"],
            "item.plan_ready",
            {
                "plan": {
                    "source_path": str(plan_path),
                    "target_root": str(plan_path),
                    "summary": {"actions": 1, "blocked": 0, "conflicts": 0},
                    "actions": [],
                },
            },
            item_id=str(plan_path),
        )
        self.store.emit(
            plan_task["id"],
            "item.audit_completed",
            {"name": "Plan", "path": str(plan_path)},
            item_id=str(plan_path),
        )
        self.store.emit(
            plan_task["id"],
            "task.completed",
            {"summary": {"total": 1, "completed": 1}},
        )

        rollback_task = self.store.create_task(
            str(self.media_dir / "rollback"),
            {"dry_run": False},
        )
        self.store.emit(
            rollback_task["id"],
            "task.completed",
            {"summary": {"total": 1, "completed": 1}},
        )

        interrupted = self.store.create_task(
            str(self.media_dir / "interrupted"),
            {"dry_run": False},
        )
        self.store.emit(
            interrupted["id"],
            "task.interrupted",
            {"error": "restart", "recoverable": True},
        )

        reversible_manifest = {
            "task_id": rollback_task["id"],
            "operations": [{
                "action": "create_file",
                "destination": str(self.media_dir / "rollback" / "movie.nfo"),
                "status": "done",
            }],
        }

        def manifest_for(task_id):
            return reversible_manifest if task_id == rollback_task["id"] else None

        with patch("src.core.operation_manifest.get_manifest", side_effect=manifest_for):
            preview_response = self.client.get("/api/tasks/history/cleanup-preview")
            response = self.client.delete("/api/tasks/history/completed")

        self.assertEqual(preview_response.status_code, 200)
        preview = preview_response.json()
        self.assertEqual(preview["eligible_count"], 1)
        self.assertEqual(preview["task_ids"], [removable["id"]])
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["task_ids"], [removable["id"]])
        retained = {
            item["task_id"]: set(item["reasons"])
            for item in result["retained"]
        }
        self.assertIn("match_review", retained[match_task["id"]])
        self.assertIn("plan_review", retained[plan_task["id"]])
        self.assertIn("rollback_available", retained[rollback_task["id"]])
        self.assertIn("recovery_available", retained[interrupted["id"]])
        self.assertIsNone(self.store.get_task(removable["id"]))
        self.assertIsNotNone(self.store.get_task(match_task["id"]))
        self.assertIsNotNone(self.store.get_task(plan_task["id"]))
        self.assertIsNotNone(self.store.get_task(rollback_task["id"]))
        self.assertIsNotNone(self.store.get_task(interrupted["id"]))

    def test_rollback_endpoint_reports_missing_manifest_and_emits_result(self):
        task = self.store.create_task(str(self.media_dir), {"dry_run": False})
        task_id = task["id"]
        self.store.emit(task_id, "task.completed", {"summary": {"total": 1, "completed": 1, "failed": 0}})

        with patch("src.core.operation_manifest.rollback_manifest", return_value={"status": "completed", "operations": []}):
            response = self.client.post(f"/api/tasks/{task_id}/rollback")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "completed")
        stored_task = self.store.get_task(task_id)
        self.assertEqual(stored_task["status"], "completed")
        self.assertEqual(stored_task["rollback"]["status"], "completed")
        self.assertEqual(
            [event["type"] for event in stored_task["events"][-2:]],
            ["task.rollback_started", "task.rollback_completed"],
        )

        with patch("src.core.operation_manifest.rollback_manifest", return_value={"status": "not_found"}):
            missing = self.client.post("/api/tasks/no-manifest/rollback")

        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["detail"], "Task not found")

    def test_rollback_endpoint_preserves_partial_and_failed_outcomes(self):
        for result, expected_event in (
            (
                {"status": "partial", "operations": [{"status": "current_modified"}]},
                "task.rollback_partial",
            ),
            (
                {"status": "failed", "error": "backup unreadable", "operations": []},
                "task.rollback_failed",
            ),
        ):
            task = self.store.create_task(str(self.media_dir / result["status"]), {"dry_run": False})
            task_id = task["id"]
            self.store.emit(task_id, "task.completed", {"summary": {"total": 1, "completed": 1, "failed": 0}})

            with patch("src.core.operation_manifest.rollback_manifest", return_value=result):
                response = self.client.post(f"/api/tasks/{task_id}/rollback")

            self.assertEqual(response.status_code, 200)
            stored_task = self.store.get_task(task_id)
            self.assertEqual(stored_task["status"], "completed")
            self.assertEqual(stored_task["rollback"]["status"], result["status"])
            self.assertEqual(
                [event["type"] for event in stored_task["events"][-2:]],
                ["task.rollback_started", expected_event],
            )

    def test_rollback_preview_endpoint_reports_plan_without_mutating_task(self):
        task = self.store.create_task(str(self.media_dir), {"dry_run": False})
        task_id = task["id"]
        self.store.emit(task_id, "task.completed", {"summary": {"total": 1, "completed": 1, "failed": 0}})

        with patch(
            "src.core.operation_manifest.preview_rollback_manifest",
            return_value={"status": "preview", "preview": True, "operations": [{"status": "would_removed_created_file"}]},
        ):
            response = self.client.get(f"/api/tasks/{task_id}/rollback/preview")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["preview"])
        self.assertIsNone(self.store.get_task(task_id).get("rollback"))

        with patch("src.core.operation_manifest.preview_rollback_manifest", return_value={"status": "not_found"}):
            missing = self.client.get(f"/api/tasks/{task_id}/rollback/preview")

        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["detail"], "Manifest not found")

    def test_rollback_endpoint_rejects_running_task(self):
        task = self.store.create_task(str(self.media_dir), {"dry_run": False})
        task_id = task["id"]
        self.store.emit(task_id, "task.started", {"input_dir": str(self.media_dir)})

        response = self.client.post(f"/api/tasks/{task_id}/rollback")
        preview = self.client.get(f"/api/tasks/{task_id}/rollback/preview")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "Task is still running")
        self.assertEqual(preview.status_code, 409)
        self.assertEqual(preview.json()["detail"], "Task is still running")

    def test_rollback_endpoint_reports_missing_manifest_for_finished_task(self):
        task = self.store.create_task(str(self.media_dir), {"dry_run": False})
        task_id = task["id"]
        self.store.emit(task_id, "task.completed", {"summary": {"total": 1, "completed": 1, "failed": 0}})

        with patch("src.core.operation_manifest.rollback_manifest", return_value={"status": "not_found"}):
            response = self.client.post(f"/api/tasks/{task_id}/rollback")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Manifest not found")
        stored_task = self.store.get_task(task_id)
        self.assertEqual(stored_task["rollback"]["status"], "failed")
        self.assertEqual(stored_task["rollback"]["reason"], "not_found")
        self.assertEqual(stored_task["events"][-1]["type"], "task.rollback_failed")

    def test_history_endpoint_uses_manifest_as_authoritative_rollback_evidence(self):
        completed = self.store.create_task(str(self.media_dir / "completed"), {"enable_organize": False})
        rolled_back = self.store.create_task(str(self.media_dir / "rolled"), {"enable_organize": True})
        running = self.store.create_task(str(self.media_dir / "running"), {"enable_organize": True})

        self.store.emit(completed["id"], "task.completed", {"summary": {"total": 2, "completed": 2, "failed": 0}})
        self.store.emit(rolled_back["id"], "task.completed", {"summary": {"total": 1, "completed": 1, "failed": 0}})
        self.store.emit(rolled_back["id"], "task.rollback_completed", {"status": "completed", "operations": []})
        self.store.emit(running["id"], "task.started", {"input_dir": str(self.media_dir / "running")})

        manifests = {
            completed["id"]: {
                "operations": [
                    {"action": "move_file", "source": "/source", "destination": "/target"},
                    {"action": "download_image", "destination": "/poster.jpg"},
                ]
            },
            rolled_back["id"]: {"operations": [{"action": "create_file", "destination": "/movie.nfo"}]},
        }
        with patch("src.core.operation_manifest.get_manifest", side_effect=lambda task_id: manifests.get(task_id)):
            response = self.client.get("/api/tasks/history")

        self.assertEqual(response.status_code, 200)
        history = {task["id"]: task for task in response.json()["tasks"]}
        self.assertEqual(set(history), {completed["id"], rolled_back["id"]})
        self.assertTrue(history[completed["id"]]["rollback_available"])
        self.assertEqual(history[completed["id"]]["manifest_summary"]["operation_count"], 2)
        self.assertEqual(history[completed["id"]]["manifest_summary"]["reversible_count"], 1)
        self.assertTrue(history[rolled_back["id"]]["rolled_back"])
        self.assertFalse(history[rolled_back["id"]]["rollback_available"])

    def test_history_endpoint_isolates_corrupt_manifest(self):
        task = self.store.create_task(str(self.media_dir), {"enable_organize": True})
        self.store.emit(task["id"], "task.completed", {"summary": {"total": 1, "completed": 1, "failed": 0}})

        with patch("src.core.operation_manifest.get_manifest", side_effect=ValueError("invalid manifest json")):
            response = self.client.get("/api/tasks/history")

        self.assertEqual(response.status_code, 200)
        history_task = response.json()["tasks"][0]
        self.assertFalse(history_task["manifest_summary"]["exists"])
        self.assertEqual(history_task["manifest_summary"]["error"], "invalid manifest json")
        self.assertFalse(history_task["rollback_available"])

    def test_match_review_endpoint_returns_only_items_requiring_confirmation(self):
        review_task = self.store.create_task(str(self.media_dir / "review"), {"dry_run": True, "search_mode": "smart"})
        accepted_task = self.store.create_task(str(self.media_dir / "accepted"), {"dry_run": True, "search_mode": "tmdb_only"})
        self.store.emit(
            review_task["id"],
            "item.failed",
            {
                "name": "Needs Review",
                "path": str(self.media_dir / "review"),
                "error": "Match requires confirmation before execution",
                "error_code": "MATCH_REVIEW_REQUIRED",
                "candidate": {"id": 42, "name": "Candidate", "media_type": "movie"},
                "match": {
                    "provider": "tmdb",
                    "confidence": "low",
                    "review_required": True,
                    "score": 0.31,
                    "candidates": [{"id": 42, "title": "Candidate", "score": 0.31}],
                },
            },
            item_id=str(self.media_dir / "review"),
        )
        self.store.emit(
            accepted_task["id"],
            "candidate.selected",
            {
                "title": "Accepted",
                "tmdb_id": 99,
                "media_type": "movie",
                "match": {"provider": "tmdb", "confidence": "high", "score": 0.95},
            },
            item_id=str(self.media_dir / "accepted"),
        )

        response = self.client.get("/api/matches/review")

        self.assertEqual(response.status_code, 200)
        reviews = response.json()["reviews"]
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0]["task_id"], review_task["id"])
        self.assertEqual(reviews[0]["item"]["candidate"]["tmdb_id"], 42)
        self.assertEqual(reviews[0]["item"]["candidate"]["title"], "Candidate")
        self.assertEqual(reviews[0]["item"]["error_code"], "MATCH_REVIEW_REQUIRED")

        resolved = self.client.post(
            f"/api/matches/review/{review_task['id']}/resolve",
            json={
                "item_id": str(self.media_dir / "review"),
                "action": "audit",
                "tmdb_id": 42,
                "media_type": "movie",
            },
        )
        self.assertEqual(resolved.status_code, 200)
        stored_review = self.store.get_task(review_task["id"])["items"][str(self.media_dir / "review")]["review"]
        self.assertEqual(stored_review["status"], "resolved")
        self.assertEqual(stored_review["action"], "audit")
        self.assertEqual(
            self.match_memory.lookup("Needs Review", media_type="movie")["tmdb_id"],
            42,
        )
        self.assertEqual(self.client.get("/api/matches/review").json()["reviews"], [])

    def test_match_review_resolution_validates_item_and_resolution(self):
        task = self.store.create_task(str(self.media_dir), {"dry_run": True})
        item_id = str(self.media_dir / "Unknown")
        self.store.emit(
            task["id"],
            "item.failed",
            {
                "path": item_id,
                "error_code": "MATCH_REVIEW_REQUIRED",
                "match": {"confidence": "low", "review_required": True},
            },
            item_id=item_id,
        )

        missing_item = self.client.post(
            f"/api/matches/review/{task['id']}/resolve",
            json={"item_id": "missing", "action": "ignored"},
        )
        incomplete = self.client.post(
            f"/api/matches/review/{task['id']}/resolve",
            json={"item_id": item_id, "action": "execute"},
        )
        ignored = self.client.post(
            f"/api/matches/review/{task['id']}/resolve",
            json={"item_id": item_id, "action": "ignored"},
        )

        self.assertEqual(missing_item.status_code, 404)
        self.assertEqual(incomplete.status_code, 422)
        self.assertEqual(ignored.status_code, 200)
        self.assertEqual(
            self.store.get_task(task["id"])["items"][item_id]["review"]["action"],
            "ignored",
        )
        self.assertEqual(self.match_memory.list_matches(), [])

    def test_match_memory_endpoint_lists_and_deletes_confirmed_mapping(self):
        saved = self.match_memory.remember("Example", 123, "movie", year=2026)

        listed = self.client.get("/api/matches/memory")
        deleted = self.client.delete(f"/api/matches/memory/{saved['id']}")
        missing = self.client.delete(f"/api/matches/memory/{saved['id']}")

        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["matches"][0]["tmdb_id"], 123)
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(missing.status_code, 404)

    def test_rejected_match_resolution_persists_rule_and_endpoint_can_remove_it(self):
        task = self.store.create_task(str(self.media_dir), {"dry_run": True})
        item_id = str(self.media_dir / "Front Innocent")
        self.store.emit(
            task["id"],
            "item.failed",
            {
                "path": item_id,
                "query": "Front Innocent",
                "error_code": "MATCH_REVIEW_REQUIRED",
                "match": {
                    "confidence": "low",
                    "review_required": True,
                    "candidates": [{"id": 99, "title": "Wrong Candidate", "media_type": "movie"}],
                },
            },
            item_id=item_id,
        )

        resolved = self.client.post(
            f"/api/matches/review/{task['id']}/resolve",
            json={
                "item_id": item_id,
                "action": "rejected",
                "tmdb_id": 99,
                "media_type": "movie",
            },
        )
        listed = self.client.get("/api/matches/rejections")
        rejection = listed.json()["rejections"][0]
        deleted = self.client.delete(f"/api/matches/rejections/{rejection['id']}")
        missing = self.client.delete(f"/api/matches/rejections/{rejection['id']}")

        self.assertEqual(resolved.status_code, 200)
        self.assertEqual(resolved.json()["review"]["rejection_id"], rejection["id"])
        self.assertEqual(rejection["display_title"], "Front Innocent")
        self.assertEqual(rejection["tmdb_id"], 99)
        self.assertEqual(
            self.store.get_task(task["id"])["items"][item_id]["review"]["action"],
            "rejected",
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(missing.status_code, 404)

    def test_settings_endpoint_preserves_masked_secrets_and_rejects_invalid_model_url(self):
        save = self.client.post(
            "/api/settings",
            json={
                "tmdb": {"api_key": "tmdb-secret-value"},
                "tavily": {"api_key": "tvly-secret-value"},
                "model": {"base_url": "http://127.0.0.1:11434/v1", "api_key": "model-secret-value"},
            },
        )
        self.assertEqual(save.status_code, 200)
        masked = save.json()["config"]
        self.assertEqual(masked["tmdb"]["api_key"], "tmdb********alue")
        self.assertEqual(masked["tavily"]["api_key"], "tvly********alue")

        resave_masked = self.client.post("/api/settings", json=masked)
        self.assertEqual(resave_masked.status_code, 200)
        self.assertEqual(self.settings_manager.get_effective_config()["tmdb"]["api_key"], "tmdb-secret-value")

        invalid = self.client.post("/api/settings", json={"model": {"base_url": "not-a-url"}})
        self.assertEqual(invalid.status_code, 400)

    def test_settings_history_endpoint_exposes_value_free_revision_evidence(self):
        save = self.client.post(
            "/api/settings",
            json={
                "tmdb": {"api_key": "tmdb-secret-value"},
                "matching": {"minimum_title_similarity": 0.68},
            },
        )
        history = self.client.get("/api/settings/history?limit=1")

        self.assertEqual(save.status_code, 200)
        self.assertIsNotNone(save.json()["revision"])
        self.assertEqual(save.json()["revision"]["actor"], "web")
        self.assertEqual(history.status_code, 200)
        revision = history.json()["revisions"][0]
        self.assertIn("tmdb.api_key", revision["changed_paths"])
        self.assertIn("matching.minimum_title_similarity", revision["changed_paths"])
        self.assertNotIn("tmdb-secret-value", str(revision))

    def test_settings_endpoint_rejects_stale_revision(self):
        initial = self.client.get("/api/settings").json()
        stale = dict(initial)
        first = dict(initial)
        first["matching"] = {**initial["matching"], "minimum_title_similarity": 0.67}
        accepted = self.client.post("/api/settings", json=first)

        stale["matching"] = {**initial["matching"], "minimum_token_overlap": 0.79}
        rejected = self.client.post("/api/settings", json=stale)

        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(rejected.status_code, 409)
        self.assertIn("current revision", rejected.json()["detail"])
        self.assertEqual(
            self.settings_manager.get_effective_config()["matching"]["minimum_title_similarity"],
            0.67,
        )

    def test_connectivity_endpoint_skips_missing_keys_without_network_calls(self):
        self.settings_manager.save_settings({"tmdb": {"api_key": ""}, "tavily": {"api_key": "", "api_keys": []}})

        with patch("requests.get") as tmdb_get, patch("requests.post") as tavily_post:
            response = self.client.get("/api/connectivity")
            legacy = self.client.get("/api/test_connectivity")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(legacy.status_code, 200)
        body = response.json()
        self.assertEqual(body["tmdb"]["status"], "skipped")
        self.assertEqual(body["tavily"]["status"], "skipped")
        self.assertEqual(body["tavily"]["checked_keys"], 0)
        tmdb_get.assert_not_called()
        tavily_post.assert_not_called()

    def test_connectivity_endpoint_checks_tavily_key_list_and_reports_count(self):
        self.settings_manager.save_settings(
            {
                "tmdb": {"api_key": "tmdb-key"},
                "tavily": {"api_key": "", "api_keys": ["bad-key", "good-key"]},
            }
        )
        tavily_calls = [
            FakeResponse(401, {"detail": {"error": "invalid key"}}),
            FakeResponse(200, {"results": []}),
        ]

        with patch("requests.get", return_value=FakeResponse(200, {})) as tmdb_get, patch("requests.post", side_effect=tavily_calls) as tavily_post:
            response = self.client.get("/api/test_connectivity")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["tmdb"]["status"], "ok")
        self.assertEqual(body["tavily"]["status"], "ok")
        self.assertEqual(body["tavily"]["checked_keys"], 2)
        self.assertEqual(tmdb_get.call_count, 1)
        self.assertEqual(tavily_post.call_count, 2)

    def test_recovery_preview_blocks_manual_review_and_restarts_safe_task(self):
        task = self.store.create_task(
            str(self.media_dir),
            {
                "dry_run": False,
                "workers": 1,
                "inplace": True,
                "enable_organize": True,
                "search_mode": "tmdb_only",
                "operation_scope": "full",
            },
        )
        self.store.emit(task["id"], "task.failed", {"error": "move failed"})

        manual_preview = {
            "task_id": task["id"],
            "status": "manual_review",
            "strategy": "manual_review",
            "rollback_required": True,
            "reason": "Recorded output changed.",
            "review_count": 1,
            "operations": [{"status": "current_modified"}],
        }
        with patch("src.core.operation_manifest.preview_recovery_manifest", return_value=manual_preview):
            preview = self.client.get(f"/api/tasks/{task['id']}/recovery/preview")
            blocked = self.client.post(f"/api/tasks/{task['id']}/recover")

        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()["status"], "manual_review")
        self.assertEqual(blocked.status_code, 409)

        safe_preview = {
            "task_id": task["id"],
            "status": "ready",
            "strategy": "retry",
            "rollback_required": False,
            "reason": "No operations recorded.",
            "operations": [],
        }
        with patch("src.core.operation_manifest.preview_recovery_manifest", return_value=safe_preview):
            restarted = self.client.post(f"/api/tasks/{task['id']}/recover")

        self.assertEqual(restarted.status_code, 200)
        self.assertEqual(restarted.json()["status"], "restarted")
        self.assertNotEqual(restarted.json()["task_id"], task["id"])
        source = self.store.get_task(task["id"])
        self.assertEqual(source["recovery"]["status"], "restarted")
        self.assertEqual(source["recovery"]["retry_task_id"], restarted.json()["task_id"])

    def test_recovery_rolls_back_before_retry_and_rejects_completed_task(self):
        task = self.store.create_task(str(self.media_dir), {"dry_run": False, "workers": 1})
        self.store.emit(task["id"], "task.partial", {"summary": {"total": 1, "partial": 1}})
        safe_preview = {
            "task_id": task["id"],
            "status": "ready",
            "strategy": "rollback_then_retry",
            "rollback_required": True,
            "operations": [{"status": "would_rolled_back"}],
        }
        rollback = {"task_id": task["id"], "status": "completed", "preview": False, "operations": [{"status": "rolled_back"}]}
        with patch(
            "src.core.operation_manifest.preview_recovery_manifest",
            return_value=safe_preview,
        ), patch(
            "src.core.operation_manifest.rollback_manifest",
            return_value=rollback,
        ):
            restarted = self.client.post(f"/api/tasks/{task['id']}/recover")

        self.assertEqual(restarted.status_code, 200)
        self.assertEqual(restarted.json()["strategy"], "rollback_then_retry")
        self.assertEqual(restarted.json()["rollback"]["status"], "completed")

        completed = self.store.create_task(str(self.media_dir), {})
        self.store.emit(completed["id"], "task.completed", {"summary": {"total": 1, "completed": 1}})
        rejected = self.client.get(f"/api/tasks/{completed['id']}/recovery/preview")
        self.assertEqual(rejected.status_code, 409)
