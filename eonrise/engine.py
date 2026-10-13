from __future__ import annotations

import math
import time
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

from .models import DOWN, SIDEWAYS, UP, SearchSettings, ConceptNode, Paper, RoundStats, Term
from .distant_fields import concept_gate, distant_queries, rank_distant_papers
from .literature_coverage import estimate_coverage
from .providers import ProviderError, ProviderUnavailable, SearchProvider
from .scheduling import ProviderStates, order_for

# Re-exported so engine.py stays the traversal and callers keep one import site.
from .evidence import (
    CandidateEvidence,
    DOWN_RELATIONS,
    FILLER,
    GAP_CUES,
    GAP_CUE_TOKENS,
    GAP_QUERY_SLOTS,
    GENERIC_FIELDS,
    GROUNDED,
    LIMITATION_CUES,
    MIN_TOPICAL_CORPUS,
    RELATION_MARKERS,
    REQUIRED_RELATIONS,
    STOPWORDS,
    WEAK_EDGE,
    _content_runs,
    _dedupe_papers,
    _guard_relation,
    _ngrams,
    _relation_for,
    _sentences,
    canonical_root,
    compact_question,
    concept_key,
    coverage,
    dedupe_terms,
    extract_terms,
    is_redundant,
    limitation_phrases,
    normalize,
    paper_word_families,
    to_singular,
    split_words,
    top_terms,
    topical_papers,
    grounding_papers,
)


def _core_labels(terms: list[Term]) -> list[str]:
    return [t.text for t in terms if t.relation in {"core", "topic"} and t.confidence != "low"]


def _anchor_terms(question: str, terms: list[Term]) -> list[str]:
    core = _core_labels(terms) or [compact_question(question, 5)]
    return list(dict.fromkeys(" ".join(term.split()[:4]) for term in core))[:2]


def _gap_query(anchors: list[str], relation: str, selected: str, intent: str) -> str:
    parts = [anchors[0], selected]
    if normalize(intent) not in normalize(selected): parts.append(intent)
    if len(anchors) > 1 and relation == "neighbor_field": parts.insert(1, anchors[1])
    return " ".join(" ".join(dict.fromkeys(parts)).split()[:9])


def _relation_queries(anchors: list[str], terms: list[Term], relation: str, variant: int) -> list[str]:
    """Up to two queries pairing the anchor with the relation's best terms, or its cue words."""
    relation_terms = [t.text for t in top_terms(terms, relation, 2, grounded_only=True)]
    cues = GAP_CUES[relation]
    intent = cues[variant % len(cues)]
    return [_gap_query(anchors, relation, selected, intent) for selected in (relation_terms or cues)[:2]]


def _unsearched(queries: list[str], searched_keys: set[str]) -> list[str]:
    return [query for query in queries if normalize(query) not in searched_keys]


def next_queries(question: str, terms: list[Term], gaps: list[str], searched: set[str], variant: int = 0) -> list[str]:
    """Queries that would repair the gaps. `variant` rotates the cue wording so a second
    or third repair round asks differently instead of regenerating an already-searched
    string and being dropped as a duplicate."""
    anchors = _anchor_terms(question, terms)
    searched_keys = {normalize(q) for q in searched}
    output: list[str] = []
    for relation in (gaps or list(REQUIRED_RELATIONS)):
        output += _unsearched(_relation_queries(anchors, terms, relation, variant), searched_keys)
        if len(output) >= 5: break
    return list(dict.fromkeys(output))[:5]

def _keep_score(paper: Paper, on_topic: set[str]) -> tuple:
    """Which 50 of several hundred papers survive into the artifact.

    Citations alone kept the canon: measured median year 2006-2013 across four runs.
    Topical fit leads, then whether the paper can ground anything at all, then recency,
    metadata richness and citations.

    An abstract outranks a citation count here because of v0.7: a paper with no abstract
    cannot supply a mechanism, a measurement, a method or a failure mode. It can only add
    a subject label. Ranking it above a paper that carries text was ranking the artifact's
    least useful evidence first.
    """
    recency = 0.0 if not paper.year else max(0.0, min((paper.year - 2010) / 15.0, 1.0))
    richness = min(len(paper.keywords) + len(paper.fields) + len(paper.topic_path), 6) / 6.0
    return (paper.paper_id in on_topic, bool(paper.abstract),
            round(recency + 0.6 * richness + math.log1p(paper.cited_by_count) / 12.0, 4))


def _supporting(term: Term, lookup: dict[str, Paper]) -> list[Paper]:
    return [lookup[paper_id] for paper_id in term.paper_ids[:5] if paper_id in lookup]


def build_graph(question: str, terms: list[Term], papers: list[Paper]) -> dict:
    lookup = {p.paper_id: p for p in papers}
    nodes = {"question": {"id": "question", "type": "question", "label": question}}
    edges = []
    for index, term in enumerate(terms[:30]):
        term_id = f"term:{index}"
        nodes[term_id] = {"id": term_id, "type": "term", "label": term.text, "relation": term.relation, "confidence": term.confidence}
        edges.append({"from": "question", "to": term_id, "type": term.relation})
        for paper in _supporting(term, lookup):
            node_id = f"paper:{normalize(paper.paper_id)}"
            nodes.setdefault(node_id, {"id": node_id, "type": "paper", "label": paper.title, "url": paper.url})
            edges.append({"from": node_id, "to": term_id, "type": "supports"})
    return {"nodes": list(nodes.values()), "edges": edges}

def relation_to_direction(relation: str, source_kind: str) -> str:
    """Up was unreachable. Every concept was created with source_kind `"term"`, so the
    branch above it never ran and 28 of 30 nodes in a measured run came back `sideways`.
    A `neighbor_field` term IS the broader classification the paper sits under, so it is
    what up means here — and up carries half the weight, which is the point of naming it.
    """
    if source_kind in {"field", "broader_topic"} or relation == "neighbor_field":
        return UP
    if relation in DOWN_RELATIONS:
        return DOWN
    return SIDEWAYS



def _dormant(silent_rounds: Counter) -> set[str]:
    # Two full rounds with not one candidate term: the question does not have this
    # facet in this literature. Chasing it spends the query budget on cue words.
    return {r for r, n in silent_rounds.items() if n >= 2}


@dataclass
class _Round:
    """What one round planned, fetched and read."""
    number: int
    expandable: list[ConceptNode]
    queries: list[tuple[ConceptNode, str]]
    gap_queries: list[str]
    added: int = 0
    new_on_topic: int = 0
    topic_filter: set[str] | None = None
    corpus: list[Paper] = field(default_factory=list)
    terms: list[Term] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    grounded: set[str] = field(default_factory=set)
    new_frontier: list[ConceptNode] = field(default_factory=list)


@dataclass
class _Search:
    """One run's state. Each method is one step of a round; `run_search` drives them."""
    question: str
    providers: list[SearchProvider]
    policy: SearchSettings
    results_per_query: int
    background: set[str] | None
    states: ProviderStates
    equivalence: object | None
    expansion_slots: int
    papers: list[Paper] = field(default_factory=list)
    searched: set[str] = field(default_factory=set)
    rounds: list[RoundStats] = field(default_factory=list)
    provider_errors: list[str] = field(default_factory=list)
    provider_calls: Counter = field(default_factory=Counter)
    provider_failures: Counter = field(default_factory=Counter)
    previous_grounded: set[str] = field(default_factory=set)
    last_terms: list[Term] = field(default_factory=list)
    last_gaps: list[str] = field(default_factory=list)
    # A relation the literature never mentions is not a gap to chase. Tracked per round so
    # two rounds of silence is the evidence, not one unlucky query.
    silent_rounds: Counter = field(default_factory=Counter)
    dormant: set[str] = field(default_factory=set)
    corpus_saved: int = 0  # paid calls the local store made unnecessary
    on_topic: set[str] = field(default_factory=set)
    previous_on_topic: int = 0
    expanded_queries: list[str] = field(default_factory=list)
    counter: int = 1
    status: str = "partial"
    stop_reason: str = "no additional distinct queries"

    def __post_init__(self) -> None:
        self.root_label = canonical_root(self.question)
        self.root = ConceptNode("c0", self.root_label, "root", 0, 1.0, [], "", self.root_label, 0)
        self.concepts = {self.root.node_id: self.root}
        self.visited = {normalize(self.root_label)}
        self.taken_keys = {concept_key(self.root_label)}
        self.frontier = [self.root]
        self.expansion_remaining = self.expansion_slots

    # --- the loop -------------------------------------------------------------------------

    def run_rounds(self) -> None:
        for number in range(1, max(1, self.policy.max_rounds) + 1):
            if self.run_round(number):
                return
        self._stop("partial", "maximum rounds reached")

    def run_round(self, number: int) -> bool:
        """Plan, fetch, read, grow. True when the run should stop."""
        if len(self.concepts) >= self.policy.max_nodes:
            return self._stop("partial", "node budget reached")
        step = self.plan_round(number)
        if not step.queries:
            return self._stop("partial", "no additional distinct queries")
        self.fetch(step)
        self.read_round(step)
        step.new_frontier = self.grow(step)
        checks = self.record(step)
        return self.decide(step, checks)

    def _stop(self, status: str, reason: str) -> bool:
        self.status, self.stop_reason = status, reason
        return True

    # --- plan -----------------------------------------------------------------------------

    def _expandable(self) -> list[ConceptNode]:
        return [c for c in sorted(self.frontier, key=lambda c: c.weight, reverse=True)
                if c.depth < self.policy.max_depth]

    def _query_budget(self) -> int:
        cap = self.policy.per_direction_cap
        return max(1, cap) if cap is not None else 5

    def plan_round(self, number: int) -> _Round:
        expandable = self._expandable()
        budget = self._query_budget()
        gap_queries = self.gap_queries()
        reserve = min(self.expansion_remaining, max(0, budget - len(gap_queries)))
        expandable = expandable[: max(1, budget - len(gap_queries) - reserve)]
        queries = [(node, node.label) for node in expandable if self._is_new(node.label)]
        queries += [(self.root, query) for query in gap_queries]
        queries += self.expansions(queries, budget)
        return _Round(number, expandable, queries, gap_queries)

    def _is_new(self, query: str) -> bool:
        return normalize(query) not in {normalize(x) for x in self.searched}

    def gap_queries(self) -> list[str]:
        """Gaps were computed, printed, and never searched. Reserve slots for them."""
        if not self.last_gaps:
            return []
        found: list[str] = []
        for variant in range(len(GAP_CUES["failure_mode"])):
            batch = next_queries(self.question, self.last_terms, self.last_gaps, self.searched, variant)
            found = list(dict.fromkeys(found + self._new_only(batch)))
            if len(found) >= GAP_QUERY_SLOTS:
                break
        return found[:GAP_QUERY_SLOTS]

    def _new_only(self, queries: list[str]) -> list[str]:
        return [q for q in queries if self._is_new(q)]

    def expansions(self, queries: list[tuple[ConceptNode, str]], budget: int) -> list[tuple[ConceptNode, str]]:
        """One conservative equivalence alias may use a query slot. It never replaces the
        original query, so the run still searches what the question literally asked."""
        expand = getattr(self.equivalence, "expand_query", None)
        room = min(self.expansion_remaining, budget - len(queries)) if callable(expand) else 0
        out: list[tuple[ConceptNode, str]] = []
        for node, query in queries:
            if len(out) >= room:
                break
            alias = self._new_alias(expand(query, max_aliases=1))
            if alias is not None:
                out.append((node, alias))
                self.expanded_queries.append(alias)
                self.expansion_remaining -= 1
        return out

    def _new_alias(self, candidates: list[str]) -> str | None:
        seen = {normalize(q) for q in self.expanded_queries}
        return next((c for c in candidates if self._is_new(c) and normalize(c) not in seen), None)

    # --- fetch ----------------------------------------------------------------------------

    def fetch(self, step: _Round) -> None:
        incoming: list[Paper] = []
        ordered = self._provider_order()
        for _, query in step.queries:
            self.searched.add(query)
            incoming += self._ask_all(ordered, query)
        self.papers, step.added = _dedupe_papers(self.papers, incoming)
        for node, query in step.queries:
            self._attach(node, query)

    def _attach(self, node: ConceptNode, query: str) -> None:
        node.paper_ids += [p.paper_id for p in self.papers
                           if query in p.found_by and p.paper_id not in node.paper_ids]
        node.support = len(node.paper_ids)

    def _provider_order(self) -> list[SearchProvider]:
        # Ask the source that carries what this round is missing, and skip one that is
        # rate limited until its window passes -- including a window set by an earlier run.
        by_name = {p.name: p for p in self.providers}
        names = order_for([p.name for p in self.providers], self.last_gaps, self.states)
        # The local store answers before paid providers. Ranking by metadata richness
        # otherwise puts DOAJ/OpenAlex first and spends a call a held paper could answer.
        return [by_name[n] for n in sorted(names, key=lambda name: name != "corpus")]

    def _ask_all(self, ordered: list[SearchProvider], query: str) -> list[Paper]:
        found: list[Paper] = []
        local_hits = 0
        for provider in ordered:
            # v0.6 ordered the providers and then called every one of them, so a paper
            # already held cost exactly as much as a paper fetched. The store only pays
            # off if it can end the query: a full local answer stops the paid calls.
            if local_hits >= self.results_per_query and provider.name != "corpus":
                self.corpus_saved += 1
                continue
            answer = self._ask(provider, query)
            found += answer
            local_hits = len(answer) if provider.name == "corpus" else local_hits
        return found

    def _ask(self, provider: SearchProvider, query: str) -> list[Paper]:
        self.provider_calls[provider.name] += 1
        try:
            found = provider.search(query, self.results_per_query)
        except ProviderError as exc:
            self._record_failure(provider.name, exc)
            return []
        for p in found:
            p.found_by = list(dict.fromkeys([*p.found_by, query]))
        self.states.observe(provider.name, True)
        return found

    def _record_failure(self, name: str, exc: ProviderError) -> None:
        self.provider_failures[name] += 1
        self.states.observe(name, False)
        if isinstance(exc, ProviderUnavailable):
            self.states.block(name, getattr(exc, "retry_after", 0.0) or 0.0, str(exc))
        self.provider_errors.append(f"{name}: {exc}")

    # --- read -----------------------------------------------------------------------------

    def read_evidence(self) -> tuple[set[str], set[str] | None, list[Paper], list[Term]]:
        on_topic = concept_gate(self.question, self.papers, topical_papers(self.question, self.papers))
        # A small bundle can legitimately have few literal matches; do not starve it, but
        # top it up with the closest papers rather than letting the whole corpus vote.
        topic_filter = grounding_papers(self.question, self.papers, on_topic)
        # Concepts are read from the on-topic corpus only. Letting drifted papers vote
        # produced `protein structure and dynamics` as a mechanism for a question about
        # stopping criteria: one on-topic supporter was enough to launder the rest.
        corpus = self.papers if topic_filter is None else [p for p in self.papers if p.paper_id in topic_filter]
        return on_topic, topic_filter, corpus, extract_terms(self.question, corpus, topic_filter, self.background)

    def read_round(self, step: _Round) -> None:
        on_topic, step.topic_filter, step.corpus, step.terms = self.read_evidence()
        step.new_on_topic = max(0, len(on_topic) - self.previous_on_topic)
        self.on_topic, self.previous_on_topic = on_topic, len(on_topic)
        _, gaps = coverage(step.terms)
        self._track_silence(step.terms)
        step.gaps = [g for g in gaps if g not in self.dormant]
        self.last_terms, self.last_gaps = step.terms, step.gaps
        step.grounded = {t.text for t in step.terms if t.confidence in GROUNDED}

    def _track_silence(self, terms: list[Term]) -> None:
        present = {t.relation for t in terms}
        for relation in REQUIRED_RELATIONS:
            self.silent_rounds[relation] = 0 if relation in present else self.silent_rounds[relation] + 1
        self.dormant = _dormant(self.silent_rounds)

    # --- grow -----------------------------------------------------------------------------

    def grow(self, step: _Round) -> list[ConceptNode]:
        """Grow concepts from newly grounded terms; the node budget is the ceiling."""
        new: list[ConceptNode] = []
        for term in step.terms:
            parent = self._placement(term, step)
            if parent is None:
                continue
            if len(self.concepts) >= self.policy.max_nodes:
                break
            new.append(self._add_concept(term, parent))
        return sorted(new, key=lambda c: c.weight, reverse=True)

    def _placement(self, term: Term, step: _Round) -> ConceptNode | None:
        if not self._admissible(term, step.topic_filter):
            return None
        parent = self._parent_for(term, step.expandable)
        if parent.depth + 1 > self.policy.max_depth:
            return None
        if step.number > 1 and len(term.paper_ids) < self.policy.support_threshold:
            return None
        return parent

    def _admissible(self, term: Term, topic_filter: set[str] | None) -> bool:
        if term.confidence not in GROUNDED or normalize(term.text) in self.visited:
            return False
        if is_redundant(term.text, self.taken_keys):
            return False  # paraphrase of a concept already holding a node
        return topic_filter is None or bool(set(term.paper_ids) & topic_filter)  # else drifted

    def _parent_for(self, term: Term, expandable: list[ConceptNode]) -> ConceptNode:
        """The highest-weight expandable parent that shares a paper."""
        shared = (c for c in expandable if set(c.paper_ids) & set(term.paper_ids))
        return next(shared, expandable[0] if expandable else self.root)

    def _add_concept(self, term: Term, parent: ConceptNode) -> ConceptNode:
        depth = parent.depth + 1
        direction = relation_to_direction(term.relation, "term")
        weight = term.score * self.policy.direction_weight(direction) * (self.policy.decay ** depth)
        node = ConceptNode(f"c{self.counter}", term.text, direction, depth, round(weight, 4),
                           list(term.paper_ids[:8]), parent.node_id, parent.label, len(term.paper_ids))
        self.counter += 1
        self.concepts[node.node_id] = node
        self.visited.add(normalize(term.text))
        self.taken_keys.add(concept_key(term.text))
        return node

    # --- judge ----------------------------------------------------------------------------

    def record(self, step: _Round) -> dict[str, bool]:
        checks = self._checks(step)
        new_grounded = len(step.grounded - self.previous_grounded)
        self.rounds.append(RoundStats(step.number, [q for _, q in step.queries], step.added,
                                      len(self.papers), new_grounded, len(step.grounded), step.gaps,
                                      checks, gap_queries=list(step.gap_queries),
                                      new_on_topic=step.new_on_topic, on_topic_papers=len(self.on_topic)))
        self.previous_grounded = step.grounded
        self.frontier = step.new_frontier
        return checks

    def _checks(self, step: _Round) -> dict[str, bool]:
        top = step.terms[:20]
        grounded = [t for t in top if t.confidence in GROUNDED]
        return {"minimum_rounds": step.number >= 2,
                "enough_papers": len(step.corpus) >= 12,
                "relations_covered": not step.gaps,
                "grounded_top_terms": len(grounded) / max(len(top), 1) >= 0.70,
                "multiple_search_paths": len({q for p in step.corpus for q in p.found_by}) >= 4,
                "saturated": self._saturated(step),
                "node_budget": len(self.concepts) < self.policy.max_nodes,
                "has_frontier": bool(step.new_frontier)}

    def _saturated(self, step: _Round) -> bool:
        # Saturation counts on-topic arrivals only: a run that has drifted into a neighbouring
        # literature keeps returning new papers forever and would never look saturated.
        fresh = step.new_on_topic if len(self.on_topic) >= MIN_TOPICAL_CORPUS else step.added
        return step.number >= 2 and fresh <= 2 and len(step.grounded - self.previous_grounded) <= 2

    def _unreachable(self) -> bool:
        return not self.papers and bool(self.provider_errors)

    def decide(self, step: _Round, checks: dict[str, bool]) -> bool:
        if self._unreachable():
            return self._stop("failed", "live providers were unreachable or returned no evidence")
        if all(checks.values()):
            return self._stop("ready", "all usability checks passed")
        if step.added == 0 and not step.new_frontier:
            return self._stop("partial", "search produced no new evidence")
        return False

    # --- finish ---------------------------------------------------------------------------

    def finish(self) -> None:
        self.topic_filter: set[str] | None = None
        if not self.papers:
            self._finish_empty()
            return
        self.on_topic, self.topic_filter, _, self.terms = self.read_evidence()
        self.covered, self.gaps = coverage(self.terms)
        # `ready` demands all five relations; a run that repaired every gap it could and
        # still misses one was reported as plain `partial`, which read as failure.
        if self.status != "ready" and len(self.gaps) <= 1:
            self._grade_usable()
        self._fail_off_topic()

    def _finish_empty(self) -> None:
        self.terms: list[Term] = []
        self.covered, self.gaps = {r: [] for r in REQUIRED_RELATIONS}, list(REQUIRED_RELATIONS)
        self._stop("failed", "no papers could be retrieved")

    def _fail_off_topic(self) -> None:
        # `few` and `none` are not the same signal. MIN_TOPICAL_CORPUS exists so a small
        # bundle with few literal matches is not starved, but at zero it was converting
        # "no evidence of relevance" into "every paper may vote": `topic_filter` became
        # None, and `_guard_relation` skips its on-topic check entirely when on_topic is
        # None. Measured 2026-09-16 on a live run: 0 of 60 papers on topic, status
        # `partial`, and the brief named quality control as the mechanism from papers
        # about neuroimaging QC and health-system care quality.
        if not self.on_topic and len(self.papers) >= MIN_TOPICAL_CORPUS:
            self._stop("failed", f"{len(self.papers)} papers retrieved, none about the question")

    def _repaired(self) -> set[str]:
        return {q for r in self.rounds for q in (r.gap_queries or [])}

    def _grade_usable(self) -> None:
        grounded = len(REQUIRED_RELATIONS) - len(self.gaps)
        repaired = self._repaired()
        if grounded >= 4 and (repaired or not self.gaps):
            suffix = " after gap repair" if repaired else ""
            self._stop("usable", f"{grounded}/5 relations grounded{suffix}")

    # --- output ---------------------------------------------------------------------------

    def result(self) -> dict:
        kept = sorted(self.papers, key=lambda p: _keep_score(p, self.on_topic), reverse=True)[:50]
        return {**self._summary(), **self._evidence(kept), **self._diagnostics(kept)}

    def _summary(self) -> dict:
        return {"version": 5, "question": self.question, "root_topic": self.root_label,
                "status": self.status, "stop_reason": self.stop_reason,
                "coverage": self.covered, "gaps": self.gaps, "dormant_relations": sorted(self.dormant),
                # Every paper retrieved this run, not the kept 50. The artifact shows 50; the
                # store learns from all of them. Capping the store at what a reader sees threw
                # away ~90% of each run's evidence before the next run could reuse it.
                "corpus_papers": [p.to_dict() for p in self.papers],
                "calls_saved_by_corpus": self.corpus_saved,
                # Only sentences a paper actually wrote. Title n-grams containing "failure"
                # were being quoted here as stated limitations.
                "limitations": [t.to_dict() for t in top_terms(self.terms, "failure_mode", 5, grounded_only=True)
                                if t.stated_limitation],
                "recommended_queries": next_queries(self.question, self.terms, self.gaps, set()),
                "query_expansion": {
                    "enabled": self.equivalence is not None and self.expansion_slots > 0,
                    "max_slots": self.expansion_slots,
                    "slots_used": len(self.expanded_queries),
                    "rejected_for_budget": 0,
                    "expanded_queries": list(self.expanded_queries)}}

    def _distant(self) -> list[dict]:
        home = self.on_topic | (self.topic_filter or set())
        return rank_distant_papers(self.terms, self.papers, home, home_ids=self.on_topic) if self.papers else []

    def _evidence(self, kept: list[Paper]) -> dict:
        distant = self._distant()
        return {"on_topic_paper_ids": sorted(self.on_topic),
                # Capture histories of the on-topic papers: how much these queries can still reach.
                "unseen": estimate_coverage(self.papers, self.on_topic),
                # Off-gate papers carrying the question's grounded shape: the distant fields.
                "harvest": distant,
                "distant_queries": distant_queries(distant),
                "terms": [t.to_dict() for t in self.terms[:30]],
                "concepts": [c.to_dict() for c in sorted(self.concepts.values(), key=lambda c: (c.depth, -c.weight))],
                "policy": self.policy.to_dict(),
                "on_topic_papers": len(self.on_topic),
                "retrieved_papers": len(self.papers),
                "papers": [p.to_dict() for p in kept]}

    def _providers_down(self) -> list[str]:
        # A provider that answered nothing all run changes what the map can contain, so the
        # brief says so instead of quietly reading as a Crossref-only result.
        return sorted(n for n, calls in self.provider_calls.items() if calls and self.provider_failures[n] == calls)

    def _diagnostics(self, kept: list[Paper]) -> dict:
        now = time.time()
        return {"rounds": [r.to_dict() for r in self.rounds],
                "provider_errors": list(dict.fromkeys(self.provider_errors)),
                "providers_down": self._providers_down(),
                "providers_blocked": sorted(n for n, st in self.states.states.items() if not st.available(now)),
                "graph": build_graph(self.question, self.terms[:30], kept)}


def run_search(
    question: str,
    providers: list[SearchProvider],
    policy: SearchSettings | None = None,
    *,
    results_per_query: int = 20,
    background: set[str] | None = None,
    states: ProviderStates | None = None,
    equivalence: object | None = None,
    query_expansion_slots: int = 0,
) -> dict:
    """Single-root, budgeted traversal.

    One root topic; the settings bound depth and direction.
    Concepts accumulate until max_nodes / max_depth / max_rounds / saturation.
    """
    search = _Search(question, providers, policy or SearchSettings(), results_per_query, background,
                     states if states is not None else ProviderStates(), equivalence,
                     max(0, int(query_expansion_slots or 0)))
    search.run_rounds()
    search.finish()
    return search.result()
