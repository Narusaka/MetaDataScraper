import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, Any
from pathlib import Path
from src.batch.scraper import BatchMediaScraper

import threading

logger = logging.getLogger(__name__)

from src.core.filename_parser import FilenameParser

class JobManager:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="JobManager")
        self.current_task = None
        self.is_running = False
        self.pipeline = None 
        self.scraper = None
        self.stop_signal = threading.Event()

    async def start_batch_scan(self, 
                             input_dir: str, 
                             config_path: str = "config/config.yaml",
                             workers: int = 4,
                             dry_run: bool = True,
                             inplace: bool = False,
                             copy: bool = False,
                             output_dir: Optional[str] = None,
                             use_local_nfo: bool = False,
                             extra_images: bool = False,
                             media_type: Optional[str] = None,
                             tmdb_id: Optional[int] = None,
                             search_mode: str = "smart",
                             enable_fallback: bool = True,
                             multi_mode: Optional[bool] = None,
                             fresh: bool = False,
                             enable_organize: bool = False,
                             overwrite_images: bool = False,
                             rename_parent_dir: bool = False):
        
        if self.is_running:
            raise Exception("A task is already running")

        self.is_running = True
        self.stop_signal.clear() # Reset stop signal
        logger.info(f"JobManager: Starting batch scan for {input_dir}")
        
        loop = asyncio.get_running_loop()
        
        try:
            await loop.run_in_executor(
                self.executor, 
                self._run_scraper_sync,
                input_dir, config_path, workers, dry_run, inplace, copy, output_dir, use_local_nfo, extra_images, media_type, tmdb_id, search_mode, enable_fallback, multi_mode, fresh, enable_organize, overwrite_images, rename_parent_dir
            )
        except Exception as e:
            logger.error(f"JobManager Error: {e}")
        finally:
            self.is_running = False
            self.current_task = None
            self.stop_signal.clear()
            logger.info("JobManager: Task finished")

    def _run_scraper_sync(self, input_dir: str, config_path: str, workers: int, dry_run: bool, inplace: bool, copy: bool, output_dir: Optional[str], use_local_nfo: bool, extra_images: bool, media_type: Optional[str], tmdb_id: Optional[int], search_mode: str, enable_fallback: bool, multi_mode: Optional[bool], fresh: bool, enable_organize: bool, overwrite_images: bool, rename_parent_dir: bool):
        """
        Synchronous wrapper to run BatchMediaScraper
        """
        try:
            if self.stop_signal.is_set():
                 logger.warning("JobManager: Task aborted before start.")
                 return

            should_multi = True
            
            # --- Auto-Detection Logic ---
            if multi_mode is not None:
                should_multi = multi_mode
            elif tmdb_id is not None:
                should_multi = False
            else:
                try:
                    p = Path(input_dir)
                    video_file_count = 0
                    has_subdirs = False
                    has_season_dirs = False
                    import re
                    
                    if p.exists() and p.is_dir():
                        ignored_dirs = {'extras', 'specials', 'featurettes', 'metadata', 'images', 'subs', 'subtitles'}
                        
                        for item in p.iterdir():
                            if self.stop_signal.is_set(): # Early exit during scan
                                logger.warning("JobManager: Task aborted during pre-scan.")
                                return

                            if item.name.startswith('.'): continue
                            
                            if item.is_dir():
                                name_lower = item.name.lower()
                                if name_lower in ignored_dirs: continue
                                if re.match(r'^season\s*\d+$', name_lower):
                                    has_season_dirs = True
                                else:
                                    has_subdirs = True
                            elif item.is_file() and item.suffix.lower() in FilenameParser.VIDEO_EXTENSIONS:
                                video_file_count += 1
                        
                        if has_season_dirs:
                            logger.info("Auto-detect: Season folders found -> Using SINGLE Mode")
                            should_multi = False
                        elif video_file_count == 1 and not has_subdirs:
                            logger.info("Auto-detect: One loose video file -> Using SINGLE Mode")
                            should_multi = False
                        elif video_file_count > 1 and not has_subdirs:
                            logger.info(f"Auto-detect: {video_file_count} loose video files found -> Using BATCH loose-file mode")
                            should_multi = True
                        else:
                            should_multi = True
                except Exception as e:
                    logger.warning(f"Auto-detect failed, defaulting to Multi: {e}")
                    should_multi = True
            
            if self.stop_signal.is_set():
                 logger.warning("JobManager: Task aborted before scraper init.")
                 return

            import time
            from src.server.stats_manager import stats_manager
            
            start_time = time.time()
            scraper = BatchMediaScraper(
                config_path=config_path,
                copy_files=copy,
                inplace_rename=inplace,
                output_dir=output_dir,
                multi_mode=should_multi, 
                media_type=media_type,
                tmdb_id=tmdb_id,
                search_mode=search_mode,
                enable_fallback=enable_fallback,
                max_workers=workers,
                dry_run=dry_run,
                use_local_nfo=use_local_nfo,
                extra_images=extra_images,
                fresh=fresh,
                enable_organize=enable_organize,
                overwrite_images=overwrite_images,
                rename_parent_dir=rename_parent_dir
            )
            self.scraper = scraper 
            
            # Check signal again just in case Stop was pressed during init
            if self.stop_signal.is_set():
                logger.warning("JobManager: Task aborted immediately after init.")
                scraper.stop() # Ensure internal cleanup if needed
                return

            results = scraper.run(input_dir)
            self.scraper = None
            
            duration = time.time() - start_time
            if results and not dry_run:
                stats_manager.record_task(
                    input_dir=input_dir,
                    total=results.get("total", 0),
                    successful=results.get("completed", 0),
                    failed=results.get("failed", 0),
                    duration=duration
                )
        except Exception as e:
            logger.exception(f"Scraper Failed: {e}")
            import traceback
            traceback.print_exc()

    def stop_task(self):
        """Signals the active scraper to stop."""
        logger.warning("JobManager: Stop signal received.")
        self.stop_signal.set() # Set the flag immediately
        
        if self.scraper:
            logger.warning("JobManager: Stopping active scraper instance...")
            self.scraper.stop()
        else:
            logger.warning("JobManager: No active scraper instance yet (maybe initializing). Signal set.")

job_manager = JobManager()
