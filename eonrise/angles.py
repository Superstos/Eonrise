"""Merges several runs of one problem asked from different angles, and shows whether the angles differ."""
from __future__ import annotations

import json
from pathlib import Path


def read_questions(path: str) -> list[str]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def _angle(folder: Path) -> dict:
    data = json.loads((folder / "research_map.json").read_text(encoding="utf-8"))
    papers = data.get("papers") or []
    return {"folder": folder.name, "question": data.get("question", ""), "root_topic": data.get("root_topic", ""),
            "status": data.get("status", ""),
            "titles": {(p.get("title") or "").strip().lower() for p in papers},
            "fields": {f for p in papers for f in (p.get("fields") or [])[:1] if isinstance(f, str)}}


def merge(folders: list[Path]) -> dict:
    """Per angle: papers, papers no other angle found, and fields no earlier angle reached."""
    angles = [_angle(f) for f in folders if (f / "research_map.json").exists()]
    seen_fields: set[str] = set()
    rows = []
    for a in angles:
        others = set().union(*(b["titles"] for b in angles if b is not a))
        new_fields = sorted(a["fields"] - seen_fields)
        seen_fields |= a["fields"]
        rows.append({"folder": a["folder"], "question": a["question"], "root_topic": a["root_topic"],
                     "status": a["status"], "papers": len(a["titles"]),
                     "only_here": len(a["titles"] - others), "new_fields": new_fields})
    papers = set().union(*(a["titles"] for a in angles)) if angles else set()
    return {"angles": rows, "papers": len(papers), "fields": sorted(seen_fields)}


def write_merge(out: Path, folders: list[Path]) -> dict:
    merged = merge(folders)
    (out / "angles.json").write_text(json.dumps(merged, indent=2), encoding="utf-8")
    lines = ["# Angles", "", f"{len(merged['angles'])} angles, {merged['papers']} distinct papers, "
             f"{len(merged['fields'])} fields.", "",
             "| Angle | Root topic | Papers | Only here | New fields |", "|---|---|---|---|---|"]
    for r in merged["angles"]:
        lines.append(f"| {r['folder']} | {r['root_topic']} | {r['papers']} | {r['only_here']} | {len(r['new_fields'])} |")
    last = merged["angles"][-1]["new_fields"] if merged["angles"] else []
    lines += ["", f"Last angle added {len(last)} new fields. Few new fields over the last angles means the "
              "fields are saturating; add angles while they still bring new ones."]
    (out / "angles.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return merged
