from __future__ import annotations

from pathlib import Path


def render_compact_markdown(result: dict) -> str:
    lines = ["# Eonrise brief", "", f"**Question:** {result['question']}", f"**Status:** {result['status']} — {result['stop_reason']}", f"**Evidence:** {len(result['papers'])} papers", "", "## Grounded map", ""]
    for relation, terms in result["coverage"].items():
        label = relation.replace("_", " ").title(); shown = ", ".join(terms[:3]) if terms else "not grounded yet"; lines.append(f"- **{label}:** {shown}")
    if result["gaps"]: lines.extend(["", "**Gaps:** " + ", ".join(x.replace("_", " ") for x in result["gaps"])])
    if result["recommended_queries"]:
        lines.extend(["", "## Next searches", ""]); lines.extend(f"- `{q}`" for q in result["recommended_queries"][:3])
    return "\n".join(lines) + "\n"


def render_markdown(result: dict) -> str:
    lines = ["# Eonrise research report", "", f"**Question:** {result['question']}", f"**Mode:** {result.get('mode', 'unknown')}", f"**Status:** {result['status']} — {result['stop_reason']}", "", "## Research map", ""]
    for relation, terms in result["coverage"].items(): lines.append(f"- **{relation.replace('_', ' ').title()}:** {', '.join(terms) if terms else 'not grounded yet'}")
    lines.extend(["", "## Deep search routes", ""]); lines.extend(f"- `{q}`" for q in result["recommended_queries"])
    lines.extend(["", "## Evidence", ""])
    for paper in result["papers"][:15]: lines.append(f"- [{paper['title']}]({paper.get('url') or paper.get('doi') or ''}) ({paper.get('year') or 'n.d.'}, {paper['provider']})")
    return "\n".join(lines) + "\n"


def write_outputs(result: dict, output_dir: str | Path) -> None:
    import json
    path = Path(output_dir); path.mkdir(parents=True, exist_ok=True)
    (path / "research_map.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    (path / "report.md").write_text(render_compact_markdown(result), encoding="utf-8")
    (path / "internal_report.md").write_text(render_markdown(result), encoding="utf-8")
    (path / "graph.json").write_text(json.dumps(result["graph"], indent=2, ensure_ascii=False), encoding="utf-8")
