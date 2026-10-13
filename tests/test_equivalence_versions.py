from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from eonrise.engine import run_search
from eonrise.equivalence import ConceptEquivalenceStore
from eonrise.equivalence_versions import evolve_equivalence_state
from eonrise.models import SearchSettings, Paper
from eonrise.scheduling import ProviderStates


class ReplayProvider:
    name = "evolution-test"

    def __init__(self, papers):
        self.papers = list(papers)

    def search(self, query, limit=20):
        wanted = {t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 2}
        ranked = []
        for paper in self.papers:
            text = {t for t in re.findall(
                r"[a-z0-9]+", f"{paper.title} {paper.abstract}".lower()
            ) if len(t) > 2}
            hits = len(wanted & text)
            if hits:
                clone = Paper.from_dict(paper.to_dict())
                clone.found_by = [query]
                ranked.append((hits / max(1, len(wanted)), clone))
        ranked.sort(key=lambda row: row[0], reverse=True)
        return [paper for _, paper in ranked[:limit]]


def evidence(pid, field):
    return {
        "paper_id": pid,
        "paper_key": f"doi:10.9/{pid}",
        "kind": "explicit_alias",
        "field": field,
        "example": "explicit terminology evidence",
        "query": "concept drift",
    }


def paper(pid, title, abstract, keywords, fields):
    return Paper(
        paper_id=pid,
        title=title,
        abstract=abstract,
        url=f"https://example.org/{pid}",
        doi=f"10.9/{pid}",
        year=2026,
        cited_by_count=1,
        provider="evolution-test",
        keywords=keywords,
        fields=fields,
        topic_path=[],
        venue="",
        found_by=[],
    )


class EvolutionTests(unittest.TestCase):
    def test_promotes_measured_win_and_stops_when_no_better_candidate_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed = root / "equivalence.jsonl"
            store = ConceptEquivalenceStore(seed)

            store.append_observation(
                "concept drift", "distribution shift", "equivalent",
                [evidence("good-1", "Machine Learning")],
            )
            store.append_observation(
                "concept drift", "distribution shift", "equivalent",
                [evidence("good-2", "Statistics")],
            )
            for index, field in enumerate(("Physics", "Finance", "Cognitive Science"), 1):
                store.append_observation(
                    "concept drift", "drift diffusion", "equivalent",
                    [evidence(f"bad-{index}", field)],
                )

            papers = [
                *[
                    paper(
                        f"base-{i}",
                        f"Concept drift in adaptive models {i}",
                        "Concept drift changes model performance over time.",
                        ["concept drift", "machine learning"],
                        ["Machine Learning"],
                    )
                    for i in range(1, 4)
                ],
                *[
                    paper(
                        f"alternate-{i}",
                        f"Distribution shift in deployed models {i}",
                        "Distribution shift changes model performance after deployment.",
                        ["distribution shift", "concept drift", "machine learning"],
                        ["Machine Learning"],
                    )
                    for i in range(1, 7)
                ],
                *[
                    paper(
                        f"decoy-{i}",
                        f"Drift diffusion process {i}",
                        "Drift diffusion models describe noisy evidence accumulation.",
                        ["drift diffusion"],
                        ["Cognitive Science"],
                    )
                    for i in range(1, 7)
                ],
            ]
            relevant = {f"base-{i}" for i in range(1, 4)} | {
                f"alternate-{i}" for i in range(1, 7)
            }

            def score(graph):
                result = run_search(
                    "concept drift",
                    [ReplayProvider(papers)],
                    SearchSettings(
                        name="evolution-test",
                        max_nodes=30,
                        max_depth=1,
                        max_rounds=1,
                        support_threshold=1,
                    ),
                    results_per_query=20,
                    background=set(),
                    states=ProviderStates(),
                    equivalence=graph,
                    query_expansion_slots=1,
                )
                found = {row["paper_id"] for row in result.get("papers", [])[:20]}
                return len(found & relevant) / len(relevant)

            state_root = root / "state"
            first = evolve_equivalence_state(seed, state_root, score)

            self.assertEqual(first["parent_score"], 1 / 3)
            self.assertEqual(first["active_score"], 1.0)
            self.assertTrue(first["accepted"])
            self.assertEqual(first["active_version"], 1)
            self.assertEqual(
                first["accepted_edge_revocation"],
                ["concept drift", "drift diffusion"],
            )

            second = evolve_equivalence_state(seed, state_root, score)
            self.assertFalse(second["accepted"])
            self.assertEqual(second["active_version"], 1)
            self.assertEqual(second["active_score"], 1.0)


if __name__ == "__main__":
    unittest.main()
