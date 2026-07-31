from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

@dataclass
class Paper:
    paper_id: str
    title: str
    abstract: str = ""
    url: str = ""
    doi: str = ""
    year: int | None = None
    cited_by_count: int = 0
    provider: str = "unknown"
    keywords: list[str] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    topic_path: list[str] = field(default_factory=list)
    venue: str = ""
    found_by: list[str] = field(default_factory=list)
    def to_dict(self) -> dict[str, Any]: return asdict(self)
    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Paper":
        allowed = {f.name for f in cls.__dataclass_fields__.values()}
        data = {k: v for k, v in raw.items() if k in allowed}
        path = list(data.get("topic_path") or [])
        if path and not data.get("fields") and len(path) > 1:
            data["fields"] = path[:-1]; data["topic_path"] = [path[-1]]
        return cls(**data)

@dataclass
class Term:
    text: str
    relation: str
    score: float
    confidence: str
    paper_ids: list[str]
    providers: list[str]
    queries: list[str]
    examples: list[str]
    @property
    def support(self) -> int: return len(self.paper_ids)
    def to_dict(self) -> dict[str, Any]:
        data = asdict(self); data["support"] = self.support; return data

@dataclass
class RoundStats:
    round_number: int
    queries: list[str]
    new_papers: int
    total_papers: int
    new_grounded_terms: int
    grounded_terms: int
    gaps: list[str]
    stop_checks: dict[str, bool]
    def to_dict(self) -> dict[str, Any]: return asdict(self)
