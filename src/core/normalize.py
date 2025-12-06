from typing import Dict, Any, List, Optional
from .schema_internal import InternalSchema


class DataNormalizer:
    @staticmethod
    def normalize_tmdb_movie(data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize TMDB movie data to internal schema format."""
        normalized = {
            "media_type": "movie",
            "tmdb_id": data.get("id"),
            "title": data.get("title", ""),
            "original_title": data.get("original_title"),
            "year": int(data.get("release_date", "0000-00-00")[:4]) if data.get("release_date") else 0,
            "plot": data.get("overview"),
            "tagline": data.get("tagline"),
            "runtime": data.get("runtime"),
            "release_date": data.get("release_date"),
            "rating": data.get("vote_average"),
            "rating_count": data.get("vote_count"),
            "genres": [genre["name"] for genre in data.get("genres", [])],
            "countries": [country["name"] for country in data.get("production_countries", [])],
            "languages": [lang["english_name"] for lang in data.get("spoken_languages", [])],
            "studios": [studio["name"] for studio in data.get("production_companies", [])],
            "cast": [],
            "directors": [],
            "writers": [],
            "images": {}
        }

        # Check if the returned data is already in Chinese
        import re
        title = data.get("title", "")
        overview = data.get("overview", "")

        # If title contains Chinese characters, assume it's already Chinese
        if re.search(r'[\u4e00-\u9fff]', title):
            normalized["title_zh"] = title
        if re.search(r'[\u4e00-\u9fff]', overview):
            normalized["plot_zh"] = overview

        # Extract additional Chinese translations if available
        if "translations" in data:
            for translation in data["translations"].get("translations", []):
                if translation["iso_639_1"] == "zh":
                    normalized["title_zh"] = translation["data"].get("title")
                    normalized["plot_zh"] = translation["data"].get("overview")
                    break

        return normalized

    @staticmethod
    def normalize_tmdb_tv(data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize TMDB TV show data to internal schema format."""
        # Extract network information
        networks = data.get("networks", [])
        network_name = networks[0].get("name", "") if networks else ""

        # Extract all networks
        all_networks = [network.get("name", "") for network in networks if network.get("name")]

        normalized = {
            "media_type": "tv",
            "tmdb_id": data.get("id"),
            "title": data.get("name", ""),
            "original_title": data.get("original_name"),
            "year": int(data.get("first_air_date", "0000-00-00")[:4]) if data.get("first_air_date") else 0,
            "plot": data.get("overview"),
            "tagline": data.get("tagline"),
            "runtime": data.get("episode_run_time", [0])[0] if data.get("episode_run_time") else None,
            "release_date": data.get("first_air_date"),
            "rating": data.get("vote_average"),
            "rating_count": data.get("vote_count"),
            "genres": [genre["name"] for genre in data.get("genres", [])],
            "countries": data.get("origin_country", []),
            "languages": [lang for lang in data.get("languages", [])],
            "studios": [studio["name"] for studio in data.get("production_companies", [])],
            "networks": all_networks,  # All networks, not just the first one
            "network": network_name,  # Keep backward compatibility
            "status": data.get("status", ""),
            "homepage": data.get("homepage", ""),
            "cast": [],
            "directors": [],
            "writers": [],
            "images": {},
            "seasons": data.get("seasons", []),
            "episodes": []
        }

        # Check if the returned data is already in Chinese
        import re
        title = data.get("name", "")
        overview = data.get("overview", "")

        # If title contains Chinese characters, assume it's already Chinese
        if re.search(r'[\u4e00-\u9fff]', title):
            normalized["title_zh"] = title
        if re.search(r'[\u4e00-\u9fff]', overview):
            normalized["plot_zh"] = overview

        # Extract additional Chinese translations if available
        if "translations" in data:
            for translation in data["translations"].get("translations", []):
                if translation["iso_639_1"] == "zh":
                    normalized["title_zh"] = translation["data"].get("name")
                    normalized["plot_zh"] = translation["data"].get("overview")
                    break

        return normalized

    @staticmethod
    def enrich_with_credits(normalized: Dict[str, Any], credits_data: Dict[str, Any]) -> Dict[str, Any]:
        """Enrich normalized data with credits information."""
        cast = []
        for person in credits_data.get("cast", [])[:10]:  # Top 10 cast members
            cast.append({
                "name_en": person.get("name", ""),
                "name_zh": None,  # Will be filled by OMDB
                "role": person.get("character", ""),
                "original_name": person.get("original_name", ""),
                "profile_path": person.get("profile_path", ""),
                "popularity": person.get("popularity", 0)
            })

        normalized["cast"] = cast

        # Extract directors and writers from crew
        directors = set()
        writers = set()

        for person in credits_data.get("crew", []):
            job = person.get("job", "")
            department = person.get("department", "")

            # Check by job title or department
            if job == "Director" or department == "Directing":
                directors.add(person.get("name", ""))
            elif job in ["Writer", "Screenplay", "Story", "Series Composition"] or department == "Writing":
                writers.add(person.get("name", ""))

        # Also check episode-level crew for TV shows
        if normalized.get("media_type") == "tv" and normalized.get("episodes"):
            for episode in normalized["episodes"]:
                for person in episode.get("crew", []):
                    job = person.get("job", "")
                    department = person.get("department", "")

                    if job == "Director" or department == "Directing":
                        directors.add(person.get("name", ""))
                    elif job in ["Writer", "Screenplay", "Story"] or department == "Writing":
                        writers.add(person.get("name", ""))

        normalized["directors"] = list(directors)  # Convert set to list
        normalized["writers"] = list(writers)

        return normalized

    @staticmethod
    def enrich_with_keywords(normalized: Dict[str, Any], keywords_data: Dict[str, Any], translate: bool = False) -> Dict[str, Any]:
        """Enrich normalized data with keywords information."""
        # Handle different API response formats
        # Movie API returns: {"keywords": [...]}
        # TV API returns: {"results": [...]}
        keywords = keywords_data.get("keywords", []) or keywords_data.get("results", [])
        if keywords:
            # Extract keyword names
            keyword_names = [kw.get("name", "") for kw in keywords if kw.get("name")]
            normalized["keywords_en"] = keyword_names  # Always keep English keywords

            # Use translated keywords if available and translation is enabled, otherwise use English
            if translate and normalized.get("keywords_zh"):
                normalized["keywords"] = normalized["keywords_zh"]
            else:
                normalized["keywords"] = keyword_names

        return normalized

    @staticmethod
    def enrich_with_omdb(normalized: Dict[str, Any], omdb_data: Dict[str, Any]) -> Dict[str, Any]:
        """Enrich normalized data with OMDB information."""
        if "imdbID" in omdb_data:
            normalized["OMDB_id"] = omdb_data["imdbID"]

        # Update cast with Chinese names if available
        if "Actors" in omdb_data and normalized.get("cast"):
            omdb_actors = [actor.strip() for actor in omdb_data["Actors"].split(",")]
            for i, omdb_actor in enumerate(omdb_actors):
                if i < len(normalized["cast"]):
                    # Try to match by similarity or just assign sequentially
                    normalized["cast"][i]["name_zh"] = omdb_actor

        # Update other fields if better data available
        if "Plot" in omdb_data and not normalized.get("plot_zh"):
            normalized["plot_zh"] = omdb_data["Plot"]
        if "Genre" in omdb_data:
            omdb_genres = [g.strip() for g in omdb_data["Genre"].split(",")]
            normalized["genres_zh"] = omdb_genres
        if "Director" in omdb_data:
            omdb_directors = [d.strip() for d in omdb_data["Director"].split(",")]
            normalized["directors"] = list(set(normalized.get("directors", []) + omdb_directors))
        if "Writer" in omdb_data:
            omdb_writers = [w.strip() for w in omdb_data["Writer"].split(",")]
            normalized["writers"] = list(set(normalized.get("writers", []) + omdb_writers))

        return normalized
