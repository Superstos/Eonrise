from __future__ import annotations

import unittest
from pathlib import Path

from eonrise.engine import canonical_root, relation_to_direction, run_search
from eonrise.models import SearchSettings
from eonrise.providers import EvidenceBundleProvider

FIXTURE = Path(__file__).parent / "fixtures" / "papers.json"


def provider() -> EvidenceBundleProvider:
    return EvidenceBundleProvider(str(FIXTURE))


class SingleRootTests(unittest.TestCase):
    def test_canonical_root_is_single_topic(self):
        root = canonical_root("How does spaced repetition improve long-term memory?")
        self.assertTrue(root)
        self.assertLessEqual(len(root.split()), 6)
        self.assertNotIn("?", root)

    def test_root_drops_question_filler(self):
        # Real runs, 2026-10-14: `often come` retrieved "Do You Come Here Often?".
        self.assertEqual(canonical_root("why do inventions often come from borrowing a method from an unrelated field"),
                         "inventions borrowing method unrelated field")
        self.assertEqual(canonical_root("how do new ideas form when knowledge from two separate fields is combined"),
                         "ideas form knowledge separate fields combined")
        self.assertEqual(canonical_root("how to keep going"), "keep going")

    def test_run_produces_single_root_and_concepts(self):
        result = run_search("memory retention", [provider()],
                           SearchSettings(max_nodes=40, max_depth=3, max_rounds=3))
        self.assertIn("root_topic", result)
        self.assertEqual(len(result["root_topic"].split()), len(set(result["root_topic"].split())))
        self.assertGreaterEqual(len(result["concepts"]), 1)
        self.assertEqual(result["concepts"][0]["direction"], "root")
        self.assertGreater(len(result["papers"]), 0)

    def test_agent_depth_budget_respected(self):
        shallow = run_search("memory", [provider()], SearchSettings(max_nodes=120, max_depth=1, max_rounds=4))
        deep = run_search("memory", [provider()], SearchSettings(max_nodes=120, max_depth=4, max_rounds=4))
        shallow_depth = max(c["depth"] for c in shallow["concepts"])
        deep_depth = max(c["depth"] for c in deep["concepts"])
        self.assertLessEqual(shallow_depth, 1)
        self.assertGreaterEqual(deep_depth, shallow_depth)

    def test_direction_weights_change_expansion(self):
        down_heavy = run_search("memory", [provider()],
                               SearchSettings(max_nodes=30, max_depth=2, max_rounds=2,
                                           down_weight=2.0, sideways_weight=0.1, up_weight=0.1))
        side_heavy = run_search("memory", [provider()],
                               SearchSettings(max_nodes=30, max_depth=2, max_rounds=2,
                                           down_weight=0.1, sideways_weight=2.0, up_weight=0.1))
        down_dirs = [c["direction"] for c in down_heavy["concepts"]]
        side_dirs = [c["direction"] for c in side_heavy["concepts"]]
        self.assertIn("down", down_dirs)
        self.assertIn("sideways", side_dirs)

    def test_relation_to_direction_mapping(self):
        self.assertEqual(relation_to_direction("mechanism", "term"), "down")
        self.assertEqual(relation_to_direction("method", "term"), "down")
        # Up used to be unreachable: concepts are always built with source_kind "term",
        # so only the `field` branch could return it and no caller passed `field`.
        self.assertEqual(relation_to_direction("neighbor_field", "term"), "up")
        self.assertEqual(relation_to_direction("topic", "field"), "up")
        self.assertEqual(relation_to_direction("topic", "term"), "sideways")


if __name__ == "__main__":
    unittest.main()
