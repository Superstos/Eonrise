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
- [ ] `--version`
- [ ] Source package tests pass (gold fixtures and `benchmarks/` missing from `MANIFEST.in`)
- [ ] Release workflow runs the tests and checks tag == `__version__`
- [ ] `eonrise --demo`: offline sample bundle shipped in the wheel, full report in a second
- [ ] TestPyPI dry run

## Agent: product

- [ ] One brand page: who it is for, what they want, the one idea, tagline
- [ ] Logo drafts (mark + wordmark, light/dark, readable at 16px), 2 colors, 1 typeface
- [ ] Social preview image 1280x640
- [ ] README top: logo, badges, recording of a real run, one distant-field result
- [ ] `examples/`: 3-5 real runs from different fields
- [ ] User docs: bundle format, output schema, env vars, what is saved under `~/.cache/eonrise/`
- [ ] `CITATION.cff`
- [ ] Repo description, topics, website link

## Owner

- [ ] Buy a domain (`eonrise.dev` / `eonrise.app` free on 2026-10-12)
- [ ] Pick a logo direction from the drafts
- [ ] Approve deleting 23 old branches and 65+ probe workflow runs
- [ ] Register the PyPI trusted publisher (agent gives the clicks)
- [ ] Make the repo public, then turn on private vulnerability reporting and protect `main`
- [ ] Tag the first release

## After launch

- [ ] Cache: atomic writes, skip a corrupt file (`providers.py` cache read/write)
- [ ] Failed run gets its own exit code (today 2, same as bad flags)
- [ ] Budget split between rounds (400 is fully used on the README example)
- [ ] "Same field, missed by the word gate" lists unrelated papers via shared words
- [ ] `EONRISE_CACHE` to move the cache
- [ ] jscpd and semgrep scans
- [ ] Dependabot for Actions, pin actions to SHAs
- [ ] Rename output keys `harvest`/`unseen`/`corpus_*` with the next schema version
- [ ] Announce: launch post, where to post, "share your map" thread, good first issues
