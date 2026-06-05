import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.server import main as server_main
from src.server.settings_manager import SettingsManager
from src.server.task_events import TaskEventStore


class FakeJobManager:
    def __init__(self):
        self.is_running = False
        self.started = None
        self.stopped = False
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
        if self.auto_release:
            self.release_reservation()

    def stop_task(self):
        self.stopped = True


class ApiContractsTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.root = Path(self.temp_dir.name)
        self.media_dir = self.root / "media"
        self.media_dir.mkdir()
        self.store = TaskEventStore(storage_path=str(self.root / "task_events.json"))
        self.fake_jobs = FakeJobManager()
        self.settings_manager = SettingsManager(config_path=str(self.root / "config.yaml"))

        self.patches = [
            patch.object(server_main, "task_event_store", self.store),
            patch.object(server_main, "job_manager", self.fake_jobs),
            patch.object(server_main, "settings_manager", self.settings_manager),
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
        self.assertEqual(self.fake_jobs.started["task_id"], task_id)
        self.assertEqual(self.fake_jobs.started["tmdb_id"], None)

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
        self.assertEqual(task["config"]["search_mode"], "tmdb_only")

    def test_start_task_snapshot_records_copy_and_organize_strategy(self):
        output_dir = self.root / "library"
        output_dir.mkdir()

        copy_response = self.client.post(
            "/api/tasks/start",
            json={
                "input_dir": str(self.media_dir),
                "dry_run": False,
                "copy_mode": True,
                "output_dir": str(output_dir),
                "enable_organize": True,
            },
        )

        self.assertEqual(copy_response.status_code, 200)
        copy_task = self.store.get_task(copy_response.json()["task_id"])
        self.assertEqual(copy_task["config"]["strategy"], "copy")
        self.assertTrue(copy_task["config"]["copy_mode"])
        self.assertEqual(copy_task["config"]["output_dir"], str(output_dir))

        organize_response = self.client.post(
            "/api/tasks/start",
            json={
                "input_dir": str(self.media_dir),
                "dry_run": False,
                "inplace": True,
                "enable_organize": True,
            },
        )

        self.assertEqual(organize_response.status_code, 200)
        organize_task = self.store.get_task(organize_response.json()["task_id"])
        self.assertEqual(organize_task["config"]["strategy"], "organize")
        self.assertTrue(organize_task["config"]["inplace"])
        self.assertFalse(organize_task["config"]["copy_mode"])

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

    def test_rollback_endpoint_reports_missing_manifest_and_emits_result(self):
        task = self.store.create_task(str(self.media_dir), {"dry_run": False})
        task_id = task["id"]
        self.store.emit(task_id, "task.completed", {"summary": {"total": 1, "completed": 1, "failed": 0}})

        with patch("src.core.operation_manifest.rollback_manifest", return_value={"status": "completed", "operations": []}):
            response = self.client.post(f"/api/tasks/{task_id}/rollback")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "completed")
        self.assertEqual(self.store.get_task(task_id)["rollback"]["status"], "completed")

        with patch("src.core.operation_manifest.rollback_manifest", return_value={"status": "not_found"}):
            missing = self.client.post("/api/tasks/no-manifest/rollback")

        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["detail"], "Task not found")

    def test_rollback_endpoint_rejects_running_task(self):
        task = self.store.create_task(str(self.media_dir), {"dry_run": False})
        task_id = task["id"]
        self.store.emit(task_id, "task.started", {"input_dir": str(self.media_dir)})

        response = self.client.post(f"/api/tasks/{task_id}/rollback")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "Task is still running")

    def test_rollback_endpoint_reports_missing_manifest_for_finished_task(self):
        task = self.store.create_task(str(self.media_dir), {"dry_run": False})
        task_id = task["id"]
        self.store.emit(task_id, "task.completed", {"summary": {"total": 1, "completed": 1, "failed": 0}})

        with patch("src.core.operation_manifest.rollback_manifest", return_value={"status": "not_found"}):
            response = self.client.post(f"/api/tasks/{task_id}/rollback")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Manifest not found")

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
