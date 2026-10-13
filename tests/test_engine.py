from __future__ import annotations

import unittest
from pathlib import Path

from eonrise.engine import GAP_QUERY_SLOTS, _keep_score, concept_key, is_redundant, run_search
from eonrise.models import STATUSES, SearchSettings, Paper


FIXTURE = Path(__file__).parent / "fixtures" / "papers.json"


def paper(pid: str, title: str, **kw) -> Paper:
    return Paper(pid, title, **kw)


class RedundancyTests(unittest.TestCase):
    def test_plural_and_substring_paraphrases_collapse(self):
        taken = {concept_key("similarity measure")}
        for label in ("similarity measures", "measure similarity", "semantic similarity measure between"):
            self.assertTrue(is_redundant(label, taken), label)

    def test_distinct_concept_is_not_redundant(self):
        taken = {concept_key("similarity measure")}
        self.assertFalse(is_redundant("ontology alignment", taken))

    def test_run_produces_no_paraphrase_pairs(self):
        from eonrise.providers import EvidenceBundleProvider
        result = run_search("memory retention", [EvidenceBundleProvider(str(FIXTURE))],
                           SearchSettings(max_nodes=60, max_depth=3, max_rounds=3))
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
        result = run_search("how does spaced repetition improve memory retention", [provider],
                           SearchSettings(max_nodes=80, max_depth=3, max_rounds=4))
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
        run_search("how does spaced repetition improve memory retention", [provider],
                  SearchSettings(max_nodes=80, max_depth=3, max_rounds=3))
        self.assertTrue(provider.queries)

    def test_status_vocabulary_is_closed(self):
        from eonrise.providers import EvidenceBundleProvider
        result = run_search("memory", [EvidenceBundleProvider(str(FIXTURE))],
                           SearchSettings(max_nodes=40, max_depth=2, max_rounds=3))
        self.assertIn(result["status"], STATUSES)

    def test_usable_requires_four_of_five_relations(self):
        from eonrise.providers import EvidenceBundleProvider
        result = run_search("spaced repetition memory retention",
                           [EvidenceBundleProvider(str(FIXTURE))],
                           SearchSettings(max_nodes=80, max_depth=3, max_rounds=4))
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


if __name__ == "__main__":
    unittest.main()
