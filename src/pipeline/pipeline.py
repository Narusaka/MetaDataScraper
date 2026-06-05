import os
import shutil
import difflib
import re
from typing import Dict, Any, List, Optional, Tuple

from ..adapters.tmdb import TMDBAdapter
from ..adapters.OMDB import OMDBAdapter
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

    def __init__(self, config: Dict[str, Any], skip_images: bool = False, preferred_language: str = "zh-CN", verbose: bool = False, quiet: bool = False, inplace: bool = False, extra_images: bool = False, manifest: Optional[Any] = None):
        self.config = config
        self.skip_images = skip_images
        self.preferred_language = preferred_language
        self.inplace = inplace
        self.extra_images = extra_images
        self.verbose = verbose
        self.quiet = quiet
        self.manifest = manifest

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
        
        # Tavily Search
        tavily_config = config.get("tavily", {})
        tavily_keys = tavily_config.get("api_keys", [])
        if not isinstance(tavily_keys, list): tavily_keys = [tavily_keys]
        
        # Also check single api_key
        if tavily_config.get("api_key"): tavily_keys.append(tavily_config.get("api_key"))
        
        if os.getenv("TAVILY_API_KEY"): tavily_keys.append(os.getenv("TAVILY_API_KEY"))
        if os.getenv("TAVILY_API_KEY_2"): tavily_keys.append(os.getenv("TAVILY_API_KEY_2"))
        if os.getenv("TAVILY_API_KEY_3"): tavily_keys.append(os.getenv("TAVILY_API_KEY_3"))
        
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
        self.artwork = ArtworkDownloader(config["tmdb"]["api_key"], config.get("proxy"), manifest=manifest)

    def _log(self, msg: str, verbose_only: bool = False):
        import logging
        if self.quiet and not verbose_only: 
            # In quiet mode, still log to the logging system for remote terminal visibility
            # but maybe at a lower level or respect the quiet flag?
            # Actually, the user wants 'Live Logs', so we SHOULD log to the logging system.
            pass 
        
        if verbose_only and not self.verbose: return
        
        # Strip emojis for cleaner system logs if preferred, or keep them
        logging.info(msg)

    def _clean_query_for_match(self, query: str) -> str:
        return re.sub(r'\s*\(\d{4}\)', '', query or "").strip().lower()

    def _has_cjk(self, text: str) -> bool:
        return bool(re.search(r'[\u3040-\u30ff\u3400-\u9fff]', text or ""))

    def _token_overlap(self, a: str, b: str) -> float:
        a_tokens = set(re.findall(r'[a-z0-9]+', (a or "").lower()))
        b_tokens = set(re.findall(r'[a-z0-9]+', (b or "").lower()))
        if not a_tokens or not b_tokens:
            return 0.0
        return len(a_tokens & b_tokens) / len(a_tokens)

    def _candidate_title_text(self, candidate: Dict[str, Any]) -> str:
        return " ".join(
            value
            for value in [
                candidate.get("name"),
                candidate.get("title"),
                candidate.get("original_name"),
                candidate.get("original_title"),
                *self._candidate_aliases(candidate),
            ]
            if value
        )

    def _candidate_aliases(self, candidate: Dict[str, Any]) -> List[str]:
        if isinstance(candidate, dict) and ("titles" in candidate or "results" in candidate):
            aliases = candidate.get("titles") or candidate.get("results") or []
        else:
            aliases = candidate.get("alternative_titles") or candidate.get("_aliases") or []
        if isinstance(aliases, dict):
            aliases = aliases.get("titles") or aliases.get("results") or []
        result = []
        for item in aliases:
            if isinstance(item, str):
                title = item
            elif isinstance(item, dict):
                title = item.get("title") or item.get("name")
            else:
                title = None
            if title and title not in result:
                result.append(title)
        return result

    def _candidate_title_values(self, candidate: Dict[str, Any]) -> List[Tuple[str, str]]:
        values: List[Tuple[str, str]] = []
        for field in ["name", "title", "original_name", "original_title"]:
            value = (candidate.get(field) or "").strip()
            if value:
                values.append((field, value))
        values.extend(("alias", value) for value in self._candidate_aliases(candidate))
        return values

    def _candidate_year(self, candidate: Dict[str, Any]) -> int:
        date_str = candidate.get('first_air_date') or candidate.get('release_date') or ""
        return int(date_str[:4]) if date_str and len(date_str) >= 4 and date_str[:4].isdigit() else 0

    def _candidate_similarity(self, clean_query: str, candidate: Dict[str, Any]) -> float:
        return self._candidate_best_title_match(clean_query, candidate)["score"]

    def _candidate_best_title_match(self, clean_query: str, candidate: Dict[str, Any]) -> Dict[str, Any]:
        best = {"score": 0.0, "field": None, "title": None}
        for field, title in self._candidate_title_values(candidate):
            score = difflib.SequenceMatcher(None, clean_query, title.lower()).ratio()
            if score > best["score"]:
                best = {"score": score, "field": field, "title": title}
        return best

    def _enrich_candidate_aliases(self, candidate: Dict[str, Any], media_type: str) -> None:
        if candidate.get("_aliases_loaded"):
            return
        candidate["_aliases_loaded"] = True
        getter = getattr(self.tmdb, "get_alternative_titles", None)
        if not getter or not candidate.get("id"):
            return
        try:
            aliases_data = getter(media_type, candidate.get("id"))
        except Exception as exc:
            candidate["_aliases_error"] = str(exc)
            return
        candidate["_aliases"] = self._candidate_aliases(aliases_data)

    def _candidate_rejection_reason(self, candidate: Dict[str, Any], target_year: Optional[int] = None, selected_id: Optional[int] = None) -> str:
        if selected_id and candidate.get("id") == selected_id:
            return "selected"
        candidate_year = candidate.get("_match_year") or self._candidate_year(candidate)
        if target_year and candidate_year and candidate_year != target_year:
            return "year_mismatch"
        score = candidate.get("_match_score", 0) or 0
        overlap = candidate.get("_token_overlap", 0) or 0
        if score < 0.55 and overlap < 0.75:
            return "low_similarity"
        return "not_best_match"

    def _summarize_candidates(
        self,
        candidates: List[Dict[str, Any]],
        limit: int = 5,
        target_year: Optional[int] = None,
        selected_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        top_candidates = sorted(candidates, key=lambda item: item.get("_match_score", 0), reverse=True)[:limit]
        return [
            {
                "id": item.get("id"),
                "title": item.get("name") or item.get("title"),
                "original_title": item.get("original_name") or item.get("original_title"),
                "media_type": item.get("_search_type") or item.get("media_type"),
                "year": item.get("_match_year") or self._candidate_year(item),
                "score": round(item.get("_match_score", 0), 4),
                "token_overlap": round(item.get("_token_overlap", 0), 4),
                "matched_title": item.get("_matched_title"),
                "matched_field": item.get("_matched_field"),
                "decision": self._candidate_rejection_reason(item, target_year=target_year, selected_id=selected_id),
                "alias_error": item.get("_aliases_error"),
            }
            for item in top_candidates
        ]

    def _verify_external_candidate(self, query: str, target_year: Optional[int], media_type: str, tmdb_id: int) -> Dict[str, Any]:
        """Fetch and score an external TMDB id before trusting it."""
        try:
            details = self.tmdb.get_movie_details(tmdb_id) if media_type == "movie" else self.tmdb.get_tv_details(tmdb_id)
        except Exception as exc:
            return {
                "accepted": False,
                "reason": "external_details_failed",
                "error": str(exc),
                "score": 0.0,
                "token_overlap": 0.0,
            }

        candidate = dict(details or {})
        candidate["id"] = tmdb_id
        candidate["media_type"] = media_type
        if media_type == "movie":
            candidate.setdefault("name", candidate.get("title"))
            candidate.setdefault("original_name", candidate.get("original_title"))
        else:
            candidate.setdefault("title", candidate.get("name"))
            candidate.setdefault("original_title", candidate.get("original_name"))

        self._enrich_candidate_aliases(candidate, media_type)
        clean_query = self._clean_query_for_match(query)
        best_title = self._candidate_best_title_match(clean_query, candidate)
        score = best_title["score"]
        overlap = self._token_overlap(clean_query, self._candidate_title_text(candidate))
        candidate_year = self._candidate_year(candidate)
        query_has_cjk = self._has_cjk(clean_query)
        title_text = self._candidate_title_text(candidate)
        candidate_has_cjk = self._has_cjk(title_text)
        year_conflicts = bool(target_year and candidate_year and candidate_year != target_year)

        accepts_title = score >= 0.55 or overlap >= 0.75
        accepts_localized = not query_has_cjk and candidate_has_cjk and score >= 0.25
        accepted = not year_conflicts and (accepts_title or accepts_localized)
        confidence = "high" if score >= 0.75 or overlap >= 0.85 else ("medium" if accepted else "none")

        candidate["_match_score"] = score
        candidate["_match_year"] = candidate_year
        candidate["_matched_title"] = best_title.get("title")
        candidate["_matched_field"] = best_title.get("field")
        candidate["_token_overlap"] = overlap

        return {
            "accepted": accepted,
            "reason": "external_verified" if accepted else ("year_mismatch" if year_conflicts else "external_low_confidence"),
            "confidence": confidence,
            "score": score,
            "token_overlap": overlap,
            "candidate": candidate,
            "candidate_year": candidate_year,
            "matched_title": best_title.get("title"),
            "matched_field": best_title.get("field"),
        }

    def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the pipeline linearly."""
        try:
            self._log(f"▶️ Pipeline Input: Type={input_data.get('media_type')}, Query={input_data.get('query')}", verbose_only=False)
            # 1. Input & Search
            search_result = self._step_search(input_data)
            candidate = search_result.get("selected")
            match_explanation = search_result.get("match", {})
            
            if not candidate:
                self._log("❌ No candidate found.", verbose_only=False)
                return {"status": "failed", "error": "No candidate found", "match": match_explanation}

            tmdb_id = candidate["id"]
            media_type = candidate.get("media_type")

            # Ensure we have the title/year for logging/UI update (even for direct ID runs)
            # Fetch details if missing title OR if we need to validate year for a non-TMDB-search result
            target_year = input_data.get("year")
            
            if not (candidate.get("name") or candidate.get("title")) or (target_year and "first_air_date" not in candidate and "release_date" not in candidate):
                try:
                    if media_type == "movie":
                        details = self.tmdb.get_movie_details(tmdb_id)
                        candidate["title"] = details.get("title", "")
                        candidate["name"] = details.get("title", "")
                        candidate["release_date"] = details.get("release_date", "")
                        candidate["poster_path"] = details.get("poster_path")
                    else:
                        details = self.tmdb.get_tv_details(tmdb_id)
                        candidate["name"] = details.get("name", "")
                        candidate["title"] = details.get("name", "")
                        candidate["first_air_date"] = details.get("first_air_date", "")
                        candidate["poster_path"] = details.get("poster_path")
                except:
                    pass # Ignore fetch error, just log what we have

            # Strict Year Validation
            candidate_date = candidate.get('first_air_date') or candidate.get('release_date') or ""
            candidate_year = int(candidate_date[:4]) if candidate_date and len(candidate_date) >= 4 else 0
            
            # Skip validation if manual ID provided
            is_manual_override = input_data.get("tmdb_id") is not None
            
            if target_year and candidate_year != 0 and not is_manual_override:
                 if candidate_year != target_year:
                     self._log(f"❌ STRICT MODE: Candidate Year {candidate_year} != Target {target_year}. Rejecting ID {tmdb_id}.", verbose_only=False)
                     match_explanation.update({
                         "confidence": "none",
                         "reason": "year_mismatch",
                         "candidate_year": candidate_year,
                         "selected_id": None,
                     })
                     return {"status": "failed", "error": f"Year mismatch: {candidate_year} vs {target_year}", "match": match_explanation}

            # Append Year to Title for UI Display and Sanitize for Logging
            display_title = candidate.get('name') or candidate.get('title')
            # Replace single quotes with typographic ones to avoid breaking frontend regex matching Title='...'
            if display_title:
                display_title = display_title.replace("'", "’")
            
            if candidate_year and display_title:
                if str(candidate_year) not in display_title:
                    candidate["name"] = f"{display_title} ({candidate_year})"
                    candidate["title"] = f"{display_title} ({candidate_year})"
            elif display_title:
                 candidate["name"] = display_title
                 candidate["title"] = display_title

            self._log(f"✅ Selected Candidate: TMDB ID {tmdb_id} Title='{candidate.get('name') or candidate.get('title')}' (Type: {media_type})", verbose_only=False)

            if not media_type:
                 self._log("❌ Error: Candidate has no media_type!", verbose_only=False)
                 return {"status": "failed", "error": "Candidate missing media_type"}

            # 2. Fetch Data
            if input_data.get("audit_only", False):
                # Ensure we have the title for the audit log
                if not (candidate.get("name") or candidate.get("title")):
                    try:
                        self._log(f"📥 Fetching basic details for Audit ID {tmdb_id}...", verbose_only=True)
                        if media_type == "movie":
                            details = self.tmdb.get_movie_details(tmdb_id)
                            candidate["title"] = details.get("title", "")
                            candidate["name"] = details.get("title", "")
                            candidate["poster_path"] = details.get("poster_path")
                        else:
                            details = self.tmdb.get_tv_details(tmdb_id)
                            candidate["name"] = details.get("name", "")
                            candidate["title"] = details.get("name", "")
                            candidate["poster_path"] = details.get("poster_path")
                    except Exception as e:
                        self._log(f"⚠️ Failed to fetch title for audit: {e}", verbose_only=True)

                # Use source_path for audit logging so frontend can restart task correctly
                path_log = input_data.get('source_path') or input_data.get('output_dir')
                poster_suffix = candidate.get('poster_path')
                poster_url = f"https://image.tmdb.org/t/p/w200{poster_suffix}" if poster_suffix else ""
                self._log(f"🕵️ AUDIT_HIT: Path='{path_log}' ID={tmdb_id} Title='{candidate.get('name') or candidate.get('title')}' Type='{media_type}' [Poster={poster_url}]", verbose_only=False)
                audit_title = candidate.get("name") or candidate.get("title") or ""
                audit_date = candidate.get("first_air_date") or candidate.get("release_date") or ""
                audit_year = int(audit_date[:4]) if audit_date and len(audit_date) >= 4 and audit_date[:4].isdigit() else candidate_year
                return {
                    "status": "audit_completed",
                    "candidate": candidate,
                    "match": match_explanation,
                    "tmdb_id": tmdb_id,
                    "media_type": media_type,
                    "artwork": {"status": "skipped", "reason": "audit_only"},
                    "normalized": {
                        "tmdb_id": tmdb_id,
                        "media_type": media_type,
                        "title": audit_title,
                        "title_zh": audit_title,
                        "year": audit_year,
                        "poster_path": candidate.get("poster_path"),
                    },
                    "source_data": {},
                }

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

            if input_data.get("plan_only", False):
                output_dir = input_data.get("output_dir") or "./output"
                planned_media_dir = self._planned_media_directory(
                    output_dir,
                    normalized.get("title"),
                    normalized.get("year"),
                    media_type,
                )
                return {
                    "status": "plan_ready",
                    "normalized": normalized,
                    "candidate": candidate,
                    "match": match_explanation,
                    "nfo": nfo_data,
                    "source_data": source_data,
                    "output": {"media_dir": planned_media_dir},
                    "artwork": {"status": "skipped", "reason": "plan_only"},
                }
            
            # 7. Write Output
            output_result = self._step_write_output(normalized, nfo_data, source_data, input_data)
            
            # 8. Download Images (post-writing, or during)
            artwork_result = (
                {"status": "skipped", "reason": "skip_images"}
                if self.skip_images
                else self._step_download_images(normalized, output_result["media_dir"], input_data)
            )

            poster_suffix = normalized.get('poster_path')
            poster_url = f"https://image.tmdb.org/t/p/w200{poster_suffix}" if poster_suffix else ""
            self._log(f"🐛 DEBUG: Poster Suffix='{poster_suffix}' URL='{poster_url}'")
            self._log(f"🏆 Task Successfully Finished: {normalized.get('title')} [Poster={poster_url}]")
            return {
                "status": "completed",
                "normalized": normalized,
                "candidate": candidate,
                "match": match_explanation,
                "nfo": nfo_data,
                "source_data": source_data,
                "output": output_result,
                "artwork": artwork_result,
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
        """Step 1: Search for media."""
        query = input_data.get("query", "")
        tmdb_id = input_data.get("tmdb_id")
        media_type = input_data.get("media_type", "tv")
        force_type = input_data.get("media_type_forced", False)
        mode = input_data.get("search_mode", "smart") # smart, tmdb_only, tavily_only
        
        self._log(f"🕵️‍♂️ DEBUG: Search Mode='{mode}' Query='{query}' Type='{media_type}' ForceType={force_type}")
        
        # Extract year from query if not already provided
        target_year = input_data.get("year")
        import re
        year_match = re.search(r'\((\d{4})\)', query)
        if year_match and not target_year:
            target_year = int(year_match.group(1))
            self._log(f"📅 Extracted Year from query: {target_year}")

        # Direct ID
        if tmdb_id:
            return {
                "selected": {"id": int(tmdb_id), "media_type": media_type},
                "match": {
                    "provider": "manual",
                    "confidence": "manual",
                    "reason": "tmdb_id_override",
                    "score": 1.0,
                    "candidates": [],
                },
            }
            
        candidate = None
        match_explanation: Dict[str, Any] = {
            "provider": None,
            "confidence": "none",
            "reason": "no_candidate",
            "score": 0.0,
            "token_overlap": 0.0,
            "candidates": [],
        }
        
        # User defined priority: Smart Mode (Auto) -> Prioritize Movie
        if force_type:
            search_types = [media_type]
        else:
            search_types = ["movie", "tv"]

        # 1. TMDB Search (Search both types if not forced)
        if mode in ["smart", "tmdb_only"]:
            all_candidates = []
            for m_type in search_types:
                self._log(f"🔍 Searching TMDB as {m_type}: '{query}' ...")
                results = self.tmdb.search_tv(query) if m_type == "tv" else self.tmdb.search_movie(query)
                if results and results.get("results"):
                    for c in results["results"][:10]:
                        c["_search_type"] = m_type
                        all_candidates.append(c)
            
            if all_candidates:
                self._log(f"   🔎 Found {len(all_candidates)} total candidates, analyzing similarity...")
                best_match = None
                best_score = -1.0
                
                # Clean query for similarity check (remove year)
                clean_query = self._clean_query_for_match(query)
                
                for i, c in enumerate(all_candidates):
                     date_str = c.get('first_air_date') or c.get('release_date') or ""
                     c_year = self._candidate_year(c)
                     c_title = (c.get('name') or c.get('title') or "").strip()
                     self._enrich_candidate_aliases(c, c.get("_search_type") or media_type)
                     
                     # Calculate similarity score
                     best_title = self._candidate_best_title_match(clean_query, c)
                     current_score = best_title["score"]
                     token_overlap = self._token_overlap(clean_query, self._candidate_title_text(c))
                     c["_match_score"] = current_score
                     c["_match_year"] = c_year
                     c["_matched_title"] = best_title.get("title")
                     c["_matched_field"] = best_title.get("field")
                     c["_token_overlap"] = token_overlap
                     
                     match_info = f" [Score: {current_score:.2f}]"
                     if target_year:
                         if c_year == target_year:
                             match_info += " [✅ YEAR MATCH]"
                         else:
                             match_info += f" [❌ Year Mismatch: {c_year}]"

                     if self.verbose:
                         self._log(f"      {i+1}. [{c.get('id')}] {c_title} ({date_str}){match_info}")
                     
                     # Selection Logic:
                     if target_year:
                         # 1. Prioritize YEAR matches first. 
                         # Among year matches, pick highest score.
                         if c_year == target_year:
                             # We use a weighted score for year match to favor it, 
                             # but title similarity still matters.
                             if current_score > best_score:
                                 best_score = current_score
                                 best_match = c
                     else:
                         # 2. No year provided, pick highest similarity
                         if current_score > best_score:
                             best_score = current_score
                             best_match = c
                
                # Final filter: Romanized anime searches often return localized CJK titles.
                # Be strict for Latin-to-Latin matches to avoid false positives like
                # "Front Innocent" -> "Steven Avery: Innocent or Guilty?", but allow
                # low text similarity when TMDB returns a localized CJK candidate.
                threshold = 0.25
                if best_match:
                    title_for_filter = self._candidate_title_text(best_match)
                    query_has_cjk = self._has_cjk(clean_query)
                    candidate_has_cjk = self._has_cjk(title_for_filter)
                    latin_overlap = self._token_overlap(clean_query, title_for_filter)

                    accepts_localized_title = (
                        not target_year
                        and not query_has_cjk
                        and candidate_has_cjk
                        and len(all_candidates) <= 2
                    )
                    accepts_latin_title = best_score >= 0.55 or latin_overlap >= 0.75

                    accepts_candidate = (
                        accepts_latin_title
                        if not candidate_has_cjk
                        else (best_score >= threshold or accepts_localized_title)
                    )
                    match_explanation = {
                        "provider": "tmdb",
                        "confidence": "none",
                        "reason": "low_confidence",
                        "score": round(best_score, 4),
                        "token_overlap": round(latin_overlap, 4),
                        "target_year": target_year,
                        "candidates": self._summarize_candidates(
                            all_candidates,
                            target_year=target_year,
                            selected_id=best_match.get("id") if accepts_candidate else None,
                        ),
                    }

                    if accepts_candidate:
                        candidate = best_match
                        candidate["media_type"] = candidate["_search_type"]
                        if candidate.get("_matched_field") == "alias":
                            reason = "alias"
                        else:
                            reason = "localized title" if accepts_localized_title and best_score < threshold else "similarity"
                        confidence = "high" if best_score >= 0.75 or latin_overlap >= 0.85 else ("medium" if best_score >= 0.55 or latin_overlap >= 0.75 else "low")
                        match_explanation.update({
                            "confidence": confidence,
                            "reason": reason,
                            "selected_id": candidate.get("id"),
                            "selected_title": candidate.get("name") or candidate.get("title"),
                            "matched_title": candidate.get("_matched_title"),
                            "matched_field": candidate.get("_matched_field"),
                        })
                        self._log(f"   ✅ Selected Best Match: {candidate.get('name') or candidate.get('title')} (ID: {candidate.get('id')}, Score: {best_score:.2f}, Type: {candidate['media_type']}, Reason: {reason})")
                    else:
                        self._log(f"   ⚠️ Best match '{best_match.get('name') or best_match.get('title')}' rejected due to low confidence (score={best_score:.2f}, token_overlap={latin_overlap:.2f})")
                elif target_year:
                     self._log(f"   ⚠️ No candidates matched year {target_year}")

        # 2. Tavily Search (If mode is smart AND TMDB failed, OR if mode is tavily_only)
        if not candidate and mode in ["smart", "tavily_only"] and self.tavily_search:
            self._log(f"🔍 Trying Tavily Search for ID: '{query}' ...")
            
            for m_type in search_types:
                tavily_id = self.tavily_search.search_tmdb_id(query, m_type, year=target_year, verbose=self.verbose)
                if tavily_id:
                    verification = self._verify_external_candidate(query, target_year, m_type, tavily_id)
                    match_explanation = {
                        "provider": "tavily",
                        "confidence": verification.get("confidence", "none"),
                        "reason": verification.get("reason", "external_low_confidence"),
                        "score": round(verification.get("score", 0.0), 4),
                        "token_overlap": round(verification.get("token_overlap", 0.0), 4),
                        "target_year": target_year,
                        "external_id": tavily_id,
                        "selected_title": (verification.get("candidate") or {}).get("name") or (verification.get("candidate") or {}).get("title"),
                        "matched_title": verification.get("matched_title"),
                        "matched_field": verification.get("matched_field"),
                        "candidates": self._summarize_candidates(
                            [verification.get("candidate", {})],
                            target_year=target_year,
                            selected_id=tavily_id if verification.get("accepted") else None,
                        ) if verification.get("candidate") else [],
                    }
                    if verification.get("accepted"):
                        candidate = verification.get("candidate") or {"id": tavily_id, "media_type": m_type}
                        candidate["media_type"] = m_type
                        match_explanation["selected_id"] = tavily_id
                        self._log(f"   ✅ Tavily Found Verified ID: {tavily_id} (Type: {m_type}, Score: {verification.get('score', 0.0):.2f})")
                        break
                    self._log(f"   ⚠️ Tavily ID {tavily_id} rejected ({verification.get('reason')}, score={verification.get('score', 0.0):.2f})")
        
        return {"selected": candidate, "match": match_explanation}

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
        season_nfos = {}
        
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
            
            # Generate season NFOs
            seasons = source_data.get("seasons", [])
            for s_data in seasons:
                s_num = s_data.get("season_number", 0)
                if s_num > 0:
                     try:
                         s_nfo = self.mapper.map_to_season_nfo(s_data, normalized)
                         s_xml = NfoRenderer.render_season_nfo(s_nfo)
                         season_nfos[s_num] = s_xml
                     except: pass
            
        return {"data": nfo_obj.model_dump(), "xml": xml, "episode_nfos": episode_nfos, "season_nfos": season_nfos}

    def _step_write_output(self, normalized: Dict, nfo_data: Dict, source_data: Dict, input_data: Dict) -> Dict:
        """Step 7: Write NFO and structure."""
        output_dir = input_data.get("output_dir") or "./output"
        media_type = normalized.get("media_type")
        title = normalized.get("title")
        year = normalized.get("year")
        
        # Create Directory
        planned_media_dir = self._planned_media_directory(output_dir, title, year, media_type)
        media_dir_existed = os.path.exists(planned_media_dir)
        media_dir = FileSystemManager.create_media_directory(output_dir, title, year, media_type, inplace=self.inplace)
        self._record_created_dir(media_dir, media_dir_existed)
        
        # Write Main NFO
        nfo_filename = f"{title} ({year}).nfo" if media_type == "movie" else "tvshow.nfo"
        self._write_manifested_nfo(media_dir, nfo_filename, nfo_data["xml"], kind="main_nfo")
        
        # Handle Seasons/Episodes NFO
        if media_type == "tv":
            episodes = source_data.get("translated_episodes", [])
            for ep in episodes:
                s_num = ep.get("season_number", 0)
                e_num = ep.get("episode_number", 0)
                if s_num == 0: continue
                
                
                planned_s_dir = os.path.join(media_dir, f"Season {s_num:02d}")
                s_dir_existed = os.path.exists(planned_s_dir)
                s_dir = FileSystemManager.create_season_directory(media_dir, s_num)
                self._record_created_dir(s_dir, s_dir_existed)
                
                # Season NFO
                # Write season.nfo into the season folder if we have it
                s_xml = nfo_data.get("season_nfos", {}).get(s_num)
                if s_xml:
                    self._write_manifested_nfo(s_dir, "season.nfo", s_xml, kind="season_nfo")

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
                self._write_manifested_nfo(s_dir, f"{base_name}.nfo", ep_xml, kind="episode_nfo")

        return {"media_dir": media_dir}

    def _planned_media_directory(self, output_dir: str, title: str, year: int, media_type: str) -> str:
        if self.inplace:
            return output_dir
        safe_title = re.sub(r'[\\/:"*?<>|]', '', title or "").strip()
        return os.path.join(output_dir, "Movies" if media_type == "movie" else "TV", f"{safe_title} ({year})")

    def _record_created_dir(self, directory: str, existed_before: bool) -> None:
        if self.manifest and not existed_before:
            self.manifest.record("create_dir", None, directory, extra={"kind": "pipeline_output"})

    def _write_manifested_nfo(self, directory: str, filename: str, content: str, kind: str) -> str:
        path = os.path.join(directory, filename)
        existed_before = os.path.exists(path)
        backup_path = self.manifest.backup_file(path) if self.manifest and existed_before else None
        written_path = FileSystemManager.write_nfo_file(directory, filename, content)
        if self.manifest:
            extra = {"kind": kind}
            if backup_path:
                extra["backup_path"] = str(backup_path)
            self.manifest.record(
                "overwrite_file" if existed_before else "create_file",
                None,
                written_path,
                extra=extra,
            )
        return written_path

    def _summarize_artwork_downloads(self, downloaded_images: Dict[str, Any]) -> Dict[str, Any]:
        files = {
            key: value
            for key, value in (downloaded_images or {}).items()
            if isinstance(value, list)
        }
        counts = {key: len(value) for key, value in files.items()}
        total = sum(counts.values())
        core_keys = ["poster", "fanart", "banner", "logo", "clearart"]
        missing_core = [key for key in core_keys if counts.get(key, 0) == 0]
        return {
            "status": "downloaded" if total else "empty",
            "total": total,
            "counts": counts,
            "files": files,
            "missing_core": missing_core,
        }

    def _step_download_images(self, normalized: Dict, media_dir: str, input_data: Dict) -> Dict[str, Any]:
        """Step 8: Download."""
        tmdb_id = normalized.get("tmdb_id")
        media_type = normalized.get("media_type")
        if not tmdb_id or not media_type:
            return {"status": "skipped", "reason": "missing_tmdb_id_or_media_type"}
        if not self.artwork:
            return {"status": "skipped", "reason": "artwork_downloader_unavailable"}

        self._log("🖼️ Downloading images...", verbose_only=True)
        try:
            downloaded_images = self.artwork.download_all_images(
                media_type, tmdb_id, media_dir, 
                verbose=self.verbose, 
                extra_images=input_data.get("extra_images", False),
                image_limits=self.config.get("output", {}).get("image_limit", {}),
                overwrite=input_data.get("overwrite_images", False)
            )
        except Exception as exc:
            return {"status": "failed", "error": str(exc), "total": 0, "counts": {}, "files": {}, "missing_core": []}

        return self._summarize_artwork_downloads(downloaded_images)
