from __future__ import annotations

import unittest

from ontology_router.models import Paper
from ontology_router.report import render_compact_markdown
from ontology_router.unseen import estimate
from ontology_router.unseen_benchmark import main as benchmark


def papers(histories):
    return [Paper(str(i), str(i), found_by=qs) for i, qs in enumerate(histories)]


class EstimateTests(unittest.TestCase):
    def test_chao2_and_coverage_by_hand(self):
        # 4 singletons, 2 doubletons, 1 found three times; T = 4 queries, U = 11 incidences.
        est = estimate(papers([["a"], ["b"], ["c"], ["d"], ["a", "b"], ["c", "d"], ["a", "b", "c"]]))
        self.assertEqual((est["singletons"], est["doubletons"], est["queries"]), (4, 2, 4))
        self.assertEqual(est["estimated_total"], round(7 + 0.75 * 4 * 3 / 6, 1))  # 8.5
        self.assertEqual(est["sample_coverage"], round(1 - 4 / 11 * (12 / 16), 3))

    def test_every_paper_found_twice_means_nothing_unseen(self):
        est = estimate(papers([["a", "b"]] * 6))
        self.assertEqual((est["estimated_total"], est["sample_coverage"]), (6.0, 1.0))

    def test_too_little_evidence_gives_no_estimate(self):
        self.assertIsNone(estimate(papers([["a"], ["b"]])))
        self.assertIsNone(estimate(papers([["a"]] * 9)))  # one query is one sample

    def test_restricted_to_the_given_ids(self):
        rows = papers([["a"], ["b"], ["a", "b"], ["a", "b"], ["a", "b"], ["a", "b"], ["a"]])
        self.assertEqual(estimate(rows, {"2", "3", "4", "5", "6"})["singletons"], 1)


class WarningTests(unittest.TestCase):
    base = {"question": "q", "status": "partial", "stop_reason": "r", "papers": [], "coverage": {},
            "gaps": [], "recommended_queries": []}

    def test_low_share_warns(self):
        text = render_compact_markdown({**self.base, "unseen": {"found_share": 0.4, "singletons": 9,
                                                                "observed": 12, "estimated_total": 30}})
        self.assertIn("at most ~40%", text)

    def test_high_share_stays_quiet(self):
        text = render_compact_markdown({**self.base, "unseen": {"found_share": 0.9, "singletons": 1,
                                                                "observed": 12, "estimated_total": 13}})
        self.assertNotIn("Unfinished", text)

    def test_shipped_warning_keeps_its_measured_precision(self):
        result = benchmark(seeds=40)
        self.assertGreaterEqual(result["warning"]["precision"], 0.85)
        self.assertFalse(result["totals"]["coverage"]["passes_kill_rule"])  # why it is only a warning


if __name__ == "__main__":
    unittest.main()
