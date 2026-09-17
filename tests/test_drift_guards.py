from __future__ import annotations

import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from ontology_router.engine import (
    GAP_QUERY_SLOTS,
    limitation_phrases,
    _guard_relation,
    _keep_score,
    concept_key,
    extract_terms,
    is_redundant,
    run_agent,
    topical_papers,
)
from ontology_router import cli
from ontology_router.models import STATUSES, AgentPolicy, Paper
from ontology_router import providers, report
from ontology_router.providers import CachedHttpClient, OpenAlexProvider

FIXTURE = Path(__file__).parent / "fixtures" / "papers.json"


def paper(pid: str, title: str, **kw) -> Paper:
    return Paper(pid, title, **kw)


class TopicalGateTests(unittest.TestCase):
    """The gate must drop drifted papers AND keep the on-topic ones."""

    question = "how can an automated ontology expansion and literature mapping system measure map quality"

    def test_drifted_paper_rejected(self):
        drifted = [paper("p1", "The Gene Ontology (GO) database and informatics resource"),
                   paper("p2", "Failure mode and effects analysis in manufacturing"),
                   paper("p3", "Stop and Search and Police Legitimacy")]
        self.assertEqual(topical_papers(self.question, drifted), set())

    def test_on_topic_paper_kept(self):
        wanted = [paper("p4", "Automated ontology expansion from literature: a mapping study"),
                  paper("p5", "Measuring the quality of automatically built ontology maps")]
        self.assertEqual(topical_papers(self.question, wanted), {"p4", "p5"})

    def test_single_word_topic_keeps_matching_papers(self):
        papers = [paper("on", "Memory consolidation during sleep"),
                  paper("off", "Coral reef bleaching")]
        self.assertEqual(topical_papers("memory", papers), {"on"})
        self.assertEqual(topical_papers("volcano", papers), set())
        self.assertEqual(topical_papers("the", papers), set())
        self.assertEqual(topical_papers("", papers), set())
        self.assertEqual(topical_papers("memory retention", papers), set())

    def test_keyword_only_evidence_still_counts(self):
        tagged = paper("p6", "A survey of concept drift", keywords=["ontology mapping"],
                       topic_path=["literature based discovery"])
        self.assertIn("p6", topical_papers(self.question, [tagged]))


class RelationGuardTests(unittest.TestCase):
    """Marker words alone must not label a relation, but real terms must survive."""

    def test_cue_only_term_demoted(self):
        self.assertEqual(_guard_relation("failure mode", "failure_mode", {"a"}, {"a"}), "topic")
        self.assertEqual(_guard_relation("limitation", "failure_mode", {"a"}, {"a"}), "topic")
        self.assertEqual(_guard_relation("failure modes", "failure_mode", {"a"}, {"a"}), "topic")
        self.assertEqual(_guard_relation("benchmarks", "measurement", {"a"}, {"a"}), "topic")

    def test_off_topic_support_demoted(self):
        self.assertEqual(_guard_relation("kidney failure", "failure_mode", {"off"}, {"on"}), "topic")

    def test_real_term_survives(self):
        self.assertEqual(_guard_relation("catastrophic forgetting", "failure_mode", {"on"}, {"on"}),
                         "failure_mode")

    def test_guard_is_inert_without_a_topic_set(self):
        self.assertEqual(_guard_relation("kidney failure", "failure_mode", {"off"}, None), "failure_mode")

    def test_extract_terms_applies_the_guard(self):
        papers = [paper(f"p{i}", "High performance computing for iterative search",
                        abstract="We report improved performance of a high performance computing cluster.")
                  for i in range(3)]
        guarded = extract_terms("when should an iterative search stop", papers, on_topic=set())
        self.assertNotIn("measurement", {t.relation for t in guarded if "performance" in t.text})


class _MixedProvider:
    """Eight on-topic papers plus a drifted cluster that shares one supporter."""

    name = "mixed"

    def search(self, query, limit=20):
        on = [paper(f"on{i}", f"Iterative search saturation and diminishing returns in exploration, study {i}",
                    abstract="A stopping criterion for iterative exploration based on saturation.",
                    keywords=["iterative search"]) for i in range(10)]
        off = [paper(f"off{i}", f"Protein structure and dynamics under iterative refinement, part {i}",
                     abstract="Protein structure and dynamics simulated with iterative refinement.",
                     keywords=["protein structure and dynamics"]) for i in range(12)]
        return on + off


class DriftedCorpusTests(unittest.TestCase):
    def test_drifted_cluster_cannot_ground_a_concept(self):
        result = run_agent("when should an iterative search or exploration process stop using saturation",
                           [_MixedProvider()], AgentPolicy(max_nodes=60, max_depth=3, max_rounds=2))
        labels = " ".join(c["label"] for c in result["concepts"])
        terms = " ".join(t["text"] for t in result["terms"])
        self.assertNotIn("protein", labels)
        self.assertNotIn("protein", terms)

    def test_on_topic_cluster_still_grounds(self):
        result = run_agent("when should an iterative search or exploration process stop using saturation",
                           [_MixedProvider()], AgentPolicy(max_nodes=60, max_depth=3, max_rounds=2))
        self.assertTrue(result["terms"], "on-topic evidence produced no terms at all")
        self.assertGreater(result["on_topic_papers"], 0)


class GenericLabelTests(unittest.TestCase):
    """Field names are the library's shelf labels, not the answer."""

    def test_generic_field_dropped_whatever_the_source(self):
        papers = [paper(f"g{i}", f"Word sense disambiguation for retrieval, study {i}",
                        keywords=["computer science", "word sense disambiguation"],
                        topic_path=["artificial intelligence"],
                        fields=["mathematics"]) for i in range(6)]
        texts = {t.text for t in extract_terms("word sense disambiguation in retrieval", papers)}
        self.assertNotIn("computer science", texts)
        self.assertNotIn("artificial intelligence", texts)
        self.assertNotIn("mathematics", texts)

    def test_real_keyword_survives(self):
        papers = [paper(f"g{i}", f"Word sense disambiguation for retrieval, study {i}",
                        keywords=["computer science", "word sense disambiguation"])
                  for i in range(6)]
        texts = {t.text for t in extract_terms("word sense disambiguation in retrieval", papers)}
        self.assertIn("word sense disambiguation", texts)

    def test_topic_hierarchy_lands_in_neighbor_field(self):
        papers = [paper(f"h{i}", f"Word sense disambiguation for retrieval, study {i}",
                        topic_path=["natural language processing"]) for i in range(6)]
        terms = {t.text: t.relation for t in extract_terms("word sense disambiguation", papers)}
        self.assertEqual(terms.get("natural language processing"), "neighbor_field")


class BackgroundPenaltyTests(unittest.TestCase):
    def _papers(self):
        return [paper(f"b{i}", f"Topic modeling and semantic relation extraction, study {i}",
                      keywords=["topic modeling", "semantic relation extraction"])
                for i in range(6)]

    def test_background_label_loses_score(self):
        papers = self._papers()
        plain = {t.text: t.score for t in extract_terms("semantic relation extraction", papers)}
        damped = {t.text: t.score for t in extract_terms("semantic relation extraction", papers,
                                                         background={"topic modeling"})}
        self.assertIn("topic modeling", plain)
        self.assertLess(damped["topic modeling"], plain["topic modeling"])
        self.assertEqual(damped["semantic relation extraction"],
                         plain["semantic relation extraction"])

    def test_no_background_changes_nothing(self):
        papers = self._papers()
        a = [t.text for t in extract_terms("semantic relation extraction", papers)]
        b = [t.text for t in extract_terms("semantic relation extraction", papers, background=set())]
        self.assertEqual(a, b)

    def test_memory_only_counts_unrelated_roots(self):
        import json
        import tempfile
        from ontology_router.memory import MemoryStore
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.jsonl"
            rows = [{"root_topic": f"root {i}", "concepts": [{"label": "computer science"},
                                                             {"label": f"unique {i}"}]}
                    for i in range(4)]
            path.write_text(chr(10).join(json.dumps(r) for r in rows), encoding="utf-8")
            store = MemoryStore(path)
            self.assertIn("computer science", store.background_labels("other root"))
            self.assertNotIn("unique 1", store.background_labels("other root"))
            # a label seen under only two other roots is not yet background
            self.assertNotIn("computer science", store.background_labels("other", min_roots=5))


class SubfieldOnlyTests(unittest.TestCase):
    """OpenAlex domain and field labels are shelf names; only the subfield is a neighbour."""

    def test_only_the_subfield_is_kept(self):
        http = OpenAlexKeylessTests._FakeHttp()
        papers = OpenAlexProvider(http).search("q", 5)
        self.assertEqual(papers[0].fields, ["Information Systems"])
        self.assertNotIn("Computer Science", papers[0].fields)
        self.assertNotIn("Physical Sciences", papers[0].fields)
        self.assertIn("Ontology engineering", papers[0].topic_path)


class LimitationExtractionTests(unittest.TestCase):
    """Papers state limitations in sentences, never in keywords."""

    def test_cue_sentence_yields_the_object_of_the_complaint(self):
        found = limitation_phrases("We present a tagger. The model fails on rare senses "
                                   "and low-resource languages.")
        self.assertTrue(found)
        self.assertIn("rare senses", found[0][0])

    def test_sentence_must_mention_the_question(self):
        off = "The assay is limited to current chemical libraries and reagent purity."
        self.assertEqual(limitation_phrases(off, {"iterative", "search", "saturation"}), [])

    def test_on_topic_sentence_survives_the_same_filter(self):
        on = "The search procedure is limited to convex saturation regimes in practice."
        self.assertTrue(limitation_phrases(on, {"iterative", "search", "saturation"}))

    def test_clean_abstract_yields_nothing(self):
        self.assertEqual(limitation_phrases("Results are strong and the method is fast."), [])

    def test_discourse_marker_alone_is_not_a_limitation(self):
        self.assertEqual(limitation_phrases("However, we also report a second experiment."), [])

    def test_failure_mode_can_now_ground_from_abstracts(self):
        papers = [paper(f"l{i}", f"Word sense disambiguation with graph methods, study {i}",
                        abstract="The system is limited to coarse sense inventories and "
                                 "fails on rare senses in running text.",
                        keywords=["word sense disambiguation"]) for i in range(4)]
        terms = extract_terms("word sense disambiguation", papers)
        self.assertIn("failure_mode", {t.relation for t in terms})


class TermHygieneTests(unittest.TestCase):
    def test_filler_words_reject_a_phrase(self):
        papers = [paper(f"x{i}", f"The problem very terms and you actually matter, study {i}")
                  for i in range(5)]
        texts = {t.text for t in extract_terms("problem terms", papers)}
        self.assertNotIn("problem very terms", texts)
        self.assertNotIn("you actually", texts)

    def test_content_phrase_unaffected_by_the_filler_list(self):
        papers = [paper(f"y{i}", f"Meaning conflation deficiency in sense embeddings, {i}")
                  for i in range(5)]
        texts = {t.text for t in extract_terms("sense embeddings", papers)}
        self.assertIn("meaning conflation deficiency", texts)

    def test_fragment_edges_rejected(self):
        papers = [paper(f"f{i}", f"Similarity between documents and relation between concepts, {i}")
                  for i in range(5)]
        texts = {t.text for t in extract_terms("similarity between documents", papers)}
        self.assertNotIn("relation between", texts)
        self.assertNotIn("similarity between", texts)

    def test_real_phrase_with_an_inner_weak_word_survives(self):
        papers = [paper(f"w{i}", f"Distance between centroids clustering method, study {i}",
                        keywords=["centroid distance clustering"]) for i in range(5)]
        texts = {t.text for t in extract_terms("clustering distance", papers)}
        self.assertIn("centroid distance clustering", texts)

    def test_reported_terms_hold_no_paraphrase_pair(self):
        papers = [paper(f"p{i}", f"Search algorithm and search algorithms for iterative search, {i}",
                        keywords=["search algorithm", "search algorithms"]) for i in range(5)]
        keys = [concept_key(t.text) for t in extract_terms("iterative search algorithms", papers)]
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                self.assertFalse(a <= b or b <= a, f"{a} / {b}")


class RedundancyTests(unittest.TestCase):
    def test_plural_and_substring_paraphrases_collapse(self):
        taken = {concept_key("similarity measure")}
        for label in ("similarity measures", "measure similarity", "semantic similarity measure between"):
            self.assertTrue(is_redundant(label, taken), label)

    def test_distinct_concept_is_not_redundant(self):
        taken = {concept_key("similarity measure")}
        self.assertFalse(is_redundant("ontology alignment", taken))

    def test_run_produces_no_paraphrase_pairs(self):
        from ontology_router.providers import EvidenceBundleProvider
        result = run_agent("memory retention", [EvidenceBundleProvider(str(FIXTURE))],
                           AgentPolicy(max_nodes=60, max_depth=3, max_rounds=3))
        keys = [concept_key(c["label"]) for c in result["concepts"]]
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                self.assertFalse(a <= b or b <= a, f"paraphrase pair: {a} / {b}")


class _GappyProvider:
    """A corpus that grounds mechanisms but never a failure mode or a neighbour field,
    so the gap machinery has something real to repair."""

    name = "gappy"

    def __init__(self):
        self.queries: list[str] = []

    def search(self, query, limit=20):
        self.queries.append(query)
        return [paper(f"{abs(hash(query)) % 9999}-{i}",
                      "Spaced repetition retrieval practice mechanism study",
                      abstract="The retrieval practice mechanism improves memory consolidation.",
                      keywords=["spaced repetition"])
                for i in range(4)]


class GapRepairTests(unittest.TestCase):
    def test_gap_queries_are_actually_searched(self):
        provider = _GappyProvider()
        result = run_agent("how does spaced repetition improve memory retention", [provider],
                           AgentPolicy(max_nodes=80, max_depth=3, max_rounds=4))
        rounds = result["rounds"]
        self.assertTrue(any(r["gaps"] for r in rounds), "fixture no longer produces a gap")
        issued = [q for r in rounds for q in (r["gap_queries"] or [])]
        self.assertTrue(issued, "gaps were reported but no gap query was issued")
        for r in rounds:
            self.assertLessEqual(len(r["gap_queries"] or []), GAP_QUERY_SLOTS)
            for q in (r["gap_queries"] or []):
                self.assertIn(q, r["queries"])
                self.assertIn(q, provider.queries)

    def test_gap_queries_do_not_crowd_out_the_frontier(self):
        provider = _GappyProvider()
        run_agent("how does spaced repetition improve memory retention", [provider],
                  AgentPolicy(max_nodes=80, max_depth=3, max_rounds=3))
        self.assertTrue(provider.queries)

    def test_status_vocabulary_is_closed(self):
        from ontology_router.providers import EvidenceBundleProvider
        result = run_agent("memory", [EvidenceBundleProvider(str(FIXTURE))],
                           AgentPolicy(max_nodes=40, max_depth=2, max_rounds=3))
        self.assertIn(result["status"], STATUSES)

    def test_usable_requires_four_of_five_relations(self):
        from ontology_router.providers import EvidenceBundleProvider
        result = run_agent("spaced repetition memory retention",
                           [EvidenceBundleProvider(str(FIXTURE))],
                           AgentPolicy(max_nodes=80, max_depth=3, max_rounds=4))
        if result["status"] == "usable":
            self.assertLessEqual(len(result["gaps"]), 1)


class KeepScoreTests(unittest.TestCase):
    def test_on_topic_outranks_a_more_cited_drifted_paper(self):
        fresh = paper("on", "On-topic study", year=2024, cited_by_count=3)
        canon = paper("off", "Canonical but drifted", year=2004, cited_by_count=3000)
        self.assertGreater(_keep_score(fresh, {"on"}), _keep_score(canon, {"on"}))

    def test_within_a_tier_citations_still_count(self):
        a = paper("a", "A", year=2020, cited_by_count=500)
        b = paper("b", "B", year=2020, cited_by_count=5)
        self.assertGreater(_keep_score(a, set()), _keep_score(b, set()))


class OpenAlexKeylessTests(unittest.TestCase):
    """OpenAlex answers without a key; the old code refused to call it."""

    class _FakeHttp:
        def __init__(self):
            self.urls = []

        def get_json(self, url, headers=None):
            self.urls.append(url)
            return {"results": [{"id": "W1", "title": "Keyless result",
                                 "abstract_inverted_index": {"Mapping": [0], "quality": [1]},
                                 "publication_year": 2024,
                                 "primary_topic": {"display_name": "Ontology engineering",
                                                   "domain": {"display_name": "Physical Sciences"},
                                                   "field": {"display_name": "Computer Science"},
                                                   "subfield": {"display_name": "Information Systems"}},
                                 "keywords": [{"display_name": "ontology mapping"}]}]}

    def test_search_without_key_returns_papers(self):
        http = self._FakeHttp()
        papers = OpenAlexProvider(http).search("ontology mapping quality", 5)
        self.assertEqual(len(papers), 1)
        self.assertTrue(papers[0].abstract)
        self.assertTrue(papers[0].topic_path or papers[0].fields)
        self.assertNotIn("api_key", http.urls[0])

    def test_key_is_still_used_when_present(self):
        http = self._FakeHttp()
        OpenAlexProvider(http, api_key="secret").search("q", 5)
        self.assertIn("api_key=secret", http.urls[0])

    def test_email_becomes_mailto_when_keyless(self):
        http = self._FakeHttp()
        OpenAlexProvider(http, email="a@b.c").search("q", 5)
        self.assertIn("mailto=a%40b.c", http.urls[0])


if __name__ == "__main__":
    unittest.main()


def _raiser(error, calls):
    def fake(request, timeout=0):
        calls.append(getattr(request, "full_url", request))
        raise error
    return fake


class ProviderCooldownTests(unittest.TestCase):
    """A long Retry-After is a quota window: one run cannot wait it out."""

    def test_long_retry_after_stops_further_calls_to_that_host(self):
        err = urllib.error.HTTPError("https://api.openalex.org/works?q=1", 429, "Too Many Requests",
                                     {"Retry-After": "30746"}, None)
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            client = CachedHttpClient(cache_dir=Path(tmp), min_interval=0.0, max_retries=2)
            with mock.patch("urllib.request.urlopen", side_effect=_raiser(err, calls)), mock.patch("time.sleep"):
                with self.assertRaises(providers.ProviderUnavailable):
                    client.get_json("https://api.openalex.org/works?q=1")
                with self.assertRaises(providers.ProviderUnavailable):
                    client.get_json("https://api.openalex.org/works?q=2")
        self.assertEqual(len(calls), 1, "second call must fail fast without touching the network")

    def test_short_retry_after_still_retries(self):
        err = urllib.error.HTTPError("https://api.crossref.org/works?q=1", 429, "Too Many Requests",
                                     {"Retry-After": "1"}, None)
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            client = CachedHttpClient(cache_dir=Path(tmp), min_interval=0.0, max_retries=2)
            with mock.patch("urllib.request.urlopen", side_effect=_raiser(err, calls)), mock.patch("time.sleep"):
                with self.assertRaises(providers.ProviderError) as ctx:
                    client.get_json("https://api.crossref.org/works?q=1")
        self.assertNotIsInstance(ctx.exception, providers.ProviderUnavailable)
        self.assertEqual(len(calls), 2, "a burst limit is worth retrying inside the run")


class DegradedProviderReportTests(unittest.TestCase):
    BASE = {"question": "q", "root_topic": "q", "status": "partial", "stop_reason": "x",
            "papers": [], "retrieved_papers": 0, "on_topic_papers": 0, "concepts": [],
            "coverage": {"mechanism": []}, "gaps": ["mechanism"],
            "recommended_queries": [], "limitations": []}

    def test_brief_names_a_provider_that_answered_nothing(self):
        text = report.render_compact_markdown({**self.BASE, "providers_down": ["openalex"]})
        self.assertIn("**Degraded:** openalex", text)

    def test_brief_stays_quiet_when_every_provider_answered(self):
        self.assertNotIn("Degraded", report.render_compact_markdown({**self.BASE, "providers_down": []}))


class StatedLimitationTests(unittest.TestCase):
    """A title carrying the word "failure" is not a limitation the authors stated."""

    def _papers(self):
        return [
            Paper("p1", "Assessing the connections between state failure and terrorism", "",
                  "u1", "", 2020, 3, "crossref", [], [], [], "", ["state failure"]),
            Paper("p2", "State failure and terrorism reviewed", "", "u2", "", 2021, 2,
                  "crossref", [], [], [], "", ["state failure"]),
            Paper("p3", "Measuring state failure across regions", "Our state failure sample is "
                  "limited to three regions, so the estimates do not generalise.", "u3", "", 2022, 5,
                  "crossref", [], [], [], "", ["state failure"]),
            Paper("p4", "State failure indicators compared", "A limitation is that the state "
                  "failure index does not generalise beyond three regions.", "u4", "", 2023, 4,
                  "crossref", [], [], [], "", ["state failure"]),
        ]

    def test_title_phrase_is_not_flagged_as_stated(self):
        terms = extract_terms("what causes state failure", self._papers())
        titles = [t for t in terms if t.text == "connections between state failure"]
        self.assertTrue(all(not t.stated_limitation for t in titles))

    def test_sentence_from_an_abstract_is_flagged(self):
        terms = extract_terms("what causes state failure", self._papers())
        stated = [t for t in terms if t.stated_limitation]
        self.assertTrue(stated, "a sentence saying 'a limitation is' must be marked stated")
        self.assertTrue(any("limitation" in e.lower() or "limited" in e.lower()
                            for t in stated for e in t.examples))


class AbstractBackedRelationTests(unittest.TestCase):
    """A subject label may name the neighbourhood; only a sentence may name a mechanism."""

    def _label_papers(self):
        # Every paper carries the label as a provider keyword and nowhere else.
        return [
            Paper(f"p{i}", f"Query reuse in practice, part {i}", "This report surveys industrial "
                  "deployments and reports adoption counts by sector.", f"u{i}", "", 2020 + i, 4,
                  "openalex", [], ["service oriented architecture and web services"],
                  ["Computer Science"], "", ["query reuse"])
            for i in range(1, 5)
        ]

    def _sentence_papers(self):
        return [
            Paper(f"s{i}", f"Query reuse in practice, part {i}",
                  "The system works by caching an attention mechanism over earlier result sets, "
                  "and the attention mechanism is refreshed per round.", f"v{i}", "", 2020 + i, 4,
                  "europepmc", [], [], [], "", ["query reuse"])
            for i in range(1, 5)
        ]

    def test_label_only_term_cannot_be_a_mechanism(self):
        terms = extract_terms("how does query reuse work", self._label_papers())
        label = [t for t in terms if t.text == "service oriented architecture and web services"]
        self.assertTrue(label, "the label should still reach the map")
        self.assertTrue(all(t.relation not in {"mechanism", "measurement", "method", "failure_mode"}
                            for t in label),
                        "a provider label with no sentence behind it must not claim a relation")

    def test_sentence_term_still_becomes_a_mechanism(self):
        terms = extract_terms("how does query reuse work", self._sentence_papers())
        found = [t for t in terms if "attention mechanism" in t.text]
        self.assertTrue(found, "a phrase read out of an abstract must survive")
        self.assertEqual("mechanism", found[0].relation)


class ClaimMemoryTests(unittest.TestCase):
    """A run records what it established, not only what it read."""

    def test_grounded_down_relations_are_written_as_claims(self):
        import json
        import tempfile
        from ontology_router.memory import MemoryStore
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.jsonl")
            store.append_run({
                "question": "how does query reuse work",
                "root_topic": "query reuse",
                "terms": [
                    {"text": "attention mechanism", "relation": "mechanism", "confidence": "high",
                     "paper_ids": ["p1"], "examples": ["The system caches an attention mechanism."]},
                    {"text": "computer science", "relation": "neighbor_field", "confidence": "high",
                     "paper_ids": ["p2"], "examples": ["A paper title"]},
                    {"text": "weak idea", "relation": "mechanism", "confidence": "low",
                     "paper_ids": ["p3"], "examples": [""]},
                ],
            })
            written = json.loads(store.path.read_text(encoding="utf-8").strip())
        claims = written["claims"]
        self.assertEqual(1, len(claims), "only grounded down-relation terms are claims")
        self.assertEqual("attention mechanism", claims[0]["text"])
        self.assertIn("attention mechanism", claims[0]["example"])


class SilentFailureTests(unittest.TestCase):
    """A run that retrieved nothing exited 0 with a brief that read like a thin
    literature. Reported 2026-09-16: a socket timeout against Europe PMC produced a
    `failed` status, exit 0, and no signal a caller could branch on."""

    FAILED = {"question": "q", "root_topic": "q", "status": "failed",
              "stop_reason": "no papers could be retrieved",
              "papers": [], "retrieved_papers": 0, "on_topic_papers": 0, "concepts": [],
              "coverage": {"mechanism": []}, "gaps": ["mechanism"],
              "recommended_queries": [], "limitations": [],
              "providers_down": ["europepmc"],
              "provider_errors": ["europepmc: Request failed: https://www.ebi.ac.uk/: timed out"]}

    def _run_cli(self, bundle: str, out: str, question: str = "attention mechanisms in transformers") -> int:
        argv = ["eonrise", question, "--mode", "assistant",
                "--bundle", bundle, "--out", out, "--no-memory", "--no-corpus"]
        with mock.patch("sys.argv", argv), mock.patch("builtins.print"):
            try:
                cli.main()
            except SystemExit as exc:
                return int(exc.code or 0)
        return 0

    def test_empty_run_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "empty.json"
            bundle.write_text('{"papers": []}', encoding="utf-8")
            self.assertEqual(self._run_cli(str(bundle), str(Path(tmp) / "out")), 2)

    def test_healthy_run_still_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(__file__).parent / "fixtures" / "papers.json"
            # The bundle is a memory/forgetting literature, so the question has to be one
            # it can actually answer: since the zero-topical guard landed, asking it about
            # transformers is a failed search, and correctly exits 2.
            self.assertEqual(self._run_cli(str(fixture), str(Path(tmp) / "out"),
                                           "how does spaced repetition improve memory retention"), 0)

    def test_failed_off_topic_run_does_not_claim_nothing_was_retrieved(self):
        result = {**self.FAILED, "papers": [{"title": "Coral reef bleaching"}],
                  "retrieved_papers": 20,
                  "stop_reason": "20 papers retrieved, none about the question"}
        text = report.render_compact_markdown(result)
        self.assertIn("No retrieved paper was about this question", text)
        self.assertIn("timed out", text)
        self.assertNotIn("This run retrieved nothing", text)
        self.assertNotIn("map below is empty", text)

    def test_brief_blames_the_search_not_the_literature(self):
        text = report.render_compact_markdown(self.FAILED)
        self.assertIn("the search failed, not because the literature is silent", text)
        self.assertIn("timed out", text)
        self.assertNotIn("**Degraded:**", text)  # that line reads as a usable partial run


class ZeroTopicalCorpusTests(unittest.TestCase):
    """`few` and `none` are different signals. Reported 2026-09-16: a live run retrieved
    60 papers, matched 0 to the question, disabled its own topical filter because
    0 < MIN_TOPICAL_CORPUS, and reported `partial` with a confident map."""

    def _papers(self, n: int, about: str) -> list:
        return [Paper(f"p{i}", f"{about} study {i}", f"This paper examines {about} in depth.",
                      f"https://example.org/{i}", "", 2020, 5, "fixture", [about], [], [], "", [])
                for i in range(n)]

    def _run(self, papers: list) -> dict:
        class Bundle:
            name = "fixture"
            def search(self, query, limit=20):
                return [Paper.from_dict(p.to_dict()) for p in papers]
        policy = AgentPolicy(name="t", max_nodes=40, max_depth=3, max_rounds=2,
                             up_weight=0.5, down_weight=1.0, sideways_weight=1.0,
                             support_threshold=2)
        with tempfile.TemporaryDirectory() as tmp:
            from ontology_router.scheduling import ProviderStates
            return run_agent("how are transformer attention heads pruned", [Bundle()], policy,
                             results_per_query=20, background=set(),
                             states=ProviderStates(Path(tmp) / "p.json"))

    def test_a_wholly_off_topic_corpus_fails_the_run(self):
        result = self._run(self._papers(20, "coral reef bleaching"))
        self.assertEqual(result["on_topic_papers"], 0)
        self.assertEqual(result["status"], "failed")
        self.assertIn("none about the question", result["stop_reason"])

    def test_a_small_bundle_is_still_not_starved(self):
        # Below MIN_TOPICAL_CORPUS the old fallback stays: few literal matches is not
        # the same failure, and three earlier tightenings died by deleting real papers.
        result = self._run(self._papers(4, "coral reef bleaching"))
        self.assertNotEqual(result["status"], "failed")

    def test_brief_says_the_search_failed_not_the_field(self):
        text = report.render_compact_markdown({
            "question": "q", "root_topic": "q", "status": "failed",
            "stop_reason": "60 papers retrieved, none about the question",
            "papers": [{"title": "x"}], "retrieved_papers": 60, "on_topic_papers": 0,
            "concepts": [], "coverage": {"mechanism": ["quality control"]},
            "gaps": [], "recommended_queries": [], "limitations": []})
        self.assertIn("No retrieved paper was about this question", text)
