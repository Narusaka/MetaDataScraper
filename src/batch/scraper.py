
import os
import logging
import yaml
import traceback
import copy
from pathlib import Path
from typing import Optional, List
from concurrent.futures import ThreadPoolExecutor, as_completed, CancelledError
import threading

from src.pipeline.pipeline import MediaPipeline
from src.core.directory_lock import DirectoryLock, DirectoryLockError
from src.core.filename_parser import FilenameParser
from src.core.cancellation import OperationCancelled, raise_if_cancelled
from src.core.execution_verifier import ExecutionVerifier
from src.core.plan_integrity import assert_plan_digest
from src.core.path_filters import is_hidden_path
from src.server.task_events import task_event_store
from .scanner import MediaScanner
from .organizer import MediaOrganizer, OrganizerExecutionError
from .detector import MediaTypeDetector

logger = logging.getLogger(__name__)

class BatchMediaScraper:
    def __init__(self, 
                 config_path: str = "config.yaml",
                 copy_files: bool = False, 
                 inplace_rename: bool = False, 
                 output_dir: Optional[str] = None,
                 multi_mode: bool = False,
                 tmdb_id: Optional[int] = None, 
                 use_local_nfo: bool = False, 
                 extra_images: bool = False, 
                 media_type: Optional[str] = None,
                 search_mode: str = "smart",
                 enable_fallback: bool = True,
                 max_workers: int = 4,
                 dry_run: bool = False,
                 fresh: bool = False,
                 enable_organize: bool = False,
                 overwrite_images: bool = False,
                 rename_parent_dir: bool = False,
                 conflict_strategy: Optional[str] = None,
                 operation_scope: str = "full",
                 task_id: Optional[str] = None,
                 expected_plan_digest: Optional[str] = None,
                 runtime_config: Optional[dict] = None):
        
        self.config = copy.deepcopy(runtime_config) if runtime_config is not None else self._load_config(config_path)
        self.copy_files = copy_files
        self.inplace_rename = inplace_rename
        self.output_dir = output_dir
        self.multi_mode = multi_mode
        self.tmdb_id = tmdb_id
        self.extra_images = extra_images
        self.media_type = media_type
        self.search_mode = search_mode
        self.enable_fallback = enable_fallback
        # Priority: UI Argument > Environment Variable > Default(4)
        env_workers = os.getenv("MAX_WORKERS")
        self.max_workers = int(max_workers if max_workers is not None else (env_workers if env_workers else 4))
        self.dry_run = dry_run
        self.fresh = fresh
        self.enable_organize = enable_organize
        self.overwrite_images = overwrite_images
        self.rename_parent_dir = rename_parent_dir
        configured_conflict_strategy = self.config.get("output", {}).get("conflict_strategy", "error")
        self.conflict_strategy = conflict_strategy or configured_conflict_strategy
        self.task_id = task_id
        self.operation_scope = operation_scope if operation_scope in {"full", "nfo_only", "artwork_only", "organize_only"} else "full"
        self.expected_plan_digest = expected_plan_digest
        if self.operation_scope in {"nfo_only", "artwork_only"}:
            self.enable_organize = False
            self.rename_parent_dir = False
        
        self.pipeline = None
        
        self.stop_event = threading.Event()

        # Initialize Components
        self.scanner = MediaScanner(
            media_type=media_type, 
            use_local_nfo=use_local_nfo, 
            tmdb_id=tmdb_id
        )
        self.organizer = MediaOrganizer(
            dry_run=dry_run, 
            inplace_rename=inplace_rename, 
            copy_files=copy_files,
            enable_organize=self.enable_organize,
            overwrite_images=overwrite_images,
            rename_parent_dir=self.rename_parent_dir,
            conflict_strategy=self.conflict_strategy,
            task_id=task_id,
            cancel_event=self.stop_event,
            operation_scope=self.operation_scope,
        )
        self.executor = None
        self.verifier = ExecutionVerifier()

    def _assert_confirmed_plan(self, plan: dict) -> None:
        expected_digest = getattr(self, "expected_plan_digest", None)
        if expected_digest:
            assert_plan_digest(plan, expected_digest)

    def _effective_operation_scope(self) -> str:
        scope = getattr(self, "operation_scope", "full")
        return scope if scope in {"full", "nfo_only", "artwork_only", "organize_only"} else "full"

    def _emit(self, event_type: str, payload: Optional[dict] = None, item_id: Optional[str] = None):
        return task_event_store.emit(self.task_id, event_type, payload or {}, item_id=item_id)

    def _task_item_id(self, task: dict) -> str:
        if task["type"] == "directory":
            return str(task["path"])
        if task["type"] == "loose_files":
            show_name = task.get("show_name") or "Loose Files"
            return str(task["base_dir"] / show_name)
        if task["type"] == "quarantined":
            return str(task["path"])
        return f"unknown:{id(task)}"

    def _describe_task(self, task: dict) -> dict:
        if task["type"] == "directory":
            path = task["path"]
            return {
                "name": path.name,
                "path": str(path),
                "kind": "directory",
                "media_type": task.get("media_type") or self.media_type,
                "tmdb_id": task.get("tmdb_id"),
                "video_count": self._count_video_files(path),
            }
        if task["type"] == "loose_files":
            show_name = task.get("show_name") or "Loose Files"
            return {
                "name": FilenameParser.clean_show_name_for_search(show_name),
                "path": str(task["base_dir"] / show_name),
                "kind": "loose_files",
                "media_type": self.media_type,
                "file_count": len(task.get("files", [])),
                "video_count": sum(1 for item in task.get("files", []) if item.suffix.lower() in FilenameParser.VIDEO_EXTENSIONS),
            }
        if task["type"] == "quarantined":
            parsed = task.get("parse") or {}
            return {
                "name": task["path"].name,
                "path": str(task["path"]),
                "kind": "quarantined",
                "reason": task.get("reason"),
                "parse": parsed,
                "parse_confidence": parsed.get("confidence"),
            }
        return {"name": "Unknown", "kind": "unknown"}

    def _count_video_files(self, path: Path) -> int:
        try:
            return sum(
                1
                for item in path.rglob("*")
                if item.is_file()
                and not is_hidden_path(item)
                and item.suffix.lower() in FilenameParser.VIDEO_EXTENSIONS
            )
        except OSError:
            return 0

    def stop(self):
        """Signal the scraper to stop processing."""
        logger.warning("🛑 Stop signal received in Scraper")
        self.stop_event.set()
        if self.executor:
            # Cancel all pending futures
            self.executor.shutdown(wait=False, cancel_futures=True)

    def _load_config(self, path: str) -> dict:
        p = Path(path)
        c = {
            "tmdb": {"api_key": ""},
            "omdb": {"api_key": ""},
            "tavily": {"api_key": ""},
            "model": {
                "base_url": "http://127.0.0.1:8045/v1",
                "api_key": "EMPTY",
                "model": "gemini-3-flash",
                "temperature": 0.1,
            },
            "output": {
                "conflict_strategy": "error",
                "nfo_policy": {
                    "profile": "universal",
                    "targets": ["jellyfin", "emby", "kodi"],
                    "include_uniqueid": True,
                    "include_legacy_tmdbid": True,
                    "episode_sidecars": "present_only",
                },
                "image_limit": {"posters": 20, "backdrops": 5, "logos": 5, "stills": 10, "actors": 10},
                "artwork_policy": {
                    "preferred_languages": ["zh", "en", "ja"],
                    "min_poster_width": 500,
                    "min_backdrop_width": 1280,
                    "min_logo_width": 300,
                },
            },
        }
        if p.exists():
            with open(p, 'r') as f:
                loaded = yaml.safe_load(f) or {}
                self._deep_update(c, loaded)
                logger.info(f"Loaded config from {path}")
        
        # Inject Secrets from Environment
        self._inject_env(c, "TMDB_API_KEY", ["tmdb", "api_key"])
        self._inject_env(c, "OMDB_API_KEY", ["omdb", "api_key"])
        self._inject_env(c, "MODEL_API_KEY", ["model", "api_key"])
        self._inject_env(c, "MODEL_BASE_URL", ["model", "base_url"])
        self._inject_env(c, "TAVILY_API_KEY", ["tavily", "api_key"])
        
        return c

    def _deep_update(self, target: dict, updates: dict) -> dict:
        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                self._deep_update(target[key], value)
            else:
                target[key] = value
        return target

    def _inject_env(self, config: dict, env_key: str, config_path: List[str]):
        val = os.getenv(env_key)
        if val:
            curr = config
            for key in config_path[:-1]:
                if key not in curr: curr[key] = {}
                curr = curr[key]
            curr[config_path[-1]] = val

    def run(self, input_dir: str, output_dir: Optional[str] = None):
        """Run the batch scraper."""
        if output_dir:
            self.output_dir = output_dir
            
        root_path = Path(input_dir)
        if not root_path.exists():
            # Feature: JIT Loose File Extraction
            # If the specific task directory doesn't exist, it might be a "Virtual" task representing loose files 
            # in the parent directory that haven't been moved yet.
            parent_dir = root_path.parent
            if parent_dir.exists():
                 logger.info(f"Target directory {root_path} not found. Checking parent {parent_dir} for loose files to organize...")
                 # Temporarily use scanner to find loose files in parent
                 loose_files = self.scanner._find_loose_files(parent_dir)
                 if loose_files:
                     # Filter files that match this specific show/task name
                     target_name = root_path.name
                     # Re-use process_loose_files logic but forced to ONLY process this target
                     # We create a temporary group for just this show
                     relevant_files = []
                     for f in loose_files:
                         extracted = FilenameParser.extract_show_name(f.name)
                         if extracted and FilenameParser.clean_show_name_for_search(extracted) == target_name:
                             relevant_files.append(f)
                    
                     if relevant_files:
                         logger.info(f"Found {len(relevant_files)} loose files for '{target_name}'. Auto-organizing now...")
                         fallback_item_id = str(root_path)
                         self.organizer._ensure_directory(root_path, fallback_item_id, "organize.loose_group")
                         for f in relevant_files:
                             if f.parent != root_path:
                                 dest = root_path / f.name
                                 self.organizer._move_or_copy(f, dest, item_id=fallback_item_id)
                         logger.info(f"✅ Auto-organized files into {root_path}")
                     else:
                         logger.error(f"Input directory does not exist and no matching loose files found: {input_dir}")
                         return
                 else:
                     logger.error(f"Input directory does not exist: {input_dir}")
                     return
            else:
                 logger.error(f"Input directory does not exist: {input_dir}")
                 return
            
        logger.info("🚀 Starting Batch Scraper")
        logger.info(f"   Input: {input_dir}")
        logger.info(f"   Mode: {'Multi-directory' if self.multi_mode else 'Single directory'}")
        self._emit(
            "task.scan.started",
            {"input_dir": input_dir, "mode": "multi" if self.multi_mode else "single"},
        )
        
        # Initialize Pipeline
        if not self.pipeline:
             self.pipeline = MediaPipeline(
                 self.config, 
                 verbose=False,
                 quiet=True, # Batch mode quiet
                 inplace=self.inplace_rename,
                 extra_images=self.extra_images,
                 manifest=self.organizer.manifest,
                 cancel_event=self.stop_event,
             )
             # Inject pipeline into organizer for art download
             self.organizer.pipeline = self.pipeline

        # Scan
        if self.multi_mode:
             tasks = self.scanner.scan_multi(root_path)
             # If no sub-dirs or loose files found, maybe the root is the target?
             if not tasks:
                 logger.info("No sub-tasks found in multi-mode, falling back to single directory mode.")
                 tasks = self.scanner.scan_single(root_path)
        else:
             tasks = self.scanner.scan_single(root_path)

        self._emit("task.scan.completed", {"total": len(tasks)})
        for task in tasks:
            self._emit("item.planned", self._describe_task(task), item_id=self._task_item_id(task))
        return self._execute_tasks(tasks)

    def _execute_tasks(self, tasks: List[dict]):
        if not tasks:
            logger.info("No tasks found.")
            return

        logger.info(f"Found {len(tasks)} tasks to process with {self.max_workers} workers")

        if self.stop_event.is_set():
            logger.warning("Scraper stop event detected before execution. Aborting.")
            return

        # self.stop_event.clear() - DO NOT CLEAR here, it might have been set by stop() already
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
        
        try:
            future_to_task = {self.executor.submit(self._process_task, task): task for task in tasks}
            
            completed_count = 0
            partial_count = 0
            quarantined_count = 0
            failed_tasks = []
            
            # Process results as they complete
            # We explicitly catch CancelledError for stopped tasks
            from concurrent.futures import wait, FIRST_COMPLETED
            
            futures_set = set(future_to_task.keys())
            
            while futures_set:
                if self.stop_event.is_set():
                    logger.warning("🛑 Stop event detected in loop. Cancelling remaining tasks...")
                    for f in futures_set:
                        f.cancel()
                    break
                
                # Wait for at least one future to complete, or timeout to check stop_event
                done, not_done = wait(futures_set, timeout=0.5, return_when=FIRST_COMPLETED)
                
                for future in done:
                    futures_set.remove(future)
                    task = future_to_task[future]
                    task_name = "Loose Files"
                    if task["type"] == "directory":
                        task_name = task["path"].name
                    elif task["type"] == "loose_files":
                        task_name = task.get("show_name", "Loose Files")
                    elif task["type"] == "quarantined":
                        task_name = task["path"].name
                    
                    try:
                        result = future.result()
                        
                        # Handle Tuple (success, reason) or Bool
                        success = False
                        failure_reason = task_name # Default
                        
                        if isinstance(result, tuple):
                            outcome = result[0]
                            success = outcome is True
                            is_partial = outcome == "partial"
                            failure_reason = result[1]
                        else:
                            success = result
                            is_partial = False
                            
                        if success and task["type"] == "quarantined":
                            quarantined_count += 1
                        elif success:
                            completed_count += 1
                        elif is_partial:
                            partial_count += 1
                        else:
                            failed_tasks.append(failure_reason)

                        self._emit(
                            "task.progress",
                            {
                                "processed": completed_count + partial_count + quarantined_count + len(failed_tasks),
                                "total": len(tasks),
                                "completed": completed_count,
                                "partial": partial_count,
                                "quarantined": quarantined_count,
                                "failed": len(failed_tasks),
                            },
                        )
                            
                    except CancelledError:
                        logger.info(f"Task {task_name} was cancelled.")
                    except Exception as e:
                        logger.error(f"Task {task_name} raised exception: {e}")
                        failed_tasks.append(f"{task_name} (Worker Exception: {e})")

            msg = f"Batch processing finished: {completed_count}/{len(tasks)} successful, {partial_count} partial, {quarantined_count} quarantined, {len(failed_tasks)} failed"
            if self.stop_event.is_set():
                 msg += " (STOPPED)"
            
            if failed_tasks:
                msg += f"\n❌ Failed items: {', '.join(failed_tasks)}"
            logger.info(msg)

            return {
                "completed": completed_count,
                "partial": partial_count,
                "failed": len(failed_tasks),
                "quarantined": quarantined_count,
                "total": len(tasks),
                "failed_names": failed_tasks,
                "stopped": self.stop_event.is_set()
            }
        except KeyboardInterrupt:
            logger.warning("\n🛑 Stopping workers... (Ctrl+C pressed)")
            self.stop()
            return {"completed": 0, "failed": 0, "quarantined": 0, "total": len(tasks), "failed_names": []}
        finally:
            if self.executor:
                self.executor.shutdown(wait=False)
                self.executor = None

    def _process_task(self, task: dict):
        # Returns True, (False, Reason), or False
        if self.stop_event.is_set():
            return (False, "Scraper Stopped")
        
        item_id = self._task_item_id(task)
            
        if task["type"] == "directory":
            return self._process_directory(task["path"], task["tmdb_id"], task.get("media_type"), is_group_folder=task.get("is_group_folder", False), item_id=item_id)
        elif task["type"] == "loose_files":
            return self._process_loose_files(task["files"], task["base_dir"], task.get("show_name"), item_id=item_id)
        elif task["type"] == "quarantined":
            payload = self._describe_task(task)
            self._emit("item.quarantined", payload, item_id=item_id)
            return (True, f"{task['path'].name} quarantined")
        return (False, "Unknown Task Type")

    def _process_directory(self, dir_path: Path, tmdb_id: Optional[int], task_media_type: Optional[str] = None, is_group_folder: bool = False, item_id: Optional[str] = None, execution_lock_held: bool = False) -> bool:
        show_name = dir_path.name
        
        if self.dry_run:
            logger.info(f"[Audit Mode] Analyzing directory: {dir_path}")
        else:
            logger.info(f"Analyzing directory: {dir_path}")

        query = "" if tmdb_id else FilenameParser.clean_show_name_for_search(show_name)
        extracted_year = FilenameParser.extract_year(show_name)
        
        # Detection logic: Task-level (from NFO) > Global (from UI) > Auto-detect
        current_media_type = task_media_type or self.media_type or MediaTypeDetector.detect(dir_path)
        
        logger.info(f"Processing: {show_name} (ID: {tmdb_id}, Query: {query}, Type: {current_media_type})")
        self._emit(
            "item.started",
            {
                "name": show_name,
                "path": str(dir_path),
                "query": query,
                "media_type": current_media_type,
                "tmdb_id": tmdb_id,
                "dry_run": self.dry_run,
            },
            item_id=item_id or str(dir_path),
        )

        target_output_dir = str(dir_path) if self.inplace_rename else self.output_dir

        input_data = {
            "media_type": current_media_type,
            "media_type_forced": (self.media_type is not None) or (task_media_type is not None), 
            "query": query,
            "year": extracted_year,
            "output_dir": target_output_dir,
            "source_path": str(dir_path), # Pass source path explicitly for audit logging
            "verbose": False,
            "quiet": True,
            "aid_search": True,
            "inplace": self.inplace_rename,
            "extra_images": self.extra_images,
            "overwrite_images": self.overwrite_images,
            "search_mode": self.search_mode,
            "tmdb_only": self.search_mode == "tmdb_only",
            "fallback_on_fail": self.enable_fallback,
            "audit_only": False,
            "plan_only": self.dry_run,
            "operation_scope": self._effective_operation_scope(),
        }
        
        if tmdb_id:
            input_data["tmdb_id"] = tmdb_id
            input_data["media_type_forced"] = True
            
            # SKIPPING LOGIC (If NFO exists and NOT fresh)
            # Check for actual NFO file existence to avoid skipping clean folders where user manually input an ID
            has_existing_nfo = (dir_path / "movie.nfo").exists() or (dir_path / "tvshow.nfo").exists()
            
            if has_existing_nfo and not self.fresh and not self.dry_run:
                 logger.warning(f"Skipping {show_name}: Metadata already exists (use --fresh to overwrite)")
                 self._emit(
                     "item.skipped",
                     {"name": show_name, "path": str(dir_path), "reason": "metadata_exists"},
                     item_id=item_id or str(dir_path),
                 )
                 return (True, "任务成功，元数据已存在")
            
            if self.fresh and has_existing_nfo:
                logger.info(f"Using Fresh Mode: Overwriting/Refreshing metadata for {show_name}")

        execution_lock = None
        try:
            if not self.dry_run:
                self._emit(
                    "item.execution_phase",
                    {"phase": "preflight", "name": show_name, "path": str(dir_path)},
                    item_id=item_id or str(dir_path),
                )
                preflight_input = input_data.copy()
                preflight_input["audit_only"] = False
                preflight_input["plan_only"] = True
                preflight_result = self.pipeline.run(preflight_input)
                if preflight_result.get("status") == "cancelled":
                    self._emit(
                        "item.cancelled",
                        {"name": show_name, "path": str(dir_path), "stage": preflight_result.get("stage")},
                        item_id=item_id or str(dir_path),
                    )
                    return (False, f"{show_name} cancelled")
                if preflight_result.get("status") != "plan_ready":
                    error = preflight_result.get("error", "Preflight failed")
                    self._emit(
                        "item.failed",
                        {
                            "name": show_name,
                            "path": str(dir_path),
                            "error": error,
                            "error_code": preflight_result.get("error_code"),
                            "candidate": preflight_result.get("candidate"),
                            "match": preflight_result.get("match"),
                        },
                        item_id=item_id or str(dir_path),
                    )
                    return (False, f"任务失败: {error}")

                candidate = preflight_result.get("candidate", {})
                match = preflight_result.get("match", {})
                poster_suffix = candidate.get("poster_path")
                poster_url = f"https://image.tmdb.org/t/p/w200{poster_suffix}" if poster_suffix else ""
                plan = self.organizer.build_plan(dir_path, preflight_result, configured_media_type=current_media_type, is_group_folder=is_group_folder)
                self._assert_confirmed_plan(plan)
                self._emit(
                    "candidate.selected",
                    {
                        "title": candidate.get("title") or candidate.get("name") or show_name,
                        "tmdb_id": candidate.get("id"),
                        "poster_path": poster_suffix,
                        "poster_url": poster_url,
                        "media_type": current_media_type,
                        "match": match,
                    },
                    item_id=item_id or str(dir_path),
                )
                self._emit(
                    "item.plan_ready",
                    {"plan": plan},
                    item_id=item_id or str(dir_path),
                )
                if self.organizer.has_blockers(plan):
                    message = "Execution blocked by plan conflicts"
                    logger.error(f"{message}: {show_name}")
                    self._emit(
                        "item.failed",
                        {
                            "name": show_name,
                            "path": str(dir_path),
                            "error": message,
                            "plan_summary": plan.get("summary", {}),
                        },
                        item_id=item_id or str(dir_path),
                    )
                    return (False, "任务失败，执行计划存在冲突")
                if not execution_lock_held:
                    try:
                        execution_lock = DirectoryLock(Path(plan.get("target_root") or dir_path), owner=self.task_id or item_id or show_name).acquire()
                        self._emit(
                            "item.lock_acquired",
                            {"target_path": str(execution_lock.target_path), "lock_path": str(execution_lock.lock_path)},
                            item_id=item_id or str(dir_path),
                        )
                    except DirectoryLockError as lock_error:
                        message = str(lock_error)
                        logger.error(message)
                        self._emit(
                            "item.failed",
                            {
                                "name": show_name,
                                "path": str(dir_path),
                                "error": message,
                                "lock": {
                                    "target_path": str(lock_error.target_path),
                                    "lock_path": str(lock_error.lock_path),
                                    "owner": lock_error.owner,
                                },
                            },
                            item_id=item_id or str(dir_path),
                        )
                        return (False, "任务失败，目标目录正在被其他任务处理")

                if self.inplace_rename and self.enable_organize and plan.get("target_root"):
                    input_data["output_dir"] = plan["target_root"]

                self._emit(
                    "item.execution_phase",
                    {"phase": "metadata", "name": show_name, "path": str(dir_path)},
                    item_id=item_id or str(dir_path),
                )

            result = self.pipeline.run(input_data)
            status = result.get("status")
            
            if status == "cancelled":
                self._emit(
                    "item.cancelled",
                    {"name": show_name, "path": str(dir_path), "stage": result.get("stage")},
                    item_id=item_id or str(dir_path),
                )
                return (False, f"{show_name} cancelled")
            if status == "completed":
                candidate = result.get("candidate", {})
                match = result.get("match", {})
                self._emit(
                    "candidate.selected",
                    {
                        "title": candidate.get("title") or candidate.get("name") or show_name,
                        "tmdb_id": candidate.get("id"),
                        "poster_path": candidate.get("poster_path"),
                        "media_type": current_media_type,
                        "match": match,
                    },
                    item_id=item_id or str(dir_path),
                )
                plan = self.organizer.build_plan(dir_path, result, configured_media_type=current_media_type, is_group_folder=is_group_folder)
                self._emit(
                    "item.execution_phase",
                    {"phase": "organizing", "name": show_name, "path": str(dir_path)},
                    item_id=item_id or str(dir_path),
                )
                self.organizer.organize(
                    dir_path,
                    result,
                    configured_media_type=current_media_type,
                    is_group_folder=is_group_folder,
                    item_id=item_id or str(dir_path),
                )
                self._emit(
                    "item.execution_phase",
                    {"phase": "verifying", "name": show_name, "path": str(dir_path)},
                    item_id=item_id or str(dir_path),
                )
                self._emit(
                    "item.verification_started",
                    {"name": show_name, "path": str(dir_path), "plan_summary": plan.get("summary", {})},
                    item_id=item_id or str(dir_path),
                )
                verification = self.verifier.verify(plan, artwork=result.get("artwork"))
                self._emit(
                    "item.verification_completed",
                    {"verification": verification},
                    item_id=item_id or str(dir_path),
                )
                if verification["status"] == "failed":
                    message = "Execution verification failed"
                    self._emit(
                        "item.failed",
                        {
                            "name": show_name,
                            "path": str(dir_path),
                            "error": message,
                            "error_code": "EXECUTION_VERIFICATION_FAILED",
                            "verification": verification,
                            "artwork": result.get("artwork"),
                            "plan_summary": plan.get("summary", {}),
                        },
                        item_id=item_id or str(dir_path),
                    )
                    return (False, f"{show_name}: {message}")
                if verification["status"] == "partial":
                    self._emit(
                        "item.partial",
                        {
                            "name": show_name,
                            "path": str(dir_path),
                            "result": "Execution completed with verification warnings",
                            "verification": verification,
                            "artwork": result.get("artwork"),
                            "plan_summary": plan.get("summary", {}),
                        },
                        item_id=item_id or str(dir_path),
                    )
                    return ("partial", f"{show_name}: verification warnings")
                logger.info(f"✅ Batch Scraper finished task: {show_name}")
                self._emit(
                    "item.completed",
                    {
                        "name": show_name,
                        "path": str(dir_path),
                        "result": "completed",
                        "artwork": result.get("artwork"),
                        "verification": verification,
                        "plan_summary": plan.get("summary", {}),
                    },
                    item_id=item_id or str(dir_path),
                )
                return (True, "任务成功，媒体文件数量完整。")
            elif status in {"audit_completed", "plan_ready"}:
                candidate = result.get("candidate", {})
                match = result.get("match", {})
                poster_suffix = candidate.get("poster_path")
                poster_url = f"https://image.tmdb.org/t/p/w200{poster_suffix}" if poster_suffix else ""
                plan = self.organizer.build_plan(dir_path, result, configured_media_type=current_media_type, is_group_folder=is_group_folder)
                logger.info(f"Plan completed for {show_name} [Poster={poster_url}]")
                self._emit(
                    "candidate.selected",
                    {
                        "title": candidate.get("title") or candidate.get("name") or show_name,
                        "tmdb_id": candidate.get("id"),
                        "poster_path": poster_suffix,
                        "poster_url": poster_url,
                        "media_type": current_media_type,
                        "match": match,
                    },
                    item_id=item_id or str(dir_path),
                )
                self._emit(
                    "item.plan_ready",
                    {"plan": plan},
                    item_id=item_id or str(dir_path),
                )
                self._emit(
                    "item.audit_completed",
                    {"name": show_name, "path": str(dir_path), "result": "audit_completed", "plan_summary": plan.get("summary", {})},
                    item_id=item_id or str(dir_path),
                )
                return (True, "检测通过/PASS")
            else:
                error_detail = result.get('error', 'Unknown error').lower()
                self._emit(
                    "item.failed",
                    {
                        "name": show_name,
                        "path": str(dir_path),
                        "error": result.get("error", "Unknown error"),
                        "error_code": result.get("error_code"),
                        "candidate": result.get("candidate"),
                        "match": result.get("match"),
                    },
                    item_id=item_id or str(dir_path),
                )
                if "no candidates" in error_detail or "not found" in error_detail:
                    return (False, "任务失败，找不到相关信息")
                return (False, f"任务失败: {result.get('error')}")

                
                # Format a more descriptive error message for the summary
                failure_reason = f"{show_name} ({error_detail})"
                if error_code:
                     failure_reason += f" [Code: {error_code}]"

                logger.error(f"Metadata generation failed for {show_name}: {error_detail} {f'({error_code})' if error_code else ''}")
                return (False, failure_reason)

        except OperationCancelled as exc:
            self._emit(
                "item.cancelled",
                {"name": show_name, "path": str(dir_path), "stage": exc.stage},
                item_id=item_id or str(dir_path),
            )
            return (False, f"{show_name} cancelled")
        except OrganizerExecutionError as exc:
            logger.error("Organizer stopped for %s: %s", show_name, exc)
            self._emit(
                "item.failed",
                {
                    "name": show_name,
                    "path": str(dir_path),
                    "error": str(exc),
                    "error_code": "ORGANIZER_OPERATION_FAILED",
                    "operation": exc.as_dict(),
                },
                item_id=item_id or str(dir_path),
            )
            return (False, f"{show_name} (Organizer stopped: {exc})")
        except Exception as e:
            logger.error(f"Scraper Error for {show_name}: {e}")
            self._emit(
                "item.failed",
                {"name": show_name, "path": str(dir_path), "error": str(e)},
                item_id=item_id or str(dir_path),
            )
            import traceback
            traceback.print_exc()
            return (False, f"{show_name} (System Error: {str(e)})")
        finally:
            if execution_lock:
                execution_lock.release()

    def _process_loose_files(self, files: List[Path], base_dir: Path, show_name: Optional[str] = None, item_id: Optional[str] = None) -> bool:
        if not files: return True
        
        # If show_name wasn't passed, try to extract it from the first file
        if not show_name:
            show_name = FilenameParser.extract_show_name(files[0].name)
        if not show_name: return (False, "Could not extract name from loose files")
        
        safe_name = FilenameParser.clean_show_name_for_search(show_name)
        target_path = base_dir / safe_name
        item_id = item_id or str(target_path)
        
        # Determine media type: User Override > Auto Detect
        if self.media_type:
            media_type = self.media_type
        else:
            # Detect media type from first file or name
            import re
            has_episode_marker = any(re.search(r'[#＃]\s*\d+', f.name) for f in files)
            is_tv = any(FilenameParser.parse_episode_info(str(f)) for f in files) or has_episode_marker
            media_type = "tv" if is_tv else "movie"

        operation_scope = self._effective_operation_scope()
        if not self.dry_run and operation_scope in {"nfo_only", "artwork_only"}:
            message = "NFO-only and artwork-only tasks require media to already be inside a dedicated directory"
            self._emit(
                "item.failed",
                {
                    "name": safe_name,
                    "path": str(target_path),
                    "error": message,
                    "error_code": "LOOSE_FILES_REQUIRE_ORGANIZE",
                    "operation_scope": operation_scope,
                },
                item_id=item_id,
            )
            return (False, message)

        if self.dry_run:
            logger.info(f"[Dry Run] Group: {safe_name} ({len(files)} files) -> Type: {media_type}")
            self._emit(
                "item.started",
                {
                    "name": safe_name,
                    "path": str(target_path),
                    "query": safe_name,
                    "media_type": media_type,
                    "file_count": len(files),
                    "dry_run": True,
                },
                item_id=item_id,
            )
            
            # A plan must fetch the same metadata that execution will use.
            input_data = {
                "media_type": media_type,
                "media_type_forced": True, 
                "query": safe_name,
                "year": FilenameParser.extract_year(show_name) or FilenameParser.extract_year(str(files[0])),
                "output_dir": str(base_dir), # Not used in audit
                "source_path": str(target_path), 
                "verbose": False,
                "quiet": True,
                "aid_search": True,
                "search_mode": self.search_mode,
                "overwrite_images": self.overwrite_images,
                "tmdb_only": self.search_mode == "tmdb_only",
                "fallback_on_fail": self.enable_fallback,
                "audit_only": False,
                "plan_only": True,
                "operation_scope": operation_scope,
            }
            
            try:
                logger.info(f"[Plan Mode] Analyzing directory (Loose Group): {target_path}")
                logger.info(f"Processing: {safe_name} (ID: None, Query: {safe_name}, Type: {media_type})")
                result = self.pipeline.run(input_data)
                
                status = result.get("status")
                if status == "cancelled":
                    self._emit(
                        "item.cancelled",
                        {"name": safe_name, "path": str(target_path), "stage": result.get("stage")},
                        item_id=item_id,
                    )
                    return (False, f"{safe_name} cancelled")
                if status in {"audit_completed", "completed", "plan_ready"}:
                    candidate = result.get("candidate", {})
                    match = result.get("match", {})
                    poster_suffix = candidate.get("poster_path")
                    poster_url = f"https://image.tmdb.org/t/p/w200{poster_suffix}" if poster_suffix else ""
                    plan = self.organizer.build_loose_file_plan(files, base_dir, show_name, result, media_type)
                    logger.info(f"Plan completed for {show_name} [Poster={poster_url}]")
                    self._emit(
                        "candidate.selected",
                        {
                            "title": candidate.get("title") or candidate.get("name") or safe_name,
                            "tmdb_id": candidate.get("id"),
                            "poster_path": poster_suffix,
                            "poster_url": poster_url,
                            "media_type": media_type,
                            "match": match,
                        },
                        item_id=item_id,
                    )
                    self._emit(
                        "item.plan_ready",
                        {"plan": plan},
                        item_id=item_id,
                    )
                    self._emit(
                        "item.audit_completed",
                        {"name": safe_name, "path": str(target_path), "result": "audit_completed", "plan_summary": plan.get("summary", {})},
                        item_id=item_id,
                    )
                    return True
                else:
                    logger.warning(f"Audit failed for {safe_name}: {result.get('error')}")
                    self._emit(
                        "item.failed",
                        {"name": safe_name, "path": str(target_path), "error": result.get("error", "Unknown error"), "match": result.get("match")},
                        item_id=item_id,
                    )
                    return (False, f"Audit failed: {result.get('error')}")
            except Exception as e:
                logger.error(f"Audit scan error for {safe_name}: {e}")
                self._emit(
                    "item.failed",
                    {"name": safe_name, "path": str(target_path), "error": str(e)},
                    item_id=item_id,
                )
                return (False, f"Audit Error: {e}")
        
        # Real Mode: Organize and process
        audit_input = {
            "media_type": media_type,
            "media_type_forced": True,
            "query": safe_name,
            "year": FilenameParser.extract_year(show_name) or FilenameParser.extract_year(str(files[0])),
            "output_dir": str(base_dir),
            "source_path": str(target_path),
            "verbose": False,
            "quiet": True,
            "aid_search": True,
            "search_mode": self.search_mode,
            "overwrite_images": self.overwrite_images,
            "tmdb_only": self.search_mode == "tmdb_only",
            "fallback_on_fail": self.enable_fallback,
            "audit_only": True,
            "operation_scope": operation_scope,
        }
        plan_input = audit_input.copy()
        plan_input["audit_only"] = False
        plan_input["plan_only"] = True
        audit_result = self.pipeline.run(plan_input)
        if audit_result.get("status") == "cancelled":
            self._emit(
                "item.cancelled",
                {"name": safe_name, "path": str(target_path), "stage": audit_result.get("stage")},
                item_id=item_id,
            )
            return (False, f"{safe_name} cancelled")
        if audit_result.get("status") != "plan_ready":
            error = audit_result.get("error", "Unknown error")
            self._emit(
                "item.failed",
                {"name": safe_name, "path": str(target_path), "error": error, "match": audit_result.get("match")},
                item_id=item_id,
            )
            return (False, f"Audit failed before execution: {error}")

        plan = self.organizer.build_loose_file_plan(files, base_dir, show_name, audit_result, media_type)
        self._assert_confirmed_plan(plan)
        self._emit(
            "item.plan_ready",
            {"plan": plan},
            item_id=item_id,
        )
        if self.organizer.has_blockers(plan):
            message = "Execution blocked by plan conflicts"
            logger.error(f"{message}: {safe_name}")
            self._emit(
                "item.failed",
                {"name": safe_name, "path": str(target_path), "error": message, "plan_summary": plan.get("summary", {})},
                item_id=item_id,
            )
            return (False, "任务失败，执行计划存在冲突")

        try:
            with DirectoryLock(target_path, owner=self.task_id or item_id or safe_name) as lock:
                self._emit(
                    "item.lock_acquired",
                    {"target_path": str(lock.target_path), "lock_path": str(lock.lock_path)},
                    item_id=item_id,
                )
                raise_if_cancelled(self.stop_event, "loose_files.create_directory")
                self.organizer._ensure_directory(target_path, item_id, "loose_files.create_directory")
                
                for f in files:
                    raise_if_cancelled(self.stop_event, "loose_files.move")
                    if f.parent != target_path:
                        dest = target_path / f.name
                        self.organizer._move_or_copy(f, dest, item_id=item_id)
                
                return self._process_directory(target_path, None, is_group_folder=True, item_id=item_id, execution_lock_held=True)
        except OperationCancelled as exc:
            self._emit(
                "item.cancelled",
                {"name": safe_name, "path": str(target_path), "stage": exc.stage},
                item_id=item_id,
            )
            return (False, f"{safe_name} cancelled")
        except DirectoryLockError as lock_error:
            message = str(lock_error)
            logger.error(message)
            self._emit(
                "item.failed",
                {
                    "name": safe_name,
                    "path": str(target_path),
                    "error": message,
                    "lock": {
                        "target_path": str(lock_error.target_path),
                        "lock_path": str(lock_error.lock_path),
                        "owner": lock_error.owner,
                    },
                },
                item_id=item_id,
            )
            return (False, "任务失败，目标目录正在被其他任务处理")
        except OrganizerExecutionError as exc:
            logger.error("Organizer stopped for loose file group %s: %s", safe_name, exc)
            self._emit(
                "item.failed",
                {
                    "name": safe_name,
                    "path": str(target_path),
                    "error": str(exc),
                    "error_code": "ORGANIZER_OPERATION_FAILED",
                    "operation": exc.as_dict(),
                },
                item_id=item_id,
            )
            return (False, f"任务失败: {exc}")
