"""Whole-run outputs pinned byte for byte, so a refactor that changes a result fails here.

Regenerate only when a change of output is intended:
    EONRISE_UPDATE_SNAPSHOTS=1 python -m unittest tests.test_output_snapshot
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from eonrise.engine import run_search
from eonrise.equivalence import ConceptEquivalenceStore
from eonrise.models import Paper, SearchSettings
from eonrise.providers import EvidenceBundleProvider
from eonrise.report import render_compact_markdown, render_markdown

FIXTURES = Path(__file__).parent / "fixtures"
SNAPSHOTS = FIXTURES / "snapshots"
SCENARIOS = {
    "readme": ("papers.json", "how does spaced repetition improve memory retention"),
    "crossfield": ("crossfield_gold.json", None),
    "heldout": ("heldout_battery.json", None),
}


def _scenario_output(bundle: str, question: str | None) -> dict:
    path = FIXTURES / bundle
    question = question or json.loads(path.read_text(encoding="utf-8"))["question"]
    result = run_search(question, [EvidenceBundleProvider(path)],
                        SearchSettings(max_rounds=6, max_nodes=160), results_per_query=25)
    with tempfile.TemporaryDirectory() as tmp:
        store = ConceptEquivalenceStore(Path(tmp) / "equivalence.jsonl")
        papers = [Paper.from_dict(row) for row in result.get("corpus_papers") or result["papers"]]
        learned = store.observe_run(question, result.get("terms", []), papers,
                                    set(result.get("on_topic_paper_ids", [])))
        edges = store.load().edges()
    learned = [{k: v for k, v in row.items() if k != "observed_at"} for row in learned]
    edges = [{k: v for k, v in row.items() if k != "observed_at"} for row in edges]
    return {"result": result, "learned": learned, "edges": edges,
            "compact": render_compact_markdown(result), "full": render_markdown(result)}


def _canonical(data: dict) -> str:
    return json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False, default=sorted) + "\n"


class OutputSnapshotTests(unittest.TestCase):
    def test_outputs_match_snapshots(self):
        update = os.getenv("EONRISE_UPDATE_SNAPSHOTS") == "1"
        for name, (bundle, question) in SCENARIOS.items():
            with self.subTest(name):
                actual = _canonical(_scenario_output(bundle, question))
                path = SNAPSHOTS / f"{name}.json"
                if update:
                    SNAPSHOTS.mkdir(exist_ok=True)
                    path.write_bytes(actual.encode("utf-8"))
                self.assertEqual(path.read_text(encoding="utf-8"), actual)


if __name__ == "__main__":
    unittest.main()
