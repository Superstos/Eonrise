from __future__ import annotations

"""Gauntlet: builder -> redteam loop runner (stdlib only).

Usage:
  python -m gauntlet.run            # full loop: unit tests + redteam + live smoke note
  python -m gauntlet.run --quick    # unit tests only
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
        from ontology_router.engine import run_agent
        from ontology_router.models import AgentPolicy
        from ontology_router.providers import EvidenceBundleProvider
        from ontology_router.report import write_outputs

        try:
            with tempfile.TemporaryDirectory() as tmp:
                result = run_agent(
                    "how does spaced repetition improve memory retention",
                    [EvidenceBundleProvider("tests/fixtures/papers.json")],
                    AgentPolicy(name="gauntlet", max_nodes=50, max_depth=3, max_rounds=3),
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
        except Exception as exc:  # noqa: BLE001 - gauntlet must report, not crash
            gates.append(("assistant smoke emits 4 artifacts + root", False, f"{type(exc).__name__}: {exc}"))

    print("# Gauntlet report")
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
