from __future__ import annotations

from pathlib import Path

from .literature_coverage import WARN_BELOW


def _bullets(items) -> list[str]:
    return [f"- `{item}`" for item in items]


def _words(relations: list[str]) -> str:
    return ", ".join(x.replace("_", " ") for x in relations)


def _header(result: dict) -> list[str]:
    papers = result["papers"]
    return ["# Eonrise brief", "", f"**Question:** {result['question']}",
            f"**Root topic:** {result.get('root_topic', '')}",
            f"**Status:** {result['status']} — {result['stop_reason']}",
            f"**Evidence:** {len(papers)} papers kept of {result.get('retrieved_papers', len(papers))} retrieved"
            f" ({result.get('on_topic_papers', 0)} on topic), {len(result.get('concepts', []))} concepts"]


def _failure_notes(result: dict) -> list[str]:
    if result["status"] != "failed":
        return []
    lines = []
    errors = result.get("provider_errors") or []
    if not result.get("on_topic_papers") and result["papers"]:
        lines += ["", "**No retrieved paper was about this question. Every term below was "
                      "read out of a different literature — treat the map as a failed "
                      "search, not as a finding.**"]
    if errors and not result.get("papers") and not result.get("retrieved_papers"):
        # Not a thin literature — a broken run. Without the error text the brief blames
        # the field for what a socket timeout did.
        return lines + ["", "**This run retrieved nothing. The map below is empty because the "
                            "search failed, not because the literature is silent.**", ""] + _bullets(errors[:5])
    # Retrieved papers do not make provider errors disappear; the search can be both
    # off topic and degraded.
    return lines + (["", "**Provider errors:**", ""] + _bullets(errors[:5]) if errors else [])


def _warnings(result: dict) -> list[str]:
    lines = []
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
    return lines


def _grounded_map(result: dict) -> list[str]:
    lines = ["", "## Grounded map", ""]
    for relation, terms in result["coverage"].items():
        shown = ", ".join(terms[:3]) if terms else "not grounded yet"
        lines.append(f"- **{relation.replace('_', ' ').title()}:** {shown}")
    quotes = [t for t in result.get("limitations", []) if t.get("examples")]
    if quotes:
        # A limitation phrase is only worth as much as the sentence it came from.
        lines += ["", "## Stated limitations", ""]
        lines += [f'- **{t["text"]}** — "{t["examples"][0][:180]}"' for t in quotes[:3]]
    return lines


def _distant_papers(result: dict) -> list[str]:
    # The papers the gate set aside that carry the same shape. Distant fields are the
    # product; a brief that only showed the on-topic map hid them.
    harvested = result.get("harvest") or []
    lines: list[str] = []
    for heading, distant in (("Same shape, other fields", True), ("Same field, missed by the word gate", False)):
        group = [h for h in harvested if bool(h.get("distant")) is distant]
        if group:
            lines += ["", f"## {heading}", ""]
            lines += [f"- **{h['title']}** ({h.get('year') or 'n.d.'}, {h['field']}) — shares "
                      + ", ".join(h["shares"][:3]) for h in group[:5]]
    return lines


def _directions(result: dict) -> list[str]:
    by_dir: dict[str, list[str]] = {}
    for c in result.get("concepts", [])[1:9]:
        by_dir.setdefault(c.get("direction", "?"), []).append(c.get("label", ""))
    rows = [f"- **{d}:** " + ", ".join(by_dir[d][:4]) for d in ("up", "down", "sideways") if by_dir.get(d)]
    return ["", "## Concept directions", ""] + rows if by_dir else []


def _next_steps(result: dict) -> list[str]:
    lines = ["", "**Gaps:** " + _words(result["gaps"])] if result["gaps"] else []
    dormant = result.get("dormant_relations") or []
    if dormant:
        lines += ["", "**Not in this literature:** " + _words(dormant)
                  + " — two full rounds produced no candidate at all, so the run stopped "
                    "spending queries on it rather than calling it an unfilled gap."]
    if result["recommended_queries"]:
        lines += ["", "## Next searches", ""] + _bullets(result["recommended_queries"][:3])
    if result.get("distant_queries"):
        lines += ["", "## Searches toward other fields", ""] + _bullets(result["distant_queries"])
    return lines


def render_compact_markdown(result: dict) -> str:
    sections = (_header, _failure_notes, _warnings, _grounded_map, _distant_papers, _directions, _next_steps)
    return "\n".join(line for section in sections for line in section(result)) + "\n"


def _full_map(result: dict) -> list[str]:
    lines = ["# Eonrise research report", "", f"**Question:** {result['question']}",
             f"**Root topic:** {result.get('root_topic', '')}",
             f"**Agent:** {result.get('policy', {}).get('name', 'default')}",
             f"**Mode:** {result.get('mode', 'unknown')}",
             f"**Status:** {result['status']} — {result['stop_reason']}", "", "## Research map", ""]
    lines += [f"- **{relation.replace('_', ' ').title()}:** {', '.join(terms) if terms else 'not grounded yet'}"
              for relation, terms in result["coverage"].items()]
    lines += ["", "## Concept tree (single root)", ""]
    lines += [f"- `{'  ' * min(c.get('depth', 0), 4)}{c.get('label', '')}` ({c.get('direction', '')}, "
              f"w={c.get('weight', 0)}, n={c.get('support', 0)})" for c in result.get("concepts", [])[:30]]
    return lines + ["", "## Deep search routes", ""] + _bullets(result["recommended_queries"])


def _round_table(result: dict) -> list[str]:
    rounds = result.get("rounds") or []
    if not rounds:
        return []
    lines = ["", "## Search integrity", "",
             "| Round | Queries | New papers | On topic (total) | Gap queries | Gaps left |",
             "|---|---|---|---|---|---|"]
    for r in rounds:
        lines.append("| {} | {} | {} | {} | {} | {} |".format(
            r.get("round_number"), len(r.get("queries", [])), r.get("new_papers"),
            r.get("on_topic_papers", 0), len(r.get("gap_queries") or []),
            ", ".join(r.get("gaps", [])) or "none"))
    return lines


def _quoted_limitations(result: dict) -> list[str]:
    quotes = [t for t in result.get("limitations", []) if t.get("examples")]
    lines = ["", "## Stated limitations (quoted)", ""] if quotes else []
    return lines + [f'- **{t["text"]}** ({t["support"]} papers) — "{example[:220]}"'
                    for t in quotes for example in t["examples"][:2]]


def _evidence_list(result: dict) -> list[str]:
    return ["", "## Evidence", ""] + [
        f"- [{p['title']}]({p.get('url') or p.get('doi') or ''}) ({p.get('year') or 'n.d.'}, {p['provider']})"
        for p in result["papers"][:15]]


def render_markdown(result: dict) -> str:
    sections = (_full_map, _round_table, _quoted_limitations, _evidence_list)
    return "\n".join(line for section in sections for line in section(result)) + "\n"


def write_outputs(result: dict, output_dir: str | Path) -> None:
    import json
    path = Path(output_dir); path.mkdir(parents=True, exist_ok=True)
    (path / "research_map.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    (path / "report.md").write_text(render_compact_markdown(result), encoding="utf-8")
    (path / "internal_report.md").write_text(render_markdown(result), encoding="utf-8")
    (path / "graph.json").write_text(json.dumps(result["graph"], indent=2, ensure_ascii=False), encoding="utf-8")
