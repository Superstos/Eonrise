from __future__ import annotations

import unittest

from eonrise.engine import limitation_phrases, _guard_relation, concept_key, extract_terms
from eonrise.models import Paper


def paper(pid: str, title: str, **kw) -> Paper:
    return Paper(pid, title, **kw)


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


if __name__ == "__main__":
    unittest.main()
