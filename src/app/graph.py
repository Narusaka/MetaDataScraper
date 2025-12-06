import os
import shutil
import signal
from typing import Dict, Any, List
from langgraph.graph import StateGraph, END
from .state import GraphState
from ..adapters.tmdb import TMDBAdapter
from ..adapters.OMDB import OMDBAdapter
from ..adapters.google_search import GoogleSearchAdapter
from ..core.normalize import DataNormalizer
from ..core.translator import Translator, TagTranslator
from ..core.llm_mapper import LLMMapper
from ..core.artwork import ArtworkDownloader
from ..core.nfo_renderer import NfoRenderer
from ..core.filesystem import FileSystemManager
from ..core.cache import CacheManager
from ..core.logger import MetadataLogger


class MediaMetadataGraph:
    def __init__(self, config: Dict[str, Any], quiet_google: bool = False, skip_images: bool = False, preferred_language: str = "zh-CN", verbose: bool = False, quiet: bool = False, inplace: bool = False, extra_images: bool = False):
        self.config = config
        self.skip_images = skip_images
        self.preferred_language = preferred_language
        self.inplace = inplace  # New parameter for in-place mode
        self.extra_images = extra_images  # Whether to create Extra folder for additional images

        # Initialize logger
        self.logger = MetadataLogger(
            log_dir="./logs",
            log_level="DEBUG",
            verbose=verbose,
            quiet=quiet
        )

        self.tmdb = TMDBAdapter(
            api_key=config["tmdb"]["api_key"],
            proxy=config.get("proxy"),
            preferred_language=preferred_language
        )
        self.omdb = OMDBAdapter(
            api_key=config["omdb"]["api_key"],
            proxy=config.get("proxy")
        )
        google_config = config.get("google", {})
        self.google_search = GoogleSearchAdapter(
            proxy=config.get("proxy"),
            api_key=google_config.get("api_key"),
            search_engine_id=google_config.get("search_engine_id"),
            quiet=quiet_google
        )
        self.translator = Translator(config["model"])
        self.tag_translator = TagTranslator(config["model"], config.get("proxy"))
        self.mapper = LLMMapper()  # DirectMapper doesn't need config
        self.artwork = ArtworkDownloader(config["tmdb"]["api_key"], config.get("proxy"))
        self.cache = CacheManager()

    def _copy_image_if_missing(self, source_path: str, dest_path: str, image_type: str, source_desc: str, input_data: Dict[str, Any]) -> bool:
        """Copy image if source exists and destination doesn't."""
        if os.path.exists(source_path) and not os.path.exists(dest_path):
            try:
                shutil.copy2(source_path, dest_path)
                if self._should_print(input_data):
                    print(f"      🔄 {image_type} <- 从{source_desc}复制")
                return True
            except Exception as e:
                if self._should_print(input_data):
                    print(f"      ⚠️ {image_type}复制失败: {e}")
        elif os.path.exists(dest_path):
            if self._should_print(input_data):
                print(f"      ⏭️ {image_type}已存在，跳过")
        return False

    def _should_print(self, input_data: Dict[str, Any], level: str = "normal") -> bool:
        """Determine if message should be printed based on verbosity settings."""
        verbose = input_data.get("verbose", False)
        quiet = input_data.get("quiet", False)

        if quiet:
            return False  # Quiet mode: no output except errors
        elif level == "verbose":
            return verbose  # Only show verbose messages in verbose mode
        else:
            return True  # Normal messages always show unless quiet

    def create_graph(self) -> StateGraph:
        """Create the LangGraph workflow."""
        workflow = StateGraph(GraphState)

        # Add nodes
        workflow.add_node("parse_input", self.parse_input_node)
        workflow.add_node("search", self.search_node)
        workflow.add_node("select_candidate", self.select_candidate_node)
        workflow.add_node("fetch", self.fetch_node)
        workflow.add_node("translate", self.translate_node)
        workflow.add_node("omdb_enrich", self.omdb_enrich_node)
        workflow.add_node("normalize", self.normalize_node)

        # Conditionally add image-related nodes
        if not self.skip_images:
            workflow.add_node("plan_artwork", self.plan_artwork_node)
            workflow.add_node("download_images", self.download_all_images_node)

        workflow.add_node("map_to_nfo", self.llm_map_to_nfo_node)
        workflow.add_node("validate_nfo", self.validate_nfo_node)
        workflow.add_node("render_xml", self.render_xml_node)
        workflow.add_node("write_output", self.write_output_node)
        workflow.add_node("report", self.report_node)

        # Define edges
        workflow.set_entry_point("parse_input")
        workflow.add_edge("parse_input", "search")
        workflow.add_edge("search", "select_candidate")
        workflow.add_edge("select_candidate", "fetch")
        workflow.add_edge("fetch", "normalize")
        workflow.add_edge("normalize", "translate")
        workflow.add_edge("translate", "omdb_enrich")

        if self.skip_images:
            # Skip image processing
            workflow.add_edge("normalize", "map_to_nfo")
        else:
            # Include image processing
            workflow.add_edge("normalize", "plan_artwork")
            workflow.add_edge("plan_artwork", "download_images")
            workflow.add_edge("download_images", "map_to_nfo")

        workflow.add_edge("map_to_nfo", "validate_nfo")
        workflow.add_edge("validate_nfo", "render_xml")
        workflow.add_edge("render_xml", "write_output")
        workflow.add_edge("write_output", "report")
        workflow.add_edge("report", END)

        return workflow

    def parse_input_node(self, state: GraphState) -> Dict[str, Any]:
        """Parse input parameters."""
        input_data = state.input

        # Log input parameters
        self.logger.log_input(input_data)

        # If TMDB ID is provided directly, suppress Google search configuration messages
        has_direct_id = bool(input_data.get('tmdb_id') or input_data.get('omdb_id'))
        if has_direct_id:
            # Reinitialize GoogleSearchAdapter with quiet mode
            google_config = self.config.get("google", {})
            self.google_search = GoogleSearchAdapter(
                proxy=self.config.get("proxy"),
                api_key=google_config.get("api_key"),
                search_engine_id=google_config.get("search_engine_id"),
                quiet=True  # Suppress configuration messages when ID is provided
            )

        return {"input": input_data}

    def search_node(self, state: GraphState) -> Dict[str, Any]:
        """Search for media items."""
        input_data = state.input
        media_type_forced = input_data.get("media_type_forced", False)
        media_type = input_data.get("media_type", "tv")  # Default to tv for auto-fallback
        query = input_data.get("query", "")
        tmdb_id = input_data.get("tmdb_id")
        omdb_id = input_data.get("omdb_id")

        if not query and (tmdb_id or omdb_id):
            self.logger.log_search({}, skip_search=True)
            return {"search": {"results": [], "skip_search": True}}

        search_results = None
        performed_search_type = None

        # If not forced to a specific type, try TV first then Movie
        if not media_type_forced:
            # Try TV first
            if self._should_print(input_data):
                print("🔍 检查TV结果...")
            tv_results = self.tmdb.search_tv(query)
            if tv_results and tv_results.get("results"):
                search_results = tv_results.get("results", [])
                performed_search_type = "tv"
                if self._should_print(input_data):
                    print(f"   ✅ 找到 {len(search_results)} 个TV结果")
            else:
                # Try Movie as fallback
                if self._should_print(input_data):
                    print("   ⚠️ TV无结果，尝试Movie...")
                movie_results = self.tmdb.search_movie(query)
                if movie_results and movie_results.get("results"):
                    search_results = movie_results.get("results", [])
                    performed_search_type = "movie"
                    if self._should_print(input_data):
                        print(f"   ✅ 找到 {len(search_results)} 个Movie结果")
                else:
                    search_results = []
                    performed_search_type = ""
                    if self._should_print(input_data):
                        print("   ❌ 两者均无结果")
        else:
            # Forced to specific type
            if media_type == "movie":
                if self._should_print(input_data):
                    print("🔍 搜索Movie...")
                results = self.tmdb.search_movie(query)
                performed_search_type = "movie"
            else:
                if self._should_print(input_data):
                    print("🔍 搜索TV...")
                results = self.tmdb.search_tv(query)
                performed_search_type = "tv"
            search_results = results.get("results", [])

        # Log search results
        self.logger.log_search({"results": search_results, "performed_search_type": performed_search_type})

        return {"search": {"results": search_results, "performed_search_type": performed_search_type}}

    def select_candidate_node(self, state: GraphState) -> Dict[str, Any]:
        """Select the best candidate from search results."""
        search_results = state.search.get("results", [])
        input_data = state.input
        skip_search = state.search.get("skip_search", False)
        query = input_data.get("query", "")

        if skip_search:
            # Use TMDB ID or OMDB ID directly from input
            tmdb_id = input_data.get("tmdb_id")
            omdb_id = input_data.get("omdb_id")
            media_type = input_data.get("media_type", "tv")  # Default to tv for consistency

            if tmdb_id:
                # Create a mock candidate object with TMDB ID
                candidate = {
                    "id": tmdb_id,
                    "media_type": media_type
                }
            elif omdb_id:
                # Find TMDB ID from OMDB ID
                find_result = self.tmdb.find_by_imdb_id(omdb_id)
                movie_results = find_result.get("movie_results", [])
                tv_results = find_result.get("tv_results", [])

                if media_type == "movie" and movie_results:
                    candidate = movie_results[0]
                    candidate["media_type"] = "movie"
                elif media_type == "tv" and tv_results:
                    candidate = tv_results[0]
                    candidate["media_type"] = "tv"
                else:
                    raise Exception(f"No TMDB ID found for OMDB ID {omdb_id} and media type {media_type}")
            else:
                raise Exception("Either TMDB ID or OMDB ID is required when query is not provided")
        else:
            # Simple selection logic - take first result or by ID
            if input_data.get("tmdb_id"):
                candidate = next((r for r in search_results if r["id"] == input_data["tmdb_id"]), None)
            else:
                candidate = search_results[0] if search_results else None

            # If no candidate found from TMDB search, try Google search if aid_search is enabled
            if not candidate and query and input_data.get("aid_search", False):
                if self._should_print(input_data):
                    print("🔍 TMDB 搜索无结果，尝试谷歌搜索...")

                media_type = input_data.get("media_type", "movie")
                # Create a temporary GoogleSearchAdapter for search operations
                google_config = self.config.get("google", {})
                temp_google_search = GoogleSearchAdapter(
                    proxy=self.config.get("proxy"),
                    api_key=google_config.get("api_key"),
                    search_engine_id=google_config.get("search_engine_id"),
                    quiet=False  # Show info during search
                )
                google_tmdb_id = temp_google_search.search_tmdb_id(query, media_type, verbose=self._should_print(input_data, "verbose"))

                if google_tmdb_id:
                    if self._should_print(input_data):
                        print(f"   通过谷歌搜索找到 TMDB ID: {google_tmdb_id}")

                    candidate = {
                        "id": google_tmdb_id,
                        "media_type": media_type
                    }
                else:
                    if self._should_print(input_data):
                        print("   谷歌搜索也未找到结果")

            if not candidate:
                error_msg = "No suitable candidate found"
                if input_data.get("aid_search", False):
                    error_msg += " from TMDB or Google search (Google search requires JavaScript support)"
                else:
                    error_msg += " from TMDB search"
                raise Exception(error_msg)

            # Ensure media_type is set on the candidate
            if "media_type" not in candidate:
                candidate["media_type"] = input_data.get("media_type", "movie")

        return {"search": {**state.search, "selected": candidate}}

    def fetch_node(self, state: GraphState) -> Dict[str, Any]:
        """Fetch detailed data from TMDB."""
        selected = state.search.get("selected", {})
        input_data = state.input
        tmdb_id = selected.get("id")

        if not tmdb_id:
            raise Exception("No TMDB ID available")

        # Determine media type - override with forced type if specified
        media_type = input_data.get("media_type", "tv")
        if input_data.get("media_type_forced", False):
            # media_type already set from input
            pass
        else:
            # Use auto-detected type from search results
            media_type = selected.get("media_type", media_type)

        # Fetch main data
        if media_type == "movie":
            main_data = self.tmdb.get_movie_details(tmdb_id)
        else:
            main_data = self.tmdb.get_tv_details(tmdb_id)

        # Fetch credits
        credits_data = self.tmdb.get_credits(media_type, tmdb_id)

        # Fetch keywords
        keywords_data = self.tmdb.get_keywords(media_type, tmdb_id)

        # For TV shows, fetch season and episode details
        seasons_data = []
        episodes_data = []

        if media_type == "tv":
            seasons = main_data.get("seasons", [])

            for season in seasons:
                season_number = season.get("season_number", 0)
                if season_number > 0:  # Skip season 0 (specials)
                    try:
                        season_detail = self.tmdb.get_tv_season_details(tmdb_id, season_number)
                        seasons_data.append(season_detail)

                        # Get episodes for this season
                        episodes = season_detail.get("episodes", [])
                        for episode in episodes:
                            episode_number = episode.get("episode_number", 0)
                            try:
                                episode_detail = self.tmdb.get_tv_episode_details(tmdb_id, season_number, episode_number)
                                episodes_data.append(episode_detail)
                            except Exception as e:
                                pass  # Silent fail for individual episodes

                    except Exception as e:
                        pass  # Silent fail for seasons

        source_data = {
            "main": main_data,
            "credits": credits_data,
            "keywords": keywords_data,
            "seasons": seasons_data if seasons_data else None,
            "episodes": episodes_data if episodes_data else None
        }

        # Log the fetched data
        self.logger.log_fetch(source_data)

        return {"source_data": source_data}

    def translate_node(self, state: GraphState) -> Dict[str, Any]:
        """Translate fields that don't have target language versions."""
        source_data = state.source_data
        main_data = source_data.get("main", {})
        episodes_data = source_data.get("episodes", [])
        input_data = state.input
        translate_enabled = input_data.get("translate", False)
        target_language = input_data.get("language", "zh-CN")

        # Determine media type from the selected candidate
        selected = state.search.get("selected", {})
        media_type = selected.get("media_type", "movie")

        # Use existing normalized data if available, otherwise create new
        if state.normalized:
            # Use existing normalized data from previous steps
            normalized = state.normalized
        else:
            # Fallback: normalize from main data (shouldn't happen in normal flow)
            if media_type == "movie":
                normalized = DataNormalizer.normalize_tmdb_movie(main_data)
            else:
                normalized = DataNormalizer.normalize_tmdb_tv(main_data)

            # Enrich with credits if available
            credits_data = source_data.get("credits", {})
            if credits_data:
                normalized = DataNormalizer.enrich_with_credits(normalized, credits_data)

            # Enrich with keywords if available
            keywords_data = source_data.get("keywords", {})
            if keywords_data:
                normalized = DataNormalizer.enrich_with_keywords(normalized, keywords_data, translate_enabled)

        # Check if we need translation based on target language and available data
        needs_translation = False
        if target_language.startswith("zh"):
            # For Chinese, check if Chinese fields are missing
            needs_translation = (
                not normalized.get("title_zh") or
                not normalized.get("plot_zh") or
                not normalized.get("keywords")  # Keywords are only available in English from TMDB
            )
        elif target_language == "en-US":
            # For English, we generally don't need translation since TMDB provides English data
            needs_translation = False

        if translate_enabled and needs_translation:
            # Translate missing fields
            translated = self.translator.translate_metadata(normalized)
        else:
            # Use original data without translation
            translated = normalized

        # Handle episode titles for TV shows
        translated_episodes = []
        if media_type == "tv" and episodes_data:
            if translate_enabled and target_language.startswith("zh"):
                for episode in episodes_data:
                    try:
                        # Create a simple episode data structure for translation
                        episode_for_translation = {
                            "title": episode.get("name", ""),
                            "plot": episode.get("overview", ""),
                        }

                        # Translate episode data
                        translated_episode = self.translator.translate_metadata(episode_for_translation)

                        # Update the episode with translated fields
                        translated_episode_data = episode.copy()
                        translated_episode_data["name_zh"] = translated_episode.get("title_zh", episode.get("name", ""))
                        translated_episode_data["overview_zh"] = translated_episode.get("plot_zh", episode.get("overview", ""))

                        translated_episodes.append(translated_episode_data)
                    except Exception:
                        # If translation fails, use original data
                        translated_episode_data = episode.copy()
                        translated_episode_data["name_zh"] = episode.get("name", "")
                        translated_episode_data["overview_zh"] = episode.get("overview", "")
                        translated_episodes.append(translated_episode_data)
            else:
                # Use original episode data
                translated_episodes = episodes_data

        result_data = {
            **source_data,
            "translated": translated,
            "translated_episodes": translated_episodes if translated_episodes else None
        }

        # Log translation results
        self.logger.log_translate(translated, translated_episodes if translated_episodes else None)

        return {"source_data": result_data}

    def omdb_enrich_node(self, state: GraphState) -> Dict[str, Any]:
        """Enrich with OMDB data."""
        source_data = state.source_data
        main_data = source_data.get("main", {})

        # Get IMDB ID from TMDB data
        imdb_id = main_data.get("imdb_id")
        if not imdb_id:
            return {"source_data": source_data}  # Skip if no IMDB ID

        # Determine media type from the selected candidate
        selected = state.search.get("selected", {})
        media_type = selected.get("media_type", "movie")

        # Try to get OMDB data
        try:
            if media_type == "movie":
                omdb_data = self.omdb.get_movie_details(imdb_id)
            else:  # TV
                omdb_data = self.omdb.get_tv_details(imdb_id)

            return {"source_data": {**source_data, "omdb": omdb_data}}
        except Exception as e:
            print(f"OMDB enrichment failed: {e}")
            return {"source_data": source_data}

    def normalize_node(self, state: GraphState) -> Dict[str, Any]:
        """Normalize all data into internal schema."""
        source_data = state.source_data
        main_data = source_data.get("main", {})
        credits_data = source_data.get("credits", {})
        keywords_data = source_data.get("keywords", {})
        omdb_data = source_data.get("omdb", {})
        input_data = state.input
        translate_enabled = input_data.get("translate", False)

        # Determine media type from the selected candidate
        selected = state.search.get("selected", {})
        media_type = selected.get("media_type", "movie")

        # Normalize base data
        if media_type == "movie":
            normalized = DataNormalizer.normalize_tmdb_movie(main_data)
        else:
            normalized = DataNormalizer.normalize_tmdb_tv(main_data)

        # Ensure episodes data is preserved for TV shows BEFORE enrich_with_credits
        if media_type == "tv" and source_data.get("episodes"):
            normalized["episodes"] = source_data["episodes"]

        # Enrich with credits (directors, writers, cast) - now episodes are available
        normalized = DataNormalizer.enrich_with_credits(normalized, credits_data)

        # Enrich with keywords
        normalized = DataNormalizer.enrich_with_keywords(normalized, keywords_data, translate_enabled)

        # Enrich with OMDB if available
        if omdb_data:
            normalized = DataNormalizer.enrich_with_omdb(normalized, omdb_data)

        # Translate tags if enabled
        tag_translation_enabled = input_data.get("translate_tags", True)
        if tag_translation_enabled and normalized.get("keywords"):
            if self._should_print(input_data):
                print("🏷️ 翻译标签...")

            original_tags = normalized["keywords"]
            translated_tags = self.tag_translator.translate_tags(original_tags)

            # Update normalized data with translated tags
            normalized["keywords_zh"] = translated_tags

            # Show translation results
            if self._should_print(input_data):
                translated_count = sum(1 for orig, trans in zip(original_tags, translated_tags) if orig != trans)
                print(f"   翻译了 {translated_count} 个标签，共 {len(original_tags)} 个")

                # Show translated tags in normal mode, examples in verbose mode
                if translated_count > 0:
                    if self._should_print(input_data, "verbose"):
                        # Verbose mode: show examples
                        examples = []
                        for orig, trans in zip(original_tags, translated_tags):
                            if orig != trans:
                                examples.append(f"'{orig}' -> '{trans}'")
                                if len(examples) >= 3:  # Show up to 3 examples
                                    break
                        if examples:
                            print(f"   示例: {', '.join(examples)}")
                    else:
                        # Normal mode: show translated tags list
                        print(f"   中文标签: {', '.join(translated_tags)}")

        # Log normalization results
        self.logger.log_normalize(normalized)

        return {"normalized": normalized}

    def plan_artwork_node(self, state: GraphState) -> Dict[str, Any]:
        """Plan artwork downloads."""
        normalized = state.normalized
        media_type = normalized.get("media_type")
        tmdb_id = normalized.get("tmdb_id")

        if not media_type or not tmdb_id:
            raise Exception("Missing media_type or tmdb_id in normalized data")

        # Get available images
        images_data = self.tmdb.get_images(media_type, tmdb_id)

        artwork_plan = {
            "poster": images_data.get("posters", [])[:3],  # Top 3 posters
            "fanart": images_data.get("backdrops", [])[:3],  # Top 3 backdrops
            "banner": [],  # TMDB doesn't have banners
            "logo": images_data.get("logos", [])[:2],  # Top 2 logos
        }

        if media_type == "tv":
            artwork_plan["stills"] = []  # Will be filled during download

        return {"artwork": {"plan": artwork_plan, "images_data": images_data}}

    def download_all_images_node(self, state: GraphState) -> Dict[str, Any]:
        """Download all planned images."""
        normalized = state.normalized
        input_data = state.input
        artwork_plan = state.artwork.get("plan", {})
        extra_images = input_data.get("extra_images", False)

        media_type = normalized.get("media_type", "movie")
        tmdb_id = normalized.get("tmdb_id")
        output_dir = input_data.get("output_dir", "./output")
        title = normalized.get("title", "Unknown")
        year = normalized.get("year", 0)

        if self._should_print(input_data):
            print("🖼️ 下载图片...")

        # Create media directory first
        media_dir = FileSystemManager.create_media_directory(output_dir, title, year, media_type, inplace=state.inplace)

        # Download all images
        if media_type and tmdb_id:
            downloaded_images = self.artwork.download_all_images(media_type, tmdb_id, media_dir, self._should_print(input_data, "verbose"), extra_images)

            # Count downloaded images
            total_images = sum(len(images) for images in downloaded_images.values() if isinstance(images, list))
            if self._should_print(input_data):
                print(f"   下载了 {total_images} 张图片")

                # Show details in verbose mode
                if self._should_print(input_data, "verbose"):
                    for image_type, images in downloaded_images.items():
                        if isinstance(images, list) and images:
                            print(f"   {image_type}: {len(images)} 张")
        else:
            downloaded_images = {}
            if self._should_print(input_data):
                print("   跳过图片下载（缺少必要信息）")

        return {"artwork": {**state.artwork, "downloaded": downloaded_images}}

    def llm_map_to_nfo_node(self, state: GraphState) -> Dict[str, Any]:
        """Map internal data to NFO schema using LLM."""
        normalized = state.normalized
        input_data = state.input
        media_type = normalized.get("media_type")

        if media_type == "movie":
            nfo_data = self.mapper.map_to_movie_nfo(normalized)
            nfo_dict = nfo_data.model_dump()
        else:
            nfo_data = self.mapper.map_to_tvshow_nfo(normalized)
            nfo_dict = nfo_data.model_dump()

        return {"nfo": nfo_dict}

    def validate_nfo_node(self, state: GraphState) -> Dict[str, Any]:
        """Validate NFO data."""
        nfo_data = state.nfo

        # Basic validation - check required fields
        required_fields = ["title", "year"]
        for field in required_fields:
            if field not in nfo_data or not nfo_data[field]:
                raise Exception(f"Missing required field: {field}")

        return {"nfo": {**nfo_data, "validated": True}}

    def render_xml_node(self, state: GraphState) -> Dict[str, Any]:
        """Render NFO data to XML."""
        nfo_data = state.nfo
        normalized = state.normalized
        input_data = state.input
        media_type = normalized.get("media_type")
        tmdb_id = normalized.get("tmdb_id")

        if media_type == "movie":
            from ..core.schema_nfo import MovieNfo
            nfo_obj = MovieNfo(**nfo_data)
            xml_content = NfoRenderer.render_movie_nfo(nfo_obj, tmdb_id)
        else:
            from ..core.schema_nfo import TvShowNfo
            nfo_obj = TvShowNfo(**nfo_data)
            xml_content = NfoRenderer.render_tvshow_nfo(nfo_obj, tmdb_id)

        # Log NFO generation
        self.logger.log_nfo(nfo_data, xml_content)

        return {"nfo": {**nfo_data, "xml": xml_content}}

    def write_output_node(self, state: GraphState) -> Dict[str, Any]:
        """Write files to output directory."""
        normalized = state.normalized
        nfo_data = state.nfo
        input_data = state.input
        source_data = state.source_data

        media_type = normalized.get("media_type", "movie")
        title = normalized.get("title", "Unknown")
        year = normalized.get("year", 0)
        output_dir = input_data.get("output_dir", "./output")

        if self._should_print(input_data):
            print("💾 写入输出文件...")

        # Create media directory
        media_dir = FileSystemManager.create_media_directory(output_dir, title, year, media_type, inplace=state.inplace)

        # Note: No longer create images directory as per new requirements

        # Write NFO file
        xml_content = nfo_data.get("xml", "")
        nfo_filename = f"{title} ({year}).nfo" if media_type == "movie" else "tvshow.nfo"
        nfo_path = FileSystemManager.write_nfo_file(media_dir, nfo_filename, xml_content)

        if self._should_print(input_data):
            print(f"   媒体目录: {media_dir}")
            print(f"   NFO 文件: {nfo_path}")

        files_created = {
            "nfo_file": nfo_path,
            "media_dir": media_dir
        }

        # Handle TV show episodes
        if media_type == "tv":
            seasons_data = source_data.get("seasons", [])
            episodes_data = source_data.get("translated_episodes", source_data.get("episodes", []))

            if seasons_data and episodes_data:
                if self._should_print(input_data):
                    print("📺 处理剧集数据...")

                # Group episodes by season
                episodes_by_season = {}
                for episode in episodes_data:
                    season_num = episode.get("season_number", 0)
                    if season_num not in episodes_by_season:
                        episodes_by_season[season_num] = []
                    episodes_by_season[season_num].append(episode)

                # Process each season
                for season_data in seasons_data:
                    season_number = season_data.get("season_number", 0)
                    if season_number <= 0:  # Skip specials
                        continue

                    season_dir = FileSystemManager.create_season_directory(media_dir, season_number)

                    # Process episodes in this season
                    season_episodes = episodes_by_season.get(season_number, [])
                    for episode_data in season_episodes:
                        episode_number = episode_data.get("episode_number", 0)
                        episode_title = episode_data.get("name", f"Episode {episode_number}")

                        # Create episode directory and images folder
                        episode_dir, episode_images_dir = FileSystemManager.create_episode_directory(
                            season_dir, title, season_number, episode_number, episode_title
                        )

                        # Generate episode NFO content
                        episode_nfo = self.mapper.map_to_episode_nfo(normalized, episode_data, normalized)
                        episode_nfo_content = NfoRenderer.render_episode_nfo(episode_nfo)
                        episode_nfo_path = FileSystemManager.write_episode_nfo(
                            season_dir, title, season_number, episode_number, episode_title, episode_nfo_content
                        )

                        # Download episode-specific images (poster, fanart, thumb)
                        try:
                            selected = state.search.get("selected", {})
                            tmdb_id = selected.get("id")
                            episode_images_data = self.tmdb.get_tv_episode_images(tmdb_id, season_number, episode_number)

                            if self._should_print(input_data):
                                print(f"      📸 处理剧集 S{season_number:02d}E{episode_number:02d} 图片...")

                            # Clean episode title for filename
                            if '/' in episode_title:
                                safe_episode_title = episode_title.split('/')[0].strip()
                            else:
                                safe_episode_title = "".join(c for c in episode_title if c not in '\\:*?"<>|').strip()

                            # Define target filenames (Emby standard)
                            episode_thumb_filename = f"{title} - S{season_number:02d}E{episode_number:02d} - {safe_episode_title}-thumb.jpg"
                            episode_fanart_filename = f"{title} - S{season_number:02d}E{episode_number:02d} - {safe_episode_title}-fanart.jpg"

                            episode_thumb_path = os.path.join(season_dir, episode_thumb_filename)
                            episode_fanart_path = os.path.join(season_dir, episode_fanart_filename)

                            # Remove any existing thumb files for this episode (cleanup from previous runs)
                            import glob
                            thumb_pattern = os.path.join(season_dir, f"{title} - S{season_number:02d}E{episode_number:02d} - {safe_episode_title}-thumb*.jpg")
                            for old_thumb_file in glob.glob(thumb_pattern):
                                try:
                                    os.remove(old_thumb_file)
                                    if self._should_print(input_data, "verbose"):
                                        print(f"      🗑️  删除旧thumb文件: {os.path.basename(old_thumb_file)}")
                                except Exception as e:
                                    if self._should_print(input_data, "verbose"):
                                        print(f"      ⚠️ 无法删除旧thumb文件 {old_thumb_file}: {e}")

                            # Check available episode images
                            available_stills = len(episode_images_data.get('stills', []))
                            if self._should_print(input_data):
                                print(f"      📊 TMDB提供 {available_stills} 张剧集截图")

                            # Download episode images (Emby standard: -thumb.jpg and -fanart.jpg)
                            thumb_downloaded = False
                            fanart_downloaded = False
                            if episode_images_data.get('stills'):
                                still = episode_images_data['stills'][0]  # Only download the first still
                                if still.get('file_path'):
                                    still_path = still['file_path']
                                    if not still_path.startswith('/'):
                                        still_path = '/' + still_path
                                    still_url = f"https://image.tmdb.org/t/p/original{still_path}"

                                    if self._should_print(input_data):
                                        print(f"      ⬇️  下载剧集图片: {episode_thumb_filename}")
                                    # Download as thumb
                                    if self.artwork.download_image(episode_thumb_path, still_url):
                                        thumb_downloaded = True
                                        # Also copy as fanart
                                        try:
                                            import shutil
                                            shutil.copy2(episode_thumb_path, episode_fanart_path)
                                            fanart_downloaded = True
                                        except:
                                            pass
                                        if self._should_print(input_data):
                                            print("      ✓ thumb图片下载成功")
                                    else:
                                        if self._should_print(input_data):
                                            print("      ✗ thumb图片下载失败")
                            else:
                                if self._should_print(input_data):
                                    print("      ⚠️ 无可用剧集图片，将尝试复制其他图片")

                            # If thumb still missing, try to copy from main poster
                            if not thumb_downloaded:
                                main_poster = os.path.join(media_dir, "poster.jpg")
                                if os.path.exists(main_poster):
                                    if self._should_print(input_data):
                                        print("      📋 thumb缺失，使用主poster...")
                                    try:
                                        shutil.copy2(main_poster, episode_thumb_path)
                                        thumb_downloaded = True
                                        if self._should_print(input_data):
                                            print("      ✓ episode thumb从主poster创建成功")
                                    except Exception as e:
                                        if self._should_print(input_data):
                                            print(f"      ⚠️ 主poster复制失败: {e}")
                                else:
                                    if self._should_print(input_data):
                                        print("      ⚠️ 主poster不存在")

                            # If fanart still missing, try to copy from main fanart
                            if not fanart_downloaded:
                                main_fanart = os.path.join(media_dir, "fanart.jpg")
                                if os.path.exists(main_fanart):
                                    if self._should_print(input_data):
                                        print("      📋 fanart缺失，使用主fanart...")
                                    try:
                                        shutil.copy2(main_fanart, episode_fanart_path)
                                        fanart_downloaded = True
                                        if self._should_print(input_data):
                                            print("      ✓ episode fanart从主fanart创建成功")
                                    except Exception as e:
                                        if self._should_print(input_data):
                                            print(f"      ⚠️ 主fanart复制失败: {e}")
                                else:
                                    if self._should_print(input_data):
                                        print("      ⚠️ 主fanart不存在")

                            # Final status report (thumb and fanart)
                            thumb_exists = os.path.exists(episode_thumb_path)
                            fanart_exists = os.path.exists(episode_fanart_path)

                            if self._should_print(input_data):
                                status_parts = []
                                if thumb_exists:
                                    status_parts.append("thumb✓")
                                else:
                                    status_parts.append("thumb✗")
                                if fanart_exists:
                                    status_parts.append("fanart✓")
                                else:
                                    status_parts.append("fanart✗")
                                print(f"      📊 最终状态: {' | '.join(status_parts)}")

                        except Exception as e:
                            if self._should_print(input_data, "verbose"):
                                print(f"      ⚠️ Episode image processing failed: {e}")
                            pass  # Silent fail for image download

                        files_created[f"season_{season_number}_episode_{episode_number}"] = episode_nfo_path

                total_episodes = sum(len(episodes) for episodes in episodes_by_season.values() if episodes)
                if self._should_print(input_data):
                    print(f"   处理完成: {len(episodes_by_season)} 季, {total_episodes} 集")

        if self._should_print(input_data):
            print(f"   创建了 {len(files_created)} 个文件/目录")

        # Log output results
        output_data = {"status": "completed", "files": files_created}
        self.logger.log_output(output_data)

        return {"output": output_data}



    def report_node(self, state: GraphState) -> Dict[str, Any]:
        """Generate final report."""
        # Finalize logging
        log_file = self.logger.finalize()

        result = {"output": {**state.output, "report": "Processing completed successfully", "log_file": log_file}}

        # Print final summary
        if not self.logger.quiet:
            print(f"\n✅ 处理完成! 日志文件: {log_file}")

        return result
