from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ontology_router.engine import run_agent
from ontology_router.equivalence import (
    ConceptEquivalenceGraph,
    ConceptEquivalenceStore,
    discover_observations,
)
from ontology_router.equivalence_benchmark import run_benchmark
from ontology_router.models import AgentPolicy, Paper


def evidence(pid: str, kind: str = "explicit_alias", field: str = "Machine Learning") -> dict:
    return {
        "paper_id": pid,
        "paper_key": f"doi:10.9/{pid}",
        "kind": kind,
        "field": field,
        "example": "Distribution shift, also known as concept drift, changes results.",
        "query": "concept drift",
    }


def learned_edge(store: ConceptEquivalenceStore, second_field: str = "Statistics") -> dict:
    first = store.append_observation(
        "concept drift", "distribution shift", "equivalent", [evidence("p1")]
    )
    assert first is not None
    second = store.append_observation(
        "distribution shift",
        "concept drift",
        "equivalent",
        [evidence("p2", field=second_field)],
    )
    assert second is not None
    return second


class EquivalenceStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "equivalence.jsonl"
        self.addCleanup(self.tmp.cleanup)

    def test_relationship_persistence(self):
        store = ConceptEquivalenceStore(self.path)
        learned_edge(store)
        reopened = ConceptEquivalenceStore(self.path).load()
        edge = reopened.edge_for("concept drift", "distribution shift")
        self.assertIsNotNone(edge)
        assert edge is not None
        self.assertEqual(edge["relation"], "equivalent")
        self.assertEqual(edge["support_count"], 2)
        self.assertEqual(edge["fields"], ["Machine Learning", "Statistics"])
        self.assertGreaterEqual(edge["confidence"], 0.75)

    def test_duplicate_evidence_merges(self):
        store = ConceptEquivalenceStore(self.path)
        first = store.append_observation("alpha beta", "gamma delta", "equivalent", [evidence("p1")])
        second = store.append_observation("gamma delta", "alpha beta", "equivalent", [evidence("p1")])
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        assert first is not None and second is not None
        self.assertEqual(first["support_count"], 1)
        self.assertEqual(second["support_count"], 1)
        self.assertEqual(second["confidence"], first["confidence"])
        self.assertEqual(len(ConceptEquivalenceStore(self.path).load().edges()), 1)

    def test_confidence_grows_with_independent_support(self):
        store = ConceptEquivalenceStore(self.path)
        one = store.append_observation("alpha beta", "gamma delta", "equivalent", [evidence("p1")])
        two = store.append_observation("alpha beta", "gamma delta", "equivalent", [evidence("p2")])
        three = store.append_observation("alpha beta", "gamma delta", "equivalent", [evidence("p3")])
        assert one is not None and two is not None and three is not None
        self.assertEqual((one["support_count"], two["support_count"], three["support_count"]), (1, 2, 3))
        self.assertLess(one["confidence"], two["confidence"])
        self.assertLess(two["confidence"], three["confidence"])

    def test_repeated_co_occurrence_is_not_an_equivalence(self):
        store = ConceptEquivalenceStore(self.path)
        store.append_observation("robustness", "reliability", "equivalent",
                                 [evidence("p1", kind="co_occurrence"),
                                  evidence("p2", kind="co_occurrence")])
        graph = store.load()
        self.assertEqual(graph.aliases_for("robustness"), ())
        self.assertEqual(graph.aliases_for("reliability"), ())
        edge = graph.edge_for("robustness", "reliability")
        assert edge is not None
        self.assertEqual(edge["relation"], "closely_related")

    def test_malformed_store_recovery(self):
        store = ConceptEquivalenceStore(self.path)
        learned_edge(store)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write('{"schema_version": 1, "type": "observation", "a": "half\n')
            handle.write('["not", "a", "record"]\n')
            handle.write('{"schema_version": 99, "type": "observation"}\n')
        edge = ConceptEquivalenceStore(self.path).load().edge_for("concept drift", "distribution shift")
        self.assertIsNotNone(edge)
        assert edge is not None
        self.assertEqual(edge["support_count"], 2)

    def test_no_self_equivalence(self):
        store = ConceptEquivalenceStore(self.path)
        self.assertIsNone(store.append_observation("Concept Drift", "concept drift!",
                                                   "equivalent", [evidence("p1"), evidence("p2")]))
        self.assertIsNone(store.append_observation("search algorithm", "algorithm search",
                                                   "equivalent", [evidence("p1"), evidence("p2")]))
        self.assertEqual(store.load().edges(), [])

    def test_order_insensitive_concept_identity(self):
        store = ConceptEquivalenceStore(self.path)
        learned_edge(store)
        edge = store.load().edge_for("distribution shift", "CONCEPT drift")
        assert edge is not None
        self.assertEqual((edge["a"], edge["b"]), ("concept drift", "distribution shift"))

    def test_revocation_survives_reopening(self):
        store = ConceptEquivalenceStore(self.path)
        learned_edge(store)
        self.assertTrue(store.revoke("distribution shift", "concept drift", "polysemy"))
        reopened = ConceptEquivalenceStore(self.path).load()
        self.assertTrue(reopened.is_revoked("concept drift", "distribution shift"))
        self.assertEqual(reopened.aliases_for("concept drift"), ())

    def test_off_topic_evidence_is_not_learned(self):
        papers = [
            Paper("p1", "Concept drift study", "Distribution shift, also known as concept drift.",
                  "", "", 2024, 0, "benchmark", ["concept drift", "distribution shift"], [], [], "", []),
        ]
        terms = [{"text": "concept drift", "relation": "topic", "confidence": "high",
                  "paper_ids": ["p1"]},
                 {"text": "distribution shift", "relation": "topic", "confidence": "high",
                  "paper_ids": ["p1"]}]
        self.assertEqual(discover_observations("concept drift", terms, papers, set()), [])


class QueryExpansionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "equivalence.jsonl"
        self.addCleanup(self.tmp.cleanup)
        store = ConceptEquivalenceStore(self.path)
        learned_edge(store)
        self.graph = store.load()

    def test_query_expansion_preserves_original(self):
        expanded = self.graph.expand_query("concept drift in deployed models")
        self.assertEqual(expanded, ["distribution shift in deployed models"])

    def test_no_recursive_query_explosion(self):
        store = ConceptEquivalenceStore(self.path)
        store.append_observation("distribution shift", "regime change", "equivalent",
                                 [evidence("q1"), evidence("q2")])
        graph = store.load()
        self.assertEqual(graph.expand_query("concept drift"), ["distribution shift"])
        self.assertNotIn("regime change", graph.expand_query("concept drift"))

    def test_ambiguous_component_does_not_expand(self):
        store = ConceptEquivalenceStore(self.path)
        for index in range(9):
            store.append_observation("hub concept", f"spoke concept {index}", "equivalent",
                                     [evidence(f"a-{index}"), evidence(f"b-{index}")])
        self.assertEqual(store.load().expand_query("hub concept"), [])

    def test_expansion_matches_across_hyphenation(self):
        store = ConceptEquivalenceStore(self.path)
        store.append_observation("feedback loop", "closed-loop control", "equivalent",
                                 [evidence("p1"), evidence("p2")])
        self.assertEqual(store.load().expand_query("feedback loop"),
                         ["closed-loop control"])

    def test_disabled_expansion_changes_nothing(self):
        class Recording:
            name = "recording"

            def __init__(self):
                self.queries: list[str] = []

            def search(self, query, limit=20):
                self.queries.append(query)
                return []

        provider = Recording()
        result = run_agent("concept drift", [provider], AgentPolicy(max_rounds=1),
                           equivalence=self.graph, query_expansion_slots=0)
        self.assertEqual(provider.queries, ["concept drift"])
        self.assertEqual(result["query_expansion"]["slots_used"], 0)

    def test_expanded_query_reaches_provider(self):
        class Recording:
            name = "recording"

            def __init__(self):
                self.queries: list[str] = []

            def search(self, query, limit=20):
                self.queries.append(query)
                paper = Paper("p1", "Concept drift", "", "", "", 2024, 0,
                              "recording", [], [], [], "", [])
                paper.found_by = [query]
                return [paper]

        provider = Recording()
        result = run_agent("concept drift", [provider], AgentPolicy(max_rounds=1),
                           equivalence=self.graph, query_expansion_slots=1)
        self.assertIn("distribution shift", provider.queries)
        self.assertEqual(result["query_expansion"]["slots_used"], 1)
        self.assertIn("distribution shift", result["query_expansion"]["expanded_queries"])
        self.assertIn("distribution shift", result["papers"][0]["found_by"])

    def test_expansion_leaves_graph_artifact_shape_unchanged(self):
        class Empty:
            name = "empty"

            def search(self, query, limit=20):
                return []

        result = run_agent("concept drift", [Empty()], AgentPolicy(max_rounds=1),
                           equivalence=self.graph, query_expansion_slots=1)
        self.assertEqual(set(result["graph"].keys()), {"nodes", "edges"})


class EquivalenceBenchmarkTests(unittest.TestCase):
    def test_benchmark_passes_kill_rule(self):
        result = run_benchmark()
        self.assertEqual(result["true_equivalences_discovered"], result["true_equivalences"])
        self.assertEqual(result["false_equivalence_rate"], 0.0)
        self.assertGreater(result["median_retrieval_gain"], 0.0)
        self.assertGreater(result["net_median_gain"], 0.0)
        self.assertTrue(result["passed_kill_rule"])


if __name__ == "__main__":
    unittest.main()
