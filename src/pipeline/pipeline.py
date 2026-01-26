
import os
import shutil
from typing import Dict, Any, List, Optional

from ..adapters.tmdb import TMDBAdapter
from ..adapters.OMDB import OMDBAdapter
from ..adapters.google_search import GoogleSearchAdapter
from ..adapters.tavily_search import TavilySearchAdapter

from ..core.normalize import DataNormalizer
from ..core.translator import Translator, TagTranslator
from ..core.llm_mapper import DirectMapper
from ..core.artwork import ArtworkDownloader
from ..core.nfo_renderer import NfoRenderer
from ..core.filesystem import FileSystemManager
from ..core.cache import CacheManager
from ..core.logger import MetadataLogger

class MediaPipeline:
    """Linearly process media metadata without LangGraph overhead."""

    def __init__(self, config: Dict[str, Any], quiet_google: bool = False, skip_images: bool = False, preferred_language: str = "zh-CN", verbose: bool = False, quiet: bool = False, inplace: bool = False, extra_images: bool = False):
        self.config = config
        self.skip_images = skip_images
        self.preferred_language = preferred_language
        self.inplace = inplace
        self.extra_images = extra_images
        self.verbose = verbose
        self.quiet = quiet

        # Initialize logger
        self.logger = MetadataLogger(
            log_dir="./logs",
            log_level="DEBUG" if verbose else "INFO",
            verbose=verbose,
            quiet=quiet
        )

        # Initialize Adapters
        self.tmdb = TMDBAdapter(
            api_key=config["tmdb"]["api_key"],
            proxy=config.get("proxy"),
            preferred_language=preferred_language
        )
        self.omdb = OMDBAdapter(
            api_key=config["omdb"]["api_key"],
            proxy=config.get("proxy")
        )
        
        # Google Search
        google_config = config.get("google", {})
        self.google_search = GoogleSearchAdapter(
            proxy=config.get("proxy"),
            api_key=google_config.get("api_key"),
            search_engine_id=google_config.get("search_engine_id"),
            quiet=quiet_google
        )

        # Tavily Search
        tavily_config = config.get("tavily", {})
        # Combine keys from config and env
        tavily_keys = tavily_config.get("api_keys", [])
        if os.getenv("TAVILY_API_KEY"): tavily_keys.append(os.getenv("TAVILY_API_KEY"))
        if os.getenv("TAVILY_API_KEY_2"): tavily_keys.append(os.getenv("TAVILY_API_KEY_2"))
        
        # Remove duplicates and empties
        tavily_keys = list(set([k for k in tavily_keys if k]))
        
        self.tavily_search = None
        if tavily_keys:
            try:
                self.tavily_search = TavilySearchAdapter(tavily_keys, proxy=config.get("proxy"))
                if self.verbose: print(f"   Tavily Search Initialized with {len(tavily_keys)} keys")
            except Exception as e:
                if self.verbose: print(f"   Failed to init Tavily: {e}")

        # Core Components
        self.translator = Translator(config["model"])
        self.tag_translator = TagTranslator(config["model"], config.get("proxy"))
        self.mapper = DirectMapper()
        self.artwork = ArtworkDownloader(config["tmdb"]["api_key"], config.get("proxy"))

    def _log(self, msg: str, verbose_only: bool = False):
        if self.quiet: return
        if verbose_only and not self.verbose: return
        print(msg)

    def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the pipeline linearly."""
        try:
            self._log(f"▶️ Pipeline Input: Type={input_data.get('media_type')}, Query={input_data.get('query')}", verbose_only=False)
            # 1. Input & Search
            search_result = self._step_search(input_data)
            candidate = search_result.get("selected")
            
            if not candidate:
                self._log("❌ No candidate found.", verbose_only=False)
                return {"status": "failed", "error": "No candidate found"}

            tmdb_id = candidate["id"]
            media_type = candidate.get("media_type")
            self._log(f"✅ Selected Candidate: TMDB ID {tmdb_id} (Type: {media_type})", verbose_only=False) # Changed to False to see in log

            if not media_type:
                 self._log("❌ Error: Candidate has no media_type!", verbose_only=False)
                 return {"status": "failed", "error": "Candidate missing media_type"}

            # 2. Fetch Data
            source_data = self._step_fetch(tmdb_id, media_type)
            
            # 3. Normalize
            normalized = self._step_normalize(source_data, media_type, input_data)
            
            # 4. Translate
            translated_result = self._step_translate(source_data, normalized, media_type, input_data)
            normalized = translated_result["translated"] # Updated normalized data
            translated_episodes = translated_result.get("translated_episodes")
            
            # Update source_data with episodes logic
            if translated_episodes:
                source_data["translated_episodes"] = translated_episodes

            # 5. Enrich (OMDB)
            # (Optional) OMDB Enrichment logic can be added here if needed, skipped for now to keep it lean or add if requested.
            # Assuming simplified flow as per request "linear processing". 
            
            # 6. Artwork & NFO
            nfo_data = self._step_generate_nfo(normalized, media_type, source_data)
            
            # 7. Write Output
            output_result = self._step_write_output(normalized, nfo_data, source_data, input_data)
            
            # 8. Download Images (post-writing, or during)
            if not self.skip_images:
                self._step_download_images(normalized, output_result["media_dir"], input_data)

            return {
                "status": "completed",
                "normalized": normalized,
                "nfo": nfo_data,
                "source_data": source_data,
                "output": output_result
            }

        except Exception as e:
            # Fallback Logic for Manual ID
            if input_data.get("tmdb_id") and input_data.get("fallback_on_fail", False):
                 self._log(f"⚠️ Manual ID {input_data['tmdb_id']} failed: {e}. Retrying with auto-search...", verbose_only=False)
                 # Remove manual ID and force retry
                 retry_input = input_data.copy()
                 del retry_input["tmdb_id"]
                 # Recursive retry (one level)
                 return self.run(retry_input)

            self._log(f"❌ Pipeline Error: {e}", verbose_only=False)
            import traceback
            traceback.print_exc()
            return {"status": "failed", "error": str(e)}

    def _step_search(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Step 1: Search for media.
        
        Strategy:
        1. Direct ID (if provided)
        2. TMDB Native Search (best for exact name matches)
        3. Tavily Search (AI-powered, targeted at site:themoviedb.org to find ID)
        4. Google Search (Fallback, targeted at site:themoviedb.org)
        """
        query = input_data.get("query", "")
        tmdb_id = input_data.get("tmdb_id")
        media_type = input_data.get("media_type", "tv")
        force_type = input_data.get("media_type_forced", False)
        
        # Direct ID
        if tmdb_id:
            return {"selected": {"id": int(tmdb_id), "media_type": media_type}}
            
        # Search TMDB
        self._log(f"🔍 Searching TMDB: '{query}' ({'Forced ' if force_type else ''}{media_type}) ...")
        
        candidate = None
        
        # Strategy: 
        # 1. Search specified type (or auto-detect sequence)
        # 2. If fail, use Tavily
        # 3. If fail, use Google
        
        search_types = [media_type] if force_type else (["tv", "movie"] if media_type == "tv" else ["movie", "tv"])
        
        # 1. TMDB Search
        for m_type in search_types:
            results = self.tmdb.search_tv(query) if m_type == "tv" else self.tmdb.search_movie(query)
            if results and results.get("results"):
                candidate = results["results"][0]
                candidate["media_type"] = m_type
                self._log(f"   ✅ TMDB Found: {candidate.get('name') or candidate.get('title')} ({m_type})")
                break
        
        # 2. Tavily Search (Fallback)
        if not candidate and input_data.get("aid_search") and not input_data.get("tmdb_only") and self.tavily_search:
            self._log(f"🔍 TMDB failed, trying Tavily Search...")
            # For fallback, if type was NOT forced, we might want to try both? 
            # Usually fallback respects the primary type intent.
            fallback_type = media_type
            tavily_id = self.tavily_search.search_tmdb_id(query, fallback_type, verbose=self.verbose)
            if tavily_id:
                candidate = {"id": tavily_id, "media_type": fallback_type}
                self._log(f"   ✅ Tavily Found ID: {tavily_id}")
        
        # 3. Google Search (Fallback)
        if not candidate and input_data.get("aid_search") and not input_data.get("tmdb_only") and self.google_search and not self.tavily_search:
             self._log(f"🔍 Trying Google Search...")
             google_id = self.google_search.search_tmdb_id(query, media_type, verbose=self.verbose)
             if google_id:
                 candidate = {"id": google_id, "media_type": media_type}
                 self._log(f"   ✅ Google Found ID: {google_id}")

        return {"selected": candidate}

    def _step_fetch(self, tmdb_id: int, media_type: str) -> Dict[str, Any]:
        """Step 2: Fetch metadata."""
        self._log("📥 Fetching metadata...", verbose_only=True)
        if media_type == "movie":
            main_data = self.tmdb.get_movie_details(tmdb_id)
        else:
            main_data = self.tmdb.get_tv_details(tmdb_id)
            
        credits_data = self.tmdb.get_credits(media_type, tmdb_id)
        keywords_data = self.tmdb.get_keywords(media_type, tmdb_id)
        
        seasons_data = []
        episodes_data = []
        
        if media_type == "tv":
            seasons = main_data.get("seasons", [])
            for season in seasons:
                s_num = season.get("season_number", 0)
                if s_num > 0:
                    try:
                        s_detail = self.tmdb.get_tv_season_details(tmdb_id, s_num)
                        seasons_data.append(s_detail)
                        episodes_data.extend(s_detail.get("episodes", []))
                    except: pass
        
        return {
            "main": main_data,
            "credits": credits_data,
            "keywords": keywords_data,
            "seasons": seasons_data,
            "episodes": episodes_data
        }

    def _step_normalize(self, source_data: Dict, media_type: str, input_data: Dict) -> Dict:
        """Step 3: Normalize data."""
        main_data = source_data["main"]
        credits_data = source_data["credits"]
        keywords_data = source_data["keywords"]
        
        if media_type == "movie":
            normalized = DataNormalizer.normalize_tmdb_movie(main_data)
        else:
            normalized = DataNormalizer.normalize_tmdb_tv(main_data)
        
        normalized = DataNormalizer.enrich_with_credits(normalized, credits_data)
        normalized = DataNormalizer.enrich_with_keywords(normalized, keywords_data, input_data.get("translate", False))
        
        # Tag Translation
        if input_data.get("translate_tags", True) and normalized.get("keywords"):
            self._log("🏷️ Translating tags...", verbose_only=True)
            normalized["keywords_zh"] = self.tag_translator.translate_tags(normalized["keywords"])
            
        return normalized

    def _step_translate(self, source_data: Dict, normalized: Dict, media_type: str, input_data: Dict) -> Dict:
        """Step 4: LLM Translation."""
        if not input_data.get("translate", False):
            return {"translated": normalized, "translated_episodes": source_data.get("episodes")}
            
        target_lang = input_data.get("language", "zh-CN")
        if not target_lang.startswith("zh"):
             return {"translated": normalized, "translated_episodes": source_data.get("episodes")}

        # Check main fields
        needs_trans = not normalized.get("title_zh") or not normalized.get("plot_zh")
        if needs_trans:
            self._log("🤖 Translating metadata via LLM...", verbose_only=True)
            normalized = self.translator.translate_metadata(normalized)
            
        # Translate episodes (TV only)
        translated_episodes = []
        episodes = source_data.get("episodes", [])
        if media_type == "tv" and episodes:
            # Batch or single? For now, we iterate. 
            # Performance note: For many episodes, this is slow. Ideally batch translate names/plots.
            # Simplified: Only translate if missing name_zh
            self._log(f"🤖 Processing {len(episodes)} episodes (Lazy translation)...", verbose_only=True)
            
            for ep in episodes:
                # We skip full LLM call for every episode to save time/cost unless essential
                # Just copy logic from original graph
                ep_copy = ep.copy()
                # Basic mapping if exists in TMDB (TMDBAdapter might have fetched Chinese if lang=zh)
                # If TMDB returned Chinese, name_zh/overview_zh should be populated or name/overview is already Chinese?
                # The adapters/tmdb.py uses 'language' param. So likely 'name' IS Chinese if available.
                
                # Check if 'name' contains Chinese characters?
                # For simplicity in this pipeline refactor, we assume TMDB data is primary source. 
                # If we really want LLM translation for EVERY episode summary, it needs async batching.
                # Here we stick to basic mapping to populate *_zh keys
                
                ep_copy["name_zh"] = ep.get("name") # Provided by TMDB with &language=zh-CN
                ep_copy["overview_zh"] = ep.get("overview")
                translated_episodes.append(ep_copy)

        return {"translated": normalized, "translated_episodes": translated_episodes}

    def _step_generate_nfo(self, normalized: Dict, media_type: str, source_data: Dict) -> Dict:
        """Step 6: Generate NFO struct."""
        episode_nfos = {}
        
        if media_type == "movie":
            nfo_obj = self.mapper.map_to_movie_nfo(normalized)
            xml = NfoRenderer.render_movie_nfo(nfo_obj, normalized.get("tmdb_id"))
        else:
            nfo_obj = self.mapper.map_to_tvshow_nfo(normalized)
            xml = NfoRenderer.render_tvshow_nfo(nfo_obj, normalized.get("tmdb_id"))
            
            # Generate episode NFOs (in memory)
            episodes = source_data.get("translated_episodes", [])
            for ep in episodes:
                s_num = ep.get("season_number", 0)
                e_num = ep.get("episode_number", 0)
                if s_num > 0:
                    try:
                        ep_nfo = self.mapper.map_to_episode_nfo(normalized, ep, normalized)
                        ep_xml = NfoRenderer.render_episode_nfo(ep_nfo)
                        episode_nfos[(s_num, e_num)] = ep_xml
                    except: pass
            
        return {"data": nfo_obj.model_dump(), "xml": xml, "episode_nfos": episode_nfos}

    def _step_write_output(self, normalized: Dict, nfo_data: Dict, source_data: Dict, input_data: Dict) -> Dict:
        """Step 7: Write NFO and structure."""
        output_dir = input_data.get("output_dir") or "./output"
        media_type = normalized.get("media_type")
        title = normalized.get("title")
        year = normalized.get("year")
        
        # Create Directory
        media_dir = FileSystemManager.create_media_directory(output_dir, title, year, media_type, inplace=self.inplace)
        
        # Write Main NFO
        nfo_filename = f"{title} ({year}).nfo" if media_type == "movie" else "tvshow.nfo"
        FileSystemManager.write_nfo_file(media_dir, nfo_filename, nfo_data["xml"])
        
        # Handle Seasons/Episodes NFO
        if media_type == "tv":
            episodes = source_data.get("translated_episodes", [])
            for ep in episodes:
                s_num = ep.get("season_number", 0)
                e_num = ep.get("episode_number", 0)
                if s_num == 0: continue
                
                s_dir = FileSystemManager.create_season_directory(media_dir, s_num)
                
                # Episode NFO
                ep_nfo_obj = self.mapper.map_to_episode_nfo(normalized, ep, normalized)
                ep_xml = NfoRenderer.render_episode_nfo(ep_nfo_obj)
                
                # Filename logic usually handled by batch_scraper file renaming, 
                # BUT here we just write .nfo sidecars if we knew the filename.
                # In this pipeline we don't know the exact video filename.
                # We usually generate a Standard Name.
                # In 'batch_scraper', we typically already have the file. 
                # This Step mainly generates the 'tvshow.nfo'. Individual episode NFOs 
                # are tricky without the video file map. 
                # *Correction*: The original graph wrote standardized NFOs like `Show - S01E01 - Title.nfo`.
                
                e_title = ep.get("name", "")
                ep_dir, _ = FileSystemManager.create_episode_directory(s_dir, title, s_num, e_num, e_title)
                # We will skip writing specific episode NFOs blindly here to avoid clutter, 
                # or write them using standard naming if requested.
                # For compatibility, let's skip episode NFO writing in Linear Pipeline for now 
                # unless we are sure about the structure, OR write to standard name.
                
                base_name = f"{title} - S{s_num:02d}E{e_num:02d} - {e_title}".replace("/", "-") 
                FileSystemManager.write_nfo_file(s_dir, f"{base_name}.nfo", ep_xml)

        return {"media_dir": media_dir}

    def _step_download_images(self, normalized: Dict, media_dir: str, input_data: Dict):
        """Step 8: Download."""
        tmdb_id = normalized.get("tmdb_id")
        media_type = normalized.get("media_type")
        if tmdb_id:
            self._log("🖼️ Downloading images...", verbose_only=True)
            self.artwork.download_all_images(
                media_type, tmdb_id, media_dir, 
                verbose=self.verbose, 
                extra_images=input_data.get("extra_images", False)
            )
