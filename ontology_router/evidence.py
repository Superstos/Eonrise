"""Papers in, grounded and ranked terms out.

Split out of engine.py on architecture review: the traversal decides what to search and
when to stop, this module decides what a corpus actually says. Nothing here knows about
rounds, budgets or providers.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from .models import Paper, Term

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


def canonical_root(question: str, max_tokens: int = 6) -> str:
    """Single root topic for the whole run. One question -> one canonical node."""
    selected = tokens(question)
    return " ".join(selected[:max_tokens]) or question.strip().lower()

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
