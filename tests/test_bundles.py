from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eonrise.providers import EvidenceBundleProvider, ProviderError


def _write(path: Path, rows) -> None:
    path.write_text(json.dumps(rows), encoding="utf-8")


class BundleTests(unittest.TestCase):
    """Evidence gathered by several searchers arrives as several files."""

    def test_folder_merges_every_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp) / "a.json", [{"paper_id": "a", "title": "Analogy mining for innovation"}])
            _write(Path(tmp) / "b.json", {"papers": [{"paper_id": "b", "title": "Bisociative discovery"}]})
            provider = EvidenceBundleProvider(tmp)
            self.assertEqual({p.paper_id for p in provider.papers}, {"a", "b"})

    def test_same_doi_from_two_searchers_is_one_richer_paper(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp) / "a.json", [{"paper_id": "x", "title": "Analogy mining", "doi": "10.1/X"}])
            _write(Path(tmp) / "b.json", [{"paper_id": "y", "title": "Analogy mining", "doi": "https://doi.org/10.1/x",
                                           "abstract": "Purpose and mechanism vectors.", "keywords": ["analogy"]}])
            papers = EvidenceBundleProvider([Path(tmp) / "a.json", Path(tmp) / "b.json"]).papers
            self.assertEqual(len(papers), 1)
            self.assertEqual(papers[0].abstract, "Purpose and mechanism vectors.")
            self.assertEqual(papers[0].keywords, ["analogy"])

    def test_untitled_rows_are_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp) / "a.json", [{"paper_id": "a"}, {"paper_id": "b", "title": "Kept"}])
            self.assertEqual([p.title for p in EvidenceBundleProvider(tmp).papers], ["Kept"])

    def test_missing_or_broken_bundle_names_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ProviderError):
                EvidenceBundleProvider(Path(tmp) / "absent.json")
            (Path(tmp) / "bad.json").write_text("[{", encoding="utf-8")
            with self.assertRaisesRegex(ProviderError, "bad.json"):
                EvidenceBundleProvider(Path(tmp) / "bad.json")


if __name__ == "__main__":
    unittest.main()
