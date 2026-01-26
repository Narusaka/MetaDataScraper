
import logging
import re
from pathlib import Path
from typing import List, Optional, Set
from src.core.filename_parser import FilenameParser
from src.core.nfo_parser import NfoParser

logger = logging.getLogger(__name__)

class MediaScanner:
    def __init__(self, media_type: Optional[str] = None, use_local_nfo: bool = False, tmdb_id: Optional[int] = None, exclude_dirs: Set[str] = None):
        self.media_type = media_type
        self.use_local_nfo = use_local_nfo
        self.global_tmdb_id = tmdb_id
        self.exclude_dirs = exclude_dirs or {'tv', 'movies', 'shows', 'films', 'series', 'output', 'extras', 'season', 'specials'}

    def scan_single(self, input_dir: Path) -> List[dict]:
        """Scan single directory mode."""
        # For single mode, we apply global ID if exists
        task = self._create_task_for_dir(input_dir, force_id=self.global_tmdb_id)
        return [task]

    def scan_multi(self, input_dir: Path) -> List[dict]:
        """Scan multi-directory mode."""
        tasks = []
        # Subdirectories
        for item in input_dir.iterdir():
             if not item.is_dir() or item.name.startswith('.'): continue
             
             name_lower = item.name.lower()
             if name_lower in self.exclude_dirs: continue
             
             # Exclude "Season XX" or "Specials" directories usually found inside shows
             if re.match(r'^season\s*\d+$', name_lower) or name_lower == 'specials':
                 continue

             # In multi mode, global ID does not apply to subdirs
             tasks.append(self._create_task_for_dir(item, force_id=None))
        
        # Loose files
        loose = self._find_loose_files(input_dir)
        if loose:
             tasks.append({
                 "type": "loose_files",
                 "files": loose,
                 "base_dir": input_dir
             })
        return tasks

    def _find_loose_files(self, dir_path: Path) -> List[Path]:
        return [
            f for f in dir_path.iterdir() 
            if f.is_file() and f.suffix.lower() in FilenameParser.VIDEO_EXTENSIONS
        ]

    def _create_task_for_dir(self, dir_path: Path, force_id: Optional[int] = None) -> dict:
        tmdb_id = force_id
        
        if not tmdb_id and self.use_local_nfo:
             # Strict matching for movies to avoid false positives
             strict = (self.media_type == "movie")
             # Try parse NFO
             tmdb_id = NfoParser.extract_tmdb_id_from_directory(str(dir_path), dir_path.name, strict_match=strict)
        
        return {
            "type": "directory",
            "path": dir_path,
            "tmdb_id": tmdb_id
        }
