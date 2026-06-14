
import logging
import re
from pathlib import Path
from typing import List, Optional, Set
from src.core.filename_parser import FilenameParser
from src.core.nfo_parser import NfoParser
from src.core.path_filters import is_hidden_path

logger = logging.getLogger(__name__)

class MediaScanner:
    def __init__(self, media_type: Optional[str] = None, use_local_nfo: bool = False, tmdb_id: Optional[int] = None, exclude_dirs: Set[str] = None):
        self.media_type = media_type
        self.use_local_nfo = use_local_nfo
        self.global_tmdb_id = tmdb_id
        self.exclude_dirs = exclude_dirs or {'tv', 'movies', 'shows', 'films', 'series', 'output', 'extras', 'season', 'specials'}

    def scan_single(self, input_dir: Path) -> List[dict]:
        """Scan single directory mode."""
        if not self.has_processable_media(input_dir):
            logger.info(f"No media or NFO files found in {input_dir}. Skipping single-directory task.")
            return []
        # For single mode, we apply global ID if exists
        task = self._create_task_for_dir(input_dir, force_id=self.global_tmdb_id)
        return [task]

    def scan_multi(self, input_dir: Path) -> List[dict]:
        """Scan multi-directory mode."""
        # Check if input_dir ITSELF is a TV Show root (contains "Season X" or "Specials")
        # If so, treating it as a single task prevents loose files in this root from being processed separately.
        try:
            root_sub_dirs = [d.name.lower() for d in input_dir.iterdir() if d.is_dir()]
            is_show_root = any(re.match(r'^season\s*\d+$', d) or d == 'specials' for d in root_sub_dirs)
            
            if is_show_root:
                logger.info(f"Detected {input_dir.name} as Show Root (contains Season folders). Treating as single task.")
                # We use scan_single logic basically, treating this folder as the media item
                return [self._create_task_for_dir(input_dir, force_id=self.global_tmdb_id)]
        except Exception as e:
            logger.error(f"Error checking show root: {e}")

        tasks = []
        # Subdirectories
        for item in input_dir.iterdir():
            if not item.is_dir() or item.name.startswith('.'): continue
            
            name_lower = item.name.lower()
            if name_lower in self.exclude_dirs: continue
            
            # Check if this directory itself should be a task
            # If it contains "Season X" folders or "Specials", it's likely a TV show root
            sub_dirs = [d.name.lower() for d in item.iterdir() if d.is_dir()]
            has_seasons = any(re.match(r'^season\s*\d+$', d) or d == 'specials' for d in sub_dirs)
            
            if has_seasons:
                 # Found a TV show root, do not scan its seasons as separate tasks
                 tasks.append(self._create_task_for_dir(item, force_id=None))
                 continue

            # Exclude "Season XX" or "Specials" if they were loose in the current level
            if re.match(r'^season\s*\d+$', name_lower) or name_lower == 'specials':
                continue

            # Normal behavior: treat each subdirectory as a potential show/movie
            tasks.append(self._create_task_for_dir(item, force_id=None))
        
        # Loose files - Grouped by show name for parallelism
        loose = self._find_loose_files(input_dir)
        if loose:
            groups = {}
            quarantined = []
            for f in loose:
                parsed = FilenameParser.parse_media_filename(f.name)
                name = parsed.get("title")
                if not name or parsed.get("confidence") not in {"high", "medium"}:
                    quarantined.append({
                        "path": f,
                        "parse": parsed,
                        "reason": "Filename could not be parsed with sufficient confidence.",
                    })
                    continue
                group_key = FilenameParser.clean_show_name_for_search(str(name)).casefold()
                groups.setdefault(group_key, {"show_name": name, "files": [], "parses": []})
                groups[group_key]["files"].append(f)
                groups[group_key]["parses"].append(parsed)
            
            for group in groups.values():
                tasks.append({
                    "type": "loose_files",
                    "files": group["files"],
                    "show_name": group["show_name"],
                    "parses": group["parses"],
                    "base_dir": input_dir,
                })
            for item in quarantined:
                tasks.append({
                    "type": "quarantined",
                    "path": item["path"],
                    "parse": item["parse"],
                    "reason": item["reason"],
                })
        return tasks

    def _find_loose_files(self, dir_path: Path) -> List[Path]:
        sub_exts = {'.ass', '.srt', '.ssa', '.vtt', '.sub'}
        return [
            f for f in dir_path.iterdir() 
            if f.is_file()
            and not is_hidden_path(f)
            and (f.suffix.lower() in FilenameParser.VIDEO_EXTENSIONS or f.suffix.lower() in sub_exts)
        ]

    def has_processable_media(self, dir_path: Path) -> bool:
        media_exts = set(FilenameParser.VIDEO_EXTENSIONS) | {'.nfo'}
        try:
            return any(
                item.is_file()
                and not is_hidden_path(item)
                and item.suffix.lower() in media_exts
                for item in dir_path.rglob("*")
            )
        except OSError as e:
            logger.warning(f"Could not scan {dir_path} for media files: {e}")
            return False

    def _create_task_for_dir(self, dir_path: Path, force_id: Optional[int] = None) -> dict:
        tmdb_id = force_id
        media_type = self.media_type
        
        if self.use_local_nfo:
             # Strict matching for movies to avoid false positives
             strict = (self.media_type == "movie")
             # Try parse NFO metadata
             meta = NfoParser.extract_metadata_from_directory(str(dir_path), dir_path.name, strict_match=strict)
             
             # NFO takes HIGHEST priority if enabled
             if meta.get("tmdb_id"):
                 tmdb_id = meta["tmdb_id"]
                 logger.info(f"NFO: Found TMDB ID {tmdb_id} in {dir_path.name}")
             if meta.get("media_type"):
                 media_type = meta["media_type"]
                 logger.info(f"NFO: Detected media type '{media_type}' in {dir_path.name}")
        
        return {
            "type": "directory",
            "path": dir_path,
            "tmdb_id": tmdb_id,
            "media_type": media_type
        }
