"""Check whether a model uses an Eonrise brief or throws its distant papers away as noise.

Gives the model a real brief and a user's problem, with and without the Eonrise skill
(`plugin/skills/eonrise/SKILL.md`), several times each, and counts how many distant fields
each answer turns into advice and how often it dismisses the results.

    python tools/agent_check.py --model haiku --runs 5
    python tools/agent_check.py --cli codex --model gpt-6-luna --effort high

Needs the `claude` or `codex` command line tool. Not part of the test suite: it calls a model.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "plugin" / "skills" / "eonrise" / "SKILL.md"
BRIEF = ROOT / "examples" / "written-instructions-new-workers.md"
TASK = ('A developer asks you: "My AI coding agents keep repeating mistakes I corrected in earlier '
        'sessions. Every session starts fresh and reads my written instructions. What should I '
        'change?" You ran Eonrise on the question. Its brief is below. Answer the developer in '
        'under 200 words, using whatever in the brief is useful.')
# The distant fields this brief offers, and the words that show an answer used one.
FIELDS = {
    "courts": r"\bjur(y|ies|or|ors)\b|courtroom",
    "nursing": r"\bnurs(e|es|ing)\b|clinical mistake",
    "adult learning": r"adult learn",
    "persuasion": r"persuasion",
    "learning design": r"active learning|FADE|computational thinking",
}
DISMISS = r"\bnoise\b|irrelevant|off.topic|unrelated (fields|papers|results)|not relevant|came from unrelated"


def score(answer: str) -> dict:
    """Which distant fields an answer uses, and whether it waves the results away."""
    used = [name for name, pattern in FIELDS.items() if re.search(pattern, answer, re.I)]
    return {"fields": used, "dismissed": bool(re.search(DISMISS, answer, re.I))}


def prompt(with_skill: bool) -> str:
    parts = [SKILL.read_text(encoding="utf-8")] if with_skill else []
    return "\n\n".join(parts + [TASK, "---", BRIEF.read_text(encoding="utf-8")])


def ask(cli: str, model: str, effort: str, text: str) -> str:
    if cli == "claude":
        command = ["claude", "-p", "--model", model, "--tools", ""] + (["--effort", effort] if effort else [])
        return subprocess.run(command, input=text, capture_output=True, text=True,
                              encoding="utf-8", timeout=600).stdout
    with tempfile.TemporaryDirectory() as tmp:
        answer = Path(tmp) / "answer.md"
        command = ["codex", "exec", "-m", model, "--skip-git-repo-check", "-s", "read-only",
                   "-o", str(answer), "-"] + (["-c", f"model_reasoning_effort={effort}"] if effort else [])
        subprocess.run(command, input=text, capture_output=True, text=True, encoding="utf-8",
                       timeout=600, cwd=tmp)
        return answer.read_text(encoding="utf-8") if answer.exists() else ""


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--cli", choices=["claude", "codex"], default="claude")
    p.add_argument("--model", default="haiku")
    p.add_argument("--effort", default="", help="reasoning effort, such as high")
    p.add_argument("--runs", type=int, default=5)
    p.add_argument("--save", type=Path, help="folder for the raw answers")
    args = p.parse_args()
    jobs = [(cond, i) for cond in ("plain", "skill") for i in range(args.runs)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        answers = list(pool.map(lambda job: ask(args.cli, args.model, args.effort, prompt(job[0] == "skill")), jobs))
    if args.save:
        args.save.mkdir(parents=True, exist_ok=True)
        for (cond, i), answer in zip(jobs, answers):
            (args.save / f"{cond}-{i + 1}.md").write_text(answer, encoding="utf-8")
    print(f"{args.cli} {args.model} {args.effort or 'default effort'}, {args.runs} runs each, {len(FIELDS)} distant fields in the brief")
    for cond in ("plain", "skill"):
        scores = [score(a) for (c, _), a in zip(jobs, answers) if c == cond]
        mean = sum(len(s["fields"]) for s in scores) / len(scores)
        two = sum(len(s["fields"]) >= 2 for s in scores)
        dismissed = sum(s["dismissed"] for s in scores)
        print(f"{cond:6} fields used per answer {mean:.1f} | answers using 2+ fields {two}/{len(scores)}"
              f" | answers dismissing results {dismissed}/{len(scores)}")


if __name__ == "__main__":
    main()
