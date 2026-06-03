
import os
import shutil
import logging
import yaml
import traceback
from pathlib import Path
from typing import Optional, List
from concurrent.futures import ThreadPoolExecutor, as_completed, CancelledError
import threading

from src.pipeline.pipeline import MediaPipeline
from src.core.filename_parser import FilenameParser
from src.server.task_events import task_event_store
from .scanner import MediaScanner
from .organizer import MediaOrganizer
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
                 task_id: Optional[str] = None):
        
        self.config = self._load_config(config_path)
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
        self.task_id = task_id
        
        self.pipeline = None
        
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
            enable_organize=enable_organize,
            overwrite_images=overwrite_images,
            rename_parent_dir=rename_parent_dir,
            task_id=task_id
        )
        
        self.stop_event = threading.Event()
        self.executor = None

    def _emit(self, event_type: str, payload: Optional[dict] = None, item_id: Optional[str] = None):
        return task_event_store.emit(self.task_id, event_type, payload or {}, item_id=item_id)

    def _task_item_id(self, task: dict) -> str:
        if task["type"] == "directory":
            return str(task["path"])
        if task["type"] == "loose_files":
            show_name = task.get("show_name") or "Loose Files"
            return str(task["base_dir"] / show_name)
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
        return {"name": "Unknown", "kind": "unknown"}

    def _count_video_files(self, path: Path) -> int:
        try:
            return sum(
                1
                for item in path.rglob("*")
                if item.is_file() and item.suffix.lower() in FilenameParser.VIDEO_EXTENSIONS
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
            "output": {"image_limit": {"posters": 20, "backdrops": 5, "logos": 5, "stills": 10, "actors": 10}},
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
                         # Create dir
                         root_existed = root_path.exists()
                         root_path.mkdir(exist_ok=True)
                         if not root_existed:
                             self.organizer.manifest.record("create_dir", None, root_path)
                         # Move files
                         import shutil
                         for f in relevant_files:
                             if f.parent != root_path:
                                 dest = root_path / f.name
                                 shutil.move(str(f), str(dest))
                                 self.organizer.manifest.record("move_file", f, dest)
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
                 extra_images=self.extra_images
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
                    
                    try:
                        result = future.result()
                        
                        # Handle Tuple (success, reason) or Bool
                        success = False
                        failure_reason = task_name # Default
                        
                        if isinstance(result, tuple):
                            success = result[0]
                            failure_reason = result[1]
                        else:
                            success = result
                            
                        if success: 
                            completed_count += 1
                        else: 
                            failed_tasks.append(failure_reason)
                            
                    except CancelledError:
                        logger.info(f"Task {task_name} was cancelled.")
                    except Exception as e:
                        logger.error(f"Task {task_name} raised exception: {e}")
                        failed_tasks.append(f"{task_name} (Worker Exception: {e})")

            msg = f"Batch processing finished: {completed_count}/{len(tasks)} successful, {len(failed_tasks)} failed"
            if self.stop_event.is_set():
                 msg += " (STOPPED)"
            
            if failed_tasks:
                msg += f"\n❌ Failed items: {', '.join(failed_tasks)}"
            logger.info(msg)

            return {
                "completed": completed_count,
                "failed": len(failed_tasks),
                "total": len(tasks),
                "failed_names": failed_tasks,
                "stopped": self.stop_event.is_set()
            }
        except KeyboardInterrupt:
            logger.warning("\n🛑 Stopping workers... (Ctrl+C pressed)")
            self.stop()
            return {"completed": 0, "failed": 0, "total": len(tasks), "failed_names": []}
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
        return (False, "Unknown Task Type")

    def _process_directory(self, dir_path: Path, tmdb_id: Optional[int], task_media_type: Optional[str] = None, is_group_folder: bool = False, item_id: Optional[str] = None) -> bool:
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
            "audit_only": self.dry_run # Enable audit mode if dry_run is True
        }
        
        # Override for inplace/dry_run dynamic behavior if this was triggered during a running batch
        # But here self.dry_run is set at init. 
        # Crucial Fix: If dry_run is False, input_data["audit_only"] MUST be False
        if not self.dry_run:
            input_data["audit_only"] = False
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

        try:
            result = self.pipeline.run(input_data)
            status = result.get("status")
            
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
                self.organizer.organize(dir_path, result, configured_media_type=current_media_type, is_group_folder=is_group_folder)
                logger.info(f"✅ Batch Scraper finished task: {show_name}")
                self._emit(
                    "item.completed",
                    {"name": show_name, "path": str(dir_path), "result": "completed"},
                    item_id=item_id or str(dir_path),
                )
                return (True, "任务成功，媒体文件数量完整。")
            elif status == "audit_completed":
                candidate = result.get("candidate", {})
                match = result.get("match", {})
                poster_suffix = candidate.get("poster_path")
                poster_url = f"https://image.tmdb.org/t/p/w200{poster_suffix}" if poster_suffix else ""
                plan = self.organizer.build_plan(dir_path, result, configured_media_type=current_media_type, is_group_folder=is_group_folder)
                logger.info(f"Audit completed for {show_name} [Poster={poster_url}]")
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
                    {"name": show_name, "path": str(dir_path), "error": result.get("error", "Unknown error")},
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
            
            # Prepare Pipeline Input for AUDIT
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
                "audit_only": True
            }
            
            try:
                logger.info(f"[Audit Mode] Analyzing directory (Loose Group): {target_path}")
                logger.info(f"Processing: {safe_name} (ID: None, Query: {safe_name}, Type: {media_type})")
                result = self.pipeline.run(input_data)
                
                status = result.get("status")
                if status == "audit_completed" or status == "completed":
                    candidate = result.get("candidate", {})
                    match = result.get("match", {})
                    poster_suffix = candidate.get("poster_path")
                    poster_url = f"https://image.tmdb.org/t/p/w200{poster_suffix}" if poster_suffix else ""
                    plan = self.organizer.build_loose_file_plan(files, base_dir, show_name, result, media_type)
                    logger.info(f"Audit completed for {show_name} [Poster={poster_url}]")
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
                        {"name": safe_name, "path": str(target_path), "error": result.get("error", "Unknown error")},
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
        if not target_path.exists():
            target_path.mkdir(exist_ok=True)
            self.organizer.manifest.record("create_dir", None, target_path)
        
        for f in files:
            if f.parent != target_path:
                dest = target_path / f.name
                shutil.move(str(f), str(dest))
                self.organizer.manifest.record("move_file", f, dest)
        
        return self._process_directory(target_path, None, is_group_folder=True, item_id=item_id)
