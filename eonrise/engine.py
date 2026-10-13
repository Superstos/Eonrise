from __future__ import annotations

import math
import time
import re
from collections import Counter
from dataclasses import dataclass
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
    paper_word_families,
    to_singular,
    split_words,
    top_terms,
    topical_papers,
    grounding_papers,
)


def seed_queries(question: str) -> list[str]:
    compact = compact_question(question)
    q_tokens = split_words(question)
    phrases = sorted(_ngrams(question, 2, 4), key=lambda x: (len(set(split_words(x))), len(x)), reverse=True)
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


def _query_for_node(node: ConceptNode) -> str:
    # Direction steers priority, not query mangling: query stays the label.
    return node.label


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
    policy = policy or SearchSettings()
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
    # A relation the literature never mentions is not a gap to chase. Tracked per round so
    # two rounds of silence is the evidence, not one unlucky query.
    silent_rounds: Counter = Counter()
    corpus_saved = 0  # paid calls the local store made unnecessary
    dormant: set[str] = set()
    taken_keys: set[frozenset[str]] = {concept_key(root_label)}
    on_topic: set[str] = set()
    previous_on_topic = 0
    expansion_slots = max(0, int(query_expansion_slots or 0))
    expansion_remaining = expansion_slots
    expanded_queries: list[str] = []
    expansion_rejected = 0
    status = "partial"
    stop_reason = "no additional distinct queries"

    for round_number in range(1, max(1, policy.max_rounds) + 1):
        if len(concepts) >= policy.max_nodes:
            status, stop_reason = "partial", "node budget reached"
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
        # One conservative equivalence alias may use a query slot. It never replaces the
        # original query, so the run still searches what the question literally asked.
        expansion_reserve = min(expansion_remaining, max(0, query_budget - len(gap_queries)))
        expandable = expandable[: max(1, query_budget - len(gap_queries) - expansion_reserve)]
        round_queries = []
        for node in expandable:
            q = _query_for_node(node)
            if normalize(q) not in {normalize(x) for x in searched}:
                round_queries.append((node, q))
        for gq in gap_queries:
            round_queries.append((root, gq))
        round_expansions: list[tuple[ConceptNode, str]] = []
        expand = getattr(equivalence, "expand_query", None) if equivalence is not None else None
        if callable(expand) and expansion_remaining > 0:
            seen_expansions = {normalize(q) for q in expanded_queries}
            for node, query in list(round_queries):
                if expansion_remaining <= 0:
                    break
                if len(round_queries) + len(round_expansions) >= query_budget:
                    break
                candidates = expand(query, max_aliases=1)
                for candidate in candidates:
                    marker = normalize(candidate)
                    if marker in {normalize(x) for x in searched} or marker in seen_expansions:
                        continue
                    round_expansions.append((node, candidate))
                    seen_expansions.add(marker)
                    expanded_queries.append(candidate)
                    expansion_remaining -= 1
                    break
            if round_expansions and len(round_queries) + len(round_expansions) > query_budget:
                dropped = (len(round_queries) + len(round_expansions)) - query_budget
                for _ in range(dropped):
                    round_expansions.pop()
                    expanded_queries.pop()
                    expansion_remaining += 1
                    expansion_rejected += 1
        round_queries.extend(round_expansions)
        if not round_queries:
            status, stop_reason = "partial", "no additional distinct queries"
            break
        incoming: list[Paper] = []
        # Ask the source that carries what this round is missing, and skip one that is
        # rate limited until its window passes -- including a window set by an earlier run.
        by_name = {p.name: p for p in providers}
        ordered_names = order_for([p.name for p in providers], last_gaps, states)
        # The local store answers before paid providers. Ranking by metadata richness
        # otherwise puts DOAJ/OpenAlex first and spends a call a held paper could answer.
        if "corpus" in by_name and "corpus" in ordered_names:
            ordered_names = ["corpus", *[name for name in ordered_names if name != "corpus"]]
        ordered = [by_name[n] for n in ordered_names]
        for node, query in round_queries:
            searched.add(query)
            local_hits = 0
            for provider in ordered:
                # v0.6 ordered the providers and then called every one of them, so a paper
                # already held cost exactly as much as a paper fetched. The store only pays
                # off if it can end the query: a full local answer stops the paid calls.
                if local_hits >= results_per_query and provider.name != "corpus":
                    corpus_saved += 1
                    continue
                provider_calls[provider.name] += 1
                try:
                    found = provider.search(query, results_per_query)
                    for p in found:
                        p.found_by = list(dict.fromkeys([*p.found_by, query]))
                    incoming.extend(found)
                    if provider.name == "corpus":
                        local_hits = len(found)
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
        on_topic = concept_gate(question, papers, topical_papers(question, papers))
        # A small bundle can legitimately have few literal matches; do not starve it, but
        # top it up with the closest papers rather than letting the whole corpus vote.
        topic_filter = grounding_papers(question, papers, on_topic)
        new_on_topic = max(0, len(on_topic) - previous_on_topic)
        previous_on_topic = len(on_topic)
        # Concepts are read from the on-topic corpus only. Letting drifted papers vote
        # produced `protein structure and dynamics` as a mechanism for a question about
        # stopping criteria: one on-topic supporter was enough to launder the rest.
        corpus = [p for p in papers if p.paper_id in topic_filter] if topic_filter is not None else papers
        terms = extract_terms(question, corpus, topic_filter, background)
        covered, gaps = coverage(terms)
        for relation in REQUIRED_RELATIONS:
            if any(t.relation == relation for t in terms):
                silent_rounds[relation] = 0
            else:
                silent_rounds[relation] += 1
        # Two full rounds with not one candidate term: the question does not have this
        # facet in this literature. Chasing it spends the query budget on cue words.
        dormant = {r for r, n in silent_rounds.items() if n >= 2}
        gaps = [g for g in gaps if g not in dormant]
        last_terms, last_gaps = terms, gaps
        grounded_now = {t.text for t in terms if t.confidence in {"high", "medium"}}
        # Grow concepts from newly grounded terms; the node budget is the ceiling.
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
                              new_on_topic=new_on_topic if len(on_topic) >= MIN_TOPICAL_CORPUS else None)
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
        on_topic = concept_gate(question, papers, topical_papers(question, papers))
        topic_filter = grounding_papers(question, papers, on_topic)
        corpus = [p for p in papers if p.paper_id in topic_filter] if topic_filter is not None else papers
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
        # `few` and `none` are not the same signal. MIN_TOPICAL_CORPUS exists so a small
        # bundle with few literal matches is not starved, but at zero it was converting
        # "no evidence of relevance" into "every paper may vote": `topic_filter` became
        # None, and `_guard_relation` skips its on-topic check entirely when on_topic is
        # None. Measured 2026-09-16 on a live run: 0 of 60 papers on topic, status
        # `partial`, and the brief named quality control as the mechanism from papers
        # about neuroimaging QC and health-system care quality.
        if not on_topic and len(papers) >= MIN_TOPICAL_CORPUS:
            status = "failed"
            stop_reason = f"{len(papers)} papers retrieved, none about the question"
    # A provider that answered nothing all run changes what the map can contain, so the
    # brief says so instead of quietly reading as a Crossref-only result.
    down_providers = sorted(n for n, calls in provider_calls.items() if calls and provider_failures[n] == calls)
    top = terms[:30]
    harvested = rank_distant_papers(terms, papers, on_topic | (topic_filter or set()), home_ids=on_topic) if papers else []
    concept_list = sorted(concepts.values(), key=lambda c: (c.depth, -c.weight))
    kept_papers = sorted(papers, key=lambda p: _keep_score(p, on_topic), reverse=True)[:50]
    return {"version": 5, "question": question, "root_topic": root_label,
            "status": status, "stop_reason": stop_reason,
            "coverage": covered, "gaps": gaps, "dormant_relations": sorted(dormant),
            # Every paper retrieved this run, not the kept 50. The artifact shows 50; the
            # store learns from all of them. Capping the store at what a reader sees threw
            # away ~90% of each run's evidence before the next run could reuse it.
            "corpus_papers": [p.to_dict() for p in papers],
            "calls_saved_by_corpus": corpus_saved,
            # kept separately: these rank below the top 30 but carry the quoted sentence
            # Only sentences a paper actually wrote. Title n-grams containing "failure"
            # were being quoted here as stated limitations.
            "limitations": [t.to_dict() for t in top_terms(terms, "failure_mode", 5, grounded_only=True)
                            if t.stated_limitation],
            "recommended_queries": next_queries(question, terms, gaps, set()),
            "query_expansion": {
                "enabled": equivalence is not None and expansion_slots > 0,
                "max_slots": expansion_slots,
                "slots_used": len(expanded_queries),
                "rejected_for_budget": expansion_rejected,
                "expanded_queries": list(expanded_queries),
            },
            "on_topic_paper_ids": sorted(on_topic),
            # Capture histories of the on-topic papers: how much these queries can still reach.
            "unseen": estimate_coverage(papers, on_topic),
            # Off-gate papers carrying the question's grounded shape: the distant fields.
            "harvest": harvested,
            "distant_queries": distant_queries(harvested),
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
