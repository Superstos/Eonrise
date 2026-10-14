# Eonrise output

## Files

| File | What it holds |
| --- | --- |
| `report.md` | The brief. Read this first. |
| `research_map.json` | Everything the run found, for scripts. Fields below. |
| `internal_report.md` | The concept tree, each search round, and the evidence behind each term. |
| `graph.json` | `nodes` and typed `edges`, for a graph view. |
| `README.md` | This guide. |

## Reading order

1. `status` in report.md. `failed` means no paper was about the question: rephrase, do not build on it.
2. **Same shape, other fields**: papers from distant fields that share the question's concepts. Each carries one sentence on what the paper did. These are the reason to run Eonrise.
3. **Grounded map** and **Stated limitations**: what the on-topic papers say.
4. **Unfinished: saw at most ~N%**, when present: the search is partial, so an empty section is unsearched, not absent.
5. **Next searches** and **Searches toward other fields**: run one or two when the first pass is thin.

## Numbers

- **`status`**: `ready` > `usable` (4 or 5 of the 5 map parts grounded) > `partial` > `failed` (no paper was about the question). A `failed` run exits with code 2.
- **`unseen.found_share`**: An upper bound on the share of the papers *these queries* can reach that the run saw. It says nothing about all research. A follow-up run with broader queries can reach far more papers, so its share can drop while it finds more: compare `unseen.observed`, not the percentages.
- **`on_topic_papers vs on_topic_paper_ids`**: The first is a count, the second the list of IDs.
- **`retrieved_papers vs papers`**: Every paper the run saw, against the 50 it kept in `papers`.

## Fields in research_map.json

| Field | Type | Meaning |
| --- | --- | --- |
| `version` | int | Schema version of this file, now 5. |
| `question` | str | The question as asked. |
| `root_topic` | str | The question reduced to its topic words; the root of the concept tree. |
| `mode` | str | `live` (searched the APIs) or `assistant` (read the given bundles only). |
| `status` | str | `ready`, `usable`, `partial` or `failed`. See Numbers. |
| `stop_reason` | str | Why the run stopped. |
| `coverage` | dict | Each map part (mechanism, measurement, failure_mode, method, neighbor_field) to its grounded terms. |
| `gaps` | list[str] | Map parts with no grounded term. |
| `dormant_relations` | list[str] | Map parts that got no candidate in two full rounds; the run stopped searching for them. |
| `harvest` | list[dict] | The distant-field papers: `paper_id`, `title`, `year`, `url`, `field`, `distant` (true when the field differs from the on-topic papers'), `shares` (concepts shared with the question), `what_they_did` (one abstract sentence, empty without an abstract), `score`. |
| `distant_queries` | list[str] | Searches that follow the harvest into other fields. |
| `recommended_queries` | list[str] | Next searches that would fill the gaps. |
| `limitations` | list[dict] | Failure modes the papers state themselves, with quoted `examples`. |
| `terms` | list[dict] | The top 30 grounded terms: `text`, `relation`, `confidence`, `paper_ids` and the queries that found them. |
| `concepts` | list[dict] | The concept tree: `label`, `direction` (up, down, sideways), `depth`, `parent_id`, `paper_ids`. |
| `graph` | dict | `nodes` and `edges`, the same as graph.json. |
| `papers` | list[dict] | The 50 papers kept: `paper_id`, `title`, `abstract`, `url`, `doi`, `year`, `cited_by_count`, `provider`, `keywords`, `fields`, `topic_path`, `venue`. |
| `on_topic_paper_ids` | list[str] | IDs of the papers about the question. |
| `on_topic_papers` | int | How many papers were about the question (a count, not a list). |
| `retrieved_papers` | int | Every paper the run saw, before keeping 50. |
| `from_store_paper_ids` | list[str] | Papers the local store supplied from earlier runs, not a live search. |
| `unseen` | dict | How much of what the queries can reach was seen: `observed`, `estimated_total`, `found_share`, `singletons`, `doubletons`. See Numbers. |
| `rounds` | list[dict] | One row per search round: queries, new papers, gaps left, stop checks. |
| `policy` | dict | The search budget used: `max_nodes`, `max_depth`, `max_rounds` and weights. |
| `query_expansion` | dict | Extra queries made from learned equivalent terms, and how many slots were used. |
| `provider_errors` | list[str] | Errors from the sources. Keys never appear here. |
| `providers_down` | list[str] | Sources that answered nothing this run. |
| `providers_blocked` | list[str] | Sources skipped because they are rate limited. |
| `calls_saved_by_corpus` | int | Live searches skipped because the local store already answered. |
| `corpus_added` | int | Papers this run added to the local store. |
| `corpus_size` | int | Papers in the local store after this run. |
| `equivalence_store` | str | Path of the equivalent-terms store. |
| `equivalence_observations` | int | Term pairs this run learned. |
| `equivalence_edges` | int | Equivalent-term pairs in the store after this run. |
| `background_terms_penalised` | int | Terms down-weighted because earlier questions used them too. |
| `input_bundle` | str | The first bundle read, in `assistant` mode. |
| `input_bundles` | list[str] | Every bundle read, in `assistant` mode. |
