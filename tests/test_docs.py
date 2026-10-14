"""Docs that name a flag, file or environment variable must name a real one, so a rename
in the code fails here instead of leaving the README describing a tool that no longer exists."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from eonrise import cli

ROOT = Path(__file__).resolve().parent.parent
DOCS = ["README.md", "CONTRIBUTING.md", "AGENTS.md", "SECURITY.md", "docs/USAGE.md",
        ".github/PULL_REQUEST_TEMPLATE.md", ".github/ISSUE_TEMPLATE/bug.yml",
        ".github/ISSUE_TEMPLATE/feature.yml"]
OTHER_TOOLS_FLAGS = {"--quick"}  # python -m benchmarks.run --quick
REPO_TOP = ("docs/", "tests/", "eonrise/", "benchmarks/", ".github/")


@unittest.skipUnless((ROOT / ".github").is_dir(), "docs ship only in the repository, not the source package")
class DocsMatchCodeTests(unittest.TestCase):
    def _text(self, name: str) -> str:
        return (ROOT / name).read_text(encoding="utf-8")

    def test_every_flag_in_the_docs_exists(self):
        known = {flag for action in cli.parser()._actions for flag in action.option_strings}
        for name in DOCS:
            for flag in set(re.findall(r"(?<![\w-])--[a-z][a-z0-9-]*", self._text(name))):
                with self.subTest(doc=name, flag=flag):
                    self.assertIn(flag, known | OTHER_TOOLS_FLAGS)

    def test_every_repo_path_in_the_docs_exists(self):
        for name in DOCS:
            for path in set(re.findall(r"[`(\[]((?:[\w.-]+/)*[\w.-]+\.(?:md|json|py|yml|toml|cff))[`)\]]", self._text(name))):
                if path.startswith(REPO_TOP) or path[0].isupper():  # bare lowercase names are run outputs
                    with self.subTest(doc=name, path=path):
                        self.assertTrue((ROOT / path).exists() or (ROOT / name).parent.joinpath(path).exists())

    def test_every_environment_variable_in_the_docs_is_read(self):
        source = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "eonrise").glob("*.py"))
        for name in DOCS:
            for var in set(re.findall(r"`([A-Z][A-Z0-9]*_[A-Z0-9_]+)`", self._text(name))):
                with self.subTest(doc=name, var=var):
                    self.assertIn(f'getenv("{var}"', source)

    def test_numbers_the_readme_states(self):
        import json
        readme = self._text("README.md")
        demo = json.loads((ROOT / "eonrise" / "data" / "demo_bundle.json").read_text(encoding="utf-8"))
        self.assertIn(f"a sample of {len(demo['papers'])} papers", readme)
        defaults = cli._provider_names(cli.parser().parse_args(["q", "--s2-key", "", "--core-key", ""]), {})
        words = {4: "Four", 5: "Five", 6: "Six"}
        self.assertIn(f"{words[len(defaults)]} sources run by default", readme)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless((ROOT / "CITATION.cff").is_file(), "the citation file ships only in the repository")
class CitationTests(unittest.TestCase):
    def test_citation_version_matches_the_package(self):
        from eonrise import __version__
        text = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
        self.assertIn(f"\nversion: {__version__}\n", text)
