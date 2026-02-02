
import re
from collections import defaultdict
from pathlib import Path

LOG_FILE = "logs/web_session_20260202_165218.log"
REGEX = r"Renamed: (.+) -> (.+)"

def main():
    # Destination -> List of Sources that were renamed to this Destination
    overwrite_map = defaultdict(list)
    
    with open(LOG_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            if "Renamed:" in line and "Dir" not in line and "Renamed Directory" not in line:
                match = re.search(REGEX, line)
                if match:
                    src = match.group(1).strip()
                    dst = match.group(2).strip()
                    overwrite_map[dst].append(src)

    affected_shows_count = defaultdict(int) # ShowName -> Count

    for dst, sources in overwrite_map.items():
        if len(sources) > 1:
            # All but the last one were overwritten
            overwritten = sources[:-1]
            
            for f in overwritten:
                # Extract show name
                # Format usually: Show Name - S01E01 - Title.ext
                parts = f.split(' - S')
                if len(parts) > 1:
                    show_name = parts[0]
                else:
                    show_name = "Unknown"
                
                affected_shows_count[show_name] += 1

    # Output Report A-z
    sorted_shows = sorted(affected_shows_count.keys())
    
    print("### 丢失剧集统计 (按 A-z 排序)")
    for show in sorted_shows:
        count = affected_shows_count[show]
        print(f"{show} - {count}")

if __name__ == "__main__":
    main()
