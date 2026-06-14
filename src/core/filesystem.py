import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Optional


class FileSystemManager:
    @staticmethod
    def sanitize_component(value: str, fallback: str = "Untitled", replacement: str = "") -> str:
        cleaned = re.sub(r'[\x00-\x1f\\/:"*?<>|]', replacement, value or "")
        cleaned = cleaned.strip().strip(".").strip()
        if cleaned in {"", ".", ".."}:
            cleaned = fallback
        return cleaned[:180].rstrip().rstrip(".")

    @staticmethod
    def create_media_directory(base_dir: str, title: str, year: int, media_type: str, inplace: bool = False) -> str:
        """Create directory structure for media item."""
        safe_title = FileSystemManager.sanitize_component(title)
        dir_name = f"{safe_title} ({year})"

        if inplace:
            # In inplace mode, use base_dir directly without creating subfolders
            media_dir = base_dir
        else:
            # Normal mode: create Movies/TV subfolder structure
            media_dir = os.path.join(base_dir, "Movies" if media_type == "movie" else "TV", dir_name)

        os.makedirs(media_dir, exist_ok=True)
        return media_dir

    @staticmethod
    def create_season_directory(tv_dir: str, season_number: int) -> str:
        """Create season directory for TV shows."""
        season_dir = os.path.join(tv_dir, f"Season {season_number:02d}")
        os.makedirs(season_dir, exist_ok=True)
        return season_dir

    @staticmethod
    def write_text_atomic(path: str, content: str, encoding: str = "utf-8") -> str:
        """Write text through a temporary file and atomically replace the target."""
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding=encoding) as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
            return path
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    @staticmethod
    def write_nfo_file(directory: str, filename: str, content: str) -> str:
        """Write NFO file to directory."""
        directory_path = Path(directory).expanduser().resolve(strict=False)
        filename_path = Path(filename)
        if filename_path.is_absolute() or filename_path.name != filename:
            raise ValueError("NFO filename must be a single safe path component")
        nfo_path = (directory_path / filename).resolve(strict=False)
        try:
            nfo_path.relative_to(directory_path)
        except ValueError as exc:
            raise ValueError("NFO destination escapes its media directory") from exc
        return FileSystemManager.write_text_atomic(str(nfo_path), content)

    @staticmethod
    def copy_video_file(source: str, destination_dir: str, filename: str) -> Optional[str]:
        """Copy video file to media directory."""
        if not os.path.exists(source):
            return None

        dest_path = os.path.join(destination_dir, filename)
        shutil.copy2(source, dest_path)
        return dest_path

    @staticmethod
    def create_images_directory(media_dir: str) -> str:
        """Create images subdirectory."""
        images_dir = os.path.join(media_dir, "images")
        os.makedirs(images_dir, exist_ok=True)
        return images_dir

    @staticmethod
    def create_episode_directory(season_dir: str, title: str, season: int, episode: int, episode_title: str) -> tuple[str, str]:
        """Create episode images directory and return paths."""
        # For TV shows, files should be placed directly in the season directory
        # No separate episode subdirectories should be created
        # Return season directory for both episode and images directories
        return season_dir, season_dir

    @staticmethod
    def write_episode_nfo(season_dir: str, title: str, season: int, episode: int, episode_title: str, content: str) -> str:
        """Write episode NFO file."""
        safe_title = FileSystemManager.sanitize_component(title)
        safe_episode_title = FileSystemManager.sanitize_component(episode_title, fallback="Episode", replacement="-")
        nfo_filename = f"{safe_title} - S{season:02d}E{episode:02d} - {safe_episode_title}.nfo"
        return FileSystemManager.write_nfo_file(season_dir, nfo_filename, content)

    @staticmethod
    def write_episode_poster(episode_dir: str, title: str, season: int, episode: int, episode_title: str, poster_path: str) -> Optional[str]:
        """Copy poster to episode directory as thumb."""
        if not os.path.exists(poster_path):
            return None

        safe_title = FileSystemManager.sanitize_component(title)
        safe_episode_title = FileSystemManager.sanitize_component(episode_title, fallback="Episode", replacement="-")
        poster_filename = f"{safe_title} - S{season:02d}E{episode:02d} - {safe_episode_title}-thumb.jpg"
        dest_path = os.path.join(episode_dir, poster_filename)

        shutil.copy2(poster_path, dest_path)
        return dest_path
