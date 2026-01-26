
import re
from pathlib import Path
from typing import Optional, List, Tuple

class NfoParser:
    """Helper class for parsing NFO files."""

    @staticmethod
    def extract_tmdb_id(nfo_content: str) -> Optional[int]:
        """Extract TMDB ID from NFO content string."""
        match = re.search(r'<tmdbid>(\d+)</tmdbid>', nfo_content, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def find_tmdb_id_in_nfo_file(nfo_path: Path) -> Optional[int]:
        """Read NFO file and extract TMDB ID."""
        try:
            content = nfo_path.read_text(encoding='utf-8')
            return NfoParser.extract_tmdb_id(content)
        except Exception as e:
            print(f"Warning: Could not parse {nfo_path.name}: {e}")
            return None

    @staticmethod
    def extract_tmdb_id_from_directory(show_dir: str, movie_title: Optional[str] = None, strict_match: bool = False) -> Optional[int]:
        """
        Extract TMDB ID from nfo file in the show directory.
        
        Args:
            show_dir: Directory path to search
            movie_title: Movie title for strict name matching
            strict_match: If True, prioritized matching NFOs containing title/folder name
        """
        show_path = Path(show_dir)
        folder_name = show_path.name
        match_title = movie_title or folder_name

        if strict_match and match_title:
            # Strict mode: Look for NFO files containing the title
            for nfo_file in show_path.glob("*.nfo"):
                try:
                    content = nfo_file.read_text(encoding='utf-8')
                    if match_title.lower() in content.lower():
                        tmdb_id = NfoParser.extract_tmdb_id(content)
                        if tmdb_id:
                            return tmdb_id
                except Exception:
                    continue

        # Priority 1: tvshow.nfo
        tvshow_nfo = show_path / "tvshow.nfo"
        if tvshow_nfo.exists():
            tmdb_id = NfoParser.find_tmdb_id_in_nfo_file(tvshow_nfo)
            if tmdb_id:
                return tmdb_id

        # Priority 2: Any other .nfo file
        for nfo_file in show_path.glob("*.nfo"):
            if nfo_file.name != "tvshow.nfo":
                tmdb_id = NfoParser.find_tmdb_id_in_nfo_file(nfo_file)
                if tmdb_id:
                    return tmdb_id

        return None

    @staticmethod
    def find_all_nfo_files_with_tmdb_id(show_dir: str) -> List[Tuple[int, str]]:
        """Find all NFO files in directory that contain TMDB IDs."""
        show_path = Path(show_dir)
        results = []

        for nfo_file in show_path.glob("*.nfo"):
            tmdb_id = NfoParser.find_tmdb_id_in_nfo_file(nfo_file)
            if tmdb_id:
                results.append((tmdb_id, str(nfo_file)))

        return results
