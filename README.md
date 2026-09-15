# Eonrise v0.3.1

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

OpenAlex runs by default and needs no key; a key only raises rate limits and enables
`--semantic`. Crossref alone carries no topic hierarchy and few abstracts (measured over
200 retrieved papers: 0% subjects, 16% abstracts), which leaves `neighbor_field`
permanently empty — `--crossref-only` accepts that trade deliberately.

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

Builder → redteam loop: 50 unit tests + 6 offline attacks (vague, single-word,
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
