# Eonrise

Eonrise maps where fields intersect. It searches scholarly sources and organizes the evidence into mechanisms, measurements, failure modes, methods, and neighboring fields.

The goal is a shortcut to ideas: a problem that is new or half solved in your field is often already solved, more maturely, in another one. Results from distant fields are the point, not noise.

It can also learn when different fields use different names for the same or closely related idea, then reuse that vocabulary in later searches.

No third-party Python packages are required at runtime.

## Quick start

Eonrise installs on Python 3.11+.

```bash
pip install .
eonrise "how does spaced repetition improve memory retention" --out output
```

Live mode searches scholarly APIs and can keep a local cache so later runs reuse papers already found.

For a fully offline run:

```bash
eonrise "how does spaced repetition improve memory retention" \
  --mode assistant \
  --bundle tests/fixtures/papers.json \
  --out output \
  --no-memory --no-corpus --no-equivalence \
  --max-rounds 2 --results 10
```

## What you get

A run writes four files:

- `report.md` is the short readable result.
- `research_map.json` contains the full structured map.
- `graph.json` contains nodes and typed edges for other tools or a UI.
- `internal_report.md` shows the concept tree and supporting evidence.

A map can look like this:

```text
Mechanism: retrieval practice, encoding dynamics
Measurement: recall accuracy, retention rate
Failure mode: accuracy degradation
Method: randomized trial, replication baseline
Neighbor field: cognitive psychology, learning science
```

If Eonrise cannot support part of the map with evidence, it leaves that part empty instead of making something up.

## How it works

Eonrise keeps one root question for the whole run. It searches several scholarly sources, rejects papers that drift too far from that question, extracts supported concepts, then uses later searches to repair missing parts of the map.

Normal runs can grow a local paper store at `~/.cache/eonrise/corpus.jsonl`. Later runs search that store before spending API calls, and a paper can gain richer metadata when another source returns a better copy of the same record.

Cross-field terminology lives in `~/.cache/eonrise/equivalence.jsonl`. An `equivalent` link needs support from at least two independent on-topic papers before it can change retrieval. Repeated co-occurrence alone is stored as `closely_related` and does not alter searches.

The detailed traversal rules, benchmarks, rejected experiments, and version history live in [`docs/SPEC.md`](docs/SPEC.md).

## Sources

Eonrise can search:

| Source | Access |
| --- | --- |
| Crossref | keyless |
| OpenAlex | keyless, optional API key |
| Europe PMC | keyless |
| DOAJ | keyless |
| Semantic Scholar | free API key |
| CORE | free API key |

Use `--providers` to choose a subset. API availability and limits belong to the providers and can change independently of Eonrise.

## Current limits

- Topical filtering still depends partly on word overlap, so ambiguous wording can let unrelated papers through.
- Eonrise works from the metadata and abstracts returned by its sources. It does not read full papers.
- Plain everyday questions with no technical vocabulary tend to produce weaker maps.
- Live runs depend on external scholarly APIs. A provider outage can make a run thinner or fail it outright.

Eonrise reports provider failures instead of treating a broken search as evidence that the literature is empty.

## Development

The installable package targets Python 3.11+. CI also runs the source tests on Python 3.8, 3.9, and 3.10 to catch avoidable compatibility breakage.

```bash
python -m unittest discover -s tests -v
python -m benchmarks.run --quick
python -m benchmarks.run
```

Build the package with:

```bash
python -m pip install build
python -m build
```

Contributions should stay small and measurable. See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## License and retrieved data

Eonrise is MIT-licensed. See [`LICENSE`](LICENSE).

The license covers Eonrise itself. Metadata, abstracts, and other material returned by external scholarly sources keep their original licenses and terms. Live mode may save those records locally, so redistribution is subject to the source or provider terms.
