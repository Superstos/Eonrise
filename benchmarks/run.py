from __future__ import annotations

"""Release checks: unit tests, attack tests and offline runs (stdlib only).

Usage:
  python -m benchmarks.run            # full loop: unit tests + redteam + live smoke note
  python -m benchmarks.run --quick    # unit tests only
"""
import subprocess
import sys


def run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main() -> None:
    quick = "--quick" in sys.argv
    gates: list[tuple[str, bool, str]] = []

    code, out = run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"])
    gates.append(("unit+redteam suite passes", code == 0, out[-3000:]))

    if not quick:
        # Offline assistant smoke: must produce all 4 artifacts without network.
        import json
        import tempfile
        from pathlib import Path
        from eonrise.engine import run_search
        from eonrise.models import SearchSettings
        from eonrise.providers import EvidenceBundleProvider
        from eonrise.report import write_outputs

        try:
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
                artifacts = ["research_map.json", "report.md", "internal_report.md", "graph.json"]
                ok = all((Path(tmp) / "out" / a).exists() for a in artifacts)
                ok = ok and bool(result.get("root_topic")) and len(result.get("concepts", [])) >= 1
                gates.append(("assistant smoke emits 4 artifacts + root", ok,
                              f"root={result.get('root_topic')} concepts={len(result.get('concepts', []))} papers={len(result.get('papers', []))}"))
        except Exception as exc:  # noqa: BLE001 - the runner must report, not crash
            gates.append(("assistant smoke emits 4 artifacts + root", False, f"{type(exc).__name__}: {exc}"))

    if not quick:
        # Offline drift gate: a corpus that is half on-topic and half a neighbouring
        # literature must not put the neighbour in the map.
        try:
            from eonrise.engine import run_search as _run
            from eonrise.models import SearchSettings as _Policy, Paper as _Paper

            class _Mixed:
                name = "benchmark-mixed"

                def search(self, query, limit=20):
                    on = [_Paper(f"on{i}", f"Saturation criteria for iterative exploration, study {i}",
                                 keywords=["saturation"]) for i in range(10)]
                    off = [_Paper(f"off{i}", f"Protein structure and dynamics under iterative refinement, part {i}",
                                  keywords=["protein structure and dynamics"]) for i in range(12)]
                    return on + off

            drift = _run("when should an iterative search or exploration process stop using saturation",
                         [_Mixed()], _Policy(name="benchmark", max_nodes=60, max_depth=3, max_rounds=2))
            labels = " ".join(c["label"] for c in drift["concepts"]) + " " +                      " ".join(t["text"] for t in drift["terms"])
            ok = "protein" not in labels and bool(drift["terms"])
            gates.append(("drift guard keeps a neighbouring literature out", ok,
                          f"concepts={len(drift['concepts'])} on_topic={drift.get('on_topic_papers')}"))
        except Exception as exc:  # noqa: BLE001
            gates.append(("drift guard keeps a neighbouring literature out", False,
                          f"{type(exc).__name__}: {exc}"))

    print("# Release check report")
    failed = 0
    for name, passed, detail in gates:
        print(f"- [{'PASS' if passed else 'FAIL'}] {name}")
        if not passed:
            failed += 1
            print(f"  detail: {detail[-1500:]}")
    print(f"\n{'CLEAR' if failed == 0 else 'BLOCKED'}: {len(gates) - failed}/{len(gates)} gates passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
