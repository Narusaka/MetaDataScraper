
import uvicorn
import os
import sys

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    print("🚀 Starting Media Metadata Scraper Web Server...")
    print("   URL: http://localhost:8000")
    print("   API Docs: http://localhost:8000/docs")
    
    # Load .env
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
        
    # Run uvicorn
    uvicorn.run("src.server.main:app", host="0.0.0.0", port=8000, reload=True)
