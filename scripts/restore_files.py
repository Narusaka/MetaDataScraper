
import os
import re
import shutil
from pathlib import Path

# Config
LOG_FILE = "logs/web_session_20260202_165218.log"
BASE_DIR = Path("/Volumes/WorkStation/奴隶区 The Animation (2018)")

# Regex
REGEX = r"Renamed: (.+) -> (.+)"

def main():
    if not BASE_DIR.exists():
        print(f"Base Directory not found: {BASE_DIR}")
        return

    moves = {} # dst -> src
    
    print(f"Reading log: {LOG_FILE}")
    with open(LOG_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            if "Renamed Directory" in line:
                continue
            if "Renamed:" in line:
                match = re.search(REGEX, line)
                if match:
                    src = match.group(1).strip()
                    dst = match.group(2).strip()
                    moves[dst] = src

    print(f"Found {len(moves)} rename records.")
    
    success_count = 0
    fail_count = 0
    
    for dst_name, src_name in moves.items():
        # Current Path Check
        # Try Season 01
        current_path = BASE_DIR / "Season 01" / dst_name
        
        if not current_path.exists():
            # Try Root
            current_path = BASE_DIR / dst_name
            if not current_path.exists():
                print(f"❌ Missing file: {dst_name}")
                fail_count += 1
                continue
        
        # Determine Target
        # Extract Show Name
        parts = src_name.split(' - ')
        if len(parts) < 2:
            print(f"⚠️ Cannot parse show name: {src_name}")
            continue # Try fallback?
        
        show_name = parts[0]
        
        # Find matching folder in BASE_DIR
        target_show_dir = None
        # Try exact match first
        candidates = []
        for item in BASE_DIR.iterdir():
            if item.is_dir():
                if item.name == show_name:
                    target_show_dir = item
                    break
                if item.name.startswith(show_name):
                    candidates.append(item)
        
        if not target_show_dir and candidates:
            # Pick best match (shortest is usually the root name without year suffix if multiple?)
            # Usually folders have Year suffix now: "Show Name (Year)"
            # Sort by name length
            candidates.sort(key=lambda x: len(x.name))
            target_show_dir = candidates[0]
            
        if not target_show_dir:
            print(f"⚠️ Show folder not found for: {show_name} (Src: {src_name})")
            # Create it? Default to straight name
            # target_show_dir = BASE_DIR / show_name
            # target_show_dir.mkdir(exist_ok=True)
            # print(f"Created folder: {target_show_dir}")
            fail_count += 1
            continue
            
        # Extract Season
        season_match = re.search(r'S(\d+)E', src_name)
        if season_match:
             s_num = int(season_match.group(1))
             season_folder_name = f"Season {s_num:02d}"
        else:
             season_folder_name = "Season 01" # Default
             
        target_dir = target_show_dir / season_folder_name
        target_dir.mkdir(exist_ok=True)
        
        target_path = target_dir / src_name
        
        if target_path.exists():
            print(f"⏩ Target exists: {target_path.name}")
            continue

        try:
            shutil.move(str(current_path), str(target_path))
            print(f"✅ Restored: {show_name}/{season_folder_name}/{src_name}")
            success_count += 1
        except Exception as e:
            print(f"Error moving: {e}")
            fail_count += 1

    print(f"Done. Success: {success_count}, Failed: {fail_count}")

if __name__ == "__main__":
    main()
