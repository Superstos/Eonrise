# Eonrise launch checklist

Everything between today's private repo and a public release people can adopt. Built from the
2026-10-12 audit: a fresh install, live runs, a secrets scan and a code-shape measure. Tick items
as they land. Remove or archive this file once the launch is done.

## Already settled

| Area | State | Evidence |
| --- | --- | --- |
| License | MIT, modern package metadata (PEP 639) | `LICENSE`, `pyproject.toml` |
| Community files | Code of conduct 2.1, security policy, contributing guide, issue and PR templates | `.github/`, repo root |
| Tests | 149 unit tests and the gauntlet (3/3) pass | `python -m unittest discover -s tests`, `python -m gauntlet.run` |
| CI | Green on Python 3.8 to 3.14, plus a build-install-run check of the wheel | `.github/workflows/ci.yml` |
| Dependencies | None at runtime | `pyproject.toml` |
| Git history | No secrets found (trufflehog: 0), author emails are GitHub noreply | all 72 commits, all branches |
| Names | PyPI `eonrise` free. GitHub user `eonrise` taken, `eonrise-dev` free. eonrise.com registered by someone; .dev, .app and .org returned "not registered" | checked 2026-10-12 |

## Your calls

- [ ] Keep the name "Eonrise"? A web search found no product with that name, but nobody has checked the trademark databases yet (see Identity).
- [ ] Buy a domain: eonrise.dev or eonrise.app were free on 2026-10-12.
- [ ] Where the project lives: your account (`Superstos/Eonrise`) or a new org such as `eonrise-dev`.
- [ ] Pick the logo direction from the options that come out of Identity.

## 1. Code blockers (before anyone outside can see the repo)

- [ ] **Keep API keys and emails out of the reports.** `ontology_router/providers.py:63` puts the full request URL into the error text, and that text is printed in the terminal and written into `report.md` and `research_map.json`. The URL carries the OpenAlex `api_key` and the `--email` address. Strip the query string from errors and add a test that a failing request with a fake key never writes the key anywhere. Then add "redact keys" to the provider field of `.github/ISSUE_TEMPLATE/bug.yml`, which today asks users to paste `provider_errors` into a public issue.
- [ ] **Rename the import package `ontology_router` to `eonrise`.** Today `pip install eonrise` works but `import eonrise` fails. This touches every import, the tests, `gauntlet/run.py`, the `eonrise` and `eonrise.cmd` shims, `pyproject.toml` and CI. It has to land before the first PyPI upload, because after that a rename breaks every user.
- [ ] **Let the README example finish.** On defaults (`--max-nodes 120`), `how does spaced repetition improve memory retention` stops after round 1 as `partial`, so gap repair never runs. With `--max-nodes 400` it ends `usable`, 5/5 relations, in 22s. Raise the default, or stop round 1 from spending the whole budget. Done when the README example ends `usable` on default settings.
- [ ] **Rewrite `AGENTS.md` for contributors' agents.** It calls the repo private and names the owner. Keep the research and delivery rules that apply to anyone.

## 2. Clean the GitHub repo (before making it public)

- [ ] Delete the 23 branches other than `main` (`probe/*`, `exp/*`, `autotest1`). Checked: the code on `exp/evolution-proof` is already on `main`; the others add only probe workflow files or nothing.
- [ ] Delete the 65+ probe workflow runs and the `teachme-eonrise-probe` artifact. On a public repo anyone can read every run log.
- [ ] Fill in the repo description, topics and website link (all empty today).

## 3. Identity

- [ ] **Trademark check** for "Eonrise" in the WIPO Global Brand Database, EUIPO and USPTO (software classes 9 and 42) before spending on a logo or domain.
- [ ] **Answer the brand questions before drawing anything.** Who the user believes they are, what outcome they already want, and how Eonrise credibly connects the two (saved post `Da4885cvSuE`). Then a signature symbol, a slogan, the one salient idea and a short story (staged questions, saved post `DbOHA_8DeqZ`). One page of answers.
- [ ] **Logo: a mark and a wordmark** as SVG, in light and dark versions, readable at 16px (favicon) and 64px (GitHub avatar). Pull 3 to 6 references from Brand New, LogoLounge and Identity Designed (`notes/design-sources/00-index.md` in the harness) before drawing. Seeds to test, not a direction: dawn (eon + rise), and the shape of a run (one root, branches up, down and sideways, one bridge to a distant field).
- [ ] **Two colors and one typeface**, written as tokens so the README images, the social card and the docs match.
- [ ] **Social preview image** (1280x640 PNG with logo, tagline and one sample map line), set in the repo settings. It is the image shown when the link is pasted into chat apps and social sites.
- [ ] **Tagline and PyPI description.** `pyproject.toml` says "Single-root, agent-budget research traversal with drift guards". The README already has the plain version: a problem half solved in your field is often already solved in another one.

## 4. First run and docs

- [ ] **Built-in offline demo**, for example `eonrise --demo` reading a sample bundle shipped inside the package, so a pip user sees a full report in a second with no network. Today the offline example needs `tests/fixtures/papers.json`, which the wheel does not include.
- [ ] **README top section:** logo, tagline, badges (CI, PyPI version, Python versions, license), a terminal recording of one real run, and one real report that shows a result from a distant field.
- [ ] **Example gallery:** 3 to 5 real runs from different fields in `examples/`. Use questions with technical wording (the README's own stated limit). Keep titles, links and the map; check each provider's terms before committing abstracts.
- [ ] **User docs:** the evidence-bundle format, the output schema (`research_map.json` carries `"version": 5`), the environment variables (`CROSSREF_EMAIL`, `OPENALEX_API_KEY`, `S2_API_KEY`, `CORE_API_KEY`), and everything saved under `~/.cache/eonrise/`, including that every question is saved to `memory.jsonl`, with the flag that turns each one off.
- [ ] **`CITATION.cff`** and a Zenodo DOI per release, so researchers can cite the tool. GitHub then shows a "Cite this repository" button.
- [ ] **"Who it is for, how it differs" section:** no LLM, no API key needed, no dependencies, and a gap stays empty instead of being made up. The comparison with tools users already know needs a research pass first, starting from the problem rather than from tool names.

## 5. Release plumbing

- [ ] Register `eonrise` as a pending trusted publisher on PyPI and create the `pypi` environment on GitHub. The release workflow has never run.
- [ ] Make the release workflow run the tests and check that the tag matches `__version__` before it publishes.
- [ ] Do a dry run on TestPyPI.
- [ ] Add `--version` (the bug template asks for the version, and the CLI cannot print it).
- [ ] Add the three gold fixtures to `MANIFEST.in`. Tests run from the source package fail with 5 errors today.
- [ ] Add `CHANGELOG.md` with user-facing changes; `docs/SPEC.md` keeps the engineering history.

## 6. Go public

- [ ] Make the repo public.
- [ ] Turn on private vulnerability reporting. `SECURITY.md` depends on it, and GitHub offers it only on public repos.
- [ ] Protect `main` so a merge needs CI to pass.
- [ ] Tag the first release and let the workflow publish it to PyPI.

## 7. Announce

- [ ] Launch post: the problem (the answer often sits in another field), one real example, and the one command to try it.
- [ ] Choose where to post after a research pass on where research-tool users actually gather.
- [ ] Decide on GitHub Discussions, label 3 to 5 `good first issue`s, and publish a short roadmap.
- [ ] Open a "share your map" thread so first users have an obvious way to reply.

## 8. After launch

- [ ] Write cache files atomically and skip a corrupt one. Today one half-written file crashes later runs with a traceback (`providers.py:37-38` and `:51`; reproduced).
- [ ] Split `run_agent` (`engine.py:155`, 264 lines, 118 branches) into plan, fetch and score steps. Code shape is 1.5/5 on the maintainability scale.
- [ ] Give a failed run its own exit code. It exits 2 today, the same code argparse uses for bad flags.
- [ ] Fix the "Same field, missed by the word gate" section. On "what makes an open source software project attract users and contributors after its first public release" it listed irrigation and bacteria-growth papers, and "heart failure" landed under Failure Mode through the shared word "failure".
- [ ] Let users move the cache: `~/.cache/eonrise` is fixed in `cli.py:57` (an `EONRISE_CACHE` variable, or the standard XDG one).
- [ ] Finish the audit: the duplicate-code and security scans did not run because jscpd and semgrep are missing on the audit PC.
- [ ] Turn on Dependabot for GitHub Actions and pin actions to commit SHAs (the OpenSSF Scorecard checks both).

## Ideas from running Eonrise on this launch

The run on "what makes an open source software project attract users and contributors after its
first public release" returned these titles from other fields:

- "Am I Teaching into the Void?" (online biology instructors facing silent students): a launch is silent by default too, so plan the first prompts that invite a reply (the share-your-map thread, good first issues).
- Structured teach-back discharge education (patients repeat the care plan back before leaving hospital): the install should end with one command whose result the user can read and explain back, which is the built-in demo.
- ARMS farm financial and crop production practices (a yearly survey of how farms actually run, used for policy): a short opt-in survey of how people use Eonrise, to steer the roadmap.
- Right atrial pacemaker lead thrombosis after rivaroxaban failure: not mapped; it matched on the word "failure".
