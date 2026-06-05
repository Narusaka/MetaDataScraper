
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path when this smoke script is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

load_dotenv()

from src.adapters.tavily_search import TavilySearchAdapter

def run_tavily_smoke():
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        print("TAVILY_API_KEY not found")
        return 0
        
    adapter = TavilySearchAdapter([api_key])
    query = "Futari no Yume Mochi (2024)"
    
    print(f"Testing Tavily for: {query}")
    
    # Try as TV
    tv_id = adapter.search_tmdb_id(query, "tv", verbose=True)
    print(f"TV ID result: {tv_id}")
    
    # Try as Movie
    movie_id = adapter.search_tmdb_id(query, "movie", verbose=True)
    print(f"Movie ID result: {movie_id}")
    return 0

if __name__ == "__main__":
    raise SystemExit(run_tavily_smoke())
