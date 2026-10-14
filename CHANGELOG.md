# Changelog

User-facing changes. `docs/SPEC.md` keeps the engineering history.

## Unreleased

### Added

- Eonrise skill and Claude Code plugin (`plugin/`): teaches an agent to run Eonrise and map each distant paper to a concrete idea instead of dismissing it. Install with `/plugin install eonrise --marketplace Superstos/Eonrise`.
- `tools/agent_check.py` measures how many distant fields a model's answer uses, with and without the skill.

## 0.9.0 - 2026-10-14

First public release.

### Added

- `--version` prints the installed version.
- `docs/USAGE.md`: bundle format, output files, environment variables, and what a run saves.
- `--demo` runs offline on a sample bundle shipped in the package and writes only to `--out`.
- The source package carries the tests, fixtures and benchmarks, and they pass from it.
- The release workflow runs the tests first, refuses a tag that differs from `__version__`, and can rehearse the upload on TestPyPI.

### Changed

- The brief's header lines (question, root topic, status, evidence, warnings) are separate paragraphs; they ran together into one line on GitHub.
- README rewritten around a real brief; `examples/` holds two live runs and the demo.
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
