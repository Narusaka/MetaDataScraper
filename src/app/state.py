from typing import Dict, Any
from pydantic import BaseModel


class GraphState(BaseModel):
    input: Dict[str, Any]
    search: Dict[str, Any]
    source_data: Dict[str, Any]
    normalized: Dict[str, Any]
    artwork: Dict[str, Any]
    nfo: Dict[str, Any]
    output: Dict[str, Any]
    errors: Dict[str, Any]
    inplace: bool = False  # In-place mode flag
