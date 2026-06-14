import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock

from src.pipeline.pipeline import MediaPipeline
from src.core.match_scorer import CandidateScorer
from src.storage.match_memory import MatchMemoryStore, normalize_match_title


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
    pipeline.match_memory = None
    return pipeline


class MatchingReliabilityTest(unittest.TestCase):
    def test_candidate_scorer_exposes_weighted_dimensions_and_hard_blockers(self):
        evidence = CandidateScorer().score(
            query="Example Show (2026)",
            titles=[("name", "Example Show")],
            candidate_year=2025,
            target_year=2026,
            candidate_type="tv",
            expected_type="tv",
            type_forced=True,
        )

        self.assertEqual(evidence["schema_version"], 1)
        self.assertEqual(evidence["dimensions"]["title_similarity"]["score"], 1.0)
        self.assertEqual(evidence["dimensions"]["year"]["status"], "mismatch")
        self.assertEqual(evidence["dimensions"]["media_type"]["status"], "exact")
        self.assertIn("year_mismatch", evidence["hard_blockers"])
        self.assertGreater(evidence["composite_score"], 0.75)

    def test_candidate_scorer_marks_official_alias_as_cross_script_bridge(self):
        evidence = CandidateScorer().score(
            query="Ookii Onnanoko wa Suki Desuka?",
            titles=[
                ("name", "大きい女の子は好きですか？"),
                ("alias", "Ookii Onnanoko wa Suki Desuka?"),
            ],
            candidate_year=2020,
            candidate_type="tv",
            expected_type="tv",
            type_forced=True,
        )

        self.assertEqual(evidence["matched_field"], "alias")
        self.assertEqual(evidence["title_similarity"], 1.0)
        self.assertEqual(evidence["dimensions"]["script"]["status"], "compatible")
        self.assertNotIn("weak_title_evidence", evidence["warnings"])

    def test_confirmed_match_memory_bypasses_external_search(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            store = MatchMemoryStore(str(Path(temp_dir) / "matches.db"))
            store.remember("Ookii Onnanoko wa Suki Desuka?", 123, "tv", year=2020)
            tmdb = FakeTMDB()
            pipeline = make_pipeline(tmdb)
            pipeline.match_memory = store

            result = pipeline._step_search(
                {
                    "query": "Ookii Onnanoko wa Suki Desuka?",
                    "year": 2020,
                    "media_type": "tv",
                    "media_type_forced": True,
                    "search_mode": "tmdb_only",
                }
            )

            self.assertEqual(result["selected"], {"id": 123, "media_type": "tv"})
            self.assertEqual(result["match"]["provider"], "user_memory")
            self.assertEqual(result["match"]["confidence"], "confirmed")

    def test_rejected_best_candidate_is_skipped_for_next_valid_candidate(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            store = MatchMemoryStore(str(Path(temp_dir) / "matches.db"))
            store.reject("Example Movie", 10, "movie")
            pipeline = make_pipeline(
                FakeTMDB(
                    movie_results=[
                        {
                            "id": 10,
                            "title": "Example Movie",
                            "original_title": "Example Movie",
                            "release_date": "2026-01-01",
                        },
                        {
                            "id": 11,
                            "title": "Example Movie",
                            "original_title": "Example Movie",
                            "release_date": "2025-01-01",
                        },
                    ]
                )
            )
            pipeline.match_memory = store

            result = pipeline._step_search(
                {
                    "query": "Example Movie",
                    "media_type": "movie",
                    "media_type_forced": True,
                    "search_mode": "tmdb_only",
                }
            )

            self.assertEqual(result["selected"]["id"], 11)
            decisions = {item["id"]: item["decision"] for item in result["match"]["candidates"]}
            self.assertEqual(decisions[10], "user_rejected")
            self.assertEqual(decisions[11], "selected")
            self.assertEqual(store.list_rejections()[0]["hit_count"], 1)

    def test_only_rejected_candidate_remains_visible_as_review_evidence(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            store = MatchMemoryStore(str(Path(temp_dir) / "matches.db"))
            store.reject("Front Innocent", 99, "movie")
            pipeline = make_pipeline(
                FakeTMDB(
                    movie_results=[
                        {
                            "id": 99,
                            "title": "Front Innocent",
                            "original_title": "Front Innocent",
                            "release_date": "2022-01-01",
                        }
                    ]
                )
            )
            pipeline.match_memory = store

            result = pipeline._step_search(
                {
                    "query": "Front Innocent",
                    "media_type": "movie",
                    "media_type_forced": True,
                    "search_mode": "tmdb_only",
                }
            )

            self.assertIsNone(result["selected"])
            self.assertEqual(result["match"]["reason"], "user_rejected")
            self.assertEqual(result["match"]["candidates"][0]["decision"], "user_rejected")

    def test_low_confidence_localized_match_requires_review_before_execution(self):
        pipeline = make_pipeline(
            FakeTMDB(
                tv_results=[
                    {
                        "id": 321,
                        "name": "大きい女の子",
                        "original_name": "大きい女の子",
                        "first_air_date": "2026-01-01",
                    }
                ]
            )
        )
        pipeline._log = lambda *args, **kwargs: None

        result = pipeline.run(
            {"query": "Unrelated Romanized Name", "media_type": "tv", "media_type_forced": True, "search_mode": "tmdb_only"}
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "MATCH_REVIEW_REQUIRED")
        self.assertEqual(result["candidate"]["id"], 321)
        self.assertTrue(result["match"]["review_required"])

    def test_low_confidence_match_remains_visible_in_audit_mode(self):
        pipeline = make_pipeline(
            FakeTMDB(
                tv_results=[
                    {
                        "id": 321,
                        "name": "大きい女の子",
                        "original_name": "大きい女の子",
                        "first_air_date": "2026-01-01",
                    }
                ]
            )
        )
        pipeline._log = lambda *args, **kwargs: None

        result = pipeline.run(
            {
                "query": "Unrelated Romanized Name",
                "media_type": "tv",
                "media_type_forced": True,
                "search_mode": "tmdb_only",
                "audit_only": True,
                "source_path": "/media/example",
            }
        )

        self.assertEqual(result["status"], "audit_completed")
        self.assertTrue(result["match"]["review_required"])
        self.assertEqual(result["candidate"]["id"], 321)

    def test_manual_match_never_requires_automatic_review(self):
        self.assertFalse(
            MediaPipeline._match_requires_review(
                {"confidence": "low", "review_required": True},
                manual_override=True,
            )
        )

    def test_manual_id_fetch_failure_never_falls_back_to_empty_title_search(self):
        pipeline = object.__new__(MediaPipeline)
        pipeline._log = lambda *args, **kwargs: None
        pipeline._checkpoint = lambda *args, **kwargs: None
        pipeline._step_search = lambda input_data: {
            "selected": {"id": input_data["tmdb_id"], "media_type": "tv"},
            "match": {"provider": "manual", "confidence": "manual"},
        }
        pipeline.tmdb = Mock()
        pipeline.tmdb.get_tv_details.side_effect = RuntimeError("provider unavailable")
        pipeline._step_fetch = Mock(side_effect=RuntimeError("provider unavailable"))

        result = pipeline.run({
            "query": "",
            "tmdb_id": 123,
            "media_type": "tv",
            "fallback_on_fail": True,
        })

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "MANUAL_ID_FETCH_FAILED")
        self.assertEqual(result["tmdb_id"], 123)
        pipeline._step_fetch.assert_called_once_with(123, "tv")
        pipeline.tmdb.search_tv.assert_not_called()


class MatchMemoryStoreTest(unittest.TestCase):
    def test_normalization_handles_unicode_width_punctuation_and_year(self):
        self.assertEqual(
            normalize_match_title("Ｏｏｋｉｉ： Onnanoko (2020)"),
            "ookii onnanoko",
        )

    def test_lookup_rejects_ambiguous_yearless_title(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            store = MatchMemoryStore(str(Path(temp_dir) / "matches.db"))
            store.remember("The Office", 2316, "tv", year=2005)
            store.remember("The Office", 2996, "tv", year=2001)

            self.assertIsNone(store.lookup("The Office", media_type="tv"))
            self.assertEqual(store.lookup("The Office", year=2005, media_type="tv")["tmdb_id"], 2316)

    def test_remember_updates_existing_mapping_and_delete_removes_it(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            store = MatchMemoryStore(str(Path(temp_dir) / "matches.db"))
            first = store.remember("Example Movie", 10, "movie", year=2026)
            updated = store.remember("Example Movie", 11, "movie", year=2026)

            self.assertEqual(first["id"], updated["id"])
            self.assertEqual(store.lookup("example-movie", year=2026, media_type="movie")["tmdb_id"], 11)
            self.assertTrue(store.delete(updated["id"]))
            self.assertIsNone(store.lookup("Example Movie", year=2026, media_type="movie"))

    def test_rejection_persists_tracks_hits_and_can_be_deleted(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            store = MatchMemoryStore(str(Path(temp_dir) / "matches.db"))
            rejected = store.reject("Example Movie", 17, "movie", year=2026)

            hit = store.is_rejected("example-movie", 17, "movie", year=2026)

            self.assertEqual(hit["id"], rejected["id"])
            self.assertEqual(hit["hit_count"], 1)
            self.assertEqual(store.list_rejections()[0]["tmdb_id"], 17)
            self.assertTrue(store.delete_rejection(rejected["id"]))
            self.assertIsNone(store.is_rejected("Example Movie", 17, "movie", year=2026))

    def test_explicit_confirmation_clears_matching_rejection(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            store = MatchMemoryStore(str(Path(temp_dir) / "matches.db"))
            store.reject("Example Movie", 17, "movie", year=2026)

            store.remember("Example Movie", 17, "movie", year=2026)

            self.assertEqual(store.list_rejections(), [])
            self.assertEqual(store.lookup("Example Movie", year=2026, media_type="movie")["tmdb_id"], 17)

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
        self.assertIn("dimensions", result["match"]["candidates"][0]["evidence"])
        self.assertEqual(
            result["match"]["candidates"][0]["evidence"]["dimensions"]["media_type"]["status"],
            "exact",
        )

    def test_configured_matching_threshold_changes_candidate_acceptance(self):
        pipeline = make_pipeline(
            FakeTMDB(
                movie_results=[
                    {
                        "id": 44,
                        "title": "Example Feature Extended",
                        "original_title": "Example Feature Extended",
                        "release_date": "2026-01-01",
                    }
                ]
            )
        )
        pipeline.config = {
            "matching": {
                "minimum_title_similarity": 0.99,
                "minimum_token_overlap": 0.99,
            }
        }

        result = pipeline._step_search(
            {
                "query": "Example Movie",
                "media_type": "movie",
                "media_type_forced": True,
                "search_mode": "tmdb_only",
            }
        )

        self.assertIsNone(result["selected"])
        self.assertEqual(result["match"]["reason"], "low_confidence")
        self.assertEqual(result["match"]["candidates"][0]["decision"], "low_similarity")

    def test_strict_year_can_be_disabled_without_hiding_mismatch_evidence(self):
        pipeline = make_pipeline(
            FakeTMDB(
                movie_results=[
                    {
                        "id": 45,
                        "title": "Example Movie",
                        "original_title": "Example Movie",
                        "release_date": "2025-01-01",
                    }
                ]
            )
        )
        pipeline.config = {"matching": {"strict_year": False}}

        result = pipeline._step_search(
            {
                "query": "Example Movie",
                "year": 2026,
                "media_type": "movie",
                "media_type_forced": True,
                "search_mode": "tmdb_only",
            }
        )

        self.assertEqual(result["selected"]["id"], 45)
        evidence = result["match"]["evidence"]
        self.assertEqual(evidence["dimensions"]["year"]["status"], "mismatch")
        self.assertIn("year_mismatch", evidence["hard_blockers"])

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
