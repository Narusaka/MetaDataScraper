import os
import json
import hashlib
from typing import Dict, Any, Optional
from datetime import datetime, timedelta


class CacheManager:
    def __init__(self, cache_dir: str = ".cache"):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def _get_cache_key(self, key: str) -> str:
        """Generate cache key from string."""
        return hashlib.md5(key.encode()).hexdigest()

    def _get_cache_path(self, key: str) -> str:
        """Get full path for cache file."""
        return os.path.join(self.cache_dir, f"{self._get_cache_key(key)}.json")

    def _is_expired(self, cache_path: str, ttl_hours: int = 24) -> bool:
        """Check if cache file is expired."""
        if not os.path.exists(cache_path):
            return True

        file_time = datetime.fromtimestamp(os.path.getmtime(cache_path))
        return datetime.now() - file_time > timedelta(hours=ttl_hours)

    def get(self, key: str, ttl_hours: int = 24) -> Optional[Dict[str, Any]]:
        """Get cached data if not expired."""
        cache_path = self._get_cache_path(key)

        if self._is_expired(cache_path, ttl_hours):
            return None

        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return None

    def set(self, key: str, data: Dict[str, Any]) -> None:
        """Cache data."""
        cache_path = self._get_cache_path(key)

        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Failed to cache data: {e}")

    def clear_expired(self, ttl_hours: int = 24) -> int:
        """Clear expired cache files."""
        cleared = 0
        for filename in os.listdir(self.cache_dir):
            if filename.endswith('.json'):
                filepath = os.path.join(self.cache_dir, filename)
                if self._is_expired(filepath, ttl_hours):
                    try:
                        os.remove(filepath)
                        cleared += 1
                    except OSError:
                        pass
        return cleared
