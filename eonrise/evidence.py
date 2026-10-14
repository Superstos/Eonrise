"""Papers in, grounded and ranked terms out.

Split out of engine.py on architecture review: the traversal decides what to search and
when to stop, this module decides what a corpus actually says. Nothing here knows about
rounds, budgets or providers.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from itertools import dropwhile, groupby, islice, takewhile
from typing import Iterable

from .models import Paper, Term

DOWN_RELATIONS = ("mechanism", "measurement", "failure_mode", "method")

REQUIRED_RELATIONS = ("mechanism", "measurement", "failure_mode", "method", "neighbor_field")
STOPWORDS = {"a","an","and","are","as","at","be","been","being","but","by","can","could","did","do","does","for","from","had","has","have","how","if","in","into","is","it","its","may","might","more","most","of","on","or","our","should","so","than","that","the","their","them","then","there","these","they","this","to","under","using","was","we","were","what","when","where","which","who","why","will","with","within","without","would","across","reliably","change","effect","effects","impact","study","paper","papers","research","results","new","based","approach","using","used","large","system",
             # Conjunctions and quantifiers: `because` took one of six root slots in "when should a
             # search stop because it has found enough relevant papers".
             "because","since","while","whether","although","though","unless","until","also","just","only","enough","very","much","any","some","all","each","every","such","not","no","nor","yet","still","even","either","neither","both"}
RELATION_MARKERS = {
    "mechanism": {"mechanism","process","pathway","architecture","dynamics","feedback","retrieval","storage","encoding","consolidation","adaptation","mediation","causal","intervention","memory","attention","learning","policy","control","update","resolution","propagation","interaction","inference"},
    "measurement": {"estimate","estimator","estimation","coverage","completeness","metric","measure","measurement","accuracy","score","index","scale","benchmark","evaluation","reliability","validity","robustness","performance","recall","precision","rate","assessment","test","testing","fidelity","consistency","generalization","sensitivity","specificity","error","outcome"},
    "failure_mode": {"failure","failures","limitation","limitations","bias","confound","confounding","artifact","error","errors","weakness","risk","vulnerability","interference","hallucination","stale","obsolete","invalid","fragility","degradation","drift","collapse","forgetting","injection","noise","misalignment"},
    "method": {"experiment","experimental","randomized","controlled","trial","ablation","longitudinal","cross-sectional","simulation","survey","interview","cohort","case-control","meta-analysis","systematic review","protocol","replication","baseline","comparison","comparative","observational","ethnography","factorial","blinded","sampling","evaluation protocol","controlled evaluation","controlled experiment","comparative testing","component assessment","component-level assessment","human annotation","prediction-powered inference","reproducible workflow","metric validation"},
}
GROUNDED = {"high", "medium"}
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
    stated_limitation: bool = False  # the paper wrote this limitation in a sentence
    abstract_count: int = 0  # times the term was read out of an abstract, not a label
    relation_votes: Counter | None = None
    def __post_init__(self) -> None:
        if self.relation_votes is None:
            self.relation_votes = Counter()

    def see(self, paper: Paper, example: str, kind: str) -> None:
        """Count one sighting of the term in a paper; `kind` says where it was read."""
        explicit, in_title, stated_limitation, from_abstract = _SIGHTINGS[kind]
        self.papers.add(paper.paper_id)
        self.providers.add(paper.provider)
        self.queries.update(paper.found_by)
        if example and example not in self.examples and len(self.examples) < 3:
            self.examples.append(example)
        self.explicit_count += int(explicit)
        self.title_count += int(in_title)
        self.stated_limitation = self.stated_limitation or stated_limitation
        self.abstract_count += int(from_abstract)

def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()

def split_words(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z][a-z0-9-]+", text.lower()) if t not in STOPWORDS and len(t) > 1]

def question_words(question: str) -> list[str]:
    # Words a question needs for grammar but no paper is about. "why do inventions often come
    # from" rooted a run on `often come` and retrieved "Do You Come Here Often?".
    words = split_words(question)
    return [w for w in words if w not in QUESTION_FILLER] or words


def compact_question(question: str, max_tokens: int = 8) -> str:
    selected = question_words(question)
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
QUESTION_FILLER = FILLER | {
    "often", "sometimes", "always", "never", "come", "comes", "came", "coming", "get", "gets",
    "getting", "got", "keep", "keeps", "kept", "keeping", "go", "goes", "going", "one", "two",
    "three", "way", "ways", "thing", "things", "someone", "something"}
WEAK_EDGE = {"between", "through", "via", "within", "among", "toward", "towards", "into",
             "under", "over", "upon", "per", "about", "against", "after", "before",
             "during", "such", "both", "each", "other", "others", "same", "given",
             "present", "presents", "shows", "show", "propose", "proposed", "proposes",
             "provide", "provides", "including", "include", "includes", "however"}


# -ies -> -y; -es after s, x, z, ch, sh; any other final s except -ss.
_PLURAL = re.compile(r"ies$|(?:(?<=[sxz])|(?<=[cs]h))es$|(?<!s)s$")


def to_singular(token: str) -> str:
    """Crude singulariser so `similarity measure` and `similarity measures` collapse."""
    if len(token) <= 4:
        return token
    return _PLURAL.sub(lambda match: "y" if match.group() == "ies" else "", token, count=1)


# Derivational endings, longest first. `to_singular` only folds plurals, so a question asking for
# "analogous" solutions shared no word with papers titled "analogy" or "analogical", and
# "retrieve" missed "retrieval": 67 papers on exactly the question scored 0 on topic.
_FAMILY_ENDINGS = ("ically", "ical", "ation", "ition", "ously", "ous", "ive", "ness", "ment",
                   "ity", "ing", "ed", "al", "ic", "y", "e")


def word_family(token: str) -> str:
    """Word family for topical matching: `analogy`, `analogous` and `analogical` -> `analog`.

    One ending is removed and at least four letters must remain. `-er` is never stripped
    (`discover`/`discovery` must meet), and `-al` is kept after `er` so that `general`
    does not join `generation`.
    """
    # `to_singular` would read the s of -ous as a plural: `analogous` -> `analogou`.
    token = token if token.endswith("ous") else to_singular(token)
    ending = next((ending for ending in _FAMILY_ENDINGS if _strippable(token, ending)), "")
    return _strip_ending(token, ending) if ending else token


def _strippable(token: str, ending: str) -> bool:
    return token.endswith(ending) and len(token) - len(ending) >= 4


def _undouble(base: str) -> str:
    """stopping -> stopp -> stop; `-ll`, `-ss` and `-zz` stems keep both letters."""
    return base[:-1] if base[-1] == base[-2] and base[-1] not in "lsz" else base


def _strip_ending(token: str, ending: str) -> str:
    base = token[:-len(ending)]
    if ending == "al" and base.endswith("er"):
        return token
    return _undouble(base) if ending in ("ing", "ed") else base


def concept_key(label: str) -> frozenset[str]:
    """Order- and plural-insensitive identity for a concept label."""
    return frozenset(to_singular(t) for t in split_words(label))


def _doi_key(value: str) -> str:
    """Bare DOIs and DOI URLs identify the same paper."""
    doi = re.sub(r"\s+", "", str(value or "").lower())
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)
    return re.sub(r"^doi:", "", doi).strip().strip("/")


def _paper_dedupe_key(paper: Paper) -> str:
    doi = _doi_key(paper.doi)
    if doi:
        return f"doi:{doi}"
    return normalize(paper.title or paper.paper_id)


def is_redundant(label: str, existing: Iterable[frozenset[str]]) -> bool:
    """True when the label is a paraphrase or sub/superstring of one already taken."""
    key = concept_key(label)
    if not key:
        return True
    return any(key <= other or other <= key for other in existing)


MAX_LABEL_WORDS = 6
MAX_LABEL_CHARS = 80


def is_clean_label(key: str) -> bool:
    """A normalized label short and specific enough to be a concept, with no filler in it.

    `computer science` reached the top ten of 8/8 runs because the generic-field list was
    only checked on paper.fields, while the same label also arrives as an OpenAlex keyword,
    as a topic, and as a title n-gram. One gate, all sources.
    """
    parts = key.split()
    return (0 < len(parts) <= MAX_LABEL_WORDS and len(key) <= MAX_LABEL_CHARS and key not in GENERIC_FIELDS
            and not {parts[0], parts[-1]} & WEAK_EDGE and FILLER.isdisjoint(parts))


def canonical_root(question: str, max_tokens: int = 6) -> str:
    """Single root topic for the whole run. One question -> one canonical node."""
    selected = question_words(question)
    return " ".join(selected[:max_tokens]) or question.strip().lower()

def _families(text: str) -> set[str]:
    return {word_family(t) for t in split_words(text)}


def paper_word_families(paper: Paper) -> set[str]:
    return _families(" ".join([paper.title, " ".join(paper.keywords), " ".join(paper.topic_path), " ".join(paper.fields)]))


def _belongs(found: set[str], root: set[str], rest: set[str]) -> bool:
    hits, extra = len(root & found), len(rest & found)
    single_word_question = len(root) == 1 and not rest
    return hits >= 2 or (hits >= 1 and (extra >= 1 or single_word_question))


def topical_papers(question: str, papers: list[Paper]) -> set[str]:
    """Paper ids that still belong to the root question.

    A sub-query like `gene ontology terms` retrieves real papers about the wrong subject;
    without this gate the map drifts into a neighbouring literature and the saturation
    check reads that drift as productivity.

    Known limit: the test is token overlap, so a paper that happens to share two common
    root words ("search", "process") survives. Corpus-frequency weighting was tried and
    could not separate those cases without starving on-topic papers too.
    """
    root = _families(canonical_root(question))
    rest = _families(question) - root
    return {paper.paper_id for paper in papers if _belongs(paper_word_families(paper), root, rest)}


def grounding_papers(question: str, papers: list[Paper], on_topic: set[str]) -> set[str] | None:
    """Papers allowed to ground concepts. The gate's set when it is big enough.

    Below MIN_TOPICAL_CORPUS every retrieved paper used to vote, so one gate miss handed
    the map to whatever else was in the corpus: 99 analogy papers set beside 74 stopping-rule
    papers put `literature based discovery` and `link prediction` in the concepts of a
    question about when a search should stop. Now the best-matching papers top the gate up
    to the minimum instead: gate first, then question words in title and labels, then in the
    abstract. A paper with no question word at all never votes. None only when nothing does.
    """
    if len(on_topic) >= MIN_TOPICAL_CORPUS:
        return on_topic
    return set(_best_voters(_families(question), papers, on_topic)) or None


def _vote_rank(paper: Paper, words: set[str], on_topic: set[str]) -> tuple[bool, int, int]:
    """Gate first, then question words in title and labels, then in the abstract."""
    return (paper.paper_id in on_topic, len(words & paper_word_families(paper)),
            len(words & _families(paper.abstract)))


def _best_voters(words: set[str], papers: list[Paper], on_topic: set[str]) -> list[str]:
    ranked = sorted(((_vote_rank(paper, words, on_topic), paper.paper_id) for paper in papers), reverse=True)
    return [paper_id for rank, paper_id in ranked if any(rank)][:MIN_TOPICAL_CORPUS]


_RUN_BREAKS = STOPWORDS | set(".!?;,:()")


def _content_runs(text: str) -> list[list[str]]:
    """Unbroken runs of content words; punctuation and stopwords end a run."""
    tokens = re.findall(r"[a-z][a-z0-9-]+|[.!?;,:()]", text.lower())
    return [list(run) for is_break, run in groupby(tokens, key=lambda token: token in _RUN_BREAKS) if not is_break]

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
                   "intractable", "overfits", "overfitting", "underperforms",
                   # v0.13: on 364 labelled abstract sentences the list above found 25 of 75
                   # limitations (precision 0.89); with these, 36 of 75 at 0.88.
                   "miss", "misses", "biased", "exaggerate", "exaggerates", "overestimate",
                   "overestimates", "underestimate", "underestimates", "inaccurate",
                   "misrepresent", "misrepresents", "lack", "lacks", "lacking", "vulnerable",
                   "fragile", "hampered", "hinder", "hinders", "overlook", "overlooks",
                   "ignore", "ignores", "omitting", "poorly", "difficult")
# Words that announce a limitation rather than name one. "Limitation stated: ..." and
# structured-abstract headings made `stated one designer` a failure mode.
LIMITATION_META = {"limitation", "limitations", "stated", "noted", "note", "notes", "motivation",
                   "drawback", "drawbacks", "weakness", "weaknesses", "shortcoming", "shortcomings",
                   "states", "highlights", "reports", "finds", "shows", "showing", "suggesting",
                   "indicating", "revealing"}
_HEADER = re.compile(r"^[^:]{0,48}:\s+")


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|;\s+", text or "") if part.strip()]


_LIMITATION_WORDS = set(LIMITATION_CUES) | LIMITATION_META


def _is_edge_word(word: str) -> bool:
    return word in WEAK_EDGE or word in FILLER or word.endswith("ly")


def _phrase_edge(run: list[str]) -> list[str]:
    run = list(dropwhile(_is_edge_word, [w for w in run if w not in _LIMITATION_WORDS]))
    return list(dropwhile(_is_edge_word, reversed(run)))[::-1]


def _limitation_body(sentence: str) -> str:
    """The sentence without a leading header that announces a limitation."""
    head = sentence.split(":", 1)[0].lower()
    announces = _HEADER.match(sentence) and set(re.findall(r"[a-z]+", head)) & LIMITATION_META
    return _HEADER.sub("", sentence) if announces else sentence


def _is_content(word: str) -> bool:
    return word[0].isalpha() and word not in STOPWORDS


def _is_skipped(word: str) -> bool:
    return word in STOPWORDS or word in LIMITATION_CUES or word.endswith("ly")


def _words_after(words: list[str], index: int) -> list[str]:
    """Up to four content words after the cue, past up to three stopwords, cues or adverbs."""
    j = index + 1
    while j < min(len(words), index + 5) and _is_skipped(words[j]):
        j += 1
    return list(islice(takewhile(_is_content, words[j:]), 4))


def _words_before(words: list[str], index: int) -> list[str]:
    """Up to four content words before the cue, past up to two stopwords."""
    k = index - 1
    while k > index - 3 and k >= 0 and words[k] in STOPWORDS:
        k -= 1
    return list(islice(takewhile(_is_content, reversed(words[:k + 1])), 4))[::-1]


def _pick(after: list[str], before: list[str]) -> list[str]:
    """The run after the cue names the condition; a one-word run defers to the subject before."""
    after, before = _phrase_edge(after), _phrase_edge(before)
    return after if len(after) >= 2 else before if len(before) >= 2 else after or before


def _first_limitation(words: list[str]) -> str:
    for index in (i for i, word in enumerate(words) if word in LIMITATION_CUES):
        phrase = " ".join(_pick(_words_after(words, index), _words_before(words, index)))
        if len(phrase) >= 5:
            return phrase
    return ""


def _about_question(words: list[str], root_tokens: set[str] | None) -> bool:
    # The sentence has to be talking about the question. `current chemical libraries`
    # was a real grounded limitation for a question about stopping criteria.
    return not root_tokens or bool({word_family(w) for w in words} & root_tokens)


def limitation_phrases(abstract: str, root_tokens: set[str] | None = None) -> list[tuple[str, str]]:
    """(phrase, sentence) pairs naming what a paper says goes wrong.

    `failure_mode` grounded on 0 of 4 self-test questions because limitations are written
    as sentences ("however, the method fails on rare senses"), never as keywords.

    v0.13: the phrase is one unbroken run of content words, never words gathered across
    stopwords ("prone to stop a trial at a random high" gave `stop trial random`). The run
    after the cue names the condition ("struggle with far analogies"); when it is a single
    word the run before names the subject ("past cases that cannot be retrieved"). A leading
    "Limitation stated:" header is dropped. One phrase per sentence, the first complaint.
    """
    found: list[tuple[str, str]] = []
    for sentence in _sentences(abstract):
        # Single letters kept: dropping "a" joined "stop a trial" into `stop trial`.
        words = re.findall(r"[a-z][a-z0-9-]*|[.,;:()!?]", _limitation_body(sentence).lower())
        phrase = _first_limitation(words) if _about_question(words, root_tokens) else ""
        if phrase:
            found.append((phrase, sentence[:200]))
    return found


# One list for both jobs. A phrase used to enter the candidates because it held a
# measurement marker (`recall`, `precision`, `measure`) and was then classified from a
# shorter list as a plain topic: `average precision` and `target recall` never grounded, and
# both v0.10 self-runs reported measurement as empty.
MEASUREMENT_WORDS = {"accuracy", "accurate", "metric", "metrics", "score", "scores", "rate", "rates",
                     "benchmark", "evaluation", "reliability", "validity", "robustness", "performance",
                     "fidelity", "consistency", "generalization", "sensitivity", "assessment",
                     "precision", "recall", "specificity", "measure", "measures", "measurement",
                     "measurements", "estimate", "estimates", "estimator", "estimation",
                     "coverage", "completeness", "index"}


_METHOD_PHRASES = ("fault injection", "ablation", "controlled trial", "randomized trial", "controlled comparison", "systematic review", "meta analysis", "stress testing", "trace analysis", "controlled evaluation", "controlled experiment", "evaluation protocol", "comparative testing", "component-level assessment", "metric validation")
# First match wins, in this order.
_WORD_RELATIONS = (
    ("failure_mode", {"failure", "failures", "stale", "obsolete", "invalid", "fragility", "bias", "confound", "vulnerability", "degradation", "interference", "hallucination"}),
    ("measurement", MEASUREMENT_WORDS),
    ("method", {"experiment", "experimental", "randomized", "controlled", "trial", "ablation", "longitudinal", "simulation", "survey", "cohort", "replication", "baseline", "sampling", "comparative", "annotation", "validation", "protocol"}),
    ("mechanism", RELATION_MARKERS["mechanism"]),
)
_ALL_MARKERS = set().union(*RELATION_MARKERS.values())


def _marked_relation(term: str) -> str:
    if any(phrase in normalize(term) for phrase in _METHOD_PHRASES):
        return "method"
    words = set(split_words(term))
    return next((relation for relation, markers in _WORD_RELATIONS if words & markers), "")


def _relation_for(term: str, source_kind: str, question_tokens: set[str]) -> str:
    marked = _marked_relation(term)
    if marked:
        return marked
    if source_kind == "broader_topic":
        return "neighbor_field"
    return "core" if set(split_words(term)) & question_tokens else "topic"


# Where a term was read -> (explicit, in_title, stated_limitation, from_abstract).
# Explicit: the paper names the term itself, as a label or in a limitation sentence.
_SIGHTINGS = {
    "keyword": (True, False, False, False),
    "label": (True, False, False, False),
    "title": (False, True, False, False),
    "limitation": (True, False, True, True),
    "abstract": (False, False, False, True),
}
# A provider's topic hierarchy names the neighbourhood, not the finding.
_FIXED_RELATIONS = {"label": "neighbor_field", "limitation": "failure_mode"}
_GAP_CUE_SINGULARS = {relation: {to_singular(t) for t in tokens} for relation, tokens in GAP_CUE_TOKENS.items()}


def _guard_relation(key: str, relation: str, paper_ids: set[str], on_topic: set[str] | None, abstract_backed: bool = True) -> str:
    """Keep a down-relation label only when it is about the question.

    Two measured failures this closes: `high performance computing` scored as a
    measurement because it contains "performance", and `kidney failure` scored as a
    failure mode because it contains "failure". A third is the gap cue itself
    (`failure mode`) becoming the finding when a gap query goes out.

    A provider's subject label is free and infinite; a sentence costs a real paper. Without
    the abstract check the cheapest evidence outranks the truest, and a brief reports
    `service oriented architecture and web services` as the question's mechanism with a
    paper title as its proof. Measured on 7 saved runs: 13 of 30 down-relation terms had
    never been read out of an abstract, and every obvious junk label was among them.
    """
    if relation not in DOWN_RELATIONS:
        return relation
    on_question = on_topic is None or bool(paper_ids & on_topic)
    return relation if abstract_backed and on_question and not _is_gap_cue(key, relation) else "topic"


def _is_gap_cue(key: str, relation: str) -> bool:
    """The gap query's own cue words (`failure mode`) coming back as the finding."""
    return {to_singular(t) for t in key.split()} <= _GAP_CUE_SINGULARS[relation]


def _confidence(key: str, ev: CandidateEvidence) -> str:
    """Two papers make a labelled term high, three an unlabelled one; a lone named phrase is medium."""
    support = len(ev.papers)
    labelled = bool(ev.explicit_count or ev.title_count)
    if support >= 3 - labelled:
        return "high"
    return "medium" if support >= 2 or len(key.split()) >= 2 else "low"


@dataclass
class _TermReader:
    """Reads candidate terms out of papers, then grades them into Terms."""

    question: str
    on_topic: set[str] | None
    background: set[str] | None
    found: dict[str, CandidateEvidence] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.question_words = set(split_words(self.question))
        self.root_families = _families(canonical_root(self.question))

    def add(self, term: str, paper: Paper, kind: str, example: str = "") -> None:
        key = normalize(term)
        if not is_clean_label(key):
            return
        relation = _FIXED_RELATIONS.get(kind) or _relation_for(term, kind, self.question_words)
        item = self.found.setdefault(key, CandidateEvidence(set(), set(), set(), []))
        item.see(paper, example or paper.title, kind)
        item.relation_votes[relation] += 1

    def read(self, paper: Paper) -> None:
        for keyword in paper.keywords:
            self.add(keyword, paper, "keyword")
        for label in (*paper.fields, *paper.topic_path):
            self.add(label, paper, "label")
        for phrase in _ngrams(paper.title, 2, 4):
            self.add(phrase, paper, "title")
        self.read_abstract(paper)

    def read_abstract(self, paper: Paper) -> None:
        for phrase, sentence in limitation_phrases(paper.abstract, self.root_families):
            # Every paper words its limitation differently, so demanding two papers agree
            # on the wording left `failure_mode` empty on 4/4 live runs.
            self.add(phrase, paper, "limitation", sentence)
        for phrase in _ngrams(paper.abstract, 2, 4):
            if set(split_words(phrase)) & _ALL_MARKERS:
                self.add(phrase, paper, "abstract")

    def _score(self, key: str, ev: CandidateEvidence) -> float:
        words = set(key.split())
        score = (1.25 * math.log1p(len(ev.papers)) + 0.34 * min(ev.explicit_count, 3) + 0.18 * min(ev.title_count, 3)
                 + 0.16 * min(len(ev.queries), 4) + 0.20 * min(len(ev.providers), 2)
                 + 0.35 * (len(words & self.question_words) / max(len(words), 1)) + 0.08 * min(len(key.split()), 4))
        # Background labels ranked highly on unrelated past questions: wallpaper, halved.
        return score * (0.5 if self.background and key in self.background else 1.0)

    def term(self, key: str, ev: CandidateEvidence) -> Term:
        voted = ev.relation_votes.most_common(1)[0][0]
        relation = _guard_relation(key, voted, ev.papers, self.on_topic, ev.abstract_count > 0)
        return Term(key, relation, round(self._score(key, ev), 3), _confidence(key, ev), sorted(ev.papers),
                    sorted(ev.providers), sorted(ev.queries), ev.examples, stated_limitation=ev.stated_limitation)

    def terms(self) -> list[Term]:
        # One paper is enough only when the paper names the term itself.
        return [self.term(key, ev) for key, ev in self.found.items() if len(ev.papers) > 1 or ev.explicit_count]


def extract_terms(question: str, papers: list[Paper], on_topic: set[str] | None = None,
                  background: set[str] | None = None) -> list[Term]:
    """`background` holds labels that ranked highly on unrelated past questions. They are
    the field's wallpaper, not this question's answer, so their score is halved."""
    reader = _TermReader(question, on_topic, background)
    for paper in papers:
        reader.read(paper)
    ranked = sorted(reader.terms(), key=lambda t: (t.confidence == "high", t.score), reverse=True)
    return dedupe_terms(ranked)


def dedupe_terms(ranked: list[Term]) -> list[Term]:
    """Drop a term whose stemmed word set contains, or is contained by, a stronger one.

    `search algorithm` and `search algorithms` both reached one top five; the concept tree
    already collapsed pairs like that, the reported terms did not.
    """
    kept: list[Term] = []
    taken: list[frozenset[str]] = []
    for term in ranked:
        if is_redundant(term.text, taken):
            continue
        kept.append(term)
        taken.append(concept_key(term.text))
    return kept

def _merged(old: list[str], new: list[str]) -> list[str]:
    return list(dict.fromkeys([*old, *new]))


def _absorb(old: Paper, new: Paper) -> None:
    """Fold a duplicate's provenance and labels into the copy already kept."""
    old.found_by = _merged(old.found_by, new.found_by)
    old.keywords = _merged(old.keywords, new.keywords)
    old.fields = _merged(old.fields, new.fields)
    old.topic_path = _merged(old.topic_path, new.topic_path)
    if not old.venue and new.venue: old.venue = new.venue
    if not old.abstract and new.abstract: old.abstract = new.abstract


def _dedupe_papers(existing: list[Paper], incoming: Iterable[Paper]) -> tuple[list[Paper], int]:
    by_key = {_paper_dedupe_key(p): p for p in existing}
    added = 0
    for paper in incoming:
        key = _paper_dedupe_key(paper)
        if key in by_key:
            _absorb(by_key[key], paper)
            continue
        by_key[key] = paper
        added += 1
    return list(by_key.values()), added

def top_terms(terms: list[Term], relation: str | None = None, limit: int = 5, grounded_only: bool = False) -> list[Term]:
    selected = [t for t in terms if relation in (None, t.relation)]
    return (_grounded(selected) if grounded_only else selected)[:limit]


def _grounded(terms: list[Term]) -> list[Term]:
    return [t for t in terms if t.confidence in GROUNDED]

def coverage(terms: list[Term], minimum_per_relation: int = 2) -> tuple[dict[str, list[str]], list[str]]:
    covered, gaps = {}, []
    for relation in REQUIRED_RELATIONS:
        items = top_terms(terms, relation, limit=5, grounded_only=True)
        covered[relation] = [item.text for item in items]
        if len(items) < minimum_per_relation: gaps.append(relation)
    return covered, gaps

