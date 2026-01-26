import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, Any
from pathlib import Path
from src.batch.scraper import BatchMediaScraper

logger = logging.getLogger(__name__)

class JobManager:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=1)
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
                             media_type: Optional[str] = None,
                             tmdb_id: Optional[int] = None,
                             search_mode: str = "smart",
                             enable_fallback: bool = True):
        
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
                input_dir, config_path, workers, dry_run, inplace, copy, output_dir, use_local_nfo, extra_images, media_type, tmdb_id, search_mode, enable_fallback
            )
        except Exception as e:
            logger.error(f"JobManager Error: {e}")
        finally:
            self.is_running = False
            self.current_task = None
            logger.info("JobManager: Task finished")

    def _run_scraper_sync(self, input_dir: str, config_path: str, workers: int, dry_run: bool, inplace: bool, copy: bool, output_dir: Optional[str], use_local_nfo: bool, extra_images: bool, media_type: Optional[str], tmdb_id: Optional[int], search_mode: str, enable_fallback: bool):
        """
        Synchronous wrapper to run BatchMediaScraper
        """
        try:
            scraper = BatchMediaScraper(
                config_path=config_path,
                copy_files=copy,
                inplace_rename=inplace,
                output_dir=output_dir,
                multi_mode=True, # Always assume multi-mode for "Batch" unless specific ID overrides? Actually single mode logic is handled inside if needed, but BatchMediaScraper loop handles directories.
                media_type=media_type,
                tmdb_id=tmdb_id,
                search_mode=search_mode,
                enable_fallback=enable_fallback,
                max_workers=workers,
                dry_run=dry_run,
                use_local_nfo=use_local_nfo,
                extra_images=extra_images
            )
            # Store reference?
            scraper.run(input_dir)
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
