"""Every paper a run has ever seen, kept on disk so later runs start rich instead of empty.

Three things compound off one store:

- **Budget.** A paper already held costs no API call, and OpenAlex now charges credits.
- **Drift.** Term co-occurrence measured over thousands of stored papers is a corpus-level
  signal; the topical gate currently has only the words in the question.
- **Cross-literature leads.** Swanson's ABC needs two large literatures gathered
  separately. One run cannot build them; a year of runs can.

Append-only JSONL, one paper per line, merged by DOI. Nothing here calls the network.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .models import Paper

STOP = {"a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "in",
        "is", "it", "of", "on", "or", "that", "the", "to", "what", "when", "which", "with"}


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) > 2 and t not in STOP}


def _key(paper: Paper) -> str:
    return (paper.doi or paper.title or paper.paper_id or "").strip().lower()


class CorpusStore:
    """A local paper store that answers searches like any other provider."""

    name = "corpus"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._papers: dict[str, Paper] = {}
        self._loaded = False

    def load(self) -> dict[str, Paper]:
        if self._loaded:
            return self._papers
        self._loaded = True
        if not self.path.exists():
            return self._papers
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                paper = Paper.from_dict(json.loads(line))
            except (json.JSONDecodeError, TypeError, KeyError):
                continue  # a half-written line must not lose the rest of the store
            key = _key(paper)
            if key:
                self._merge(key, paper)
        return self._papers

    def _merge(self, key: str, paper: Paper) -> None:
        held = self._papers.get(key)
        if held is None:
            self._papers[key] = paper
            return
        # The same paper from two sources: keep whichever fields are actually filled.
        if not held.abstract and paper.abstract:
            held.abstract = paper.abstract
        held.keywords = list(dict.fromkeys([*held.keywords, *paper.keywords]))
        held.fields = list(dict.fromkeys([*held.fields, *paper.fields]))
        held.topic_path = list(dict.fromkeys([*held.topic_path, *paper.topic_path]))
        held.found_by = list(dict.fromkeys([*held.found_by, *paper.found_by]))
        if not held.venue and paper.venue:
            held.venue = paper.venue
        if paper.cited_by_count > held.cited_by_count:
            held.cited_by_count = paper.cited_by_count

    def add(self, papers: list[Paper]) -> int:
        """Append papers that are new or newly enriched. Returns how many lines were written."""
        self.load()
        fresh: list[Paper] = []
        for paper in papers:
            key = _key(paper)
            if not key:
                continue
            before = self._papers.get(key)
            was_thin = before is None or (not before.abstract and bool(paper.abstract))
            self._merge(key, paper)
            if was_thin:
                fresh.append(self._papers[key])
        if not fresh:
            return 0
        with self.path.open("a", encoding="utf-8") as handle:
            for paper in fresh:
                handle.write(json.dumps(paper.to_dict(), ensure_ascii=False) + "\n")
        return len(fresh)

    def search(self, query: str, limit: int = 20) -> list[Paper]:
        """Rank stored papers against the query. A stored paper costs no API credit."""
        wanted = _tokens(query)
        if not wanted:
            return []
        ranked: list[tuple[float, Paper]] = []
        for paper in self.load().values():
            found = _tokens(f"{paper.title} {paper.abstract} {' '.join(paper.keywords)} "
                           f"{' '.join(paper.fields)} {' '.join(paper.topic_path)}")
            hits = wanted & found
            if len(hits) < min(2, len(wanted)):
                continue
            clone = Paper.from_dict(paper.to_dict())
            clone.found_by = list(dict.fromkeys([*clone.found_by, query]))
            ranked.append((len(hits) / len(wanted) + min(paper.cited_by_count, 200) / 2000, clone))
        ranked.sort(key=lambda row: row[0], reverse=True)
        return [paper for _, paper in ranked[:limit]]

    def stats(self) -> dict:
        papers = self.load()
        return {"papers": len(papers),
                "with_abstract": sum(1 for p in papers.values() if p.abstract),
                "with_keywords": sum(1 for p in papers.values() if p.keywords),
                "providers": sorted({p.provider for p in papers.values() if p.provider})}
