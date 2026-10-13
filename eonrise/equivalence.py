"""A small persistent graph of cross-field concept equivalences.

Different fields often use different words for nearby ideas: ``concept drift`` in one
paper, ``distribution shift`` in another. The graph remembers only relationships with
real textual evidence, then reuses them as alternate search queries.

The scope is deliberately narrow. This module does not merge concepts, rerank papers,
or relax the topical gate. It supplies extra queries; the existing engine still
decides what counts as on topic.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable, Mapping

from .evidence import (
    GENERIC_FIELDS,
    MIN_TOPICAL_CORPUS,
    GROUNDED,
    _sentences,
    concept_key,
    is_clean_label,
    is_redundant,
    normalize,
)
from .models import Paper, Term

SCHEMA_VERSION = 1
EQUIVALENT = "equivalent"
CLOSELY_RELATED = "closely_related"
RELATIONS = (EQUIVALENT, CLOSELY_RELATED)

EXPLICIT_ALIAS = "explicit_alias"
CO_OCCURRENCE = "co_occurrence"
COUNTERPART = "counterpart"
EVIDENCE_KINDS = (EXPLICIT_ALIAS, CO_OCCURRENCE, COUNTERPART)

# Two independent papers must support an edge before it can influence retrieval. One
# accidental co-occurrence is therefore never enough to merge two concepts.
MIN_EQUIVALENCE_SUPPORT = 2
# Only a confident equivalent edge may create an alternate query. Repeated
# co-occurrence stays in the graph as `closely_related`, but it does not search.
EXPANSION_MIN_CONFIDENCE = 0.75
# A component that keeps growing is usually polysemy, not one shared concept.
MAX_ACTIVE_COMPONENT = 8
MAX_EXAMPLES = 3
EXAMPLE_CHARS = 240

EXPLICIT_CUES = (
    "also known as",
    "also called",
    "referred to as",
    "known as",
    "called",
    "termed as",
    "termed",
    "synonymous with",
    "equivalent to",
    "same as",
    "interchangeably",
)
_CUE_PATTERN = re.compile(
    r"(?<![a-z0-9-])(?:" + "|".join(re.escape(cue) for cue in EXPLICIT_CUES) + r")(?![a-z0-9-])",
    re.IGNORECASE,
)


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _canonical_label(label: Any) -> str:
    """Order-insensitive display form used for storage and query matching."""
    return normalize(_clean_text(label))


def _pair_key(left: str, right: str) -> tuple[str, str] | None:
    left_key = _canonical_label(left)
    right_key = _canonical_label(right)
    if not left_key or not right_key or left_key == right_key:
        return None
    return tuple(sorted((left_key, right_key)))


def _doi_key(doi: Any) -> str:
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", _clean_text(doi).lower())
    doi = re.sub(r"^doi:", "", doi).strip().strip("/")
    return "doi:" + re.sub(r"\s+", "", doi) if doi else ""


def _paper_identity(paper: Paper) -> str:
    title = normalize(getattr(paper, "title", ""))
    return _doi_key(getattr(paper, "doi", "")) or (f"title:{title}" if title else "")


def _identity_key(paper: Paper | None = None, *, paper_id: Any = "", paper_key: Any = "") -> str:
    supplied = _clean_text(paper_key).lower()
    if supplied:
        return supplied
    if paper is not None:
        found = _paper_identity(paper)
        if found:
            return found
        paper_id = getattr(paper, "paper_id", paper_id)
    key = normalize(paper_id)
    return f"id:{key}" if key else ""


def _is_plausible_label(label: Any) -> bool:
    key = _canonical_label(label)
    return is_clean_label(key) and bool(concept_key(key))


def _relation_bucket(relation: Any) -> str:
    if relation in {"mechanism", "measurement", "failure_mode", "method"}:
        return str(relation)
    if relation == "neighbor_field":
        return "neighbor_field"
    return "topic"


def _distinct_labels(left: Any, right: Any) -> bool:
    # A label and its own reordering are the same concept label, not an equivalence.
    return (_is_plausible_label(left) and _is_plausible_label(right)
            and _pair_key(left, right) is not None and concept_key(left) != concept_key(right))


def _can_pair(left: Any, right: Any, relation: str) -> bool:
    if relation not in RELATIONS or not _distinct_labels(left, right):
        return False
    return relation == EQUIVALENT or not is_redundant(right, [concept_key(left)])


def _unique(values: Iterable[str]) -> list[str]:
    return sorted({value for value in values if value})


def _evidence_key(item: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        _clean_text(item.get("paper_key") or _identity_key(paper_id=item.get("paper_id", ""))).lower(),
        _clean_text(item.get("kind", "")).lower(),
        normalize(item.get("example", "")),
        normalize(item.get("query", "")),
    )


def _clean_evidence(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, Mapping):
        return None
    paper_id = _clean_text(item.get("paper_id", ""))
    kind = _clean_text(item.get("kind", "")).lower()
    if not paper_id or kind not in EVIDENCE_KINDS:
        return None
    paper_key = _identity_key(paper_id=paper_id, paper_key=item.get("paper_key", ""))
    if not paper_key:
        return None
    return {
        "paper_id": paper_id,
        "paper_key": paper_key,
        "kind": kind,
        "field": _clean_text(item.get("field", "")),
        "example": _clean_text(item.get("example", ""))[:EXAMPLE_CHARS],
        "query": _clean_text(item.get("query", "")),
    }


def _clean_all(items: Iterable[Any] | None) -> list[dict[str, Any]]:
    return [item for item in map(_clean_evidence, items or []) if item is not None]


def _new_evidence(items: Iterable[Any], seen: set[tuple[str, str, str, str]]) -> list[dict[str, Any]]:
    fresh = []
    for item in _clean_all(items):
        key = _evidence_key(item)
        if key not in seen:
            seen.add(key)
            fresh.append(item)
    return fresh


def _evidence_order(item: Mapping[str, Any]) -> tuple[str, ...]:
    return item["paper_key"], item["kind"], item["paper_id"], item["example"], item["query"]


def _relation_from(evidence: Iterable[Mapping[str, Any]]) -> str:
    # Co-occurrence alone is never promoted to equivalence, even if a caller labels it
    # that way. Only explicit terminology evidence upgrades the edge.
    explicit = any(item["kind"] in {EXPLICIT_ALIAS, COUNTERPART} for item in evidence)
    return EQUIVALENT if explicit else CLOSELY_RELATED


def _support_count(edge: "ConceptEquivalence") -> int:
    return len({item["paper_key"] for item in edge.evidence})


def _kind_count(edge: "ConceptEquivalence", kind: str) -> int:
    return len({item["paper_key"] for item in edge.evidence if item["kind"] == kind})


def _confidence_for(edge: "ConceptEquivalence") -> float:
    explicit = _kind_count(edge, EXPLICIT_ALIAS)
    counterpart = _kind_count(edge, COUNTERPART)
    co_occurrence = _kind_count(edge, CO_OCCURRENCE)
    fields = max(0, len(edge.fields) - 1)
    score = (
        0.35
        + 0.28 * min(explicit, 2)
        + 0.04 * min(max(0, explicit - 2), 4)
        + 0.18 * min(counterpart, 2)
        + 0.08 * min(co_occurrence, 3)
        + 0.03 * min(fields, 2)
    )
    return round(min(score, 0.99), 3)


@dataclass
class ConceptEquivalence:
    """One unordered pair of labels plus the evidence behind it."""

    a: str
    b: str
    relation: str = EQUIVALENT
    support: list[str] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    confidence: float = 0.0
    evidence: list[dict[str, Any]] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)

    @property
    def key(self) -> tuple[str, str] | None:
        return _pair_key(self.a, self.b)

    def merge_evidence(self, items: Iterable[Mapping[str, Any]]) -> bool:
        fresh = _new_evidence(items, {_evidence_key(item) for item in self.evidence})
        if fresh:
            self.evidence.extend(fresh)
            self._refresh()
        return bool(fresh)

    def _refresh(self) -> None:
        self.evidence.sort(key=_evidence_order)
        self.support = _unique(item["paper_id"] for item in self.evidence)
        self.fields = _unique(item["field"] for item in self.evidence)
        self.queries = _unique(item["query"] for item in self.evidence)[:8]
        self.relation = _relation_from(self.evidence)
        self.confidence = _confidence_for(self)

    def examples(self) -> list[str]:
        seen: list[str] = []
        for item in self.evidence:
            if item["example"] and item["example"] not in seen:
                seen.append(item["example"])
            if len(seen) >= MAX_EXAMPLES:
                break
        return seen

    def to_dict(self) -> dict[str, Any]:
        return {
            "a": self.a,
            "b": self.b,
            "relation": self.relation,
            "support": list(self.support),
            "support_count": _support_count(self),
            "fields": list(self.fields),
            "confidence": self.confidence,
            "evidence": [dict(item) for item in self.evidence],
            "queries": list(self.queries),
            "examples": self.examples(),
        }


def _label_pattern(label: Any) -> re.Pattern[str]:
    return re.compile(r"(?:^| )" + re.escape(_canonical_label(label)) + r"(?=$| )")


def _mentions(text: str, label: Any) -> bool:
    return bool(_canonical_label(label)) and bool(_label_pattern(label).search(text))


def _swap_first(text: str, edge: ConceptEquivalence) -> str:
    """Replace whichever side of the edge the text names, a first, with the other side."""
    source, replacement = (edge.a, edge.b) if _mentions(text, edge.a) else (edge.b, edge.a)
    swapped = _label_pattern(source).sub(f" {replacement} ", text, count=1)
    swapped = re.sub(r"\s+", " ", swapped).strip()
    return swapped if normalize(swapped) != text else ""


class ConceptEquivalenceGraph:
    """In-memory edges. Persistence lives in ConceptEquivalenceStore."""

    def __init__(self) -> None:
        self._edges: dict[tuple[str, str], ConceptEquivalence] = {}
        self._revoked: dict[tuple[str, str], str] = {}

    def __len__(self) -> int:
        return len(self._edges)

    def edges(self) -> list[dict[str, Any]]:
        return [self._edges[key].to_dict() for key in sorted(self._edges)]

    def edge_for(self, left: Any, right: Any) -> dict[str, Any] | None:
        key = _pair_key(left, right)
        if key is None:
            return None
        edge = self._edges.get(key)
        return edge.to_dict() if edge is not None else None

    def is_revoked(self, left: Any, right: Any) -> bool:
        key = _pair_key(left, right)
        return key is not None and key in self._revoked

    def revoke(self, left: Any, right: Any, reason: Any = "") -> bool:
        key = _pair_key(left, right)
        if key is None:
            return False
        self._revoked[key] = _clean_text(reason) or "revoked"
        return True

    def add_observation(
        self,
        left: Any,
        right: Any,
        relation: Any = EQUIVALENT,
        evidence: Iterable[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        relation = _clean_text(relation).lower()
        if not _can_pair(left, right, relation):
            return None
        key = _pair_key(left, right)
        assert key is not None
        edge = self._edges.get(key) or self._new_edge(key, left, right, relation)
        # The stored relation follows the evidence, not the caller's label: `merge_evidence`
        # upgrades an edge only when new explicit terminology evidence actually arrives.
        edge.merge_evidence(evidence or [])
        if not edge.evidence:
            del self._edges[key]
            return None
        return edge.to_dict()

    def _new_edge(self, key: tuple[str, str], left: Any, right: Any, relation: str) -> ConceptEquivalence:
        labels = (_clean_text(left), _clean_text(right))
        if key[0] != _canonical_label(labels[0]):
            labels = labels[::-1]
        self._edges[key] = ConceptEquivalence(a=labels[0], b=labels[1], relation=relation)
        return self._edges[key]

    def _active(self) -> list[tuple[tuple[str, str], ConceptEquivalence]]:
        return [(key, edge) for key, edge in self._edges.items() if key not in self._revoked]

    def _eligible_edges(
        self, relation: str = EQUIVALENT, min_confidence: float = EXPANSION_MIN_CONFIDENCE
    ) -> list[ConceptEquivalence]:
        return [edge for _, edge in self._active()
                if edge.relation == relation and edge.confidence >= min_confidence
                and _support_count(edge) >= MIN_EQUIVALENCE_SUPPORT]

    def aliases_for(
        self,
        label: Any,
        relation: str = EQUIVALENT,
        min_confidence: float = EXPANSION_MIN_CONFIDENCE,
    ) -> tuple[str, ...]:
        wanted = _canonical_label(label)
        if not wanted:
            return ()
        found: list[str] = []
        for edge in self._eligible_edges(relation, min_confidence):
            if _canonical_label(edge.a) == wanted:
                found.append(edge.b)
            elif _canonical_label(edge.b) == wanted:
                found.append(edge.a)
        return tuple(sorted(set(found)))

    def _linked(self, label: str) -> list[str]:
        return [key[1 - key.index(label)] for key, _ in self._active() if label in key]

    def component_size(self, label: Any) -> int:
        """Labels reachable from this one, counted exactly up to one past MAX_ACTIVE_COMPONENT."""
        start = _canonical_label(label)
        seen = [start] if start else []
        for current in seen:  # `seen` grows while it is walked: a breadth-first search
            if len(seen) > MAX_ACTIVE_COMPONENT:
                break
            seen += [other for other in self._linked(current) if other not in seen]
        return len(seen)

    def _directed(self, relation: str, min_confidence: float) -> list[tuple[ConceptEquivalence, str, str]]:
        return [(edge, source, target) for edge in self._eligible_edges(relation, min_confidence)
                for source, target in ((edge.a, edge.b), (edge.b, edge.a))]

    def _expandable(self, text: str, relation: str, min_confidence: float) -> list[ConceptEquivalence]:
        rows = [(edge.confidence, _support_count(edge), target, edge)
                for edge, source, target in self._directed(relation, min_confidence) if _mentions(text, source)]
        # Highest-confidence evidence first so the choice is deterministic.
        rows.sort(key=lambda row: (-row[0], -row[1], row[2]))
        return [edge for *_, edge in rows if self.component_size(edge.a) <= MAX_ACTIVE_COMPONENT]

    def expand_query(
        self,
        query: Any,
        max_aliases: int = 1,
        relation: str = EQUIVALENT,
        min_confidence: float = EXPANSION_MIN_CONFIDENCE,
    ) -> list[str]:
        """Return up to one alternate phrasing for a query, without recursion."""
        normalized = normalize(_clean_text(query))
        if not normalized or max_aliases <= 0:
            return []
        found = [_swap_first(normalized, edge) for edge in self._expandable(normalized, relation, min_confidence)]
        return list(dict.fromkeys(filter(None, found)))[:max_aliases]

    def stats(self) -> dict[str, Any]:
        eligible = self._eligible_edges()
        return {
            "edges": len(self._edges),
            "revoked": len(self._revoked),
            "equivalent": sum(1 for edge in self._edges.values() if edge.relation == EQUIVALENT),
            "closely_related": sum(1 for edge in self._edges.values() if edge.relation == CLOSELY_RELATED),
            "eligible_for_expansion": len(eligible),
        }


def _parse_line(line: str) -> dict[str, Any]:
    try:
        raw = json.loads(line)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}  # malformed lines must not lose earlier evidence
    return raw if isinstance(raw, dict) else {}


def _read_records(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    except OSError:
        lines = []
    return [raw for raw in map(_parse_line, lines) if raw.get("schema_version") == SCHEMA_VERSION]


def _stamped(kind: str, **fields: Any) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "type": kind, **fields, "observed_at": time.time()}


class ConceptEquivalenceStore:
    """Append-only JSONL persistence beside the paper corpus and run memory."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._graph: ConceptEquivalenceGraph | None = None
        self._records = 0

    def load(self) -> ConceptEquivalenceGraph:
        if self._graph is None:
            self._graph = ConceptEquivalenceGraph()
            self._records = sum(self._replay(self._graph, raw) for raw in _read_records(self.path))
        return self._graph

    @staticmethod
    def _replay(graph: ConceptEquivalenceGraph, raw: dict[str, Any]) -> int:
        """Apply one stored record; count it when it is an observation."""
        if raw.get("type") == "revocation":
            graph.revoke(raw.get("a", ""), raw.get("b", ""), raw.get("reason", ""))
        if raw.get("type") != "observation":
            return 0
        graph.add_observation(raw.get("a", ""), raw.get("b", ""), raw.get("relation", EQUIVALENT),
                              raw.get("evidence", []))
        return 1

    def _append_record(self, record: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def append_observation(
        self,
        left: Any,
        right: Any,
        relation: Any = EQUIVALENT,
        evidence: Iterable[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        relation = _clean_text(relation).lower()
        cleaned = _clean_all(evidence)
        if not cleaned or not _can_pair(left, right, relation):
            return None
        self._append_record(_stamped(
            "observation", a=_clean_text(left), b=_clean_text(right), relation=relation, evidence=cleaned,
            support=_unique(item["paper_id"] for item in cleaned), fields=_unique(item["field"] for item in cleaned),
        ))
        self._records += 1
        return self.load().add_observation(left, right, relation, cleaned)

    def observe_run(
        self,
        question: str,
        terms: Iterable[Term | Mapping[str, Any]],
        papers: Iterable[Paper],
        on_topic: set[str] | None,
    ) -> list[dict[str, Any]]:
        observations = discover_observations(question, terms, papers, on_topic)
        learned: list[dict[str, Any]] = []
        for observation in observations:
            edge = self.append_observation(
                observation["a"], observation["b"], observation["relation"], observation["evidence"]
            )
            if edge is not None:
                learned.append(edge)
        return learned

    def revoke(self, left: Any, right: Any, reason: Any = "") -> bool:
        if _pair_key(left, right) is None:
            return False
        self._append_record(_stamped("revocation", a=_clean_text(left), b=_clean_text(right),
                                     reason=_clean_text(reason) or "revoked"))
        return self.load().revoke(left, right, reason)

    def expand_query(self, query: Any, max_aliases: int = 1) -> list[str]:
        return self.load().expand_query(query, max_aliases=max_aliases)

    def stats(self) -> dict[str, Any]:
        graph = self.load()
        data = graph.stats()
        data["records"] = self._records
        data["path"] = str(self.path)
        return data


def _term_parts(term: Term | Mapping[str, Any] | Any) -> tuple[Any, Any, Any, list[Any]] | None:
    if isinstance(term, Term):
        return term.text, term.relation, term.confidence, list(term.paper_ids)
    if isinstance(term, Mapping):
        return (term.get("text", ""), term.get("relation", "topic"), term.get("confidence", ""),
                list(term.get("paper_ids", []) or []))
    return None


def _id_set(paper_ids: Iterable[Any]) -> set[str]:
    return {str(paper_id) for paper_id in paper_ids if str(paper_id)}


def _term_view(term: Term | Mapping[str, Any] | Any) -> dict[str, Any] | None:
    parts = _term_parts(term)
    if parts is None:
        return None
    text, relation, confidence, paper_ids = parts
    if confidence not in GROUNDED or not _is_plausible_label(text):
        return None
    return {
        "label": _clean_text(text),
        "relation": relation,
        "bucket": _relation_bucket(relation),
        "papers": _id_set(paper_ids),
    }


def _paper_fields(paper: Paper) -> list[str]:
    fields = _unique([*paper.fields, *paper.topic_path])
    return [name for name in fields if _clean_text(name) and normalize(name) not in GENERIC_FIELDS]


def _label_spans(sentence: str, label: str) -> list[tuple[int, int]]:
    # Match canonical phrases across hyphenation: `closed-loop control` and
    # `closed loop control` are the same label for evidence purposes.
    flat = re.sub(r"[^a-z0-9]+", " ", sentence.lower()).strip()
    marker = _canonical_label(label)
    if not marker:
        return []
    pattern = re.compile(r"(?<![a-z0-9])" + re.escape(marker) + r"(?![a-z0-9])")
    return [(match.start(), match.end()) for match in pattern.finditer(flat)]


def _cue_between(flat: str, one: tuple[int, int], other: tuple[int, int]) -> bool:
    """True when two non-overlapping spans have a terminology cue between them."""
    (_, first_end), (second_start, _) = sorted((one, other))
    return first_end <= second_start and bool(_CUE_PATTERN.search(flat[first_end:second_start]))


def _explicit_evidence(sentence: str, left: str, right: str) -> bool:
    flat = re.sub(r"[^a-z0-9]+", " ", sentence.lower()).strip()
    return any(_cue_between(flat, one, other)
               for one in _label_spans(flat, left) for other in _label_spans(flat, right))


def _explicit_example(sentences: list[str], left: str, right: str) -> str:
    return next((sentence[:EXAMPLE_CHARS] for sentence in sentences if _explicit_evidence(sentence, left, right)), "")


def _topical_papers(papers: list[Paper], on_topic: set[str] | None) -> dict[str, Paper]:
    """On-topic papers by id, in id order; empty when too few for a topical pass."""
    by_id = {paper.paper_id: paper for paper in papers}
    wanted = sorted(set(on_topic or ()) & set(by_id))
    return {paper_id: by_id[paper_id] for paper_id in wanted} if len(wanted) >= MIN_TOPICAL_CORPUS else {}


def _term_views(terms: Iterable[Term | Mapping[str, Any]], wanted: set[str]) -> dict[str, dict[str, Any]]:
    """One view per canonical label: the variant grounded in the most on-topic papers."""
    views: dict[str, dict[str, Any]] = {}
    for view in filter(None, map(_term_view, terms or [])):
        key = _canonical_label(view["label"])
        current = views.get(key)
        if current is None or len(view["papers"] & wanted) > len(current["papers"] & wanted):
            views[key] = view
    return views


def _metadata_labels(paper: Paper) -> set[str]:
    labels = (*paper.keywords, *paper.fields, *paper.topic_path)
    return {_canonical_label(label) for label in labels if _is_plausible_label(label)}


def _paper_labels(paper: Paper, views: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Canonical key -> display label for every concept this paper carries, in key order."""
    grounded = {key for key, view in views.items() if paper.paper_id in view["papers"]}
    return {key: views.get(key, {"label": key})["label"] for key in sorted(grounded | _metadata_labels(paper))}


def _paper_evidence(paper: Paper) -> dict[str, Any]:
    fields = _paper_fields(paper)
    return {
        "paper_id": paper.paper_id,
        "paper_key": _identity_key(paper),
        "field": fields[0] if fields else "",
        "example": "",
        "query": (paper.found_by or [""])[0],
    }


def _multiword_distinct(pair: tuple[str, str], left: str, right: str) -> bool:
    return all(len(key.split()) >= 2 for key in pair) and not is_redundant(right, [concept_key(left)])


@dataclass
class _Observer:
    """Collects one run's observations, paper by paper."""

    views: dict[str, dict[str, Any]]
    explicit: list[dict[str, Any]] = field(default_factory=list)
    co_occurrence: dict[tuple[str, str], list[dict[str, Any]]] = field(default_factory=dict)

    def read(self, paper: Paper) -> None:
        labels = _paper_labels(paper, self.views)
        evidence = _paper_evidence(paper)
        sentences = _sentences(f"{paper.title}. {paper.abstract}".strip())
        for pair in combinations(labels, 2):
            left, right = labels[pair[0]], labels[pair[1]]
            example = _explicit_example(sentences, left, right)
            if example and _can_pair(left, right, EQUIVALENT):
                self.explicit.append({"a": left, "b": right, "relation": EQUIVALENT,
                                      "evidence": [{**evidence, "kind": EXPLICIT_ALIAS, "example": example}]})
            elif self._co_occurs(pair, left, right):
                self.co_occurrence.setdefault(pair, []).append({**evidence, "kind": CO_OCCURRENCE})

    def _co_occurs(self, pair: tuple[str, str], left: str, right: str) -> bool:
        views = [self.views.get(key) for key in pair]
        if None in views or _pair_key(left, right) is None:
            return False
        return views[0]["bucket"] == views[1]["bucket"] and _multiword_distinct(pair, left, right)

    def closely_related(self) -> list[dict[str, Any]]:
        rows = []
        for (left_key, right_key), items in sorted(self.co_occurrence.items()):
            left, right = self.views[left_key]["label"], self.views[right_key]["label"]
            if _can_pair(left, right, CLOSELY_RELATED):
                rows.append({"a": left, "b": right, "relation": CLOSELY_RELATED, "evidence": items})
        return rows


def discover_observations(
    question: str,
    terms: Iterable[Term | Mapping[str, Any]],
    papers: Iterable[Paper],
    on_topic: set[str] | None,
) -> list[dict[str, Any]]:
    """Turn one run's grounded terms and papers into conservative observations.

    Explicit terminology statements become `equivalent`; repeated co-occurrence of two
    grounded terms becomes `closely_related` and therefore never expands a query.
    """
    del question  # terms and papers already carry the topical context for this pass
    topical = _topical_papers([paper for paper in papers if isinstance(paper, Paper)], on_topic)
    if not topical:
        return []
    observer = _Observer(_term_views(terms, set(topical)))
    for paper in topical.values():
        observer.read(paper)
    return observer.explicit + observer.closely_related()
