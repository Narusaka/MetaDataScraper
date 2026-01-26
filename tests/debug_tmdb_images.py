
import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("TMDB_API_KEY")
BASE_URL = "https://api.themoviedb.org/3"
HTTP_PROXY = os.getenv("HTTP_PROXY")

proxies = {
    "http": HTTP_PROXY,
    "https": HTTP_PROXY
} if HTTP_PROXY else None

def inspect_tv_images(tmdb_id):
    print(f"--- Inspecting TV Show ID: {tmdb_id} ---")
    
    # 1. Check Show Images (Fanart/Poster)
    url = f"{BASE_URL}/tv/{tmdb_id}/images"
    try:
        resp = requests.get(url, params={"api_key": API_KEY}, proxies=proxies, timeout=10)
        data = resp.json()
        print(f"Show Images: {len(data.get('backdrops', []))} backdrops, {len(data.get('posters', []))} posters")
        if data.get('backdrops'):
            print(f"  First Backdrop: {data['backdrops'][0]['file_path']}")
        else:
            print("  ❌ NO BACKDROPS FOUND")
    except Exception as e:
        print(f"  Error fetching show images: {e}")

    # 2. Check Season 1 Episode Images
    url = f"{BASE_URL}/tv/{tmdb_id}/season/1"
    try:
        resp = requests.get(url, params={"api_key": API_KEY}, proxies=proxies, timeout=10)
        data = resp.json()
        episodes = data.get("episodes", [])
        print(f"Season 1 has {len(episodes)} episodes")
        
        missing_stills = 0
        for ep in episodes:
            if not ep.get("still_path"):
                missing_stills += 1
                
        print(f"  Episodes missing still_path: {missing_stills}/{len(episodes)}")
        if episodes and episodes[0].get("still_path"):
             print(f"  Sample Still Path (S01E01): {episodes[0]['still_path']}")
             
    except Exception as e:
        print(f"  Error fetching season 1: {e}")

if __name__ == "__main__":
    # Test Guilty Hole (2025) which we scraped
    inspect_tv_images(288577)
    # Test Made in Abyss
    inspect_tv_images(72636)
