"""Release checks: unit tests, attack tests and offline runs (stdlib only).

Usage:
  python -m benchmarks.run            # full loop: unit tests + redteam + live smoke note
  python -m benchmarks.run --quick    # unit tests only
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from eonrise.engine import run_search
from eonrise.models import Paper, SearchSettings
from eonrise.providers import EvidenceBundleProvider
from eonrise.report import write_outputs

ARTIFACTS = ["research_map.json", "report.md", "internal_report.md", "graph.json"]


def run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _unit_suite() -> tuple[bool, str]:
    code, out = run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"])
    return code == 0, out[-3000:]


def _assistant_smoke() -> tuple[bool, str]:
    """Offline assistant run: must produce all 4 artifacts without network."""
    with tempfile.TemporaryDirectory() as tmp:
        result = run_search(
            "how does spaced repetition improve memory retention",
            [EvidenceBundleProvider("tests/fixtures/papers.json")],
            SearchSettings(name="benchmark", max_nodes=50, max_depth=3, max_rounds=3),
            results_per_query=10,
        )
        result["mode"] = "assistant"
        result["input_bundle"] = "tests/fixtures/papers.json"
        write_outputs(result, Path(tmp) / "out")
        ok = all((Path(tmp) / "out" / a).exists() for a in ARTIFACTS)
    concepts = len(result.get("concepts", []))
    ok = ok and bool(result.get("root_topic")) and concepts >= 1
    return ok, f"root={result.get('root_topic')} concepts={concepts} papers={len(result.get('papers', []))}"


class _Mixed:
    """Half on-topic papers, half a neighbouring literature."""

    name = "benchmark-mixed"

    def search(self, query, limit=20):
        on = [Paper(f"on{i}", f"Saturation criteria for iterative exploration, study {i}",
                    keywords=["saturation"]) for i in range(10)]
        off = [Paper(f"off{i}", f"Protein structure and dynamics under iterative refinement, part {i}",
                     keywords=["protein structure and dynamics"]) for i in range(12)]
        return on + off


def _drift_guard() -> tuple[bool, str]:
    """The neighbouring literature must not reach the map."""
    drift = run_search("when should an iterative search or exploration process stop using saturation",
                       [_Mixed()], SearchSettings(name="benchmark", max_nodes=60, max_depth=3, max_rounds=2))
    labels = " ".join(c["label"] for c in drift["concepts"]) + " " + " ".join(t["text"] for t in drift["terms"])
    ok = "protein" not in labels and bool(drift["terms"])
    return ok, f"concepts={len(drift['concepts'])} on_topic={drift.get('on_topic_papers')}"


def _gate(name: str, check) -> tuple[str, bool, str]:
    try:
        return (name, *check())
    except Exception as exc:  # noqa: BLE001 - the runner must report, not crash
        return name, False, f"{type(exc).__name__}: {exc}"


def main() -> None:
    gates = [_gate("unit+redteam suite passes", _unit_suite)]
    if "--quick" not in sys.argv:
        gates.append(_gate("assistant smoke emits 4 artifacts + root", _assistant_smoke))
        gates.append(_gate("drift guard keeps a neighbouring literature out", _drift_guard))

    print("# Release check report")
    for name, passed, detail in gates:
        print(f"- [{'PASS' if passed else 'FAIL'}] {name}")
        if not passed:
            print(f"  detail: {detail[-1500:]}")
    failed = sum(not passed for _, passed, _ in gates)
    print(f"\n{'CLEAR' if failed == 0 else 'BLOCKED'}: {len(gates) - failed}/{len(gates)} gates passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
