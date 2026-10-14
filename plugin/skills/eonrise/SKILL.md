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

## 1. Run it

```bash
pip install eonrise
eonrise "the problem in plain words" --out eonrise-out
```

- Describe the problem, not a solution you already suspect. Naming a method only finds that method.
- Use everyday words. Leave out idioms and your own field's jargon: they pull results back
  into your field, or match the idiom literally.
- Deeper run when the first one is shallow: `--max-depth 30 --max-nodes 2000`.
- Offline sample, no network: `eonrise --demo --out eonrise-out`.

## 2. Read the brief

Open `eonrise-out/report.md`. Read in this order:

1. **Status.** `failed` means no paper was about the question: tell the user so and rephrase.
   Do not build on a failed map.
2. **Same shape, other fields.** The main reason to run Eonrise.
3. **Grounded map** and **Stated limitations**.
4. **Unfinished: saw at most ~N%.** The search is partial. An empty section is unsearched,
   not absent.
5. **Searches toward other fields** and **Next searches**: run the best one or two if the
   first pass is thin.

## 3. Map every distant item

For each paper or concept from another field, write one line:

> their problem -> what they did -> our version

Example, for "AI agents repeat mistakes I corrected in earlier sessions":

> jurors are new every trial and hear instructions once -> courts test which wording jurors
> follow -> test which wording of a rule changes the agent's behavior

Drop an item only after trying that line, and say in a few words why it failed
("shares only the word 'training'"). Titles alone are thin evidence: say when you only saw
the title.

## 4. Answer the user

Lead with the recommendation. Then the two or three strongest mappings, each with the field
and the paper. Then what you could not map, and how complete the search was.
