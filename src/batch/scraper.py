
import os
import shutil
import logging
import yaml
import traceback
from pathlib import Path
from typing import Optional, List
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.pipeline.pipeline import MediaPipeline
from src.core.filename_parser import FilenameParser
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
                 dry_run: bool = False):
        
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
        self.max_workers = int(os.getenv("MAX_WORKERS", str(max_workers)))
        self.dry_run = dry_run
        
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
            copy_files=copy_files
        )

    def _load_config(self, path: str) -> dict:
        p = Path(path)
        c = {}
        if p.exists():
            with open(p, 'r') as f:
                c = yaml.safe_load(f)
                logger.info(f"Loaded config from {path}")
        
        # Inject Secrets from Environment
        self._inject_env(c, "TMDB_API_KEY", ["tmdb", "api_key"])
        self._inject_env(c, "OMDB_API_KEY", ["omdb", "api_key"])
        self._inject_env(c, "GOOGLE_API_KEY", ["google", "api_key"])
        self._inject_env(c, "GOOGLE_SEARCH_ENGINE_ID", ["google", "search_engine_id"])
        self._inject_env(c, "MODEL_API_KEY", ["model", "api_key"])
        self._inject_env(c, "MODEL_BASE_URL", ["model", "base_url"])
        
        return c

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
            logger.error(f"Input directory does not exist: {input_dir}")
            return
            
        logger.info("🚀 Starting Batch Scraper")
        logger.info(f"   Input: {input_dir}")
        logger.info(f"   Mode: {'Multi-directory' if self.multi_mode else 'Single directory'}")
        
        # Initialize Pipeline
        if not self.pipeline:
             self.pipeline = MediaPipeline(
                 self.config, 
                 quiet_google=True, 
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
        else:
             tasks = self.scanner.scan_single(root_path)

        self._execute_tasks(tasks)

    def _execute_tasks(self, tasks: List[dict]):
        if not tasks:
            logger.info("No tasks found.")
            return

        logger.info(f"Found {len(tasks)} tasks to process with {self.max_workers} workers")

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_task = {executor.submit(self._process_task, task): task for task in tasks}
            
            try:
                completed = 0
                failed = 0
                for future in as_completed(future_to_task):
                    if future.result(): completed += 1
                    else: failed += 1
                logger.info(f"Batch processing finished: {completed}/{len(tasks)} successful, {failed} failed")
            except KeyboardInterrupt:
                logger.warning("\n🛑 Stopping workers... (Ctrl+C pressed)")
                executor.shutdown(wait=False, cancel_futures=True)

    def _process_task(self, task: dict) -> bool:
        if task["type"] == "directory":
            return self._process_directory(task["path"], task["tmdb_id"])
        elif task["type"] == "loose_files":
            return self._process_loose_files(task["files"], task["base_dir"])
        return False

    def _process_directory(self, dir_path: Path, tmdb_id: Optional[int]) -> bool:
        show_name = dir_path.name
        
        if self.dry_run:
            logger.info(f"[DRY RUN] Would process directory: {dir_path}")
            return True

        query = "" if tmdb_id else FilenameParser.clean_show_name_for_search(show_name)
        
        # Detection logic
        current_media_type = self.media_type or MediaTypeDetector.detect(dir_path)
        
        logger.info(f"Processing: {show_name} (ID: {tmdb_id}, Query: {query}, Type: {current_media_type})")

        target_output_dir = str(dir_path) if self.inplace_rename else self.output_dir

        input_data = {
            "media_type": current_media_type,
            "media_type_forced": self.media_type is not None, 
            "query": query,
            "output_dir": target_output_dir,
            "verbose": False,
            "quiet": True,
            "aid_search": True,
            "inplace": self.inplace_rename,
            "extra_images": self.extra_images,
            "tmdb_only": self.search_mode == "tmdb_only",
            "fallback_on_fail": self.enable_fallback
        }
        if tmdb_id:
            input_data["tmdb_id"] = tmdb_id
            input_data["media_type_forced"] = True

        try:
            result = self.pipeline.run(input_data)
            if result.get("status") == "completed":
                self.organizer.organize(dir_path, result, configured_media_type=current_media_type)
                return True
            else:
                logger.error(f"Metadata generation failed for {show_name}: {result.get('error')}")
                return False
        except Exception as e:
            logger.error(f"Error processing {show_name}: {e}")
            logger.error(traceback.format_exc())
            return False

    def _process_loose_files(self, files: List[Path], base_dir: Path) -> bool:
        # Grouping logic... 
        groups = {}
        for f in files:
            name = FilenameParser.extract_show_name(f.name)
            if not name: continue
            if name not in groups: groups[name] = []
            groups[name].append(f)
            
        logger.info(f"Processing split files: found {len(groups)} groups")
        
        if self.dry_run: return True
        
        for show_name, group_files in groups.items():
             safe_name = FilenameParser.clean_show_name_for_search(show_name)
             new_dir = base_dir / safe_name
             if not new_dir.exists(): new_dir.mkdir(exist_ok=True)
             
             for f in group_files:
                 if f.parent != new_dir:
                     shutil.move(str(f), str(new_dir / f.name))
             
             self._process_directory(new_dir, None)
        return True
