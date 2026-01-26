
import os
import shutil
from pathlib import Path

def setup_test_env():
    """Create a temporary test environment with dummy media files."""
    base_dir = Path("test_media_env")
    if base_dir.exists():
        shutil.rmtree(base_dir)
    base_dir.mkdir()

    # 1. TV Show Case: Breaking Bad
    tv_dir = base_dir / "Breaking Bad"
    tv_dir.mkdir()
    (tv_dir / "Breaking.Bad.S01E01.Pilot.mkv").touch()
    (tv_dir / "Breaking.Bad.S01E02.Cat.in.the.Bag.mkv").touch()
    (tv_dir / "Breaking.Bad.S01E01.Pilot.zh.srt").touch()

    # 2. Movie Case: Inception
    movie_dir = base_dir / "Inception (2010)"
    movie_dir.mkdir()
    (movie_dir / "Inception.2010.1080p.BluRay.x264.mkv").touch()
    
    # 3. Anime Case: Made in Abyss (Using Chinese folder name to test search)
    anime_dir = base_dir / "罪恶之渊" # Intentionally using the confusing name
    anime_dir.mkdir()
    (anime_dir / "[Nekomoe kissaten][Made in Abyss][01][1080p][Jpn_Sc].mp4").touch()
    
    # 4. Anime Case: Why the Hell are You Here, Teacher!? (Fuzzy search)
    teacher_dir = base_dir / "为什么老师会在这里"
    teacher_dir.mkdir()
    (teacher_dir / "[SumiSora][Nande Koko ni Sensei ga!?][01][1080p].mp4").touch()    
    
    # 5. Loose Files Case (in root) - The Matrix
    (base_dir / "The.Matrix.1999.mp4").touch()

    print(f"✅ Test environment created at: {base_dir.absolute()}")
    return base_dir

if __name__ == "__main__":
    setup_test_env()
