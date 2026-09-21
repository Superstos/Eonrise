from __future__ import annotations

import unittest

from ontology_router.evolution_proof import proof_fixture


class EvolutionProofTests(unittest.TestCase):
    def test_eonrise_can_select_and_promote_a_better_learned_state(self):
        result = proof_fixture()

        self.assertLess(result["parent_score"], result["active_score"])
        self.assertTrue(result["accepted"])
        self.assertEqual(result["parent_version"], 0)
        self.assertEqual(result["active_version"], 1)
        self.assertEqual(
            result["accepted_edge_revocation"],
            ["concept drift", "drift diffusion"],
        )
        self.assertIn("drift diffusion", " ".join(result["before_case"]["queries"]))
        self.assertIn("distribution shift", " ".join(result["cases"][0]["queries"]))
        self.assertEqual(result["active_score"], 1.0)
        self.assertFalse(result["second_pass"]["accepted"])
        self.assertEqual(result["second_pass"]["active_version"], 1)
        self.assertEqual(result["second_pass"]["active_score"], 1.0)


if __name__ == "__main__":
    unittest.main()
