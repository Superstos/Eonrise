# Example runs

Real briefs, copied unedited from `report.md`. Each one shows the question, what Eonrise found
in the question's own field, and the papers from other fields that share its shape.

| Brief | Question | Run | Other fields it found |
| --- | --- | --- | --- |
| [written-instructions-new-workers.md](written-instructions-new-workers.md) | how can written instructions prevent the same mistakes from repeating when every worker is new | live, 2026-10-13, 249 papers retrieved | jury instructions (law), clinical mistakes in nursing training |
| [plans-that-keep-growing.md](plans-that-keep-growing.md) | why do rules and plans keep growing in scope without being finished or removed | live, 2026-10-13, 407 papers retrieved | corporate planning, city planning |
| [demo-analogous-solutions.md](demo-analogous-solutions.md) | how can a system retrieve analogous solutions to a problem from distant research fields | `eonrise --demo`, offline | link prediction in knowledge networks |

The two live runs used `--max-nodes 220 --max-depth 6 --down-weight 1.5 --sideways-weight 1.5`
on the default sources. A live run today returns different papers: the sources change daily.
