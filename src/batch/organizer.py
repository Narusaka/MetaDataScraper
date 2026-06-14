
import logging
import os
import shutil
import tempfile
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from src.core.filename_parser import FilenameParser
from src.core.path_filters import is_hidden_path
from src.core.operation_manifest import OperationManifest
from src.core.filesystem import FileSystemManager
from src.core.cancellation import raise_if_cancelled

logger = logging.getLogger(__name__)


class OrganizerExecutionError(RuntimeError):
    def __init__(self, stage: str, action: str, source: Optional[Path], destination: Optional[Path], cause: Exception):
        self.stage = stage
        self.action = action
        self.source = str(source) if source is not None else None
        self.destination = str(destination) if destination is not None else None
        self.cause = cause
        super().__init__(f"{action} failed at {stage}: {cause}")

    def as_dict(self) -> dict:
        return {
            "stage": self.stage,
            "action": self.action,
            "source": self.source,
            "destination": self.destination,
            "cause": str(self.cause),
        }


class MediaOrganizer:
    CONFLICT_STRATEGIES = {"error", "skip", "suffix", "overwrite"}
    REVERSIBLE_ACTIONS = {
        "move_file",
        "copy_file",
        "rename_dir",
        "create_file",
        "create_dir",
        "overwrite_file",
        "replace_file",
    }

    def __init__(self, dry_run: bool = False, inplace_rename: bool = False, copy_files: bool = False, pipeline=None, enable_organize: bool = False, overwrite_images: bool = False, rename_parent_dir: bool = False, conflict_strategy: str = "error", task_id: Optional[str] = None, cancel_event=None, operation_scope: str = "full"):
        self.dry_run = dry_run
        self.inplace_rename = inplace_rename
        self.copy_files = copy_files
        self.pipeline = pipeline 
        self.enable_organize = enable_organize
        self.overwrite_images = overwrite_images
        self.rename_parent_dir = rename_parent_dir
        self.conflict_strategy = conflict_strategy if conflict_strategy in self.CONFLICT_STRATEGIES else "error"
        self.manifest = OperationManifest(task_id)
        self.cancel_event = cancel_event
        self.operation_scope = operation_scope if operation_scope in {"full", "nfo_only", "artwork_only", "organize_only"} else "full"

    def _checkpoint(self, stage: str) -> None:
        raise_if_cancelled(getattr(self, "cancel_event", None), stage)

    def _emit_operation(
        self,
        event_type: str,
        item_id: Optional[str],
        action: str,
        source: Optional[Path],
        destination: Path,
        stage: str,
        **details,
    ) -> None:
        if not self.manifest.task_id or not item_id:
            return
        from src.server.task_events import task_event_store

        operation = {
            "stage": stage,
            "action": action,
            "source": str(source) if source is not None else None,
            "destination": str(destination),
            **details,
        }
        task_event_store.emit(
            self.manifest.task_id,
            event_type,
            {"operation": operation},
            item_id=item_id,
        )

    def _record_failed_operation(
        self,
        action: str,
        source: Optional[Path],
        destination: Path,
        stage: str,
        error: Exception,
        extra: Optional[dict] = None,
    ) -> None:
        try:
            self.manifest.record(
                action,
                source,
                destination,
                status="failed",
                extra={"error": str(error), "stage": stage, **(extra or {})},
            )
        except Exception:
            logger.exception("Failed to persist operation failure evidence for %s", destination)

    def _ensure_directory(self, directory: Path, item_id: Optional[str], stage: str) -> None:
        if directory.exists():
            return
        self._emit_operation("operation.started", item_id, "create_dir", None, directory, stage)
        try:
            directory.mkdir(parents=True, exist_ok=True)
            self.manifest.record("create_dir", None, directory)
        except Exception as exc:
            self._record_failed_operation("create_dir", None, directory, stage, exc)
            self._emit_operation(
                "operation.failed",
                item_id,
                "create_dir",
                None,
                directory,
                stage,
                error=str(exc),
            )
            raise OrganizerExecutionError(stage, "create_dir", None, directory, exc) from exc
        self._emit_operation("operation.completed", item_id, "create_dir", None, directory, stage)

    def _unique_destination(self, destination: Path, reserved: Optional[set] = None) -> Path:
        reserved = reserved or set()
        counter = 1
        candidate = destination
        while candidate.exists() or str(candidate.resolve(strict=False)) in reserved:
            candidate = destination.with_name(f"{destination.stem} ({counter}){destination.suffix}")
            counter += 1
        return candidate

    def _resolve_file_action(self, source: Path, destination: Path, action_type: str, reserved: Optional[set] = None) -> Tuple[dict, Optional[dict]]:
        reserved = reserved if reserved is not None else set()
        original_destination = destination
        destination_key = str(destination.resolve(strict=False))
        collision = (
            source.resolve(strict=False) != destination.resolve(strict=False)
            and (destination.exists() or destination_key in reserved)
        )
        action = {
            "type": action_type,
            "source": str(source),
            "destination": str(destination),
            "required": True,
            "reversible": True,
            "status": "ready",
        }
        conflict = None
        if collision:
            conflict = {
                "source": str(source),
                "destination": str(original_destination),
                "reason": "destination_exists" if destination.exists() else "planned_destination_collision",
                "strategy": self.conflict_strategy,
            }
            if self.conflict_strategy == "skip":
                action["status"] = "skipped"
                action["resolution"] = "skip"
                conflict["resolution"] = "skipped"
            elif self.conflict_strategy == "suffix":
                destination = self._unique_destination(destination, reserved)
                action["destination"] = str(destination)
                action["original_destination"] = str(original_destination)
                action["resolution"] = "suffix"
                conflict["resolution"] = "renamed"
                conflict["resolved_destination"] = str(destination)
            elif self.conflict_strategy == "overwrite":
                action["type"] = "overwrite_file" if action_type == "copy_file" else "replace_file"
                action["resolution"] = "overwrite_with_backup"
                conflict["resolution"] = "overwrite_with_backup"
            else:
                action["status"] = "blocked"
                action["resolution"] = "manual_required"
                conflict["resolution"] = "blocked"
        if action["status"] == "ready":
            reserved.add(str(Path(action["destination"]).resolve(strict=False)))
        return action, conflict

    def _resolve_directory_action(self, source: Path, destination: Path) -> Tuple[dict, Optional[dict]]:
        action = {
            "type": "rename_dir",
            "source": str(source),
            "destination": str(destination),
            "required": True,
            "reversible": True,
            "status": "ready",
        }
        if not destination.exists():
            return action, None
        conflict = {
            "source": str(source),
            "destination": str(destination),
            "reason": "destination_exists",
            "strategy": self.conflict_strategy,
        }
        if self.conflict_strategy == "skip":
            action["status"] = "skipped"
            action["resolution"] = "skip"
            conflict["resolution"] = "skipped"
        elif self.conflict_strategy == "suffix":
            resolved = self._unique_destination(destination)
            action["destination"] = str(resolved)
            action["original_destination"] = str(destination)
            action["resolution"] = "suffix"
            conflict["resolution"] = "renamed"
            conflict["resolved_destination"] = str(resolved)
        else:
            action["status"] = "blocked"
            action["resolution"] = "directory_merge_not_supported" if self.conflict_strategy == "overwrite" else "manual_required"
            conflict["resolution"] = "blocked"
            if self.conflict_strategy == "overwrite":
                conflict["reason"] = "directory_overwrite_unsupported"
        return action, conflict

    def build_plan(self, show_path: Path, metadata_result: dict, configured_media_type: Optional[str] = None, is_group_folder: bool = False) -> dict:
        """Build a dry, auditable plan using the same naming rules as organize()."""
        normalized = metadata_result.get("normalized", {})
        episodes_data = metadata_result.get("source_data", {}).get("translated_episodes", [])
        nfo_data = metadata_result.get("nfo", {})
        detected_type = normalized.get("media_type") or configured_media_type
        meta_ep_map = {(e.get("season_number"), e.get("episode_number")): e for e in episodes_data}
        found_episodes = set()
        actions: List[dict] = []
        conflicts: List[dict] = []
        risks: List[dict] = []
        reserved_destinations: set = set()
        episode_sources: Dict[Tuple[int, int], List[str]] = {}

        has_seasons = self._has_season_dirs(show_path)
        target_root = self._planned_target_root(show_path, normalized, has_seasons)

        if not self.enable_organize:
            risks.append({"level": "info", "code": "organize_disabled", "message": "File movement is disabled; metadata and images may still be written during execution."})

        if detected_type == "tv" and not episodes_data:
            risks.append({"level": "warning", "code": "tv_no_episode_metadata", "message": "TV metadata has no episode list; episode rename plan cannot be verified."})

        scanned_files = self._scan_media_files(show_path)
        for file_path in scanned_files:
            if detected_type == "tv" and file_path.suffix.lower() in FilenameParser.VIDEO_EXTENSIONS:
                ep_info = FilenameParser.parse_episode_info(file_path.name)
                if not ep_info:
                    risks.append({
                        "level": "warning",
                        "code": "unparseable_episode_file",
                        "message": f"Could not identify a season and episode number for {file_path.name}.",
                        "source": str(file_path),
                    })
                else:
                    episode_sources.setdefault(ep_info, []).append(str(file_path))
                    if ep_info in meta_ep_map:
                        found_episodes.add(ep_info)
                    else:
                        risks.append({
                            "level": "warning",
                            "code": "episode_not_in_metadata",
                            "message": f"{file_path.name} maps to S{ep_info[0]:02d}E{ep_info[1]:02d}, which is absent from provider metadata.",
                            "source": str(file_path),
                        })

            if not self.enable_organize or self.operation_scope not in {"full", "organize_only"}:
                continue

            dest_path = self._planned_destination(file_path, show_path, target_root, detected_type, normalized, meta_ep_map, found_episodes)
            if not dest_path:
                risks.append({"level": "warning", "code": "unmatched_file", "message": f"No metadata episode match for {file_path.name}", "source": str(file_path)})
                continue

            action_type = "copy_file" if self.copy_files else "move_file"
            action, conflict = self._resolve_file_action(file_path, dest_path, action_type, reserved_destinations)
            actions.append(action)
            if conflict:
                conflicts.append(conflict)

        for (season, episode), sources in sorted(episode_sources.items()):
            if len(sources) > 1:
                risks.append({
                    "level": "error",
                    "code": "duplicate_episode_files",
                    "message": f"{len(sources)} video files claim S{season:02d}E{episode:02d}.",
                    "episode": f"S{season:02d}E{episode:02d}",
                    "sources": sources[:20],
                })
                actions.append({
                    "type": "manual_review",
                    "source": sources[0],
                    "destination": None,
                    "kind": "duplicate_episode",
                    "required": True,
                    "reversible": False,
                    "status": "blocked",
                    "reason": "duplicate_episode_files",
                    "episode": f"S{season:02d}E{episode:02d}",
                    "sources": sources[:20],
                })

        should_rename = self.rename_parent_dir or is_group_folder or has_seasons
        if self.inplace_rename and self.enable_organize and self.operation_scope in {"full", "organize_only"} and should_rename:
            rename_dest = self._planned_renamed_directory(show_path, normalized)
            if rename_dest and show_path.resolve() != rename_dest.resolve():
                rename_action, conflict = self._resolve_directory_action(show_path, rename_dest)
                actions.append(rename_action)
                if conflict:
                    conflicts.append(conflict)

        missing_eps = self._missing_episodes(meta_ep_map, found_episodes)
        if missing_eps:
            risks.append({"level": "warning", "code": "missing_episodes", "message": f"{len(missing_eps)} expected episodes were not found.", "episodes": missing_eps[:50]})

        diagnostics = []
        source_issues = metadata_result.get("source_data", {}).get("issues") or []
        nfo_issues = nfo_data.get("issues") or []
        for issue in list(source_issues) + list(nfo_issues):
            if not isinstance(issue, dict):
                continue
            diagnostic = {
                **issue,
                "level": issue.get("level") if issue.get("level") in {"info", "warning", "error"} else "warning",
                "code": issue.get("code") or "metadata_diagnostic",
                "message": issue.get("message") or "Metadata processing reported an incomplete result.",
            }
            diagnostics.append(diagnostic)
            risks.append(diagnostic)
            if diagnostic["level"] == "error":
                actions.append({
                    "type": "manual_review",
                    "source": str(show_path),
                    "destination": None,
                    "kind": "metadata_diagnostic",
                    "required": True,
                    "reversible": False,
                    "status": "blocked",
                    "reason": diagnostic["code"],
                    "diagnostic": diagnostic,
                })

        image_limits = {}
        artwork_policy = {}
        if self.pipeline:
            image_limits = self.pipeline.config.get("output", {}).get("image_limit", {})
            artwork_policy = self.pipeline.config.get("output", {}).get("artwork_policy", {})

        metadata_actions = self._planned_metadata_actions(
            target_root,
            normalized,
            detected_type,
            episodes_data,
            nfo_data,
            present_episode_keys=found_episodes,
        )
        if self.operation_scope == "nfo_only":
            metadata_actions = [action for action in metadata_actions if "nfo" in str(action.get("kind") or "")]
        elif self.operation_scope == "artwork_only":
            metadata_actions = [action for action in metadata_actions if str(action.get("kind") or "").startswith("artwork")]
        elif self.operation_scope == "organize_only":
            metadata_actions = []
        actions.extend(metadata_actions)

        plan = {
            "media_type": detected_type,
            "title": normalized.get("title_zh") or normalized.get("title") or show_path.name,
            "year": normalized.get("year"),
            "source_path": str(show_path),
            "target_root": str(target_root),
            "mode": "metadata_only" if not self.enable_organize else ("copy" if self.copy_files else "move"),
            "conflict_strategy": self.conflict_strategy,
            "operation_scope": self.operation_scope,
            "rollback_available": self._plan_has_reversible_actions(actions),
            "artwork": {
                "extra_images": bool(getattr(self.pipeline, "extra_images", False)) if self.pipeline else False,
                "overwrite_images": self.overwrite_images,
                "limits": image_limits,
                "selection_policy": artwork_policy,
            },
            "nfo": {
                "policy": nfo_data.get("policy", {}),
                "episode_sidecars": "present_only",
                "present_episodes": len(found_episodes),
                "diagnostic_count": len(diagnostics),
            },
            "diagnostics": diagnostics,
            "summary": {
                "actions": len(actions),
                "ready": sum(1 for action in actions if action["status"] == "ready"),
                "blocked": sum(1 for action in actions if action["status"] == "blocked"),
                "skipped": sum(1 for action in actions if action["status"] == "skipped"),
                "resolved_conflicts": sum(1 for conflict in conflicts if conflict.get("resolution") not in {"blocked", None}),
                "conflicts": len(conflicts),
                "risks": len(risks),
                "media_files": len(scanned_files),
                "missing_episodes": len(missing_eps),
                "metadata_writes": len(metadata_actions),
            },
            "actions": actions,
            "conflicts": conflicts,
            "risks": risks,
            "missing_episodes": missing_eps,
            "review": self._build_plan_review(actions, conflicts, risks),
        }
        return plan

    def build_loose_file_plan(self, files: List[Path], base_dir: Path, show_name: str, metadata_result: dict, media_type: str) -> dict:
        safe_name = FilenameParser.clean_show_name_for_search(show_name)
        target_path = base_dir / safe_name
        actions = []
        conflicts = []
        risks = []
        reserved_destinations: set = set()
        can_group_files = self.operation_scope in {"full", "organize_only"}
        if can_group_files:
            for file_path in files:
                destination = target_path / file_path.name
                action, conflict = self._resolve_file_action(file_path, destination, "move_file", reserved_destinations)
                actions.append(action)
                if conflict:
                    conflicts.append(conflict)
        else:
            risks.append({
                "level": "error",
                "code": "loose_scope_requires_grouped_directory",
                "message": "NFO-only and artwork-only tasks require media to already be inside a dedicated directory.",
            })
            actions.append({
                "type": "group_loose_files",
                "source": str(base_dir),
                "destination": str(target_path),
                "required": True,
                "reversible": True,
                "status": "blocked",
                "resolution": "run_full_or_files_scope_first",
            })

        grouped_plan = self.build_plan(target_path, metadata_result, configured_media_type=media_type, is_group_folder=True) if target_path.exists() else {}
        risks.extend(grouped_plan.get("risks", []))
        if can_group_files and not target_path.exists():
            actions.insert(0, {
                "type": "create_dir",
                "source": None,
                "destination": str(target_path),
                "required": True,
                "reversible": True,
                "status": "ready",
            })

        return {
            "media_type": media_type,
            "title": metadata_result.get("normalized", {}).get("title_zh") or metadata_result.get("normalized", {}).get("title") or safe_name,
            "source_path": str(base_dir),
            "target_root": str(target_path),
            "mode": "loose_file_group",
            "operation_scope": self.operation_scope,
            "conflict_strategy": self.conflict_strategy,
            "rollback_available": self._plan_has_reversible_actions(
                actions + grouped_plan.get("actions", [])
            ),
            "summary": {
                "actions": len(actions) + grouped_plan.get("summary", {}).get("actions", 0),
                "ready": sum(1 for action in actions if action["status"] == "ready") + grouped_plan.get("summary", {}).get("ready", 0),
                "blocked": sum(1 for action in actions if action["status"] == "blocked") + grouped_plan.get("summary", {}).get("blocked", 0),
                "skipped": sum(1 for action in actions if action["status"] == "skipped") + grouped_plan.get("summary", {}).get("skipped", 0),
                "resolved_conflicts": sum(1 for conflict in conflicts if conflict.get("resolution") not in {"blocked", None}) + grouped_plan.get("summary", {}).get("resolved_conflicts", 0),
                "conflicts": len(conflicts) + grouped_plan.get("summary", {}).get("conflicts", 0),
                "risks": len(risks),
                "media_files": len(files),
                "missing_episodes": grouped_plan.get("summary", {}).get("missing_episodes", 0),
                "metadata_writes": grouped_plan.get("summary", {}).get("metadata_writes", 0),
            },
            "actions": actions + grouped_plan.get("actions", []),
            "conflicts": conflicts + grouped_plan.get("conflicts", []),
            "risks": risks,
            "missing_episodes": grouped_plan.get("missing_episodes", []),
            "artwork": grouped_plan.get("artwork", {}),
            "review": self._build_plan_review(
                actions + grouped_plan.get("actions", []),
                conflicts + grouped_plan.get("conflicts", []),
                risks,
            ),
        }

    def _planned_file_write_action(self, destination: Path, kind: str, required: bool = True) -> dict:
        exists = destination.exists()
        return {
            "type": "overwrite_file" if exists else "create_file",
            "source": None,
            "destination": str(destination),
            "kind": kind,
            "required": required,
            "reversible": True,
            "status": "ready",
        }

    def _plan_has_reversible_actions(self, actions: List[dict]) -> bool:
        return any(
            action.get("status") == "ready"
            and action.get("reversible") is not False
            and action.get("type") in self.REVERSIBLE_ACTIONS
            for action in actions
        )

    def _planned_metadata_actions(self, target_root: Path, normalized: dict, detected_type: Optional[str], episodes_data: List[dict], nfo_data: dict, present_episode_keys: Optional[set] = None) -> List[dict]:
        actions: List[dict] = []
        present_episode_keys = present_episode_keys or set()
        if not normalized:
            return actions

        title = self._safe_title(normalized.get("title_zh") or normalized.get("title") or target_root.name)
        year = normalized.get("year", 0)
        if detected_type == "movie":
            actions.append(self._planned_file_write_action(target_root / f"{title} ({year}).nfo", "main_nfo"))
        elif detected_type == "tv":
            actions.append(self._planned_file_write_action(target_root / "tvshow.nfo", "main_nfo"))
            season_nfos = nfo_data.get("season_nfos", {}) if isinstance(nfo_data, dict) else {}
            episode_nfos = nfo_data.get("episode_nfos", {}) if isinstance(nfo_data, dict) else {}
            seasons = sorted({
                season
                for season, episode in present_episode_keys
                if season and episode
            })
            for season in seasons:
                season_dir = target_root / f"Season {int(season):02d}"
                if season_nfos and season in season_nfos:
                    actions.append(self._planned_file_write_action(season_dir / "season.nfo", "season_nfo"))
            for episode_data in episodes_data:
                season = episode_data.get("season_number", 0)
                episode = episode_data.get("episode_number", 0)
                if not season or season == 0 or not episode:
                    continue
                if (season, episode) not in present_episode_keys:
                    continue
                if episode_nfos and (season, episode) not in episode_nfos:
                    continue
                ep_title = episode_data.get("name_zh") or episode_data.get("name", "")
                safe_ep_title = "".join(c for c in ep_title if c not in '/\\:*?"<>|').strip()
                base_name = f"{title} - S{int(season):02d}E{int(episode):02d} - {safe_ep_title}"
                actions.append(self._planned_file_write_action(target_root / f"Season {int(season):02d}" / f"{base_name}.nfo", "episode_nfo"))

        actions.append(self._planned_file_write_action(target_root / "artwork-manifest.json", "artwork_manifest", required=False))
        for filename, kind in [
            ("poster.jpg", "poster"),
            ("fanart.jpg", "fanart"),
            ("banner.jpg", "banner"),
            ("clearlogo.png", "logo"),
            ("clearart.png", "clearart"),
        ]:
            actions.append(self._planned_file_write_action(target_root / filename, f"artwork:{kind}", required=False))
        return actions

    def has_blockers(self, plan: dict) -> bool:
        summary = plan.get("summary", {})
        return summary.get("blocked", 0) > 0

    def _build_plan_review(self, actions: List[dict], conflicts: List[dict], risks: List[dict]) -> dict:
        reasons = []
        seen = set()

        def review_key(record: dict, fallback: str) -> tuple:
            code = record.get("code") or record.get("reason") or fallback
            episode = record.get("episode")
            if code == "duplicate_episode_files" and episode:
                return code, episode
            return code, episode, record.get("source"), record.get("destination")

        for risk in risks:
            if risk.get("level") != "error":
                continue
            key = review_key(risk, "error_risk")
            if key in seen:
                continue
            seen.add(key)
            reasons.append({
                key: value
                for key, value in risk.items()
                if key in {"level", "code", "message", "episode", "source", "sources"}
            })

        for conflict in conflicts:
            if conflict.get("resolution") != "blocked":
                continue
            key = review_key(conflict, "blocked_conflict")
            if key in seen:
                continue
            seen.add(key)
            reasons.append({
                "level": "error",
                "code": conflict.get("reason") or "blocked_conflict",
                "message": f"Destination conflict requires review: {conflict.get('destination')}",
                "source": conflict.get("source"),
                "destination": conflict.get("destination"),
                "resolution": conflict.get("resolution"),
            })

        for action in actions:
            if action.get("status") != "blocked" or action.get("type") != "manual_review":
                continue
            key = review_key(action, "manual_review")
            if key in seen:
                continue
            seen.add(key)
            reasons.append({
                "level": "error",
                "code": action.get("reason") or "manual_review",
                "message": "This action requires manual review before execution.",
                "episode": action.get("episode"),
                "source": action.get("source"),
                "sources": action.get("sources"),
            })

        return {
            "required": bool(reasons),
            "status": "manual_review" if reasons else "ready",
            "reason_count": len(reasons),
            "reasons": reasons[:20],
        }

    def organize(self, show_path: Path, metadata_result: dict, configured_media_type: Optional[str] = None, is_group_folder: bool = False, item_id: Optional[str] = None):
        """Organize files, download full metadata, and report missing episodes."""
        self._checkpoint("organize.start")
        scope_allows_organize = self.operation_scope in {"full", "organize_only"}
        scope_allows_nfo = self.operation_scope in {"full", "nfo_only"}
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
        
        if self.inplace_rename and not self.dry_run and not has_seasons and self.enable_organize and scope_allows_organize:
             # Scenario 2: Create Sibling
             target_root = self._planned_renamed_directory(show_path, normalized)
             self._ensure_directory(target_root, item_id, "organize.create_target")
             logger.info(f"Organize: Creating sibling directory: {target_root}")
        
        if not self.enable_organize or not scope_allows_organize:
             logger.info(f"Organize: File movement is DISABLED. Skipping rename/move for video/subtitle files.")
             final_show_path = show_path 
        else:
             # 1. Scan and Rename Existing Files
             scanned_files = []
             for file_path in show_path.rglob('*'):
                 if file_path.is_file() and not is_hidden_path(file_path) and (file_path.suffix.lower() in FilenameParser.VIDEO_EXTENSIONS or file_path.suffix.lower() in FilenameParser.SUBTITLE_EXTENSIONS):
                     scanned_files.append(file_path)
    
             for file_path in scanned_files:
                 self._checkpoint("organize.files")
                 if file_path.name.endswith('.nfo') or 'images' in str(file_path): continue
                 
                 suffix = file_path.suffix
                 
                 # Movie Logic
                 if detected_type == "movie":
                     dest_path = self._planned_movie_destination(file_path, target_root, normalized)
                     
                     self._move_or_copy(file_path, dest_path, item_id=item_id)
                     continue
    
                 # TV Logic
                 ep_info = FilenameParser.parse_episode_info(file_path.name)
                 if not ep_info: continue
                 
                 season, episode = ep_info
                 ep_data = meta_ep_map.get((season, episode))
                 
                 if ep_data:
                     if file_path.suffix.lower() in FilenameParser.VIDEO_EXTENSIONS:
                         found_episodes.add((season, episode))
                     
                     dest_path = self._planned_episode_destination(file_path, target_root, normalized, season, episode, ep_data)
                     
                     if not self.dry_run:
                         dest_dir = dest_path.parent
                         self._ensure_directory(dest_dir, item_id, "organize.create_season")
                         self._move_or_copy(file_path, dest_path, item_id=item_id)

        # 2. Rename Directory
        # Condition: 
        # - In-place rename enabled AND (Rename Parent toggle is ON OR it's a folder we just created for loose files OR it has Season structure)
        final_show_path = target_root
        should_rename = (self.rename_parent_dir or is_group_folder or has_seasons)
        
        if self.inplace_rename and not self.dry_run and self.enable_organize and scope_allows_organize and should_rename:
             self._checkpoint("organize.rename_directory")
             final_show_path = self._rename_directory(show_path, normalized, item_id=item_id)

        # 3. Full Metadata Download & Missing Check
        if detected_type == "tv" and scope_allows_nfo:
            self._process_full_metadata(final_show_path, meta_ep_map, found_episodes, normalized, episode_nfos, season_nfos, item_id=item_id)

    def _move_or_copy(self, src: Path, dest: Path, item_id: Optional[str] = None):
        self._checkpoint("organize.file_operation")
        if self.dry_run: return
        if src.resolve() == dest.resolve(): return
        action_type = "copy_file" if self.copy_files else "move_file"
        action = {"type": action_type, "destination": str(dest)}
        backup_path = None
        temp_path = None
        side_effect_recorded = False
        try:
            action, conflict = self._resolve_file_action(src, dest, action_type)
            if action["status"] == "blocked":
                raise FileExistsError(f"Destination conflict requires a new plan: {dest}")
            if action["status"] == "skipped":
                logger.warning(f"Skipped existing destination: {dest}")
                self._emit_operation(
                    "operation.skipped",
                    item_id,
                    action.get("type") or action_type,
                    src,
                    Path(action.get("destination") or dest),
                    "organize.file_operation",
                    reason="destination_exists",
                )
                return

            resolved_dest = Path(action["destination"])
            self._ensure_directory(resolved_dest.parent, item_id, "organize.create_destination")
            self._emit_operation(
                "operation.started",
                item_id,
                action["type"],
                src,
                resolved_dest,
                "organize.file_operation",
            )
            backup_path = self.manifest.backup_file(resolved_dest) if resolved_dest.exists() else None

            if self.copy_files:
                temp_path = self._copy_to_destination_temp(src, resolved_dest)
                temp_path.replace(resolved_dest)
                temp_path = None
            elif self._same_filesystem(src, resolved_dest.parent):
                os.replace(src, resolved_dest)
            else:
                temp_path = self._copy_to_destination_temp(src, resolved_dest)
                temp_path.replace(resolved_dest)
                temp_path = None
                try:
                    self._remove_source_after_copy(src)
                except Exception:
                    side_effect_action = "overwrite_file" if backup_path else "copy_file"
                    side_effect_extra = {
                        "derived_from": action["type"],
                        "incomplete_move": True,
                    }
                    if backup_path:
                        side_effect_extra["backup_path"] = str(backup_path)
                    self.manifest.record(
                        side_effect_action,
                        src if side_effect_action == "copy_file" else None,
                        resolved_dest,
                        extra=side_effect_extra,
                    )
                    side_effect_recorded = True
                    raise
            extra = {
                "conflict_strategy": self.conflict_strategy,
                "conflict_resolution": action.get("resolution"),
                "original_destination": str(dest),
            }
            if backup_path:
                extra["backup_path"] = str(backup_path)
            self.manifest.record(action["type"], src, resolved_dest, extra=extra)
            self._emit_operation(
                "operation.completed",
                item_id,
                action["type"],
                src,
                resolved_dest,
                "organize.file_operation",
            )
            verb = "Copied" if self.copy_files else "Moved"
            logger.info(f"{verb}: {src.name} -> {resolved_dest.name}")
        except OrganizerExecutionError:
            if temp_path:
                temp_path.unlink(missing_ok=True)
            raise
        except Exception as e:
            if temp_path:
                temp_path.unlink(missing_ok=True)
            resolved_dest = Path(action.get("destination") or dest)
            self._record_failed_operation(
                action.get("type") or action_type,
                src,
                resolved_dest,
                "organize.file_operation",
                e,
                {
                    **({"backup_path": str(backup_path)} if backup_path else {}),
                    "side_effect_recorded": side_effect_recorded,
                },
            )
            self._emit_operation(
                "operation.failed",
                item_id,
                action.get("type") or action_type,
                src,
                resolved_dest,
                "organize.file_operation",
                error=str(e),
                side_effect_recorded=side_effect_recorded,
            )
            raise OrganizerExecutionError(
                "organize.file_operation",
                action.get("type") or action_type,
                src,
                resolved_dest,
                e,
            ) from e

    def _copy_to_destination_temp(self, source: Path, destination: Path) -> Path:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".copying",
            dir=str(destination.parent),
        )
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            shutil.copy2(str(source), str(temp_path))
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
        return temp_path

    def _same_filesystem(self, source: Path, destination_parent: Path) -> bool:
        return source.stat().st_dev == destination_parent.stat().st_dev

    def _remove_source_after_copy(self, source: Path) -> None:
        source.unlink()

    def _rename_directory(self, show_path: Path, normalized: dict, item_id: Optional[str] = None) -> Path:
        new_show_path = self._planned_renamed_directory(show_path, normalized)
        action = {"type": "rename_dir", "destination": str(new_show_path)}
        try:
             if show_path.resolve() != new_show_path.resolve():
                 action, conflict = self._resolve_directory_action(show_path, new_show_path)
                 if action["status"] == "blocked":
                     raise FileExistsError(f"Directory conflict requires a new plan: {new_show_path}")
                 if action["status"] == "skipped":
                     logger.warning(f"Skipped directory rename conflict: {new_show_path}")
                     self._emit_operation(
                         "operation.skipped",
                         item_id,
                         action.get("type") or "rename_dir",
                         show_path,
                         Path(action.get("destination") or new_show_path),
                         "organize.rename_directory",
                         reason="destination_exists",
                     )
                     return show_path
                 resolved_path = Path(action["destination"])
                 self._emit_operation(
                     "operation.started",
                     item_id,
                     action["type"],
                     show_path,
                     resolved_path,
                     "organize.rename_directory",
                 )
                 show_path.rename(resolved_path)
                 self.manifest.record("rename_dir", show_path, resolved_path, extra={
                     "conflict_strategy": self.conflict_strategy,
                     "conflict_resolution": action.get("resolution"),
                     "original_destination": str(new_show_path),
                 })
                 self._emit_operation(
                     "operation.completed",
                     item_id,
                     action["type"],
                     show_path,
                     resolved_path,
                     "organize.rename_directory",
                 )
                 logger.info(f"Renamed Directory: {show_path.name} -> {resolved_path.name}")
                 return resolved_path
        except Exception as e:
             destination = Path(action.get("destination") or new_show_path)
             self._record_failed_operation(
                 action.get("type") or "rename_dir",
                 show_path,
                 destination,
                 "organize.rename_directory",
                 e,
             )
             self._emit_operation(
                 "operation.failed",
                 item_id,
                 action.get("type") or "rename_dir",
                 show_path,
                 destination,
                 "organize.rename_directory",
                 error=str(e),
             )
             raise OrganizerExecutionError(
                 "organize.rename_directory",
                 action.get("type") or "rename_dir",
                 show_path,
                 destination,
                 e,
             ) from e
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
            and not is_hidden_path(file_path)
            and (file_path.suffix.lower() in FilenameParser.VIDEO_EXTENSIONS or file_path.suffix.lower() in FilenameParser.SUBTITLE_EXTENSIONS)
            and not file_path.name.endswith(".nfo")
            and "images" not in str(file_path)
        ]

    def _safe_title(self, value: str) -> str:
        return FileSystemManager.sanitize_component(value)

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
        movie_title = self._safe_title(normalized.get("title_zh") or normalized.get("title") or target_root.name)
        year = normalized.get("year")
        return target_root / f"{movie_title} ({year}){file_path.suffix}"

    def _planned_episode_destination(self, file_path: Path, target_root: Path, normalized: dict, season: int, episode: int, ep_data: dict) -> Path:
        show_title = self._safe_title(normalized.get("title_zh") or normalized.get("title") or target_root.name)
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
        if file_path.suffix.lower() in FilenameParser.VIDEO_EXTENSIONS:
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

    def _process_full_metadata(self, show_path: Path, meta_ep_map, found_episodes, normalized, episode_nfos, season_nfos=None, item_id: Optional[str] = None):
        missing_eps = []
        logger.info("📡 Processing full metadata for all episodes...")
        
        for (season, episode), ep_data in meta_ep_map.items():
            self._checkpoint("organize.episode_metadata")
            if season == 0: continue
            
            if (season, episode) not in found_episodes:
                missing_eps.append(f"S{season:02d}E{episode:02d}")
                continue
                
            show_title = self._safe_title(normalized.get("title_zh") or normalized.get("title") or show_path.name)
            ep_title = ep_data.get("name_zh") or ep_data.get("name", "")
            safe_ep_title = "".join(c for c in ep_title if c not in '/\\:*?"<>|').strip()
            
            base_name = f"{show_title} - S{season:02d}E{episode:02d} - {safe_ep_title}"
            dest_dir = show_path / f"Season {season:02d}"
            
            if not self.dry_run:
                self._ensure_directory(dest_dir, item_id, "organize.create_season")
                
                # Write Season NFO if not exists
                if season_nfos and season in season_nfos:
                    s_xml = season_nfos[season]
                    s_nfo_dest = dest_dir / "season.nfo"
                    if not s_nfo_dest.exists():
                        self._emit_operation(
                            "operation.started",
                            item_id,
                            "create_file",
                            None,
                            s_nfo_dest,
                            "organize.season_nfo",
                            kind="season_nfo",
                        )
                        try:
                            FileSystemManager.write_text_atomic(str(s_nfo_dest), s_xml)
                            self.manifest.record("create_file", None, s_nfo_dest)
                            self._emit_operation(
                                "operation.completed",
                                item_id,
                                "create_file",
                                None,
                                s_nfo_dest,
                                "organize.season_nfo",
                                kind="season_nfo",
                            )
                        except Exception as exc:
                            self._record_failed_operation(
                                "create_file",
                                None,
                                s_nfo_dest,
                                "organize.season_nfo",
                                exc,
                            )
                            self._emit_operation(
                                "operation.failed",
                                item_id,
                                "create_file",
                                None,
                                s_nfo_dest,
                                "organize.season_nfo",
                                kind="season_nfo",
                                error=str(exc),
                            )
                            raise OrganizerExecutionError(
                                "organize.season_nfo",
                                "create_file",
                                None,
                                s_nfo_dest,
                                exc,
                            ) from exc

                # Write NFO
                ep_xml = episode_nfos.get((season, episode))
                nfo_dest = dest_dir / f"{base_name}.nfo"
                if ep_xml and not nfo_dest.exists():
                     self._emit_operation(
                         "operation.started",
                         item_id,
                         "create_file",
                         None,
                         nfo_dest,
                         "organize.episode_nfo",
                         kind="episode_nfo",
                         season=season,
                         episode=episode,
                     )
                     try:
                        FileSystemManager.write_text_atomic(str(nfo_dest), ep_xml)
                        self.manifest.record("create_file", None, nfo_dest)
                        self._emit_operation(
                            "operation.completed",
                            item_id,
                            "create_file",
                            None,
                            nfo_dest,
                            "organize.episode_nfo",
                            kind="episode_nfo",
                            season=season,
                            episode=episode,
                        )
                     except Exception as exc:
                        self._record_failed_operation(
                            "create_file",
                            None,
                            nfo_dest,
                            "organize.episode_nfo",
                            exc,
                        )
                        self._emit_operation(
                            "operation.failed",
                            item_id,
                            "create_file",
                            None,
                            nfo_dest,
                            "organize.episode_nfo",
                            kind="episode_nfo",
                            season=season,
                            episode=episode,
                            error=str(exc),
                        )
                        raise OrganizerExecutionError(
                            "organize.episode_nfo",
                            "create_file",
                            None,
                            nfo_dest,
                            exc,
                        ) from exc
                        
                # Download Thumb
                still_path = ep_data.get("still_path")
                if still_path and self.pipeline and self.pipeline.artwork:
                    thumb_dest = dest_dir / f"{base_name}-thumb.jpg"
                    if self.overwrite_images or not thumb_dest.exists():
                         full_url = f"https://image.tmdb.org/t/p/original{still_path}"
                         existed = thumb_dest.exists()
                         backup_path = self.manifest.backup_file(thumb_dest) if existed else None
                         try:
                            if self.pipeline.artwork.download_image(str(thumb_dest), full_url):
                                if not getattr(self.pipeline.artwork, "manifest", None):
                                    extra = {}
                                    if backup_path:
                                        extra["backup_path"] = str(backup_path)
                                    self.manifest.record("overwrite_file" if existed else "create_file", None, thumb_dest, extra=extra)
                         except Exception as exc:
                            self._record_failed_operation(
                                "overwrite_file" if existed else "create_file",
                                None,
                                thumb_dest,
                                "organize.episode_thumbnail",
                                exc,
                            )
                            logger.exception("Failed to download optional episode thumbnail: %s", thumb_dest)

        if missing_eps:
            missing_eps.sort()
            logger.warning(f"⚠️  Missing {len(missing_eps)} Episodes:")
            chunk_size = 10
            for i in range(0, len(missing_eps), chunk_size):
                logger.warning("   " + ", ".join(missing_eps[i:i+chunk_size]))
        else:
            logger.info("✅ All episodes present!")
