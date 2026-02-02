
import uvicorn
import os
import sys

# Ensure project root is in path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)
# CRITICAL: Set PYTHONPATH so uvicorn subprocess (reloader) also sees local src
os.environ["PYTHONPATH"] = project_root + os.pathsep + os.environ.get("PYTHONPATH", "")

if __name__ == "__main__":
    import src
    print(f"DEBUG: src package path: {src.__path__}")
    print("🚀 Starting Media Metadata Scraper Web Server...")
    print("   Local:    http://localhost:8000")
    print("   Network:  http://0.0.0.0:8000 (Check your IP)")
    print("   API Docs: http://localhost:8000/docs")
    
    # Load .env
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
        
    # Run uvicorn
    uvicorn.run("src.server.main:app", host="0.0.0.0", port=8000, reload=True)
