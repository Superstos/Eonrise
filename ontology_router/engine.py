from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from .models import Paper, RoundStats, Term
from .providers import ProviderError, SearchProvider

REQUIRED_RELATIONS = ("mechanism", "measurement", "failure_mode", "method", "neighbor_field")
STOPWORDS = {"a","an","and","are","as","at","be","been","being","but","by","can","could","did","do","does","for","from","had","has","have","how","if","in","into","is","it","its","may","might","more","most","of","on","or","our","should","so","than","that","the","their","them","then","there","these","they","this","to","under","using","was","we","were","what","when","where","which","who","why","will","with","within","without","would","across","reliably","change","effect","effects","impact","study","paper","papers","research","results","new","based","approach","using","used","large","system"}
RELATION_MARKERS = {
    "mechanism": {"mechanism","process","pathway","architecture","dynamics","feedback","retrieval","storage","encoding","consolidation","adaptation","mediation","causal","intervention","memory","attention","learning","policy","control","update","resolution","propagation","interaction","inference"},
    "measurement": {"metric","measure","measurement","accuracy","score","index","scale","benchmark","evaluation","reliability","validity","robustness","performance","recall","precision","rate","assessment","test","testing","fidelity","consistency","generalization","sensitivity","specificity","error","outcome"},
    "failure_mode": {"failure","failures","limitation","limitations","bias","confound","confounding","artifact","error","errors","weakness","risk","vulnerability","interference","hallucination","stale","obsolete","invalid","fragility","degradation","drift","collapse","forgetting","injection","noise","misalignment"},
    "method": {"experiment","experimental","randomized","controlled","trial","ablation","longitudinal","cross-sectional","simulation","survey","interview","cohort","case-control","meta-analysis","systematic review","protocol","replication","baseline","comparison","comparative","observational","ethnography","factorial","blinded","sampling","evaluation protocol","controlled evaluation","controlled experiment","comparative testing","component assessment","component-level assessment","human annotation","prediction-powered inference","reproducible workflow","metric validation"},
}
GENERIC_FIELDS = {"science", "social sciences", "physical sciences", "life sciences", "health sciences", "computer science", "artificial intelligence", "mathematics", "engineering", "medicine"}
GAP_CUES = {
    "mechanism": ["mechanism", "causal process", "architecture"],
    "measurement": ["metric", "benchmark", "reliability"],
    "failure_mode": ["failure mode", "limitation", "confound"],
    "method": ["experiment", "ablation", "controlled study"],
    "neighbor_field": ["interdisciplinary", "related field", "analogy"],
}

@dataclass
class CandidateEvidence:
    papers: set[str]
    providers: set[str]
    queries: set[str]
    examples: list[str]
    explicit_count: int = 0
    title_count: int = 0
    relation_votes: Counter | None = None
    def __post_init__(self) -> None:
        if self.relation_votes is None:
            self.relation_votes = Counter()

def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()

def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z][a-z0-9-]+", text.lower()) if t not in STOPWORDS and len(t) > 1]

def compact_question(question: str, max_tokens: int = 8) -> str:
    selected = tokens(question)
    return " ".join(selected[:max_tokens]) or question.strip()

def _content_runs(text: str) -> list[list[str]]:
    runs, current = [], []
    for raw in re.findall(r"[a-z][a-z0-9-]+|[.!?;,:()]", text.lower()):
        if raw in ".!?;,:()" or raw in STOPWORDS:
            if current:
                runs.append(current)
                current = []
            continue
        if len(raw) > 1:
            current.append(raw)
    if current:
        runs.append(current)
    return runs

def _ngrams(text: str, min_n: int = 2, max_n: int = 4) -> Iterable[str]:
    for run in _content_runs(text):
        for n in range(min_n, min(max_n, len(run)) + 1):
            for i in range(len(run) - n + 1):
                phrase = " ".join(run[i:i+n])
                if len(phrase) >= 6:
                    yield phrase

def _relation_for(term: str, context: str, source_kind: str, question_tokens: set[str]) -> str:
    key = normalize(term)
    term_tokens = set(tokens(term))
    if any(x in key for x in ("fault injection", "ablation", "controlled trial", "randomized trial", "controlled comparison", "systematic review", "meta analysis", "stress testing", "trace analysis", "controlled evaluation", "controlled experiment", "evaluation protocol", "comparative testing", "component-level assessment", "metric validation")):
        return "method"
    if term_tokens & {"failure", "failures", "stale", "obsolete", "invalid", "fragility", "bias", "confound", "vulnerability", "degradation", "interference", "hallucination"}:
        return "failure_mode"
    if term_tokens & {"accuracy", "accurate", "metric", "metrics", "score", "rate", "benchmark", "evaluation", "reliability", "validity", "robustness", "performance", "fidelity", "consistency", "generalization", "sensitivity", "assessment"}:
        return "measurement"
    if term_tokens & {"experiment", "experimental", "randomized", "controlled", "trial", "ablation", "longitudinal", "simulation", "survey", "cohort", "replication", "baseline", "sampling", "comparative", "annotation", "validation", "protocol"}:
        return "method"
    if term_tokens & RELATION_MARKERS["mechanism"]:
        return "mechanism"
    if source_kind == "broader_topic":
        return "neighbor_field"
    if term_tokens & question_tokens:
        return "core"
    return "topic"

def _add_candidate(bucket: dict[str, CandidateEvidence], term: str, paper: Paper, relation: str, example: str, explicit: bool = False, in_title: bool = False) -> None:
    key = normalize(term)
    if not key or len(key.split()) > 6 or len(key) > 80:
        return
    item = bucket.setdefault(key, CandidateEvidence(set(), set(), set(), []))
    item.papers.add(paper.paper_id)
    item.providers.add(paper.provider)
    item.queries.update(paper.found_by)
    if example and example not in item.examples and len(item.examples) < 3:
        item.examples.append(example)
    item.explicit_count += int(explicit)
    item.title_count += int(in_title)
    item.relation_votes[relation] += 1

def extract_terms(question: str, papers: list[Paper]) -> list[Term]:
    q_tokens = set(tokens(question))
    candidates: dict[str, CandidateEvidence] = {}
    for paper in papers:
        context = f"{paper.title}. {paper.abstract}"
        for keyword in paper.keywords:
            _add_candidate(candidates, keyword, paper, _relation_for(keyword, context, "keyword", q_tokens), paper.title, explicit=True)
        for field_name in paper.fields:
            if normalize(field_name) not in GENERIC_FIELDS:
                _add_candidate(candidates, field_name, paper, "neighbor_field", paper.title, explicit=True)
        for topic in paper.topic_path:
            if normalize(topic) not in GENERIC_FIELDS:
                _add_candidate(candidates, topic, paper, _relation_for(topic, context, "topic", q_tokens), paper.title, explicit=True)
        for phrase in _ngrams(paper.title, 2, 4):
            _add_candidate(candidates, phrase, paper, _relation_for(phrase, context, "title", q_tokens), paper.title, in_title=True)
        for phrase in _ngrams(paper.abstract, 2, 4):
            phrase_tokens = set(tokens(phrase))
            if any(phrase_tokens & marker_set for marker_set in RELATION_MARKERS.values()):
                _add_candidate(candidates, phrase, paper, _relation_for(phrase, context, "abstract", q_tokens), paper.title)
    terms: list[Term] = []
    for key, ev in candidates.items():
        support = len(ev.papers)
        relation = ev.relation_votes.most_common(1)[0][0]
        score = 1.25 * math.log1p(support) + 0.34 * min(ev.explicit_count, 3) + 0.18 * min(ev.title_count, 3) + 0.16 * min(len(ev.queries), 4) + 0.20 * min(len(ev.providers), 2) + 0.35 * (len(set(key.split()) & q_tokens) / max(len(set(key.split())), 1)) + 0.08 * min(len(key.split()), 4)
        if support >= 3 or (support >= 2 and (ev.explicit_count or ev.title_count)):
            confidence = "high"
        elif support >= 2 or ((ev.explicit_count >= 1 or ev.title_count >= 1) and len(key.split()) >= 2 and relation in {*REQUIRED_RELATIONS, "core", "topic"}):
            confidence = "medium"
        else:
            confidence = "low"
        if support == 1 and ev.explicit_count == 0:
            continue
        terms.append(Term(key, relation, round(score, 3), confidence, sorted(ev.papers), sorted(ev.providers), sorted(ev.queries), ev.examples))
    return sorted(terms, key=lambda t: (t.confidence == "high", t.score), reverse=True)

def _dedupe_papers(existing: list[Paper], incoming: Iterable[Paper]) -> tuple[list[Paper], int]:
    by_key = {normalize(p.doi or p.title or p.paper_id): p for p in existing}
    added = 0
    for paper in incoming:
        key = normalize(paper.doi or paper.title or paper.paper_id)
        if key in by_key:
            old = by_key[key]
            old.found_by = list(dict.fromkeys([*old.found_by, *paper.found_by]))
            old.keywords = list(dict.fromkeys([*old.keywords, *paper.keywords]))
            old.fields = list(dict.fromkeys([*old.fields, *paper.fields]))
            old.topic_path = list(dict.fromkeys([*old.topic_path, *paper.topic_path]))
            if not old.venue and paper.venue: old.venue = paper.venue
            if not old.abstract and paper.abstract: old.abstract = paper.abstract
            continue
        by_key[key] = paper
        added += 1
    return list(by_key.values()), added

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

def top_terms(terms: list[Term], relation: str | None = None, limit: int = 5, grounded_only: bool = False) -> list[Term]:
    selected = [t for t in terms if relation is None or t.relation == relation]
    if grounded_only: selected = [t for t in selected if t.confidence in {"high", "medium"}]
    return selected[:limit]

def coverage(terms: list[Term], minimum_per_relation: int = 2) -> tuple[dict[str, list[str]], list[str]]:
    covered, gaps = {}, []
    for relation in REQUIRED_RELATIONS:
        items = top_terms(terms, relation, limit=5, grounded_only=True)
        covered[relation] = [item.text for item in items]
        if len(items) < minimum_per_relation: gaps.append(relation)
    return covered, gaps

def _anchor_terms(question: str, terms: list[Term]) -> list[str]:
    core = [t.text for t in terms if t.relation in {"core", "topic"} and t.confidence != "low"] or [compact_question(question, 5)]
    anchors, seen = [], set()
    for term in core:
        term = " ".join(term.split()[:4])
        if term not in seen:
            anchors.append(term); seen.add(term)
        if len(anchors) == 2: break
    return anchors

def next_queries(question: str, terms: list[Term], gaps: list[str], searched: set[str]) -> list[str]:
    anchors = _anchor_terms(question, terms)
    output = []
    for relation in (gaps or list(REQUIRED_RELATIONS)):
        relation_terms = [t.text for t in top_terms(terms, relation, 2, grounded_only=True)]
        for selected in (relation_terms or GAP_CUES[relation])[:2]:
            parts = [anchors[0], selected]
            intent = GAP_CUES[relation][0]
            if normalize(intent) not in normalize(selected): parts.append(intent)
            if len(anchors) > 1 and relation == "neighbor_field": parts.insert(1, anchors[1])
            query = " ".join(" ".join(dict.fromkeys(parts)).split()[:9])
            if normalize(query) not in {normalize(q) for q in searched}: output.append(query)
        if len(output) >= 5: break
    return list(dict.fromkeys(output))[:5]

def _stop_checks(round_number: int, papers: list[Paper], terms: list[Term], gaps: list[str], *, new_papers: int, new_grounded_terms: int) -> dict[str, bool]:
    top = terms[:20]
    grounded = [t for t in top if t.confidence in {"high", "medium"}]
    return {"minimum_rounds": round_number >= 2, "enough_papers": len(papers) >= 12, "relations_covered": not gaps, "grounded_top_terms": len(grounded) / max(len(top), 1) >= 0.70, "multiple_search_paths": len({q for p in papers for q in p.found_by}) >= 4, "saturated": round_number >= 2 and new_papers <= 2 and new_grounded_terms <= 2}

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

def run_router(question: str, providers: list[SearchProvider], *, max_rounds: int = 6, results_per_query: int = 20) -> dict:
    papers, searched, rounds, provider_errors = [], set(), [], []
    queries = seed_queries(question)
    previous_grounded = set()
    for round_number in range(1, max_rounds + 1):
        round_queries = [q for q in queries if normalize(q) not in {normalize(x) for x in searched}]
        if not round_queries: break
        incoming = []
        for query in round_queries:
            searched.add(query)
            for provider in providers:
                try: incoming.extend(provider.search(query, results_per_query))
                except ProviderError as exc: provider_errors.append(f"{provider.name}: {exc}")
        papers, added = _dedupe_papers(papers, incoming)
        terms = extract_terms(question, papers)
        covered, gaps = coverage(terms)
        grounded_now = {t.text for t in terms if t.confidence in {"high", "medium"}}
        checks = _stop_checks(round_number, papers, terms, gaps, new_papers=added, new_grounded_terms=len(grounded_now - previous_grounded))
        rounds.append(RoundStats(round_number, round_queries, added, len(papers), len(grounded_now - previous_grounded), len(grounded_now), gaps, checks))
        previous_grounded = grounded_now
        if not papers and provider_errors:
            status, stop_reason = "failed", "live providers were unreachable or returned no evidence"; break
        if all(checks.values()):
            status, stop_reason = "ready", "all usability checks passed"; break
        queries = next_queries(question, terms, gaps, searched)
        if added == 0 and not queries:
            status, stop_reason = "partial", "search produced no new evidence"; break
    else:
        status, stop_reason = "partial", "maximum rounds reached"
    if not papers:
        status, stop_reason, terms = "failed", "no papers could be retrieved", []
        covered, gaps = {r: [] for r in REQUIRED_RELATIONS}, list(REQUIRED_RELATIONS)
    else:
        terms = extract_terms(question, papers)
        covered, gaps = coverage(terms)
        if "status" not in locals(): status, stop_reason = "partial", "no additional distinct queries"
    top = terms[:30]
    return {"version": 4, "question": question, "status": status, "stop_reason": stop_reason, "coverage": covered, "gaps": gaps, "recommended_queries": next_queries(question, terms, gaps, set()), "terms": [t.to_dict() for t in top], "papers": [p.to_dict() for p in sorted(papers, key=lambda p: (p.cited_by_count, p.year or 0), reverse=True)[:50]], "rounds": [r.to_dict() for r in rounds], "provider_errors": list(dict.fromkeys(provider_errors)), "graph": build_graph(question, top, papers)}
