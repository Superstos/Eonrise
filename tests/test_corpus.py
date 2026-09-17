from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ontology_router.corpus import CorpusStore
from ontology_router.engine import run_agent
from ontology_router.models import AgentPolicy, Paper


def paper(pid, title, abstract="", doi="", keywords=(), cited=0, provider="crossref"):
    return Paper(pid, title, abstract, f"https://example.org/{pid}", doi, 2024, cited,
                 provider, list(keywords), [], [], "", [])


class CorpusStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "corpus.jsonl"
    def tearDown(self):
        self.tmp.cleanup()

    def test_a_second_run_reads_what_the_first_wrote(self):
        CorpusStore(self.path).add([paper("p1", "Spaced repetition and memory", "Retention improved.")])
        found = CorpusStore(self.path).search("spaced repetition memory")
        self.assertEqual([p.title for p in found], ["Spaced repetition and memory"])

    def test_the_same_paper_twice_is_stored_once(self):
        store = CorpusStore(self.path)
        store.add([paper("p1", "Memory study", "A.", doi="10.1/x")])
        store.add([paper("p2", "Memory study", "A.", doi="10.1/x")])
        self.assertEqual(store.stats()["papers"], 1)

    def test_a_thin_record_is_enriched_by_a_richer_one(self):
        store = CorpusStore(self.path)
        store.add([paper("p1", "Memory study", "", doi="10.1/x")])
        store.add([paper("p1", "Memory study", "Now with an abstract.", doi="10.1/x",
                         keywords=["retention"], provider="europepmc")])
        held = store.load()["10.1/x"]
        self.assertEqual(held.abstract, "Now with an abstract.")
        self.assertEqual(held.keywords, ["retention"])

    def test_metadata_enrichment_survives_reopening_the_store(self):
        store = CorpusStore(self.path)
        store.add([paper("p1", "Memory study", "An existing abstract.", doi="10.1/x")])
        richer = paper("p2", "Memory study", "An existing abstract.", doi="10.1/x",
                       keywords=["retention"], cited=12)
        richer.fields = ["Cognitive Psychology"]
        richer.topic_path = ["Memory consolidation"]
        richer.venue = "Memory Journal"
        richer.found_by = ["memory retention"]
        store.add([richer])
        before = store.load()["10.1/x"].to_dict()
        after = CorpusStore(self.path).load()["10.1/x"].to_dict()
        self.assertEqual(after, before)

    def test_papers_beyond_old_cap_survive_reopening(self):
        store = CorpusStore(self.path)
        self.assertEqual(store.add([Paper(str(i), f"Paper {i}") for i in range(50000)]), 50000)
        self.assertEqual(store.add([Paper("extra", "Memory retention")]), 1)
        reopened = CorpusStore(self.path)
        self.assertEqual(reopened.stats()["papers"], 50001)
        self.assertEqual(reopened.search("memory retention")[0].paper_id, "extra")
        self.assertEqual(store.stats(), reopened.stats())

    def test_full_local_answer_prevents_all_network_searches(self):
        store = CorpusStore(self.path)
        store.add([paper(f"p{i}", f"Memory retention study {i}",
                         "Memory retention improves.", doi=f"10.1/{i}") for i in range(8)])
        remote = mock.Mock()
        remote.name = "doaj"
        remote.search.return_value = []
        result = run_agent("memory retention", [store, remote],
                           AgentPolicy(max_rounds=1), results_per_query=8)
        self.assertEqual(result["retrieved_papers"], 8)
        remote.search.assert_not_called()
        self.assertEqual(result["calls_saved_by_corpus"], 1)

    def test_single_word_search_returns_only_matching_papers(self):
        store = CorpusStore(self.path)
        store.add([paper("on", "Memory consolidation"),
                   paper("off", "Coral reef bleaching")])
        self.assertEqual([p.paper_id for p in store.search("memory")], ["on"])
        self.assertEqual(store.search("volcano"), [])
        self.assertEqual(store.search("the"), [])
        self.assertEqual(store.search(""), [])
        self.assertEqual(store.search("memory retention"), [])

    def test_one_shared_common_word_is_not_a_match(self):
        store = CorpusStore(self.path)
        store.add([paper("p1", "Bridge rehabilitation in China", "Epoxy resin layers.")])
        self.assertEqual(store.search("memory retention in learning"), [])

    def test_a_truncated_line_does_not_lose_the_store(self):
        store = CorpusStore(self.path)
        store.add([paper("p1", "First paper", "A.", doi="10.1/a"),
                   paper("p2", "Second paper", "B.", doi="10.1/b")])
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write('{"title": "half written\n')
        self.assertEqual(CorpusStore(self.path).stats()["papers"], 2)

    def test_stored_papers_are_returned_as_copies(self):
        store = CorpusStore(self.path)
        store.add([paper("p1", "Memory study", "A.", doi="10.1/x")])
        got = store.search("memory study")[0]
        got.title = "mutated"
        self.assertEqual(store.load()["10.1/x"].title, "Memory study")

    def test_search_records_the_query_that_found_it(self):
        store = CorpusStore(self.path)
        store.add([paper("p1", "Memory study", "Retention.", doi="10.1/x")])
        self.assertIn("memory retention", store.search("memory retention")[0].found_by)

    def test_stats_counts_what_the_store_actually_holds(self):
        store = CorpusStore(self.path)
        store.add([paper("p1", "A paper", "abs", doi="10.1/a", keywords=["k"], provider="europepmc"),
                   paper("p2", "B paper", "", doi="10.1/b")])
        self.assertEqual(store.stats(), {"papers": 2, "with_abstract": 1, "with_keywords": 1,
                                         "providers": ["crossref", "europepmc"]})


if __name__ == "__main__":
    unittest.main()
