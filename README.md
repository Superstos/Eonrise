# Eonrise v1.1

One question → one root topic → agent-owned up/down/sideways traversal.

## Use

```bash
# Offline / reproducible (no network)
python -m ontology_router "how does spaced repetition improve memory" --mode assistant --bundle tests/fixtures/papers.json --out output

# Live (Crossref + optional OpenAlex)
python -m ontology_router "your question" --mode live --email you@example.com --out output

# Agent steers depth and direction
python -m ontology_router "memory retention" --mode assistant --bundle tests/fixtures/papers.json --out output \
  --agent-name deep-diver --max-depth 5 --max-nodes 200 --down-weight 2.0 --sideways-weight 0.5
```

## Rule

Single root topic. Each agent carries its own budget (`--max-nodes`, `--max-depth`,
`--up/--down/--sideways-weight`) and recurses until budget, depth, or saturation.
Two agents, same question, different policies → different maps. See `docs/SPEC-v1.md`.

## Output

- `report.md` — compact brief with direction groups
- `internal_report.md` — concept tree + evidence
- `research_map.json` — full evidence, concepts, policy, run history
- `graph.json` — nodes and typed edges for a UI

## Gauntlet

```bash
python -m unittest discover -s tests -v
python -m gauntlet.run
```

Builder → redteam loop: 12 unit tests + 6 offline attacks (vague, single-word,
non-English, empty bundle, duplicates, hostile input) + artifact smoke. All must
pass before OSS release.

Standard library only. MIT.
