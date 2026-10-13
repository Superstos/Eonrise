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
    # True only when a paper wrote this limitation in a sentence. A title carrying the
    # word "failure" was being quoted in the brief as if the authors had stated a limit.
    stated_limitation: bool = False
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
    gap_queries: list[str] = field(default_factory=list)
    new_on_topic: int = 0
    on_topic_papers: int = 0
    def to_dict(self) -> dict[str, Any]: return asdict(self)


# Run outcomes. `usable` sits between: every gap that could be repaired was searched,
# at least 4 of 5 relations grounded, one may remain honestly empty.
STATUSES = ("ready", "usable", "partial", "failed")

UP = "up"
DOWN = "down"
SIDEWAYS = "sideways"
DIRECTIONS = (UP, DOWN, SIDEWAYS)

@dataclass
class SearchSettings:
    """Limits and weights for one search from one root topic."""
    name: str = "default"
    max_nodes: int = 400
    max_depth: int = 4
    max_rounds: int = 6
    up_weight: float = 0.5
    down_weight: float = 1.0
    sideways_weight: float = 1.0
    support_threshold: int = 2
    decay: float = 0.6
    per_direction_cap: int | None = None  # None = unbounded
    def direction_weight(self, direction: str) -> float:
        return {
            UP: self.up_weight,
            DOWN: self.down_weight,
            SIDEWAYS: self.sideways_weight,
        }.get(direction, 1.0)
    def to_dict(self) -> dict[str, Any]: return asdict(self)
    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SearchSettings":
        allowed = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in raw.items() if k in allowed})

@dataclass
class ConceptNode:
    node_id: str
    label: str
    direction: str = "root"  # root | up | down | sideways
    depth: int = 0
    weight: float = 1.0
    paper_ids: list[str] = field(default_factory=list)
    parent_id: str = ""
    query: str = ""
    support: int = 0
    def to_dict(self) -> dict[str, Any]: return asdict(self)
