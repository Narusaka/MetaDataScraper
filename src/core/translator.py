from typing import Dict, Any, Optional, List
import requests
import json
from .tag_cache import TagCacheManager


class LLMTranslator:
    """LLM-based translator using local model."""

    def __init__(self, model_config: Dict[str, Any], proxy: Optional[Dict[str, str]] = None):
        self.model_config = model_config
        self.proxy = proxy
        self.base_url = model_config.get("base_url", "http://127.0.0.1:32668/v1")
        self.api_key = model_config.get("api_key", "EMPTY")
        self.model = model_config.get("model", "local-4b")
        self.session = requests.Session()
        if proxy:
            self.session.proxies.update(proxy)

    def _call_llm(self, prompt: str) -> str:
        """Call LLM API for translation."""
        try:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "You are a professional translator. Translate the given text to Chinese. Return only the translated text without any explanation."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.1,
                "max_tokens": 1000
            }

            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key != "EMPTY" else {}

            response = self.session.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=60
            )
            response.raise_for_status()

            result = response.json()
            return result["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"Translation failed: {e}")
            return ""

    def translate_text(self, text: str) -> str:
        """Translate a single text to Chinese."""
        if not text or not isinstance(text, str):
            return text

        try:
            translated = self._call_llm(f"Translate to Chinese: {text}")
            return translated if translated else text
        except Exception:
            return text

    def translate_keywords(self, keywords: list) -> list:
        """Translate a list of keywords to Chinese."""
        if not keywords or not isinstance(keywords, list):
            return keywords

        try:
            keywords_text = ", ".join(keywords)
            translated_text = self._call_llm(f"Translate these keywords/tags to Chinese, keep them as comma-separated list: {keywords_text}")
            if translated_text:
                # Split back into list
                translated_keywords = [tag.strip() for tag in translated_text.split(",") if tag.strip()]
                # If translation failed or returned wrong number, keep original
                if len(translated_keywords) == len(keywords):
                    return translated_keywords
            return keywords
        except Exception:
            return keywords

    def translate_metadata(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Translate metadata fields to Chinese."""
        translated_data = data.copy()

        # Translate title
        if 'title' in data and not data.get('title_zh'):
            translated_data['title_zh'] = self.translate_text(data['title'])

        # Translate plot
        if 'plot' in data and not data.get('plot_zh'):
            translated_data['plot_zh'] = self.translate_text(data['plot'])

        # Translate tagline
        if 'tagline' in data and not data.get('tagline_zh'):
            translated_data['tagline_zh'] = self.translate_text(data['tagline'])

        # Translate genres
        if 'genres' in data and not data.get('genres_zh'):
            # Genres are typically list of strings
            if isinstance(data['genres'], list):
                translated_genres = []
                for genre in data['genres']:
                    translated_genres.append(self.translate_text(genre))
                translated_data['genres_zh'] = translated_genres
            else:
                translated_data['genres_zh'] = self.translate_text(str(data['genres']))

        # Translate keywords/tags
        if 'keywords' in data and not data.get('keywords_zh'):
            translated_data['keywords_zh'] = self.translate_keywords(data['keywords'])

        # Ensure cast has name_zh
        if 'cast' in translated_data:
            for actor in translated_data['cast']:
                if 'name_en' in actor and not actor.get('name_zh'):
                    actor['name_zh'] = self.translate_text(actor['name_en'])

        return translated_data


class SimpleTranslator:
    """Simple translator that ensures Chinese fields exist - fallback when LLM unavailable."""

    def __init__(self, model_config: Dict[str, Any], proxy: Optional[Dict[str, str]] = None):
        # Try to use LLM translator first
        try:
            self.translator = LLMTranslator(model_config, proxy)
        except Exception:
            self.translator = None

    def translate_metadata(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure Chinese fields exist, use LLM if available, fallback to English if needed."""
        if self.translator:
            return self.translator.translate_metadata(data)

        # Fallback to simple copy
        translated_data = data.copy()

        # Ensure title_zh exists
        if 'title' in data and not data.get('title_zh'):
            translated_data['title_zh'] = data['title']

        # Ensure plot_zh exists
        if 'plot' in data and not data.get('plot_zh'):
            translated_data['plot_zh'] = data['plot']

        # Ensure tagline_zh exists
        if 'tagline' in data and not data.get('tagline_zh'):
            translated_data['tagline_zh'] = data['tagline']

        # Ensure genres_zh exists
        if 'genres' in data and not data.get('genres_zh'):
            translated_data['genres_zh'] = data['genres']

        # Ensure keywords_zh exists
        if 'keywords' in data and not data.get('keywords_zh'):
            translated_data['keywords_zh'] = data['keywords']

        # Ensure cast has name_zh
        if 'cast' in translated_data:
            for actor in translated_data['cast']:
                if 'name_en' in actor and not actor.get('name_zh'):
                    actor['name_zh'] = actor['name_en']

        return translated_data


class TagTranslator:
    """Specialized translator for tags/keywords with caching support."""

    SYSTEM_PROMPT = """You are a professional translator specializing in media tags and keywords.
Your task is to translate English tags/keywords to Chinese. You must return the same number of translations as input tags.
Each translation should be accurate, natural, and commonly used in Chinese media contexts.

Rules:
- Return only the translated tags, one per line
- Do not add any explanations, comments, or extra text
- Maintain the exact same number of output lines as input
- Use simplified Chinese characters
- Keep technical terms appropriately translated"""

    def __init__(self, model_config: Dict[str, Any], proxy: Optional[Dict[str, str]] = None):
        self.model_config = model_config
        self.proxy = proxy
        self.base_url = model_config.get("base_url", "http://127.0.0.1:32668/v1")
        self.api_key = model_config.get("api_key", "EMPTY")
        self.model = model_config.get("model", "local-4b")
        self.session = requests.Session()
        if proxy:
            self.session.proxies.update(proxy)
        self.cache = TagCacheManager()

    def translate_tags(self, tags: List[str], enable_cache: bool = True) -> List[str]:
        """
        Translate a list of tags to Chinese with caching support.

        Args:
            tags: List of tags to translate
            enable_cache: Whether to use cache (default: True)

        Returns:
            List of translated tags (same length as input)
        """
        if not tags:
            return []

        # Remove duplicates while preserving order
        unique_tags = []
        seen = set()
        for tag in tags:
            if tag and tag not in seen:
                unique_tags.append(tag)
                seen.add(tag)

        if enable_cache:
            # Get cached translations
            cached_translations = self.cache.get_translations(unique_tags)

            # Get uncached tags
            uncached_tags = [tag for tag in unique_tags if tag not in cached_translations]
        else:
            cached_translations = {}
            uncached_tags = unique_tags

        # Translate uncached tags
        new_translations = {}
        if uncached_tags:
            try:
                translated_list = self._translate_tags_batch(uncached_tags)
                if len(translated_list) == len(uncached_tags):
                    for original, translated in zip(uncached_tags, translated_list):
                        new_translations[original] = translated
                else:
                    # If translation failed, use original tags
                    for tag in uncached_tags:
                        new_translations[tag] = tag
            except Exception as e:
                print(f"Tag translation failed: {e}")
                # Use original tags as fallback
                for tag in uncached_tags:
                    new_translations[tag] = tag

            # Cache new translations
            if enable_cache and new_translations:
                self.cache.set_translations(new_translations)

        # Combine cached and new translations
        result = []
        for tag in unique_tags:
            if tag in cached_translations:
                result.append(cached_translations[tag])
            elif tag in new_translations:
                result.append(new_translations[tag])
            else:
                result.append(tag)  # Fallback

        return result

    def _translate_tags_batch(self, tags: List[str]) -> List[str]:
        """Translate a batch of tags using LLM."""
        if not tags:
            return []

        # Prepare input
        tags_text = "\n".join(tags)

        user_prompt = f"""Translate these tags to Chinese:

{tags_text}

Return one translated tag per line:"""

        try:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.1,
                "max_tokens": len(tags) * 50  # Estimate tokens needed
            }

            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key != "EMPTY" else {}

            response = self.session.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=120  # Longer timeout for batch translation
            )
            response.raise_for_status()

            result = response.json()
            translated_text = result["choices"][0]["message"]["content"].strip()

            # Parse the response - split by lines
            translated_lines = [line.strip() for line in translated_text.split('\n') if line.strip()]

            # Ensure we have the same number of translations
            if len(translated_lines) == len(tags):
                return translated_lines
            else:
                # If parsing failed, return original tags
                print(f"Translation parsing failed: expected {len(tags)} translations, got {len(translated_lines)}")
                return tags

        except Exception as e:
            print(f"Batch tag translation failed: {e}")
            return tags


# Backward compatibility alias
Translator = SimpleTranslator
