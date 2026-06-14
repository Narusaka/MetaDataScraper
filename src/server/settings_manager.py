
import yaml
import os
import copy
import hashlib
import json
import threading
from urllib.parse import urlparse
from pathlib import Path
from typing import Dict, Any, List, Optional

from src.storage.settings_audit import SettingsAuditStore

class SettingsValidationError(ValueError):
    pass

class SettingsConflictError(RuntimeError):
    pass

class SettingsManager:
    def __init__(self, config_path: str = "config/config.yaml", audit_path: Optional[str] = None):
        self.config_path = Path(config_path)
        if audit_path is None:
            audit_path = (
                "logs/settings_audit.db"
                if self.config_path == Path("config/config.yaml")
                else str(self.config_path.parent / "settings_audit.db")
            )
        self.audit_store = SettingsAuditStore(audit_path)
        self._lock = threading.RLock()
        self.config_data = {}
        self.last_revision: Optional[Dict[str, Any]] = None
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
            "matching": {
                "minimum_title_similarity": 0.55,
                "minimum_token_overlap": 0.75,
                "high_confidence_title_similarity": 0.75,
                "high_confidence_token_overlap": 0.85,
                "localized_title_min_similarity": 0.25,
                "strict_year": True,
            },
            "output": {
                "conflict_strategy": "error",
                "nfo_policy": {
                    "profile": "universal",
                    "targets": ["jellyfin", "emby", "kodi"],
                    "include_uniqueid": True,
                    "include_legacy_tmdbid": True,
                    "episode_sidecars": "present_only",
                },
                "image_limit": {"posters": 20, "backdrops": 5, "logos": 5, "stills": 10, "actors": 10},
                "artwork_policy": {
                    "preferred_languages": ["zh", "en", "ja"],
                    "min_poster_width": 500,
                    "min_backdrop_width": 1280,
                    "min_logo_width": 300,
                },
            },
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

    def _coerce_bool(self, value: Any, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off"}:
                return False
        if isinstance(value, (int, float)):
            return bool(value)
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

        matching_data = raw.get("matching", {}) if isinstance(raw.get("matching"), dict) else {}
        existing_matching = current.get("matching", {})
        matching_defaults = normalized["matching"]
        normalized["matching"] = {
            "minimum_title_similarity": self._coerce_float(
                matching_data.get(
                    "minimum_title_similarity",
                    existing_matching.get("minimum_title_similarity", matching_defaults["minimum_title_similarity"]),
                ),
                matching_defaults["minimum_title_similarity"],
                max_value=1.0,
            ),
            "minimum_token_overlap": self._coerce_float(
                matching_data.get(
                    "minimum_token_overlap",
                    existing_matching.get("minimum_token_overlap", matching_defaults["minimum_token_overlap"]),
                ),
                matching_defaults["minimum_token_overlap"],
                max_value=1.0,
            ),
            "high_confidence_title_similarity": self._coerce_float(
                matching_data.get(
                    "high_confidence_title_similarity",
                    existing_matching.get("high_confidence_title_similarity", matching_defaults["high_confidence_title_similarity"]),
                ),
                matching_defaults["high_confidence_title_similarity"],
                max_value=1.0,
            ),
            "high_confidence_token_overlap": self._coerce_float(
                matching_data.get(
                    "high_confidence_token_overlap",
                    existing_matching.get("high_confidence_token_overlap", matching_defaults["high_confidence_token_overlap"]),
                ),
                matching_defaults["high_confidence_token_overlap"],
                max_value=1.0,
            ),
            "localized_title_min_similarity": self._coerce_float(
                matching_data.get(
                    "localized_title_min_similarity",
                    existing_matching.get("localized_title_min_similarity", matching_defaults["localized_title_min_similarity"]),
                ),
                matching_defaults["localized_title_min_similarity"],
                max_value=1.0,
            ),
            "strict_year": self._coerce_bool(
                matching_data.get(
                    "strict_year",
                    existing_matching.get("strict_year", matching_defaults["strict_year"]),
                ),
                matching_defaults["strict_year"],
            ),
        }
        if normalized["matching"]["high_confidence_title_similarity"] < normalized["matching"]["minimum_title_similarity"]:
            raise SettingsValidationError(
                "matching.high_confidence_title_similarity must be greater than or equal to matching.minimum_title_similarity"
            )
        if normalized["matching"]["high_confidence_token_overlap"] < normalized["matching"]["minimum_token_overlap"]:
            raise SettingsValidationError(
                "matching.high_confidence_token_overlap must be greater than or equal to matching.minimum_token_overlap"
            )

        image_defaults = normalized["output"]["image_limit"]
        image_data = raw.get("output", {}).get("image_limit", {}) if isinstance(raw.get("output"), dict) else {}
        existing_images = current.get("output", {}).get("image_limit", {})
        normalized["output"]["image_limit"] = {
            key: self._coerce_int(image_data.get(key, existing_images.get(key, default)), default, min_value=0, max_value=200)
            for key, default in image_defaults.items()
        }
        policy_defaults = normalized["output"]["artwork_policy"]
        output_data = raw.get("output", {}) if isinstance(raw.get("output"), dict) else {}
        existing_output = current.get("output", {})
        conflict_strategy = str(output_data.get("conflict_strategy", existing_output.get("conflict_strategy", "error")) or "error").strip().lower()
        if conflict_strategy not in {"error", "skip", "suffix", "overwrite"}:
            raise SettingsValidationError("output.conflict_strategy must be error, skip, suffix, or overwrite")
        normalized["output"]["conflict_strategy"] = conflict_strategy
        nfo_defaults = normalized["output"]["nfo_policy"]
        nfo_data = output_data.get("nfo_policy", {}) if isinstance(output_data.get("nfo_policy"), dict) else {}
        existing_nfo = existing_output.get("nfo_policy", {})
        targets = nfo_data.get("targets", existing_nfo.get("targets", nfo_defaults["targets"]))
        if isinstance(targets, str):
            targets = targets.split(",")
        supported_targets = []
        for target in targets if isinstance(targets, list) else nfo_defaults["targets"]:
            value = str(target or "").strip().lower()
            if value in {"jellyfin", "emby", "kodi"} and value not in supported_targets:
                supported_targets.append(value)
        normalized["output"]["nfo_policy"] = {
            "profile": "universal",
            "targets": supported_targets or nfo_defaults["targets"],
            "include_uniqueid": bool(nfo_data.get("include_uniqueid", existing_nfo.get("include_uniqueid", True))),
            "include_legacy_tmdbid": bool(nfo_data.get("include_legacy_tmdbid", existing_nfo.get("include_legacy_tmdbid", True))),
            "episode_sidecars": "present_only",
        }
        policy_data = output_data.get("artwork_policy", {}) if isinstance(output_data.get("artwork_policy"), dict) else {}
        existing_policy = current.get("output", {}).get("artwork_policy", {})
        languages = policy_data.get("preferred_languages", existing_policy.get("preferred_languages", policy_defaults["preferred_languages"]))
        if isinstance(languages, str):
            languages = languages.split(",")
        normalized_languages = []
        for language in languages if isinstance(languages, list) else policy_defaults["preferred_languages"]:
            value = str(language or "").strip().lower().split("-")[0]
            if value and value not in normalized_languages:
                normalized_languages.append(value)
        normalized["output"]["artwork_policy"] = {
            "preferred_languages": normalized_languages or policy_defaults["preferred_languages"],
            "min_poster_width": self._coerce_int(
                policy_data.get("min_poster_width", existing_policy.get("min_poster_width", policy_defaults["min_poster_width"])),
                policy_defaults["min_poster_width"],
                max_value=10000,
            ),
            "min_backdrop_width": self._coerce_int(
                policy_data.get("min_backdrop_width", existing_policy.get("min_backdrop_width", policy_defaults["min_backdrop_width"])),
                policy_defaults["min_backdrop_width"],
                max_value=10000,
            ),
            "min_logo_width": self._coerce_int(
                policy_data.get("min_logo_width", existing_policy.get("min_logo_width", policy_defaults["min_logo_width"])),
                policy_defaults["min_logo_width"],
                max_value=10000,
            ),
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

    def _changed_paths(self, before: Any, after: Any, prefix: str = "") -> List[str]:
        if isinstance(before, dict) and isinstance(after, dict):
            paths: List[str] = []
            for key in sorted(set(before) | set(after)):
                child_prefix = f"{prefix}.{key}" if prefix else str(key)
                if key not in before or key not in after:
                    paths.append(child_prefix)
                else:
                    paths.extend(self._changed_paths(before[key], after[key], child_prefix))
            return paths
        if before != after:
            return [prefix or "config"]
        return []

    def _config_fingerprint(self, config: Dict[str, Any]) -> str:
        canonical = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _inject_environment(self, config: Dict[str, Any]) -> Dict[str, Any]:
        def inject(key: str, env_var: str) -> None:
            if val := os.getenv(env_var):
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

    def get_settings(self) -> Dict[str, Any]:
        with self._lock:
            self._load()
            masked = self._masked_copy(self.config_data)
            masked["_meta"] = {"revision": self.audit_store.current_revision()}
            return masked

    def save_settings(self, new_settings: Dict[str, Any], actor: str = "system") -> bool:
        with self._lock:
            try:
                expected_revision = None
                if isinstance(new_settings.get("_meta"), dict):
                    expected_revision = new_settings["_meta"].get("revision")
                current_revision = self.audit_store.current_revision()
                if expected_revision is not None:
                    try:
                        expected_revision = int(expected_revision)
                    except (TypeError, ValueError):
                        raise SettingsValidationError("_meta.revision must be an integer")
                    if expected_revision != current_revision:
                        raise SettingsConflictError(
                            f"Settings changed since this page was loaded "
                            f"(expected revision {expected_revision}, current revision {current_revision})"
                        )
                normalized = self._normalize_settings(new_settings)
                before = copy.deepcopy(self.config_data)
                changed_paths = self._changed_paths(before, normalized)

                if not changed_paths:
                    self.last_revision = None
                    return True

                self.config_path.parent.mkdir(parents=True, exist_ok=True)
                previous_content = self.config_path.read_bytes() if self.config_path.exists() else None
                tmp_path = self.config_path.with_suffix(self.config_path.suffix + ".tmp")
                with open(tmp_path, 'w') as f:
                    yaml.safe_dump(normalized, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
                tmp_path.replace(self.config_path)

                try:
                    revision = self.audit_store.record(
                        actor=actor,
                        changed_paths=changed_paths,
                        config_fingerprint=self._config_fingerprint(normalized),
                    )
                except Exception:
                    restore_path = self.config_path.with_suffix(self.config_path.suffix + ".restore")
                    if previous_content is None:
                        self.config_path.unlink(missing_ok=True)
                    else:
                        restore_path.write_bytes(previous_content)
                        restore_path.replace(self.config_path)
                    raise

                self.config_data = normalized
                self.last_revision = revision
                return True
            except (SettingsValidationError, SettingsConflictError):
                raise
            except Exception as e:
                print(f"Error saving config: {e}")
                return False

    def get_revision_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            return self.audit_store.list_recent(limit)

    def get_runtime_context(self) -> Dict[str, Any]:
        """Freeze the effective runtime config and its non-secret audit evidence."""
        with self._lock:
            self._load()
            config = self._inject_environment(copy.deepcopy(self.config_data))
            return {
                "config": config,
                "revision": self.audit_store.current_revision(),
                "fingerprint": self._config_fingerprint(config),
            }

    def get_effective_config(self) -> Dict[str, Any]:
        """
        Returns the config as it would be seen by the Scraper
        (injecting env vars). Useful for debugging.
        """
        return self.get_runtime_context()["config"]
