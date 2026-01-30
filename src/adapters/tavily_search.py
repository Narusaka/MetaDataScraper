
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

    def search_tmdb_id(self, query: str, media_type: str = "tv", year: Optional[int] = None, verbose: bool = False) -> Optional[int]:
        """Search specifically for TMDB ID using Tavily with 2-step strategy."""
        
        # Strategy defined by user:
        # 1. Query: "{Title} tmdb" -> Filter by Year/Type
        # 2. Query: "{Title} ({Year}) tmdb" -> Filter by Year/Type
        
        steps = [
            {"q": f"{query} tmdb", "desc": "Attempt 1 (Basic)"},
        ]
        
        if year:
             steps.append({"q": f"{query} ({year}) tmdb", "desc": "Attempt 2 (Year Explicit)"})
        
        # Shuffle keys (load balance)
        available_keys = list(self.api_keys)
        random.shuffle(available_keys)

        for step in steps:
            search_query = step["q"]
            if verbose: print(f"   Trying Tavily Search [{step['desc']}]: '{search_query}'")
            
            # Simple retry logic across keys
            for key in available_keys:
                try:
                    payload = {
                        "api_key": key,
                        "query": search_query,
                        "search_depth": "basic",
                        "max_results": 10, # Increased to 10 to expand scope (2 steps * 10 = max 20 candidates)
                        "include_domains": ["themoviedb.org"],
                    }
                    
                    response = requests.post(
                        self.BASE_URL, 
                        json=payload, 
                        proxies=self.proxy, 
                        timeout=15
                    )
                    
                    if response.status_code in [429, 432]:
                        continue
                        
                    response.raise_for_status()
                    results = response.json().get("results", [])
                    
                    if verbose: print(f"      Found {len(results)} raw results")
                    
                    # Filter/Parse Results
                    candidate_id = self._parse_and_filter_results(results, media_type, year)
                    if candidate_id:
                        return candidate_id
                    
                    # If this key worked but returned no valid candidates, break key loop 
                    # and proceed to next step (next query strategy)
                    break 

                except Exception as e:
                    if verbose: print(f"      Key failed: {e}")
                    continue
        
        return None

    def _parse_and_filter_results(self, results: List[Dict[str, Any]], media_type: str, target_year: Optional[int]) -> Optional[int]:
        """Extract TMDB ID with filtering."""
        import re
        
        # Regex for ID: https://www.themoviedb.org/movie/550-fight-club -> 550
        url_pattern = re.compile(f"themoviedb\\.org/{media_type}/(\\d+)")
        
        for result in results:
            url = result.get("url", "")
            title = result.get("title", "")
            
            # 1. URL/Type Match
            match = url_pattern.search(url)
            if not match:
                continue
                
            tmdb_id = int(match.group(1))
            
            # 2. Year Match (if target_year exists)
            if target_year:
                # User Requirement: Combine with year filter.
                # If target_year is provided, we REQUIRE it to be in the title to be safe.
                # Exceptions can be handled by the pipeline fallback if this returns None.
                
                # Check for strict year presence
                if str(target_year) not in title:
                    # Debug log
                    print(f"      [Filter] Rejecting {tmdb_id} ('{title}'): Year {target_year} not found in title.")
                    continue
                else:
                    print(f"      [Filter] Accepting {tmdb_id} ('{title}'): Matched year {target_year}.")
            
            return tmdb_id
            
        return None
