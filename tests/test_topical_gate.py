from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from eonrise.engine import run_search, topical_papers
from eonrise.models import SearchSettings, Paper
from eonrise import report


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
        result = run_search("when should an iterative search or exploration process stop using saturation",
                           [_MixedProvider()], SearchSettings(max_nodes=60, max_depth=3, max_rounds=2))
        labels = " ".join(c["label"] for c in result["concepts"])
        terms = " ".join(t["text"] for t in result["terms"])
        self.assertNotIn("protein", labels)
        self.assertNotIn("protein", terms)

    def test_on_topic_cluster_still_grounds(self):
        result = run_search("when should an iterative search or exploration process stop using saturation",
                           [_MixedProvider()], SearchSettings(max_nodes=60, max_depth=3, max_rounds=2))
        self.assertTrue(result["terms"], "on-topic evidence produced no terms at all")
        self.assertGreater(result["on_topic_papers"], 0)


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
        policy = SearchSettings(name="t", max_nodes=40, max_depth=3, max_rounds=2,
                             up_weight=0.5, down_weight=1.0, sideways_weight=1.0,
                             support_threshold=2)
        with tempfile.TemporaryDirectory() as tmp:
            from eonrise.scheduling import ProviderStates
            return run_search("how are transformer attention heads pruned", [Bundle()], policy,
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


if __name__ == "__main__":
    unittest.main()
