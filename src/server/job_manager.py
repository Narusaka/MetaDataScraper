import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, Any
from pathlib import Path
from src.batch.scraper import BatchMediaScraper

logger = logging.getLogger(__name__)

class JobManager:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="JobManager")
        self.current_task = None
        self.is_running = False
        self.pipeline = None # Holds reference to active pipeline if needed

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
                             fresh: bool = False):
        
        if self.is_running:
            raise Exception("A task is already running")

        self.is_running = True
        logger.info(f"JobManager: Starting batch scan for {input_dir}")
        
        loop = asyncio.get_running_loop()
        
        # Run in a separate thread to avoid blocking the async loop
        try:
            await loop.run_in_executor(
                self.executor, 
                self._run_scraper_sync,
                input_dir, config_path, workers, dry_run, inplace, copy, output_dir, use_local_nfo, extra_images, media_type, tmdb_id, search_mode, enable_fallback, multi_mode, fresh
            )
        except Exception as e:
            logger.error(f"JobManager Error: {e}")
        finally:
            self.is_running = False
            self.current_task = None
            logger.info("JobManager: Task finished")

    def _run_scraper_sync(self, input_dir: str, config_path: str, workers: int, dry_run: bool, inplace: bool, copy: bool, output_dir: Optional[str], use_local_nfo: bool, extra_images: bool, media_type: Optional[str], tmdb_id: Optional[int], search_mode: str, enable_fallback: bool, multi_mode: Optional[bool], fresh: bool):
        """
        Synchronous wrapper to run BatchMediaScraper
        """
        try:
            should_multi = True
            
            if multi_mode is not None:
                should_multi = multi_mode
            elif tmdb_id is not None:
                # If a TMDB ID is provided, we are definitely targeting a specific item
                should_multi = False
            else:
                # Auto-detect based on directory content
                try:
                    p = Path(input_dir)
                    has_video_files = False
                    has_subdirs = False
                    has_season_dirs = False
                    import re
                    
                    if p.exists() and p.is_dir():
                        # Smarter detection logic
                        ignored_dirs = {'extras', 'specials', 'featurettes', 'metadata', 'images', 'subs', 'subtitles'}
                        
                        for item in p.iterdir():
                            if item.name.startswith('.'): continue
                            
                            if item.is_dir():
                                name_lower = item.name.lower()
                                if name_lower in ignored_dirs: continue
                                
                                # Check for Season folder pattern
                                if re.match(r'^season\s*\d+$', name_lower):
                                    has_season_dirs = True
                                else:
                                    has_subdirs = True # Potential other show folder
                                    
                            elif item.is_file() and item.suffix.lower() in FilenameParser.VIDEO_EXTENSIONS:
                                has_video_files = True
                        
                        # Decision Matrix:
                        # 1. If it has Season folders -> It's a Show Root -> SINGLE MODE
                        # 2. If it has NO subdirs (only videos) -> It's a flattened Show/Movie -> SINGLE MODE
                        # 3. If it has 'other' subdirs (likely multiple shows) -> MULTI MODE
                        
                        if has_season_dirs:
                            logger.info("Auto-detect: Season folders found -> Using SINGLE Mode (Show Root)")
                            should_multi = False
                        elif has_video_files and not has_subdirs:
                            logger.info("Auto-detect: Video files found without other show directories -> Using SINGLE Mode")
                            should_multi = False
                        else:
                            logger.info(f"Auto-detect: Multiple show directories likely ({has_subdirs}) -> Using MULTI Mode")
                            should_multi = True
                except Exception as e:
                    logger.warning(f"Auto-detect failed, defaulting to Multi: {e}")
                    should_multi = True
            
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
                fresh=fresh
            )
            results = scraper.run(input_dir)
            
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
            logger.error(f"Scraper Failed: {e}")
            import traceback
            traceback.print_exc()

    def stop_task(self):
        # Implementation depends on how we can kill the thread or signal the scraper
        # For now, simplistic not-supported, or we rely on scraper checking a flag
        logger.warning("Stop task not fully implemented yet")
        pass

job_manager = JobManager()
