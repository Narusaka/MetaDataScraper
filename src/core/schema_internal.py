from typing import List, Dict, Optional, Literal
from pydantic import BaseModel


class InternalSchema(BaseModel):
    media_type: Literal["movie", "tv"]
    tmdb_id: int
    OMDB_id: Optional[str]
    title: str
    title_zh: Optional[str]
    original_title: Optional[str]
    year: int
    plot: Optional[str]
    plot_zh: Optional[str]
    tagline: Optional[str]
    tagline_zh: Optional[str]
    runtime: Optional[int]
    release_date: Optional[str]
    rating: Optional[float]
    rating_count: Optional[int]
    genres: List[str]
    genres_zh: List[str]
    countries: List[str]
    languages: List[str]
    studios: List[str]
    cast: List[Dict]   # [{"name_en": "Cillian Murphy","name_zh": "希里安·墨菲","role":"Oppenheimer"}]
    directors: List[str]
    writers: List[str]
    images: Dict[str, List[str]]  # {"poster": [...], "banner": [...], "stills": [...]}
    seasons: Optional[List[Dict]]
    episodes: Optional[List[Dict]]
