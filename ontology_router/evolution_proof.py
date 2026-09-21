from __future__ import annotations

import json
import shutil
import statistics
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .engine import run_agent
from .equivalence import ConceptEquivalenceGraph, ConceptEquivalenceStore
from .equivalence_benchmark import BenchmarkProvider
from .models import AgentPolicy, Paper
from .scheduling import ProviderStates


@dataclass
class ReplayCase:
    question: str
    papers: list[Paper]
    relevant_ids: set[str]


def _run_case(case: ReplayCase, graph: ConceptEquivalenceGraph) -> tuple[float, list[str]]:
    result = run_agent(
        case.question,
        [BenchmarkProvider(case.papers)],
        AgentPolicy(name="evolution-proof", max_nodes=30, max_depth=1, max_rounds=1,
                    support_threshold=1),
        results_per_query=20,
        background=set(),
        states=ProviderStates(),
        equivalence=graph,
        query_expansion_slots=1,
    )
    found = {row["paper_id"] for row in result.get("papers", [])[:20]}
    recall = len(found & case.relevant_ids) / max(1, len(case.relevant_ids))
    queries = result.get("rounds", [{}])[0].get("queries", []) if result.get("rounds") else []
    return recall, list(queries)


def score_graph(graph: ConceptEquivalenceGraph, cases: Iterable[ReplayCase]) -> float:
    scores = [_run_case(case, graph)[0] for case in cases]
    return float(statistics.mean(scores)) if scores else 0.0


class VersionedEquivalenceState:
    """Tiny versioned state store used only by the evolution proof."""

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

    def promote(self, candidate: Path) -> tuple[int, Path]:
        version, _ = self.active()
        new_version = version + 1
        target = self.versions / f"equivalence_v{new_version}.jsonl"
        shutil.copyfile(candidate, target)
        self._set_active(new_version, target)
        return new_version, target


def evolve_once(seed_store: str | Path, cases: list[ReplayCase], state_root: str | Path) -> dict:
    """Ablate one active equivalence at a time and keep only a measured win."""

    state = VersionedEquivalenceState(state_root, seed_store)
    parent_version, parent_path = state.active()
    parent_graph = ConceptEquivalenceStore(parent_path).load()
    parent_score = score_graph(parent_graph, cases)

    candidates = []
    for index, edge in enumerate(parent_graph.edges(), 1):
        if edge.get("relation") != "equivalent":
            continue
        if not parent_graph.aliases_for(edge["a"]):
            continue
        candidate_path = state.candidate_revoking(edge["a"], edge["b"], index)
        candidate_graph = ConceptEquivalenceStore(candidate_path).load()
        candidate_score = score_graph(candidate_graph, cases)
        candidates.append({
            "edge": [edge["a"], edge["b"]],
            "score": candidate_score,
            "path": str(candidate_path),
        })

    best = max(candidates, key=lambda row: row["score"], default=None)
    accepted = bool(best and best["score"] > parent_score + 1e-9)
    active_version = parent_version
    active_path = parent_path
    if accepted:
        active_version, active_path = state.promote(Path(best["path"]))

    after_graph = ConceptEquivalenceStore(active_path).load()
    case_details = []
    for case in cases:
        recall, queries = _run_case(case, after_graph)
        case_details.append({"question": case.question, "recall": recall, "queries": queries})

    return {
        "parent_version": parent_version,
        "parent_score": round(parent_score, 4),
        "candidates": [
            {"edge": row["edge"], "score": round(row["score"], 4)}
            for row in candidates
        ],
        "accepted": accepted,
        "accepted_edge_revocation": best["edge"] if accepted else None,
        "active_version": active_version,
        "active_score": round(score_graph(after_graph, cases), 4),
        "cases": case_details,
    }


def _evidence(paper_id: str, field: str) -> dict:
    return {
        "paper_id": paper_id,
        "paper_key": f"doi:10.9/{paper_id}",
        "kind": "explicit_alias",
        "field": field,
        "example": "explicit terminology evidence",
        "query": "concept drift",
    }


def _paper(paper_id: str, title: str, abstract: str, keywords: list[str],
           fields: list[str]) -> Paper:
    return Paper(
        paper_id=paper_id,
        title=title,
        abstract=abstract,
        url=f"https://example.org/{paper_id}",
        doi=f"10.9/{paper_id}",
        year=2026,
        cited_by_count=1,
        provider="evolution-proof",
        keywords=keywords,
        fields=fields,
        topic_path=[],
        venue="",
        found_by=[],
    )


def proof_fixture() -> dict:
    """Controlled proof: a stronger bad alias blocks a weaker useful alias."""

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed = root / "seed.jsonl"
        store = ConceptEquivalenceStore(seed)

        # Useful edge: two independent supports.
        store.append_observation(
            "concept drift", "distribution shift", "equivalent",
            [_evidence("good-1", "Machine Learning")]
        )
        store.append_observation(
            "concept drift", "distribution shift", "equivalent",
            [_evidence("good-2", "Statistics")]
        )

        # Bad edge: three supports, so current Eonrise prefers it for the single
        # expansion slot. This models a confidently learned but harmful alias.
        for i, field in enumerate(("Physics", "Finance", "Cognitive Science"), 1):
            store.append_observation(
                "concept drift", "drift diffusion", "equivalent",
                [_evidence(f"bad-{i}", field)]
            )

        papers = []
        relevant = set()
        for i in range(1, 4):
            pid = f"base-{i}"
            relevant.add(pid)
            papers.append(_paper(
                pid,
                f"Concept drift in adaptive models {i}",
                "Concept drift changes model performance over time.",
                ["concept drift", "machine learning"],
                ["Machine Learning"],
            ))
        for i in range(1, 7):
            pid = f"alternate-{i}"
            relevant.add(pid)
            papers.append(_paper(
                pid,
                f"Distribution shift in deployed models {i}",
                "Distribution shift changes model performance after deployment.",
                ["distribution shift", "concept drift", "machine learning"],
                ["Machine Learning"],
            ))
        for i in range(1, 7):
            papers.append(_paper(
                f"decoy-{i}",
                f"Drift diffusion process {i}",
                "Drift diffusion models describe noisy evidence accumulation.",
                ["drift diffusion"],
                ["Cognitive Science"],
            ))

        case = ReplayCase("concept drift", papers, relevant)
        parent_graph = store.load()
        before_recall, before_queries = _run_case(case, parent_graph)
        state_root = root / "state"
        result = evolve_once(seed, [case], state_root)
        result["before_case"] = {
            "recall": round(before_recall, 4),
            "queries": before_queries,
        }
        result["second_pass"] = evolve_once(seed, [case], state_root)
        return result


def main() -> None:
    print(json.dumps(proof_fixture(), indent=2))


if __name__ == "__main__":
    main()
