from __future__ import annotations

import math
import time
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from .models import DOWN, SIDEWAYS, UP, AgentPolicy, ConceptNode, Paper, RoundStats, Term
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
    LIMITATION_CUES,
    MIN_TOPICAL_CORPUS,
    RELATION_MARKERS,
    REQUIRED_RELATIONS,
    STOPWORDS,
    WEAK_EDGE,
    _add_candidate,
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
    paper_tokens,
    stem,
    tokens,
    top_terms,
    topical_papers,
)


def seed_queries(question: str) -> list[str]:
    compact = compact_question(question)
    q_tokens = tokens(question)
    phrases = sorted(_ngrams(question, 2, 4), key=lambda x: (len(set(tokens(x))), len(x)), reverse=True)
    queries = [compact]
    for phrase in phrases:
        if len(queries) >= 3: break
        if phrase not in queries and len(phrase.split()) <= 5: queries.append(phrase)
    if len(queries) == 1 and len(q_tokens) > 3: queries.append(" ".join(q_tokens[:4]))
    return list(dict.fromkeys(queries))

def _anchor_terms(question: str, terms: list[Term]) -> list[str]:
    core = [t.text for t in terms if t.relation in {"core", "topic"} and t.confidence != "low"] or [compact_question(question, 5)]
    anchors, seen = [], set()
    for term in core:
        term = " ".join(term.split()[:4])
        if term not in seen:
            anchors.append(term); seen.add(term)
        if len(anchors) == 2: break
    return anchors

def next_queries(question: str, terms: list[Term], gaps: list[str], searched: set[str], variant: int = 0) -> list[str]:
    """Queries that would repair the gaps. `variant` rotates the cue wording so a second
    or third repair round asks differently instead of regenerating an already-searched
    string and being dropped as a duplicate."""
    anchors = _anchor_terms(question, terms)
    output = []
    for relation in (gaps or list(REQUIRED_RELATIONS)):
        relation_terms = [t.text for t in top_terms(terms, relation, 2, grounded_only=True)]
        for selected in (relation_terms or GAP_CUES[relation])[:2]:
            parts = [anchors[0], selected]
            intent = GAP_CUES[relation][variant % len(GAP_CUES[relation])]
            if normalize(intent) not in normalize(selected): parts.append(intent)
            if len(anchors) > 1 and relation == "neighbor_field": parts.insert(1, anchors[1])
            query = " ".join(" ".join(dict.fromkeys(parts)).split()[:9])
            if normalize(query) not in {normalize(q) for q in searched}: output.append(query)
        if len(output) >= 5: break
    return list(dict.fromkeys(output))[:5]

def _stop_checks(round_number: int, papers: list[Paper], terms: list[Term], gaps: list[str], *, new_papers: int, new_grounded_terms: int, new_on_topic: int | None = None) -> dict[str, bool]:
    top = terms[:20]
    grounded = [t for t in top if t.confidence in {"high", "medium"}]
    # Saturation counts on-topic arrivals only: a run that has drifted into a neighbouring
    # literature keeps returning new papers forever and would never look saturated.
    fresh = new_papers if new_on_topic is None else new_on_topic
    return {"minimum_rounds": round_number >= 2, "enough_papers": len(papers) >= 12, "relations_covered": not gaps, "grounded_top_terms": len(grounded) / max(len(top), 1) >= 0.70, "multiple_search_paths": len({q for p in papers for q in p.found_by}) >= 4, "saturated": round_number >= 2 and fresh <= 2 and new_grounded_terms <= 2}

def _keep_score(paper: Paper, on_topic: set[str]) -> tuple:
    """Which 50 of several hundred papers survive into the artifact.

    Citations alone kept the canon: measured median year 2006-2013 across four runs.
    Topical fit leads, then recency, then citations.
    """
    recency = 0.0 if not paper.year else max(0.0, min((paper.year - 2010) / 15.0, 1.0))
    return (paper.paper_id in on_topic, round(recency + math.log1p(paper.cited_by_count) / 12.0, 4))


def build_graph(question: str, terms: list[Term], papers: list[Paper]) -> dict:
    nodes = [{"id": "question", "type": "question", "label": question}]
    edges = []
    paper_lookup = {p.paper_id: p for p in papers}
    for index, term in enumerate(terms[:30]):
        term_id = f"term:{index}"
        nodes.append({"id": term_id, "type": "term", "label": term.text, "relation": term.relation, "confidence": term.confidence})
        edges.append({"from": "question", "to": term_id, "type": term.relation})
        for paper_id in term.paper_ids[:5]:
            paper = paper_lookup.get(paper_id)
            if not paper: continue
            node_id = f"paper:{normalize(paper.paper_id)}"
            if not any(n["id"] == node_id for n in nodes): nodes.append({"id": node_id, "type": "paper", "label": paper.title, "url": paper.url})
            edges.append({"from": node_id, "to": term_id, "type": "supports"})
    return {"nodes": nodes, "edges": edges}

def relation_to_direction(relation: str, source_kind: str) -> str:
    if source_kind in {"field", "broader_topic"}:
        return UP
    if relation in DOWN_RELATIONS:
        return DOWN
    return SIDEWAYS


def _query_for_node(node: ConceptNode) -> str:
    # Direction steers priority, not query mangling: query stays the label.
    return node.label


def run_agent(
    question: str,
    providers: list[SearchProvider],
    policy: AgentPolicy | None = None,
    *,
    results_per_query: int = 20,
    background: set[str] | None = None,
    states: ProviderStates | None = None,
) -> dict:
    """Single-root, agent-budget traversal.

    One root topic; the agent decides depth/direction via policy.
    Concepts accumulate until max_nodes / max_depth / max_rounds / saturation.
    """
    policy = policy or AgentPolicy()
    root_label = canonical_root(question)
    concepts: dict[str, ConceptNode] = {}
    root = ConceptNode("c0", root_label, "root", 0, 1.0, [], "", root_label, 0)
    concepts[root.node_id] = root
    visited = {normalize(root_label)}
    papers: list[Paper] = []
    searched: set[str] = set()
    rounds: list[RoundStats] = []
    states = states if states is not None else ProviderStates()
    provider_errors: list[str] = []
    provider_calls: Counter[str] = Counter()
    provider_failures: Counter[str] = Counter()
    frontier: list[ConceptNode] = [root]
    counter = 1
    previous_grounded: set[str] = set()
    last_terms: list[Term] = []
    last_gaps: list[str] = []
    taken_keys: set[frozenset[str]] = {concept_key(root_label)}
    on_topic: set[str] = set()
    previous_on_topic = 0
    status = "partial"
    stop_reason = "no additional distinct queries"

    for round_number in range(1, max(1, policy.max_rounds) + 1):
        if len(concepts) >= policy.max_nodes:
            status, stop_reason = "partial", "agent node budget reached"
            break
        expandable = [c for c in sorted(frontier, key=lambda c: c.weight, reverse=True)
                      if c.depth < policy.max_depth]
        query_budget = max(1, policy.per_direction_cap) if policy.per_direction_cap is not None else 5
        # Gaps were computed, printed, and never searched. Reserve slots for them.
        gap_queries = []
        if last_gaps:
            for variant in range(len(GAP_CUES["failure_mode"])):
                for q in next_queries(question, last_terms, last_gaps, searched, variant):
                    if normalize(q) not in {normalize(x) for x in searched} and q not in gap_queries:
                        gap_queries.append(q)
                if len(gap_queries) >= GAP_QUERY_SLOTS:
                    break
            gap_queries = gap_queries[:GAP_QUERY_SLOTS]
        expandable = expandable[: max(1, query_budget - len(gap_queries))]
        round_queries = []
        for node in expandable:
            q = _query_for_node(node)
            if normalize(q) not in {normalize(x) for x in searched}:
                round_queries.append((node, q))
        for gq in gap_queries:
            round_queries.append((root, gq))
        if not round_queries:
            status, stop_reason = "partial", "no additional distinct queries"
            break
        incoming: list[Paper] = []
        # Ask the source that carries what this round is missing, and skip one that is
        # rate limited until its window passes -- including a window set by an earlier run.
        by_name = {p.name: p for p in providers}
        ordered = [by_name[n] for n in order_for([p.name for p in providers], last_gaps, states)]
        for node, query in round_queries:
            searched.add(query)
            for provider in ordered:
                provider_calls[provider.name] += 1
                try:
                    found = provider.search(query, results_per_query)
                    for p in found:
                        p.found_by = list(dict.fromkeys([*p.found_by, query]))
                    incoming.extend(found)
                    states.observe(provider.name, True)
                except ProviderUnavailable as exc:
                    provider_failures[provider.name] += 1
                    states.observe(provider.name, False)
                    states.block(provider.name, getattr(exc, "retry_after", 0.0) or 0.0, str(exc))
                    provider_errors.append(f"{provider.name}: {exc}")
                except ProviderError as exc:
                    provider_failures[provider.name] += 1
                    states.observe(provider.name, False)
                    provider_errors.append(f"{provider.name}: {exc}")
        papers, added = _dedupe_papers(papers, incoming)
        for node, query in round_queries:
            for p in papers:
                if query in p.found_by and p.paper_id not in node.paper_ids:
                    node.paper_ids.append(p.paper_id)
            node.support = len(node.paper_ids)
        on_topic = topical_papers(question, papers)
        # A small bundle can legitimately have few literal matches; do not starve it.
        topic_filter = on_topic if len(on_topic) >= MIN_TOPICAL_CORPUS else None
        new_on_topic = max(0, len(on_topic) - previous_on_topic)
        previous_on_topic = len(on_topic)
        # Concepts are read from the on-topic corpus only. Letting drifted papers vote
        # produced `protein structure and dynamics` as a mechanism for a question about
        # stopping criteria: one on-topic supporter was enough to launder the rest.
        corpus = [p for p in papers if p.paper_id in on_topic] if topic_filter is not None else papers
        terms = extract_terms(question, corpus, topic_filter, background)
        covered, gaps = coverage(terms)
        last_terms, last_gaps = terms, gaps
        grounded_now = {t.text for t in terms if t.confidence in {"high", "medium"}}
        # Grow concepts from newly grounded terms; agent budget is the ceiling.
        new_frontier: list[ConceptNode] = []
        for term in terms:
            if term.confidence not in {"high", "medium"}:
                continue
            key = normalize(term.text)
            if key in visited:
                continue
            if is_redundant(term.text, taken_keys):
                continue  # paraphrase of a concept already holding a node
            if topic_filter is not None and not (set(term.paper_ids) & topic_filter):
                continue  # grounded only in drifted papers
            direction = relation_to_direction(term.relation, "term")
            depth = 1
            # Attach to highest-weight expandable parent that shares a paper.
            parent = expandable[0] if expandable else root
            for cand in expandable:
                if set(cand.paper_ids) & set(term.paper_ids):
                    parent = cand
                    break
            depth = parent.depth + 1
            if depth > policy.max_depth:
                continue
            if round_number > 1 and len(term.paper_ids) < policy.support_threshold:
                continue
            if len(concepts) >= policy.max_nodes:
                break
            weight = term.score * policy.direction_weight(direction) * (policy.decay ** depth)
            node_id = f"c{counter}"
            counter += 1
            node = ConceptNode(node_id, term.text, direction, depth, round(weight, 4),
                               list(term.paper_ids[:8]), parent.node_id, parent.label,
                               len(term.paper_ids))
            concepts[node_id] = node
            visited.add(key)
            taken_keys.add(concept_key(term.text))
            new_frontier.append(node)
        new_frontier.sort(key=lambda c: c.weight, reverse=True)
        checks = _stop_checks(round_number, corpus, terms, gaps,
                              new_papers=added,
                              new_grounded_terms=len(grounded_now - previous_grounded),
                              new_on_topic=new_on_topic if topic_filter is not None else None)
        checks["node_budget"] = len(concepts) < policy.max_nodes
        checks["has_frontier"] = bool(new_frontier)
        rounds.append(RoundStats(round_number, [q for _, q in round_queries], added,
                                 len(papers), len(grounded_now - previous_grounded),
                                 len(grounded_now), gaps, checks,
                                 gap_queries=list(gap_queries),
                                 new_on_topic=new_on_topic,
                                 on_topic_papers=len(on_topic)))
        previous_grounded = grounded_now
        frontier = new_frontier
        if not papers and provider_errors:
            status, stop_reason = "failed", "live providers were unreachable or returned no evidence"
            break
        if all(checks.values()):
            status, stop_reason = "ready", "all usability checks passed"
            break
        if added == 0 and not new_frontier:
            status, stop_reason = "partial", "search produced no new evidence"
            break
    else:
        status, stop_reason = "partial", "maximum rounds reached"

    if not papers:
        terms: list[Term] = []
        covered, gaps = {r: [] for r in REQUIRED_RELATIONS}, list(REQUIRED_RELATIONS)
        status, stop_reason = "failed", "no papers could be retrieved"
    else:
        on_topic = topical_papers(question, papers)
        topic_filter = on_topic if len(on_topic) >= MIN_TOPICAL_CORPUS else None
        corpus = [p for p in papers if p.paper_id in on_topic] if topic_filter is not None else papers
        terms = extract_terms(question, corpus, topic_filter, background)
        covered, gaps = coverage(terms)
        # `ready` demands all five relations; a run that repaired every gap it could and
        # still misses one was reported as plain `partial`, which read as failure.
        if status != "ready" and len(gaps) <= 1 and len(REQUIRED_RELATIONS) - len(gaps) >= 4:
            searched_gap_queries = {q for r in rounds for q in (r.gap_queries or [])}
            if searched_gap_queries or not gaps:
                status = "usable"
                repaired = " after gap repair" if searched_gap_queries else ""
                stop_reason = f"{len(REQUIRED_RELATIONS) - len(gaps)}/5 relations grounded{repaired}"
    # A provider that answered nothing all run changes what the map can contain, so the
    # brief says so instead of quietly reading as a Crossref-only result.
    down_providers = sorted(n for n, calls in provider_calls.items() if calls and provider_failures[n] == calls)
    top = terms[:30]
    concept_list = sorted(concepts.values(), key=lambda c: (c.depth, -c.weight))
    kept_papers = sorted(papers, key=lambda p: _keep_score(p, on_topic), reverse=True)[:50]
    return {"version": 5, "question": question, "root_topic": root_label,
            "status": status, "stop_reason": stop_reason,
            "coverage": covered, "gaps": gaps,
            # kept separately: these rank below the top 30 but carry the quoted sentence
            # Only sentences a paper actually wrote. Title n-grams containing "failure"
            # were being quoted here as stated limitations.
            "limitations": [t.to_dict() for t in top_terms(terms, "failure_mode", 5, grounded_only=True)
                            if t.stated_limitation],
            "recommended_queries": next_queries(question, terms, gaps, set()),
            "terms": [t.to_dict() for t in top],
            "concepts": [c.to_dict() for c in concept_list],
            "policy": policy.to_dict(),
            "on_topic_papers": len(on_topic),
            "retrieved_papers": len(papers),
            "papers": [p.to_dict() for p in kept_papers],
            "rounds": [r.to_dict() for r in rounds],
            "provider_errors": list(dict.fromkeys(provider_errors)),
            "providers_down": down_providers,
            "providers_blocked": sorted(n for n, st in states.states.items() if not st.available(time.time())),
            "graph": build_graph(question, top, kept_papers)}


def run_router(question: str, providers: list[SearchProvider], *, max_rounds: int = 6, results_per_query: int = 20) -> dict:
    """Backward-compat wrapper: default policy, single root."""
    return run_agent(question, providers, AgentPolicy(max_rounds=max(1, max_rounds)),
                     results_per_query=results_per_query)
