"""Which source to call next, and which sources are still worth calling.

Two facts the router had nowhere to put:

- A rate limit outlives the process. OpenAlex answered `Retry-After: 30746` — about eight
  hours — and the next run still spent a call finding that out again.
- Sources are not interchangeable. Measured on one query, 20 results each: Europe PMC
  returned 20 abstracts and 18 keyword lists, Crossref 16% abstracts and no subjects. When
  the run is missing `failure_mode`, which is read out of abstract sentences, the source
  that carries abstracts should be asked first.

No network, no engine imports: states go in, an order comes out.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

# What each source actually supplied when measured, not what its documentation claims.
# abstracts / subjects are the share of returned papers carrying each, 0.0-1.0.
CAPABILITIES: dict[str, dict[str, float]] = {
    "corpus": {"abstracts": 0.5, "subjects": 0.3, "cost": 0.0},
    "europepmc": {"abstracts": 1.0, "subjects": 0.35, "cost": 1.0},
    "core": {"abstracts": 1.0, "subjects": 0.2, "cost": 1.0},
    "doaj": {"abstracts": 1.0, "subjects": 1.0, "cost": 1.0},
    "openalex": {"abstracts": 0.9, "subjects": 0.9, "cost": 10.0},
    "semanticscholar": {"abstracts": 0.8, "subjects": 0.8, "cost": 1.0},
    "crossref": {"abstracts": 0.16, "subjects": 0.0, "cost": 1.0},
}
# Gaps read out of abstract sentences vs gaps read off subject labels.
ABSTRACT_GAPS = {"failure_mode", "mechanism", "measurement", "method"}
SUBJECT_GAPS = {"neighbor_field"}


@dataclass
class ProviderState:
    name: str
    blocked_until: float = 0.0   # epoch seconds; 0 means available
    reason: str = ""
    failures: int = 0
    successes: int = 0

    def available(self, now: float) -> bool:
        return now >= self.blocked_until


class ProviderStates:
    """Provider availability that survives the process, so one 429 is paid once."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self.states: dict[str, ProviderState] = {}
        if self.path and self.path.exists():
            try:
                for name, row in json.loads(self.path.read_text(encoding="utf-8")).items():
                    self.states[name] = ProviderState(**row)
            except (json.JSONDecodeError, TypeError, OSError):
                self.states = {}  # a corrupt file must not stop a run

    def get(self, name: str) -> ProviderState:
        return self.states.setdefault(name, ProviderState(name))

    def block(self, name: str, seconds: float, reason: str = "", now: float | None = None) -> None:
        state = self.get(name)
        state.blocked_until = (now if now is not None else time.time()) + max(0.0, seconds)
        state.reason = reason

    def observe(self, name: str, ok: bool) -> None:
        state = self.get(name)
        if ok: state.successes += 1
        else: state.failures += 1

    def available(self, names: list[str], now: float | None = None) -> list[str]:
        moment = now if now is not None else time.time()
        return [n for n in names if self.get(n).available(moment)]

    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({n: asdict(s) for n, s in self.states.items()},
                                        indent=1), encoding="utf-8")


def order_for(names: list[str], gaps: list[str], states: ProviderStates | None = None,
              now: float | None = None) -> list[str]:
    """Rank available sources for what this round is missing. Cheap and rich go first."""
    usable = states.available(names, now) if states else list(names)
    wants_abstracts = bool(set(gaps) & ABSTRACT_GAPS)
    wants_subjects = bool(set(gaps) & SUBJECT_GAPS)

    def rank(name: str) -> tuple:
        caps = CAPABILITIES.get(name, {"abstracts": 0.3, "subjects": 0.3, "cost": 1.0})
        score = 0.0
        if wants_abstracts: score += caps["abstracts"]
        if wants_subjects: score += caps["subjects"]
        if not gaps: score += 0.5 * (caps["abstracts"] + caps["subjects"])
        return (-score, caps["cost"], names.index(name))

    return sorted(usable, key=rank)
