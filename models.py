from dataclasses import dataclass, field


@dataclass
class Chunk:
    text: str
    source: str
    section: str
    chunk_index: int = 0
    tags: list[str] = field(default_factory=list)
