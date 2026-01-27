
import os
import shutil
import logging
from pathlib import Path
from src.batch.scraper import BatchMediaScraper
from src.core.filename_parser import FilenameParser

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_sibling_creation():
    # Setup Test Environment
    base_dir = Path("dist/test_env")
    if base_dir.exists(): shutil.rmtree(base_dir)
    base_dir.mkdir(parents=True)

    # 1. Create a "Messy" Download Folder (No Season folders)
    # Name: "My.Test.Show.2024.1080p"
    # Content: video file
    show_name_raw = "My.Test.Show.2024.1080p"
    source_dir = base_dir / show_name_raw
    source_dir.mkdir()
    
    video_file = source_dir / "My.Test.Show.S01E01.mkv"
    video_file.touch()
    
    logger.info(f"Created mocked source: {source_dir}")

    # 2. Configure Scraper for "Execute Plan" (dry_run=False, inplace=True)
    # We expect it to NOT rename 'source_dir', but create 'My Test Show (2024)' sibling.
    
    scraper = BatchMediaScraper(
        config_path="config/config.yaml", # Assumes mock or real config exists, might need to mock config loading if it fails
        inplace_rename=True,
        media_type="tv", 
        dry_run=False, # EXECUTE MODE
        multi_mode=False
    )
    
    # Mock the pipeline to return a success result without actually calling APIs
    class MockPipeline:
        def __init__(self, *args, **kwargs):
            self.artwork = None
        def run(self, input_data):
            # Check if input_data correctly accepted audit_only=False
            if input_data.get("audit_only") is True:
                logger.error("❌ FAILURE: Pipeline received audit_only=True despite dry_run=False!")
            else:
                logger.info("✅ SUCCESS: Pipeline received audit_only=False")

            return {
                "status": "completed",
                "normalized": {
                    "title": "My Test Show",
                    "year": 2024,
                    "media_type": "tv"
                },
                "source_data": {
                    "translated_episodes": [
                        {"season_number": 1, "episode_number": 1, "name": "Pilot", "still_path": None}
                    ]
                },
                "nfo": {"episode_nfos": {}}
            }
            
    scraper.pipeline = MockPipeline()
    # Inject pipeline into organizer so it doesn't crash on artwork check
    scraper.organizer.pipeline = scraper.pipeline 

    # 3. Run
    logger.info("Running Scraper...")
    scraper.run(str(source_dir))

    # 4. Verify Results
    expected_sibling = base_dir / "My Test Show (2024)"
    expected_video_in_sibling = expected_sibling / "Season 01" / "My Test Show - S01E01 - Pilot.mkv"
    
    if expected_sibling.exists():
        logger.info(f"✅ Sibling Directory Created: {expected_sibling}")
        if expected_video_in_sibling.exists():
            logger.info("✅ Video File Moved correctly!")
        else:
            logger.error(f"❌ Video file NOT found in {expected_video_in_sibling}")
            # List what is there
            logger.info(f"Contents of {expected_sibling}: {list(expected_sibling.rglob('*'))}")
    else:
        logger.error(f"❌ Sibling Directory NOT Created. Left with: {list(base_dir.iterdir())}")

if __name__ == "__main__":
    try:
        test_sibling_creation()
    except Exception as e:
        logger.error(f"Test Crashed: {e}")
        import traceback
        traceback.print_exc()
