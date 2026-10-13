"""How much of the reachable literature a run has seen, from its own capture histories.

Every paper records the queries that found it (`found_by`). Ecology counts unseen species
the same way from sampling plots: a paper found by one query only is a singleton, by two a
doubleton, and many singletons mean much is still unseen. Pass-2 evidence for the port:
Chao's estimator is already used as a stopping rule for technology-assisted review, and
STADS treats software testing as species discovery.

Incidence-based, with each distinct query as one sampling unit:

- Chao2, bias-corrected (Chao 1987):  S = S_obs + (T-1)/T * Q1(Q1-1) / (2(Q2+1))
- sample coverage (Chao & Jost 2012):  C = 1 - Q1/U * (T-1)Q1 / ((T-1)Q1 + 2Q2)

Known limit, stated by the same literature: under heterogeneous findability Chao2 is a lower
bound, and queries chosen from what was already found are not random samples. The number is
"of what these queries can reach", never "of the field".
"""
from __future__ import annotations

from .models import Paper

MIN_PAPERS = 5  # below this an estimate is noise, and the brief says nothing
# The share is an upper bound on recall (it overstated recall in 90% of simulated stops).
# Below this the brief warns; in `unseen_benchmark` the warning was right 17 of 19 times.
WARN_BELOW = 0.70


def estimate_coverage(papers: list[Paper], ids: set[str] | None = None) -> dict | None:
    pool = [p for p in papers if ids is None or p.paper_id in ids]
    counts = [len(set(p.found_by)) for p in pool if p.found_by]
    queries = {q for p in pool for q in p.found_by}
    t, observed, incidences = len(queries), len(counts), sum(counts)
    if observed < MIN_PAPERS or t < 2:
        return None
    q1, q2 = counts.count(1), counts.count(2)
    total = observed + (t - 1) / t * q1 * (q1 - 1) / (2 * (q2 + 1))
    covered = 1.0 if not q1 else 1 - q1 / incidences * ((t - 1) * q1 / ((t - 1) * q1 + 2 * q2))
    return {"observed": observed, "estimated_total": round(total, 1),
            "found_share": round(observed / total, 3), "sample_coverage": round(max(0.0, covered), 3),
            "singletons": q1, "doubletons": q2, "queries": t}
