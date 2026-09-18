# Eonrise v0.1 spec — single root, agent-owned recursion

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

# v0.2 — drift guards, gap repair, keyless OpenAlex

Added 2026-09-15 after running Eonrise on itself four times and measuring the artifacts.
Findings: `references/eonrise-enhancement/00-index.md` in the training-grounds repo.

## What was wrong

| Defect | Measurement |
|---|---|
| Crossref carries no topic hierarchy and few abstracts | 0% subjects, 16% abstracts over 200 kept papers |
| `neighbor_field` therefore cannot ground | gap in 6/6 runs |
| Sub-queries drop the question | a map-quality run ended in gene-ontology literature |
| Drift reads as productivity | 120-158 new papers per round keeps `saturated` false |
| `next_queries` never searched | computed at exit, printed, never fed back |
| Marker words label relations alone | `high performance computing` = measurement, `kidney failure` = failure mode |
| Concept budget spent on paraphrases | 69-81% substring-redundant labels |
| Papers kept by citations | median year 2006-2013 |
| `ready` needs all five relations | 4/4 runs `partial` |

## Rules added

- **Providers.** OpenAlex is default and keyless; a key only raises limits and enables
  `--semantic`. `--crossref-only` is an explicit downgrade.
- **Topical gate.** `topical_papers()` keeps a paper when it shares two root tokens, or one
  root token plus another question token. Concepts are extracted from that subset only.
  Below `MIN_TOPICAL_CORPUS` (8) the gate stands down so small bundles still work.
- **Saturation.** counts on-topic arrivals, not all arrivals.
- **Gap repair.** `GAP_QUERY_SLOTS` (2) of the 5 per-round queries come from
  `next_queries`. The cue steers retrieval; it may not become a finding.
- **Relation guard.** `mechanism/measurement/failure_mode/method` need on-topic support, and
  a term made only of gap-cue words is demoted to `topic`.
- **Concept identity.** `concept_key()` is a stemmed token set; a label that contains or is
  contained by a taken key does not get its own node.
- **Keep score.** on-topic first, then recency + citations, before truncating to 50.
- **Status.** `ready` > `usable` (4-5 of 5 relations, gaps repaired where possible) >
  `partial` > `failed`. `STATUSES` in `models.py` is the closed vocabulary.
- **Round stats.** carry `gap_queries`, `new_on_topic`, `on_topic_papers`;
  `internal_report.md` prints them as a Search integrity table.

## Gate additions

`tests/test_drift_guards.py` — 22 tests, each written to fail in both directions
(the gate must block the drifted paper AND pass the on-topic one). Verified by mutation:
removing the relation guard and the redundancy skip fails 4 of them.

## Known limits (measured, not fixed)

- The topical gate is token overlap. A paper sharing two common root words survives:
  a dark-matter detector paper passed a question about stopping criteria. Corpus-frequency
  weighting was implemented and reverted — it could not separate those cases without
  starving the on-topic set.
- `failure_mode` still fails to ground on 3 of 4 self-test questions even after gap repair.
- `neighbor_field` now grounds, but often as an OpenAlex domain label
  ("biochemistry genetics and molecular biology") rather than a useful adjacent field.


# v0.3 — release candidate

Added 2026-09-15, driven by running the v0.2 build on its own weak spots.

## What the v0.2 runs exposed

| Finding | Measurement |
|---|---|
| Discipline names dominate every map | `computer science` in the top 10 of 8/8 runs |
| `GENERIC_FIELDS` was checked on one source of four | same label also arrives as keyword, topic, title n-gram |
| Provider hierarchy is mostly shelf labels | `fields` = Physical Sciences / Computer Science / Artificial Intelligence on 25 of 50 papers |
| `failure_mode` never grounds | 50 papers, 35 abstracts, 8 with a limitation cue, 12 distinct phrases, 0 repeated — the support>=2 rule killed all of them |
| Sentence fragments become concepts | `relation between`, `problem very terms`, `you actually` |
| Term list keeps paraphrases | `search algorithm` and `search algorithms` in one top five |

## Rules added

- **One gate for generic labels.** `_add_candidate` drops `GENERIC_FIELDS`, fragment edges
  (`WEAK_EDGE` first or last token) and filler (`FILLER` anywhere).
- **Hierarchy is a neighbour, never a competitor.** Topic paths and fields always carry
  `neighbor_field`; OpenAlex contributes only its subfield, not domain or field.
- **Background penalty.** `MemoryStore.background_labels` collects labels that ranked high
  under three or more unrelated roots; their score is halved.
- **Limitations from sentences.** `limitation_phrases()` reads the words after a limitation
  cue and marks them explicit, because every paper words its limitation differently and the
  two-paper rule erased all of them. The sentence travels with the term and is printed.
- **Paraphrase collapse on reported terms.** `dedupe_terms()` applies the concept-key rule
  to the term list, not only to the concept tree.

## Gate additions

Third gauntlet gate: an offline half-on-topic/half-neighbouring corpus must not put the
neighbour in the map. 50 unit tests.

## Measured, v0.2 -> v0.3

| | v0.2 | v0.3 |
|---|---|---|
| `computer science` in top 10 | 8/8 runs | 0/4 runs |
| `failure_mode` grounded | 0/4 runs | 3/3 runs, each quoted from its abstract |
| Neighbour labels | "biochemistry genetics and molecular biology" in 3/4 | "numerical analysis", "statistics probability and uncertainty", "management science and operations research" |


# v0.3.1 — provider honesty

Added 2026-09-15, driven by running the v0.3 build on two of its own weak spots.

## What the runs exposed

Both live runs looked like algorithm failures: 41 and 26 on-topic papers produced 7 and 3
concepts, and 4 to 5 of the 5 relations stayed empty. The cause was not the algorithm.

| | stopping run | technique run |
|---|---|---|
| on-topic papers | 41 | 26 |
| from OpenAlex | 0 | 0 |
| OpenAlex calls, all HTTP 429 | 16 | 13 |
| papers carrying keywords | 0 | 0 |
| papers carrying a topic hierarchy | 0 | 0 |
| papers carrying an abstract | 10 | 2 |
| candidate phrases | 164 | — |
| candidates surviving `support >= 2 or explicit` | 11 | — |

OpenAlex answered every request with `429` and `Retry-After: 30746` — a quota window about
eight hours wide. The run degraded to Crossref-only, which is the exact case v0.2 measured
as unable to ground `neighbor_field`, and nothing in the brief said so.

## Fix

- A `429` whose `Retry-After` is at or above 120s puts that host in cooldown for the rest
  of the run; later calls raise `ProviderUnavailable` without touching the network. A short
  `Retry-After` is still retried, because a burst limit is worth waiting out.
- Rate pacing is per host, so a busy Crossref no longer spends OpenAlex's interval.
- `providers_down` lists any provider that failed every call it was given, and the brief
  prints a **Degraded** line naming it and what the map is missing because of it.

Measured: the same question that spent 16 doomed OpenAlex calls now spends 1.


# v0.4 — more sources, and a smaller engine

Added 2026-09-15, after OpenAlex's credit limit made a single-source run the normal case.

## Sources

Four keyless providers now run by default (Crossref, OpenAlex, Europe PMC, DOAJ); Semantic
Scholar and CORE join when a free key is supplied. Same question, same day, OpenAlex still
rate limited:

| | 2 sources | 4 sources |
|---|---|---|
| papers retrieved | 263 | 790 |
| on-topic | 41 | 50 |
| concepts | 7 | 14 |
| relations missing | 4 | 3 |

## Architecture review

GPT-6-Astra reviewed the shape before more sources were added. Its calls, and what was done:

- **Keep one class per source.** Six twenty-line adapters are cheaper than a spec language
  that grows conditionals. Revisit only when eight of ten adapters are pure field renames.
- **Do not weight evidence by which source supplied it.** One query cannot justify a
  universal ranking; score the record in hand, not the provider's reputation.
- **Split evidence interpretation out of traversal.** Done: `evidence.py` takes the corpus
  and returns grounded, ranked terms; `engine.py` keeps rounds, gap repair, budgets and
  status. Engine went from 650 to 342 lines.
- **Not yet built:** a `scheduling.py` holding per-source budget state and next-source
  choice. Cooldown currently lives in the HTTP client, which is enough for one process.

## Known open question

Europe PMC supplied 3 of 50 kept papers in the run above: keep-ranking still prefers
citations over metadata richness, and the papers that ground relations are the ones with
abstracts. Left as measured, not patched, because one query cannot settle source order
across domains.


# v0.4.1 — what three self-runs found

Run 2026-09-15 on three questions about research discovery itself, live, four providers.

| Run | Status | On topic | Concepts | Relations grounded |
|---|---|---|---|---|
| hypothesis generation | usable | 27 | 38 | 4/5 |
| hidden connections between literatures | partial | 59 | 32 | 3/5 |
| causal mechanism extraction | partial | 49 | 23 | 3/5 |

## Bug the runs exposed

The brief quoted "Assessing the Connections between State Failure, Insurgency, and
Terrorism" as a stated limitation. That is a title, from a paper with no abstract: the
title n-gram was relation-typed `failure_mode` because it contains the word "failure", and
the brief printed the title as though the authors had written a limit. A `stated_limitation`
flag is now set only by `limitation_phrases`, and the brief prints nothing else.

## A feature that was built, measured and removed

Swanson's ABC linking — find a term B shared by two literatures that share no paper, which
is how fish oil and Raynaud's syndrome were connected in 1986. It was implemented against
the evidence Eonrise already collects, then measured on the three runs above:

| Run | Terms | Bridges found | Useful |
|---|---|---|---|
| hypothesis generation | 51 | 2 | no — both bridged on the MeSH term "animals", 1 paper each side |
| hidden connections | 58 | 0 | — |
| causal mechanism | 60 | 0 | — |

The method needs two large literatures gathered separately; a 50-paper corpus centred on
one question has no disconnected second side to bridge to. The code was removed rather than
shipped as a lead generator that mostly emits noise. What it would need first: retrieval
that gathers an A-literature and a C-literature separately, several hundred papers each.

## The ceiling, restated with evidence

Drift now traces to one place: the topical gate is word overlap. The question about hidden
connections between literatures kept papers on Puerto Rican diasporic music, because both
share the word "connections". Concept-level matching, not a longer stopword list, is the
next real step.


# v0.5 — the paper store

Added 2026-09-15. The first feature chosen because it compounds with the others rather than
standing alone.

## Why this one

Three problems measured over the previous passes had one shared cause: every run started
from nothing.

| Problem | Evidence | What a store does about it |
|---|---|---|
| OpenAlex credits run out | 16 searches per run against ~100 anonymous searches a day | A held paper costs no credit |
| Crossref records carry no abstract | 10 abstracts in 41 on-topic papers | The same DOI from Europe PMC fills it in, and the fill is kept |
| Swanson ABC finds nothing | 2 junk bridges across three runs, 50 papers each | Literatures accumulate across runs instead of dying with one |

## Shape

`corpus.py` holds an append-only JSONL of papers merged by DOI, and answers `search` like
any other provider. The CLI inserts it ahead of the network providers, so a stored paper is
found before a credit is spent, and writes the run's kept papers back at the end.

It calls no network, so it is fully testable offline: 8 tests cover a second run reading the
first run's papers, duplicate merging, enrichment of a thin record, a half-written line not
destroying the store, copies rather than shared objects, and the one-shared-word rejection.

## Deliberately not done yet

Corpus-level term statistics for the topical gate. The store must hold a few thousand papers
before co-occurrence means anything; building the statistic now would tune it on noise.


# v0.6 — source scheduling

Added 2026-09-15, the second feature in the compounding chain and the one Astra named when
it reviewed the architecture: budget and availability needed somewhere to live that is not
the HTTP client.

## A gate change that was tried and rejected first

Drift traces to the topical gate being word overlap. The attempted fix was to also require
an adjacent word pair from the root, tested offline against four saved runs:

| Run | Kept now | Relations now | Kept, phrase gate | Relations, phrase gate |
|---|---|---|---|---|
| hypothesis generation | 27 | 4/5 | 5 | 1/5 |
| hidden connections | 50 | 2/5 | 10 | 0/5 |
| causal mechanism | 49 | 2/5 | 18 | 2/5 |
| stopping criteria | 50 | 2/5 | 24 | 1/5 |

It dropped papers that were plainly on topic — "Causal-Text: An Interpretable Framework for
Causal Inference" among them — and grounded fewer relations everywhere. Rejected. Combined
with the corpus-frequency weighting rejected in v0.3, the gate has now failed two different
tightenings; the next attempt should widen the evidence, not narrow the filter.

## What shipped instead

`scheduling.py`: provider capability, availability and order, with no network and no engine
imports.

- `order_for(names, gaps, states)` ranks sources by what the round is missing — abstracts
  for `failure_mode`, `mechanism`, `measurement`, `method`; subject labels for
  `neighbor_field` — and breaks ties by credit cost.
- `ProviderStates` persists a block to `~/.cache/eonrise/providers.json`, so the eight-hour
  OpenAlex window is paid once rather than once per run.
- 10 tests, offline, both directions: a blocked source leaves the order and returns when its
  window passes, a corrupt state file changes nothing, no provider is silently dropped.

Capability numbers come from one measured query. They are a routing preference, not a
ranking of scientific worth, and they are written in one table to be argued with.

# v0.7 — a relation needs a sentence, not a label

## The failure it closes

A run on "how do search systems reuse results from earlier queries to write better later
queries" reported its mechanisms as `service oriented architecture and web services` and
`advanced data storage technologies`, and its measurements as `human resource development
and performance evaluation`. None of those are mechanisms or measurements. All three are
provider subject labels: OpenAlex keywords that matched a relation marker word
("architecture", "performance", "evaluation") and were promoted on that word alone. The
"evidence" stored beside each one was a paper title, because no sentence anywhere said the
thing.

Labels are free and infinite — every paper carries several, and providers assign them by
classifier. A sentence costs a real abstract from a real paper. Before this change the
cheapest evidence outranked the truest.

## The rule

A down-relation (`mechanism`, `measurement`, `failure_mode`, `method`) is kept only when the
term was read out of an abstract at least once — an abstract n-gram or a stated-limitation
sentence. Otherwise the term stays in the map as `topic`. Subject labels and topic paths are
unaffected as `neighbor_field`: naming the neighbourhood is exactly what they are good for.

`CandidateEvidence.abstract_count` records the provenance at admission time;
`_guard_relation` reads it. Title n-grams do not count — measured, they supply junk like
`connections between state failure`.

## Measured, 7 saved runs, offline

| Run | Down-relation terms in top 30 | Abstract-backed | Dropped |
|---|---|---|---|
| v9-query-feedback | 3 | 0 | 3 |
| v7-stopping | 2 | 0 | 2 |
| v7-map-quality | 4 | 1 | 3 |
| v7-polysemy | 4 | 3 | 1 |
| x3-mechanism | 9 | 8 | 1 |
| x1-hypothesis | 6 | 5 | 1 |
| x2-undiscovered | 2 | 0 | 2 |

Every obviously wrong term is in the dropped column. Three runs lose their mechanism row
entirely and now report it as a gap — which is the honest reading, since those rows had
never been anything but labels.

## Why this compounds

Abstracts arrive from Europe PMC, DOAJ and the local paper store, and the store keeps them.
The more the store holds, the more relations can be grounded in sentences. The label path
saturates immediately; the sentence path grows with the corpus.

## Deliberately not done

The example stored beside an abstract n-gram is still the paper title, not the sentence the
phrase came from. Capturing the sentence would make the brief's Evidence section quotable.
One improvement per pass; this is the next one.

## Dead end recorded

Requiring a kept paper's topical hits to come from author words (title + keywords) rather
than assigned subject labels. Measured on 7 saved runs: it dropped 2 of 50 in
v9-query-feedback (correctly) but 23 of 50 in x1-hypothesis, including "Accelerating
scientific discovery with Co-Scientist" — plainly on topic. Third failed tightening of the
topical gate. The gate is not the lever.

# v0.8 — six defects a second reader found, and one idea its own test killed

GPT-5.6 (thinking effort high) read the repo at `9efcdd0` through a GitHub connector. It
could not run the tests — its sandbox cannot resolve github.com — and it said so unprompted.
It made six code-level claims. All six were verified in the source before anything changed.

| Claim | Verified at | Fixed |
|---|---|---|
| `MemoryStore.recall()` never seeds a run | `memory.py:62`, zero callers | no — see below |
| Only the kept 50 papers reach the store | `cli.py:126` | yes |
| The `up` direction is unreachable | `engine.py:260` always passed `"term"` | yes |
| `_keep_score` ignores evidence richness | `engine.py:100` | yes |
| All five relations are mandatory | `evidence.py:357` | yes |
| Ordering never saves a paid call | `engine.py:212`, no break | yes |

## The `up` direction was a lie in the artifact

`relation_to_direction` returned `up` only for source kinds `field` / `broader_topic`, and
concepts are always built with `"term"`. So the branch never ran, every non-down concept came
back `sideways`, and the measured 118-of-120 sideways map was partly an artefact of the
mapping rather than of the literature. A `neighbor_field` term is the broader classification a
paper sits under, so that is what up means here — and up carries half the weight, which is the
whole reason for naming a direction. Live run: 7 up nodes where there had been 0.

## The store was capped at what a reader sees

`corpus.add()` was fed `result["papers"]`, the kept 50. A run that retrieves 963 papers taught
the next run about 50 of them. The engine now returns every retrieved paper separately under
`corpus_papers`; the CLI stores those and drops the key before the artifact is written, so the
JSON on disk is unchanged in size.

## Ordering now actually ends a query

v0.6 ranked the providers and then called every one of them, so a held paper cost exactly what
a fetched one did. When the local store answers a query with a full page of results, the paid
providers are skipped for that query and `calls_saved_by_corpus` counts it. First live run
saved 1 call against a 100-paper store — the number only means anything as the store grows,
which is the point.

## An abstract now outranks a citation count

Under v0.7 a paper with no abstract cannot ground a mechanism, a measurement, a method or a
failure mode; it can only add a subject label. Keeping it above a paper that carries text was
ranking the artifact's least useful evidence first. Live run: the kept 50 went from 72% to 96%
carrying an abstract.

## A relation the literature never mentions is no longer chased

Two full rounds with not one candidate term for a relation marks it dormant: it stops driving
gap queries and is reported as "not in this literature" instead of an unfilled gap. 5/5 was
being treated as universal completeness for every question ever asked.

## Positive evidence memory: proposed, pre-registered, and killed by its own test

The proposal was to recall previously grounded claims and use them as retrieval anchors. Its
author's kill rule, agreed before building: median ΔGER@20 ≤ 0 over a chronological replay,
or a lift that vanishes once repeated DOIs are removed.

| Condition | Runs | Median ΔGER@20 | Wins | Losses | Ties |
|---|---|---|---|---|---|
| all papers | 44 | +0.0000 | 16 | 1 | 27 |
| repeated DOIs removed | 31 | +0.0000 | 6 | 1 | 24 |

Median is exactly zero in both conditions, so by the pre-registered rule it does not get built.
Worth saying why the test could not discriminate: every saved run holds only its 50 survivors,
so the replay reranks 50 candidates into a top 20 and most runs simply tie. That bottleneck is
what this version removed. The test becomes meaningful once runs have been stored whole for a
while — it is not evidence the idea is wrong, it is evidence the data cannot yet tell.

What did ship is the half that needs no belief: `append_run` now records **claims** — grounded
down-relation terms with their supporting paper ids and the sentence each was read from.
Nothing ranks on them yet. A claim not written down when it is made cannot be measured later
at all.

## v0.8.1 — a failed run is a failed process

Reported from a live session 2026-09-16: Europe PMC socket-timed out, the run retrieved
nothing, and `python -m ontology_router.cli` exited **0**. The brief it wrote was worse than
the exit code — `Status: failed` sat above five "not grounded yet" relations and a
`**Degraded:**` line, which reads like a thin literature rather than a broken search.

Two fixes, both verified in both directions:

1. `cli.main` raises `SystemExit(2)` when `status == "failed"`. Verified: empty bundle →
   exit 2, `tests/fixtures/papers.json` → exit 0.
2. The compact brief leads a failed run with the provider errors and the sentence
   *"the search failed, not because the literature is silent"*, and suppresses the
   `**Degraded:**` line in that case, since that line describes a usable partial run.

The stdout summary also carries `providers_down` and the first five `provider_errors`, so a
caller scripting Eonrise sees the cause without opening the artifact.

**Not reproduced:** the same report said the output directory was empty. `write_outputs`
runs unconditionally after the round loop and produced all four artifacts in every failure
path tried, including a total provider outage. No code path exits 0 without writing.

Version constants aligned: `__init__.py` said `0.5.0` while `pyproject.toml` said `0.8.0`;
both now read `0.8.1`.

# v0.9 — concept equivalence graph and query expansion

Added 2026-09-18. This is the first compounding terminology feature: Eonrise can learn
that two fields use different words for nearby concepts and reuse that knowledge as an
alternate query.

## Shape

`equivalence.py` stores unordered label pairs in a separate append-only JSONL,
`~/.cache/eonrise/equivalence.jsonl`. A record is one observation or revocation; a
half-written line is skipped like the paper store. Duplicate evidence merges by paper
identity, and confidence grows only when independent papers support the pair.

An edge carries the two labels, `equivalent` or `closely_related`, supporting paper
ids, fields, confidence, evidence, queries, and source sentences.

## Conservative evidence

- Explicit terminology statements (`also known as`, `referred to as`, `equivalent to`,
  and similar wording) can create `equivalent`.
- Repeated co-occurrence can only create `closely_related`; it never expands a query.
- Automatic learning needs an active topical filter (`>= 8` on-topic papers).
- Pairs must be plausible labels, order-insensitive, non-identical, and supported by at
  least two independent papers.
- Components larger than eight labels do not expand: growth usually means polysemy.
- Revocation is a tombstone, not deletion.

## First integration

Query expansion only. One confident equivalent alias may use a query slot inside the
existing five-query budget. The original query is always searched first; expansion is
one level, phrase-shaped, and never recursive. Ranking, concept identity, the topical
gate, and `graph.json` are unchanged.

CLI:

```bash
--equivalence PATH
--no-equivalence
--query-expansion-slots N
```

## Measured, offline synthetic benchmark

`python -m ontology_router.equivalence_benchmark`

| Scenario | Baseline GER@20 | Expanded GER@20 | Gain | Precision loss |
|---|---|---|---|---|
| concept drift / distribution shift | 0.6667 | 1.0000 | +0.3333 | 0.1000 |
| non-stationarity / regime change | 0.6667 | 1.0000 | +0.3333 | 0.1000 |
| feedback loop / closed-loop control | 0.6667 | 1.0000 | +0.3333 | -0.0429 |
| fault tolerance / resilience | 0.6667 | 1.0000 | +0.3333 | 0.0000 |
| robustness / reliability control | 0.6000 | 0.6000 | 0.0000 | 0.0000 |

Totals: 4/4 true equivalences discovered, false-equivalence rate 0.0, median retrieval
gain +0.3333, median precision loss 0.05, net median gain +0.2833. The kill rule passes.

This benchmark is synthetic by design: alternate-vocabulary papers are reachable only
through the learned alias in title/abstract text, while keywords and fields establish
topicality. It measures the intended mechanism, not live retrieval across providers.

## Deliberately not done

Equivalence-aware topical gating, concept deduplication, neighbor-field discovery,
knowledge-gap detection, and Swanson-style bridging remain future integrations. Each
needs its own benchmark before it touches ranking or gating.
