from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eonrise.scheduling import ProviderStates, order_for

ALL = ["crossref", "openalex", "europepmc", "doaj"]


class OrderTests(unittest.TestCase):
    def test_a_missing_abstract_gap_asks_the_abstract_source_first(self):
        self.assertEqual(order_for(ALL, ["failure_mode"])[0], "europepmc")

    def test_a_missing_neighbour_field_prefers_a_source_with_subjects(self):
        self.assertIn(order_for(ALL, ["neighbor_field"])[0], {"doaj", "openalex", "europepmc"})

    def test_crossref_is_never_first_while_richer_sources_are_available(self):
        for gaps in ([], ["mechanism"], ["neighbor_field"], ["failure_mode", "neighbor_field"]):
            self.assertNotEqual(order_for(ALL, gaps)[0], "crossref", f"gaps={gaps}")

    def test_a_cheap_source_wins_a_tie(self):
        # doaj and openalex both supply subjects; openalex costs 10 credits a search.
        order = order_for(["openalex", "doaj"], ["neighbor_field"])
        self.assertEqual(order[0], "doaj")

    def test_every_provider_still_gets_called(self):
        self.assertEqual(sorted(order_for(ALL, ["failure_mode"])), sorted(ALL))

    def test_an_unknown_provider_is_ordered_not_dropped(self):
        self.assertIn("mystery", order_for([*ALL, "mystery"], ["mechanism"]))


class BlockingTests(unittest.TestCase):
    def test_a_blocked_source_is_left_out_until_its_window_passes(self):
        states = ProviderStates()
        states.block("openalex", 3600, "rate limited", now=1000.0)
        self.assertNotIn("openalex", order_for(ALL, [], states, now=2000.0))
        self.assertIn("openalex", order_for(ALL, [], states, now=5000.0))

    def test_a_block_survives_the_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "providers.json"
            first = ProviderStates(path)
            first.block("openalex", 30746, "rate limited")
            first.save()
            self.assertFalse(ProviderStates(path).get("openalex").available(__import__("time").time()))

    def test_a_corrupt_state_file_does_not_stop_a_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "providers.json"
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(order_for(ALL, [], ProviderStates(path)), order_for(ALL, []))

    def test_success_and_failure_are_counted_separately(self):
        states = ProviderStates()
        states.observe("doaj", True); states.observe("doaj", False); states.observe("doaj", True)
        self.assertEqual((states.get("doaj").successes, states.get("doaj").failures), (2, 1))


if __name__ == "__main__":
    unittest.main()
