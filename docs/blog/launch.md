---
title: Finding my answers in fields I never studied
---

# Finding my answers in fields I never studied

I work with AI coding agents most of the day, and somewhere along the way I got obsessed with
what I call AIX. It's UX, but for the person working alongside an AI instead of clicking
through an app.

The agents are fast. Too fast, sometimes. They search, open files, retry and search again, and
every one of those steps piles more text into their working memory (people call it the
"context") until the useful part is buried and we've both lost time.

So I tried fixing it myself. I'd get an idea, feel clever for about an hour, then stumble on a
paper from some field I'd never heard of that had solved it years ago. Other times the paper
had tested my exact idea and shown, with data, that it doesn't work. After enough of these I
stopped calling it bad luck. If somebody has already done the thinking, I want to read it
before I start, from every field, with the evidence attached. Eonrise is the tool I built for
that.

## Same problem, different name

Search engines match words, so you search with your field's vocabulary and get your field's
answers back. A problem that feels brand new to me can be decades old in nursing or ecology,
filed under a name I'd never guess.

Eonrise starts from a question in plain words. It reads what comes back, picks out the
concepts, and searches again from each of them (broader, sideways, narrower) until it reaches
fields that share the shape of the problem even when they don't share a single keyword.

## One question I really had

Here it is, word for word: *how can written instructions prevent the same mistakes from
repeating when every worker is new?*

My "new worker" is an AI agent. Each session starts from zero, reads my instructions and, now
and then, repeats the mistake I corrected yesterday.

The first field Eonrise sent me to was courtrooms. Every trial seats a jury of strangers who
have to follow instructions they hear once, and researchers try different wordings on mock
juries to see what changes. One 2023 study found that a state's new model instruction made
jurors more confident of guilt.

It also turned up nursing schools, where people study what students hope to learn from their
clinical mistakes, and the old adult-learning research on how grown-ups take in instructions.
I wouldn't have searched any of these.

## Eighteen steps out

Then I ran the same question much deeper, out to 1,950 concepts and 20 levels. Eighteen steps
from where I started, the map reached a memory-research term I didn't know, **proactive interference**,
which is when what you learned earlier gets in the way of what you're learning now, like my
agents' old instructions fighting the new ones.

A 2008 paper sits right there in the map, *"Testing during study insulates against the buildup
of proactive interference"*. Quizzing people between chunks of material cut the interference.
Would quizzing an agent between steps beat handing it another page of rules? I want to find
out.

You can click through the whole map yourself in the
[live concept map](https://superstos.github.io/Eonrise/demo/).

![Map of 1,950 concepts one run reached from a question about written instructions](../assets/concept-map.png)

## How it runs

It queries open scholarly sources (OpenAlex, Crossref and a couple more, no API key needed),
pulls concepts out of the papers, and keeps the papers that back each one. At the end it
writes a short brief with what it found, what's still missing, and which papers from *other*
fields have the same shape as your problem.

## Pointing it at itself

Eonrise has to decide when a search has found enough. Stop too early and you miss papers.
Running long is safer, but the last rounds mostly bring back things you already have.

So I asked Eonrise how other fields handle that, and it sent me to ecology. Biologists can't
catch every animal in a forest, so they estimate how many species they *haven't* seen from how
often the same ones get caught twice. Legal teams reviewing documents for a lawsuit use the
same math, and so do some software testers.

I built it in and tested it on simulated searches where I knew the real answer. As a stop rule
it lost. It stopped too early and found less. It did one job well, though, spotting when a
search has clearly missed a lot, so I kept that part and every brief now carries a line like
"this run saw at most ~40% of what its searches can reach". An empty section then reads as
"not searched yet" instead of "nothing exists".

The failed ideas are written down too, in the repo's
[design notes](https://github.com/Superstos/Eonrise/blob/main/docs/SPEC.md), next to the ones
that shipped.

## Try it

```bash
pip install eonrise
eonrise --demo --out output
eonrise "your question in plain words" --out output
```

The demo runs offline in about a second. Real runs need no account and no key, and the code is
on [GitHub](https://github.com/Superstos/Eonrise).

I'm not a scientist, just someone who got tired of reinventing things, so if you run it on
your own problem, tell me which field it sent you to.
