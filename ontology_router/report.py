from __future__ import annotations

from pathlib import Path


def render_compact_markdown(result: dict) -> str:
    lines = ["# Eonrise brief", "", f"**Question:** {result['question']}",
             f"**Root topic:** {result.get('root_topic', '')}",
             f"**Status:** {result['status']} — {result['stop_reason']}",
             f"**Evidence:** {len(result['papers'])} papers, {len(result.get('concepts', []))} concepts",
             "", "## Grounded map", ""]
    for relation, terms in result["coverage"].items():
        label = relation.replace("_", " ").title(); shown = ", ".join(terms[:3]) if terms else "not grounded yet"; lines.append(f"- **{label}:** {shown}")
    concepts = result.get("concepts", [])
    if concepts:
        by_dir: dict[str, list[str]] = {}
        for c in concepts[1:9]:
            by_dir.setdefault(c.get("direction", "?"), []).append(c.get("label", ""))
        if by_dir:
            lines.extend(["", "## Concept directions", ""])
            for direction in ("up", "down", "sideways"):
                if by_dir.get(direction):
                    lines.append(f"- **{direction}:** " + ", ".join(by_dir[direction][:4]))
    if result["gaps"]: lines.extend(["", "**Gaps:** " + ", ".join(x.replace("_", " ") for x in result["gaps"])])
    if result["recommended_queries"]:
        lines.extend(["", "## Next searches", ""]); lines.extend(f"- `{q}`" for q in result["recommended_queries"][:3])
    return "\n".join(lines) + "\n"


def render_markdown(result: dict) -> str:
    lines = ["# Eonrise research report", "", f"**Question:** {result['question']}",
             f"**Root topic:** {result.get('root_topic', '')}",
             f"**Agent:** {result.get('policy', {}).get('name', 'default')}",
             f"**Mode:** {result.get('mode', 'unknown')}",
             f"**Status:** {result['status']} — {result['stop_reason']}", "", "## Research map", ""]
    for relation, terms in result["coverage"].items(): lines.append(f"- **{relation.replace('_', ' ').title()}:** {', '.join(terms) if terms else 'not grounded yet'}")
    lines.extend(["", "## Concept tree (single root)", ""])
    for c in result.get("concepts", [])[:30]:
        lines.append(f"- `{'  ' * min(c.get('depth', 0), 4)}{c.get('label', '')}` ({c.get('direction', '')}, w={c.get('weight', 0)}, n={c.get('support', 0)})")
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
