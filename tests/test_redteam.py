from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eonrise.engine import run_agent
from eonrise.models import STATUSES, AgentPolicy, Paper
from eonrise.providers import EvidenceBundleProvider

FIXTURE = Path(__file__).parent / "fixtures" / "papers.json"


def run(q: str, **kw) -> dict:
    policy_kw = {k: v for k, v in kw.items() if k in
                 {"max_nodes", "max_depth", "max_rounds", "support_threshold"}}
    return run_agent(q, [EvidenceBundleProvider(str(FIXTURE))],
                     AgentPolicy(**{"max_nodes": 40, "max_depth": 3, "max_rounds": 3, **policy_kw}))


class RedteamTests(unittest.TestCase):
    """Gauntlet redteam: 6 offline attacks. None may crash; gaps must stay honest."""

    def test_vague_query(self):
        r = run("stuff about thinking and things")
        self.assertIn(r["status"], STATUSES)
        self.assertTrue(r["root_topic"])

    def test_single_word(self):
        r = run("memory")
        self.assertGreater(len(r["papers"]), 0)
        self.assertEqual(r["concepts"][0]["direction"], "root")

    def test_non_english(self):
        r = run("mémoire et oubli apprentissage")
        self.assertIn(r["status"], STATUSES)
        self.assertTrue(r["root_topic"])

    def test_empty_bundle(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            fh.write("[]")
            path = fh.name
        try:
            r = run_agent("memory", [EvidenceBundleProvider(path)], AgentPolicy(max_rounds=2))
            self.assertEqual(r["status"], "failed")
            self.assertEqual(r["papers"], [])
            self.assertTrue(r["gaps"])
        finally:
            Path(path).unlink(missing_ok=True)

    def test_duplicate_papers_deduped(self):
        rows = json.loads(FIXTURE.read_text(encoding="utf-8"))
        doubled = rows + [dict(x) for x in rows]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump(doubled, fh)
            path = fh.name
        try:
            r = run_agent("memory retention", [EvidenceBundleProvider(path)],
                          AgentPolicy(max_nodes=60, max_depth=2, max_rounds=2))
            titles = [p["title"] for p in r["papers"]]
            self.assertEqual(len(titles), len(set(titles)))
        finally:
            Path(path).unlink(missing_ok=True)

    def test_hostile_input_no_crash(self):
        r = run("'; DROP TABLE papers; -- <script>alert(1)</script>" * 3)
        self.assertIn(r["status"], STATUSES)
        for paper in r["papers"]:
            self.assertIsInstance(paper, dict)

    def test_urls_preserved_where_present(self):
        rows = json.loads(FIXTURE.read_text(encoding="utf-8"))
        rows[0]["url"] = "https://example.com/p1"
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump(rows, fh)
            path = fh.name
        try:
            r = run_agent("memory", [EvidenceBundleProvider(path)], AgentPolicy(max_rounds=2))
            by_id = {p["paper_id"]: p for p in r["papers"]}
            if "p1" in by_id:
                self.assertEqual(by_id["p1"]["url"], "https://example.com/p1")
        finally:
            Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
