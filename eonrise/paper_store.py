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


def _search_words(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) > 2 and t not in STOP}


def _key(paper: Paper) -> str:
    return (paper.doi or paper.title or paper.paper_id or "").strip().lower()


def _read_papers(path):
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield Paper.from_dict(json.loads(line))
        except (json.JSONDecodeError, TypeError, KeyError):
            continue  # a half-written line must not lose the rest of the store


def _fill_field(held, paper, name):
    if not getattr(held, name) and getattr(paper, name):
        setattr(held, name, getattr(paper, name))
        return True
    return False


def _merge_lists(held, paper):
    changed = False
    for name in ("keywords", "fields", "topic_path", "found_by"):
        before = len(getattr(held, name))
        setattr(held, name, list(dict.fromkeys([*getattr(held, name), *getattr(paper, name)])))
        changed = changed or len(getattr(held, name)) > before
    return changed


def _enrich_paper(held, paper):
    changed = _fill_field(held, paper, "abstract")
    lists_changed = _merge_lists(held, paper)
    changed = changed or lists_changed
    venue_changed = _fill_field(held, paper, "venue")
    changed = changed or venue_changed
    if paper.cited_by_count > held.cited_by_count:
        held.cited_by_count = paper.cited_by_count
        changed = True
    return changed


def _count_filled(papers, name):
    return sum(1 for paper in papers if getattr(paper, name))


def _providers(papers):
    return sorted({paper.provider for paper in papers if paper.provider})


class PaperStore:
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
        for paper in _read_papers(self.path):
            key = _key(paper)
            if key:
                self._merge(key, paper)
        return self._papers

    def _merge(self, key: str, paper: Paper) -> bool:
        held = self._papers.get(key)
        if held is None:
            self._papers[key] = paper
            return True
        # The same paper from two sources: keep whichever fields are actually filled.
        return _enrich_paper(held, paper)

    def add(self, papers: list[Paper]) -> int:
        """Append papers that are new or newly enriched. Returns how many lines were written."""
        self.load()
        fresh: list[Paper] = []
        for paper in papers:
            key = _key(paper)
            if not key:
                continue
            if self._merge(key, paper):
                fresh.append(self._papers[key])
        if not fresh:
            return 0
        self._append(fresh)
        return len(fresh)

    def _append(self, papers):
        with self.path.open("a", encoding="utf-8") as handle:
            for paper in papers:
                handle.write(json.dumps(paper.to_dict(), ensure_ascii=False) + "\n")

    def search(self, query: str, limit: int = 20) -> list[Paper]:
        """Rank stored papers against the query. A stored paper costs no API credit."""
        wanted = _search_words(query)
        if not wanted:
            return []
        ranked: list[tuple[float, Paper]] = []
        for paper in self.load().values():
            found = _search_words(f"{paper.title} {paper.abstract} {' '.join(paper.keywords)} "
                           f"{' '.join(paper.fields)} {' '.join(paper.topic_path)}")
            hits = wanted & found
            if len(hits) < min(2, len(wanted)):
                continue
            clone = _search_clone(paper, query)
            ranked.append((len(hits) / len(wanted) + min(paper.cited_by_count, 200) / 2000, clone))
        ranked.sort(key=lambda row: row[0], reverse=True)
        return [paper for _, paper in ranked[:limit]]

    def stats(self) -> dict:
        papers = self.load()
        return {"papers": len(papers),
                "with_abstract": _count_filled(papers.values(), "abstract"),
                "with_keywords": _count_filled(papers.values(), "keywords"),
                "providers": _providers(papers.values())}


def _search_clone(paper, query):
    clone = Paper.from_dict(paper.to_dict())
    clone.found_by = list(dict.fromkeys([*clone.found_by, query]))
    return clone
