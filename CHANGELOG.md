# Changelog

User-facing changes. `docs/SPEC.md` keeps the engineering history.

## 0.10.2 - 2026-10-14

### Fixed

- Grammar words in a question (`often`, `come`, `keep`, `two`, ...) no longer become the search's root topic. One run had searched `often come` and retrieved titles like "Do You Come Here Often?".

## 0.10.1 - 2026-10-14

### Changed

- The brief's *Same shape, other fields* section opens with one line saying why those papers look unrelated and how to read them, so an agent reading it cold maps them instead of calling them noise.
- The skill installs in Codex from the same marketplace: `codex plugin marketplace add https://github.com/Superstos/Eonrise`, then `codex plugin add eonrise@eonrise`.
- The README shows the new banner, linked by full address so it also shows on PyPI.

## 0.10.0 - 2026-10-14

### Added

- Eonrise skill and Claude Code plugin (`plugin/`): teaches an agent to run Eonrise and map each distant paper to a concrete idea instead of dismissing it. Install with `/plugin marketplace add Superstos/Eonrise`, then `/plugin install eonrise@eonrise`.
- `tools/agent_check.py` measures how many distant fields a model's answer uses, with and without the skill.
- Every run folder gets a `README.md` saying what each file, field and number means (also `docs/OUTPUT.md`). A test fails when a field goes undocumented.
- Each distant paper in the brief carries *What they did*, the abstract sentence that names its method or result, so it can be mapped without opening the paper.
- `--cache-dir` and `EONRISE_CACHE_DIR` keep every store and cached response in one folder, such as `.eonrise` inside a project.
- `from_store_paper_ids` lists the papers the local store supplied from earlier runs; the brief marks them.

### Fixed

- The local paper store no longer floods unrelated questions with old papers. A stored paper now needs 30% of the query's weight, each word weighted by how rare it is in the store, plus two of the query's words side by side; field labels no longer count. Before, any two shared words matched, and on a 5,837-paper store a question about films got ten unrelated papers, which also skipped the live search.

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
