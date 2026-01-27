
import os
import sys
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

load_dotenv()

from src.adapters.tavily_search import TavilySearchAdapter

def test_tavily():
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        print("TAVILY_API_KEY not found")
        return
        
    adapter = TavilySearchAdapter([api_key])
    query = "Futari no Yume Mochi (2024)"
    
    print(f"Testing Tavily for: {query}")
    
    # Try as TV
    tv_id = adapter.search_tmdb_id(query, "tv", verbose=True)
    print(f"TV ID result: {tv_id}")
    
    # Try as Movie
    movie_id = adapter.search_tmdb_id(query, "movie", verbose=True)
    print(f"Movie ID result: {movie_id}")

if __name__ == "__main__":
    test_tavily()
