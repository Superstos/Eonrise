# Contributing to Eonrise

I maintain Eonrise solo. Changes should stay small, measurable, and easy for one person to review.

## Setup

Requires Python `>=3.11`. Standard library only at runtime.

```bash
pip install .
```

## Checks

```bash
python -m unittest discover -s tests -v
python -m gauntlet.run --quick
python -m gauntlet.run
```

## PR scope

- One feature or fix per change.
- Do not redesign the architecture for style.
- Do not add dependencies, services, or unrelated tooling.
- Preserve evidence-grounded behavior and explicit known limits.

Experimental ideas need measurement: baseline, changed behavior, and why the result should be trusted. Rejected experiments should be recorded in `docs/SPEC.md` rather than hidden.
