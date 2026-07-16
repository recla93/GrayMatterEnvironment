from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Chunk:
    text: str
    source: str
    section: str
    chunk_index: int = 0
    tags: list[str] = field(default_factory=list)


@dataclass
class QueryResult:
    text: str
    source: str
    section: str
    score: float
    chunk_index: int = 0
