from typing import List, Dict, Optional
from pydantic import BaseModel


class MovieNfo(BaseModel):
    title: str
    originaltitle: Optional[str]
    year: int
    premiered: Optional[str]
    plot: Optional[str]
    tagline: Optional[str]
    runtime: Optional[int]
    rating: Optional[float]
    votes: Optional[int]
    genre: List[str]
    country: List[str]
    studio: List[str]
    credits: List[str]
    director: List[str]
    actor: List[Dict]  # [{"name":"希里安·墨菲","role":"奥本海默","originalname":"Cillian Murphy","thumb":"images/actors/cillian_murphy.jpg"}]
    thumb: str
    fanart: str
    tags: List[str]  # TMDB keywords/tags
    tmdb_id: Optional[int] = None  # TMDB ID for uniqueid


class TvShowNfo(BaseModel):
    title: str
    originaltitle: Optional[str]
    year: int
    premiered: Optional[str]
    plot: Optional[str]
    tagline: Optional[str]
    runtime: Optional[int]
    rating: Optional[float]
    votes: Optional[int]
    genre: List[str]
    country: List[str]
    studio: List[str]
    credits: List[str]
    director: List[str]
    actor: List[Dict]  # [{"name":"希里安·墨菲","role":"奥本海默","originalname":"Cillian Murphy","thumb":"images/actors/cillian_murphy.jpg"}]
    thumb: str
    fanart: str
    tags: List[str]  # TMDB keywords/tags
    network: Optional[str] = None  # TV network
    networks: List[str] = []  # All TV networks
    status: Optional[str] = None  # TV show status (Ended, Returning Series, etc.)
    homepage: Optional[str] = None  # Official website
    tmdb_id: Optional[int] = None  # TMDB ID for uniqueid


class EpisodeNfo(BaseModel):
    title: str
    originaltitle: Optional[str]
    sorttitle: Optional[str]
    year: int
    premiered: Optional[str]
    runtime: Optional[int]
    plot: Optional[str]
    outline: Optional[str]
    rating: Optional[float]
    votes: Optional[int]
    mpaa: Optional[str]
    genre: List[str]
    country: List[str]
    studio: List[str]
    label: Optional[str]
    credits: List[str]
    director: List[str]
    actor: List[Dict]  # [{"name":"希里安·墨菲","role":"奥本海默","originalname":"Cillian Murphy","thumb":"images/actors/cillian_murphy.jpg"}]
    set: Optional[Dict]  # {"name": "OVA 初恋時間。", "overview": "..."}
    tags: List[str]  # Additional tags
    thumb: str
    fanart: str
    num: Optional[str]  # Product number
    website: Optional[str]  # Official website
    lockedfields: Optional[str] = "Name"  # Lock the episode name field
