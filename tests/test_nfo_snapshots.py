import unittest
from pathlib import Path

from src.core.llm_mapper import DirectMapper
from src.core.nfo_renderer import NfoRenderer


SNAPSHOT_DIR = Path(__file__).parent / "snapshots"


class NfoSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.show = {
            "title": "Example",
            "title_zh": "示例",
            "original_title": "Example Original",
            "year": 2026,
            "release_date": "2026-02-03",
            "plot": "Plot & detail",
            "plot_zh": "剧情 & 详情",
            "tagline": "Tag",
            "runtime": 96,
            "rating": 8.5,
            "rating_count": 123,
            "genres": ["Drama"],
            "genres_zh": ["剧情"],
            "countries": ["CN"],
            "studios": ["Studio A"],
            "writers": ["Writer A"],
            "directors": ["Director A"],
            "cast": [{
                "name_zh": "演员甲",
                "name_en": "Actor A",
                "original_name": "Actor A",
                "role": "Lead",
                "profile_path": "/a.jpg",
            }],
            "keywords_zh": ["测试"],
            "tmdb_id": 42,
            "network": "Network A",
            "networks": ["Network A"],
            "status": "Ended",
            "homepage": "https://example.test",
            "number_of_seasons": 1,
            "number_of_episodes": 1,
        }

    def assert_snapshot(self, name: str, rendered: str):
        expected = (SNAPSHOT_DIR / f"{name}.xml").read_text(encoding="utf-8")
        self.assertEqual(rendered, expected)

    def test_movie_snapshot(self):
        self.assert_snapshot("movie", NfoRenderer.render_movie_nfo(DirectMapper.map_to_movie_nfo(self.show)))

    def test_tvshow_snapshot(self):
        self.assert_snapshot("tvshow", NfoRenderer.render_tvshow_nfo(DirectMapper.map_to_tvshow_nfo(self.show)))

    def test_season_snapshot(self):
        season = {
            "id": 421,
            "season_number": 1,
            "name": "Season 1",
            "air_date": "2026-02-03",
            "overview": "Season plot",
            "vote_average": 8.0,
        }
        self.assert_snapshot("season", NfoRenderer.render_season_nfo(DirectMapper.map_to_season_nfo(season, self.show)))

    def test_episode_snapshot(self):
        episode = {
            "id": 4201,
            "season_number": 1,
            "episode_number": 2,
            "name": "Pilot",
            "name_zh": "试播集",
            "air_date": "2026-02-04",
            "runtime": 24,
            "overview": "Episode plot",
            "overview_zh": "单集剧情",
            "vote_average": 7.8,
            "vote_count": 9,
        }
        self.assert_snapshot("episode", NfoRenderer.render_episode_nfo(DirectMapper.map_to_episode_nfo(self.show, episode, self.show)))

    def test_policy_is_fixed_to_supported_targets_and_present_sidecars(self):
        policy = NfoRenderer.normalize_policy({
            "profile": "custom",
            "targets": ["Kodi", "unknown"],
            "episode_sidecars": "all",
        })
        self.assertEqual(policy["profile"], "universal")
        self.assertEqual(policy["targets"], ["kodi"])
        self.assertEqual(policy["episode_sidecars"], "present_only")


if __name__ == "__main__":
    unittest.main()
