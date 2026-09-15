from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from .models import DOWN, SIDEWAYS, UP, AgentPolicy, ConceptNode, Paper, RoundStats, Term
from .providers import ProviderError, SearchProvider

DOWN_RELATIONS = ("mechanism", "measurement", "failure_mode", "method")

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

GAP_CUE_TOKENS = {rel: {t for cue in cues for t in re.findall(r"[a-z]+", cue)} for rel, cues in GAP_CUES.items()}
MIN_TOPICAL_CORPUS = 8  # below this, topical filtering would starve a small bundle
GAP_QUERY_SLOTS = 2  # of the per-round query budget, reserved for repairing gaps
# Words that cannot start or end a concept. `relation between`, `similarity between` and
# `measure between` are sentence fragments, not findings.
# Words that carry no subject matter anywhere in a phrase. `problem very terms` and
# `you actually` were real concepts in real runs.
FILLER = {"very", "both", "such", "many", "most", "several", "various", "actually",
          "apparently", "particularly", "especially", "significantly", "typically",
          "generally", "usually", "previously", "recently", "relatively", "highly",
          "mainly", "largely", "widely", "directly", "strongly", "currently", "finally",
          "initially", "simply", "clearly", "well-known", "state-of-the-art", "novel",
          "brought", "make", "makes", "made", "take", "takes", "good", "better", "best"}
WEAK_EDGE = {"between", "through", "via", "within", "among", "toward", "towards", "into",
             "under", "over", "upon", "per", "about", "against", "after", "before",
             "during", "such", "both", "each", "other", "others", "same", "given",
             "present", "presents", "shows", "show", "propose", "proposed", "proposes",
             "provide", "provides", "including", "include", "includes", "however"}


def stem(token: str) -> str:
    """Crude singulariser so `similarity measure` and `similarity measures` collapse."""
    if len(token) > 4:
        if token.endswith("ies"):
            return token[:-3] + "y"
        if token.endswith(("ses", "xes", "zes", "ches", "shes")):
            return token[:-2]
        if token.endswith("s") and not token.endswith("ss"):
            return token[:-1]
    return token


def concept_key(label: str) -> frozenset[str]:
    """Order- and plural-insensitive identity for a concept label."""
    return frozenset(stem(t) for t in tokens(label))


def is_redundant(label: str, existing: Iterable[frozenset[str]]) -> bool:
    """True when the label is a paraphrase or sub/superstring of one already taken."""
    key = concept_key(label)
    if not key:
        return True
    return any(key <= other or other <= key for other in existing)


def paper_tokens(paper: Paper) -> set[str]:
    text = " ".join([paper.title, " ".join(paper.keywords), " ".join(paper.topic_path), " ".join(paper.fields)])
    return {stem(t) for t in tokens(text)}


def topical_papers(question: str, papers: list[Paper]) -> set[str]:
    """Paper ids that still belong to the root question.

    A sub-query like `gene ontology terms` retrieves real papers about the wrong subject;
    without this gate the map drifts into a neighbouring literature and the saturation
    check reads that drift as productivity.

    Known limit: the test is token overlap, so a paper that happens to share two common
    root words ("search", "process") survives. Corpus-frequency weighting was tried and
    could not separate those cases without starving on-topic papers too.
    """
    root = {stem(t) for t in tokens(canonical_root(question))}
    rest = {stem(t) for t in tokens(question)} - root
    keep: set[str] = set()
    for paper in papers:
        found = paper_tokens(paper)
        hits, extra = len(root & found), len(rest & found)
        if hits >= 2 or (hits >= 1 and extra >= 1):
            keep.add(paper.paper_id)
    return keep


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

# "however" is deliberately absent: it is a discourse marker, so the words after it
# are the subject of the sentence, not the thing that goes wrong.
LIMITATION_CUES = ("limitation", "limitations", "limited", "fails", "fail",
                   "cannot", "suffers", "suffer", "degrades", "degrade", "brittle",
                   "struggles", "struggle", "unable", "drawback", "drawbacks", "shortcoming",
                   "shortcomings", "bottleneck", "prone", "sensitive", "expensive",
                   "intractable", "overfits", "overfitting", "underperforms")


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|;\s+", text or "") if part.strip()]


def limitation_phrases(abstract: str, root_tokens: set[str] | None = None) -> list[tuple[str, str]]:
    """(phrase, sentence) pairs naming what a paper says goes wrong.

    `failure_mode` grounded on 0 of 4 self-test questions because limitations are written
    as sentences ("however, the method fails on rare senses"), never as keywords. This
    reads the words that follow the cue, which is where the object of the complaint sits.
    """
    found: list[tuple[str, str]] = []
    for sentence in _sentences(abstract):
        words = re.findall(r"[a-z][a-z0-9-]+", sentence.lower())
        # The sentence has to be talking about the question. `current chemical libraries`
        # was a real grounded limitation for a question about stopping criteria.
        if root_tokens and not ({stem(w) for w in words} & root_tokens):
            continue
        for index, word in enumerate(words):
            if word not in LIMITATION_CUES:
                continue
            tail = [w for w in words[index + 1:index + 8]
                    if w not in STOPWORDS and w not in LIMITATION_CUES
                    and w not in FILLER and len(w) > 2]
            if len(tail) >= 2:
                found.append((" ".join(tail[:3]), sentence[:200]))
    return found


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
    # `computer science` reached the top ten of 8/8 runs because the generic-field list
    # was only checked on paper.fields, while the same label also arrives as an OpenAlex
    # keyword, as a topic, and as a title n-gram. One gate, all sources.
    if key in GENERIC_FIELDS:
        return
    parts = key.split()
    if parts[0] in WEAK_EDGE or parts[-1] in WEAK_EDGE:
        return
    if any(part in FILLER for part in parts):
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

def _guard_relation(key: str, relation: str, paper_ids: set[str], on_topic: set[str] | None) -> str:
    """Keep a down-relation label only when it is about the question.

    Two measured failures this closes: `high performance computing` scored as a
    measurement because it contains "performance", and `kidney failure` scored as a
    failure mode because it contains "failure". A third is the gap cue itself
    (`failure mode`) becoming the finding when a gap query goes out.
    """
    if relation not in DOWN_RELATIONS:
        return relation
    term_tokens = {stem(t) for t in key.split()}
    if term_tokens <= {stem(t) for t in GAP_CUE_TOKENS.get(relation, set())}:
        return "topic"
    if on_topic is not None and not (paper_ids & on_topic):
        return "topic"
    return relation


def extract_terms(question: str, papers: list[Paper], on_topic: set[str] | None = None,
                  background: set[str] | None = None) -> list[Term]:
    """`background` holds labels that ranked highly on unrelated past questions. They are
    the field's wallpaper, not this question's answer, so their score is halved."""
    q_tokens = set(tokens(question))
    root_tokens = {stem(t) for t in tokens(canonical_root(question))}
    candidates: dict[str, CandidateEvidence] = {}
    for paper in papers:
        context = f"{paper.title}. {paper.abstract}"
        for keyword in paper.keywords:
            _add_candidate(candidates, keyword, paper, _relation_for(keyword, context, "keyword", q_tokens), paper.title, explicit=True)
        for field_name in paper.fields:
            _add_candidate(candidates, field_name, paper, "neighbor_field", paper.title, explicit=True)
        for topic in paper.topic_path:
            # A provider's topic hierarchy names the neighbourhood, not the finding.
            _add_candidate(candidates, topic, paper, "neighbor_field", paper.title, explicit=True)
        for phrase in _ngrams(paper.title, 2, 4):
            _add_candidate(candidates, phrase, paper, _relation_for(phrase, context, "title", q_tokens), paper.title, in_title=True)
        for phrase, sentence in limitation_phrases(paper.abstract, root_tokens):
            # explicit: the paper says this itself, in a sentence kept as the example.
            # Every paper words its limitation differently, so demanding two papers agree
            # on the wording left `failure_mode` empty on 4/4 live runs.
            _add_candidate(candidates, phrase, paper, "failure_mode", sentence, explicit=True)
        for phrase in _ngrams(paper.abstract, 2, 4):
            phrase_tokens = set(tokens(phrase))
            if any(phrase_tokens & marker_set for marker_set in RELATION_MARKERS.values()):
                _add_candidate(candidates, phrase, paper, _relation_for(phrase, context, "abstract", q_tokens), paper.title)
    terms: list[Term] = []
    for key, ev in candidates.items():
        support = len(ev.papers)
        relation = _guard_relation(key, ev.relation_votes.most_common(1)[0][0], ev.papers, on_topic)
        background_penalty = 0.5 if background and key in background else 1.0
        score = 1.25 * math.log1p(support) + 0.34 * min(ev.explicit_count, 3) + 0.18 * min(ev.title_count, 3) + 0.16 * min(len(ev.queries), 4) + 0.20 * min(len(ev.providers), 2) + 0.35 * (len(set(key.split()) & q_tokens) / max(len(set(key.split())), 1)) + 0.08 * min(len(key.split()), 4)
        score *= background_penalty
        if support >= 3 or (support >= 2 and (ev.explicit_count or ev.title_count)):
            confidence = "high"
        elif support >= 2 or ((ev.explicit_count >= 1 or ev.title_count >= 1) and len(key.split()) >= 2 and relation in {*REQUIRED_RELATIONS, "core", "topic"}):
            confidence = "medium"
        else:
            confidence = "low"
        if support == 1 and ev.explicit_count == 0:
            continue
        terms.append(Term(key, relation, round(score, 3), confidence, sorted(ev.papers), sorted(ev.providers), sorted(ev.queries), ev.examples))
    ranked = sorted(terms, key=lambda t: (t.confidence == "high", t.score), reverse=True)
    return dedupe_terms(ranked)


def dedupe_terms(ranked: list[Term]) -> list[Term]:
    """Drop a term whose stemmed word set contains, or is contained by, a stronger one.

    `search algorithm` and `search algorithms` both reached one top five; the concept tree
    already collapsed pairs like that, the reported terms did not.
    """
    kept: list[Term] = []
    taken: list[frozenset[str]] = []
    for term in ranked:
        key = concept_key(term.text)
        if not key or any(key <= other or other <= key for other in taken):
            continue
        kept.append(term)
        taken.append(key)
    return kept

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

def canonical_root(question: str, max_tokens: int = 6) -> str:
    """Single root topic for the whole run. One question -> one canonical node."""
    selected = tokens(question)
    return " ".join(selected[:max_tokens]) or question.strip().lower()


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
        for node, query in round_queries:
            searched.add(query)
            for provider in providers:
                provider_calls[provider.name] += 1
                try:
                    found = provider.search(query, results_per_query)
                    for p in found:
                        p.found_by = list(dict.fromkeys([*p.found_by, query]))
                    incoming.extend(found)
                except ProviderError as exc:
                    provider_failures[provider.name] += 1
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
            "limitations": [t.to_dict() for t in top_terms(terms, "failure_mode", 5, grounded_only=True)],
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
            "graph": build_graph(question, top, kept_papers)}


def run_router(question: str, providers: list[SearchProvider], *, max_rounds: int = 6, results_per_query: int = 20) -> dict:
    """Backward-compat wrapper: default policy, single root."""
    return run_agent(question, providers, AgentPolicy(max_rounds=max(1, max_rounds)),
                     results_per_query=results_per_query)
