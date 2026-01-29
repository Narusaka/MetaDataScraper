
import os
import yaml
import logging
from src.pipeline.pipeline import MediaPipeline

# Setup basic logging to see output
logging.basicConfig(level=logging.INFO, format='%(message)s')

def load_config():
    if os.path.exists("config.yaml"):
        with open("config.yaml", "r") as f:
            return yaml.safe_load(f)
    return {}

def test_fallback():
    print("--- STARTING FALLBACK DEBUG TEST ---")
    config = load_config()
    
    # Inject env vars if needed (simulating batch/scraper.py behavior)
    # The user environment seems to have keys set or they are in config.yaml
    
    # Initialize pipeline
    print("Initializing Pipeline...")
    # Mock config basics
    if "tmdb" not in config: config["tmdb"] = {}
    if "api_key" not in config["tmdb"]: config["tmdb"]["api_key"] = "dummy_key"
    if "omdb" not in config: config["omdb"] = {}
    if "api_key" not in config["omdb"]: config["omdb"]["api_key"] = "dummy_key"
    if "model" not in config or isinstance(config["model"], str): 
        config["model"] = {"base_url": "http://dummy", "api_key": "dummy"}
    
    pipeline = MediaPipeline(config, verbose=True)
    
    # Test Input
    input_data = {
        "query": "两人怀揣之梦",
        "media_type": "movie", # Intentionally wrong/default to trigger fallback
        "year": 2024,
        "search_mode": "tavily_only", # Force Tavily to test the loop logic
        # Or use 'smart' if we want to test full flow, but 'tavily_only' isolates the fix block
        "media_type_forced": False 
    }
    
    print(f"\nTesting Input: {input_data}")
    
    # Mock Tavily search to avoid real API calls if keys missing, 
    # OR rely on real keys if available. 
    # Let's inspect if pipeline.tavily_search is initialized.
    if not pipeline.tavily_search:
        print("⚠️ Tavily Search not initialized! Cannot test fallback logic with live API.")
        # We can mock it for logic verification
        class MockTavily:
            def search_tmdb_id(self, query, media_type, verbose=False):
                print(f"   [MOCK TAVILY] Searching for '{query}' as '{media_type}'")
                if media_type == "tv":
                    return 12345 # Simulate found on TV
                return None
        pipeline.tavily_search = MockTavily()
        print("   -> Injected Mock Tavily Adapter")

    # Run Search Step
    print("\n>>> Executing _step_search...")
    result = pipeline._step_search(input_data)
    
    print("\n>>> Result: ", result)
    
    selected = result.get("selected")
    if selected and selected.get("media_type") == "tv":
        print("\n✅ TEST PASSED: Fallback to TV successful!")
    else:
        print("\n❌ TEST FAILED: Did not fallback to TV correctly.")

if __name__ == "__main__":
    test_fallback()
