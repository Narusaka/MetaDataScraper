from typing import Dict, Any, List
from .schema_nfo import MovieNfo, TvShowNfo, EpisodeNfo


class DirectMapper:
    """Direct JSON mapping without LLM calls."""

    @staticmethod
    def map_to_movie_nfo(internal_data: Dict[str, Any]) -> MovieNfo:
        """Direct mapping from internal schema to MovieNfo."""
        return MovieNfo(
            title=internal_data.get('title_zh') or internal_data.get('title', ''),
            originaltitle=internal_data.get('original_title', ''),
            year=internal_data.get('year', 0),
            premiered=internal_data.get('release_date', ''),
            plot=internal_data.get('plot_zh') or internal_data.get('plot', ''),
            tagline=internal_data.get('tagline_zh') or internal_data.get('tagline', ''),
            runtime=internal_data.get('runtime', 0),
            rating=internal_data.get('rating', 0.0),
            votes=internal_data.get('rating_count', 0),
            genre=internal_data.get('genres_zh', internal_data.get('genres', [])),
            country=internal_data.get('countries', []),
            studio=internal_data.get('studios', []),
            credits=internal_data.get('writers', []),
            director=internal_data.get('directors', []),
            actor=DirectMapper._format_cast(internal_data.get('cast', [])),
            thumb="poster.jpg",
            fanart="fanart.jpg",
            tags=internal_data.get('keywords_zh', internal_data.get('keywords', [])),
            tmdb_id=internal_data.get('tmdb_id', None)
        )

    @staticmethod
    def map_to_tvshow_nfo(internal_data: Dict[str, Any]) -> TvShowNfo:
        """Direct mapping from internal schema to TvShowNfo."""
        return TvShowNfo(
            title=internal_data.get('title_zh') or internal_data.get('title', ''),
            originaltitle=internal_data.get('original_title', ''),
            year=internal_data.get('year', 0),
            premiered=internal_data.get('release_date', ''),
            plot=internal_data.get('plot_zh') or internal_data.get('plot', ''),
            tagline=internal_data.get('tagline_zh') or internal_data.get('tagline', ''),
            runtime=internal_data.get('runtime', 0),
            rating=internal_data.get('rating', 0.0),
            votes=internal_data.get('rating_count', 0),
            genre=internal_data.get('genres_zh', internal_data.get('genres', [])),
            country=internal_data.get('countries', []),
            studio=internal_data.get('studios', []),
            credits=internal_data.get('writers', []),
            director=internal_data.get('directors', []),
            actor=DirectMapper._format_cast(internal_data.get('cast', [])),
            thumb="poster.jpg",
            fanart="fanart.jpg",
            tags=internal_data.get('keywords_zh', internal_data.get('keywords', [])),
            network=internal_data.get('network', ''),
            networks=internal_data.get('networks', []),
            status=internal_data.get('status', ''),
            homepage=internal_data.get('homepage', ''),
            tmdb_id=internal_data.get('tmdb_id', None)
        )

    @staticmethod
    def map_to_episode_nfo(internal_data: Dict[str, Any], episode_data: Dict[str, Any], show_data: Dict[str, Any]) -> EpisodeNfo:
        """Direct mapping from internal schema to EpisodeNfo."""
        season_number = episode_data.get("season_number", 0)
        episode_number = episode_data.get("episode_number", 0)
        show_title = show_data.get("title_zh") or show_data.get("title", "Unknown Show")

        # Use the episode name from TMDB, prefer translated Chinese version
        episode_name = episode_data.get("name_zh", episode_data.get("name", f"Episode {episode_number}"))

        # Get basic episode info
        year = episode_data.get("air_date", "")[:4] if episode_data.get("air_date") else show_data.get("year", 2024)
        premiered = episode_data.get("air_date", "")
        runtime = episode_data.get("runtime", show_data.get("episode_runtime", [25])[0] if show_data.get("episode_runtime") else 25)
        # Use translated plot if available
        plot = episode_data.get("overview_zh", episode_data.get("overview", ""))
        rating = episode_data.get("vote_average", 0.0)
        votes = episode_data.get("vote_count", 0)

        # Get show-level information
        genres = show_data.get('genres_zh', show_data.get('genres', []))
        countries = show_data.get('countries', [])
        studios = show_data.get('studios', [])

        # Extract episode-level crew information
        episode_directors = []
        episode_writers = []

        # Check episode-level crew first
        if episode_data.get("crew"):
            for crew_member in episode_data["crew"]:
                job = crew_member.get("job", "")
                department = crew_member.get("department", "")
                name = crew_member.get("name", "")

                if job == "Director" or department == "Directing":
                    episode_directors.append(name)
                elif job in ["Writer", "Screenplay", "Story"] or department == "Writing":
                    episode_writers.append(name)

        # Fall back to show-level crew if episode doesn't have specific crew
        if not episode_directors:
            episode_directors = show_data.get('directors', [])
        if not episode_writers:
            episode_writers = show_data.get('writers', [])

        cast = DirectMapper._format_cast(show_data.get('cast', []))

        # Generate correct episode image filenames (Emby standard)
        show_title_for_filename = show_data.get("title_zh") or show_data.get("title", "Unknown Show")
        # Use -thumb.jpg for episode thumbs (Emby standard)
        episode_thumb_filename = f"{show_title_for_filename} - S{season_number:02d}E{episode_number:02d} - {episode_name}-thumb.jpg"
        # Use episode-specific fanart with fallback to main fanart
        episode_fanart_filename = f"{show_title_for_filename} - S{season_number:02d}E{episode_number:02d} - {episode_name}-fanart.jpg"

        # Create episode NFO without hardcoded adult content
        episode_nfo = EpisodeNfo(
            title=episode_name,
            originaltitle=episode_data.get('name', ''),
            sorttitle=episode_name,  # Use only episode name for sorttitle
            year=year,
            premiered=premiered,
            runtime=runtime,
            plot=plot,
            outline=plot,  # Use plot as outline if no specific outline
            rating=rating,
            votes=votes,
            mpaa="",  # Empty MPAA rating
            genre=genres,
            country=countries,
            studio=studios,
            label="",  # Empty label
            credits=episode_writers,
            director=episode_directors,
            actor=cast,
            set=None,  # No set by default
            tags=[],  # Empty tags list by default
            thumb=episode_thumb_filename,
            fanart=episode_fanart_filename,
            num="",  # Empty product number
            website=""  # Empty website
        )

        # Only add set information for TV shows with multiple episodes/seasons
        if show_data.get("number_of_seasons", 1) > 1 or show_data.get("number_of_episodes", 1) > 1:
            episode_nfo.set = {
                "name": show_title,
                "overview": show_data.get("overview", "")
            }

        # Add tags from show data keywords (use translated Chinese tags if available)
        episode_nfo.tags = show_data.get("keywords_zh", show_data.get("keywords", []))

        return episode_nfo

    @staticmethod
    def _format_cast(cast_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Format cast list for NFO with extended information."""
        formatted_cast = []
        for actor in cast_list[:10]:  # Limit to top 10 actors
            # Format name with both Chinese and English if available
            name_zh = actor.get('name_zh')
            name_en = actor.get('name_en', '')
            original_name = actor.get('original_name', '')

            # Create bilingual name format
            if name_zh and name_zh != name_en:
                display_name = f"{name_zh} / {name_en}"
            else:
                display_name = name_en

            # Format role with both Chinese and English if available
            role = actor.get('role', '')

            actor_info = {
                "name": display_name,
                "role": role
            }

            # Add original name if different from display name
            if original_name and original_name != name_en and original_name != name_zh:
                actor_info["originalname"] = original_name

            # Add profile path for actor image (Emby standard: root ./actors/ directory)
            profile_path = actor.get('profile_path', '')
            if profile_path:
                # Convert TMDB path to local path (match artwork.py naming convention)
                actor_name_clean = "".join(c for c in name_en if c.isalnum() or c in ' _-').strip()
                actor_name_clean = actor_name_clean.replace(' ', '_')  # Use underscores like artwork.py
                if not actor_name_clean:
                    actor_name_clean = "unknown"
                # Use ./actors/ path for Emby standard structure
                actor_info["thumb"] = f"./actors/{actor_name_clean}.jpg"

            formatted_cast.append(actor_info)
        return formatted_cast


# Backward compatibility alias
LLMMapper = DirectMapper
