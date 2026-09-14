from __future__ import annotations

import unittest
from pathlib import Path

from ontology_router.engine import canonical_root, relation_to_direction, run_agent
from ontology_router.models import AgentPolicy
from ontology_router.providers import EvidenceBundleProvider

FIXTURE = Path(__file__).parent / "fixtures" / "papers.json"


def provider() -> EvidenceBundleProvider:
    return EvidenceBundleProvider(str(FIXTURE))


class SingleRootTests(unittest.TestCase):
    def test_canonical_root_is_single_topic(self):
        root = canonical_root("How does spaced repetition improve long-term memory?")
        self.assertTrue(root)
        self.assertLessEqual(len(root.split()), 6)
        self.assertNotIn("?", root)

    def test_run_produces_single_root_and_concepts(self):
        result = run_agent("memory retention", [provider()],
                           AgentPolicy(max_nodes=40, max_depth=3, max_rounds=3))
        self.assertIn("root_topic", result)
        self.assertEqual(len(result["root_topic"].split()), len(set(result["root_topic"].split())))
        self.assertGreaterEqual(len(result["concepts"]), 1)
        self.assertEqual(result["concepts"][0]["direction"], "root")
        self.assertGreater(len(result["papers"]), 0)

    def test_agent_depth_budget_respected(self):
        shallow = run_agent("memory", [provider()], AgentPolicy(max_nodes=120, max_depth=1, max_rounds=4))
        deep = run_agent("memory", [provider()], AgentPolicy(max_nodes=120, max_depth=4, max_rounds=4))
        shallow_depth = max(c["depth"] for c in shallow["concepts"])
        deep_depth = max(c["depth"] for c in deep["concepts"])
        self.assertLessEqual(shallow_depth, 1)
        self.assertGreaterEqual(deep_depth, shallow_depth)

    def test_direction_weights_change_expansion(self):
        down_heavy = run_agent("memory", [provider()],
                               AgentPolicy(max_nodes=30, max_depth=2, max_rounds=2,
                                           down_weight=2.0, sideways_weight=0.1, up_weight=0.1))
        side_heavy = run_agent("memory", [provider()],
                               AgentPolicy(max_nodes=30, max_depth=2, max_rounds=2,
                                           down_weight=0.1, sideways_weight=2.0, up_weight=0.1))
        down_dirs = [c["direction"] for c in down_heavy["concepts"]]
        side_dirs = [c["direction"] for c in side_heavy["concepts"]]
        self.assertIn("down", down_dirs)
        self.assertIn("sideways", side_dirs)

    def test_relation_to_direction_mapping(self):
        self.assertEqual(relation_to_direction("mechanism", "term"), "down")
        self.assertEqual(relation_to_direction("method", "term"), "down")
        self.assertEqual(relation_to_direction("neighbor_field", "term"), "sideways")
        self.assertEqual(relation_to_direction("topic", "field"), "up")


if __name__ == "__main__":
    unittest.main()
