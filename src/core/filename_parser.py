import re
import unicodedata
from pathlib import Path
from typing import Dict, Optional, Set, Tuple


class FilenameParser:
    """Parse media filenames conservatively while keeping legacy helpers stable."""

    VIDEO_EXTENSIONS = {
        ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm",
        ".rmvb", ".rm", ".asf", ".mpg", ".mpeg", ".m4v", ".3gp",
        ".m2ts", ".mts", ".vob", ".ogv", ".divx", ".xvid", ".f4v",
        ".mxf", ".r3d", ".braw", ".dng", ".m2v", ".ts",
    }
    SUBTITLE_EXTENSIONS = {".ass", ".srt", ".ssa", ".sub", ".vtt"}

    TECHNICAL_TOKENS = {
        "2160p", "1080p", "1080i", "720p", "576p", "480p", "4k", "uhd",
        "bluray", "blu-ray", "bdrip", "bdremux", "remux", "web", "web-dl",
        "webrip", "hdtv", "dvdrip", "hevc", "avc", "x264", "x265", "h264",
        "h265", "10bit", "8bit", "hdr", "hdr10", "dv", "dolbyvision",
        "aac", "flac", "opus", "dts", "dts-hd", "truehd", "atmos", "ac3",
        "ddp", "proper", "repack", "uncensored", "multi", "dual", "complete",
    }

    @staticmethod
    def _tokens(value: str) -> Set[str]:
        normalized = unicodedata.normalize("NFKC", value).lower()
        return {
            token
            for token in re.split(r"[^0-9a-z\u3040-\u30ff\u3400-\u9fff]+", normalized)
            if token
        }

    @staticmethod
    def detect_subtitle_language(filename: str) -> str:
        """Detect language from explicit filename tokens, not arbitrary substrings."""
        normalized = unicodedata.normalize("NFKC", filename).lower()
        tokens = FilenameParser._tokens(Path(normalized).stem)
        chinese_markers = {"zh", "zho", "chi", "chn", "chinese", "sc", "tc", "chs", "cht"}
        english_markers = {"en", "eng", "english"}
        japanese_markers = {"ja", "jpn", "jp", "japanese", "nihongo"}

        if any(marker in normalized for marker in ("简中", "简体中文", "简体", "繁中", "繁体中文", "繁体", "中文", "中字")) or tokens & chinese_markers:
            return "zh"
        if any(marker in normalized for marker in ("英文", "英语", "英字")) or tokens & english_markers:
            return "en"
        if any(marker in normalized for marker in ("日文", "日语", "日字", "にほんご", "ひらがな", "カタカナ")) or tokens & japanese_markers:
            return "ja"
        return ""

    @staticmethod
    def get_subtitle_language_suffix(filename: str) -> str:
        language = FilenameParser.detect_subtitle_language(filename)
        return f".{language}" if language else ""

    @staticmethod
    def _clean_title(value: str) -> str:
        value = re.sub(r"^[\s._-]+|[\s._-]+$", "", value)
        value = re.sub(r"\s*\(\d{4}\)\s*$", "", value)
        value = re.sub(r"[._]+", " ", value)
        value = re.sub(r"\s+", " ", value).strip(" -_.")
        return value

    @staticmethod
    def _is_usable_title(value: str) -> bool:
        if not value or not re.search(r"[A-Za-z\u3040-\u30ff\u3400-\u9fff]", value):
            return False
        tokens = FilenameParser._tokens(value)
        meaningful = {token for token in tokens if token not in FilenameParser.TECHNICAL_TOKENS}
        return bool(meaningful)

    @staticmethod
    def parse_media_filename(filename: str) -> Dict[str, object]:
        """Return a structured, auditable parse result for grouping and detection."""
        path = Path(filename)
        stem = path.stem
        result: Dict[str, object] = {
            "filename": path.name,
            "title": None,
            "year": FilenameParser.extract_year(stem),
            "season": None,
            "episode": None,
            "episode_end": None,
            "release_group": None,
            "media_type_guess": None,
            "confidence": "none",
            "reasons": [],
        }
        reasons = result["reasons"]

        leading_group = re.match(r"^\[([^\]]+)\]\s*", stem)
        if leading_group:
            group = leading_group.group(1).strip()
            if not group.isdigit() and not FilenameParser._is_technical_block(group):
                result["release_group"] = group

        patterns = [
            (r"(?i)\bS(\d{1,2})[ ._-]*E(\d{1,3})(?:[ ._-]*(?:E|-)[ ._-]*(\d{1,3}))?", "season_episode"),
            (r"(?i)\b(\d{1,2})x(\d{1,3})(?:[ ._-]*(?:x|-)[ ._-]*(\d{1,3}))?", "season_episode"),
            (r"(?i)\bSeason[ ._-]*(\d{1,2}).*?\bEpisode[ ._-]*(\d{1,3})", "season_episode"),
        ]
        episode_match = None
        for pattern, reason in patterns:
            episode_match = re.search(pattern, stem)
            if episode_match:
                result["season"] = int(episode_match.group(1))
                result["episode"] = int(episode_match.group(2))
                if episode_match.lastindex and episode_match.lastindex >= 3 and episode_match.group(3):
                    result["episode_end"] = int(episode_match.group(3))
                reasons.append(reason)
                break

        title = ""
        if episode_match:
            title = stem[:episode_match.start()]
        else:
            bracket_parts = re.findall(r"\[([^\]]+)\]", stem)
            if len(bracket_parts) >= 3:
                episode_block = next((part for part in bracket_parts[2:] if re.fullmatch(r"\d{1,3}(?:v\d+)?", part, re.IGNORECASE)), None)
                candidate = bracket_parts[1].strip()
                if episode_block and FilenameParser._is_usable_title(candidate):
                    title = candidate
                    result["season"] = 1
                    result["episode"] = int(re.match(r"\d+", episode_block).group())
                    reasons.append("anime_bracket_episode")

        if not result["episode"]:
            anime_patterns = [
                r"\s+-\s+(\d{1,3})(?:v\d+)?(?:\s|$)",
                r"[#＃]\s*(\d{1,3})",
                r"第\s*(\d{1,3})\s*[集话話]",
                r"(?i)\b(?:EP?|Episode)[ ._-]*(\d{1,3})\b",
            ]
            for pattern in anime_patterns:
                match = re.search(pattern, stem)
                if not match:
                    continue
                prefix = stem[:match.start()]
                prefix = re.sub(r"^\[[^\]]+\]\s*", "", prefix)
                if FilenameParser._is_usable_title(FilenameParser._clean_title(prefix)):
                    result["season"] = 1
                    result["episode"] = int(match.group(1))
                    title = prefix
                    reasons.append("episode_only_marker")
                    break

        if not title:
            title = stem
            title = re.sub(r"^\[[^\]]+\]\s*", "", title)
            title = re.sub(r"\[[^\]]+\]", " ", title)
            if result["year"]:
                title = re.sub(rf"[\s._-]*[\(\[]?{result['year']}[\)\]]?", " ", title, count=1)

        title = FilenameParser._strip_technical_suffix(title)
        title = FilenameParser._clean_title(title)
        if FilenameParser._is_usable_title(title):
            result["title"] = title

        if result["episode"] and result["title"]:
            result["media_type_guess"] = "tv"
            result["confidence"] = "high" if "season_episode" in reasons or "anime_bracket_episode" in reasons else "medium"
        elif result["title"] and result["year"]:
            result["media_type_guess"] = "movie"
            result["confidence"] = "high"
            reasons.append("title_and_year")
        elif result["title"]:
            result["media_type_guess"] = "movie"
            result["confidence"] = "medium"
            reasons.append("title_only")
        else:
            reasons.append("no_stable_title")
        return result

    @staticmethod
    def _is_technical_block(value: str) -> bool:
        tokens = FilenameParser._tokens(value)
        return bool(tokens) and tokens.issubset(FilenameParser.TECHNICAL_TOKENS)

    @staticmethod
    def _strip_technical_suffix(value: str) -> str:
        chunks = re.split(r"([ ._-]+)", value)
        while chunks:
            token = chunks[-1].strip(" ._-[]()").lower()
            if not token:
                chunks.pop()
                continue
            if token in FilenameParser.TECHNICAL_TOKENS or re.fullmatch(r"\d{3,4}p", token):
                chunks.pop()
                if chunks and re.fullmatch(r"[ ._-]+", chunks[-1]):
                    chunks.pop()
                continue
            break
        return "".join(chunks)

    @staticmethod
    def parse_episode_info(filename: str) -> Optional[Tuple[int, int]]:
        parsed = FilenameParser.parse_media_filename(filename)
        if parsed["season"] is not None and parsed["episode"] is not None:
            return int(parsed["season"]), int(parsed["episode"])
        return None

    @staticmethod
    def extract_show_name(filename: str) -> str:
        parsed = FilenameParser.parse_media_filename(filename)
        return str(parsed["title"] or "")

    @staticmethod
    def extract_year(filename: str) -> Optional[int]:
        match = re.search(r"(?<!\d)[\(\[]?((?:18|19|20)\d{2})[\)\]]?(?!\d)", filename)
        return int(match.group(1)) if match else None

    @staticmethod
    def clean_show_name_for_search(show_name: str) -> str:
        show_name = unicodedata.normalize("NFKC", show_name)
        show_name = re.sub(r"\s*[\(\[]?(?:18|19|20)\d{2}[\)\]]?\s*", " ", show_name)
        show_name = re.sub(r"\[[^\]]+\]", " ", show_name)
        tokens = re.split(r"([ ._-]+)", show_name)
        cleaned = [
            "" if token.strip(" ._-").lower() in FilenameParser.TECHNICAL_TOKENS else token
            for token in tokens
        ]
        return FilenameParser._clean_title("".join(cleaned))
