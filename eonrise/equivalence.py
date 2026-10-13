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
from pathlib import Path
from typing import Any, Iterable, Mapping

from .evidence import (
    FILLER,
    GENERIC_FIELDS,
    MIN_TOPICAL_CORPUS,
    WEAK_EDGE,
    _sentences,
    concept_key,
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
MAX_LABEL_TOKENS = 6
MAX_LABEL_CHARS = 80
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


def _identity_key(paper: Paper | None = None, *, paper_id: Any = "", paper_key: Any = "") -> str:
    supplied = _clean_text(paper_key).lower()
    if supplied:
        return supplied
    if paper is not None:
        doi = _clean_text(getattr(paper, "doi", "")).lower()
        if doi:
            doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)
            doi = re.sub(r"^doi:", "", doi).strip().strip("/")
            if doi:
                return "doi:" + re.sub(r"\s+", "", doi)
        title = normalize(getattr(paper, "title", ""))
        if title:
            return "title:" + title
        paper_id = getattr(paper, "paper_id", paper_id)
    key = normalize(paper_id)
    return f"id:{key}" if key else ""


def _is_plausible_label(label: Any) -> bool:
    key = _canonical_label(label)
    if not key:
        return False
    parts = key.split()
    if len(parts) > MAX_LABEL_TOKENS or len(key) > MAX_LABEL_CHARS:
        return False
    if key in GENERIC_FIELDS:
        return False
    if parts[0] in WEAK_EDGE or parts[-1] in WEAK_EDGE:
        return False
    if any(part in FILLER for part in parts):
        return False
    return bool(concept_key(key))


def _relation_bucket(relation: Any) -> str:
    if relation in {"mechanism", "measurement", "failure_mode", "method"}:
        return str(relation)
    if relation == "neighbor_field":
        return "neighbor_field"
    return "topic"


def _can_pair(left: Any, right: Any, relation: str) -> bool:
    if relation not in RELATIONS:
        return False
    if not _is_plausible_label(left) or not _is_plausible_label(right):
        return False
    if _pair_key(left, right) is None:
        return False
    # A label and its own reordering are the same concept label, not an equivalence.
    if concept_key(left) == concept_key(right):
        return False
    if relation != EQUIVALENT and is_redundant(right, [concept_key(left)]):
        return False
    return True


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
        seen = {_evidence_key(item) for item in self.evidence}
        changed = False
        for raw in items:
            item = _clean_evidence(raw)
            if item is None:
                continue
            key = _evidence_key(item)
            if key in seen:
                continue
            seen.add(key)
            self.evidence.append(item)
            changed = True
        if changed:
            self.evidence.sort(key=lambda item: (
                item["paper_key"], item["kind"], item["paper_id"], item["example"], item["query"]
            ))
            self.support = _unique([item["paper_id"] for item in self.evidence])
            self.fields = _unique([item["field"] for item in self.evidence if item["field"]])
            self.queries = _unique([item["query"] for item in self.evidence if item["query"]])[:8]
            # Co-occurrence alone is never promoted to equivalence, even if a caller
            # labels it that way. Only explicit terminology evidence upgrades the edge.
            if any(item["kind"] in {EXPLICIT_ALIAS, COUNTERPART} for item in self.evidence):
                self.relation = EQUIVALENT
            else:
                self.relation = CLOSELY_RELATED
            self.confidence = _confidence_for(self)
        return changed

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
        left_label = _clean_text(left)
        right_label = _clean_text(right)
        if key[0] != _canonical_label(left_label):
            left_label, right_label = right_label, left_label
        edge = self._edges.get(key)
        if edge is None:
            edge = ConceptEquivalence(a=left_label, b=right_label, relation=relation)
            self._edges[key] = edge
        # The stored relation follows the evidence, not the caller's label: `merge_evidence`
        # upgrades an edge only when new explicit terminology evidence actually arrives.
        edge.merge_evidence(evidence or [])
        if not edge.evidence:
            del self._edges[key]
            return None
        return edge.to_dict()

    def _eligible_edges(
        self, relation: str = EQUIVALENT, min_confidence: float = EXPANSION_MIN_CONFIDENCE
    ) -> list[ConceptEquivalence]:
        eligible: list[ConceptEquivalence] = []
        for key, edge in self._edges.items():
            if key in self._revoked:
                continue
            if edge.relation != relation:
                continue
            if edge.confidence < min_confidence:
                continue
            if _support_count(edge) < MIN_EQUIVALENCE_SUPPORT:
                continue
            eligible.append(edge)
        return eligible

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

    def component_size(self, label: Any) -> int:
        start = _canonical_label(label)
        if not start:
            return 0
        seen = {start}
        frontier = [start]
        while frontier and len(seen) <= MAX_ACTIVE_COMPONENT:
            current = frontier.pop()
            for key in self._edges:
                if key in self._revoked:
                    continue
                if current not in key:
                    continue
                other = key[1] if key[0] == current else key[0]
                if other not in seen:
                    seen.add(other)
                    frontier.append(other)
        return len(seen)

    def expand_query(
        self,
        query: Any,
        max_aliases: int = 1,
        relation: str = EQUIVALENT,
        min_confidence: float = EXPANSION_MIN_CONFIDENCE,
    ) -> list[str]:
        """Return up to one alternate phrasing for a query, without recursion."""
        text = _clean_text(query)
        if not text or max_aliases <= 0:
            return []
        normalized = normalize(text)
        if not normalized:
            return []
        candidates: list[tuple[float, int, str, ConceptEquivalence]] = []
        for edge in self._eligible_edges(relation, min_confidence):
            for source, target in ((edge.a, edge.b), (edge.b, edge.a)):
                marker = _canonical_label(source)
                if not marker:
                    continue
                pattern = re.compile(r"(?:^| )" + re.escape(marker) + r"(?=$| )")
                if pattern.search(normalized):
                    candidates.append((edge.confidence, _support_count(edge), target, edge))
        # Highest-confidence evidence first so the choice is deterministic.
        candidates.sort(key=lambda row: (-row[0], -row[1], row[2]))
        expanded: list[str] = []
        for _, _, _, edge in candidates:
            if len(expanded) >= max_aliases:
                break
            if self.component_size(edge.a) > MAX_ACTIVE_COMPONENT:
                continue
            for source, replacement in ((edge.a, edge.b), (edge.b, edge.a)):
                marker = _canonical_label(source)
                pattern = re.compile(r"(?:^| )" + re.escape(marker) + r"(?=$| )")
                if pattern.search(normalized):
                    candidate = pattern.sub(f" {replacement} ", normalized, count=1)
                    candidate = re.sub(r"\s+", " ", candidate).strip()
                    if candidate and normalize(candidate) != normalized and candidate not in expanded:
                        expanded.append(candidate)
                    break
        return expanded

    def stats(self) -> dict[str, Any]:
        eligible = self._eligible_edges()
        return {
            "edges": len(self._edges),
            "revoked": len(self._revoked),
            "equivalent": sum(1 for edge in self._edges.values() if edge.relation == EQUIVALENT),
            "closely_related": sum(1 for edge in self._edges.values() if edge.relation == CLOSELY_RELATED),
            "eligible_for_expansion": len(eligible),
        }


class ConceptEquivalenceStore:
    """Append-only JSONL persistence beside the paper corpus and run memory."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._graph: ConceptEquivalenceGraph | None = None
        self._records = 0

    def load(self) -> ConceptEquivalenceGraph:
        if self._graph is not None:
            return self._graph
        graph = ConceptEquivalenceGraph()
        records = 0
        if self.path.exists():
            try:
                lines = self.path.read_text(encoding="utf-8").splitlines()
            except OSError:
                lines = []
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue  # malformed lines must not lose earlier evidence
                if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
                    continue
                kind = raw.get("type")
                if kind == "observation":
                    records += 1
                    graph.add_observation(
                        raw.get("a", ""),
                        raw.get("b", ""),
                        raw.get("relation", EQUIVALENT),
                        raw.get("evidence", []),
                    )
                elif kind == "revocation":
                    graph.revoke(raw.get("a", ""), raw.get("b", ""), raw.get("reason", ""))
        self._graph = graph
        self._records = records
        return graph

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
        if not _can_pair(left, right, relation):
            return None
        cleaned = [_clean_evidence(item) for item in (evidence or [])]
        cleaned = [item for item in cleaned if item is not None]
        if not cleaned:
            return None
        record = {
            "schema_version": SCHEMA_VERSION,
            "type": "observation",
            "a": _clean_text(left),
            "b": _clean_text(right),
            "relation": relation,
            "evidence": cleaned,
            "support": _unique([item["paper_id"] for item in cleaned]),
            "fields": _unique([item["field"] for item in cleaned if item["field"]]),
            "observed_at": time.time(),
        }
        self._append_record(record)
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
        record = {
            "schema_version": SCHEMA_VERSION,
            "type": "revocation",
            "a": _clean_text(left),
            "b": _clean_text(right),
            "reason": _clean_text(reason) or "revoked",
            "observed_at": time.time(),
        }
        self._append_record(record)
        return self.load().revoke(left, right, reason)

    def expand_query(self, query: Any, max_aliases: int = 1) -> list[str]:
        return self.load().expand_query(query, max_aliases=max_aliases)

    def stats(self) -> dict[str, Any]:
        graph = self.load()
        data = graph.stats()
        data["records"] = self._records
        data["path"] = str(self.path)
        return data


def _term_view(term: Term | Mapping[str, Any] | Any) -> dict[str, Any] | None:
    if isinstance(term, Term):
        text = term.text
        relation = term.relation
        confidence = term.confidence
        paper_ids = list(term.paper_ids)
    elif isinstance(term, Mapping):
        text = term.get("text", "")
        relation = term.get("relation", "topic")
        confidence = term.get("confidence", "")
        paper_ids = list(term.get("paper_ids", []) or [])
    else:
        return None
    if confidence not in {"high", "medium"} or not _is_plausible_label(text):
        return None
    return {
        "label": _clean_text(text),
        "relation": relation,
        "bucket": _relation_bucket(relation),
        "papers": {str(paper_id) for paper_id in paper_ids if str(paper_id)},
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


def _explicit_evidence(sentence: str, left: str, right: str) -> bool:
    flat = re.sub(r"[^a-z0-9]+", " ", sentence.lower()).strip()
    left_spans = _label_spans(flat, left)
    right_spans = _label_spans(flat, right)
    for left_start, left_end in left_spans:
        for right_start, right_end in right_spans:
            if not (left_end <= right_start or right_end <= left_start):
                continue
            if left_end <= right_start:
                middle = flat[left_end:right_start]
            else:
                middle = flat[right_end:left_start]
            if _CUE_PATTERN.search(middle):
                return True
    return False


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
    papers = [paper for paper in papers if isinstance(paper, Paper)]
    if not papers or not on_topic or len(on_topic) < MIN_TOPICAL_CORPUS:
        return []
    by_id = {paper.paper_id: paper for paper in papers}
    wanted = {paper_id for paper_id in on_topic if paper_id in by_id}
    if len(wanted) < MIN_TOPICAL_CORPUS:
        return []

    term_views: dict[str, dict[str, Any]] = {}
    for term in terms or []:
        view = _term_view(term)
        if view is None:
            continue
        key = _canonical_label(view["label"])
        current = term_views.get(key)
        if current is None or len(view["papers"] & wanted) > len(current["papers"] & wanted):
            term_views[key] = view

    observations: list[dict[str, Any]] = []
    co_occurrence: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for paper_id in sorted(wanted):
        paper = by_id[paper_id]
        grounded = sorted(
            key
            for key, view in term_views.items()
            if paper_id in view["papers"]
        )
        metadata = sorted(
            {
                _canonical_label(label)
                for label in ([*paper.keywords, *paper.fields, *paper.topic_path])
                if _is_plausible_label(label)
            }
        )
        candidates = sorted(set(grounded) | set(metadata))
        if len(candidates) < 2:
            continue
        labels = {key: term_views.get(key, {"label": key})["label"] for key in candidates}
        text = f"{paper.title}. {paper.abstract}".strip()
        fields = _paper_fields(paper)
        query = (paper.found_by or [""])[0]
        for left_index, left_key in enumerate(candidates):
            for right_key in candidates[left_index + 1:]:
                left = labels[left_key]
                right = labels[right_key]
                if _pair_key(left, right) is None:
                    continue
                evidence = {
                    "paper_id": paper.paper_id,
                    "paper_key": _identity_key(paper),
                    "field": fields[0] if fields else "",
                    "example": "",
                    "query": query,
                }
                explicit = any(
                    _explicit_evidence(sentence, left, right) for sentence in _sentences(text)
                )
                if explicit and _can_pair(left, right, EQUIVALENT):
                    observations.append({
                        "a": left,
                        "b": right,
                        "relation": EQUIVALENT,
                        "evidence": [{**evidence, "kind": EXPLICIT_ALIAS,
                                      "example": next(
                                          (sentence[:EXAMPLE_CHARS] for sentence in _sentences(text)
                                           if _explicit_evidence(sentence, left, right)),
                                          "")}],
                    })
                    continue
                left_view = term_views.get(left_key)
                right_view = term_views.get(right_key)
                if left_view is None or right_view is None:
                    continue
                if left_view["bucket"] != right_view["bucket"]:
                    continue
                if len(left_key.split()) < 2 or len(right_key.split()) < 2:
                    continue
                if is_redundant(right, [concept_key(left)]):
                    continue
                key = tuple(sorted((left_key, right_key)))
                co_occurrence.setdefault(key, []).append({**evidence, "kind": CO_OCCURRENCE})

    for (left_key, right_key), items in sorted(co_occurrence.items()):
        left = term_views[left_key]["label"]
        right = term_views[right_key]["label"]
        if not _can_pair(left, right, CLOSELY_RELATED):
            continue
        observations.append({"a": left, "b": right, "relation": CLOSELY_RELATED, "evidence": items})
    return observations
