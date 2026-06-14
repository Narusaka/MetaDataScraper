
from pathlib import Path
from src.core.filename_parser import FilenameParser
from src.core.path_filters import is_hidden_path

class MediaTypeDetector:
    @staticmethod
    def detect(path: Path) -> str:
        """Heuristic to detect media type based on files."""
        video_files = 0
        episode_files = 0
        
        for f in path.rglob('*'):
            if f.is_file() and not is_hidden_path(f) and f.suffix.lower() in FilenameParser.VIDEO_EXTENSIONS:
                video_files += 1
                if FilenameParser.parse_episode_info(f.name):
                    episode_files += 1
                    
        # If > 30% of video files look like episodes, assume TV
        if video_files > 0 and (episode_files / video_files) > 0.3:
            return "tv"
        return "movie"
