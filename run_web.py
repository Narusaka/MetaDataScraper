
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
    host = os.getenv("WEB_HOST", "127.0.0.1")
    port = int(os.getenv("WEB_PORT", "8000"))
    reload_enabled = os.getenv("WEB_RELOAD", "0").lower() in {"1", "true", "yes", "on"}

    print(f"DEBUG: src package path: {src.__path__}")
    print("🚀 Starting Media Metadata Scraper Web Server...")
    print(f"   Local:    http://{host}:{port}")
    print(f"   API Docs: http://{host}:{port}/docs")
    if host in {"0.0.0.0", "::"}:
        print(f"   Network:  http://{host}:{port} (Check your IP)")
    
    # Load .env
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
        
    # Run uvicorn
    uvicorn.run("src.server.main:app", host=host, port=port, reload=reload_enabled)
