from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from eonrise import cli
from eonrise.distant_fields import what_they_did
from eonrise.models import Paper
from eonrise.output_guide import FIELDS, render_guide

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"


def _run_cli(tmp: Path, *extra: str, env: dict | None = None) -> Path:
    out = tmp / "out"
    argv = ["eonrise", "how does spaced repetition improve memory retention",
            "--bundle", str(FIXTURES / "papers.json"), "--out", str(out), *extra]
    with mock.patch("sys.argv", argv), mock.patch("pathlib.Path.home", return_value=tmp / "home"), \
            mock.patch.dict("os.environ", env or {}), mock.patch("builtins.print"):
        cli.main()
    return out


class OutputGuideTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_field_is_documented_and_no_stale_field_is(self):
        out = _run_cli(self.path)
        keys = set(json.loads((out / "research_map.json").read_text(encoding="utf-8")))
        self.assertEqual(sorted(keys - set(FIELDS)), [], "document these fields in output_guide.FIELDS")
        self.assertEqual(sorted(set(FIELDS) - keys), [], "these documented fields no longer exist")

    def test_every_run_folder_carries_the_guide(self):
        out = _run_cli(self.path)
        self.assertEqual((out / "README.md").read_text(encoding="utf-8"), render_guide())
        self.assertIn("README.md in this folder", (out / "report.md").read_text(encoding="utf-8"))

    @unittest.skipUnless((ROOT / "docs").is_dir(), "docs ship only in the repository, not the source package")
    def test_docs_page_is_the_guide(self):
        # Regenerate with: python -c "from eonrise.output_guide import render_guide as r; open('docs/OUTPUT.md','w',encoding='utf-8',newline='\n').write(r())"
        self.assertEqual((ROOT / "docs" / "OUTPUT.md").read_text(encoding="utf-8"), render_guide())


class CacheFolderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_cache_dir_keeps_every_store_inside_the_given_folder(self):
        _run_cli(self.path, "--cache-dir", str(self.path / "project" / ".eonrise"))
        self.assertTrue((self.path / "project" / ".eonrise" / "corpus.jsonl").exists())
        self.assertFalse((self.path / "home").exists())

    def test_environment_variable_sets_the_cache_folder(self):
        _run_cli(self.path, env={"EONRISE_CACHE_DIR": str(self.path / "env-cache")})
        self.assertTrue((self.path / "env-cache" / "corpus.jsonl").exists())
        self.assertFalse((self.path / "home").exists())

    def test_default_cache_is_under_home(self):
        _run_cli(self.path)
        self.assertTrue((self.path / "home" / ".cache" / "eonrise" / "corpus.jsonl").exists())


class WhatTheyDidTests(unittest.TestCase):
    def test_picks_the_sentence_that_says_what_was_done(self):
        p = Paper("e", "Species richness", abstract=(
            "Species richness is hard to know from samples alone in the field. "
            "We estimate richness from the species accumulation curve and test when sampling can stop. "
            "Funding came from a national science agency grant."))
        self.assertTrue(what_they_did(p, ["accumulation curve"]).startswith("We estimate richness"))

    def test_a_future_research_sentence_is_not_what_they_did(self):
        # Seen 2026-10-14: a gypsum review's "Future research should integrate ..." was shown.
        p = Paper("g", "Gypsum conversion", abstract=(
            "This review compares hydrothermal routes for converting by-product gypsum into hemihydrate. "
            "Future research should integrate process modeling and life cycle assessment."))
        self.assertTrue(what_they_did(p, ["process modeling", "life cycle"]).startswith("This review compares"))

    def test_journal_headers_are_never_the_answer(self):
        p = Paper("h", "Green chemistry", abstract=(
            "Science Education International ¦ Volume 32 ¦ Issue 2 107 ORIGINAL ARTICLE INTRODUCTION The method is used. "
            "Students reviewed green chemistry principles through a problem-based polycondensation lab."))
        self.assertTrue(what_they_did(p, ["problem based"]).startswith("Students reviewed"))

    def test_a_leading_section_label_is_dropped(self):
        p = Paper("a", "Neuropathy model", abstract="Abstract This study aims to develop a predictive model for neuropathy risk.")
        self.assertTrue(what_they_did(p, ["predictive model"]).startswith("This study aims"))
        kept = Paper("r", "Recall", abstract="Results show that spaced recall doubles retention after a week.")
        self.assertTrue(what_they_did(kept, ["spaced recall"]).startswith("Results show"))

    def test_no_abstract_gives_an_empty_answer(self):
        self.assertEqual(what_they_did(Paper("t", "A title only"), ["anything"]), "")

    def test_long_sentences_are_cut_at_a_word(self):
        p = Paper("l", "Long", abstract="We tested " + "a very long method description " * 20 + ".")
        did = what_they_did(p, ["method"])
        self.assertLessEqual(len(did), 241)
        self.assertTrue(did.endswith("…"))


if __name__ == "__main__":
    unittest.main()
