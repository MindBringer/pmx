from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class IndexRequest(BaseModel):
    source_urls: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    upsert: bool = True

class QueryRequest(BaseModel):
    query: str
    top_k: int = 5
    tags_any: Optional[List[str]] = None
    tags_all: Optional[List[str]] = None
    with_sources: bool = True
    stream: bool = False

class TagPatch(BaseModel):
    add: Optional[List[str]] = None
    remove: Optional[List[str]] = None

class QueryResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    used_tags: List[str] = Field(default_factory=list)
