from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from eonrise.engine import extract_terms
from eonrise.models import Paper


def paper(pid: str, title: str, **kw) -> Paper:
    return Paper(pid, title, **kw)


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
        from eonrise.question_log import QuestionLog
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.jsonl"
            rows = [{"root_topic": f"root {i}", "concepts": [{"label": "computer science"},
                                                             {"label": f"unique {i}"}]}
                    for i in range(4)]
            path.write_text(chr(10).join(json.dumps(r) for r in rows), encoding="utf-8")
            store = QuestionLog(path)
            self.assertIn("computer science", store.background_labels("other root"))
            self.assertNotIn("unique 1", store.background_labels("other root"))
            # a label seen under only two other roots is not yet background
            self.assertNotIn("computer science", store.background_labels("other", min_roots=5))


class ClaimMemoryTests(unittest.TestCase):
    """A run records what it established, not only what it read."""

    def test_grounded_down_relations_are_written_as_claims(self):
        import json
        import tempfile
        from eonrise.question_log import QuestionLog
        with tempfile.TemporaryDirectory() as tmp:
            store = QuestionLog(Path(tmp) / "memory.jsonl")
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


if __name__ == "__main__":
    unittest.main()
