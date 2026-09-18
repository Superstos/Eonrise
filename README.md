# Eonrise

Built only on the Python standard library.

Eonrise maps where fields intersect, finding concepts that are fundamentally similar even when different disciplines use different names for them.

It maps:

- mechanisms (how something works)
- measurements (how it is judged)
- failure modes (how it breaks)
- methods (how it was tested)
- neighboring fields (where else the idea shows up)

## Why it exists

Most search tools stay inside one field's words. Eonrise starts from one question, builds a map of nearby ideas across fields, fills the gaps it can, and remembers wording it has seen before. The point is a clearer map, not a longer list of papers.

## Installation

Requires Python `>=3.11`.

From a repository checkout:

```bash
pip install .
eonrise --help
```

A PyPI release is planned; until then, install from source.

## Fastest working example

This offline example uses the bundled fixture and writes no local memory, corpus, or equivalence state:

```bash
eonrise "how does spaced repetition improve memory retention" \
  --mode assistant \
  --bundle tests/fixtures/papers.json \
  --out output \
  --no-memory --no-corpus --no-equivalence \
  --max-rounds 2 --results 10
```

## Example output

`report.md` leads with the grounded map:

```text
Status: usable — 4/5 relations grounded after gap repair
Evidence: 14 papers kept of 14 retrieved, 38 concepts

Mechanism: retrieval practice, encoding dynamics, attention mediation
Measurement: recall accuracy, retention rate, retention robustness
Failure Mode: accuracy degradation
Method: evaluation protocol, randomized trial, replication baseline
Neighbor Field: cognitive psychology, testing effect, learning science
```

The run also writes `internal_report.md`, `research_map.json`, and `graph.json`.

## How it works

One question becomes one shared topic name for the whole run. The code calls it `canonical_root` (see `ontology_router/evidence.py`).

A small policy object sets the budget: how many concepts, how deep to go, how many rounds, and how much each direction counts. The run stops when the budget runs out or when new rounds stop adding evidence (`ontology_router/engine.py`).

- `up` = the bigger picture: parent theories and fields.
- `down` = the details: mechanism, measurement, failure mode, method.
- `sideways` = the same idea elsewhere: parallel names, analogies, neighbor fields.

Three checks stop a weak run from looking better than it is:

- **Topical gate** (`topical_papers` in `ontology_router/evidence.py`): every paper must still share words with the original question. Off-topic papers cannot support a finding and do not count as progress.
- **Relation guard**: a title containing the word "failure" is not a failure mode. Detail-level relations need a paper that is actually on topic.
- **Gap repair**: each round spends part of its 5 searches on the missing pieces instead of repeating searches that already worked.

Run status is `ready`, `usable`, `partial`, or `failed`. `docs/SPEC.md` keeps the full history of what was tried, measured, kept, or rejected.

## Providers

Four keyless sources run by default; two more join when a free key is present. Measured on one query, 20 results each:

| Source | Key | Abstracts | Keywords | Subjects |
|---|---|---|---|---|
| Europe PMC | none | 20/20 | 18/20 | 7/20 MeSH |
| DOAJ | none | 8/8 | 7/8 | 8/8 LCC |
| Crossref | none | 16% | 0% | 0% |
| OpenAlex | none, but see below | good | good | good |
| Semantic Scholar | free key | — | — | fields of study |
| CORE | free key | 10/10 | — | — |

OpenAlex anonymous use is credit-limited; a free key raises the budget. Semantic Scholar and CORE stay out until `--s2-key` / `S2_API_KEY` or `--core-key` / `CORE_API_KEY` is supplied. Papers are merged by DOI, so a thin record can later inherit an abstract from a richer provider.

Sources are not equal, so each round asks first the source most likely to have what is still missing. Failure modes are read from abstract sentences, so an abstract-rich source goes first; neighbor fields come from subject labels, so a subject-rich source goes first (`ontology_router/scheduling.py`). Ties go to the cheaper source. A long rate-limit pause is remembered across runs in `~/.cache/eonrise/providers.json`, so the next run does not pay to learn the same limit twice.

## Local paper store

Every normal run can read and grow a local paper store at `~/.cache/eonrise/corpus.jsonl`. A stored paper costs no API credit, and richer metadata received later is added to the earlier record. The store pays off three ways: cheaper runs, richer records over time, and literatures that accumulate across runs instead of dying with one.

```bash
--corpus PATH
--no-corpus
```

## Concept equivalence

Eonrise can also remember careful cross-field wording links in `~/.cache/eonrise/equivalence.jsonl`. Phrases such as "also known as" may create an `equivalent` link, but only after two separate on-topic papers back it. Words that merely appear together are stored as `closely_related` and never change a search.

A strong `equivalent` link may add one extra search to a round, inside the usual limit of 5 searches per round. The original search always runs too, and ranking, concept identity, and the topical gate stay unchanged.

```bash
--equivalence PATH
--no-equivalence
--query-expansion-slots N
```

Measure that integration with:

```bash
python -m ontology_router.equivalence_benchmark
```

## Known limitations

- The topical gate matches words, not meaning. A paper sharing two ordinary root words can slip through.
- A question phrased in everyday words, with no technical anchor, returns noise. Ask in a field's vocabulary.
- Concepts are phrases lifted from titles, keywords, and abstracts, so Eonrise names subjects, never techniques. Naming a method would need a model that reads the papers.
- `--semantic` needs an OpenAlex key; without one it falls back to keyword search.
- Measurement numbers in this README come from the runs that produced them. Other fields may differ.

## Development and testing

Supported Python package versions: `>=3.11`. CI also probes source compatibility on Python 3.8–3.10 intentionally.

```bash
python -m unittest discover -s tests -v
python -m gauntlet.run --quick
python -m gauntlet.run
```

Verify the distributable package:

```bash
python -m pip install build
python -m build
```

Experimental ideas should include measurement. Rejected experiments should be recorded in `docs/SPEC.md`, not hidden.

## License and data notice

Eonrise code is MIT-licensed; see `LICENSE`.

That license covers Eonrise software. It does not relicense scholarly metadata, abstracts, API responses, or other outside scholarly material. Those stay under their original provider and source terms.

Live mode contacts outside scholarly APIs and may save copies of what they return on your machine. You are responsible for following each provider's terms, especially if you share downloaded papers or abstracts with others.
