import requests
from typing import Dict, Any, Optional
import time


class OMDBAdapter:
    def __init__(self, api_key: str, proxy: Optional[Dict[str, str]] = None):
        self.base_url = "http://www.omdbapi.com/"
        self.api_key = api_key
        self.proxy = proxy
        self.session = requests.Session()
        if proxy:
            self.session.proxies.update(proxy)

    def _make_request(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Make API request with retries and timeout."""
        params['apikey'] = self.api_key

        for attempt in range(3):
            try:
                response = self.session.get(self.base_url, params=params, timeout=30)
                response.raise_for_status()
                data = response.json()
                if data.get('Response') == 'False':
                    raise Exception(f"OMDB API error: {data.get('Error')}")
                return data
            except requests.RequestException as e:
                if attempt == 2:
                    raise e
                time.sleep(1)

    def get_movie_details(self, imdb_id: str) -> Dict[str, Any]:
        """Get movie details by IMDB ID."""
        return self._make_request({"i": imdb_id})

    def get_tv_details(self, imdb_id: str) -> Dict[str, Any]:
        """Get TV show details by IMDB ID."""
        return self._make_request({"i": imdb_id})

    def search_by_title(self, title: str, year: Optional[int] = None) -> Dict[str, Any]:
        """Search by title and optional year."""
        params = {"t": title}
        if year:
            params["y"] = str(year)
        return self._make_request(params)
