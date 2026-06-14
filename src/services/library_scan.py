import hashlib
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.batch.detector import MediaTypeDetector
from src.core.filename_parser import FilenameParser
from src.core.nfo_parser import NfoParser
from src.core.path_filters import is_hidden_path


class LibraryScanService:
    """Read-only inventory service used before metadata matching or planning."""

    ARTWORK_NAMES = {
        "poster.jpg": "poster",
        "poster.png": "poster",
        "fanart.jpg": "fanart",
        "fanart.png": "fanart",
        "banner.jpg": "banner",
        "clearlogo.png": "logo",
        "logo.png": "logo",
        "clearart.png": "clearart",
        "landscape.jpg": "landscape",
    }

    def __init__(self, max_items: int = 500, max_files_per_item: int = 10000):
        self.max_items = max(1, int(max_items))
        self.max_files_per_item = max(1, int(max_files_per_item))

    def scan(self, root: Path, mode: str = "auto", use_local_nfo: bool = True) -> Dict[str, Any]:
        root = root.expanduser().resolve()
        if not root.exists():
            raise FileNotFoundError(str(root))
        if not root.is_dir():
            raise NotADirectoryError(str(root))
        if mode not in {"auto", "single", "batch"}:
            raise ValueError("mode must be auto, single, or batch")

        effective_mode = self._effective_mode(root, mode)
        candidates = [root] if effective_mode == "single" else self._batch_candidates(root)
        items = []
        for path in candidates[: self.max_items]:
            item = self._inspect_directory(path, use_local_nfo=use_local_nfo)
            if item["video_count"] or item["nfo_count"]:
                items.append(item)

        if effective_mode == "batch" and len(items) < self.max_items:
            items.extend(self._inspect_loose_files(root, self.max_items - len(items)))

        counts = Counter(item["status"] for item in items)
        media_counts = Counter(item["media_type"] for item in items)
        return {
            "root": str(root),
            "mode": effective_mode,
            "read_only": True,
            "truncated": len(candidates) > self.max_items or any(item.get("truncated") for item in items),
            "summary": {
                "items": len(items),
                "ready": counts["ready"],
                "review": counts["review"],
                "quarantined": counts["quarantined"],
                "movies": media_counts["movie"],
                "tv": media_counts["tv"],
                "videos": sum(item["video_count"] for item in items),
                "nfo": sum(item["nfo_count"] for item in items),
                "with_tmdb_id": sum(1 for item in items if item.get("tmdb_id")),
            },
            "items": sorted(items, key=lambda item: (item["status"] != "review", item["name"].casefold())),
        }

    def _effective_mode(self, root: Path, mode: str) -> str:
        if mode != "auto":
            return mode
        try:
            children = [
                child
                for child in root.iterdir()
                if child.is_dir() and not child.is_symlink() and not is_hidden_path(child)
            ]
        except OSError:
            return "single"
        has_season_dirs = any(self._is_season_dir(child.name) for child in children)
        child_media_dirs = sum(1 for child in children if self._has_media(child))
        if has_season_dirs or child_media_dirs == 0:
            return "single"
        return "batch"

    def _batch_candidates(self, root: Path) -> List[Path]:
        candidates = []
        try:
            children = sorted(root.iterdir(), key=lambda path: path.name.casefold())
        except OSError:
            return candidates
        for child in children:
            if (
                not child.is_dir()
                or child.is_symlink()
                or is_hidden_path(child)
                or self._is_season_dir(child.name)
            ):
                continue
            if self._has_media(child):
                candidates.append(child)
        return candidates

    def _has_media(self, root: Path) -> bool:
        for _, path in self._walk_files(root, limit=250):
            if path.suffix.lower() in FilenameParser.VIDEO_EXTENSIONS or path.suffix.lower() == ".nfo":
                return True
        return False

    def _inspect_directory(self, root: Path, use_local_nfo: bool) -> Dict[str, Any]:
        files_with_index = list(self._walk_files(root, limit=self.max_files_per_item + 1))
        truncated = len(files_with_index) > self.max_files_per_item
        files = [path for _, path in files_with_index[: self.max_files_per_item]]
        videos = [path for path in files if path.suffix.lower() in FilenameParser.VIDEO_EXTENSIONS]
        subtitles = [path for path in files if path.suffix.lower() in FilenameParser.SUBTITLE_EXTENSIONS]
        nfo_files = [path for path in files if path.suffix.lower() == ".nfo"]
        artwork_counts = Counter(
            self.ARTWORK_NAMES[path.name.casefold()]
            for path in files
            if path.name.casefold() in self.ARTWORK_NAMES
        )
        invalid_artwork = [
            str(path)
            for path in files
            if path.name.casefold() in self.ARTWORK_NAMES
            and not self._has_recognized_image_signature(path)
        ]
        parsed_root = FilenameParser.parse_media_filename(root.name)
        episode_parses = [
            FilenameParser.parse_media_filename(video.name)
            for video in videos
        ]
        episode_keys: Dict[Tuple[int, int], List[str]] = defaultdict(list)
        for video, parsed in zip(videos, episode_parses):
            if parsed.get("season") is not None and parsed.get("episode") is not None:
                episode_keys[(int(parsed["season"]), int(parsed["episode"]))].append(str(video))

        duplicates = [
            {
                "episode": f"S{season:02d}E{episode:02d}",
                "sources": sources,
            }
            for (season, episode), sources in sorted(episode_keys.items())
            if len(sources) > 1
        ]
        detected_type = MediaTypeDetector.detect(root) if videos else (parsed_root.get("media_type_guess") or "movie")
        local_metadata = (
            NfoParser.extract_metadata_from_directory(str(root), root.name, strict_match=detected_type == "movie")
            if use_local_nfo
            else {"tmdb_id": None, "media_type": None}
        )
        media_type = local_metadata.get("media_type") or detected_type
        issues = []
        if not videos:
            issues.append(self._issue("no_video_files", "error", "No video files were found."))
        if not parsed_root.get("title") and not local_metadata.get("tmdb_id"):
            issues.append(self._issue("unparseable_title", "error", "Folder name does not contain a stable media title."))
        elif parsed_root.get("confidence") == "none":
            issues.append(self._issue("low_parse_confidence", "warning", "Folder name has low parse confidence."))
        if duplicates:
            for duplicate in duplicates:
                issues.append({
                    **self._issue(
                        "duplicate_episode_files",
                        "error",
                        f"{len(duplicate['sources'])} files claim {duplicate['episode']}.",
                    ),
                    **duplicate,
                })
        if invalid_artwork:
            issues.append({
                **self._issue(
                    "invalid_artwork_file",
                    "warning",
                    f"{len(invalid_artwork)} artwork file(s) have an invalid or mismatched image format.",
                ),
                "sources": invalid_artwork,
            })
        if truncated:
            issues.append(self._issue("scan_truncated", "warning", f"Stopped after {self.max_files_per_item} files."))

        status = "quarantined" if any(issue["code"] == "unparseable_title" for issue in issues) else (
            "review" if any(issue["level"] in {"error", "warning"} for issue in issues) else "ready"
        )
        return {
            "id": self._item_id(root),
            "name": root.name,
            "path": str(root),
            "kind": "directory",
            "status": status,
            "media_type": media_type,
            "parsed_title": parsed_root.get("title"),
            "year": parsed_root.get("year"),
            "parse_confidence": parsed_root.get("confidence"),
            "parse_reasons": parsed_root.get("reasons") or [],
            "tmdb_id": local_metadata.get("tmdb_id"),
            "local_nfo_type": local_metadata.get("media_type"),
            "video_count": len(videos),
            "subtitle_count": len(subtitles),
            "nfo_count": len(nfo_files),
            "episode_count": len(episode_keys),
            "artwork": dict(artwork_counts),
            "issues": issues,
            "truncated": truncated,
        }

    @staticmethod
    def _has_recognized_image_signature(path: Path) -> bool:
        try:
            if path.stat().st_size < 32:
                return False
            with path.open("rb") as file:
                header = file.read(16)
        except OSError:
            return False
        return any((
            header.startswith(b"\xff\xd8\xff"),
            header.startswith(b"\x89PNG\r\n\x1a\n"),
            header.startswith(b"RIFF") and header[8:12] == b"WEBP",
            header.startswith((b"GIF87a", b"GIF89a")),
        ))

    def _inspect_loose_files(self, root: Path, remaining: int) -> List[Dict[str, Any]]:
        groups: Dict[str, List[Path]] = defaultdict(list)
        quarantined: List[Path] = []
        try:
            children = list(root.iterdir())
        except OSError:
            return []
        for path in children:
            if (
                not path.is_file()
                or is_hidden_path(path)
                or path.suffix.lower() not in FilenameParser.VIDEO_EXTENSIONS
            ):
                continue
            parsed = FilenameParser.parse_media_filename(path.name)
            title = parsed.get("title")
            if not title or parsed.get("confidence") == "none":
                quarantined.append(path)
                continue
            groups[FilenameParser.clean_show_name_for_search(str(title)).casefold()].append(path)

        items = []
        for _, files in sorted(groups.items())[:remaining]:
            first = FilenameParser.parse_media_filename(files[0].name)
            item_path = root / str(first.get("title") or files[0].stem)
            items.append({
                "id": self._item_id(item_path),
                "name": str(first.get("title") or files[0].stem),
                "path": str(item_path),
                "source_root": str(root),
                "kind": "loose_files",
                "status": "ready",
                "media_type": first.get("media_type_guess") or "movie",
                "parsed_title": first.get("title"),
                "year": first.get("year"),
                "parse_confidence": first.get("confidence"),
                "parse_reasons": first.get("reasons") or [],
                "tmdb_id": None,
                "local_nfo_type": None,
                "video_count": len(files),
                "subtitle_count": 0,
                "nfo_count": 0,
                "episode_count": sum(1 for file in files if FilenameParser.parse_episode_info(file.name)),
                "artwork": {},
                "issues": [],
                "sources": [str(file) for file in files],
                "truncated": False,
            })
        for path in quarantined[: max(0, remaining - len(items))]:
            parsed = FilenameParser.parse_media_filename(path.name)
            items.append({
                "id": self._item_id(path),
                "name": path.name,
                "path": str(path),
                "source_root": str(root),
                "kind": "quarantined",
                "status": "quarantined",
                "media_type": parsed.get("media_type_guess") or "movie",
                "parsed_title": parsed.get("title"),
                "year": parsed.get("year"),
                "parse_confidence": parsed.get("confidence"),
                "parse_reasons": parsed.get("reasons") or [],
                "tmdb_id": None,
                "local_nfo_type": None,
                "video_count": 1,
                "subtitle_count": 0,
                "nfo_count": 0,
                "episode_count": 0,
                "artwork": {},
                "issues": [self._issue("unparseable_title", "error", "Filename does not contain a stable media title.")],
                "sources": [str(path)],
                "truncated": False,
            })
        return items

    def _walk_files(self, root: Path, limit: int) -> Iterable[Tuple[int, Path]]:
        count = 0
        for current, dirs, files in os.walk(root, followlinks=False):
            current_path = Path(current)
            dirs[:] = [
                name
                for name in dirs
                if not is_hidden_path(current_path / name) and not (current_path / name).is_symlink()
            ]
            for name in files:
                path = current_path / name
                if is_hidden_path(path):
                    continue
                yield count, path
                count += 1
                if count >= limit:
                    return

    @staticmethod
    def _is_season_dir(name: str) -> bool:
        normalized = name.casefold().replace("_", " ").strip()
        return normalized == "specials" or (
            normalized.startswith("season ") and normalized[7:].strip().isdigit()
        )

    @staticmethod
    def _item_id(path: Path) -> str:
        return hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:20]

    @staticmethod
    def _issue(code: str, level: str, message: str) -> Dict[str, str]:
        return {"code": code, "level": level, "message": message}
