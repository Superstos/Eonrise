# Eonrise

One question → one root topic → agent-owned up/down/sideways traversal.

## Use

```bash
# Offline / reproducible (no network)
python -m ontology_router "how does spaced repetition improve memory" --mode assistant --bundle tests/fixtures/papers.json --out output

# Live (Crossref + OpenAlex; no API key needed)
python -m ontology_router "your question" --mode live --email you@example.com --out output

# Agent steers depth and direction
python -m ontology_router "memory retention" --mode assistant --bundle tests/fixtures/papers.json --out output \
  --agent-name deep-diver --max-depth 5 --max-nodes 200 --down-weight 2.0 --sideways-weight 0.5
```

## Rule

Single root topic. Each agent carries its own budget (`--max-nodes`, `--max-depth`,
`--up/--down/--sideways-weight`) and recurses until budget, depth, or saturation.
Two agents, same question, different policies → different maps. See `docs/SPEC.md`.

## Providers

Four keyless sources run by default; two more join when a free key is present. Measured on
one query, 20 results each:

| Source | Key | Abstracts | Keywords | Subjects |
|---|---|---|---|---|
| Europe PMC | none | 20/20 | 18/20 | 7/20 MeSH |
| DOAJ | none | 8/8 | 7/8 | 8/8 LCC |
| Crossref | none | 16% | 0% | 0% |
| OpenAlex | none, but see below | good | good | good |
| Semantic Scholar | free key | — | — | fields of study |
| CORE | free key | 10/10 | — | — |

OpenAlex now charges credits: anonymous is 1,000 credits a day and a search costs 10, so
roughly 100 searches — one Eonrise run spends about 16. A free key raises the budget 10×
(openalex.org/settings/api). Semantic Scholar and CORE answer `429` without a key, so they
stay out of the default set until `--s2-key` / `S2_API_KEY` or `--core-key` / `CORE_API_KEY`
is supplied. `--providers crossref,europepmc` picks any subset; `--crossref-only` still
means Crossref alone, which carries no subjects and few abstracts.

Papers are merged across sources by DOI, so a Crossref record with no abstract inherits
one from Europe PMC when both return it.

## Source scheduling

Sources are not interchangeable, and a rate limit outlives the process.

- The round asks the source that carries what it is missing: `failure_mode` is read out of
  abstract sentences, so Europe PMC goes first; `neighbor_field` is read off subject labels,
  so DOAJ does. Crossref is never asked first while a richer source is available.
- A `429` carrying a long `Retry-After` blocks that source in `~/.cache/eonrise/providers.json`
  until its window passes, so tomorrow's run skips it instead of spending a call to learn
  the same thing.
- A tie goes to the cheaper source: DOAJ before OpenAlex, which charges 10 credits a search.

## The paper store

Every run writes the papers it kept to `~/.cache/eonrise/corpus.jsonl` and every later run
searches that store before it touches the network. Three things compound off it:

- **Budget** — a paper already held costs no API credit, and OpenAlex now charges them.
- **Evidence** — a thin Crossref record is enriched the day Europe PMC returns the same DOI
  with an abstract, and the enrichment is kept.
- **Cross-literature leads** — Swanson-style discovery needs two large literatures gathered
  separately. One run cannot build them; a year of runs can.

`--corpus PATH` picks a different store, `--no-corpus` turns it off.

## Concept equivalence

Eonrise also keeps learned cross-field terminology in `~/.cache/eonrise/equivalence.jsonl`.
Explicit statements such as “also known as” can create an `equivalent` edge after two
independent on-topic papers support it; repeated co-occurrence stays `closely_related`
and never changes a search. A confident equivalent edge may supply one alternate query
inside the normal query budget. The original query is always searched, and ranking,
concept identity, and the topical gate are unchanged.

`--equivalence PATH` picks a different store, `--no-equivalence` turns it off, and
`--query-expansion-slots N` controls alternate-query use. Measure the integration with:

```bash
python -m ontology_router.equivalence_benchmark
```

## What a brief contains

`report.md` leads with the grounded map (mechanism / measurement / failure mode / method /
neighbour field), then **Stated limitations** — each one quoted from the sentence in the
abstract that made the claim, so a noisy phrase can be judged against its source.

## Drift guards

Sub-queries drift: a run about map quality ends up in gene-ontology literature, and every
round still returns new papers, so saturation never fires. Three guards:

- **Topical gate** — a retrieved paper must still share tokens with the root question.
  Off-topic papers never ground a term and never count toward saturation.
- **Relation guard** — `measurement` / `failure_mode` / `method` need a supporting on-topic
  paper, and a bare gap cue (`failure mode`) cannot become the finding.
- **Gap repair** — 2 of the 5 per-round query slots go to the recommended gap queries, which
  were previously printed and never searched. The cue wording rotates each repair round.
- **Label hygiene** — discipline names (`computer science`), sentence fragments
  (`relation between`), filler (`problem very terms`) and paraphrase pairs
  (`search algorithm` / `search algorithms`) never become concepts.
- **Background penalty** — a label that ranked high under three or more unrelated past
  questions scores half. Run memory makes reruns compound.
- **Limitations** — read from abstract sentences that state one, not from keywords.
- **Provider health** — a `429` carrying a long `Retry-After` is a quota window, not a
  burst limit, so that host is dropped for the rest of the run instead of being asked 16
  more times. If a provider answered nothing, the brief says **Degraded** at the top:
  losing OpenAlex means no keywords, no topic hierarchy and few abstracts, and a map read
  without knowing that looks like a thin literature rather than a thin run.

## Status

`ready` (all checks) > `usable` (4-5 of 5 relations grounded, gaps repaired where possible)
> `partial` > `failed`.

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

Builder → redteam loop: the unit suite + 6 offline attacks (vague, single-word,
non-English, empty bundle, duplicates, hostile input) + artifact smoke + an offline
drift gate. All three gauntlet gates must pass before release.

Standard library only. MIT.

## Known limits

- The topical gate is token overlap. A paper sharing two common root words survives.
- A question phrased in ordinary words ("choose which neighbouring field is relevant")
  has no technical anchor and returns noise — ask in the vocabulary of a field.
- Concepts are phrases lifted from titles, keywords and abstracts, so Eonrise names a
  subject, never a technique. Naming a method needs a model reading the papers.
- `--semantic` needs an OpenAlex key; without one it falls back to keyword search.
