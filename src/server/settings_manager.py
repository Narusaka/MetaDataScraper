
import yaml
import os
import shutil
import copy
from urllib.parse import urlparse
from pathlib import Path
from typing import Dict, Any, Optional

class SettingsValidationError(ValueError):
    pass

class SettingsManager:
    def __init__(self, config_path: str = "config/config.yaml"):
        self.config_path = Path(config_path)
        self.config_data = {}
        self._load()

    def _defaults(self) -> Dict[str, Any]:
        return {
            "tmdb": {"api_key": ""},
            "omdb": {"api_key": ""},
            "tavily": {"api_key": ""},
            "model": {
                "base_url": "http://127.0.0.1:8045/v1",
                "api_key": "EMPTY",
                "model": "gemini-3-flash",
                "temperature": 0.1,
            },
            "output": {"image_limit": {"posters": 20, "backdrops": 5, "logos": 5, "stills": 10, "actors": 10}},
        }

    def _deep_update(self, target: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                self._deep_update(target[key], value)
            else:
                target[key] = value
        return target

    def _coerce_int(self, value: Any, default: int, min_value: int = 0, max_value: int = 200) -> int:
        try:
            return max(min_value, min(max_value, int(value)))
        except (TypeError, ValueError):
            return default

    def _coerce_float(self, value: Any, default: float, min_value: float = 0.0, max_value: float = 2.0) -> float:
        try:
            return max(min_value, min(max_value, float(value)))
        except (TypeError, ValueError):
            return default

    def _mask_secret(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if len(text) <= 8:
            return "********"
        return f"{text[:4]}********{text[-4:]}"

    def _is_masked_secret(self, value: Any) -> bool:
        text = str(value or "")
        return bool(text) and "********" in text

    def _resolve_secret(self, incoming: Any, existing: Any) -> str:
        if self._is_masked_secret(incoming):
            return str(existing or "").strip()
        return str(incoming or "").strip()

    def _validate_url(self, value: str, field_name: str, required: bool = False) -> str:
        text = str(value or "").strip()
        if not text:
            if required:
                raise SettingsValidationError(f"{field_name} is required")
            return ""
        parsed = urlparse(text)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise SettingsValidationError(f"{field_name} must be an http(s) URL")
        return text.rstrip("/")

    def _validate_proxy(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._validate_url(value, "proxy")
        if isinstance(value, dict):
            normalized = {}
            for key, item in value.items():
                if key not in {"http", "https"}:
                    raise SettingsValidationError("proxy only supports http and https keys")
                normalized[key] = self._validate_url(item, f"proxy.{key}", required=True)
            return normalized
        raise SettingsValidationError("proxy must be a URL string or an object with http/https URLs")

    def _normalize_settings(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        raw = raw or {}
        current = self._deep_update(self._defaults(), copy.deepcopy(self.config_data))
        normalized = self._defaults()

        for section in ("tmdb", "omdb", "tavily"):
            section_data = raw.get(section, {})
            existing = current.get(section, {})
            if isinstance(section_data, dict):
                api_key = section_data.get("api_key", existing.get("api_key", ""))
                normalized[section]["api_key"] = self._resolve_secret(api_key, existing.get("api_key", ""))
                if section == "tavily":
                    api_keys = section_data.get("api_keys", existing.get("api_keys", []))
                    if isinstance(api_keys, str):
                        api_keys = [api_keys]
                    if isinstance(api_keys, list):
                        existing_keys = existing.get("api_keys", [])
                        if not isinstance(existing_keys, list):
                            existing_keys = []
                        normalized[section]["api_keys"] = [
                            self._resolve_secret(item, existing_keys[index] if index < len(existing_keys) else "")
                            for index, item in enumerate(api_keys)
                            if str(item).strip()
                        ]

        model_data = raw.get("model", {}) if isinstance(raw.get("model"), dict) else {}
        existing_model = current.get("model", {})
        normalized["model"] = {
            "base_url": self._validate_url(
                model_data.get("base_url", existing_model.get("base_url", normalized["model"]["base_url"])),
                "model.base_url",
                required=True,
            ),
            "api_key": self._resolve_secret(
                model_data.get("api_key", existing_model.get("api_key", normalized["model"]["api_key"])),
                existing_model.get("api_key", normalized["model"]["api_key"]),
            ),
            "model": str(model_data.get("model", existing_model.get("model", normalized["model"]["model"])) or "").strip(),
            "temperature": self._coerce_float(
                model_data.get("temperature", existing_model.get("temperature", normalized["model"]["temperature"])),
                float(normalized["model"]["temperature"]),
            ),
        }

        image_defaults = normalized["output"]["image_limit"]
        image_data = raw.get("output", {}).get("image_limit", {}) if isinstance(raw.get("output"), dict) else {}
        existing_images = current.get("output", {}).get("image_limit", {})
        normalized["output"]["image_limit"] = {
            key: self._coerce_int(image_data.get(key, existing_images.get(key, default)), default, min_value=0, max_value=200)
            for key, default in image_defaults.items()
        }

        if isinstance(raw.get("proxy"), dict) or isinstance(raw.get("proxy"), str):
            normalized["proxy"] = self._validate_proxy(raw["proxy"])
        elif "proxy" in current:
            normalized["proxy"] = self._validate_proxy(current["proxy"])

        return normalized

    def _load(self):
        data = {}
        if self.config_path.exists():
            with open(self.config_path, 'r') as f:
                data = yaml.safe_load(f) or {}
        self.config_data = self._deep_update(self._defaults(), data)

    def _masked_copy(self, config: Dict[str, Any]) -> Dict[str, Any]:
        masked = copy.deepcopy(config)
        for section in ("tmdb", "omdb", "tavily"):
            if isinstance(masked.get(section), dict):
                masked[section]["api_key"] = self._mask_secret(masked[section].get("api_key", ""))
                if section == "tavily" and isinstance(masked[section].get("api_keys"), list):
                    masked[section]["api_keys"] = [self._mask_secret(item) for item in masked[section].get("api_keys", [])]
        if isinstance(masked.get("model"), dict):
            masked["model"]["api_key"] = self._mask_secret(masked["model"].get("api_key", ""))
        return masked

    def get_settings(self) -> Dict[str, Any]:
        # Reload to ensure we have the latest
        self._load() 
        return self._masked_copy(self.config_data)

    def save_settings(self, new_settings: Dict[str, Any]) -> bool:
        try:
            normalized = self._normalize_settings(new_settings)
            
            # Ensure directory exists
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            
            tmp_path = self.config_path.with_suffix(self.config_path.suffix + ".tmp")
            with open(tmp_path, 'w') as f:
                yaml.safe_dump(normalized, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            tmp_path.replace(self.config_path)
            self.config_data = normalized
            
            return True
        except SettingsValidationError:
            raise
        except Exception as e:
            print(f"Error saving config: {e}")
            return False

    def get_effective_config(self) -> Dict[str, Any]:
        """
        Returns the config as it would be seen by the Scraper 
        (injecting env vars). Useful for debugging.
        """
        self._load()
        config = copy.deepcopy(self.config_data)
        
        def inject(key, env_var):
             if val := os.getenv(env_var):
                 # traverse and set
                 parts = key.split('.')
                 curr = config
                 for part in parts[:-1]:
                     curr = curr.setdefault(part, {})
                 curr[parts[-1]] = val
        
        inject("tmdb.api_key", "TMDB_API_KEY")
        inject("omdb.api_key", "OMDB_API_KEY")
        inject("model.api_key", "MODEL_API_KEY")
        inject("model.base_url", "MODEL_BASE_URL")
        inject("tavily.api_key", "TAVILY_API_KEY")
        
        return config
