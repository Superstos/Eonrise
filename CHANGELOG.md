# Changelog

User-facing changes. `docs/SPEC.md` keeps the engineering history.

## Unreleased

### Changed

- The import package is now `eonrise` (was `ontology_router`).
- `--max-nodes` defaults to 400 (was 120), so a typical question finishes gap repair on default settings.
- A failed request no longer prints its query string, which carried API keys and the contact email.
- Removed `--agent-name` and the `agent` field in the printed summary. Eonrise runs no AI agent; the name misled.

### Renamed

Old names are gone, not aliased: nothing was published under them.

| Old | New |
| --- | --- |
| `ontology_router` | `eonrise` |
| `engine.run_agent` | `engine.run_search` |
| `engine.run_router` | removed; call `run_search` |
| `models.AgentPolicy` | `models.SearchSettings` |
| `harvest.py`, `harvest()`, `HARVEST_SIZE`, `signature()` | `distant_fields.py`, `rank_distant_papers()`, `DISTANT_PAPER_LIMIT`, `question_shape()` |
| `evolution.py` | `equivalence_versions.py` |
| `unseen.py`, `estimate()` | `literature_coverage.py`, `estimate_coverage()` |
| `memory.py`, `MemoryStore` | `question_log.py`, `QuestionLog` |
| `corpus.py`, `CorpusStore` | `paper_store.py`, `PaperStore` |
| `evidence.tokens()`, `stem()`, `family()`, `paper_tokens()`, `voting_core()` | `split_words()`, `to_singular()`, `word_family()`, `paper_word_families()`, `grounding_papers()` |
| `eonrise/unseen_benchmark.py` | `benchmarks/coverage_stop_rules.py` (no longer shipped in the wheel) |
| `eonrise/equivalence_benchmark.py` | `benchmarks/equivalence.py` (no longer shipped in the wheel) |
| `gauntlet/run.py` (`python -m gauntlet.run`) | `benchmarks/run.py` (`python -m benchmarks.run`) |

Unchanged on purpose: the output keys in `research_map.json` (`harvest`, `unseen`, `corpus_*`), the cache file names under `~/.cache/eonrise/`, and the `--corpus` and `--no-memory` flags. Renaming those would break existing outputs and caches; they move together with the output schema version.
