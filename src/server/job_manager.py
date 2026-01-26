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
                             inplace: bool = False):
        
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
                input_dir, config_path, workers, dry_run, inplace
            )
        except Exception as e:
            logger.error(f"JobManager Error: {e}")
        finally:
            self.is_running = False
            self.current_task = None
            logger.info("JobManager: Task finished")

    def _run_scraper_sync(self, input_dir: str, config_path: str, workers: int, dry_run: bool, inplace: bool):
        """
        Synchronous wrapper to run BatchMediaScraper
        """
        try:
            scraper = BatchMediaScraper(
                config_path=config_path,
                copy_files=False, # Web Mode defaults
                inplace_rename=inplace,
                output_dir=None,
                multi_mode=True, # Always assume multi-mode for "Batch"
                media_type=None,
                max_workers=workers,
                dry_run=dry_run
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
