"""Offline benchmark for conservative concept equivalence.

The benchmark uses small synthetic literatures, not live providers. Each positive
scenario contains one alternate-vocabulary paper that a literal query cannot match in
its title or abstract, but that still belongs to the question through its keywords and
fields. The comparison is therefore meaningful: expansion can only win by finding a
relevant paper the baseline vocabulary missed.
"""
from __future__ import annotations

import json
import re
import statistics
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from eonrise.engine import run_search
from eonrise.equivalence import ConceptEquivalenceGraph, ConceptEquivalenceStore
from eonrise.evidence import extract_terms, topical_papers
from eonrise.models import SearchSettings, Paper
from eonrise.scheduling import ProviderStates

TOP_K = 20


@dataclass
class Scenario:
    name: str
    question: str
    expected: tuple[str, str]
    papers: list[Paper]
    relevant: list[str]
    forbidden: list[tuple[str, str]]


def _paper(
    paper_id: str,
    title: str,
    abstract: str,
    keywords: list[str],
    fields: list[str],
    topic: str = "",
) -> Paper:
    return Paper(
        paper_id=paper_id,
        title=title,
        abstract=abstract,
        url=f"https://example.org/{paper_id}",
        doi=f"10.9/{paper_id}",
        year=2024,
        cited_by_count=5,
        provider="benchmark",
        keywords=list(keywords),
        fields=list(fields),
        topic_path=[topic] if topic else [],
        venue="",
        found_by=[],
    )


@dataclass
class Vocabulary:
    """Two names for one concept, each from its own field."""

    name: str
    question: str
    left: str
    right: str
    left_field: str
    right_field: str
    context: str
    anchor: str
    right_text: str | None = None


def _true_scenario(v: Vocabulary) -> Scenario:
    """Build one alternate-vocabulary literature with explicit alias evidence."""
    name, left, right, context, anchor = v.name, v.left, v.right, v.context, v.anchor
    left_field, right_field, right_text = v.left_field, v.right_field, v.right_text
    papers = [
        _paper(
            f"{name}-explicit-{index}",
            f"{left.title()} across {left_field} studies {index}",
            f"We study {left} in {context}. In this literature {right}, also known as {left}, "
            f"is measured through {context}.",
            [left, right, context, anchor],
            [left_field, right_field],
            context,
        )
        for index in range(1, 4)
    ]
    papers.extend([
        _paper(
            f"{name}-left-{index}",
            f"{left.title()} and {context} {index}",
            f"This paper examines {left} and its effect on {context}.",
            [left, context, anchor],
            [left_field],
            context,
        )
        for index in range(1, 4)
    ])
    papers.extend([
        _paper(
            f"{name}-right-{index}",
            f"{(right_text or right).title()} and {context} {index}",
            f"This paper examines {right_text or right} and its effect on {context}.",
            [right, context, anchor],
            [right_field],
            context,
        )
        for index in range(1, 4)
    ])
    papers.append(_paper(
        f"{name}-decoy",
        f"{right.title()} in bridge rehabilitation",
        f"This unrelated engineering report mentions {right} while discussing bridge work.",
        ["bridge rehabilitation"],
        ["Civil Engineering"],
        "Bridges",
    ))
    relevant = [paper.paper_id for paper in papers if paper.paper_id != f"{name}-decoy"]
    return Scenario(name, v.question, (left, right), papers, relevant, [])


def scenarios() -> list[Scenario]:
    true = [
        _true_scenario(Vocabulary(
            "drift",
            "how does concept drift affect machine learning models",
            "concept drift",
            "distribution shift",
            "Machine Learning",
            "Statistics",
            "model performance",
            "machine learning",
        )),
        _true_scenario(Vocabulary(
            "nonstationarity",
            "how does non-stationarity affect forecasting models",
            "non-stationarity",
            "regime change",
            "Time Series Analysis",
            "Econometrics",
            "forecast accuracy",
            "forecasting models",
        )),
        _true_scenario(Vocabulary(
            "feedback",
            "how does a feedback loop stabilize a control system",
            "feedback loop",
            "closed-loop control",
            "Control Engineering",
            "Robotics",
            "system stability",
            "feedback control",
            "closed loop regulation",
        )),
        _true_scenario(Vocabulary(
            "fault",
            "how does fault tolerance shape distributed system design",
            "fault tolerance",
            "resilience",
            "Distributed Systems",
            "Software Engineering",
            "system design",
            "distributed design",
        )),
    ]
    negative_papers = [
        _paper(
            f"negative-{index}",
            f"Robustness and reliability in system evaluation {index}",
            "This paper compares robustness with reliability without calling them the same idea.",
            ["robustness", "reliability", "system evaluation"],
            ["Systems Engineering"],
            "system evaluation",
        )
        for index in range(1, 4)
    ]
    negative_papers.extend([
        _paper(
            "negative-cache-1",
            "Caching and memoization in request handling",
            "This paper compares caching with memoization without calling them the same idea.",
            ["caching", "memoization", "request handling"],
            ["Computer Systems"],
            "request handling",
        ),
        _paper(
            "negative-cache-2",
            "Memoization and caching trade-offs",
            "A second paper compares memoization with caching without calling them the same idea.",
            ["caching", "memoization", "request handling"],
            ["Computer Systems"],
            "request handling",
        ),
    ])
    control = Scenario(
        "non-equivalent",
        "how do robustness and reliability shape system evaluation",
        ("robustness", "reliability"),
        negative_papers,
        [paper.paper_id for paper in negative_papers],
        [
            ("robustness", "reliability"),
            ("precision", "accuracy"),
            ("correlation", "causation"),
            ("caching", "memoization"),
            ("robust control", "reliability analysis"),
        ],
    )
    return [*true, control]


class BenchmarkProvider:
    """Title-and-abstract search, so metadata can establish topicality separately."""

    name = "benchmark"

    def __init__(self, papers: list[Paper]) -> None:
        self._papers = list(papers)
        self.queries: list[str] = []

    def search(self, query: str, limit: int = 20) -> list[Paper]:
        self.queries.append(query)
        wanted = {token for token in re.findall(r"[a-z0-9]+", query.lower()) if len(token) > 2}
        if not wanted:
            return []
        ranked: list[tuple[float, Paper]] = []
        for paper in self._papers:
            text = {token for token in re.findall(r"[a-z0-9]+", f"{paper.title} {paper.abstract}".lower())
                    if len(token) > 2}
            hits = len(wanted & text)
            if hits < min(2, len(wanted)):
                continue
            clone = Paper.from_dict(paper.to_dict())
            clone.found_by = list(dict.fromkeys([*clone.found_by, query]))
            ranked.append((hits / len(wanted), clone))
        ranked.sort(key=lambda row: row[0], reverse=True)
        return [paper for _, paper in ranked[:limit]]


def _top_ids(result: dict, limit: int = TOP_K) -> list[str]:
    return [paper["paper_id"] for paper in result.get("papers", [])[:limit]]


def _precision(question: str, result: dict) -> float:
    rows = result.get("papers", [])[:TOP_K]
    if not rows:
        return 0.0
    papers = [Paper.from_dict(row) for row in rows]
    return len(topical_papers(question, papers)) / len(rows)


def _run(question: str, papers: list[Paper], graph: ConceptEquivalenceGraph, slots: int) -> dict:
    return run_search(
        question,
        [BenchmarkProvider(papers)],
        SearchSettings(name="benchmark", max_nodes=30, max_depth=1, max_rounds=1, support_threshold=1),
        results_per_query=TOP_K,
        background=set(),
        states=ProviderStates(),
        equivalence=graph,
        query_expansion_slots=slots,
    )


def _ger(ids: set[str], relevant: set[str]) -> float:
    return len(ids & relevant) / len(relevant)


def _first_queries(result: dict) -> list[str]:
    return result["rounds"][0]["queries"] if result.get("rounds") else []


def _learned_graph(scenario: Scenario, tmp: str):
    store = ConceptEquivalenceStore(Path(tmp) / f"{scenario.name}.jsonl")
    on_topic = topical_papers(scenario.question, scenario.papers)
    terms = extract_terms(scenario.question, scenario.papers, on_topic or None)
    learned = store.observe_run(scenario.question, terms, scenario.papers, on_topic)
    return learned, store.load()


def _aliased(graph, pair) -> bool:
    return bool(graph.aliases_for(pair[0])) or bool(graph.aliases_for(pair[1]))


def _score_scenario(scenario: Scenario, tmp: str) -> dict:
    learned, graph = _learned_graph(scenario, tmp)
    baseline = _run(scenario.question, scenario.papers, ConceptEquivalenceGraph(), 0)
    expanded = _run(scenario.question, scenario.papers, graph, 1)
    baseline_ids, expanded_ids = set(_top_ids(baseline)), set(_top_ids(expanded))
    relevant = set(scenario.relevant)
    baseline_ger, expanded_ger = _ger(baseline_ids, relevant), _ger(expanded_ids, relevant)
    baseline_precision = _precision(scenario.question, baseline)
    expanded_precision = _precision(scenario.question, expanded)
    false_pairs = [pair for pair in scenario.forbidden if _aliased(graph, pair)]
    return {
        "name": scenario.name,
        "expected": list(scenario.expected),
        "expected_discovered": _aliased(graph, scenario.expected),
        "false_pairs": [list(pair) for pair in false_pairs],
        "learned_edges": len(learned),
        "baseline_ger20": round(baseline_ger, 4),
        "expanded_ger20": round(expanded_ger, 4),
        "retrieval_gain": round(expanded_ger - baseline_ger, 4),
        "baseline_precision": round(baseline_precision, 4),
        "expanded_precision": round(expanded_precision, 4),
        "precision_loss": round(baseline_precision - expanded_precision, 4),
        "expansion_only_relevant": sorted(expanded_ids & relevant - baseline_ids),
        "baseline_queries": _first_queries(baseline),
        "expanded_queries": _first_queries(expanded),
        "expanded_query_count": len(expanded.get("query_expansion", {}).get("expanded_queries", [])),
    }


def _summary(scenario_results: list[dict]) -> dict:
    positives = [row for row in scenario_results if row["name"] != "non-equivalent"]
    median_gain = float(statistics.median([row["retrieval_gain"] for row in positives]))
    median_loss = float(statistics.median([row["precision_loss"] for row in positives]))
    false_rate = sum(len(row["false_pairs"]) for row in scenario_results) / max(
        1, sum(len(scenario.forbidden) for scenario in scenarios())
    )
    passed = (
        all(row["expected_discovered"] for row in positives)
        and median_gain > 0
        and false_rate == 0
        and (median_gain - median_loss) > 0
    )
    return {
        "top_k": TOP_K,
        "true_equivalences_discovered": sum(1 for row in positives if row["expected_discovered"]),
        "true_equivalences": len(positives),
        "false_equivalence_rate": round(false_rate, 4),
        "median_retrieval_gain": round(median_gain, 4),
        "median_precision_loss": round(median_loss, 4),
        "net_median_gain": round(median_gain - median_loss, 4),
        "passed_kill_rule": passed,
        "scenarios": scenario_results,
    }


def run_benchmark() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        return _summary([_score_scenario(scenario, tmp) for scenario in scenarios()])


def main() -> None:
    print(json.dumps(run_benchmark(), indent=2))


if __name__ == "__main__":
    main()
