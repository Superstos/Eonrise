# Eonrise v0.5

Eonrise turns one question into a grounded research map: mechanisms, measurements, failure modes, methods, neighboring fields, evidence, gaps, and the next searches.

## Two modes

### Live mode

For a normal computer with internet. Crossref works without signup; OpenAlex adds richer topic nesting with a free key.

```bash
python -m ontology_router "your question" --mode live --email you@example.com --out output
```

### Assistant mode

For ChatGPT, restricted machines, reproducible runs, or saved research. It uses a JSON evidence bundle and makes no network request.

```bash
python -m ontology_router "your question" --mode assistant --bundle evidence.json --out output
```

The report exposes remaining gaps and recommended searches. An assistant can search those, append evidence to the bundle, and rerun until the stopping checks pass.

## Output

- `report.md` — compact human-facing brief
- `internal_report.md` — full research trace
- `research_map.json` — full evidence and run history
- `graph.json` — nodes and typed edges for a UI

## Stop rule

Eonrise stops only when it has enough papers, all five angles are grounded, several search paths contributed evidence, top terms are mostly supported, and another round adds almost nothing.

## Tests

```bash
python -m unittest discover -s tests -v
```

Standard library only.

## Operating contract

For broad work, Eonrise is the default depth layer. Research stays deep internally while the user-facing answer stays minimal. See `docs/OPERATING_CONTRACT.md`.
