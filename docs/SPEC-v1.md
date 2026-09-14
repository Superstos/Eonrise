# Eonrise v1.1 spec — single root, agent-owned recursion

Locked 2026-09-14. Replaces the 2–4 topic split.

## Rule

One question → **one canonical root topic** (`canonical_root`).
The agent decides how deep and which side, recursively, within its policy budget.

## Agent policy

`AgentPolicy`: `max_nodes` (default 120), `max_depth` (4), `max_rounds` (6),
`up/down/sideways_weight` (0.5 / 1.0 / 1.0), `support_threshold` (2 past round 1),
`decay` (0.6 per level), optional `per_direction_cap` (None = unbounded concepts,
per-round query budget of 5 keeps live APIs usable).

Two agents on the same question diverge by policy alone: one drills down into
mechanisms/implementations, another goes sideways across fields.

## Traversal

- `up` = parent theory / field / domain (from provider field hierarchies).
- `down` = mechanism, measurement, failure mode, method.
- `sideways` = parallel name, analogy, neighbor-field application.
- Frontier sorted by `score × direction_weight × decay^depth`.
- Round 1 seeds from any grounded term; round 2+ needs `support_threshold` papers.
- Guards: visited-ID set (no cycles), depth cap, node budget, no-new-evidence stop.

## Providers / memory

Unchanged interface: Crossref / OpenAlex / evidence-bundle. Results dedupe by
DOI-or-title. `MemoryStore` appends a slim JSONL record per run and recalls by
token overlap so reruns compound.

## Outputs

`research_map.json` now carries `version: 5`, `root_topic`, `policy`, `concepts[]`.
`report.md` / `internal_report.md` show direction groups and the concept tree.
`graph.json` shape unchanged (backward compat).

## Gauntlet gates (must all pass for OSS)

1. `python -m unittest discover -s tests -v` green.
2. `python -m gauntlet.run` CLEAR (6 redteam attacks + artifact smoke).
3. No crash on: vague, single-word, non-English, empty bundle, duplicates, hostile input.
4. Gaps honest when evidence missing; URLs/IDs preserved.

## Rust note

No toolchain on this machine and no proven hot path. `normalize` / `_dedupe_papers` /
n-gram extraction are isolated pure functions — first candidates for a later Rust
extension. No rewrite until profiling says so.
