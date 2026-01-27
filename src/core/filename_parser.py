
import re
from typing import Optional, Tuple, Set

class FilenameParser:
    """Helper class for parsing information from filenames."""
    
    VIDEO_EXTENSIONS = {
        # Common formats
        '.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm',
        # Additional formats
        '.rmvb', '.rm', '.asf', '.mpg', '.mpeg', '.m4v', '.3gp',
        '.m2ts', '.mts', '.vob', '.ogv', '.divx', '.xvid', '.f4v',
        '.mxf', '.r3d', '.braw', '.dng', '.m2v', '.ts'
    }
    
    SUBTITLE_EXTENSIONS = {'.ass', '.srt', '.ssa', '.sub', '.vtt'}

    @staticmethod
    def detect_subtitle_language(filename: str) -> str:
        """Detect subtitle language based on filename keywords."""
        filename_lower = filename.lower()
        
        # Chinese indicators
        chinese_indicators = [
            '简中', '简体中文', '简体', '繁中', '繁体中文', '繁体', 
            'zh', 'chn', 'chinese', '中文', '中字', 'simplified', 
            'traditional', 'sc', 'tc', 'zn'
        ]
        
        # English indicators  
        english_indicators = [
            'en', 'eng', 'english', '英文', '英语', '英字',
            'us', 'uk', 'american', 'british'
        ]
        
        # Japanese indicators
        japanese_indicators = [
            'jp', 'jpn', 'japanese', 'ja', '日文', '日语', '日字',
            'nihongo', 'にほんご', 'ひらがな', 'カタカナ'
        ]
        
        if any(indicator in filename_lower for indicator in chinese_indicators):
            return 'zh'
        elif any(indicator in filename_lower for indicator in english_indicators):
            return 'en'
        elif any(indicator in filename_lower for indicator in japanese_indicators):
            return 'ja'
        
        return ''

    @staticmethod
    def get_subtitle_language_suffix(filename: str) -> str:
        """Get appropriate language suffix for subtitle file."""
        language = FilenameParser.detect_subtitle_language(filename)
        if language:
            return f'.{language}'
        return ''

    @staticmethod
    def parse_episode_info(filename: str) -> Optional[Tuple[int, int]]:
        """Parse season and episode numbers from filename."""
        # Common patterns for episode information
        patterns = [
            # S01E01 format
            r'S(\d{1,2})E(\d{1,2})',
            # 01x01 format
            r'(\d{1,2})x(\d{1,2})',
            # Season 01 Episode 01
            r'Season\s*(\d{1,2}).*Episode\s*(\d{1,2})',
            # Episode 01 (season from context - handled by caller usually, but logic here assumes S1)
            r'Episode\s*(\d{1,2})',
        ]

        for pattern in patterns:
            match = re.search(pattern, filename, re.IGNORECASE)
            if match:
                if len(match.groups()) == 2:
                    return (int(match.group(1)), int(match.group(2)))
                elif len(match.groups()) == 1 and 'Episode' in pattern:
                    return (1, int(match.group(1)))

        # Try to find numbers that might be episode numbers (e.g. .S01E01. or -01-)
        alt_patterns = [
            r'\.S(\d{1,2})E(\d{1,2})\.',
            r'-S(\d{1,2})E(\d{1,2})-',
            r'\.(\d{1,2})x(\d{1,2})\.',
            r'-(\d{1,2})x(\d{1,2})-',
        ]

        for pattern in alt_patterns:
            match = re.search(pattern, filename, re.IGNORECASE)
            if match:
                return (int(match.group(1)), int(match.group(2)))

        # Anime specific patterns (usually just episode number, assume Season 1)
        anime_patterns = [
            r'\[(\d{1,3})\]',           # [01]
            r'\s-\s(\d{1,3})\s',        # - 01 
            r'\s(\d{1,3})(?:v\d)?\.(?:mkv|mp4|avi)', # 01.mkv (at end)
        ]
        
        for pattern in anime_patterns:
            match = re.search(pattern, filename)
            if match:
                try:
                    ep_num = int(match.group(1))
                    # Avoid year numbers (e.g. 1999, 2020) being matched as episodes
                    if ep_num < 1900:
                         return (1, ep_num)
                except: pass

        return None

    @staticmethod
    def extract_show_name(filename: str) -> str:
        """Extract potential show name from filename."""
        # Anime Pattern: [Group] Show Name [Ep]
        if filename.startswith('['):
            # Find the first bracket block that is NOT digits (Group) and NOT resolution
            # A heuristic: typically [Group][NAME][Ep] or [Group] NAME - Ep
            
            # Simple approach: Remove all [...] blocks and return what's left
            # But "Made in Abyss" is inside [].
            # [Nekomoe kissaten][Made in Abyss][01]
            
            matches = re.findall(r'\[(.*?)\]', filename)
            if len(matches) >= 2:
                # Potential show name in second bracket?
                candidate = matches[1]
                # Filter out pure numbers or resolution
                if not candidate.isdigit() and not re.match(r'^\d+p$', candidate):
                    return candidate
            
            # Fallback for [Group] Show Name - 01
            no_brackets = re.sub(r'\[.*?\]', '', filename).strip()
            if no_brackets:
                # Try to cut at " - " or digits
                match = re.search(r'\s-\s\d+', no_brackets)
                if match:
                     return no_brackets[:match.start()].strip()
                return no_brackets.split()[0] # Very rough fallback

        # Try to find episode info and extract name before it (Standard TV)
        match = re.search(r'S\d{1,2}E\d{1,2}', filename, re.IGNORECASE)
        if match:
            name = filename[:match.start()].strip()
            name = re.sub(r'\s*\(\d{4}\)\s*', '', name)
            name = re.sub(r'[._\s]+$', '', name).strip()
            if len(name) > 1:
                return name
        
        # Fallback: extract from the beginning
        # Split by dots or spaces
        clean_name = re.sub(r'\[.*?\]', '', filename) # Remove brackets first
        parts = re.split(r'[._\s]', clean_name)
        
        valid_parts = []
        for part in parts:
            if part and len(part) > 1 and not part.isdigit() and part.lower() not in ['the', 'and', 'but', 'for', 'nor', 'yet', 'so', 'mkv', 'mp4']:
                valid_parts.append(part)
                if len(valid_parts) >= 2: 
                    break
        
        if valid_parts:
            return " ".join(valid_parts)
            
        return filename.split()[0] if filename.split() else filename

    @staticmethod
    def extract_year(filename: str) -> Optional[int]:
        """Extract year from filename (1800-2099)."""
        match = re.search(r'\((\d{4})\)', filename)
        if match:
            year = int(match.group(1))
            if 1800 <= year <= 2099:
                return year
        
        # Try fallback without checking brackets if tight constraints needed anywhere
        # But usually (YEAR) is the standard we look for validation.
        return None

    @staticmethod
    def clean_show_name_for_search(show_name: str) -> str:
        """Clean show name for search queries."""
        # Remove year in parentheses
        show_name = re.sub(r'\s*\(\d{4}\)\s*', '', show_name)

        # Remove other common patterns
        patterns = [
            r'\[.*?\]',           # [1080p], [ASS], etc.
            r'\b\d{4}\b',         # standalone years
            r'\d{3,4}p',          # 1080p, 720p
            r'BD|BDRip|WEB-DL|WEBRip|HDTV|BluRay',
            r'x264|x265|h264|h265',
            r'AAC|AVC|AC3|DTS',
        ]

        clean_name = show_name
        for pattern in patterns:
            clean_name = re.sub(pattern, '', clean_name, flags=re.IGNORECASE)

        # Clean up extra spaces and punctuation
        clean_name = re.sub(r'[._-]+', ' ', clean_name).strip()

        return clean_name
