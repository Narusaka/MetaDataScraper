import unittest

from src.pipeline.pipeline import MediaPipeline


class FakeTMDB:
    def __init__(self, details=None, movie_results=None, tv_results=None, alternative_titles=None):
        self.details = details or {}
        self.movie_results = movie_results or []
        self.tv_results = tv_results or []
        self.alternative_titles = alternative_titles or {}

    def search_movie(self, query):
        return {"results": self.movie_results}

    def search_tv(self, query):
        return {"results": self.tv_results}

    def get_movie_details(self, tmdb_id):
        return self.details[("movie", tmdb_id)]

    def get_tv_details(self, tmdb_id):
        return self.details[("tv", tmdb_id)]

    def get_alternative_titles(self, media_type, tmdb_id):
        return {"results": [{"title": title} for title in self.alternative_titles.get((media_type, tmdb_id), [])]}


class FakeTavily:
    def __init__(self, tmdb_id):
        self.tmdb_id = tmdb_id

    def search_tmdb_id(self, query, media_type, year=None, verbose=False):
        return self.tmdb_id


def make_pipeline(tmdb, tavily=None):
    pipeline = object.__new__(MediaPipeline)
    pipeline.tmdb = tmdb
    pipeline.tavily_search = tavily
    pipeline.verbose = False
    pipeline.quiet = True
    return pipeline


class MatchingReliabilityTest(unittest.TestCase):
    def test_tmdb_rejects_low_similarity_latin_false_positive(self):
        pipeline = make_pipeline(
            FakeTMDB(
                movie_results=[
                    {
                        "id": 1,
                        "title": "Steven Avery: Innocent or Guilty?",
                        "original_title": "Steven Avery: Innocent or Guilty?",
                        "release_date": "2016-01-01",
                    }
                ]
            )
        )

        result = pipeline._step_search(
            {"query": "Front Innocent", "media_type": "movie", "media_type_forced": True, "search_mode": "tmdb_only"}
        )

        self.assertIsNone(result["selected"])
        self.assertEqual(result["match"]["reason"], "low_confidence")
        self.assertLess(result["match"]["score"], 0.55)
        self.assertEqual(result["match"]["candidates"][0]["decision"], "low_similarity")
        self.assertIn("token_overlap", result["match"]["candidates"][0])

    def test_tmdb_accepts_official_alternative_title_match(self):
        pipeline = make_pipeline(
            FakeTMDB(
                tv_results=[
                    {
                        "id": 123,
                        "name": "大きい女の子は好きですか？",
                        "original_name": "大きい女の子は好きですか？",
                        "first_air_date": "2020-01-01",
                    }
                ],
                alternative_titles={
                    ("tv", 123): ["Ookii Onnanoko wa Suki Desuka?"],
                },
            )
        )

        result = pipeline._step_search(
            {"query": "Ookii Onnanoko wa Suki Desuka?", "media_type": "tv", "media_type_forced": True, "search_mode": "tmdb_only"}
        )

        self.assertEqual(result["selected"]["id"], 123)
        self.assertEqual(result["match"]["reason"], "alias")
        self.assertEqual(result["match"]["matched_field"], "alias")
        self.assertEqual(result["match"]["matched_title"], "Ookii Onnanoko wa Suki Desuka?")

    def test_tavily_id_is_rejected_when_tmdb_details_do_not_match_query(self):
        pipeline = make_pipeline(
            FakeTMDB(
                details={
                    ("movie", 99): {
                        "id": 99,
                        "title": "The Matumbilas",
                        "original_title": "The Matumbilas",
                        "release_date": "2020-01-01",
                    }
                }
            ),
            FakeTavily(99),
        )

        result = pipeline._step_search(
            {"query": "本地文件", "media_type": "movie", "media_type_forced": True, "search_mode": "tavily_only"}
        )

        self.assertIsNone(result["selected"])
        self.assertEqual(result["match"]["provider"], "tavily")
        self.assertEqual(result["match"]["reason"], "external_low_confidence")
        self.assertNotIn("selected_id", result["match"])
        self.assertEqual(result["match"]["external_id"], 99)
        self.assertEqual(result["match"]["candidates"][0]["decision"], "low_similarity")

    def test_tavily_id_is_not_accepted_by_year_alone(self):
        pipeline = make_pipeline(
            FakeTMDB(
                details={
                    ("movie", 99): {
                        "id": 99,
                        "title": "The Matumbilas",
                        "original_title": "The Matumbilas",
                        "release_date": "2020-01-01",
                    }
                }
            ),
            FakeTavily(99),
        )

        result = pipeline._step_search(
            {"query": "本地文件 (2020)", "media_type": "movie", "media_type_forced": True, "search_mode": "tavily_only"}
        )

        self.assertIsNone(result["selected"])
        self.assertEqual(result["match"]["reason"], "external_low_confidence")

    def test_tavily_id_is_accepted_after_tmdb_detail_verification(self):
        pipeline = make_pipeline(
            FakeTMDB(
                details={
                    ("tv", 123): {
                        "id": 123,
                        "name": "Example Show",
                        "original_name": "Example Show",
                        "first_air_date": "2026-01-01",
                    }
                }
            ),
            FakeTavily(123),
        )

        result = pipeline._step_search(
            {"query": "Example Show (2026)", "media_type": "tv", "media_type_forced": True, "search_mode": "tavily_only"}
        )

        self.assertEqual(result["selected"]["id"], 123)
        self.assertEqual(result["selected"]["media_type"], "tv")
        self.assertEqual(result["match"]["provider"], "tavily")
        self.assertEqual(result["match"]["reason"], "external_verified")
        self.assertEqual(result["match"]["selected_id"], 123)
        self.assertEqual(result["match"]["candidates"][0]["decision"], "selected")

    def test_tavily_id_can_be_verified_by_official_alias(self):
        pipeline = make_pipeline(
            FakeTMDB(
                details={
                    ("tv", 123): {
                        "id": 123,
                        "name": "大きい女の子は好きですか？",
                        "original_name": "大きい女の子は好きですか？",
                        "first_air_date": "2020-01-01",
                    }
                },
                alternative_titles={
                    ("tv", 123): ["Ookii Onnanoko wa Suki Desuka?"],
                },
            ),
            FakeTavily(123),
        )

        result = pipeline._step_search(
            {"query": "Ookii Onnanoko wa Suki Desuka?", "media_type": "tv", "media_type_forced": True, "search_mode": "tavily_only"}
        )

        self.assertEqual(result["selected"]["id"], 123)
        self.assertEqual(result["match"]["provider"], "tavily")
        self.assertEqual(result["match"]["matched_field"], "alias")

    def test_pipeline_failure_returns_match_audit(self):
        pipeline = make_pipeline(
            FakeTMDB(
                movie_results=[
                    {
                        "id": 1,
                        "title": "Steven Avery: Innocent or Guilty?",
                        "original_title": "Steven Avery: Innocent or Guilty?",
                        "release_date": "2016-01-01",
                    }
                ]
            )
        )
        pipeline._log = lambda *args, **kwargs: None

        result = pipeline.run(
            {"query": "Front Innocent", "media_type": "movie", "media_type_forced": True, "search_mode": "tmdb_only"}
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["match"]["reason"], "low_confidence")
        self.assertEqual(result["match"]["candidates"][0]["decision"], "low_similarity")


if __name__ == "__main__":
    unittest.main()
