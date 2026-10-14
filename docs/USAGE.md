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

A run writes five files to `--out`: `report.md` (the brief), `research_map.json` (everything,
for scripts), `internal_report.md`, `graph.json`, and `README.md`, a guide to every file, field
and number. The same guide is [OUTPUT.md](OUTPUT.md); a test keeps it in line with the real
output.

A `failed` run exits with code 2, so scripts can tell a broken search from a thin literature.

## Environment variables

| Variable | Same as | Use |
| --- | --- | --- |
| `CROSSREF_EMAIL` | `--email` | Contact address for Crossref's polite pool. |
| `OPENALEX_API_KEY` | `--openalex-key` | Higher OpenAlex limits; needed for `--semantic`. |
| `S2_API_KEY` | `--s2-key` | Semantic Scholar; the keyless pool often answers 429. |
| `CORE_API_KEY` | `--core-key` | CORE; keyless requests are refused after a few calls. |
| `EONRISE_CACHE_DIR` | `--cache-dir` | Folder for every store and cached response. |

Keys never appear in reports or error messages.

## What a run keeps

Live runs keep state under `~/.cache/eonrise/` so later runs cost fewer API calls.
`--cache-dir .eonrise` (or `EONRISE_CACHE_DIR`) keeps all of it inside a project folder:

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
