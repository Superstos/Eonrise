from __future__ import annotations

from pathlib import Path

from .literature_coverage import WARN_BELOW


def render_compact_markdown(result: dict) -> str:
    lines = ["# Eonrise brief", "", f"**Question:** {result['question']}",
             f"**Root topic:** {result.get('root_topic', '')}",
             f"**Status:** {result['status']} — {result['stop_reason']}",
             f"**Evidence:** {len(result['papers'])} papers kept of {result.get('retrieved_papers', len(result['papers']))} retrieved"
             f" ({result.get('on_topic_papers', 0)} on topic), {len(result.get('concepts', []))} concepts"]
    errors = result.get("provider_errors") or []
    if result["status"] == "failed" and not result.get("on_topic_papers") and result["papers"]:
        lines.extend(["", "**No retrieved paper was about this question. Every term below was "
                          "read out of a different literature — treat the map as a failed "
                          "search, not as a finding.**"])
    if result["status"] == "failed" and errors and not result.get("papers") and not result.get("retrieved_papers"):
        # Not a thin literature — a broken run. Without the error text the brief blames
        # the field for what a socket timeout did.
        lines.extend(["", "**This run retrieved nothing. The map below is empty because the "
                          "search failed, not because the literature is silent.**", ""])
        lines.extend(f"- `{e}`" for e in errors[:5])
    elif result["status"] == "failed" and errors:
        # Retrieved papers do not make provider errors disappear; the search can be both
        # off topic and degraded.
        lines.extend(["", "**Provider errors:**", ""])
        lines.extend(f"- `{e}`" for e in errors[:5])
    down = result.get("providers_down") or []
    if down and result["status"] != "failed":
        # A run that lost OpenAlex has no keywords and few abstracts. Reading the map
        # without knowing that is how a degraded run passes for a thin literature.
        lines.append(f"**Degraded:** {', '.join(down)} answered nothing this run — "
                     "expect fewer abstracts, no keywords and no topic hierarchy.")
    unseen = result.get("unseen") or {}
    if unseen and unseen.get("found_share", 1) < WARN_BELOW:
        # Chao2 is a lower bound on what is out there, so this share is an upper bound on
        # what was found. When it is low, the true figure is lower still.
        lines.append(f"**Unfinished:** {unseen['singletons']} of {unseen['observed']} on-topic papers turned up "
                     f"for one query only, so this run saw at most ~{round(100 * unseen['found_share'])}% of what "
                     f"its queries can reach (Chao2 ≈ {round(unseen['estimated_total'])}). Treat an empty "
                     "relation as unsearched, not absent.")
    lines.extend(["", "## Grounded map", ""])
    for relation, terms in result["coverage"].items():
        label = relation.replace("_", " ").title(); shown = ", ".join(terms[:3]) if terms else "not grounded yet"; lines.append(f"- **{label}:** {shown}")
    quotes = [t for t in result.get("limitations", []) if t.get("examples")]
    if quotes:
        # A limitation phrase is only worth as much as the sentence it came from.
        lines.extend(["", "## Stated limitations", ""])
        for term in quotes[:3]:
            lines.append(f'- **{term["text"]}** — "{term["examples"][0][:180]}"')
    harvested = result.get("harvest") or []
    if harvested:
        # The papers the gate set aside that carry the same shape. Distant fields are the
        # product; a brief that only showed the on-topic map hid them.
        for heading, group in (("Same shape, other fields", [h for h in harvested if h.get("distant")]),
                               ("Same field, missed by the word gate", [h for h in harvested if not h.get("distant")])):
            if group:
                lines.extend(["", f"## {heading}", ""])
                lines.extend(f"- **{h['title']}** ({h.get('year') or 'n.d.'}, {h['field']}) — shares "
                             + ", ".join(h["shares"][:3]) for h in group[:5])
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
    dormant = result.get("dormant_relations") or []
    if dormant:
        lines.extend(["", "**Not in this literature:** " + ", ".join(x.replace("_", " ") for x in dormant)
                      + " — two full rounds produced no candidate at all, so the run stopped "
                        "spending queries on it rather than calling it an unfilled gap."])
    if result["recommended_queries"]:
        lines.extend(["", "## Next searches", ""]); lines.extend(f"- `{q}`" for q in result["recommended_queries"][:3])
    if result.get("distant_queries"):
        lines.extend(["", "## Searches toward other fields", ""])
        lines.extend(f"- `{q}`" for q in result["distant_queries"])
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
    rounds = result.get("rounds") or []
    if rounds:
        lines.extend(["", "## Search integrity", "",
                      "| Round | Queries | New papers | On topic (total) | Gap queries | Gaps left |",
                      "|---|---|---|---|---|---|"])
        for r in rounds:
            lines.append("| {} | {} | {} | {} | {} | {} |".format(
                r.get("round_number"), len(r.get("queries", [])), r.get("new_papers"),
                r.get("on_topic_papers", 0), len(r.get("gap_queries") or []),
                ", ".join(r.get("gaps", [])) or "none"))
    quotes = [t for t in result.get("limitations", []) if t.get("examples")]
    if quotes:
        lines.extend(["", "## Stated limitations (quoted)", ""])
        for term in quotes:
            for example in term["examples"][:2]:
                lines.append(f'- **{term["text"]}** ({term["support"]} papers) — "{example[:220]}"')
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
