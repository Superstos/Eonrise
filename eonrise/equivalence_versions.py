from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Callable

from .equivalence import ConceptEquivalenceGraph, ConceptEquivalenceStore


ScoreFn = Callable[[ConceptEquivalenceGraph], float]


class VersionedEquivalenceState:
    """Version and promote Eonrise's learned equivalence state."""

    def __init__(self, root: str | Path, seed_store: str | Path) -> None:
        self.root = Path(root)
        self.versions = self.root / "versions"
        self.candidates = self.root / "candidates"
        self.active_file = self.root / "active.json"
        self.versions.mkdir(parents=True, exist_ok=True)
        self.candidates.mkdir(parents=True, exist_ok=True)

        if not self.active_file.exists():
            first = self.versions / "equivalence_v0.jsonl"
            shutil.copyfile(seed_store, first)
            self._set_active(0, first)

    def _set_active(self, version: int, path: Path) -> None:
        self.active_file.write_text(
            json.dumps({"version": version, "path": str(path)}, indent=2),
            encoding="utf-8",
        )

    def active(self) -> tuple[int, Path]:
        raw = json.loads(self.active_file.read_text(encoding="utf-8"))
        return int(raw["version"]), Path(raw["path"])

    def candidate_revoking(self, left: str, right: str, index: int) -> Path:
        _, active = self.active()
        path = self.candidates / f"candidate_{index}.jsonl"
        shutil.copyfile(active, path)
        ConceptEquivalenceStore(path).revoke(left, right, "evolution candidate")
        return path

    def promote(self, candidate: str | Path) -> tuple[int, Path]:
        version, _ = self.active()
        new_version = version + 1
        target = self.versions / f"equivalence_v{new_version}.jsonl"
        shutil.copyfile(candidate, target)
        self._set_active(new_version, target)
        return new_version, target


def evolve_equivalence_state(
    seed_store: str | Path,
    state_root: str | Path,
    score: ScoreFn,
) -> dict:
    """Try reversible edge removals and promote only a measured improvement.

    The caller owns the replay/evaluation set. This function only handles
    versioning, candidate generation, comparison, and promotion.
    """

    return _EquivalenceEvolution(VersionedEquivalenceState(state_root, seed_store), score).run()


class _EquivalenceEvolution:
    def __init__(self, state, score):
        self.state = state
        self.score = score
        self.parent_version, self.parent_path = state.active()
        self.parent_graph = ConceptEquivalenceStore(self.parent_path).load()
        self.parent_score = float(score(self.parent_graph))

    def _candidates(self):
        candidates = []
        for index, edge in enumerate(self.parent_graph.edges(), 1):
            if edge.get("relation") != "equivalent":
                continue
            if not self.parent_graph.aliases_for(edge["a"]):
                continue
            candidates.append(self._candidate(edge, index))
        return candidates

    def _candidate(self, edge, index):
        path = self.state.candidate_revoking(edge["a"], edge["b"], index)
        graph = ConceptEquivalenceStore(path).load()
        return {"edge": [edge["a"], edge["b"]],
                "score": float(self.score(graph)), "path": str(path)}

    def run(self):
        candidates = self._candidates()
        best = max(candidates, key=lambda row: row["score"], default=None)
        accepted = bool(best and best["score"] > self.parent_score)
        active_version, active_path = self.parent_version, self.parent_path
        if accepted and best is not None:
            active_version, active_path = self.state.promote(best["path"])
        active_graph = ConceptEquivalenceStore(active_path).load()
        active_score = float(self.score(active_graph))
        result = self._result(candidates)
        result.update(accepted=accepted, accepted_edge_revocation=_accepted_edge(best, accepted),
                      active_version=active_version, active_score=active_score, active_path=str(active_path))
        return result

    def _result(self, candidates):
        return {"parent_version": self.parent_version, "parent_score": self.parent_score,
                "candidates": [{"edge": row["edge"], "score": row["score"]} for row in candidates]}


def _accepted_edge(best, accepted):
    return best["edge"] if accepted and best else None
