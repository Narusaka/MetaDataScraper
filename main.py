
"""
Media Metadata Scraper
Entry point for the application.
"""
import sys
import os

# Add project root to sys.path explicitly
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    from dotenv import load_dotenv
    env_path = os.path.join(project_root, ".env")
    load_dotenv(env_path)
except ImportError:
    pass

from src.interface.cli import main

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n❌ Process interrupted.")
        sys.exit(130)
