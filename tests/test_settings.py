import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from src.server.settings_manager import SettingsConflictError, SettingsManager, SettingsValidationError


class SettingsManagerTest(unittest.TestCase):
    def test_save_settings_normalizes_known_sections_and_drops_unknown_keys(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            manager = SettingsManager(str(config_path))

            ok = manager.save_settings(
                {
                    "tmdb": {"api_key": "  tmdb-key  "},
                    "tavily": {"api_key": "tvly-one", "api_keys": ["tvly-two", "", "  tvly-three  "]},
                    "model": {"base_url": " http://127.0.0.1:8045/v1 ", "api_key": " EMPTY ", "model": "gemini", "temperature": "0.25"},
                    "matching": {
                        "minimum_title_similarity": "0.65",
                        "minimum_token_overlap": "0.8",
                        "high_confidence_title_similarity": "0.85",
                        "high_confidence_token_overlap": "0.9",
                        "localized_title_min_similarity": "0.3",
                        "strict_year": False,
                    },
                    "output": {
                        "conflict_strategy": "suffix",
                        "nfo_policy": {
                            "profile": "custom",
                            "targets": "Kodi, Jellyfin, unknown",
                            "include_uniqueid": False,
                            "include_legacy_tmdbid": True,
                            "episode_sidecars": "all",
                        },
                        "image_limit": {"posters": "250", "backdrops": "-3", "logos": "bad", "stills": 7, "actors": 8},
                        "artwork_policy": {
                            "preferred_languages": "zh-CN, en, zh",
                            "min_poster_width": "750",
                            "min_backdrop_width": "20000",
                            "min_logo_width": "-1",
                        },
                    },
                    "frontendOnly": {"open": True},
                }
            )

            self.assertTrue(ok)
            saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            self.assertNotIn("frontendOnly", saved)
            self.assertEqual(saved["tmdb"]["api_key"], "tmdb-key")
            self.assertEqual(saved["tavily"]["api_keys"], ["tvly-two", "tvly-three"])
            self.assertEqual(saved["model"]["temperature"], 0.25)
            self.assertEqual(saved["matching"]["minimum_title_similarity"], 0.65)
            self.assertEqual(saved["matching"]["minimum_token_overlap"], 0.8)
            self.assertEqual(saved["matching"]["high_confidence_title_similarity"], 0.85)
            self.assertEqual(saved["matching"]["high_confidence_token_overlap"], 0.9)
            self.assertEqual(saved["matching"]["localized_title_min_similarity"], 0.3)
            self.assertFalse(saved["matching"]["strict_year"])
            self.assertEqual(saved["output"]["conflict_strategy"], "suffix")
            self.assertEqual(saved["output"]["nfo_policy"]["profile"], "universal")
            self.assertEqual(saved["output"]["nfo_policy"]["targets"], ["kodi", "jellyfin"])
            self.assertFalse(saved["output"]["nfo_policy"]["include_uniqueid"])
            self.assertEqual(saved["output"]["nfo_policy"]["episode_sidecars"], "present_only")
            self.assertEqual(saved["output"]["image_limit"]["posters"], 200)
            self.assertEqual(saved["output"]["image_limit"]["backdrops"], 0)
            self.assertEqual(saved["output"]["image_limit"]["logos"], 5)
            self.assertEqual(saved["output"]["artwork_policy"]["preferred_languages"], ["zh", "en"])
            self.assertEqual(saved["output"]["artwork_policy"]["min_poster_width"], 750)
            self.assertEqual(saved["output"]["artwork_policy"]["min_backdrop_width"], 10000)
            self.assertEqual(saved["output"]["artwork_policy"]["min_logo_width"], 0)
            self.assertFalse((config_path.parent / "config.yaml.tmp").exists())

    def test_invalid_conflict_strategy_is_rejected(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            manager = SettingsManager(str(config_path))

            with self.assertRaises(SettingsValidationError):
                manager.save_settings({"output": {"conflict_strategy": "merge-anything"}})

    def test_high_confidence_threshold_cannot_be_lower_than_acceptance_threshold(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            manager = SettingsManager(str(config_path))

            with self.assertRaises(SettingsValidationError):
                manager.save_settings({
                    "matching": {
                        "minimum_title_similarity": 0.8,
                        "high_confidence_title_similarity": 0.7,
                    }
                })

    def test_effective_config_injects_tavily_env_key(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            manager = SettingsManager(str(config_path))
            manager.save_settings({"tavily": {"api_key": "file-key"}})

            with patch.dict(os.environ, {"TAVILY_API_KEY": "env-key"}, clear=False):
                effective = manager.get_effective_config()

            self.assertEqual(effective["tavily"]["api_key"], "env-key")

    def test_get_settings_masks_secrets_but_effective_config_keeps_real_values(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            manager = SettingsManager(str(config_path))
            manager.save_settings(
                {
                    "tmdb": {"api_key": "tmdb-secret-value"},
                    "tavily": {"api_key": "tvly-secret-value", "api_keys": ["tvly-extra-one"]},
                    "model": {"api_key": "model-secret-value"},
                }
            )

            settings = manager.get_settings()
            effective = manager.get_effective_config()

            self.assertEqual(settings["tmdb"]["api_key"], "tmdb********alue")
            self.assertEqual(settings["tavily"]["api_key"], "tvly********alue")
            self.assertEqual(settings["tavily"]["api_keys"], ["tvly********-one"])
            self.assertEqual(settings["model"]["api_key"], "mode********alue")
            self.assertEqual(effective["tmdb"]["api_key"], "tmdb-secret-value")
            self.assertEqual(effective["tavily"]["api_key"], "tvly-secret-value")
            self.assertEqual(effective["model"]["api_key"], "model-secret-value")

    def test_save_settings_preserves_existing_secret_when_masked_value_is_submitted(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            manager = SettingsManager(str(config_path))
            manager.save_settings(
                {
                    "tmdb": {"api_key": "tmdb-secret-value"},
                    "tavily": {"api_key": "tvly-secret-value", "api_keys": ["tvly-extra-one"]},
                    "model": {"api_key": "model-secret-value", "base_url": "http://old", "model": "old"},
                }
            )
            masked = manager.get_settings()
            masked["model"]["base_url"] = "http://new"

            ok = manager.save_settings(masked)
            saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))

            self.assertTrue(ok)
            self.assertEqual(saved["tmdb"]["api_key"], "tmdb-secret-value")
            self.assertEqual(saved["tavily"]["api_key"], "tvly-secret-value")
            self.assertEqual(saved["tavily"]["api_keys"], ["tvly-extra-one"])
            self.assertEqual(saved["model"]["api_key"], "model-secret-value")
            self.assertEqual(saved["model"]["base_url"], "http://new")

    def test_settings_history_records_changed_paths_without_secret_values(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            manager = SettingsManager(str(config_path))

            self.assertTrue(manager.save_settings(
                {
                    "tmdb": {"api_key": "tmdb-super-secret"},
                    "matching": {"minimum_title_similarity": 0.7},
                },
                actor="web",
            ))

            history = manager.get_revision_history()
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["actor"], "web")
            self.assertIn("tmdb.api_key", history[0]["changed_paths"])
            self.assertIn("matching.minimum_title_similarity", history[0]["changed_paths"])
            self.assertEqual(len(history[0]["config_fingerprint"]), 64)
            self.assertNotIn("tmdb-super-secret", str(history))

    def test_saving_unchanged_masked_settings_does_not_create_revision(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            manager = SettingsManager(str(config_path))
            self.assertTrue(manager.save_settings({"tmdb": {"api_key": "tmdb-super-secret"}}))
            masked = manager.get_settings()

            self.assertTrue(manager.save_settings(masked, actor="web"))

            self.assertEqual(len(manager.get_revision_history()), 1)
            self.assertIsNone(manager.last_revision)

    def test_stale_settings_revision_is_rejected_without_overwrite(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            manager = SettingsManager(str(config_path))
            self.assertTrue(manager.save_settings({"tmdb": {"api_key": "old-key"}}))
            stale = manager.get_settings()
            fresh = manager.get_settings()
            fresh["matching"]["minimum_title_similarity"] = 0.7
            self.assertTrue(manager.save_settings(fresh, actor="web"))
            before = config_path.read_bytes()

            stale["matching"]["minimum_token_overlap"] = 0.8
            with self.assertRaises(SettingsConflictError):
                manager.save_settings(stale, actor="web")

            self.assertEqual(config_path.read_bytes(), before)
            self.assertEqual(len(manager.get_revision_history()), 2)

    def test_audit_failure_restores_previous_config(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            manager = SettingsManager(str(config_path))
            self.assertTrue(manager.save_settings({"tmdb": {"api_key": "old-key"}}))
            before = config_path.read_bytes()

            with patch.object(manager.audit_store, "record", side_effect=OSError("audit disk unavailable")):
                self.assertFalse(manager.save_settings({"tmdb": {"api_key": "new-key"}}))

            self.assertEqual(config_path.read_bytes(), before)
            self.assertEqual(manager.get_effective_config()["tmdb"]["api_key"], "old-key")
            self.assertFalse((config_path.parent / "config.yaml.restore").exists())

    def test_invalid_model_base_url_is_rejected_without_overwriting_config(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            manager = SettingsManager(str(config_path))
            self.assertTrue(manager.save_settings({"model": {"base_url": "http://valid.local/v1", "api_key": "old"}}))
            before = config_path.read_text(encoding="utf-8")

            with self.assertRaises(SettingsValidationError):
                manager.save_settings({"model": {"base_url": "not-a-url", "api_key": "new"}})

            self.assertEqual(config_path.read_text(encoding="utf-8"), before)
            saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["model"]["base_url"], "http://valid.local/v1")
            self.assertEqual(saved["model"]["api_key"], "old")

    def test_proxy_validation_accepts_http_https_and_rejects_unknown_keys(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            manager = SettingsManager(str(config_path))

            self.assertTrue(manager.save_settings({"proxy": {"http": "http://127.0.0.1:7890/", "https": "https://proxy.local"}}))
            saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["proxy"]["http"], "http://127.0.0.1:7890")
            self.assertEqual(saved["proxy"]["https"], "https://proxy.local")

            before = config_path.read_text(encoding="utf-8")
            with self.assertRaises(SettingsValidationError):
                manager.save_settings({"proxy": {"ftp": "http://127.0.0.1:7890"}})
            self.assertEqual(config_path.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
