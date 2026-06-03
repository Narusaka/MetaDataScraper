
import logging
import shutil
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from src.core.filename_parser import FilenameParser
from src.core.operation_manifest import OperationManifest

logger = logging.getLogger(__name__)

class MediaOrganizer:
    def __init__(self, dry_run: bool = False, inplace_rename: bool = False, copy_files: bool = False, pipeline=None, enable_organize: bool = False, overwrite_images: bool = False, rename_parent_dir: bool = False, task_id: Optional[str] = None):
        self.dry_run = dry_run
        self.inplace_rename = inplace_rename
        self.copy_files = copy_files
        self.pipeline = pipeline 
        self.enable_organize = enable_organize
        self.overwrite_images = overwrite_images
        self.rename_parent_dir = rename_parent_dir
        self.manifest = OperationManifest(task_id)

    def build_plan(self, show_path: Path, metadata_result: dict, configured_media_type: Optional[str] = None, is_group_folder: bool = False) -> dict:
        """Build a dry, auditable plan using the same naming rules as organize()."""
        normalized = metadata_result.get("normalized", {})
        episodes_data = metadata_result.get("source_data", {}).get("translated_episodes", [])
        detected_type = normalized.get("media_type") or configured_media_type
        meta_ep_map = {(e.get("season_number"), e.get("episode_number")): e for e in episodes_data}
        found_episodes = set()
        actions: List[dict] = []
        conflicts: List[dict] = []
        risks: List[dict] = []

        has_seasons = self._has_season_dirs(show_path)
        target_root = self._planned_target_root(show_path, normalized, has_seasons)

        if not self.enable_organize:
            risks.append({"level": "info", "code": "organize_disabled", "message": "File movement is disabled; metadata and images may still be written during execution."})

        if detected_type == "tv" and not episodes_data:
            risks.append({"level": "warning", "code": "tv_no_episode_metadata", "message": "TV metadata has no episode list; episode rename plan cannot be verified."})

        scanned_files = self._scan_media_files(show_path)
        for file_path in scanned_files:
            dest_path = self._planned_destination(file_path, show_path, target_root, detected_type, normalized, meta_ep_map, found_episodes)
            if not dest_path:
                risks.append({"level": "warning", "code": "unmatched_file", "message": f"No metadata episode match for {file_path.name}", "source": str(file_path)})
                continue

            action_type = "copy_file" if self.copy_files else "move_file"
            action = {
                "type": action_type,
                "source": str(file_path),
                "destination": str(dest_path),
                "reversible": True,
                "status": "blocked" if dest_path.exists() and file_path.resolve() != dest_path.resolve() else "ready",
            }
            actions.append(action)
            if action["status"] == "blocked":
                conflicts.append({"source": str(file_path), "destination": str(dest_path), "reason": "destination_exists"})

        should_rename = self.rename_parent_dir or is_group_folder or has_seasons
        if self.inplace_rename and self.enable_organize and should_rename:
            rename_dest = self._planned_renamed_directory(show_path, normalized)
            if rename_dest and show_path.resolve() != rename_dest.resolve():
                actions.append({
                    "type": "rename_dir",
                    "source": str(show_path),
                    "destination": str(rename_dest),
                    "reversible": True,
                    "status": "blocked" if rename_dest.exists() else "ready",
                })
                if rename_dest.exists():
                    conflicts.append({"source": str(show_path), "destination": str(rename_dest), "reason": "destination_exists"})

        missing_eps = self._missing_episodes(meta_ep_map, found_episodes)
        if missing_eps:
            risks.append({"level": "warning", "code": "missing_episodes", "message": f"{len(missing_eps)} expected episodes were not found.", "episodes": missing_eps[:50]})

        image_limits = {}
        if self.pipeline:
            image_limits = self.pipeline.config.get("output", {}).get("image_limit", {})

        plan = {
            "media_type": detected_type,
            "title": normalized.get("title_zh") or normalized.get("title") or show_path.name,
            "year": normalized.get("year"),
            "source_path": str(show_path),
            "target_root": str(target_root),
            "mode": "metadata_only" if not self.enable_organize else ("copy" if self.copy_files else "move"),
            "rollback_available": self.enable_organize,
            "artwork": {
                "extra_images": bool(getattr(self.pipeline, "extra_images", False)) if self.pipeline else False,
                "overwrite_images": self.overwrite_images,
                "limits": image_limits,
            },
            "summary": {
                "actions": len(actions),
                "ready": sum(1 for action in actions if action["status"] == "ready"),
                "blocked": sum(1 for action in actions if action["status"] == "blocked"),
                "conflicts": len(conflicts),
                "risks": len(risks),
                "media_files": len(scanned_files),
                "missing_episodes": len(missing_eps),
            },
            "actions": actions[:200],
            "conflicts": conflicts[:100],
            "risks": risks,
            "missing_episodes": missing_eps[:100],
        }
        return plan

    def build_loose_file_plan(self, files: List[Path], base_dir: Path, show_name: str, metadata_result: dict, media_type: str) -> dict:
        safe_name = FilenameParser.clean_show_name_for_search(show_name)
        target_path = base_dir / safe_name
        actions = []
        conflicts = []
        for file_path in files:
            destination = target_path / file_path.name
            action = {
                "type": "move_file",
                "source": str(file_path),
                "destination": str(destination),
                "reversible": True,
                "status": "blocked" if destination.exists() and file_path.resolve() != destination.resolve() else "ready",
            }
            actions.append(action)
            if action["status"] == "blocked":
                conflicts.append({"source": str(file_path), "destination": str(destination), "reason": "destination_exists"})

        grouped_plan = self.build_plan(target_path, metadata_result, configured_media_type=media_type, is_group_folder=True) if target_path.exists() else {}
        risks = grouped_plan.get("risks", [])
        if not target_path.exists():
            actions.insert(0, {
                "type": "create_dir",
                "source": None,
                "destination": str(target_path),
                "reversible": True,
                "status": "ready",
            })

        return {
            "media_type": media_type,
            "title": metadata_result.get("normalized", {}).get("title_zh") or metadata_result.get("normalized", {}).get("title") or safe_name,
            "source_path": str(base_dir),
            "target_root": str(target_path),
            "mode": "loose_file_group",
            "rollback_available": True,
            "summary": {
                "actions": len(actions) + grouped_plan.get("summary", {}).get("actions", 0),
                "ready": sum(1 for action in actions if action["status"] == "ready") + grouped_plan.get("summary", {}).get("ready", 0),
                "blocked": sum(1 for action in actions if action["status"] == "blocked") + grouped_plan.get("summary", {}).get("blocked", 0),
                "conflicts": len(conflicts) + grouped_plan.get("summary", {}).get("conflicts", 0),
                "risks": len(risks),
                "media_files": len(files),
                "missing_episodes": grouped_plan.get("summary", {}).get("missing_episodes", 0),
            },
            "actions": (actions + grouped_plan.get("actions", []))[:200],
            "conflicts": (conflicts + grouped_plan.get("conflicts", []))[:100],
            "risks": risks,
            "missing_episodes": grouped_plan.get("missing_episodes", []),
            "artwork": grouped_plan.get("artwork", {}),
        }

    def organize(self, show_path: Path, metadata_result: dict, configured_media_type: Optional[str] = None, is_group_folder: bool = False):
        """Organize files, download full metadata, and report missing episodes."""
        normalized = metadata_result.get("normalized", {})
        episodes_data = metadata_result.get("source_data", {}).get("translated_episodes", [])
        nfo_data = metadata_result.get("nfo", {})
        episode_nfos = nfo_data.get("episode_nfos", {})
        season_nfos = nfo_data.get("season_nfos", {})
        
        detected_type = normalized.get("media_type") or configured_media_type
        
        # If no internal episodes data (e.g. maybe movie or failed), skip ONLY if truly TV
        if not episodes_data and detected_type == "tv":
             return

        # Map metadata episodes
        meta_ep_map = {(e.get("season_number"), e.get("episode_number")): e for e in episodes_data}
        found_episodes = set()
        
        # 0. Determine Mode (Rename Self vs Create Sibling)
        # Check if current directory already has Season structure
        has_seasons = self._has_season_dirs(show_path)

        # Logic: 
        # - Mixed/Flat folder (No Seasons) -> Create Sibling Folder (Safe Mode)
        # - Already Structured (Has Seasons) -> Rename In-Place (Scenario 1)
        
        target_root = show_path
        
        if self.inplace_rename and not self.dry_run and not has_seasons and self.enable_organize:
             # Scenario 2: Create Sibling
             target_root = self._planned_renamed_directory(show_path, normalized)
             target_existed = target_root.exists()
             target_root.mkdir(parents=True, exist_ok=True)
             if not target_existed:
                 self.manifest.record("create_dir", None, target_root)
             logger.info(f"Organize: Creating sibling directory: {target_root}")
        
        if not self.enable_organize:
             logger.info(f"Organize: File movement is DISABLED. Skipping rename/move for video/subtitle files.")
             final_show_path = show_path 
        else:
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
                     dest_path = self._planned_movie_destination(file_path, target_root, normalized)
                     
                     self._move_or_copy(file_path, dest_path)
                     continue
    
                 # TV Logic
                 ep_info = FilenameParser.parse_episode_info(file_path.name)
                 if not ep_info: continue
                 
                 season, episode = ep_info
                 ep_data = meta_ep_map.get((season, episode))
                 
                 if ep_data:
                     found_episodes.add((season, episode))
                     
                     dest_path = self._planned_episode_destination(file_path, target_root, normalized, season, episode, ep_data)
                     
                     if not self.dry_run:
                         dest_dir = dest_path.parent
                         dest_existed = dest_dir.exists()
                         dest_dir.mkdir(parents=True, exist_ok=True)
                         if not dest_existed:
                             self.manifest.record("create_dir", None, dest_dir)
                         self._move_or_copy(file_path, dest_path)

        # 2. Rename Directory
        # Condition: 
        # - In-place rename enabled AND (Rename Parent toggle is ON OR it's a folder we just created for loose files OR it has Season structure)
        final_show_path = target_root
        should_rename = (self.rename_parent_dir or is_group_folder or has_seasons)
        
        if self.inplace_rename and not self.dry_run and self.enable_organize and should_rename:
             final_show_path = self._rename_directory(show_path, normalized)

        # 3. Full Metadata Download & Missing Check
        if detected_type == "tv":
            self._process_full_metadata(final_show_path, meta_ep_map, found_episodes, normalized, episode_nfos, season_nfos)

    def _move_or_copy(self, src: Path, dest: Path):
        if self.dry_run: return
        if src.resolve() == dest.resolve(): return
        
        try:
            if dest.exists():
                logger.warning(f"⚠️ Skip move: Destination already exists: {dest.name}")
                return

            if self.copy_files:
                shutil.copy2(str(src), str(dest))
                self.manifest.record("copy_file", src, dest)
                logger.info(f"Copied: {src.name} -> {dest.name}")
            else:
                shutil.move(str(src), str(dest))
                self.manifest.record("move_file", src, dest)
                logger.info(f"Renamed: {src.name} -> {dest.name}")
        except Exception as e:
            logger.error(f"Failed to move/copy {src.name}: {e}")

    def _rename_directory(self, show_path: Path, normalized: dict) -> Path:
        try:
             new_show_path = self._planned_renamed_directory(show_path, normalized)
             
             if show_path.resolve() != new_show_path.resolve():
                 show_path.rename(new_show_path)
                 self.manifest.record("rename_dir", show_path, new_show_path)
                 logger.info(f"Renamed Directory: {show_path.name} -> {new_show_path.name}")
                 return new_show_path
        except Exception as e:
             logger.error(f"Failed to rename directory: {e}")
        return show_path

    def _has_season_dirs(self, show_path: Path) -> bool:
        try:
            root_sub_dirs = [d.name.lower() for d in show_path.iterdir() if d.is_dir()]
            return any(re.match(r'^season\s*\d+$', d) for d in root_sub_dirs)
        except OSError:
            return False

    def _scan_media_files(self, show_path: Path) -> List[Path]:
        if not show_path.exists():
            return []
        return [
            file_path
            for file_path in show_path.rglob("*")
            if file_path.is_file()
            and (file_path.suffix.lower() in FilenameParser.VIDEO_EXTENSIONS or file_path.suffix.lower() in FilenameParser.SUBTITLE_EXTENSIONS)
            and not file_path.name.endswith(".nfo")
            and "images" not in str(file_path)
        ]

    def _safe_title(self, value: str) -> str:
        return re.sub(r'[\\/:"*?<>|]', '', value or "").strip()

    def _planned_renamed_directory(self, show_path: Path, normalized: dict) -> Path:
        show_year = normalized.get("year", 0)
        show_title = normalized.get("title_zh") or normalized.get("title", show_path.name)
        safe_title = self._safe_title(show_title)
        return show_path.parent / f"{safe_title} ({show_year})"

    def _planned_target_root(self, show_path: Path, normalized: dict, has_seasons: bool) -> Path:
        if self.inplace_rename and self.enable_organize and not has_seasons:
            return self._planned_renamed_directory(show_path, normalized)
        return show_path

    def _planned_movie_destination(self, file_path: Path, target_root: Path, normalized: dict) -> Path:
        movie_title = normalized.get("title_zh") or normalized.get("title")
        year = normalized.get("year")
        return target_root / f"{movie_title} ({year}){file_path.suffix}"

    def _planned_episode_destination(self, file_path: Path, target_root: Path, normalized: dict, season: int, episode: int, ep_data: dict) -> Path:
        show_title = normalized.get("title_zh") or normalized.get("title", target_root.name)
        ep_title = ep_data.get("name_zh") or ep_data.get("name", "")
        safe_ep_title = self._safe_title(ep_title)
        new_name = f"{show_title} - S{season:02d}E{episode:02d} - {safe_ep_title}"
        suffix = file_path.suffix
        if suffix.lower() in FilenameParser.SUBTITLE_EXTENSIONS:
            lang_suffix = FilenameParser.get_subtitle_language_suffix(file_path.name)
            new_filename = f"{new_name}{lang_suffix}{suffix}"
        else:
            new_filename = f"{new_name}{suffix}"
        return target_root / f"Season {season:02d}" / new_filename

    def _planned_destination(self, file_path: Path, show_path: Path, target_root: Path, detected_type: Optional[str], normalized: dict, meta_ep_map: Dict[Tuple[int, int], dict], found_episodes: set) -> Optional[Path]:
        if detected_type == "movie":
            return self._planned_movie_destination(file_path, target_root, normalized)
        ep_info = FilenameParser.parse_episode_info(file_path.name)
        if not ep_info:
            return None
        season, episode = ep_info
        ep_data = meta_ep_map.get((season, episode))
        if not ep_data:
            return None
        found_episodes.add((season, episode))
        return self._planned_episode_destination(file_path, target_root, normalized, season, episode, ep_data)

    def _missing_episodes(self, meta_ep_map: Dict[Tuple[int, int], dict], found_episodes: set) -> List[str]:
        missing = []
        for season, episode in meta_ep_map.keys():
            if season == 0:
                continue
            if (season, episode) not in found_episodes:
                missing.append(f"S{season:02d}E{episode:02d}")
        return sorted(missing)

    def _process_full_metadata(self, show_path: Path, meta_ep_map, found_episodes, normalized, episode_nfos, season_nfos=None):
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
                dest_existed = dest_dir.exists()
                dest_dir.mkdir(parents=True, exist_ok=True)
                if not dest_existed:
                    self.manifest.record("create_dir", None, dest_dir)
                
                # Write Season NFO if not exists
                if season_nfos and season in season_nfos:
                    s_xml = season_nfos[season]
                    s_nfo_dest = dest_dir / "season.nfo"
                    if not s_nfo_dest.exists():
                        try:
                            s_nfo_dest.write_text(s_xml, encoding="utf-8")
                            self.manifest.record("create_file", None, s_nfo_dest)
                        except: pass

                # Write NFO
                ep_xml = episode_nfos.get((season, episode))
                nfo_dest = dest_dir / f"{base_name}.nfo"
                if ep_xml and not nfo_dest.exists():
                     try:
                        nfo_dest.write_text(ep_xml, encoding="utf-8")
                        self.manifest.record("create_file", None, nfo_dest)
                     except Exception as e:
                        pass
                        
                # Download Thumb
                still_path = ep_data.get("still_path")
                if still_path and self.pipeline and self.pipeline.artwork:
                    thumb_dest = dest_dir / f"{base_name}-thumb.jpg"
                    if self.overwrite_images or not thumb_dest.exists():
                         full_url = f"https://image.tmdb.org/t/p/original{still_path}"
                         existed = thumb_dest.exists()
                         try:
                            if self.pipeline.artwork.download_image(str(thumb_dest), full_url):
                                self.manifest.record("overwrite_file" if existed else "create_file", None, thumb_dest)
                         except: pass

        if missing_eps:
            missing_eps.sort()
            logger.warning(f"⚠️  Missing {len(missing_eps)} Episodes:")
            chunk_size = 10
            for i in range(0, len(missing_eps), chunk_size):
                logger.warning("   " + ", ".join(missing_eps[i:i+chunk_size]))
        else:
            logger.info("✅ All episodes present!")
