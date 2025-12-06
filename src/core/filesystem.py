import os
import shutil
from typing import Optional


class FileSystemManager:
    @staticmethod
    def create_media_directory(base_dir: str, title: str, year: int, media_type: str, inplace: bool = False) -> str:
        """Create directory structure for media item."""
        # Sanitize title for directory name - only remove filesystem-illegal characters
        import re
        # Remove only characters that are illegal in filesystem: \ / : * ? " < > |
        safe_title = re.sub(r'[\\/:"*?<>|]', '', title).strip()
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
    def write_nfo_file(directory: str, filename: str, content: str) -> str:
        """Write NFO file to directory."""
        nfo_path = os.path.join(directory, filename)
        with open(nfo_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return nfo_path

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
        # Clean episode title: if contains '/', take part before '/', otherwise remove other invalid chars
        if '/' in episode_title:
            safe_episode_title = episode_title.split('/')[0].strip()
        else:
            safe_episode_title = "".join(c for c in episode_title if c not in '\\:*?"<>|').strip()
        nfo_filename = f"{title} - S{season:02d}E{episode:02d} - {safe_episode_title}.nfo"
        nfo_path = os.path.join(season_dir, nfo_filename)

        with open(nfo_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return nfo_path

    @staticmethod
    def write_episode_poster(episode_dir: str, title: str, season: int, episode: int, episode_title: str, poster_path: str) -> Optional[str]:
        """Copy poster to episode directory as thumb."""
        if not os.path.exists(poster_path):
            return None

        # Clean episode title: if contains '/', take part before '/', otherwise remove other invalid chars
        if '/' in episode_title:
            safe_episode_title = episode_title.split('/')[0].strip()
        else:
            safe_episode_title = "".join(c for c in episode_title if c not in '\\:*?"<>|').strip()
        poster_filename = f"{title} - S{season:02d}E{episode:02d} - {safe_episode_title}-thumb.jpg"
        dest_path = os.path.join(episode_dir, poster_filename)

        shutil.copy2(poster_path, dest_path)
        return dest_path
