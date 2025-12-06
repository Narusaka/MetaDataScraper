import requests
from typing import Dict, Any, Optional
import os
import time


class TMDBAdapter:
    def __init__(self, api_key: str, proxy: Optional[Dict[str, str]] = None, preferred_language: str = "zh-CN"):
        self.base_url = "https://api.themoviedb.org/3"
        self.api_key = api_key
        self.proxy = proxy
        self.preferred_language = preferred_language
        # Set language priority based on preferred language
        if preferred_language == "zh-CN":
            self.language_priority = ["zh-CN", "zh-TW", "en-US"]
        elif preferred_language == "zh-TW":
            self.language_priority = ["zh-TW", "zh-CN", "en-US"]
        else:  # en-US or other
            self.language_priority = ["en-US", "zh-CN", "zh-TW"]
        self.session = requests.Session()
        if proxy:
            self.session.proxies.update(proxy)

    def _make_request(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make API request with retries and timeout."""
        url = f"{self.base_url}{endpoint}"
        params = params.copy() if params else {}
        params['api_key'] = self.api_key

        for attempt in range(3):
            try:
                response = self.session.get(url, params=params, timeout=30)
                response.raise_for_status()
                return response.json()
            except requests.RequestException as e:
                if attempt == 2:
                    raise e
                time.sleep(1)

    def get_movie_details(self, tmdb_id: int) -> Dict[str, Any]:
        """Get movie details with language fallback."""
        for lang in self.language_priority:
            try:
                return self._make_request(f"/movie/{tmdb_id}", {"language": lang})
            except requests.RequestException:
                continue
        raise Exception(f"Failed to fetch movie {tmdb_id} in any language")

    def get_tv_details(self, tmdb_id: int) -> Dict[str, Any]:
        """Get TV show details with language fallback."""
        for lang in self.language_priority:
            try:
                return self._make_request(f"/tv/{tmdb_id}", {"language": lang})
            except requests.RequestException:
                continue
        raise Exception(f"Failed to fetch TV show {tmdb_id} in any language")

    def get_tv_season_details(self, tmdb_id: int, season_number: int) -> Dict[str, Any]:
        """Get TV season details with language fallback."""
        for lang in self.language_priority:
            try:
                return self._make_request(f"/tv/{tmdb_id}/season/{season_number}", {"language": lang})
            except requests.RequestException:
                continue
        raise Exception(f"Failed to fetch TV season {tmdb_id} season {season_number} in any language")

    def get_tv_episode_details(self, tmdb_id: int, season_number: int, episode_number: int) -> Dict[str, Any]:
        """Get TV episode details with language fallback."""
        for lang in self.language_priority:
            try:
                return self._make_request(f"/tv/{tmdb_id}/season/{season_number}/episode/{episode_number}", {"language": lang})
            except requests.RequestException:
                continue
        raise Exception(f"Failed to fetch TV episode {tmdb_id} season {season_number} episode {episode_number} in any language")

    def search_movie(self, query: str) -> Dict[str, Any]:
        """Search for movies."""
        return self._make_request("/search/movie", {"query": query})

    def search_tv(self, query: str) -> Dict[str, Any]:
        """Search for TV shows."""
        return self._make_request("/search/tv", {"query": query})

    def get_images(self, media_type: str, tmdb_id: int) -> Dict[str, Any]:
        """Get images for movie or TV show."""
        return self._make_request(f"/{media_type}/{tmdb_id}/images")

    def get_credits(self, media_type: str, tmdb_id: int) -> Dict[str, Any]:
        """Get credits for movie or TV show."""
        return self._make_request(f"/{media_type}/{tmdb_id}/credits")

    def get_tv_episode_images(self, tmdb_id: int, season_number: int, episode_number: int) -> Dict[str, Any]:
        """Get images for a specific TV episode."""
        return self._make_request(f"/tv/{tmdb_id}/season/{season_number}/episode/{episode_number}/images")

    def find_by_imdb_id(self, imdb_id: str) -> Dict[str, Any]:
        """Find TMDB ID by IMDB ID."""
        return self._make_request("/find/" + imdb_id, {"external_source": "imdb_id"})

    def get_keywords(self, media_type: str, tmdb_id: int) -> Dict[str, Any]:
        """Get keywords for movie or TV show."""
        try:
            return self._make_request(f"/{media_type}/{tmdb_id}/keywords")
        except requests.RequestException:
            # Keywords endpoint might not be available for all media
            return {"keywords": []}
