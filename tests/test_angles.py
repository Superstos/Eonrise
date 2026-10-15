import json
import tempfile
import unittest
from pathlib import Path

from eonrise import angles


def _run_folder(root: Path, name: str, papers: list[tuple[str, str]]) -> Path:
    folder = root / name
    folder.mkdir()
    data = {"question": name, "root_topic": name, "status": "usable",
            "papers": [{"title": t, "fields": [f]} for t, f in papers]}
    (folder / "research_map.json").write_text(json.dumps(data), encoding="utf-8")
    return folder


class AnglesTest(unittest.TestCase):
    def test_questions_skip_blank_and_comment_lines(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "q.txt"
            path.write_text("# seeds\nfirst question\n\n  second question  \n", encoding="utf-8")
            self.assertEqual(angles.read_questions(str(path)), ["first question", "second question"])

    def test_merge_counts_unique_papers_and_new_fields_in_order(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            a = _run_folder(root, "angle-1", [("Shared", "Ecology"), ("Only A", "Ecology")])
            b = _run_folder(root, "angle-2", [("shared", "Ecology"), ("Only B", "Nursing")])
            merged = angles.write_merge(root, [a, b, root / "angle-3"])
            self.assertEqual(merged["papers"], 3)
            self.assertEqual([r["only_here"] for r in merged["angles"]], [1, 1])
            self.assertEqual([r["new_fields"] for r in merged["angles"]], [["Ecology"], ["Nursing"]])
            self.assertIn("Last angle added 1 new fields", (root / "angles.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
