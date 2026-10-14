# Launch plan (temporary)

Working checklist for the agent preparing the public release. Change it freely; delete it after
launch. Source: 2026-10-12 audit. Detail lives in commits and `CHANGELOG.md`, not here.

## Decided

- Name stays **Eonrise**. No trademark search needed before the logo.
- Repo stays at `Superstos/Eonrise`. No org.
- Agent may commit and push to `main`. Ask before: deleting branches or runs, making the repo
  public, publishing to PyPI, buying anything.

## Done

- [x] API keys and emails kept out of error text and reports
- [x] Package renamed `ontology_router` -> `eonrise`
- [x] Default `--max-nodes` 400: the README example ends `usable`
- [x] `AGENTS.md` rewritten for contributors
- [x] Plain names for modules and functions; old -> new in `CHANGELOG.md`
- [x] `test_drift_guards.py` split one file per module

## Agent: code

- [x] Code shape 4.5 stars (was 1.5); inputs per function still 3 stars (17.4% vs 15.4%)
- [x] `--version`
- [x] Source package tests pass (CI unpacks the sdist and runs them)
- [x] Release workflow runs the tests and checks tag == `__version__`
- [x] `eonrise --demo`: offline sample bundle shipped in the wheel, full report in a second
- [x] TestPyPI dry run: 0.9.0 uploaded, installed from test.pypi.org, `--demo` ran

## Agent: product

Trimmed 2026-10-13: a command-line tool is judged on its README in about 30 seconds, so brand
work waits until people use it (see After launch).

- [x] User docs: `docs/USAGE.md`; `tests/test_docs.py` keeps every doc in line with the code
- [x] CI badge
- [x] README rewritten (create-readme + readme-write gates pass); hero is a real brief
- [x] `examples/`: 2 live runs + the demo
- [x] `CITATION.cff` (a test keeps its version in line)
- [x] Repo description and topics

## Owner

- [x] Approve deleting 23 old branches and 65+ probe workflow runs
- [x] Register the trusted publisher on PyPI (TestPyPI done; same five fields, environment `pypi`)
- [x] Make the repo public, then turn on private vulnerability reporting and protect `main`
- [x] Same day: turn on GitHub Pages from `main` `/docs`. Until then the README's live map
  link (`superstos.github.io/Eonrise/demo/`) is a 404
- [x] Tag the first release (v0.9.0 on PyPI, 2026-10-14)

## After launch

- [ ] Brand page, logo (mark + wordmark, light/dark, 16px), social preview 1280x640
- [ ] Domain (`eonrise.dev` / `eonrise.app` free on 2026-10-12), once there is a site to host

- [ ] Cache: atomic writes, skip a corrupt file (`providers.py` cache read/write)
- [ ] Failed run gets its own exit code (today 2, same as bad flags)
- [ ] Budget split between rounds (400 is fully used on the README example)
- [ ] "Same field, missed by the word gate" lists unrelated papers via shared words
- [ ] `EONRISE_CACHE` to move the cache
- [ ] jscpd and semgrep scans
- [ ] Dependabot for Actions, pin actions to SHAs
- [ ] Rename output keys `harvest`/`unseen`/`corpus_*` with the next schema version
- [ ] Announce: launch post, where to post, "share your map" thread, good first issues
