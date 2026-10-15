---
name: eonrise
description: Find where other research fields already solved the user's problem, and turn those distant papers into concrete ideas. Use for design, invention, architecture, strategy or research questions where an answer from another field could help, and whenever an Eonrise brief (report.md) is in front of you.
---

# Eonrise

Eonrise searches open scholarly sources for a question, then walks outward into broader,
related and narrower fields. Its point is the papers from fields far from the question: they
often solved the same problem years ago under another name.

**A paper from a distant field is the product, not a search error.** Never call a result
noise, off-topic or irrelevant before you have tried to map it (step 3).

## 0. What you need

- **Python 3.11 or newer.** Check with `python --version` first. On an older Python, pip says
  `Could not find a version that satisfies the requirement eonrise (from versions: none)`:
  that means the wrong Python, not a missing package. On Windows, `py -3.12` picks a newer one.
- **Network access** to the scholarly APIs. If your sandbox blocks the network, say so to the
  user. `eonrise --demo` works offline but answers its own sample question, not the user's.
- **A research question.** Sources are scholarly papers. A question that needs other sources
  (films to watch, products, code repositories) usually ends `failed` or finds little; say so
  instead of stretching the result.

## 1. Run it, inside the project folder

Everything stays in the folder you work in: the virtual environment, the output, and the
cache of past runs.

```bash
python -m venv .venv                  # Python 3.11+
.venv/bin/python -m pip install eonrise
.venv/bin/python -m eonrise "the problem in plain words" --out eonrise-out --cache-dir .eonrise
```

On Windows: `py -3.12 -m venv .venv`, then `.venv\Scripts\python.exe` in place of
`.venv/bin/python`.

`--cache-dir`, the output `README.md` and the *What they did* lines need 0.10.0 or newer. If
`python -m eonrise --help` does not list `--cache-dir`, run
`.venv/bin/python -m pip install -U eonrise`.

- `--cache-dir .eonrise` keeps every store inside the project. Without it, Eonrise writes to
  `~/.cache/eonrise`, outside the folder. `EONRISE_CACHE_DIR` does the same as the flag.
- Use the command line and its flags only. Never import Eonrise's private functions to change
  where it writes; `eonrise --help` lists every option.
- Describe the problem, not a solution you already suspect. Naming a method only finds that method.
- Use everyday words. Leave out idioms and your own field's jargon: they pull results back
  into your field, or match the idiom literally. A word with two senses ("train" a model,
  "train" staff) needs the other words to fix its sense.
- Deeper run when the first one is shallow: `--max-depth 30 --max-nodes 2000`.

## 2. Read the brief

Open `eonrise-out/report.md`. `eonrise-out/README.md` says what every file, field and number
means: read it before you open `research_map.json`, never guess the fields.
(`on_topic_papers` is a count; the IDs are in `on_topic_paper_ids`.)

Read the brief in this order:

1. **Status.** `failed` has two causes. If the brief lists provider errors, the sources failed:
   retry later or pick others with `--providers`. Otherwise no paper was about the question:
   tell the user and rephrase. Do not build on a failed map.
2. **Same shape, other fields.** The main reason to run Eonrise. Each paper carries
   *What they did*, one sentence from its abstract.
3. **Grounded map** and **Stated limitations**.
4. **Unfinished: saw at most ~N%.** The share of what *these queries* can reach, not of all
   research. A broader follow-up run can show a lower share while finding more papers, so
   compare paper counts between runs, never the percentages.
5. **Searches toward other fields** and **Next searches**: run the best one or two if the
   first pass is thin.

A paper marked *from an earlier run* came from the local store, not a fresh search.

## 3. Map every distant item

**Confirmation bias warning:** Don't lead your search with an answer you already suspect.
Don't reject unfamiliar findings before checking for a meaningful connection or similar pattern.
But don't force connections where none exist. Both premature rejection and forced connections
can reinforce confirmation bias and create an echo chamber.

For each paper or concept from another field, write one line:

> their problem -> what they did -> our version

Example, for "AI agents repeat mistakes I corrected in earlier sessions":

> jurors are new every trial and hear instructions once -> courts test which wording jurors
> follow -> test which wording of a rule changes the agent's behavior

Drop an item only after trying that line, and say in a few words why it failed
("shares only the word 'training'"). When *What they did* says "no abstract, title only",
say you only saw the title.

## 4. Answer the user

Lead with the recommendation. Then the two or three strongest mappings, each with the field
and the paper. Then what you could not map, and how complete the search was.
