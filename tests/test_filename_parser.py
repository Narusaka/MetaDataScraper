import tempfile
import unittest
from pathlib import Path

from src.batch.scanner import MediaScanner
from src.batch.detector import MediaTypeDetector
from src.batch.scraper import BatchMediaScraper
from src.core.filename_parser import FilenameParser
from src.core.nfo_parser import NfoParser


class FilenameParserFixtureTest(unittest.TestCase):
    CASES = [
        ("Show.Name.S01E01.1080p.WEB-DL.mkv", "Show Name", (1, 1), "high"),
        ("Show Name S02E10-E12 2160p.mkv", "Show Name", (2, 10), "high"),
        ("Show.Name.01x02.HDTV.mkv", "Show Name", (1, 2), "high"),
        ("[Nekomoe kissaten][Made in Abyss][01][1080p].mkv", "Made in Abyss", (1, 1), "high"),
        ("[SubsPlease] Frieren - 28 (1080p).mkv", "Frieren", (1, 28), "medium"),
        ("葬送的芙莉莲 第28集.mp4", "葬送的芙莉莲", (1, 28), "medium"),
        ("The Matrix (1999) 1080p BluRay.mkv", "The Matrix", None, "high"),
        ("Inception.mkv", "Inception", None, "medium"),
        ("1080p.x265.DTS.mkv", None, None, "none"),
        ("01.mkv", None, None, "none"),
    ]

    def test_real_world_filename_matrix(self):
        for filename, title, episode, confidence in self.CASES:
            with self.subTest(filename=filename):
                parsed = FilenameParser.parse_media_filename(filename)
                self.assertEqual(parsed["title"], title)
                self.assertEqual(FilenameParser.parse_episode_info(filename), episode)
                self.assertEqual(parsed["confidence"], confidence)

    def test_subtitle_language_requires_explicit_tokens(self):
        self.assertEqual(FilenameParser.detect_subtitle_language("Show.S01E01.en.srt"), "en")
        self.assertEqual(FilenameParser.detect_subtitle_language("Show.S01E01.简中.ass"), "zh")
        self.assertEqual(FilenameParser.detect_subtitle_language("Show.S01E01.jpn.ass"), "ja")
        self.assertEqual(FilenameParser.detect_subtitle_language("Science.Show.S01E01.srt"), "")
        self.assertEqual(FilenameParser.detect_subtitle_language("Golden.Time.S01E01.srt"), "")

    def test_unparseable_loose_file_is_quarantined_without_physical_move(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            unknown = root / "1080p.x265.DTS.mkv"
            unknown.write_bytes(b"video")

            tasks = MediaScanner().scan_multi(root)

            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0]["type"], "quarantined")
            self.assertEqual(tasks[0]["path"], unknown)
            self.assertTrue(unknown.exists())
            self.assertEqual(list(root.iterdir()), [unknown])

    def test_subtitle_and_video_group_by_normalized_title(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            video = root / "Show.Name.S01E01.mkv"
            subtitle = root / "Show Name S01E01.en.srt"
            video.write_bytes(b"video")
            subtitle.write_text("subtitle", encoding="utf-8")

            tasks = MediaScanner().scan_multi(root)

            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0]["type"], "loose_files")
            self.assertEqual(set(tasks[0]["files"]), {video, subtitle})

    def test_appledouble_media_and_nfo_files_are_ignored_everywhere(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            root = Path(temp_dir)
            season = root / "Season 01"
            season.mkdir()
            (season / "Show - S01E01.mkv").write_bytes(b"video")
            (season / "._Show - S01E01.mkv").write_bytes(b"appledouble")
            (root / "tvshow.nfo").write_text(
                "<tvshow><tmdbid>123</tmdbid></tvshow>",
                encoding="utf-8",
            )
            (root / "._fallback.nfo").write_bytes(b"\x00\x05invalid")

            task = MediaScanner(media_type="tv", use_local_nfo=True).scan_single(root)[0]
            scraper = BatchMediaScraper.__new__(BatchMediaScraper)

            self.assertEqual(task["tmdb_id"], 123)
            self.assertEqual(scraper._count_video_files(root), 1)
            self.assertEqual(MediaTypeDetector.detect(root), "tv")
            self.assertEqual(NfoParser._nfo_files(root), [root / "tvshow.nfo"])


if __name__ == "__main__":
    unittest.main()
