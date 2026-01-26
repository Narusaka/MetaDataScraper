
import logging
import shutil
import re
from pathlib import Path
from typing import Optional
from src.core.filename_parser import FilenameParser

logger = logging.getLogger(__name__)

class MediaOrganizer:
    def __init__(self, dry_run: bool = False, inplace_rename: bool = False, copy_files: bool = False, pipeline=None):
        self.dry_run = dry_run
        self.inplace_rename = inplace_rename
        self.copy_files = copy_files
        self.pipeline = pipeline 

    def organize(self, show_path: Path, metadata_result: dict, configured_media_type: Optional[str] = None):
        """Organize files, download full metadata, and report missing episodes."""
        normalized = metadata_result.get("normalized", {})
        episodes_data = metadata_result.get("source_data", {}).get("translated_episodes", [])
        nfo_data = metadata_result.get("nfo", {})
        episode_nfos = nfo_data.get("episode_nfos", {})
        
        detected_type = normalized.get("media_type") or configured_media_type
        
        # If no internal episodes data (e.g. maybe movie or failed), skip ONLY if truly TV
        if not episodes_data and detected_type == "tv":
             return

        # Map metadata episodes
        meta_ep_map = {(e.get("season_number"), e.get("episode_number")): e for e in episodes_data}
        found_episodes = set()
        
        # 1. Scan and Rename Existing Files
        scanned_files = []
        for file_path in show_path.rglob('*'):
            if file_path.is_file() and (file_path.suffix.lower() in FilenameParser.VIDEO_EXTENSIONS or file_path.suffix.lower() in FilenameParser.SUBTITLE_EXTENSIONS):
                scanned_files.append(file_path)

        for file_path in scanned_files:
            if file_path.name.endswith('.nfo') or 'images' in str(file_path): continue
            
            suffix = file_path.suffix
            
            # Movie Logic
            if detected_type == "movie":
                movie_title = normalized.get("title_zh") or normalized.get("title")
                year = normalized.get("year")
                new_name = f"{movie_title} ({year})"
                new_filename = f"{new_name}{suffix}"
                dest_path = show_path / new_filename
                
                self._move_or_copy(file_path, dest_path)
                continue

            # TV Logic
            ep_info = FilenameParser.parse_episode_info(file_path.name)
            if not ep_info: continue
            
            season, episode = ep_info
            ep_data = meta_ep_map.get((season, episode))
            
            if ep_data:
                found_episodes.add((season, episode))
                
                show_title = normalized.get("title_zh") or normalized.get("title", show_path.name)
                ep_title = ep_data.get("name_zh") or ep_data.get("name", "")
                safe_ep_title = "".join(c for c in ep_title if c not in '/\\:*?"<>|').strip()
                
                new_name = f"{show_title} - S{season:02d}E{episode:02d} - {safe_ep_title}"
                
                # Subtitle language handling
                is_subtitle = suffix.lower() in FilenameParser.SUBTITLE_EXTENSIONS
                if is_subtitle:
                    lang_suffix = FilenameParser.get_subtitle_language_suffix(file_path.name)
                    new_filename = f"{new_name}{lang_suffix}{suffix}"
                else:
                    new_filename = f"{new_name}{suffix}"

                # Destination
                if detected_type == "tv":
                    dest_dir = show_path / f"Season {season:02d}"
                else:
                    dest_dir = show_path
                    
                dest_path = dest_dir / new_filename
                
                if not self.dry_run:
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    self._move_or_copy(file_path, dest_path)
                            
        # 2. Rename Directory
        final_show_path = show_path
        if self.inplace_rename and not self.dry_run:
             final_show_path = self._rename_directory(show_path, normalized)

        # 3. Full Metadata Download & Missing Check
        if detected_type == "tv":
            self._process_full_metadata(final_show_path, meta_ep_map, found_episodes, normalized, episode_nfos)

    def _move_or_copy(self, src: Path, dest: Path):
        if self.dry_run: return
        if src.resolve() == dest.resolve(): return
        
        try:
            if self.copy_files:
                shutil.copy2(str(src), str(dest))
                logger.info(f"Copied: {src.name} -> {dest.name}")
            else:
                shutil.move(str(src), str(dest))
                logger.info(f"Renamed: {src.name} -> {dest.name}")
        except Exception as e:
            logger.error(f"Failed to move/copy {src.name}: {e}")

    def _rename_directory(self, show_path: Path, normalized: dict) -> Path:
        try:
             show_year = normalized.get("year", 0)
             show_title = normalized.get("title_zh") or normalized.get("title", show_path.name)
             safe_title = re.sub(r'[\\/:"*?<>|]', '', show_title).strip()
             new_dir_name = f"{safe_title} ({show_year})"
             new_show_path = show_path.parent / new_dir_name
             
             if show_path.resolve() != new_show_path.resolve():
                 show_path.rename(new_show_path)
                 logger.info(f"Renamed Directory: {show_path.name} -> {new_dir_name}")
                 return new_show_path
        except Exception as e:
             logger.error(f"Failed to rename directory: {e}")
        return show_path

    def _process_full_metadata(self, show_path: Path, meta_ep_map, found_episodes, normalized, episode_nfos):
        missing_eps = []
        logger.info("📡 Processing full metadata for all episodes...")
        
        for (season, episode), ep_data in meta_ep_map.items():
            if season == 0: continue
            
            if (season, episode) not in found_episodes:
                missing_eps.append(f"S{season:02d}E{episode:02d}")
                
            show_title = normalized.get("title_zh") or normalized.get("title", show_path.name)
            ep_title = ep_data.get("name_zh") or ep_data.get("name", "")
            safe_ep_title = "".join(c for c in ep_title if c not in '/\\:*?"<>|').strip()
            
            base_name = f"{show_title} - S{season:02d}E{episode:02d} - {safe_ep_title}"
            dest_dir = show_path / f"Season {season:02d}"
            
            if not self.dry_run:
                dest_dir.mkdir(parents=True, exist_ok=True)
                
                # Write NFO
                ep_xml = episode_nfos.get((season, episode))
                nfo_dest = dest_dir / f"{base_name}.nfo"
                if ep_xml and not nfo_dest.exists():
                     try:
                        nfo_dest.write_text(ep_xml, encoding="utf-8")
                     except Exception as e:
                        pass
                        
                # Download Thumb
                still_path = ep_data.get("still_path")
                if still_path and self.pipeline and self.pipeline.artwork:
                    thumb_dest = dest_dir / f"{base_name}-thumb.jpg"
                    if not thumb_dest.exists():
                         full_url = f"https://image.tmdb.org/t/p/original{still_path}"
                         try:
                            self.pipeline.artwork.download_image(str(thumb_dest), full_url)
                         except: pass

        if missing_eps:
            missing_eps.sort()
            logger.warning(f"⚠️  Missing {len(missing_eps)} Episodes:")
            chunk_size = 10
            for i in range(0, len(missing_eps), chunk_size):
                logger.warning("   " + ", ".join(missing_eps[i:i+chunk_size]))
        else:
            logger.info("✅ All episodes present!")
