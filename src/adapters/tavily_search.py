
import requests
import random
from typing import List, Optional, Dict, Any

class TavilySearchAdapter:
    """Adapter for Tavily Search API with multi-key support."""
    
    BASE_URL = "https://api.tavily.com/search"

    def __init__(self, api_keys: List[str], proxy: Optional[Dict] = None):
        self.api_keys = [k for k in api_keys if k]
        self.proxy = proxy
        if not self.api_keys:
            raise ValueError("At least one Tavily API key is required")

    def _get_api_key(self) -> str:
        """Get a random API key for load balancing."""
        return random.choice(self.api_keys)

    def search(self, query: str, search_depth: str = "basic", max_results: int = 5) -> List[Dict[str, Any]]:
        """Perform a search query."""
        payload = {
            "api_key": self._get_api_key(),
            "query": query,
            "search_depth": search_depth,
            "max_results": max_results,
            "include_domains": ["themoviedb.org", "imdb.com", "douban.com"],
        }
        
        try:
            response = requests.post(
                self.BASE_URL, 
                json=payload, 
                proxies=self.proxy, 
                timeout=15
            )
            response.raise_for_status()
            data = response.json()
            return data.get("results", [])
        except Exception as e:
            print(f"Directory Tavily Search failed: {e}")
            return []

    def search_tmdb_id(self, query: str, media_type: str = "tv", verbose: bool = False) -> Optional[int]:
        """Search specifically for TMDB ID using Tavily."""
        # Enhanced query for better results - restricts search to TMDB domain implicitly via keywords
        # and explicitly via include_domains in the search call
        search_query = f"{query} {media_type} tmdb"
        
        # Use simple search depth for speed, result is usually top 1
        payload = {
            "api_key": self._get_api_key(),
            "query": search_query,
            "search_depth": "basic",
            "max_results": 5,
            "include_domains": ["themoviedb.org"],
        }
        
        try:
            response = requests.post(
                self.BASE_URL, 
                json=payload, 
                proxies=self.proxy, 
                timeout=15
            )
            response.raise_for_status()
            results = response.json().get("results", [])
        except Exception as e:
            if verbose: print(f"   Tavily Search failed: {e}")
            return None
        
        if verbose:
            print(f"   Tavily Search Results for '{search_query}': {len(results)} items")
            
        return self._parse_tmdb_id_from_results(results, media_type)

    def _parse_tmdb_id_from_results(self, results: List[Dict[str, Any]], media_type: str) -> Optional[int]:
        """Extract TMDB ID from search results URLs."""
        import re
        
        # Regex to match TMDB URLs: https://www.themoviedb.org/tv/1399-game-of-thrones
        # or https://www.themoviedb.org/movie/550-fight-club
        pattern = re.compile(f"themoviedb\\.org/{media_type}/(\\d+)")
        
        for result in results:
            url = result.get("url", "")
            match = pattern.search(url)
            if match:
                return int(match.group(1))
                
        return None
