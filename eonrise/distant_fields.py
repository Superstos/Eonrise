"""Distant papers that share the question's shape: the product, ranked.

The topical gate keeps the papers about the question and the map is read from them. Every
other paper used to vanish from the brief, although the reason Eonrise exists is that a
problem half solved here is often solved in another field. An agent had to list the dropped
titles with a script and read all of them.

Borrowed, with the evidence in `tests/fixtures/crossfield_gold.json`:

- MAC/FAC (Forbus, Gentner and Law): a cheap surface pass proposes, structure decides. The
  gate is the surface pass; this module is the structural one.
- Purpose/mechanism analogy mining (Hope et al.): match what a paper does and what goes wrong,
  not what it is about. The signature is the run's grounded concepts, never field labels.
- Mechanism skeletons ("same problem, different field"): a paper that shares two different
  kinds of concept, say a mechanism and a failure mode, is a shape match; one that shares a
  single word is a coincidence.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from .evidence import DOWN_RELATIONS, GENERIC_FIELDS, extract_terms, word_family, normalize, split_words
from .models import Paper, Term

DISTANT_PAPER_LIMIT = 8
SNIPPET_CHARS = 240
# Words that open the sentence saying what a paper did, rather than its background.
METHOD_CUE = re.compile(r"\b(we|this (study|paper|review|article)|results?|found|show(s|ed)?|propos|develop|test(ed|s)?|compar)", re.I)
# A sentence about what others should do next is not what this paper did.
OUTLOOK = re.compile(r"\b(future (research|work|stud)|further (research|work|stud)|should|we recommend|more research)", re.I)
# Journal furniture extracted with the abstract: headers, volume lines, licences.
FURNITURE = re.compile(r"[¦|©]|\b(volume \d+|issue \d+|all rights reserved|creative commons|original article)\b", re.I)


def _families_in_order(text: str) -> list[str]:
    # Hyphens split: `capture-recapture` must meet `capture mark recapture`.
    return [word_family(t) for t in split_words(text.replace("-", " "))]


def _adjacent_families(text: str, widths: set[int]) -> set[frozenset[str]]:
    """Word families that sit next to each other, per sentence-free run of words.

    A concept is shared when its words appear together. Bag-of-words containment matched
    `accumulation curve` in "Curve fitting for accumulation of snow"."""
    seq = _families_in_order(text)
    return {frozenset(seq[i:i + n]) for n in widths for i in range(len(seq) - n + 1)}


def _field_label(paper: Paper) -> str:
    for label in (*paper.fields, *paper.topic_path, paper.venue):
        if label and normalize(label) not in GENERIC_FIELDS:
            return label
    return "unlabelled"


def question_shape(terms: list[Term]) -> list[tuple[str, frozenset[str], str]]:
    """(label, word families, relation) for every grounded concept that is not a field."""
    out = []
    for term in terms:
        out.extend(_term_shape(term))
    return out


def _term_shape(term):
    if term.confidence not in {"high", "medium"} or term.relation == "neighbor_field":
        return []
    seq = _families_in_order(term.text)
    if len(set(seq)) < 2:
        return []  # one word is a vocabulary hit, not a concept
    out = [(term.text, frozenset(seq), term.relation)]
    # A long concept also travels as its adjacent pairs: ecology writes
    # "capture-recapture" for what screening papers call "capture mark recapture".
    if len(seq) >= 3:
        out.extend(_shape_pairs(term, seq))
    return out


def _shape_pairs(term, seq):
    return [(term.text, frozenset(pair), term.relation)
            for pair in zip(seq, seq[1:]) if len(set(pair)) == 2]


def _paper_windows(paper, widths):
    return set().union(*(_adjacent_families(part, widths)
                         for part in (paper.title, paper.abstract, *paper.keywords)))


def _shared_concepts(sig, windows):  # label -> relation, once per concept
    return {label: rel for label, fams, rel in sig if fams in windows}


class _DistantRanking:
    def __init__(self, sig, papers):
        self.papers = papers
        widths = {len(fams) for _, fams, _ in sig}
        self.found = {p.paper_id: _shared_concepts(sig, _paper_windows(p, widths)) for p in papers}
        # A concept every paper mentions ranks nothing; weight by rarity across the run.
        # Adjacent only. Allowing one word between let "curve fitting accumulation" through.
        self.df = Counter(label for hits in self.found.values() for label in hits)

    def rank(self, on_topic, home_ids):
        self.home = _home_fields(self.papers, home_ids)
        ranked = []
        for paper in self.papers:
            if paper.paper_id in on_topic:
                continue
            hit = self._hit(paper)
            if hit is not None:
                ranked.append(hit)
        ranked.sort(key=lambda h: (h["score"], h["distant"]), reverse=True)
        return ranked

    def _hit(self, paper):
        shared = list(self.found[paper.paper_id].items())
        if not shared:
            return None
        kinds = {_relation_kind(rel) for _, rel in shared}
        score = self._shared_score(shared)
        if len(shared) < 2 and not kinds & {"down"}:
            return None  # one shared topic label is surface similarity, not shape
        return self._hit_record(paper, score * _kind_weight(kinds))

    def _hit_record(self, paper, score):
        shared = list(self.found[paper.paper_id].items())
        field = _field_label(paper)
        return {"paper_id": paper.paper_id, "title": paper.title, "year": paper.year,
                "url": paper.url or paper.doi, "field": field, "distant": field not in self.home,
                "shares": _shared_labels(shared),
                "what_they_did": what_they_did(paper, [label for label, _ in shared]),
                "score": round(score, 3)}

    def _shared_score(self, shared):
        return sum(self._concept_score(label, rel) for label, rel in shared)

    def _concept_score(self, label, rel):
        weight = 1.5 if rel in DOWN_RELATIONS else 1.0
        return weight * math.log(1 + len(self.papers) / self.df[label])


def what_they_did(paper: Paper, shared: list[str]) -> str:
    """The abstract sentence that best says what the paper did, or "" without an abstract.

    Agents mapped distant papers from titles and topic labels alone ("shares blockchain
    technology in education") and had to web-search each one. The sentence that names a
    method or a result and carries the shared concepts is the "what they did" step."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", paper.abstract or "")
                 if len(s.strip()) > 30 and not FURNITURE.search(s)]
    if not sentences:
        return ""
    words = {w for label in shared for w in split_words(label)}
    best = max(sentences, key=lambda s: (_did_score(s, words), -sentences.index(s)))
    return best if len(best) <= SNIPPET_CHARS else best[:SNIPPET_CHARS].rsplit(" ", 1)[0] + "…"


def _did_score(sentence, words):
    # A method or result cue outweighs shared words: the step is "what they did".
    shared = min(len(words & set(split_words(sentence))), 2)
    return 2 * bool(METHOD_CUE.search(sentence)) + shared - 3 * bool(OUTLOOK.search(sentence))


def _shared_labels(shared):
    return [label for label, _ in shared][:4]


def _relation_kind(relation):
    return "down" if relation in DOWN_RELATIONS else relation


def _pick_fields(ranked, limit):
    # One field must not fill the list: the point is the spread of places it was solved.
    picked, per_field = [], Counter()
    for hit in ranked:
        if per_field[hit["field"]] < 2:
            picked.append(hit)
            per_field[hit["field"]] += 1
        if len(picked) == limit:
            break
    return picked


def rank_distant_papers(terms: list[Term], papers: list[Paper], on_topic: set[str], limit: int = DISTANT_PAPER_LIMIT,
            home_ids: set[str] | None = None) -> list[dict]:
    """Off-gate papers ranked by how much of the question's grounded shape they carry.

    `on_topic` is excluded from the ranking (it grounded the signature); `home_ids`, the
    gate's own papers, decide which fields count as home. A paper topped up into the voting
    core is not evidence that its field is the question's: a biostatistics trial paper was
    labelled "same field" for a question about literature search."""
    sig = question_shape(terms)
    if not sig:
        return []
    home_ids = on_topic if home_ids is None else home_ids
    ranked = _DistantRanking(sig, papers).rank(on_topic, home_ids)
    return _pick_fields(ranked, limit)


def distant_queries(hits: list[dict], limit: int = 3) -> list[str]:
    """Searches that follow the harvest out of the home field: the concepts an other-field
    paper shares with the question, without the question's own domain words. On the v0.11
    stop-rule corpus these found 4 new other-field papers and no distractor, against 2 for
    the gap-cue searches; one scenario, so they are offered, not run."""
    out: list[str] = []
    for hit in sorted(hits, key=lambda h: not h.get("distant")):
        query = " ".join(dict.fromkeys(" ".join(hit["shares"][:2]).split()))
        if query and query not in out:
            out.append(query)
        if len(out) == limit:
            break
    return out


def concept_gate(question: str, papers: list[Paper], on_topic: set[str], rounds: int = 2,
                 min_shared: int = 2) -> set[str]:
    """Second stage of the topical gate: admit a paper that carries two of the concepts the
    gate's own papers ground, each as adjacent words (MAC/FAC: the word gate proposes, the
    concepts decide). Most on-topic papers never use the question's words: "literature-based
    discovery" and "bisociation" answer a question about analogous solutions.

    Token-level feedback was tried in v0.10 and drifted (6 of 10 unrelated papers admitted
    via `find`, `search`). Whole grounded concepts do not: on both gold sets, 2 rounds took
    on-topic recall 14 -> 31 of 47 and 2 -> 14 of 17, with 0 of 109 negatives admitted.
    Never bootstraps from nothing: an empty gate stays empty."""
    keep = set(on_topic)
    gate = _ConceptGate(question, papers)
    for _ in range(rounds):
        if not keep:
            break
        added = gate.additions(keep, min_shared)
        if not added:
            break
        keep |= added
    return keep


class _ConceptGate:
    def __init__(self, question, papers):
        self.question = question
        self.papers = papers

    def _shape(self, keep):
        selected = [p for p in self.papers if p.paper_id in keep]
        return question_shape(extract_terms(self.question, selected, keep))

    def additions(self, keep, min_shared):
        sig = self._shape(keep)
        widths = _signature_widths(sig)
        if not widths:
            return set()
        added = set()
        for paper in self.papers:
            if paper.paper_id in keep:
                continue
            windows = _paper_windows(paper, widths)
            if len(_shared_concepts(sig, windows)) >= min_shared:
                added.add(paper.paper_id)
        return added


def _signature_widths(sig):
    return {len(fams) for _, fams, _ in sig}


def _home_fields(papers, ids):
    return {_field_label(p) for p in papers if p.paper_id in ids}


def _kind_weight(kinds):
    return 1.25 if len(kinds) > 1 else 1.0
