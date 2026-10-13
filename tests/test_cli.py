from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from eonrise import cli
from eonrise import report


class SilentFailureTests(unittest.TestCase):
    """A run that retrieved nothing exited 0 with a brief that read like a thin
    literature. Reported 2026-09-16: a socket timeout against Europe PMC produced a
    `failed` status, exit 0, and no signal a caller could branch on."""

    FAILED = {"question": "q", "root_topic": "q", "status": "failed",
              "stop_reason": "no papers could be retrieved",
              "papers": [], "retrieved_papers": 0, "on_topic_papers": 0, "concepts": [],
              "coverage": {"mechanism": []}, "gaps": ["mechanism"],
              "recommended_queries": [], "limitations": [],
              "providers_down": ["europepmc"],
              "provider_errors": ["europepmc: Request failed: https://www.ebi.ac.uk/: timed out"]}

    def _run_cli(self, bundle: str, out: str, question: str = "attention mechanisms in transformers") -> int:
        argv = ["eonrise", question, "--mode", "assistant",
                "--bundle", bundle, "--out", out, "--no-memory", "--no-corpus"]
        with mock.patch("sys.argv", argv), mock.patch("builtins.print"):
            try:
                cli.main()
            except SystemExit as exc:
                return int(exc.code or 0)
        return 0

    def test_empty_run_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "empty.json"
            bundle.write_text('{"papers": []}', encoding="utf-8")
            self.assertEqual(self._run_cli(str(bundle), str(Path(tmp) / "out")), 2)

    def test_healthy_run_still_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(__file__).parent / "fixtures" / "papers.json"
            # The bundle is a memory/forgetting literature, so the question has to be one
            # it can actually answer: since the zero-topical guard landed, asking it about
            # transformers is a failed search, and correctly exits 2.
            self.assertEqual(self._run_cli(str(fixture), str(Path(tmp) / "out"),
                                           "how does spaced repetition improve memory retention"), 0)

    def test_failed_off_topic_run_does_not_claim_nothing_was_retrieved(self):
        result = {**self.FAILED, "papers": [{"title": "Coral reef bleaching"}],
                  "retrieved_papers": 20,
                  "stop_reason": "20 papers retrieved, none about the question"}
        text = report.render_compact_markdown(result)
        self.assertIn("No retrieved paper was about this question", text)
        self.assertIn("timed out", text)
        self.assertNotIn("This run retrieved nothing", text)
        self.assertNotIn("map below is empty", text)

    def test_brief_blames_the_search_not_the_literature(self):
        text = report.render_compact_markdown(self.FAILED)
        self.assertIn("the search failed, not because the literature is silent", text)
        self.assertIn("timed out", text)
        self.assertNotIn("**Degraded:**", text)  # that line reads as a usable partial run



class StartupFlagTests(unittest.TestCase):
    def _main(self, *argv):
        printed: list[str] = []
        with mock.patch("sys.argv", ["eonrise", *argv]),                 mock.patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(map(str, a)))):
            cli.main()
        return printed

    def test_version_prints_the_package_version(self):
        from eonrise import __version__
        with mock.patch("sys.argv", ["eonrise", "--version"]),                 mock.patch("sys.stdout.write") as write, self.assertRaises(SystemExit) as stop:
            cli.main()
        self.assertEqual(stop.exception.code, 0)
        self.assertIn(__version__, "".join(call.args[0] for call in write.call_args_list))

    def test_question_is_required_without_demo(self):
        with mock.patch("sys.argv", ["eonrise"]), mock.patch("sys.stderr.write"),                 self.assertRaises(SystemExit) as stop:
            cli.main()
        self.assertEqual(stop.exception.code, 2)

    def test_demo_runs_offline_and_writes_only_to_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, out = Path(tmp) / "home", Path(tmp) / "out"
            with mock.patch("pathlib.Path.home", return_value=home):
                self._main("--demo", "--out", str(out))
            self.assertFalse(home.exists())
            brief = (out / "report.md").read_text(encoding="utf-8")
        self.assertIn("## Same shape, other fields", brief)


if __name__ == "__main__":
    unittest.main()
