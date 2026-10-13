from __future__ import annotations

import json
import unittest
from pathlib import Path

from eonrise.engine import run_agent
from eonrise.evidence import family, topical_papers
from eonrise.models import AgentPolicy, Paper
from eonrise.providers import EvidenceBundleProvider

GOLD = Path(__file__).parent / "fixtures" / "crossfield_gold.json"


class WordFamilyTests(unittest.TestCase):
    def test_derivations_meet(self):
        for group in (("analogy", "analogous", "analogical", "analogies"),
                      ("retrieve", "retrieval", "retrieving", "retrieved"),
                      ("discover", "discovery", "discoveries"),
                      ("stop", "stopping"), ("structure", "structural")):
            self.assertEqual(len({family(w) for w in group}), 1, group)

    def test_distinct_words_stay_apart(self):
        self.assertNotEqual(family("general"), family("generation"))
        self.assertNotEqual(family("memory"), family("memo"))
        self.assertEqual(family("gene"), "gene")  # too short to lose an ending

    def test_adjective_question_finds_noun_papers(self):
        papers = [Paper("a", "Accelerating innovation through analogy mining",
                        keywords=["analogical retrieval"])]
        self.assertEqual(topical_papers("retrieve analogous solutions", papers), {"a"})


class CrossFieldGoldTests(unittest.TestCase):
    """99 web-gathered papers, independently labelled on / near / off for one question.

    Before word families the gate kept 2 of 47 on-topic papers and the run was declared
    failed ("none about the question"). The floor below is the measured value, and the
    ceiling on `off` is the reason pseudo-relevance feedback was rejected (it let 7/10 in).
    """

    @classmethod
    def setUpClass(cls):
        raw = json.loads(GOLD.read_text(encoding="utf-8"))
        cls.question, cls.labels = raw["question"], raw["labels"]
        cls.papers = EvidenceBundleProvider(GOLD).papers

    def _kept(self, label):
        keep = topical_papers(self.question, self.papers)
        return sum(1 for pid, lab in self.labels.items() if lab == label and pid in keep)

    def test_gate_recall_floor(self):
        self.assertGreaterEqual(self._kept("on"), 14)

    def test_gate_lets_no_unrelated_paper_in(self):
        self.assertEqual(self._kept("off"), 0)

    def test_run_on_its_own_literature_is_not_failed(self):
        result = run_agent(self.question, [EvidenceBundleProvider(GOLD)],
                           AgentPolicy(max_rounds=3, max_nodes=80), results_per_query=25)
        self.assertNotEqual(result["status"], "failed")
        self.assertGreater(result["on_topic_papers"], 0)


if __name__ == "__main__":
    unittest.main()


class LimitationGoldTests(unittest.TestCase):
    """364 labelled sentences, 75 limitations. Floors are the v0.13 measurements."""

    @classmethod
    def setUpClass(cls):
        from eonrise.evidence import LIMITATION_CUES, limitation_phrases
        path = Path(__file__).parent / "fixtures" / "limitation_gold.json"
        cls.rows = json.loads(path.read_text(encoding="utf-8"))["sentences"]
        cls.cues, cls.extract = set(LIMITATION_CUES), staticmethod(limitation_phrases)

    def test_sentence_detection(self):
        import re
        hits = [r for r in self.rows if set(re.findall(r"[a-z][a-z0-9-]+", r["sentence"].lower())) & self.cues]
        tp = sum(1 for r in hits if r["label"])
        self.assertGreaterEqual(tp, 36)
        self.assertGreaterEqual(tp / len(hits), 0.85)

    def test_phrase_is_an_unbroken_run_and_never_a_header(self):
        for r in self.rows:
            for phrase, _ in self.extract(r["sentence"]):
                self.assertNotIn(phrase.split()[0], {"stated", "noted", "limitation"})
                self.assertIn(phrase, r["sentence"].lower())


class ConceptGateTests(unittest.TestCase):
    def test_second_stage_on_gold(self):
        from eonrise.harvest import concept_gate
        raw = json.loads(GOLD.read_text(encoding="utf-8"))
        papers = EvidenceBundleProvider(GOLD).papers
        keep = concept_gate(raw["question"], papers, topical_papers(raw["question"], papers))
        kept = lambda label: sum(1 for pid, lab in raw["labels"].items() if lab == label and pid in keep)
        self.assertGreaterEqual(kept("on"), 31)
        self.assertEqual(kept("off"), 0)

    def test_empty_gate_is_not_bootstrapped(self):
        from eonrise.harvest import concept_gate
        self.assertEqual(concept_gate("volcano", EvidenceBundleProvider(GOLD).papers, set()), set())


class HeldOutBatteryTests(unittest.TestCase):
    """Built after v0.16 and never tuned on. Floors are the first measurement."""

    def test_heldout_run(self):
        path = Path(__file__).parent / "fixtures" / "heldout_battery.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        provider = EvidenceBundleProvider(path)
        label = {p.paper_id: raw["labels"].get(p.title) for p in provider.papers}
        result = run_agent(raw["question"], [provider], AgentPolicy(max_rounds=6, max_nodes=160), results_per_query=25)
        kept = [label.get(pid) for pid in result["on_topic_paper_ids"]]
        self.assertGreaterEqual(kept.count("on"), 23)
        self.assertLessEqual(kept.count("off"), 1)
        self.assertEqual(result["status"], "usable")
        self.assertTrue(all(label.get(h["paper_id"]) != "off" for h in result["harvest"]))
