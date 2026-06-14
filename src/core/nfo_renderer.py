import xml.etree.ElementTree as ET
from typing import Any, Optional
from xml.dom import minidom

from .schema_nfo import EpisodeNfo, MovieNfo, SeasonNfo, TvShowNfo


class NfoRenderer:
    """Render a conservative NFO dialect shared by Jellyfin, Emby, and Kodi."""

    DEFAULT_POLICY = {
        "profile": "universal",
        "targets": ["jellyfin", "emby", "kodi"],
        "include_uniqueid": True,
        "include_legacy_tmdbid": True,
        "episode_sidecars": "present_only",
    }

    @classmethod
    def normalize_policy(cls, policy: Optional[dict] = None) -> dict:
        normalized = dict(cls.DEFAULT_POLICY)
        if isinstance(policy, dict):
            normalized.update({key: value for key, value in policy.items() if key in normalized})
        targets = normalized.get("targets")
        if not isinstance(targets, list):
            targets = [targets] if targets else []
        normalized["targets"] = [
            str(target).strip().lower()
            for target in targets
            if str(target).strip().lower() in {"jellyfin", "emby", "kodi"}
        ] or list(cls.DEFAULT_POLICY["targets"])
        normalized["profile"] = "universal"
        normalized["include_uniqueid"] = bool(normalized["include_uniqueid"])
        normalized["include_legacy_tmdbid"] = bool(normalized["include_legacy_tmdbid"])
        normalized["episode_sidecars"] = "present_only"
        return normalized

    @staticmethod
    def _element(parent: ET.Element, tag: str, value: Any = None, **attributes: str) -> ET.Element:
        element = ET.SubElement(parent, tag, attributes)
        if value is not None:
            element.text = str(value)
        return element

    @classmethod
    def _list(cls, parent: ET.Element, tag: str, values: list) -> None:
        for value in values or []:
            if value not in (None, ""):
                cls._element(parent, tag, value)

    @classmethod
    def _identity(cls, root: ET.Element, tmdb_id: Optional[int], policy: dict) -> None:
        if not tmdb_id:
            return
        if policy["include_legacy_tmdbid"]:
            cls._element(root, "tmdbid", tmdb_id)
        if policy["include_uniqueid"]:
            cls._element(root, "uniqueid", tmdb_id, type="tmdb", default="true")

    @classmethod
    def _actors(cls, root: ET.Element, actors: list, relative_prefix: str = "") -> None:
        for actor in actors or []:
            if not isinstance(actor, dict) or not actor.get("name"):
                continue
            actor_element = cls._element(root, "actor")
            cls._element(actor_element, "name", actor["name"])
            if actor.get("role"):
                cls._element(actor_element, "role", actor["role"])
            cls._element(actor_element, "type", "Actor")
            if actor.get("originalname"):
                cls._element(actor_element, "originalname", actor["originalname"])
            if actor.get("thumb"):
                cls._element(actor_element, "thumb", f"{relative_prefix}{actor['thumb']}")

    @staticmethod
    def _serialize(root: ET.Element) -> str:
        rough = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        parsed = minidom.parseString(rough)
        lines = [line for line in parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8").splitlines() if line.strip()]
        return "\n".join(lines) + "\n"

    @classmethod
    def _common(cls, root: ET.Element, nfo: Any, include_tagline: bool = False, include_title: bool = True) -> None:
        if include_title:
            cls._element(root, "title", nfo.title)
        if getattr(nfo, "originaltitle", None):
            cls._element(root, "originaltitle", nfo.originaltitle)
        if getattr(nfo, "year", 0):
            cls._element(root, "year", nfo.year)
        if getattr(nfo, "premiered", None):
            cls._element(root, "premiered", nfo.premiered)
        if getattr(nfo, "plot", None):
            cls._element(root, "plot", nfo.plot)
        if include_tagline and getattr(nfo, "tagline", None):
            cls._element(root, "tagline", nfo.tagline)
        if getattr(nfo, "runtime", None):
            cls._element(root, "runtime", nfo.runtime)
        if getattr(nfo, "rating", None):
            cls._element(root, "rating", nfo.rating)
        if getattr(nfo, "votes", None):
            cls._element(root, "votes", nfo.votes)
        cls._list(root, "genre", getattr(nfo, "genre", []))
        cls._list(root, "country", getattr(nfo, "country", []))
        cls._list(root, "studio", getattr(nfo, "studio", []))

    @classmethod
    def render_movie_nfo(cls, nfo: MovieNfo, tmdb_id: Optional[int] = None, policy: Optional[dict] = None) -> str:
        policy = cls.normalize_policy(policy)
        root = ET.Element("movie")
        cls._common(root, nfo, include_tagline=True)
        cls._identity(root, tmdb_id or nfo.tmdb_id, policy)
        if nfo.credits:
            cls._element(root, "credits", ", ".join(nfo.credits))
        cls._list(root, "director", nfo.director)
        cls._actors(root, nfo.actor)
        cls._element(root, "thumb", nfo.thumb or "poster.jpg")
        cls._element(root, "fanart", nfo.fanart or "fanart.jpg")
        cls._list(root, "tag", nfo.tags)
        return cls._serialize(root)

    @classmethod
    def render_tvshow_nfo(cls, nfo: TvShowNfo, tmdb_id: Optional[int] = None, policy: Optional[dict] = None) -> str:
        policy = cls.normalize_policy(policy)
        root = ET.Element("tvshow")
        cls._common(root, nfo, include_tagline=True)
        cls._identity(root, tmdb_id or nfo.tmdb_id, policy)
        if nfo.credits:
            cls._element(root, "credits", ", ".join(nfo.credits))
        cls._list(root, "director", nfo.director)
        cls._actors(root, nfo.actor)
        cls._list(root, "network", nfo.networks or ([nfo.network] if nfo.network else []))
        if nfo.status:
            cls._element(root, "status", nfo.status)
        if nfo.homepage:
            cls._element(root, "homepage", nfo.homepage)
        cls._element(root, "thumb", nfo.thumb or "poster.jpg")
        cls._element(root, "fanart", nfo.fanart or "fanart.jpg")
        cls._list(root, "tag", nfo.tags)
        return cls._serialize(root)

    @classmethod
    def render_season_nfo(cls, nfo: SeasonNfo, policy: Optional[dict] = None) -> str:
        policy = cls.normalize_policy(policy)
        root = ET.Element("season")
        cls._element(root, "title", nfo.title)
        if nfo.season_number:
            cls._element(root, "seasonnumber", nfo.season_number)
        cls._common(root, nfo, include_title=False)
        if nfo.outline:
            cls._element(root, "outline", nfo.outline)
        cls._identity(root, nfo.tmdb_id, policy)
        cls._element(root, "thumb", nfo.thumb)
        cls._element(root, "fanart", nfo.fanart)
        return cls._serialize(root)

    @classmethod
    def render_episode_nfo(cls, nfo: EpisodeNfo, policy: Optional[dict] = None) -> str:
        policy = cls.normalize_policy(policy)
        root = ET.Element("episodedetails")
        cls._element(root, "title", nfo.title)
        if nfo.originaltitle:
            cls._element(root, "originaltitle", nfo.originaltitle)
        if nfo.sorttitle:
            cls._element(root, "sorttitle", nfo.sorttitle)
        cls._element(root, "season", nfo.season)
        cls._element(root, "episode", nfo.episode)
        if nfo.year:
            cls._element(root, "year", nfo.year)
        if nfo.premiered:
            cls._element(root, "premiered", nfo.premiered)
            cls._element(root, "aired", nfo.premiered)
        if nfo.runtime:
            cls._element(root, "runtime", nfo.runtime)
        if nfo.plot:
            cls._element(root, "plot", nfo.plot)
        if nfo.outline:
            cls._element(root, "outline", nfo.outline)
        if nfo.rating:
            cls._element(root, "rating", nfo.rating)
        if nfo.votes:
            cls._element(root, "votes", nfo.votes)
        cls._identity(root, nfo.tmdb_id, policy)
        cls._list(root, "genre", nfo.genre)
        cls._list(root, "country", nfo.country)
        cls._list(root, "studio", nfo.studio)
        cls._list(root, "credits", nfo.credits)
        cls._list(root, "director", nfo.director)
        cls._actors(root, nfo.actor, relative_prefix="../")
        cls._list(root, "tag", nfo.tags)
        if nfo.thumb:
            cls._element(root, "thumb", nfo.thumb)
        cls._element(root, "fanart", nfo.fanart or "../fanart.jpg")
        if nfo.lockedfields:
            cls._element(root, "lockedfields", nfo.lockedfields)
        return cls._serialize(root)
