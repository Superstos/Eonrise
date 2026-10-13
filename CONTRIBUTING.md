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
python -m benchmarks.run --quick
python -m benchmarks.run
```

## PR scope

- One feature or fix per change.
- Do not redesign the architecture for style.
- Do not add dependencies, services, or unrelated tooling.
- Preserve evidence-grounded behavior and explicit known limits.

`tests/test_docs.py` fails when a doc names a flag, file or environment variable the code no longer has; fix the doc in the same change.

Experimental ideas need measurement: baseline, changed behavior, and why the result should be trusted. Rejected experiments should be recorded in `docs/SPEC.md` rather than hidden.
