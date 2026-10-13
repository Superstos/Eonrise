"""Stop rules against a literature whose size is known.

`python -m benchmarks.coverage_stop_rules`

Each scenario is a population of papers with heterogeneous findability: every query finds
paper i with probability p_i, drawn log-normal, so a few papers turn up everywhere and many
turn up rarely — the shape that makes "no new papers this round" look like saturation too
early. A round is five queries, as in the engine. Every rule may stop from round 2.

Rules compared:
- `saturation` (engine v0.11): stop when a round brings at most 2 new papers.
- `coverage`: stop when Chao-Jost sample coverage reaches 0.90.
- `found_share`: stop when observed / Chao2 reaches 0.80.

Measured 2026-09-29 (40 seeds x 6 scenarios): both estimator rules stop earlier with lower
recall and fail the kill rule, so the engine's check stays. The estimate ships as a warning
only; `warning.precision` is how often it was right when it fired.

Kill rule for replacing the engine's check: over all scenarios the candidate must stop with
true recall >= 0.8 more often than `saturation`, spending at most 1.5x its queries on median.
"""
from __future__ import annotations

import json
import math
import random
import statistics

from eonrise.models import Paper
from eonrise.literature_coverage import WARN_BELOW, estimate_coverage

ROUND = 5
SCENARIOS = [  # (name, population, log-mean findability, log-sd)
    ("small, easy", 40, -2.3, 0.8),
    ("small, hard", 40, -3.4, 1.2),
    ("mid, even", 150, -3.0, 0.6),
    ("mid, skewed", 150, -3.5, 1.4),
    ("large, skewed", 400, -4.2, 1.4),
    ("large, very skewed", 400, -4.8, 1.8),
]
RULES = {
    "saturation": lambda est, new: new <= 2,
    "coverage": lambda est, new: est is not None and est["sample_coverage"] >= 0.90,
    "found_share": lambda est, new: est is not None and est["found_share"] >= 0.80,
}


def simulate(population: int, mu: float, sd: float, seed: int, max_rounds: int = 12) -> dict:
    rng = random.Random(seed)
    p = [min(0.6, math.exp(rng.gauss(mu, sd))) for _ in range(population)]
    found: dict[int, list[str]] = {}
    stops: dict[str, dict] = {}
    for round_number in range(1, max_rounds + 1):
        before = len(found)
        for q in range(ROUND):
            query = f"q{round_number}.{q}"
            for i, pi in enumerate(p):
                if rng.random() < pi:
                    found.setdefault(i, []).append(query)
        new = len(found) - before
        papers = [Paper(str(i), str(i), found_by=qs) for i, qs in found.items()]
        est = estimate_coverage(papers)
        for name, rule in RULES.items():
            if name not in stops and round_number >= 2 and rule(est, new):
                stops[name] = {"round": round_number, "recall": len(found) / population,
                               "claimed": est["found_share"] if est else None}
    for name in RULES:  # a rule that never fired ran to the cap
        stops.setdefault(name, {"round": max_rounds, "recall": len(found) / population, "claimed": None})
    return stops


def main(seeds: int = 40) -> dict:
    report = {"scenarios": [], "totals": {}}
    pooled = {name: [] for name in RULES}
    for name, population, mu, sd in SCENARIOS:
        runs = [simulate(population, mu, sd, seed) for seed in range(seeds)]
        row = {"scenario": name, "population": population}
        for rule in RULES:
            stops = [r[rule] for r in runs]
            pooled[rule].extend(stops)
            row[rule] = {"median_queries": statistics.median(s["round"] * ROUND for s in stops),
                         "median_recall": round(statistics.median(s["recall"] for s in stops), 3),
                         "recall_ge_0.8": round(sum(s["recall"] >= 0.8 for s in stops) / len(stops), 3)}
        report["scenarios"].append(row)
    base = pooled["saturation"]
    for rule, stops in pooled.items():
        claimed = [abs(s["claimed"] - s["recall"]) for s in stops if s["claimed"] is not None]
        report["totals"][rule] = {
            "recall_ge_0.8": round(sum(s["recall"] >= 0.8 for s in stops) / len(stops), 3),
            "median_queries": statistics.median(s["round"] * ROUND for s in stops),
            "median_claim_error": round(statistics.median(claimed), 3) if claimed else None}
    # The shipped use: a warning where the engine's own rule stopped, when the Chao2 share
    # (an upper bound on recall under heterogeneity) is below WARN_BELOW.
    fired = [s for s in base if s["claimed"] is not None and s["claimed"] < WARN_BELOW]
    report["warning"] = {"threshold": WARN_BELOW, "fired": len(fired), "of_stops": len(base),
                         "precision": round(sum(s["recall"] < WARN_BELOW for s in fired) / max(len(fired), 1), 3)}
    for rule in ("coverage", "found_share"):
        t, b = report["totals"][rule], report["totals"]["saturation"]
        t["passes_kill_rule"] = (t["recall_ge_0.8"] > b["recall_ge_0.8"]
                                 and t["median_queries"] <= 1.5 * b["median_queries"])
    return report


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
