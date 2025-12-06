import os
import json
import hashlib
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta


class TagCacheManager:
    """Cache manager for tag translations."""

    def __init__(self, cache_dir: str = ".cache"):
        self.cache_dir = cache_dir
        self.tag_cache_file = os.path.join(cache_dir, "tag_translations.json")
        os.makedirs(cache_dir, exist_ok=True)
        self._load_cache()

    def _load_cache(self) -> None:
        """Load tag translation cache from file."""
        if os.path.exists(self.tag_cache_file):
            try:
                with open(self.tag_cache_file, 'r', encoding='utf-8') as f:
                    self.cache = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                self.cache = {}
        else:
            self.cache = {}

    def _save_cache(self) -> None:
        """Save tag translation cache to file."""
        try:
            with open(self.tag_cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Failed to save tag cache: {e}")

    def get_translations(self, tags: List[str]) -> Dict[str, str]:
        """Get translations for the given tags from cache."""
        translations = {}
        for tag in tags:
            # Create cache key from tag
            cache_key = hashlib.md5(tag.lower().encode()).hexdigest()
            if cache_key in self.cache:
                cached_data = self.cache[cache_key]
                # Check if cache is not too old (30 days)
                if self._is_recent(cached_data.get('timestamp', 0)):
                    translations[tag] = cached_data['translation']
        return translations

    def set_translations(self, tag_translations: Dict[str, str]) -> None:
        """Store translations in cache."""
        timestamp = datetime.now().timestamp()
        for tag, translation in tag_translations.items():
            cache_key = hashlib.md5(tag.lower().encode()).hexdigest()
            self.cache[cache_key] = {
                'original': tag,
                'translation': translation,
                'timestamp': timestamp
            }
        self._save_cache()

    def _is_recent(self, timestamp: float, days: int = 30) -> bool:
        """Check if timestamp is within the specified number of days."""
        cache_time = datetime.fromtimestamp(timestamp)
        return datetime.now() - cache_time < timedelta(days=days)

    def get_uncached_tags(self, tags: List[str]) -> List[str]:
        """Get list of tags that are not in cache."""
        cached = self.get_translations(tags)
        return [tag for tag in tags if tag not in cached]

    def clear_old_cache(self, days: int = 30) -> int:
        """Clear cache entries older than specified days."""
        cleared = 0
        current_time = datetime.now().timestamp()
        max_age = timedelta(days=days).total_seconds()

        keys_to_remove = []
        for key, data in self.cache.items():
            if current_time - data.get('timestamp', 0) > max_age:
                keys_to_remove.append(key)

        for key in keys_to_remove:
            del self.cache[key]
            cleared += 1

        if cleared > 0:
            self._save_cache()

        return cleared
