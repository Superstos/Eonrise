# Using Eonrise

`eonrise --help` lists every flag. This page covers what the help cannot: the input format,
the output files, the environment variables, and what a run keeps on disk.

## Evidence bundles

`--bundle PATH` runs offline on papers you gathered yourself. `PATH` is a JSON file or a folder
of `*.json` files; repeat `--bundle` to merge several. The same DOI or title in two bundles is
merged, keeping the richer record.

A bundle is a list of papers, or an object with a `papers` list:

```json
{
  "question": "optional; used by --demo",
  "papers": [
    {
      "paper_id": "doi:10.1000/example",
      "title": "Required: papers without a title are skipped",
      "abstract": "Most of the map is read from here.",
      "url": "", "doi": "", "year": 2024, "cited_by_count": 0,
      "provider": "", "venue": "",
      "keywords": [], "fields": [], "topic_path": []
    }
  ]
}
```

Only `paper_id` and `title` are required. Unknown keys are ignored. `fields` and `topic_path`
feed the neighboring-field part of the map, so a bundle without them rarely finds one.
`eonrise/data/demo_bundle.json` is a full example.

## Output files

A run writes four files to `--out`:

| File | What it holds |
| --- | --- |
| `report.md` | The short brief: map, stated limitations, distant-field papers, next searches. |
| `internal_report.md` | The concept tree, search rounds and evidence behind each term. |
| `research_map.json` | Everything, for other tools. Carries `version` (the schema version, now 5). |
| `graph.json` | `nodes` and typed `edges` for a graph view. |

Useful keys in `research_map.json`:

- `status` is `usable`, `partial` or `failed`; `stop_reason` says why the run ended.
- `coverage` maps each part of the map (mechanism, measurement, failure_mode, method,
  neighbor_field) to its grounded terms; `gaps` lists the parts left empty.
- `harvest` holds the distant-field papers that share the question's shape.
- `papers` are the papers kept; `on_topic_paper_ids` marks the ones about the question.
- `providers_down` and `provider_errors` say which sources failed during the run.

A `failed` run exits with code 2, so scripts can tell a broken search from a thin literature.

## Environment variables

| Variable | Same as | Use |
| --- | --- | --- |
| `CROSSREF_EMAIL` | `--email` | Contact address for Crossref's polite pool. |
| `OPENALEX_API_KEY` | `--openalex-key` | Higher OpenAlex limits; needed for `--semantic`. |
| `S2_API_KEY` | `--s2-key` | Semantic Scholar; the keyless pool often answers 429. |
| `CORE_API_KEY` | `--core-key` | CORE; keyless requests are refused after a few calls. |

Keys never appear in reports or error messages.

## What a run keeps

Live runs keep state under `~/.cache/eonrise/` so later runs cost fewer API calls:

| Path | What | Turn off with |
| --- | --- | --- |
| `<hash>.json` | Cached API responses | (delete the files) |
| `corpus.jsonl` | Every paper retrieved, searched before the APIs | `--no-corpus` |
| `equivalence.jsonl` | Terms that mean the same across fields | `--no-equivalence` |
| `memory.jsonl` | One line per run; down-weights terms repeated across questions | `--no-memory` |
| `providers.json` | Which sources are rate limited, and until when | |

`--corpus` and `--equivalence` move those two stores. `--demo` keeps nothing: it uses a
temporary folder and deletes it when the run ends.

Records from scholarly sources keep their own licenses; see the README before sharing a cache.
