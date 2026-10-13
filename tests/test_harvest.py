from __future__ import annotations

import unittest

from eonrise.harvest import harvest, signature
from eonrise.models import Paper, Term
from eonrise.report import render_compact_markdown


def term(text, relation="mechanism", confidence="high"):
    return Term(text, relation, 1.0, confidence, ["on1", "on2"], [], [], [])


TERMS = [term("accumulation curve"), term("sampling completeness", "measurement"),
         term("premature stopping", "failure_mode"), term("information retrieval", "neighbor_field"),
         term("recall estimate", "measurement", "low")]


def corpus():
    on = [Paper(f"on{i}", "Stopping rules for literature search", fields=["Information Retrieval"]) for i in (1, 2)]
    shape = Paper("eco", "Estimating species richness", fields=["Ecology"],
                  abstract="The species accumulation curve flattens; sampling completeness is estimated "
                           "and premature stopping underestimates richness.")
    surface = Paper("surf", "Curve fitting for accumulation of snow", fields=["Hydrology"],
                    abstract="Snow accumulation on slopes.")
    lexical = Paper("lex", "Sampling completeness of museum records", fields=["Museology"],
                    abstract="Sampling completeness of museum collections.")
    return on + [shape, surface, lexical]


class HarvestTests(unittest.TestCase):
    def test_signature_is_grounded_concepts_not_fields(self):
        labels = [label for label, _, _ in signature(TERMS)]
        self.assertEqual(labels, ["accumulation curve", "sampling completeness", "premature stopping"])

    def test_shape_match_ranks_first_and_on_topic_is_excluded(self):
        hits = harvest(TERMS, corpus(), {"on1", "on2"})
        ids = [h["paper_id"] for h in hits]
        self.assertEqual(ids[0], "eco")
        self.assertNotIn("on1", ids)
        self.assertTrue(hits[0]["distant"])
        self.assertEqual(len(hits[0]["shares"]), 3)

    def test_words_scattered_across_a_paper_are_not_a_shared_concept(self):
        # `accumulation` and `curve` both occur in the snow paper, which is about neither
        # the concept nor the question; it shares no down-relation concept as a whole.
        ids = [h["paper_id"] for h in harvest(TERMS, corpus(), {"on1", "on2"})]
        self.assertNotIn("surf", ids)

    def test_one_field_cannot_fill_the_list(self):
        many = corpus() + [Paper(f"e{i}", "Richness", fields=["Ecology"],
                                 abstract="accumulation curve and premature stopping") for i in range(5)]
        fields = [h["field"] for h in harvest(TERMS, many, {"on1", "on2"})]
        self.assertLessEqual(fields.count("Ecology"), 2)

    def test_no_grounded_concepts_no_harvest(self):
        self.assertEqual(harvest([term("x y", confidence="low")], corpus(), set()), [])

    def test_brief_separates_other_fields_from_gate_misses(self):
        result = {"question": "q", "status": "partial", "stop_reason": "r", "papers": [], "coverage": {},
                  "gaps": [], "recommended_queries": [],
                  "harvest": [{"title": "Far", "year": 2020, "field": "Ecology", "distant": True, "shares": ["a"]},
                              {"title": "Near", "year": 2021, "field": "IR", "distant": False, "shares": ["b"]}]}
        text = render_compact_markdown(result)
        self.assertLess(text.index("Same shape, other fields"), text.index("**Far**"))
        self.assertLess(text.index("missed by the word gate"), text.index("**Near**"))


if __name__ == "__main__":
    unittest.main()


class VotingCoreTests(unittest.TestCase):
    """Below the gate minimum the closest papers vote, not the whole corpus."""

    def test_small_gate_is_topped_up_by_closeness_not_by_everything(self):
        from eonrise.evidence import MIN_TOPICAL_CORPUS, voting_core
        q = "when should a literature search stop"
        close = [Paper(f"c{i}", "Stopping rules for screening", abstract="When to stop a literature search.")
                 for i in range(MIN_TOPICAL_CORPUS)]
        far = [Paper(f"f{i}", "Analogy mining for product design") for i in range(20)]
        core = voting_core(q, far + close, {"c0"})
        self.assertEqual(core, {p.paper_id for p in close})

    def test_large_gate_is_used_as_is(self):
        from eonrise.evidence import MIN_TOPICAL_CORPUS, voting_core
        on = {f"p{i}" for i in range(MIN_TOPICAL_CORPUS)}
        self.assertEqual(voting_core("q", [], on), on)

    def test_no_question_word_anywhere_means_no_core(self):
        from eonrise.evidence import voting_core
        self.assertIsNone(voting_core("volcano eruptions", [Paper("x", "Analogy mining")], set()))


class DistantQueryTests(unittest.TestCase):
    def test_other_fields_first_no_duplicates(self):
        from eonrise.harvest import distant_queries
        hits = [{"distant": False, "shares": ["target recall", "systematic reviews"]},
                {"distant": True, "shares": ["stopping criteria", "active learning"]},
                {"distant": True, "shares": ["stopping criteria", "active learning"]}]
        self.assertEqual(distant_queries(hits), ["stopping criteria active learning",
                                                 "target recall systematic reviews"])
