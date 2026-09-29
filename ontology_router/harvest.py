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
from collections import Counter

from .evidence import DOWN_RELATIONS, GENERIC_FIELDS, family, normalize, tokens
from .models import Paper, Term

HARVEST_SIZE = 8


def _seq(text: str) -> list[str]:
    # Hyphens split: `capture-recapture` must meet `capture mark recapture`.
    return [family(t) for t in tokens(text.replace("-", " "))]


def _families(text: str) -> set[str]:
    return set(_seq(text))


def _windows(text: str, widths: set[int]) -> set[frozenset[str]]:
    """Word families that sit next to each other, per sentence-free run of words.

    A concept is shared when its words appear together. Bag-of-words containment matched
    `accumulation curve` in "Curve fitting for accumulation of snow"."""
    seq = _seq(text)
    return {frozenset(seq[i:i + n]) for n in widths for i in range(len(seq) - n + 1)}


def _field(paper: Paper) -> str:
    for label in (*paper.fields, *paper.topic_path, paper.venue):
        if label and normalize(label) not in GENERIC_FIELDS:
            return label
    return "unlabelled"


def signature(terms: list[Term]) -> list[tuple[str, frozenset[str], str]]:
    """(label, word families, relation) for every grounded concept that is not a field."""
    out = []
    for term in terms:
        if term.confidence in {"high", "medium"} and term.relation != "neighbor_field":
            seq = _seq(term.text)
            if len(set(seq)) < 2:
                continue  # one word is a vocabulary hit, not a concept
            out.append((term.text, frozenset(seq), term.relation))
            # A long concept also travels as its adjacent pairs: ecology writes
            # "capture-recapture" for what screening papers call "capture mark recapture".
            if len(seq) >= 3:
                out.extend((term.text, frozenset(pair), term.relation)
                           for pair in zip(seq, seq[1:]) if len(set(pair)) == 2)
    return out


def _has(windows: set[frozenset[str]], fams: frozenset[str]) -> bool:
    # Adjacent only. Allowing one word between let "curve fitting accumulation" through.
    return fams in windows


def harvest(terms: list[Term], papers: list[Paper], on_topic: set[str], limit: int = HARVEST_SIZE) -> list[dict]:
    """Off-gate papers ranked by how much of the question's grounded shape they carry."""
    sig = signature(terms)
    if not sig:
        return []
    widths = {len(fams) for _, fams, _ in sig}
    texts = {p.paper_id: set().union(*(_windows(part, widths) for part in (p.title, p.abstract, *p.keywords)))
             for p in papers}
    # A concept every paper mentions ranks nothing; weight by rarity across the run.
    def matches(pid: str) -> dict[str, str]:  # label -> relation, once per concept
        return {label: rel for label, fams, rel in sig if _has(texts[pid], fams)}
    found = {pid: matches(pid) for pid in texts}
    df = Counter(label for hits in found.values() for label in hits)
    home = {_field(p) for p in papers if p.paper_id in on_topic}
    ranked = []
    for paper in papers:
        if paper.paper_id in on_topic:
            continue
        shared = list(found[paper.paper_id].items())
        if not shared:
            continue
        kinds = {("down" if rel in DOWN_RELATIONS else rel) for _, rel in shared}
        score = sum((1.5 if rel in DOWN_RELATIONS else 1.0) * math.log(1 + len(papers) / df[label])
                    for label, rel in shared)
        if len(shared) < 2 and not kinds & {"down"}:
            continue  # one shared topic label is surface similarity, not shape
        field = _field(paper)
        ranked.append({"paper_id": paper.paper_id, "title": paper.title, "year": paper.year,
                       "url": paper.url or paper.doi, "field": field,
                       "distant": field not in home,
                       "shares": [label for label, _ in shared][:4],
                       "score": round(score * (1.25 if len(kinds) > 1 else 1.0), 3)})
    ranked.sort(key=lambda h: (h["score"], h["distant"]), reverse=True)
    # One field must not fill the list: the point is the spread of places it was solved.
    picked, per_field = [], Counter()
    for hit in ranked:
        if per_field[hit["field"]] < 2:
            picked.append(hit); per_field[hit["field"]] += 1
        if len(picked) == limit:
            break
    return picked
