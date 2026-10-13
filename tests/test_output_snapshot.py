"""Whole-run outputs pinned byte for byte, so a refactor that changes a result fails here.

Regenerate only when a change of output is intended:
    EONRISE_UPDATE_SNAPSHOTS=1 python -m unittest tests.test_output_snapshot
"""
from __future__ import annotations

import json
import os
import re
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
_PATH_TAIL = re.compile(r'<dir>((?:\\+[^\\\s"]+)+)')
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


def _cli_output(extra: list[str]) -> dict:
    """The whole command: flags, stores under a fake home, files written, summary printed."""
    from unittest import mock
    from eonrise import cli
    with tempfile.TemporaryDirectory() as tmp:
        home, out = Path(tmp) / "home", Path(tmp) / "out"
        argv = ["eonrise", "how does spaced repetition improve memory retention",
                "--bundle", str(FIXTURES / "papers.json"), "--out", str(out), *extra]
        printed: list[str] = []
        with mock.patch("sys.argv", argv), mock.patch("pathlib.Path.home", return_value=home), \
                mock.patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(map(str, a)))):
            cli.main()
        files = {p.relative_to(tmp).as_posix(): p.read_text(encoding="utf-8")
                 for p in sorted(Path(tmp).rglob("*")) if p.is_file() and "observed_at" not in p.read_text(encoding="utf-8")}
        dirs = {d for raw in (tmp, str(FIXTURES)) for d in (raw, str(Path(raw).resolve()))}
        spellings = sorted({s for d in dirs for s in (d, json.dumps(d)[1:-1])}, key=len, reverse=True)

        def scrub(text: str) -> str:
            for spelling in spellings:
                text = text.replace(spelling, "<dir>")
            # Windows writes <dir>\home, Linux <dir>/home: pin one spelling for every OS.
            return _PATH_TAIL.sub(lambda m: "<dir>" + re.sub(r"\\+", "/", m.group(1)), text)
        return {"printed": [scrub(line) for line in printed],
                "files": {name: scrub(text) for name, text in files.items()}}


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

    def test_command_line_matches_snapshots(self):
        update = os.getenv("EONRISE_UPDATE_SNAPSHOTS") == "1"
        for name, extra in {"cli_stores": [], "cli_no_stores": ["--no-memory", "--no-corpus", "--no-equivalence"]}.items():
            with self.subTest(name):
                actual = _canonical(_cli_output(extra))
                path = SNAPSHOTS / f"{name}.json"
                if update:
                    path.write_bytes(actual.encode("utf-8"))
                self.assertEqual(path.read_text(encoding="utf-8"), actual)


if __name__ == "__main__":
    unittest.main()
