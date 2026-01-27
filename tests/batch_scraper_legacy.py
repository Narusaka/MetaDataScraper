#!/usr/bin/env python3
"""
Batch Media Scraper for TV Shows and Episodes

This script scans a directory for TV shows and episodes, organizes them properly,
and generates metadata using the Media Metadata Agent.

Features:
- Handles organized TV show folders (subdirectories)
- Handles scattered episode files in the root directory
- Renames and moves files to proper Kodi/Emby structure
- Generates NFO files, downloads images, and organizes subtitles
"""

import os
import re
import shutil
import argparse
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Set
import json
import sys

# Add src to path
script_dir = Path(__file__).parent
src_dir = script_dir / "src"
sys.path.insert(0, str(src_dir))

from src.app.graph import MediaMetadataGraph
from src.app.state import GraphState


class BatchMediaScraper:
    """Batch scraper for organizing and metadata generation."""

    def __init__(self, config_path: Optional[str] = None, copy_files: bool = False, inplace_rename: bool = False, output_dir: Optional[str] = None, multi_mode: bool = False, tmdb_id: Optional[int] = None, use_local_nfo: bool = False, extra_images: bool = False, media_type: str = "tv"):
        """Initialize the batch scraper.

        Args:
            config_path: Path to configuration file
            copy_files: Whether to copy files instead of moving
            inplace_rename: Whether to use in-place renaming mode
            output_dir: Output directory (None means in-place mode)
            multi_mode: Whether to use multi-mode (process all subdirs/files)
            tmdb_id: TMDB ID for direct lookup (skips name parsing)
            use_local_nfo: Whether to extract TMDB ID from tvshow.nfo file
        """
        """Initialize the batch scraper."""
        self.config = self.load_config(config_path)
        self.copy_files = copy_files
        self.inplace_rename = inplace_rename
        self.output_dir = output_dir
        self.multi_mode = multi_mode
        self.tmdb_id = tmdb_id
        self.use_local_nfo = use_local_nfo
        self.extra_images = extra_images
        self.media_type = media_type
        self.graph_builder = MediaMetadataGraph(self.config, extra_images=extra_images)
        self.workflow = self.graph_builder.create_graph()
        self.app = self.workflow.compile()

        # Video file extensions
        self.video_extensions = {
            # Common formats
            '.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm',
            # Additional formats
            '.rmvb', '.rm', '.asf', '.mpg', '.mpeg', '.m4v', '.3gp',
            '.m2ts', '.mts', '.vob', '.ogv', '.divx', '.xvid', '.f4v',
            '.mxf', '.r3d', '.braw', '.dng', '.mxf', '.m2v', '.ts'
        }
        # Subtitle extensions
        self.subtitle_extensions = {'.ass', '.srt', '.ssa', '.sub', '.vtt'}

        # Directories to exclude from processing
        self.exclude_dirs = {'tv', 'movies', 'shows', 'films', 'series', 'output'}

    def load_config(self, config_path: Optional[str] = None) -> Dict:
        """Load configuration file."""
        if not config_path:
            candidates = [
                "config.yaml", "config.yml", "config.example.yaml", "model_config.json"
            ]
            for candidate in candidates:
                if os.path.exists(candidate):
                    config_path = candidate
                    break

        if not config_path:
            # Create default config if no config file found
            return self.create_default_config()

        # Try to load as JSON first
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                if config_path.endswith('.json') and config_path == "model_config.json":
                    # model_config.json only contains model config, merge with defaults
                    model_config = json.load(f)
                    default_config = self.create_default_config()
                    default_config["model"] = model_config.get("default", default_config["model"])
                    return default_config
                else:
                    return json.load(f)
        except json.JSONDecodeError:
            # Try YAML if available
            try:
                import yaml
                with open(config_path, 'r', encoding='utf-8') as f:
                    return yaml.safe_load(f)
            except ImportError:
                raise ImportError("Configuration file is not valid JSON and PyYAML is not available")
            except Exception as e:
                raise ValueError(f"Could not parse config file {config_path}: {e}")

    def create_default_config(self) -> Dict:
        """Create default configuration."""
        return {
            "proxy": {
                "http": "http://127.0.0.1:7897",
                "https": "http://127.0.0.1:7897"
            },
            "tmdb": {
                "base_url": "https://api.themoviedb.org/3",
                "api_key": os.getenv("TMDB_API_KEY", "d17bc8d9f1f1fa66368b54d95a296235")
            },
            "omdb": {
                "api_key": os.getenv("OMDB_API_KEY", "330effac")
            },
            "google": {
                "api_key": "",
                "search_engine_id": ""
            },
            "model": {
                "base_url": "http://127.0.0.1:32668/v1",
                "api_key": "EMPTY",
                "model": "local-4b",
                "max_retries": 2,
                "temperature": 0.2,
                "top_p": 0.95,
                "top_k": 20,
                "min_p": 0,
                "max_tokens": 8000
            }
        }

    def scan_directory(self, root_path: str) -> Tuple[List[str], List[str]]:
        """
        Scan directory for organized TV shows and scattered episodes.

        Returns:
            Tuple of (organized_shows, scattered_episodes)
        """
        organized_shows = []
        scattered_episodes = []

        root_dir = Path(root_path)

        if not root_dir.exists():
            raise FileNotFoundError(f"Directory not found: {root_dir}")

        # Scan all items in the directory
        for item in root_dir.iterdir():
            if item.is_dir():
                # Skip excluded directories
                if item.name.lower() in self.exclude_dirs:
                    print(f"   ⏭️  Skipping excluded directory: {item.name}")
                    continue

                # Check if this is an organized TV show directory
                if self._is_organized_tv_show(item):
                    organized_shows.append(str(item))
                else:
                    # Check for video files in subdirectories
                    video_files = self._find_video_files(item)
                    if video_files:
                        # This might be a partially organized show
                        organized_shows.append(str(item))
            elif item.is_file():
                # Check if this is a video file
                if item.suffix.lower() in self.video_extensions:
                    scattered_episodes.append(str(item))
                # Check if this is a subtitle file
                elif item.suffix.lower() in self.subtitle_extensions:
                    scattered_episodes.append(str(item))

        return organized_shows, scattered_episodes

    def _is_organized_tv_show(self, directory: Path) -> bool:
        """Check if a directory contains an organized TV show."""
        # Skip if this looks like an output directory (has TV/Movies subdirs or tvshow.nfo)
        if self._is_output_directory(directory):
            return False

        # In in-place mode, only consider the input directory itself as a show
        # Don't treat Season subdirectories as separate shows
        if self.inplace_rename:
            # For in-place mode, we only want to process the input directory
            # Season subdirectories should not be treated as separate shows
            return False

        # Look for multiple video files or season folders
        video_count = 0
        season_folders = 0

        for item in directory.iterdir():
            if item.is_file() and item.suffix.lower() in self.video_extensions:
                video_count += 1
            elif item.is_dir() and re.match(r'season\s*\d+', item.name, re.IGNORECASE):
                season_folders += 1

        # Consider it organized if it has multiple videos or season folders
        return video_count > 1 or season_folders > 0

    def _is_output_directory(self, directory: Path) -> bool:
        """Check if a directory appears to be an output/organized directory."""
        # Check for signs of organized media structure
        has_tv_dir = any(item.is_dir() and item.name.lower() in ['tv', 'movies', 'shows'] for item in directory.iterdir())
        has_nfo_files = any(item.is_file() and item.suffix.lower() == '.nfo' for item in directory.iterdir())

        # Check if directory name suggests it's output (like "TV", "Movies")
        output_names = ['tv', 'movies', 'shows', 'films', 'series']
        is_output_name = directory.name.lower() in output_names

        return has_tv_dir or (has_nfo_files and is_output_name)

    def _find_video_files(self, directory: Path) -> List[Path]:
        """Find all video files in a directory."""
        video_files = []
        for item in directory.rglob('*'):
            if item.is_file() and item.suffix.lower() in self.video_extensions:
                video_files.append(item)
        return video_files

    def _detect_subtitle_language(self, filename: str) -> str:
        """Detect subtitle language based on filename keywords.
        
        Returns:
            Language code ('zh', 'en', 'ja') or empty string if no indicators found
        """
        filename_lower = filename.lower()
        
        # Chinese indicators
        chinese_indicators = [
            '简中', '简体中文', '简体', '繁中', '繁体中文', '繁体', 
            'zh', 'chn', 'chinese', '中文', '中字', 'simplified', 
            'traditional', 'sc', 'tc', 'zn'
        ]
        
        # English indicators  
        english_indicators = [
            'en', 'eng', 'english', '英文', '英语', '英字',
            'us', 'uk', 'american', 'british'
        ]
        
        # Japanese indicators
        japanese_indicators = [
            'jp', 'jpn', 'japanese', 'ja', '日文', '日语', '日字',
            'nihongo', 'にほんご', 'ひらがな', 'カタカナ'
        ]
        
        if any(indicator in filename_lower for indicator in chinese_indicators):
            return 'zh'
        elif any(indicator in filename_lower for indicator in english_indicators):
            return 'en'
        elif any(indicator in filename_lower for indicator in japanese_indicators):
            return 'ja'
        
        return ''  # No language indicators found

    def _get_subtitle_language_suffix(self, filename: str) -> str:
        """Get appropriate language suffix for subtitle file based on content detection."""
        language = self._detect_subtitle_language(filename)
        if language:
            return f'.{language}'
        # Default to no suffix if no language indicators found
        return ''

    def _parse_episode_info(self, filename: str) -> Optional[Tuple[int, int]]:
        """Parse season and episode numbers from filename.

        Returns:
            Tuple of (season_number, episode_number) or None if not found
        """
        # Common patterns for episode information
        patterns = [
            # S01E01 format
            r'S(\d{1,2})E(\d{1,2})',
            # 01x01 format
            r'(\d{1,2})x(\d{1,2})',
            # Season 01 Episode 01
            r'Season\s*(\d{1,2}).*Episode\s*(\d{1,2})',
            # Episode 01 (season from context)
            r'Episode\s*(\d{1,2})',
        ]

        for pattern in patterns:
            match = re.search(pattern, filename, re.IGNORECASE)
            if match:
                if len(match.groups()) == 2:
                    # S01E01 or 01x01 format
                    season = int(match.group(1))
                    episode = int(match.group(2))
                    return (season, episode)
                elif len(match.groups()) == 1 and 'Episode' in pattern:
                    # Episode only, assume season 1
                    episode = int(match.group(1))
                    return (1, episode)

        # Try to find numbers that might be episode numbers
        # Look for patterns like .S01E01. or -01-
        alt_patterns = [
            r'\.S(\d{1,2})E(\d{1,2})\.',
            r'-S(\d{1,2})E(\d{1,2})-',
            r'\.(\d{1,2})x(\d{1,2})\.',
            r'-(\d{1,2})x(\d{1,2})-',
        ]

        for pattern in alt_patterns:
            match = re.search(pattern, filename, re.IGNORECASE)
            if match:
                season = int(match.group(1))
                episode = int(match.group(2))
                return (season, episode)

        return None

    def process_organized_show(self, show_dir: str, output_base: str) -> Dict:
        """Process an organized TV show directory."""
        show_path = Path(show_dir)
        show_name = show_path.name

        # Check if we should extract TMDB ID from local NFO
        local_tmdb_id = None
        if self.use_local_nfo and self.tmdb_id is None:
            local_tmdb_id = self._extract_tmdb_id_from_nfo(show_dir)
            if local_tmdb_id:
                print(f"   📝 Extracted TMDB ID from local NFO: {local_tmdb_id}")

        # Clean the show name for search - this becomes the query parameter
        search_query = self._clean_show_name_for_search(show_name) if local_tmdb_id is None else ""

        print(f"🎬 Processing organized show: {show_name}")
        print(f"   🔍 Search query: '{search_query}'")

        # First generate metadata and folder structure for this show
        metadata_result = self._generate_show_metadata(search_query, output_base, local_tmdb_id)
        if not metadata_result:
            print(f"❌ Failed to generate metadata for: {show_name}")
            return {}

        print(f"✅ Successfully processed: {show_name}")

        # Now organize the actual files
        self._organize_show_files(show_path, metadata_result, output_base)

        return metadata_result.get("output", {})

    def process_scattered_episodes(self, episode_files: List[str], output_base: str) -> Dict:
        """Process scattered episode files."""
        if not episode_files:
            return {}

        print(f"📺 Processing {len(episode_files)} scattered episode files")

        # Group files by potential show names
        show_groups = self._group_scattered_files(episode_files)

        results = {}
        successful_groups = 0
        failed_groups = 0

        for show_name, files in show_groups.items():
            print(f"  📁 Processing show group: {show_name}")

            try:
                # Process each show group
                show_result = self._process_show_group(show_name, files, output_base)
                if show_result:
                    results[show_name] = show_result
                    successful_groups += 1
                    print(f"  ✅ Successfully processed: {show_name}")
                else:
                    failed_groups += 1
                    print(f"  ❌ Failed to process: {show_name}")
            except Exception as e:
                failed_groups += 1
                print(f"  ❌ Error processing show group {show_name}: {e}")

        print(f"  📊 Show groups summary: {successful_groups} successful, {failed_groups} failed")

        return results

    def _group_scattered_files(self, files: List[str]) -> Dict[str, List[str]]:
        """Group scattered files by potential show names."""
        show_groups = {}

        for file_path in files:
            file_name = Path(file_path).stem

            # Try to extract show name from filename
            show_name = self._extract_show_name_from_filename(file_name)

            if show_name not in show_groups:
                show_groups[show_name] = []

            show_groups[show_name].append(file_path)

        return show_groups

    def _clean_show_name_for_search(self, show_name: str) -> str:
        """Clean show name for search queries by removing years, episode info, etc."""
        # Remove year in parentheses
        show_name = re.sub(r'\s*\(\d{4}\)\s*', '', show_name)

        # Remove other common patterns that shouldn't be in search queries
        patterns = [
            r'\[.*?\]',           # [1080p], [ASS], etc.
            r'\b\d{4}\b',         # standalone years
            r'\d{3,4}p',          # 1080p, 720p
            r'BD|BDRip|WEB-DL|WEBRip|HDTV|BluRay',
            r'x264|x265|h264|h265',
        ]

        clean_name = show_name
        for pattern in patterns:
            clean_name = re.sub(pattern, '', clean_name, flags=re.IGNORECASE)

        # Clean up extra spaces and punctuation
        clean_name = re.sub(r'[._-]+', ' ', clean_name).strip()

        return clean_name

    def _extract_show_name_from_filename(self, filename: str) -> str:
        """Extract potential show name from filename."""
        # Try to find episode info and extract name before it
        match = re.search(r'S\d{1,2}E\d{1,2}', filename, re.IGNORECASE)
        if match:
            name = filename[:match.start()].strip()
            # Remove year in parentheses
            name = re.sub(r'\s*\(\d{4}\)\s*', '', name)
            # Clean trailing punctuation
            name = re.sub(r'[._\s]+$', '', name).strip()
            if len(name) > 1:
                return name

        # Fallback: extract from the beginning
        parts = re.split(r'[._\s]', filename)
        for part in parts:
            if part and len(part) > 1 and not part.isdigit() and part.lower() not in ['the', 'and', 'but', 'for', 'nor', 'yet', 'so']:
                return part.strip()

        return filename.split()[0] if filename.split() else filename

    def _extract_tmdb_id_from_nfo(self, show_dir: str, movie_title: Optional[str] = None, strict_match: bool = False) -> Optional[int]:
        """Extract TMDB ID from nfo file in the show directory.

        Args:
            show_dir: Directory path to search
            movie_title: Movie title for strict name matching (when strict_match=True)
            strict_match: If True, only look for NFO files containing movie_title or folder name

        Priority (when strict_match=False):
            1. tvshow.nfo
            2. Any other .nfo file

        Priority (when strict_match=True):
            1. Any .nfo file containing movie_title/folder name
            2. Fallback to regular priority if no strict match found
        """
        show_path = Path(show_dir)
        folder_name = show_path.name

        # Determine the title to match against
        match_title = movie_title or folder_name

        if strict_match and match_title:
            # Strict mode: Look for NFO files containing the title
            for nfo_file in show_path.glob("*.nfo"):
                try:
                    content = nfo_file.read_text(encoding='utf-8')
                    if match_title.lower() in content.lower():
                        match = re.search(r'<tmdbid>(\d+)</tmdbid>', content, re.IGNORECASE)
                        if match:
                            return int(match.group(1))
                except Exception as e:
                    print(f"Warning: Could not parse {nfo_file.name} in {show_dir}: {e}")

        # Fallback or regular mode: Standard priority
        # Priority 1: Look for tvshow.nfo
        tvshow_nfo = show_path / "tvshow.nfo"
        if tvshow_nfo.exists():
            try:
                content = tvshow_nfo.read_text(encoding='utf-8')
                match = re.search(r'<tmdbid>(\d+)</tmdbid>', content, re.IGNORECASE)
                if match:
                    return int(match.group(1))
            except Exception as e:
                print(f"Warning: Could not parse tvshow.nfo in {show_dir}: {e}")

        # Priority 2: Look for any other .nfo file
        for nfo_file in show_path.glob("*.nfo"):
            if nfo_file.name != "tvshow.nfo":  # Skip tvshow.nfo since we already checked it
                try:
                    content = nfo_file.read_text(encoding='utf-8')
                    match = re.search(r'<tmdbid>(\d+)</tmdbid>', content, re.IGNORECASE)
                    if match:
                        return int(match.group(1))
                except Exception as e:
                    print(f"Warning: Could not parse {nfo_file.name} in {show_dir}: {e}")

        return None

    def _find_all_nfo_files_with_tmdb_id(self, show_dir: str) -> List[Tuple[int, str]]:
        """Find all NFO files in the directory that contain TMDB IDs.
        Returns list of (tmdb_id, file_path) tuples.
        """
        show_path = Path(show_dir)
        results = []

        # Check all .nfo files
        for nfo_file in show_path.glob("*.nfo"):
            try:
                content = nfo_file.read_text(encoding='utf-8')
                match = re.search(r'<tmdbid>(\d+)</tmdbid>', content, re.IGNORECASE)
                if match:
                    tmdb_id = int(match.group(1))
                    results.append((tmdb_id, str(nfo_file)))
            except Exception as e:
                print(f"Warning: Could not parse {nfo_file.name} in {show_dir}: {e}")

        return results

    def _generate_show_metadata(self, show_name: str, output_base: str, tmdb_id: Optional[int] = None) -> Dict:
        """Generate complete metadata and folder structure for media."""
        input_data = {
            "media_type": self.media_type,
            "media_type_forced": self.media_type != "tv",  # If not default tv, force it
            "query": show_name,
            "output_dir": output_base,
            "verbose": False,
            "quiet": True,
            "aid_search": True
        }

        # Add tmdb_id if provided - this will trigger direct lookup in Media Metadata Agent
        if tmdb_id is not None:
            input_data["tmdb_id"] = tmdb_id

        initial_state = GraphState(
            input=input_data,
            search={},
            source_data={},
            normalized={},
            artwork={},
            nfo={},
            output={},
            errors={}
        )

        try:
            result = self.app.invoke(initial_state)
            if result.get("output", {}).get("status") == "completed":
                print(f"   🚀 Starting metadata processing...")
                print(f"   ✅ Metadata processing completed")
                return result
            else:
                print(f"   ❌ Failed to generate metadata")
                return {}
        except Exception as e:
            print(f"   ❌ Error during metadata generation: {e}")
            return {}

    def _process_show_group(self, show_name: str, files: List[str], output_base: str) -> Dict:
        """Process a group of files belonging to the same show."""
        # Separate video and subtitle files
        video_files = [f for f in files if Path(f).suffix.lower() in self.video_extensions]
        subtitle_files = [f for f in files if Path(f).suffix.lower() in self.subtitle_extensions]

        if not video_files:
            print(f"    ⚠️ No video files found for show: {show_name}")
            return {}

        # For scattered episodes, we'll need to process each episode individually
        # or try to get show-level metadata first
        print(f"    🎯 Found {len(video_files)} video files and {len(subtitle_files)} subtitle files")

        # Clean the show name for search
        search_query = self._clean_show_name_for_search(show_name)
        print(f"    🔍 Search query: '{search_query}'")

        # First generate metadata and folder structure for this show
        metadata_result = self._generate_show_metadata(search_query, output_base)
        if not metadata_result:
            print(f"    ❌ Failed to generate metadata for: {show_name}")
            return {}

        # Organize the scattered files
        self._organize_scattered_files(show_name, video_files, subtitle_files, metadata_result, output_base)
        return metadata_result.get("output", {})

    def _organize_show_files(self, show_path: Path, metadata_result: Dict, output_base: str):
        """Organize files for an already organized show."""
        print(f"    📁 Organizing files for: {show_path.name}")

        # Get the output directory from metadata result
        output_info = metadata_result.get("output", {}).get("files", {})
        media_dir = output_info.get("media_dir")

        if not media_dir:
            print(f"    ⚠️ No output directory found for: {show_path.name}")
            return

        # Get episode data from metadata
        source_data = metadata_result.get("source_data", {})
        episodes_data = source_data.get("episodes", [])
        translated_episodes = source_data.get("translated_episodes", [])

        if not episodes_data:
            print(f"    ⚠️ No episode data found for: {show_path.name}")
            return

        # Create episode mapping: (season, episode) -> episode_data
        episode_map = {}
        for episode in episodes_data:
            season_num = episode.get("season_number", 0)
            episode_num = episode.get("episode_number", 0)
            episode_map[(season_num, episode_num)] = episode

        # Update episode titles with translated versions if available
        for translated_episode in translated_episodes:
            season_num = translated_episode.get("season_number", 0)
            episode_num = translated_episode.get("episode_number", 0)
            if (season_num, episode_num) in episode_map:
                # Update the episode title with translated version
                episode_map[(season_num, episode_num)]["name_zh"] = translated_episode.get("name_zh", translated_episode.get("name", ""))

        # Find all video files in the show directory
        video_files = []
        subtitle_files = []

        for item in show_path.rglob('*'):
            if item.is_file():
                if item.suffix.lower() in self.video_extensions:
                    video_files.append(item)
                elif item.suffix.lower() in self.subtitle_extensions:
                    subtitle_files.append(item)

        print(f"    📹 Found {len(video_files)} video files and {len(subtitle_files)} subtitle files")

        # Track all successfully moved/copied files for cleanup decision
        moved_files = []
        failed_moves = 0

        # Process each video file
        for video_file in video_files:
            # Parse episode info from filename
            episode_info = self._parse_episode_info(video_file.stem)

            if episode_info:
                season_num, episode_num = episode_info
                episode_data = episode_map.get((season_num, episode_num))

                if episode_data:
                    # Get episode title (prefer translated Chinese title)
                    episode_title = episode_data.get("name_zh") or episode_data.get("name", f"Episode {episode_num}")

                    # Clean episode title: if contains '/', take part before '/', otherwise remove other invalid chars
                    if '/' in episode_title:
                        safe_episode_title = episode_title.split('/')[0].strip()
                        print(f"⚠️ Episode title contained '/', truncated: '{episode_title}' -> '{safe_episode_title}'")
                    else:
                        safe_episode_title = "".join(c for c in episode_title if c not in '\\:*?"<>|').strip()
                        if episode_title != safe_episode_title:
                            print(f"⚠️ Episode title contained invalid characters, cleaned: '{episode_title}' -> '{safe_episode_title}'")

                    # Create new filename using the correct title from metadata
                    show_title = metadata_result.get("normalized", {}).get("title_zh",
                                metadata_result.get("normalized", {}).get("title", show_path.name))
                    new_filename = f"{show_title} - S{season_num:02d}E{episode_num:02d} - {safe_episode_title}{video_file.suffix}"

                    # Create season directory
                    season_dir = Path(media_dir) / f"Season {season_num:02d}"
                    season_dir.mkdir(parents=True, exist_ok=True)

                    # Move or copy video file
                    new_video_path = season_dir / new_filename
                    try:
                        if self.copy_files:
                            shutil.copy2(str(video_file), str(new_video_path))
                            print(f"      📋 Copied video: {video_file.name} -> {new_video_path.name}")
                        else:
                            shutil.move(str(video_file), str(new_video_path))
                            print(f"      ✅ Moved video: {video_file.name} -> {new_video_path.name}")
                        moved_files.append(str(video_file))
                    except Exception as e:
                        failed_moves += 1
                        print(f"      ❌ Failed to {'copy' if self.copy_files else 'move'} video {video_file.name}: {e}")

                    # Look for matching subtitle files
                    base_name = video_file.stem
                    for subtitle_file in subtitle_files:
                        if subtitle_file.stem == base_name and str(subtitle_file) not in moved_files:
                            # Get language suffix for subtitle
                            lang_suffix = self._get_subtitle_language_suffix(subtitle_file.name)
                            # Move or copy subtitle file with proper language suffix
                            new_subtitle_path = season_dir / f"{new_filename.rsplit('.', 1)[0]}{lang_suffix}{subtitle_file.suffix}"
                            try:
                                if self.copy_files:
                                    shutil.copy2(str(subtitle_file), str(new_subtitle_path))
                                    print(f"      📋 Copied subtitle: {subtitle_file.name} -> {new_subtitle_path.name}")
                                else:
                                    shutil.move(str(subtitle_file), str(new_subtitle_path))
                                    print(f"      ✅ Moved subtitle: {subtitle_file.name} -> {new_subtitle_path.name}")
                                moved_files.append(str(subtitle_file))
                            except Exception as e:
                                failed_moves += 1
                                print(f"      ❌ Failed to {'copy' if self.copy_files else 'move'} subtitle {subtitle_file.name}: {e}")
                else:
                    print(f"      ⚠️ No metadata found for S{season_num:02d}E{episode_num:02d}")
                    failed_moves += 1
            else:
                print(f"      ⚠️ Could not parse episode info from: {video_file.name}")
                failed_moves += 1

        # Move or copy remaining subtitle files that don't match video files
        for subtitle_file in subtitle_files:
            if str(subtitle_file) in moved_files:
                continue  # Already moved/copied

            episode_info = self._parse_episode_info(subtitle_file.stem)
            if episode_info:
                season_num, episode_num = episode_info
                episode_data = episode_map.get((season_num, episode_num))

                if episode_data:
                    episode_title = episode_data.get("name_zh") or episode_data.get("name", f"Episode {episode_num}")
                    # Clean episode title: if contains '/', take part before '/', otherwise remove other invalid chars
                    if '/' in episode_title:
                        safe_episode_title = episode_title.split('/')[0].strip()
                        print(f"⚠️ Episode title contained '/', truncated: '{episode_title}' -> '{safe_episode_title}'")
                    else:
                        safe_episode_title = "".join(c for c in episode_title if c not in '\\:*?"<>|').strip()
                        if episode_title != safe_episode_title:
                            print(f"⚠️ Episode title contained invalid characters, cleaned: '{episode_title}' -> '{safe_episode_title}'")
                    show_title = metadata_result.get("normalized", {}).get("title_zh",
                                metadata_result.get("normalized", {}).get("title", show_path.name))
                    new_filename = f"{show_title} - S{season_num:02d}E{episode_num:02d} - {safe_episode_title}{subtitle_file.suffix}"

                    season_dir = Path(media_dir) / f"Season {season_num:02d}"
                    season_dir.mkdir(parents=True, exist_ok=True)

                    new_subtitle_path = season_dir / new_filename
                    try:
                        if self.copy_files:
                            shutil.copy2(str(subtitle_file), str(new_subtitle_path))
                            print(f"      📋 Copied subtitle: {subtitle_file.name} -> {new_subtitle_path.name}")
                        else:
                            shutil.move(str(subtitle_file), str(new_subtitle_path))
                            print(f"      ✅ Moved subtitle: {subtitle_file.name} -> {new_subtitle_path.name}")
                        moved_files.append(str(subtitle_file))
                    except Exception as e:
                        failed_moves += 1
                        print(f"      ❌ Failed to {'copy' if self.copy_files else 'move'} subtitle {subtitle_file.name}: {e}")
                else:
                    failed_moves += 1
            else:
                failed_moves += 1

        # Check if all files were moved/copied successfully
        total_files = len(video_files) + len(subtitle_files)
        successfully_moved = len(moved_files)

        if successfully_moved == total_files and failed_moves == 0:
            # All files moved/copied successfully, safe to delete original directory
            try:
                shutil.rmtree(show_path)
                print(f"    🗑️  Deleted original directory: {show_path}")
            except Exception as e:
                print(f"    ⚠️  Failed to delete original directory {show_path}: {e}")
        else:
            print(f"    ⚠️  Not all files {'copied' if self.copy_files else 'moved'} successfully ({successfully_moved}/{total_files}, {failed_moves} failed), keeping original directory")

    def _organize_scattered_files(self, show_name: str, video_files: List[str],
                                subtitle_files: List[str], metadata_result: Dict, output_base: str):
        """Organize scattered files into proper structure."""
        print(f"    📁 Organizing scattered files for: {show_name}")

        # Get the output directory from metadata result
        output_info = metadata_result.get("output", {}).get("files", {})
        media_dir = output_info.get("media_dir")

        if not media_dir:
            print(f"    ⚠️ No output directory found for: {show_name}")
            return

        # Get episode data from metadata
        source_data = metadata_result.get("source_data", {})
        episodes_data = source_data.get("translated_episodes", source_data.get("episodes", []))

        if not episodes_data:
            print(f"    ⚠️ No episode data found for: {show_name}")
            return

        # Create episode mapping: (season, episode) -> episode_data
        episode_map = {}
        for episode in episodes_data:
            season_num = episode.get("season_number", 0)
            episode_num = episode.get("episode_number", 0)
            episode_map[(season_num, episode_num)] = episode

        # Create the media directory if it doesn't exist
        media_path = Path(media_dir)
        media_path.mkdir(parents=True, exist_ok=True)

        organized_count = 0

        # Process video files
        for video_file in video_files:
            video_path = Path(video_file)
            episode_info = self._parse_episode_info(video_path.stem)

            if episode_info:
                season_num, episode_num = episode_info
                episode_data = episode_map.get((season_num, episode_num))

                if episode_data:
                    # Get episode title (prefer translated Chinese title)
                    episode_title = episode_data.get("name_zh", episode_data.get("name", f"Episode {episode_num}"))

                    # Clean episode title to remove invalid filename characters
                    safe_episode_title = "".join(c for c in episode_title if c not in '/\\:*?"<>|').strip()

                    # Create new filename
                    show_title = metadata_result.get("normalized", {}).get("title_zh",
                                metadata_result.get("normalized", {}).get("title", show_name))
                    new_filename = f"{show_title} - S{season_num:02d}E{episode_num:02d} - {safe_episode_title}{video_path.suffix}"

                    # Create season directory
                    season_dir = Path(media_dir) / f"Season {season_num:02d}"
                    season_dir.mkdir(parents=True, exist_ok=True)

                    # Move or copy video file
                    new_video_path = season_dir / new_filename
                    try:
                        if self.copy_files:
                            shutil.copy2(str(video_path), str(new_video_path))
                            print(f"      📋 Copied video: {video_path.name} -> {new_video_path.name}")
                        else:
                            shutil.move(str(video_path), str(new_video_path))
                            print(f"      📁 Moved video: {video_path.name} -> {new_video_path.name}")
                        organized_count += 1
                    except Exception as e:
                        print(f"      ❌ Failed to {'copy' if self.copy_files else 'move'} video {video_path.name}: {e}")
                        continue

                    # Look for matching subtitle files
                    base_name = video_path.stem
                    for subtitle_file in subtitle_files:
                        subtitle_path = Path(subtitle_file)
                        if subtitle_path.stem == base_name:
                            # Get language suffix for subtitle
                            lang_suffix = self._get_subtitle_language_suffix(subtitle_path.name)
                            # Create subtitle filename with language suffix
                            new_subtitle_filename = f"{show_title} - S{season_num:02d}E{episode_num:02d} - {safe_episode_title}{lang_suffix}{subtitle_path.suffix}"
                            new_subtitle_path = season_dir / new_subtitle_filename

                            try:
                                if self.copy_files:
                                    shutil.copy2(str(subtitle_path), str(new_subtitle_path))
                                    print(f"      📋 Copied subtitle: {subtitle_path.name} -> {new_subtitle_filename}")
                                else:
                                    shutil.move(str(subtitle_path), str(new_subtitle_path))
                                    print(f"      📁 Moved subtitle: {subtitle_path.name} -> {new_subtitle_filename}")
                                organized_count += 1
                            except Exception as e:
                                print(f"      ❌ Failed to {'copy' if self.copy_files else 'move'} subtitle {subtitle_path.name}: {e}")
                else:
                    print(f"      ⚠️ No metadata found for S{season_num:02d}E{episode_num:02d} in {video_path.name}")
            else:
                print(f"      ⚠️ Could not parse episode info from: {video_path.name}")

        print(f"    📊 Organized {organized_count} files for: {show_name}")

    def process_show_by_name(self, show_name: str, input_dir: str, output_dir: str, copy_files: bool = False) -> Dict:
        """Process a TV show by name: first generate metadata, then organize files."""
        print(f"🎬 Processing TV show: {show_name}")
        print(f"   📂 Input directory: {input_dir}")
        print(f"   📂 Output directory: {output_dir}")
        print(f"   📋 Operation mode: {'Copy' if copy_files else 'Move'} files")

        # Step 1: Generate complete metadata and folder structure
        print(f"\n📋 [1/3] Generating metadata and folder structure...")
        input_data = {
            "media_type": "tv",
            "query": show_name,
            "output_dir": output_dir,
            "verbose": True,
            "quiet": False,
            "aid_search": True
        }

        initial_state = GraphState(
            input=input_data,
            search={},
            source_data={},
            normalized={},
            artwork={},
            nfo={},
            output={},
            errors={}
        )

        try:
            result = self.app.invoke(initial_state)
            if result.get("output", {}).get("status") == "completed":
                print("   ✅ Metadata and folder structure created successfully")
            else:
                print("   ❌ Failed to generate metadata")
                return {}
        except Exception as e:
            print(f"   ❌ Error during metadata generation: {e}")
            return {}

        # Step 2: Scan input directory for video and subtitle files
        print(f"\n🔍 [2/3] Scanning input directory for media files...")
        video_files, subtitle_files = self._scan_media_files(input_dir)

        print(f"   📹 Found {len(video_files)} video files:")
        for video_file in video_files:
            print(f"      • {Path(video_file).name}")
        print(f"   📝 Found {len(subtitle_files)} subtitle files:")
        for subtitle_file in subtitle_files:
            print(f"      • {Path(subtitle_file).name}")

        if not video_files:
            print("   ⚠️ No video files found in input directory")
            return result.get("output", {})

        # Step 3: Organize and move/copy files
        print(f"\n📁 [3/3] Organizing and {'copying' if copy_files else 'moving'} files...")
        organized_count = self._organize_media_files(
            video_files, subtitle_files, result, output_dir, copy_files
        )

        print("\n✅ Processing completed!")
        print(f"   📊 Summary:")
        print(f"      • Show: {show_name}")
        print(f"      • Files processed: {organized_count}")
        print(f"      • Operation: {'Copied' if copy_files else 'Moved'}")

        return result.get("output", {})

    def _scan_media_files(self, input_dir: str) -> Tuple[List[str], List[str]]:
        """Scan directory for video and subtitle files."""
        video_files = []
        subtitle_files = []

        root_dir = Path(input_dir)
        if not root_dir.exists():
            raise FileNotFoundError(f"Directory not found: {root_dir}")

        # Scan recursively for media files
        for item in root_dir.rglob('*'):
            if item.is_file():
                if item.suffix.lower() in self.video_extensions:
                    video_files.append(str(item))
                elif item.suffix.lower() in self.subtitle_extensions:
                    subtitle_files.append(str(item))

        return video_files, subtitle_files

    def _organize_media_files(self, video_files: List[str], subtitle_files: List[str],
                            metadata_result: Dict, output_dir: str, copy_files: bool = False) -> int:
        """Organize and move/copy media files to proper locations."""
        # Get the output directory from metadata result
        output_info = metadata_result.get("output", {}).get("files", {})
        media_dir = output_info.get("media_dir")

        if not media_dir:
            print("   ❌ No output directory found in metadata result")
            return 0

        # Get episode data from metadata
        source_data = metadata_result.get("source_data", {})
        episodes_data = source_data.get("translated_episodes", source_data.get("episodes", []))

        if not episodes_data:
            print("   ❌ No episode data found in metadata result")
            return 0

        # Create episode mapping: (season, episode) -> episode_data
        episode_map = {}
        for episode in episodes_data:
            season_num = episode.get("season_number", 0)
            episode_num = episode.get("episode_number", 0)
            episode_map[(season_num, episode_num)] = episode

        organized_count = 0

        # Process video files
        for video_file in video_files:
            video_path = Path(video_file)
            episode_info = self._parse_episode_info(video_path.stem)

            if episode_info:
                season_num, episode_num = episode_info
                episode_data = episode_map.get((season_num, episode_num))

                if episode_data:
                    # Get episode title (prefer translated Chinese title)
                    episode_title = episode_data.get("name_zh", episode_data.get("name", f"Episode {episode_num}"))

                    # Clean episode title: if contains '/', take part before '/', otherwise remove other invalid chars
                    if '/' in episode_title:
                        safe_episode_title = episode_title.split('/')[0].strip()
                        print(f"⚠️ Episode title contained '/', truncated: '{episode_title}' -> '{safe_episode_title}'")
                    else:
                        safe_episode_title = "".join(c for c in episode_title if c not in '\\:*?"<>|').strip()
                        if episode_title != safe_episode_title:
                            print(f"⚠️ Episode title contained invalid characters, cleaned: '{episode_title}' -> '{safe_episode_title}'")

                    # Create new filename
                    show_title = metadata_result.get("normalized", {}).get("title_zh",
                                metadata_result.get("normalized", {}).get("title", "Unknown Show"))
                    new_filename = f"{show_title} - S{season_num:02d}E{episode_num:02d} - {safe_episode_title}{video_path.suffix}"

                    # Create season directory
                    season_dir = Path(media_dir) / f"Season {season_num:02d}"
                    season_dir.mkdir(parents=True, exist_ok=True)

                    # Move or copy video file
                    new_video_path = season_dir / new_filename
                    try:
                        if copy_files:
                            shutil.copy2(str(video_path), str(new_video_path))
                            print(f"      📋 Copied video: {video_path.name} -> {new_video_path.name}")
                        else:
                            shutil.move(str(video_path), str(new_video_path))
                            print(f"      📁 Moved video: {video_path.name} -> {new_video_path.name}")
                        organized_count += 1
                    except Exception as e:
                        print(f"      ❌ Failed to {'copy' if copy_files else 'move'} video {video_path.name}: {e}")
                        continue

                    # Look for matching subtitle files
                    base_name = video_path.stem
                    for subtitle_file in subtitle_files:
                        subtitle_path = Path(subtitle_file)
                        if subtitle_path.stem == base_name:
                            # Get language suffix for subtitle
                            lang_suffix = self._get_subtitle_language_suffix(subtitle_path.name)
                            # Create subtitle filename with language suffix
                            new_subtitle_filename = f"{show_title} - S{season_num:02d}E{episode_num:02d} - {safe_episode_title}{lang_suffix}{subtitle_path.suffix}"
                            new_subtitle_path = season_dir / new_subtitle_filename

                            try:
                                if copy_files:
                                    shutil.copy2(str(subtitle_path), str(new_subtitle_path))
                                    print(f"      📋 Copied subtitle: {subtitle_path.name} -> {new_subtitle_filename}")
                                else:
                                    shutil.move(str(subtitle_path), str(new_subtitle_path))
                                    print(f"      📁 Moved subtitle: {subtitle_path.name} -> {new_subtitle_filename}")
                                organized_count += 1
                            except Exception as e:
                                print(f"      ❌ Failed to {'copy' if copy_files else 'move'} subtitle {subtitle_path.name}: {e}")
                else:
                    print(f"      ⚠️ No metadata found for S{season_num:02d}E{episode_num:02d} in {video_path.name}")
            else:
                print(f"      ⚠️ Could not parse episode info from: {video_path.name}")

        return organized_count

    def process_organized_show_inplace(self, show_dir: str, tmdb_id: Optional[int] = None) -> Dict:
        """Process an organized TV show directory with in-place renaming."""
        show_path = Path(show_dir)
        show_name = show_path.name

        # Check if we should extract TMDB ID from local NFO
        local_tmdb_id = tmdb_id
        if self.use_local_nfo and tmdb_id is None:
            # Special logic for --type movie: first try strict match with folder name, then fallback
            if self.media_type == "movie":
                print(f"   📄 Searching for NFO files (strict match: folder name, then fallback)...")
                local_tmdb_id = self._extract_tmdb_id_from_nfo(show_dir, strict_match=True)
                if not local_tmdb_id:
                    print(f"   📄 Strict match failed, trying regular NFO search...")
                    local_tmdb_id = self._extract_tmdb_id_from_nfo(show_dir, strict_match=False)
            else:
                local_tmdb_id = self._extract_tmdb_id_from_nfo(show_dir)

            if local_tmdb_id:
                print(f"   📝 Extracted TMDB ID {local_tmdb_id} from local NFO")

        # If tmdb_id is provided, skip name parsing and use direct ID lookup
        if local_tmdb_id is not None:
            print(f"🎬 Processing organized show (in-place) with TMDB ID: {local_tmdb_id}")
            print(f"   🎯 Using direct TMDB lookup, skipping name parsing")
            search_query = ""  # Empty query when using direct TMDB ID
        else:
            # Clean the show name for search - this becomes the query parameter
            search_query = self._clean_show_name_for_search(show_name)
            print(f"🎬 Processing organized show (in-place): {show_name}")
            print(f"   🔍 Search query: '{search_query}'")

        # Use the show directory itself as output directory for in-place mode
        input_data = {
            "media_type": self.media_type,
            "media_type_forced": self.media_type != "tv",  # If not default tv, force it
            "query": search_query,
            "output_dir": str(show_path),  # Use show directory as output directly
            "verbose": True,  # Enable verbose output for better debugging
            "quiet": False,   # Disable quiet mode for better debugging
            "aid_search": True
        }

        # Add tmdb_id if provided - this will trigger direct lookup in Media Metadata Agent
        if local_tmdb_id is not None:
            input_data["tmdb_id"] = local_tmdb_id

        initial_state = GraphState(
            input=input_data,
            search={},
            source_data={},
            normalized={},
            artwork={},
            nfo={},
            output={},
            errors={},
            inplace=True  # Enable in-place mode
        )

        try:
            # Generate metadata directly in the show directory (in-place mode)
            result = self.app.invoke(initial_state)
            if result.get("output", {}).get("status") != "completed":
                print(f"❌ Failed to generate metadata for: {show_name}")
                return {}

            print(f"   📁 Metadata generated directly in: {show_path.name}")

            # Step 2: Rename files within the folder (no folder renaming needed)
            self._rename_files_inplace(show_path, result)

            print(f"✅ Successfully processed (in-place): {show_name}")

        except Exception as e:
            print(f"❌ Error during in-place processing: {e}")
            return {}

        return result.get("output", {})

    def process_scattered_episodes_inplace(self, episode_files: List[str], input_dir: str) -> Dict:
        """Process scattered episode files with in-place organization."""
        if not episode_files:
            return {}

        print(f"📺 Processing {len(episode_files)} scattered episode files (in-place)")

        # Group files by potential show names
        show_groups = self._group_scattered_files(episode_files)

        results = {}
        successful_groups = 0
        failed_groups = 0

        for show_name, files in show_groups.items():
            print(f"  📁 Processing show group (in-place): {show_name}")

            try:
                # Separate video and subtitle files
                video_files = [f for f in files if Path(f).suffix.lower() in self.video_extensions]
                subtitle_files = [f for f in files if Path(f).suffix.lower() in self.subtitle_extensions]

                if not video_files:
                    print(f"    ⚠️ No video files found for show: {show_name}")
                    failed_groups += 1
                    continue

                print(f"    🎯 Found {len(video_files)} video files and {len(subtitle_files)} subtitle files")

                # Clean the show name for search
                search_query = self._clean_show_name_for_search(show_name)
                print(f"    🔍 Search query: '{search_query}'")

                # Generate metadata
                input_data = {
                    "media_type": "tv",
                    "query": search_query,
                    "output_dir": input_dir,  # Use input directory as output
                    "verbose": False,
                    "quiet": True,
                    "aid_search": True
                }

                initial_state = GraphState(
                    input=input_data,
                    search={},
                    source_data={},
                    normalized={},
                    artwork={},
                    nfo={},
                    output={},
                    errors={}
                )

                result = self.app.invoke(initial_state)
                if result.get("output", {}).get("status") != "completed":
                    print(f"    ❌ Failed to generate metadata for: {show_name}")
                    failed_groups += 1
                    continue

                # Get target folder info
                output_info = result.get("output", {}).get("files", {})
                media_dir = output_info.get("media_dir")

                if not media_dir:
                    print(f"    ❌ No output directory found for: {show_name}")
                    failed_groups += 1
                    continue

                # Create the media directory
                media_path = Path(media_dir)
                media_path.mkdir(parents=True, exist_ok=True)

                # Organize scattered files into the target structure
                organized_count = self._organize_scattered_files_inplace(
                    show_name, video_files, subtitle_files, result
                )

                if organized_count > 0:
                    results[show_name] = result.get("output", {})
                    successful_groups += 1
                    print(f"  ✅ Successfully processed (in-place): {show_name}")
                else:
                    failed_groups += 1
                    print(f"  ❌ Failed to organize files for: {show_name}")

            except Exception as e:
                failed_groups += 1
                print(f"  ❌ Error processing show group {show_name}: {e}")

        print(f"  📊 Show groups summary: {successful_groups} successful, {failed_groups} failed")

        return results

    def _rename_files_inplace(self, show_path: Path, metadata_result: Dict):
        """Rename files within the show folder to proper structure."""
        print(f"    📝 Renaming files in: {show_path.name}")

        # Determine media type from metadata
        normalized = metadata_result.get("normalized", {})
        media_type = normalized.get("media_type", "tv")

        # Handle directory renaming for both movies and TV shows
        try:
            show_title = metadata_result.get("normalized", {}).get("title_zh",
                        metadata_result.get("normalized", {}).get("title", show_path.name))
            show_year = metadata_result.get("normalized", {}).get("year", 0)

            # Clean title for directory name (remove filesystem-illegal characters)
            safe_title = re.sub(r'[\\/:"*?<>|]', '', show_title).strip()
            new_dir_name = f"{safe_title} ({show_year})"

            parent_dir = show_path.parent
            new_show_path = parent_dir / new_dir_name

            # Only rename if the name is different
            if show_path != new_show_path:
                show_path.rename(new_show_path)
                print(f"    📁 Renamed directory: {show_path.name} -> {new_dir_name}")
                # Update show_path for further operations
                show_path = new_show_path
            else:
                print(f"    ⏭️ Directory already has correct name: {show_path.name}")
        except Exception as e:
            print(f"    ⚠️ Failed to rename directory {show_path.name}: {e}")

        if media_type == "movie":
            # For movies in in-place mode, just confirm metadata generation
            # Movies don't have episode-style file renaming
            print(f"    📽️ Movie directory renamed and metadata generated")
            return

        # TV show logic - handle episode renaming
        # Get episode data from metadata
        source_data = metadata_result.get("source_data", {})
        episodes_data = source_data.get("episodes", [])
        translated_episodes = source_data.get("translated_episodes", [])

        if not episodes_data:
            print(f"    ⚠️ No episode data found")
            return

        # Create episode mapping: (season, episode) -> episode_data
        episode_map = {}
        for episode in episodes_data:
            season_num = episode.get("season_number", 0)
            episode_num = episode.get("episode_number", 0)
            episode_map[(season_num, episode_num)] = episode

        # Update episode titles with translated versions if available
        for translated_episode in translated_episodes:
            season_num = translated_episode.get("season_number", 0)
            episode_num = translated_episode.get("episode_number", 0)
            if (season_num, episode_num) in episode_map:
                episode_map[(season_num, episode_num)]["name_zh"] = translated_episode.get("name_zh", translated_episode.get("name", ""))

        # Find all video files in the show directory
        video_files = []
        subtitle_files = []

        for item in show_path.rglob('*'):
            if item.is_file():
                if item.suffix.lower() in self.video_extensions:
                    video_files.append(item)
                elif item.suffix.lower() in self.subtitle_extensions:
                    subtitle_files.append(item)

        print(f"    📹 Found {len(video_files)} video files and {len(subtitle_files)} subtitle files")

        renamed_count = 0
        skipped_count = 0

        # Process each video file
        for video_file in video_files:
            # Check if filename contains SxxExx pattern before processing
            filename = video_file.stem
            if not re.search(r'S\d{1,2}E\d{1,2}', filename, re.IGNORECASE):
                print(f"      ⏭️ Skipping video (no SxxExx pattern): {video_file.name}")
                skipped_count += 1
                continue

            # Parse episode info from filename
            episode_info = self._parse_episode_info(filename)

            if episode_info:
                season_num, episode_num = episode_info
                episode_data = episode_map.get((season_num, episode_num))

                if episode_data:
                    # Get episode title (prefer translated Chinese title)
                    episode_title = episode_data.get("name_zh") or episode_data.get("name", f"Episode {episode_num}")

                    # Clean episode title: if contains '/', take part before '/', otherwise remove other invalid chars
                    if '/' in episode_title:
                        safe_episode_title = episode_title.split('/')[0].strip()
                        print(f"⚠️ Episode title contained '/', truncated: '{episode_title}' -> '{safe_episode_title}'")
                    else:
                        safe_episode_title = "".join(c for c in episode_title if c not in '\\:*?"<>|').strip()
                        if episode_title != safe_episode_title:
                            print(f"⚠️ Episode title contained invalid characters, cleaned: '{episode_title}' -> '{safe_episode_title}'")

                    # Create new filename using the correct title from metadata
                    show_title = metadata_result.get("normalized", {}).get("title_zh",
                                metadata_result.get("normalized", {}).get("title", show_path.name))
                    new_filename = f"{show_title} - S{season_num:02d}E{episode_num:02d} - {safe_episode_title}{video_file.suffix}"

                    # Create season directory
                    season_dir = show_path / f"Season {season_num:02d}"
                    season_dir.mkdir(parents=True, exist_ok=True)

                    # Move video file to proper location
                    new_video_path = season_dir / new_filename
                    try:
                        if video_file != new_video_path:
                            shutil.move(str(video_file), str(new_video_path))
                            print(f"      📝 Renamed video: {video_file.name} -> {new_filename}")
                        else:
                            print(f"      ⏭️ Video already has correct name: {video_file.name}")
                        renamed_count += 1
                    except Exception as e:
                        print(f"      ❌ Failed to rename video {video_file.name}: {e}")

                    # Look for matching subtitle files and rename them too
                    base_name = video_file.stem
                    for subtitle_file in subtitle_files:
                        if subtitle_file.stem == base_name and subtitle_file.exists():
                            # Get language suffix for subtitle
                            lang_suffix = self._get_subtitle_language_suffix(subtitle_file.name)
                            # Create subtitle filename with language suffix
                            new_subtitle_filename = f"{show_title} - S{season_num:02d}E{episode_num:02d} - {safe_episode_title}{lang_suffix}{subtitle_file.suffix}"
                            new_subtitle_path = season_dir / new_subtitle_filename

                            try:
                                if subtitle_file != new_subtitle_path:
                                    shutil.move(str(subtitle_file), str(new_subtitle_path))
                                    print(f"      📝 Renamed subtitle: {subtitle_file.name} -> {new_subtitle_filename}")
                                else:
                                    print(f"      ⏭️ Subtitle already has correct name: {subtitle_file.name}")
                                renamed_count += 1
                            except Exception as e:
                                print(f"      ❌ Failed to rename subtitle {subtitle_file.name}: {e}")
                else:
                    print(f"      ⚠️ No metadata found for S{season_num:02d}E{episode_num:02d}")
            else:
                print(f"      ⚠️ Could not parse episode info from: {video_file.name}")

        # Handle remaining subtitle files that don't match video files
        for subtitle_file in subtitle_files:
            if not subtitle_file.exists():
                continue  # Already processed

            # Check if subtitle filename contains SxxExx pattern
            if not re.search(r'S\d{1,2}E\d{1,2}', subtitle_file.stem, re.IGNORECASE):
                print(f"      ⏭️ Skipping subtitle (no SxxExx pattern): {subtitle_file.name}")
                skipped_count += 1
                continue

            episode_info = self._parse_episode_info(subtitle_file.stem)
            if episode_info:
                season_num, episode_num = episode_info
                episode_data = episode_map.get((season_num, episode_num))

                if episode_data:
                    episode_title = episode_data.get("name_zh") or episode_data.get("name", f"Episode {episode_num}")
                    # Clean episode title
                    if '/' in episode_title:
                        safe_episode_title = episode_title.split('/')[0].strip()
                    else:
                        safe_episode_title = "".join(c for c in episode_title if c not in '\\:*?"<>|').strip()

                    show_title = metadata_result.get("normalized", {}).get("title_zh",
                                metadata_result.get("normalized", {}).get("title", show_path.name))
                    # Get language suffix for subtitle
                    lang_suffix = self._get_subtitle_language_suffix(subtitle_file.name)
                    new_filename = f"{show_title} - S{season_num:02d}E{episode_num:02d} - {safe_episode_title}{lang_suffix}{subtitle_file.suffix}"

                    season_dir = show_path / f"Season {season_num:02d}"
                    season_dir.mkdir(parents=True, exist_ok=True)

                    new_subtitle_path = season_dir / new_filename
                    try:
                        if subtitle_file != new_subtitle_path:
                            shutil.move(str(subtitle_file), str(new_subtitle_path))
                            print(f"      📝 Renamed subtitle: {subtitle_file.name} -> {new_filename}")
                        else:
                            print(f"      ⏭️ Subtitle already has correct name: {subtitle_file.name}")
                        renamed_count += 1
                    except Exception as e:
                        print(f"      ❌ Failed to rename subtitle {subtitle_file.name}: {e}")

        print(f"    📊 Renamed {renamed_count} files, skipped {skipped_count} files (no SxxExx pattern)")

        # Rename the input directory to "{title} ({year})" for TV shows only
        try:
            show_title = metadata_result.get("normalized", {}).get("title_zh",
                        metadata_result.get("normalized", {}).get("title", show_path.name))
            show_year = metadata_result.get("normalized", {}).get("year", 0)

            # Clean title for directory name (remove filesystem-illegal characters)
            safe_title = re.sub(r'[\\/:"*?<>|]', '', show_title).strip()
            new_dir_name = f"{safe_title} ({show_year})"

            parent_dir = show_path.parent
            new_show_path = parent_dir / new_dir_name

            # Only rename if the name is different
            if show_path != new_show_path:
                show_path.rename(new_show_path)
                print(f"    📁 Renamed directory: {show_path.name} -> {new_dir_name}")
            else:
                print(f"    ⏭️ Directory already has correct name: {show_path.name}")
        except Exception as e:
            print(f"    ⚠️ Failed to rename directory {show_path.name}: {e}")

    def _organize_scattered_files_inplace(self, show_name: str, video_files: List[str],
                                        subtitle_files: List[str], metadata_result: Dict) -> int:
        """Organize scattered files into proper structure (in-place)."""
        print(f"    📁 Organizing scattered files (in-place) for: {show_name}")

        # Get the output directory from metadata result
        output_info = metadata_result.get("output", {}).get("files", {})
        media_dir = output_info.get("media_dir")

        if not media_dir:
            print(f"    ⚠️ No output directory found for: {show_name}")
            return 0

        # Get episode data from metadata
        source_data = metadata_result.get("source_data", {})
        episodes_data = source_data.get("translated_episodes", source_data.get("episodes", []))

        if not episodes_data:
            print(f"    ⚠️ No episode data found for: {show_name}")
            return 0

        # Create episode mapping: (season, episode) -> episode_data
        episode_map = {}
        for episode in episodes_data:
            season_num = episode.get("season_number", 0)
            episode_num = episode.get("episode_number", 0)
            episode_map[(season_num, episode_num)] = episode

        # Create the media directory if it doesn't exist
        media_path = Path(media_dir)
        media_path.mkdir(parents=True, exist_ok=True)

        organized_count = 0

        # Process video files
        for video_file in video_files:
            video_path = Path(video_file)
            episode_info = self._parse_episode_info(video_path.stem)

            if episode_info:
                season_num, episode_num = episode_info
                episode_data = episode_map.get((season_num, episode_num))

                if episode_data:
                    # Get episode title (prefer translated Chinese title)
                    episode_title = episode_data.get("name_zh", episode_data.get("name", f"Episode {episode_num}"))

                    # Clean episode title to remove invalid filename characters
                    safe_episode_title = "".join(c for c in episode_title if c not in '/\\:*?"<>|').strip()

                    # Create new filename
                    show_title = metadata_result.get("normalized", {}).get("title_zh",
                                metadata_result.get("normalized", {}).get("title", show_name))
                    new_filename = f"{show_title} - S{season_num:02d}E{episode_num:02d} - {safe_episode_title}{video_path.suffix}"

                    # Create season directory
                    season_dir = Path(media_dir) / f"Season {season_num:02d}"
                    season_dir.mkdir(parents=True, exist_ok=True)

                    # Move video file to proper location
                    new_video_path = season_dir / new_filename
                    try:
                        if video_path != new_video_path:
                            shutil.move(str(video_path), str(new_video_path))
                            print(f"      📁 Moved video: {video_path.name} -> {new_filename}")
                        else:
                            print(f"      ⏭️ Video already in correct location: {video_path.name}")
                        organized_count += 1
                    except Exception as e:
                        print(f"      ❌ Failed to move video {video_path.name}: {e}")
                        continue

                    # Look for matching subtitle files
                    base_name = video_path.stem
                    for subtitle_file in subtitle_files:
                        subtitle_path = Path(subtitle_file)
                        if subtitle_path.stem == base_name:
                            # Get language suffix for subtitle
                            lang_suffix = self._get_subtitle_language_suffix(subtitle_path.name)
                            # Create subtitle filename with language suffix
                            new_subtitle_filename = f"{show_title} - S{season_num:02d}E{episode_num:02d} - {safe_episode_title}{lang_suffix}{subtitle_path.suffix}"
                            new_subtitle_path = season_dir / new_subtitle_filename

                            try:
                                if subtitle_path != new_subtitle_path:
                                    shutil.move(str(subtitle_path), str(new_subtitle_path))
                                    print(f"      📁 Moved subtitle: {subtitle_path.name} -> {new_subtitle_filename}")
                                else:
                                    print(f"      ⏭️ Subtitle already in correct location: {subtitle_path.name}")
                                organized_count += 1
                            except Exception as e:
                                print(f"      ❌ Failed to move subtitle {subtitle_path.name}: {e}")
                else:
                    print(f"      ⚠️ No metadata found for S{season_num:02d}E{episode_num:02d} in {video_path.name}")
            else:
                print(f"      ⚠️ Could not parse episode info from: {video_path.name}")

        print(f"    📊 Organized {organized_count} files for: {show_name}")
        return organized_count

    def run(self, input_dir: str, output_dir: str):
        """Main execution method for batch processing."""
        print(f"🔍 Scanning directory: {input_dir}")
        print(f"   📂 Input directory: {input_dir}")

        if self.multi_mode:
            print(f"   📋 Operation mode: Multi-mode (process all subdirs/files)")
            print(f"   📁 Will process each subdirectory and loose video files")
        elif self.inplace_rename:
            print(f"   📋 Operation mode: In-place renaming")
            print(f"   📁 Processing input directory directly as a show")
        else:
            print(f"   📂 Output directory: {output_dir}")
            print(f"   📋 Operation mode: {'Copy' if self.copy_files else 'Move'} files")

        if self.multi_mode:
            # Multi-mode: process all subdirectories and loose files
            self._run_multi_mode(input_dir)
        elif self.inplace_rename:
            # In-place mode: process the input directory directly as a show
            print(f"\n🎬 Processing input directory as organized show (in-place)...")
            try:
                result = self.process_organized_show_inplace(input_dir, self.tmdb_id)
                if result:
                    print(f"   ✅ Completed: {Path(input_dir).name}")
                else:
                    print(f"   ❌ Failed: {Path(input_dir).name}")
            except Exception as e:
                print(f"   ❌ Error processing show {Path(input_dir).name}: {e}")

            print("\n✅ Batch processing completed!")
            print(f"   📊 Summary:")
            print(f"      • Input directory processed: {Path(input_dir).name}")
            print(f"      • Operation: In-place renaming completed")
        else:
            # Normal mode: scan directory and process shows
            organized_shows, scattered_episodes = self.scan_directory(input_dir)

            print(f"\n📊 Scan completed!")
            print(f"   📁 Found {len(organized_shows)} organized shows:")
            for show in organized_shows:
                print(f"      • {Path(show).name}")
            print(f"   📄 Found {len(scattered_episodes)} scattered files:")
            for file in scattered_episodes:
                print(f"      • {Path(file).name}")

            # Process organized shows
            if organized_shows:
                print(f"\n🎬 Processing {len(organized_shows)} organized shows...")
                for i, show_dir in enumerate(organized_shows, 1):
                    print(f"   [{i}/{len(organized_shows)}] Processing: {Path(show_dir).name}")
                    try:
                        result = self.process_organized_show(show_dir, output_dir)
                        if result:
                            print(f"   ✅ Completed: {Path(show_dir).name}")
                        else:
                            print(f"   ❌ Failed: {Path(show_dir).name}")
                    except Exception as e:
                        print(f"   ❌ Error processing organized show {Path(show_dir).name}: {e}")

            # Process scattered episodes
            if scattered_episodes:
                print(f"\n📺 Processing {len(scattered_episodes)} scattered episode files...")
                try:
                    result = self.process_scattered_episodes(scattered_episodes, output_dir)
                    if result:
                        processed_shows = len(result)
                        print(f"   ✅ Processed {processed_shows} show groups from scattered files")
                    else:
                        print(f"   ❌ No scattered files were successfully processed")
                except Exception as e:
                    print(f"   ❌ Error processing scattered episodes: {e}")

            print("\n✅ Batch processing completed!")
            print(f"   📊 Summary:")
            print(f"      • Organized shows processed: {len(organized_shows)}")
            print(f"      • Scattered files processed: {len(scattered_episodes)}")
            print(f"      • Output directory: {output_dir}")

    def _run_multi_mode(self, input_dir: str):
        """Run multi-mode processing: process all subdirs, NFO files, and loose files."""
        root_path = Path(input_dir)

        # Scan for all subdirectories and loose video files
        subdirs = []
        loose_video_files = []
        loose_subtitle_files = []

        for item in root_path.iterdir():
            if item.is_dir() and not item.name.startswith('.') and item.name.lower() not in self.exclude_dirs:
                subdirs.append(item)
            elif item.is_file():
                if item.suffix.lower() in self.video_extensions:
                    loose_video_files.append(item)
                elif item.suffix.lower() in self.subtitle_extensions:
                    loose_subtitle_files.append(item)

        print(f"\n📊 Multi-mode scan completed!")
        print(f"   📁 Found {len(subdirs)} subdirectories:")

        # In multi-mode, scan all subdirectories for NFO files with TMDB IDs
        nfo_tasks = []
        for subdir in subdirs:
            print(f"      • {subdir.name}")
            if self.use_local_nfo:
                # Special logic for --type movie: first try strict match with folder name, then fallback
                if self.media_type == "movie":
                    print(f"        📄 Searching for NFO files (strict match: folder name, then fallback)...")
                    folder_name = subdir.name
                    # First try strict match with folder name
                    tmdb_id = self._extract_tmdb_id_from_nfo(str(subdir), folder_name, strict_match=True)
                    if tmdb_id:
                        # Find the corresponding NFO file path
                        nfo_files = list(subdir.glob("*.nfo"))
                        matching_nfo = f"{str(subdir)}/{subdir.name}.nfo"  # Default assumption
                        for nfo_file in nfo_files:
                            try:
                                content = nfo_file.read_text(encoding='utf-8')
                                if folder_name.lower() in content.lower():
                                    matching_nfo = str(nfo_file)
                                    break
                            except:
                                continue
                        nfo_tasks.append((tmdb_id, str(subdir), matching_nfo))
                        print(f"        📄 Found TMDB ID {tmdb_id} via strict match in {Path(matching_nfo).name}")
                        continue  # Skip fallback for this subdirectory

                    # Strict match failed, try regular NFO search
                    print(f"        📄 Strict match failed, trying regular NFO search...")
                    nfo_files = self._find_all_nfo_files_with_tmdb_id(str(subdir))
                    if nfo_files:
                        print(f"        📄 Found {len(nfo_files)} NFO file(s) with TMDB ID(s) via fallback")
                        for tmdb_id, nfo_path in nfo_files:
                            nfo_tasks.append((tmdb_id, str(subdir), nfo_path))
                            print(f"          • TMDB ID {tmdb_id} in {Path(nfo_path).name}")
                else:
                    # Regular NFO search for TV shows
                    nfo_files = self._find_all_nfo_files_with_tmdb_id(str(subdir))
                    if nfo_files:
                        print(f"        📄 Found {len(nfo_files)} NFO file(s) with TMDB ID(s)")
                        for tmdb_id, nfo_path in nfo_files:
                            nfo_tasks.append((tmdb_id, str(subdir), nfo_path))
                            print(f"          • TMDB ID {tmdb_id} in {Path(nfo_path).name}")

        # Also scan root directory for loose NFO files with TMDB IDs
        loose_nfo_files = []
        for item in root_path.iterdir():
            if item.is_file() and item.suffix.lower() == '.nfo':
                try:
                    content = item.read_text(encoding='utf-8')
                    match = re.search(r'<tmdbid>(\d+)</tmdbid>', content, re.IGNORECASE)
                    if match:
                        tmdb_id = int(match.group(1))
                        loose_nfo_files.append((tmdb_id, str(item)))
                        print(f"      • Loose NFO: {item.name} (TMDB ID: {tmdb_id})")
                except Exception as e:
                    print(f"      ⚠️ Could not parse loose NFO file {item.name}: {e}")

        print(f"   📹 Found {len(loose_video_files)} loose video files:")
        for video_file in loose_video_files:
            print(f"      • {video_file.name}")
        print(f"   📝 Found {len(loose_subtitle_files)} loose subtitle files:")
        for subtitle_file in loose_subtitle_files:
            print(f"      • {subtitle_file.name}")

        if self.use_local_nfo:
            print(f"   🆔 Found {len(nfo_tasks)} NFO tasks from subfolders")
            print(f"   📄 Found {len(loose_nfo_files)} loose NFO files with TMDB IDs")

        processed_count = 0
        failed_count = 0

        # Process loose NFO files by creating movie directories
        if loose_nfo_files:
            print(f"\n🎬 Processing {len(loose_nfo_files)} loose NFO files (creating movie directories)...")
            for i, (tmdb_id, nfo_path) in enumerate(loose_nfo_files, 1):
                nfo_name = Path(nfo_path).name
                print(f"   [{i}/{len(loose_nfo_files)}] Creating movie directory for TMDB ID {tmdb_id} from {nfo_name}")
                try:
                    # Create a temporary scraper to generate metadata and folder structure
                    temp_scraper = BatchMediaScraper(
                        config_path=None,  # Use default config
                        copy_files=False,
                        inplace_rename=True,  # Enable in-place mode
                        output_dir=None,
                        multi_mode=False,
                        tmdb_id=tmdb_id,  # Use TMDB ID for direct lookup
                        use_local_nfo=False,  # Don't try to extract ID again
                        extra_images=self.extra_images,
                        media_type=self.media_type  # Use the specified media type
                    )

                    # Process the movie - create a directory with same name as NFO file (without extension)
                    nfo_stem = Path(nfo_path).stem  # Remove .nfo extension
                    movie_dir = Path(root_path) / nfo_stem

                    if movie_dir.exists():
                        print(f"   ⚠️ Directory already exists, skipping: {nfo_stem}")
                        continue

                    movie_dir.mkdir(parents=True, exist_ok=True)
                    print(f"   📁 Created movie directory: {nfo_stem}")

                    # Copy NFO file to the new directory as movie.nfo
                    target_nfo = movie_dir / "movie.nfo"
                    try:
                        shutil.copy2(nfo_path, target_nfo)
                        print(f"   📄 Copied NFO to: {target_nfo.name}")
                    except Exception as e:
                        print(f"   ❌ Failed to copy NFO: {e}")
                        continue

                    # Process the newly created directory like a normal organized show
                    result = temp_scraper.process_organized_show_inplace(str(movie_dir), tmdb_id)
                    if result:
                        print(f"   ✅ Created movie directory for TMDB ID {tmdb_id}")
                        processed_count += 1
                        # Clean up the loose NFO file since it's been processed
                        try:
                            os.remove(nfo_path)
                            print(f"   🗑️ Cleaned up processed NFO: {nfo_name}")
                        except Exception as e:
                            print(f"   ⚠️ Failed to clean up NFO {nfo_path}: {e}")
                    else:
                        print(f"   ❌ Failed to create directory for TMDB ID {tmdb_id}")
                        failed_count += 1
                except Exception as e:
                    print(f"   ❌ Error processing TMDB ID {tmdb_id} from {nfo_name}: {e}")
                    failed_count += 1

        # Process NFO-based tasks (each TMDB ID creates a separate task)
        if self.use_local_nfo and nfo_tasks:
            print(f"\n🎯 Processing {len(nfo_tasks)} NFO-based tasks...")
            for i, (tmdb_id, subdir_path, nfo_path) in enumerate(nfo_tasks, 1):
                subdir_name = Path(subdir_path).name
                nfo_name = Path(nfo_path).name
                print(f"   [{i}/{len(nfo_tasks)}] Processing TMDB ID {tmdb_id} from {nfo_name} in {subdir_name}")
                try:
                    # Create a scraper instance for this specific TMDB ID
                    temp_scraper = BatchMediaScraper(
                        config_path=None,  # Use default config
                        copy_files=False,
                        inplace_rename=True,  # Enable in-place mode
                        output_dir=None,
                        multi_mode=False,
                        tmdb_id=tmdb_id,  # Pass the TMDB ID
                        use_local_nfo=True,  # Keep NFO usage enabled
                        extra_images=self.extra_images,
                        media_type=self.media_type  # Pass the media type
                    )
                    result = temp_scraper.process_organized_show_inplace(subdir_path, tmdb_id)
                    if result:
                        print(f"   ✅ Completed: TMDB ID {tmdb_id} for {subdir_name}")
                        processed_count += 1
                        # Remove this subdirectory from the regular subdirs list since it's processed
                        subdirs = [s for s in subdirs if str(s) != subdir_path]
                    else:
                        print(f"   ❌ Failed: TMDB ID {tmdb_id} for {subdir_name}")
                        failed_count += 1
                except Exception as e:
                    print(f"   ❌ Error processing TMDB ID {tmdb_id} for {subdir_name}: {e}")
                    failed_count += 1

        # Process remaining subdirectories (not processed as NFO tasks)
        if subdirs:
            print(f"\n🏗️ Processing remaining {len(subdirs)} subdirectories (no TMDB IDs found in NFO files)...")
            for i, subdir in enumerate(subdirs, 1):
                print(f"   [{i}/{len(subdirs)}] Processing subdirectory: {subdir.name}")
                try:
                    # Create a temporary scraper instance for each subdirectory
                    temp_scraper = BatchMediaScraper(
                        config_path=None,  # Use default config
                        copy_files=False,
                        inplace_rename=True,  # Enable in-place mode
                        output_dir=None,
                        multi_mode=False,
                        use_local_nfo=self.use_local_nfo,  # Keep NFO usage if enabled
                        extra_images=self.extra_images
                    )
                    result = temp_scraper.process_organized_show_inplace(str(subdir))
                    if result:
                        print(f"   ✅ Completed: {subdir.name}")
                        processed_count += 1
                    else:
                        print(f"   ❌ Failed: {subdir.name}")
                        failed_count += 1
                except Exception as e:
                    print(f"   ❌ Error processing subdirectory {subdir.name}: {e}")
                    failed_count += 1

        # Process loose video files
        if loose_video_files:
            print(f"\n🎬 Processing {len(loose_video_files)} loose video files...")
            for i, video_file in enumerate(loose_video_files, 1):
                print(f"   [{i}/{len(loose_video_files)}] Processing loose file: {video_file.name}")
                try:
                    self._process_loose_video_file(video_file, loose_subtitle_files)
                    processed_count += 1
                except Exception as e:
                    print(f"   ❌ Error processing loose file {video_file.name}: {e}")
                    failed_count += 1

        print("\n✅ Multi-mode processing completed!")
        print(f"   📊 Summary:")
        if self.use_local_nfo:
            print(f"      • NFO-based tasks processed: {len(nfo_tasks)}")
        print(f"      • Remaining items processed: {processed_count - len(nfo_tasks) if self.use_local_nfo else processed_count}")
        print(f"      • Items failed: {failed_count}")
        print(f"      • Total items: {len(subdirs) + len(loose_video_files) + (len(nfo_tasks) if self.use_local_nfo else 0)}")

    def _process_loose_video_file(self, video_file: Path, all_subtitle_files: List[Path]):
        """Process a loose video file by creating a show directory for it."""
        # Extract show name from filename
        filename = video_file.stem
        show_name = self._extract_show_name_from_filename(filename)

        if not show_name:
            print(f"      ⚠️ Could not extract show name from: {filename}")
            return

        print(f"      🎯 Extracted show name: '{show_name}'")

        # Create a new directory for this show in the same directory as the video file
        parent_dir = video_file.parent
        show_dir_name = f"{show_name} (Unknown Year)"  # We'll update this after getting metadata
        show_dir = parent_dir / show_dir_name

        # Create the directory
        show_dir.mkdir(parents=True, exist_ok=True)
        print(f"      📁 Created show directory: {show_dir_name}")

        # Move the video file to the new directory
        new_video_path = show_dir / video_file.name
        shutil.move(str(video_file), str(new_video_path))
        print(f"      📁 Moved video file: {video_file.name} -> {show_dir_name}/")

        # Look for matching subtitle files
        matching_subtitles = []
        base_name = video_file.stem
        for subtitle_file in all_subtitle_files[:]:  # Copy the list to avoid modification issues
            if subtitle_file.stem == base_name:
                new_subtitle_path = show_dir / subtitle_file.name
                shutil.move(str(subtitle_file), str(new_subtitle_path))
                print(f"      📁 Moved subtitle file: {subtitle_file.name} -> {show_dir_name}/")
                matching_subtitles.append(subtitle_file)

        # Remove moved subtitles from the original list
        for moved_subtitle in matching_subtitles:
            all_subtitle_files.remove(moved_subtitle)

        # Now process the newly created show directory in-place
        print(f"      🔄 Processing created show directory...")
        # Create temporary scraper with same settings as the parent scraper
        temp_scraper = BatchMediaScraper(
            config_path=None,  # Use default config
            copy_files=False,
            inplace_rename=True,  # Enable in-place mode
            output_dir=None,
            multi_mode=False,
            use_local_nfo=self.use_local_nfo,
            extra_images=self.extra_images,
            media_type=self.media_type  # Use same media type
        )
        result = temp_scraper.process_organized_show_inplace(str(show_dir))
        if result:
            print(f"      ✅ Show processing completed: {show_dir_name}")
        else:
            print(f"      ❌ Show processing failed: {show_dir_name}")


def main():
    parser = argparse.ArgumentParser(
        description="Batch Media Scraper for TV Shows",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python batch_scraper.py /path/to/input/dir                    # In-place rename (default)
  python batch_scraper.py /path/to/input/dir --copy            # Copy to ./output
  python batch_scraper.py /path/to/input/dir --output /path/to/output  # Move to specified dir
  python batch_scraper.py /path/to/input/dir --output /path/to/output --copy  # Copy to specified dir
  python batch_scraper.py /path/to/input/dir --inplace         # Force in-place rename
  python batch_scraper.py /path/to/input/dir --multi           # Multi-mode: process all subdirs and loose files

Note: Default behavior is in-place renaming (move and rename in place).
      Use --output to specify output directory for move/copy operations.
      Use --copy to copy files instead of moving them.
      Use --inplace to force in-place renaming (overrides --output).
      Use --multi to process all subdirectories and loose video files in-place.
        """
    )
    parser.add_argument("input_dir", help="Input directory to scan for TV shows")
    parser.add_argument("--output", "-o", help="Output base directory (if not specified, uses in-place mode)")
    parser.add_argument("--config", "-c", help="Configuration file path")
    parser.add_argument("--copy", action="store_true",
                       help="Copy files instead of moving them (requires --output)")
    parser.add_argument("--inplace", action="store_true",
                       help="Force in-place renaming mode (ignores --output)")
    parser.add_argument("--multi", action="store_true",
                       help="Multi-mode: process all subdirectories and loose files in-place")
    parser.add_argument("--tmdb-id", type=int,
                       help="TMDB ID for direct lookup (only works with --inplace mode)")
    parser.add_argument("--use-local-nfo", action="store_true",
                       help="Extract TMDB ID from tvshow.nfo file if no --tmdb-id provided")
    parser.add_argument("--type", choices=["movie", "tv"],
                       help="Force media type (default: auto fallback TV->Movie)")
    parser.add_argument("--extra-images", action="store_true",
                       help="Create Extra folder to store additional images (posters, logos, backdrops, fanart). Default: disabled")

    args = parser.parse_args()

    # Validate tmdb-id parameter - it should work in both explicit inplace mode and default inplace mode
    if args.tmdb_id and args.output is not None and not args.inplace:
        parser.error("--tmdb-id can only be used in in-place mode (don't specify --output, or use --inplace)")

    # Determine operation mode based on arguments
    if args.multi:
        # Multi-mode: process all subdirs and loose files
        inplace_rename = False
        copy_files = False
        output_dir = args.input_dir  # Not used in multi mode
        multi_mode = True
    elif args.inplace:
        # Force in-place mode
        inplace_rename = True
        copy_files = False
        output_dir = args.input_dir  # Not used in inplace mode
        multi_mode = False
    elif args.output is None:
        # No output specified, use in-place mode
        inplace_rename = True
        copy_files = False
        output_dir = args.input_dir  # Not used in inplace mode
        multi_mode = False
    else:
        # Output specified, use move/copy mode
        inplace_rename = False
        copy_files = args.copy
        output_dir = args.output
        multi_mode = False

    try:
        scraper = BatchMediaScraper(args.config, copy_files, inplace_rename, output_dir, multi_mode, args.tmdb_id, args.use_local_nfo, args.extra_images, args.type or "tv")
        scraper.run(args.input_dir, output_dir)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
