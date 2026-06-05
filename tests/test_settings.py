import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from src.server.settings_manager import SettingsManager, SettingsValidationError


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
                    "output": {"image_limit": {"posters": "250", "backdrops": "-3", "logos": "bad", "stills": 7, "actors": 8}},
                    "frontendOnly": {"open": True},
                }
            )

            self.assertTrue(ok)
            saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            self.assertNotIn("frontendOnly", saved)
            self.assertEqual(saved["tmdb"]["api_key"], "tmdb-key")
            self.assertEqual(saved["tavily"]["api_keys"], ["tvly-two", "tvly-three"])
            self.assertEqual(saved["model"]["temperature"], 0.25)
            self.assertEqual(saved["output"]["image_limit"]["posters"], 200)
            self.assertEqual(saved["output"]["image_limit"]["backdrops"], 0)
            self.assertEqual(saved["output"]["image_limit"]["logos"], 5)
            self.assertFalse((config_path.parent / "config.yaml.tmp").exists())

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
