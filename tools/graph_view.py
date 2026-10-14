"""Draw a run's concept map as an interactive network page, and optionally a still image.

    python tools/graph_view.py output/research_map.json --out graph.html
    python tools/graph_view.py output/research_map.json --out graph.html --png docs/assets/concept-map.png

Two kinds of links: the tree (each concept to the concept it grew from) and shared papers
(two concepts supported by the same papers). The page lays them out with ForceAtlas2, finds
clusters with Louvain, and lets you switch links, colours and search. It loads graphology from
a CDN; the package itself stays free of dependencies. --png saves a still in headless Chrome.
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import os
import shutil
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

LIBS = "".join(f'<script src="https://cdn.jsdelivr.net/npm/{path}"></script>' for path in (
    "graphology@0.25.4/dist/graphology.umd.min.js",
    "graphology-library@0.8.0/dist/graphology-library.min.js",
))

# A paper backing more concepts than this says little about any pair of them.
MAX_PAPER_FANOUT = 60
MIN_SHARED_PAPERS = 2

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Eonrise concept map</title>
<style>
  :root { --bg: #111317; --panel: #181b21; --line: #2a2f38; --text: #d4d6db; --dim: #8a8f99; }
  html, body { margin: 0; height: 100%; background: var(--bg); color: var(--text);
    font: 13px/1.45 system-ui, sans-serif; overflow: hidden; }
  canvas { display: block; cursor: grab; }
  #title { position: fixed; left: 20px; top: 16px; max-width: 55%; font-size: 15px; }
  #title small { display: block; color: var(--dim); font-size: 12px; margin-top: 3px; }
  #panel { position: fixed; right: 16px; top: 16px; width: 270px; background: var(--panel);
    border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px; }
  #panel h4 { margin: 10px 0 4px; font-size: 11px; font-weight: 600; color: var(--dim);
    text-transform: uppercase; letter-spacing: .6px; }
  #panel h4:first-child { margin-top: 0; }
  .seg { display: flex; border: 1px solid var(--line); border-radius: 6px; overflow: hidden; }
  .seg button { flex: 1; background: none; border: 0; color: var(--dim); padding: 5px 0;
    font: inherit; cursor: pointer; }
  .seg button + button { border-left: 1px solid var(--line); }
  .seg button.on { background: #262a33; color: var(--text); }
  .hint { color: var(--dim); font-size: 12px; margin-top: 5px; }
  input { width: 100%; box-sizing: border-box; background: var(--bg); color: var(--text);
    border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px; font: inherit; }
  #panel { max-height: calc(100vh - 34px); overflow-y: auto; box-sizing: border-box; }
  #detail { display: none; border-top: 1px solid var(--line); margin-top: 12px; padding-top: 10px; }
  #detail h3 { margin: 0 0 2px; font-size: 15px; font-weight: 600; }
  #detail .meta, #detail .crumbs { color: var(--dim); font-size: 12px; }
  #detail a { color: #b9c4d6; text-decoration: none; }
  #detail a:hover { text-decoration: underline; }
  #detail .go { cursor: pointer; color: #b9c4d6; }
  #detail ol { padding-left: 18px; margin: 4px 0; }
  #detail li { margin-bottom: 7px; }
  #detail summary { cursor: pointer; color: var(--dim); font-size: 12px; }
  #detail p { margin: 4px 0; font-size: 12px; color: #a9adb6; }
  #info { position: fixed; left: 20px; bottom: 16px; max-width: 420px; color: var(--dim); }
  #info b { color: var(--text); font-weight: 600; }
  #busy { position: fixed; inset: 0; display: grid; place-items: center; color: var(--dim);
    pointer-events: none; }
  body.still #panel, body.still #info { display: none; }
</style>
__LIBS__</head>
<body><div id="title"></div><canvas id="map"></canvas><div id="busy">Laying out...</div>
<div id="panel">
  <h4>Links</h4>
  <div class="seg" data-key="links"><button data-v="tree">Tree</button><button data-v="shared">Shared papers</button><button data-v="both">Both</button></div>
  <div class="hint">Tree: each concept to the one it grew from. Shared papers: two concepts the same papers support.</div>
  <h4>Colour</h4>
  <div class="seg" data-key="color"><button data-v="cluster">Cluster</button><button data-v="direction">Direction</button><button data-v="depth">Depth</button></div>
  <div class="hint" id="colorHint"></div>
  <h4>Find</h4>
  <input id="find" placeholder="a concept, then Enter">
  <div id="detail"></div>
</div>
<div id="info">Hover a concept to see what it connects to; click it for its papers. Scroll to zoom, drag to move.</div>
<script>
const DATA = __DATA__;
DATA.byId = Object.fromEntries(DATA.nodes.map(n => [n.id, n]));
const lib = graphologyLibrary;
const still = location.hash === "#still";
if (still) document.body.classList.add("still");
const state = { links: "both", color: "cluster" };
const PALETTE = ["#8da0b3", "#b8a27c", "#93a890", "#a8909e", "#9590b3", "#80a3a1", "#b39581",
  "#a1a08a", "#7f94a9", "#a7a7bb", "#9aa88a", "#b09a9a"];
const DIRECTION = { root: "#ece6da", up: "#c2a878", sideways: "#8d9bb0", down: "#8fae94" };
const HINTS = {
  cluster: "Groups the links pull together (Louvain). A colour is a neighbourhood, not a field.",
  direction: "Ochre: broader than its parent. Slate: related. Sage: narrower.",
  depth: "Light: close to your question. Dark: many steps away (up to " + DATA.maxDepth + ")."
};
const cache = {};

function build(mode) {
  if (cache[mode]) return cache[mode];
  const g = new graphology.Graph();
  DATA.nodes.forEach((n, i) => g.addNode(n.id, { ...n, x: Math.cos(i) * Math.sqrt(i), y: Math.sin(i) * Math.sqrt(i) }));
  const add = (s, t, kind, w) => { if (s !== t && !g.hasEdge(s, t) && !g.hasEdge(t, s)) g.addEdge(s, t, { kind, weight: w }); };
  if (mode !== "shared") DATA.tree.forEach(([s, t]) => add(s, t, "tree", 1));
  if (mode !== "tree") DATA.shared.forEach(([s, t, w]) => add(s, t, "shared", Math.min(w, 5) / 2));
  lib.layoutForceAtlas2.assign(g, { iterations: 700, getEdgeWeight: "weight", settings: {
    ...lib.layoutForceAtlas2.inferSettings(g), barnesHutOptimize: true, strongGravityMode: true,
    gravity: 0.5, scalingRatio: 8, edgeWeightInfluence: 1 } });
  const community = lib.communitiesLouvain(g, { getEdgeWeight: "weight", resolution: 1 });
  const size = {};
  Object.values(community).forEach(c => size[c] = (size[c] || 0) + 1);
  const rank = Object.keys(size).sort((a, b) => size[b] - size[a]);
  const hub = {};
  g.forEachNode((id, a) => { const c = community[id];
    if (a.depth > 0 && (!hub[c] || g.degree(id) > g.degree(hub[c]))) hub[c] = id; });
  return cache[mode] = { g, community, rank, hubs: new Set(rank.slice(0, 16).map(c => hub[c])) };
}

const canvas = document.getElementById("map"), ctx = canvas.getContext("2d");
const dpr = window.devicePixelRatio || 1;
let W, H, view = { k: 1, x: 0, y: 0 }, cur, hover = null, selected = null;

function resize() {
  W = innerWidth; H = innerHeight;
  canvas.width = W * dpr; canvas.height = H * dpr;
  canvas.style.width = W + "px"; canvas.style.height = H + "px";
}
function fit() {
  const xs = cur.g.mapNodes((_, a) => a.x), ys = cur.g.mapNodes((_, a) => a.y);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const right = still ? 40 : 320;
  view.k = Math.min((W - 40 - right) / (x1 - x0), (H - 110) / (y1 - y0));
  view.x = (W - right + 40) / 2 - (x0 + x1) / 2 * view.k;
  view.y = (H + 50) / 2 - (y0 + y1) / 2 * view.k;
}
const sx = a => a.x * view.k + view.x, sy = a => a.y * view.k + view.y;
function colorOf(id, a) {
  if (a.depth === 0) return DIRECTION.root;
  if (state.color === "direction") return DIRECTION[a.direction] || DIRECTION.sideways;
  if (state.color === "depth") {
    const t = a.depth / DATA.maxDepth, mix = (p, q) => Math.round(p + (q - p) * t);
    return "rgb(" + mix(222, 70) + "," + mix(214, 82) + "," + mix(196, 102) + ")";
  }
  return PALETTE[cur.rank.indexOf(String(cur.community[id])) % PALETTE.length];
}
const radius = id => id === "c0" ? 7 : 1.4 + Math.sqrt(cur.g.degree(id)) * 0.75;

function draw() {
  const g = cur.g, focus = hover || selected, near = focus ? new Set(g.neighbors(focus).concat(focus)) : null;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = "#111317"; ctx.fillRect(0, 0, W, H);
  ctx.lineWidth = 0.6;
  g.forEachEdge((e, attr, s, t, sa, ta) => {
    const lit = near && (s === focus || t === focus);
    if (near && !lit) ctx.strokeStyle = "rgba(150,158,172,0.03)";
    else if (lit) ctx.strokeStyle = "rgba(225,228,235,0.55)";
    else ctx.strokeStyle = attr.kind === "tree" ? "rgba(150,158,172,0.13)" : "rgba(178,160,128,0.16)";
    ctx.beginPath(); ctx.moveTo(sx(sa), sy(sa)); ctx.lineTo(sx(ta), sy(ta)); ctx.stroke();
  });
  g.forEachNode((id, a) => {
    ctx.globalAlpha = near && !near.has(id) ? 0.15 : 1;
    ctx.fillStyle = colorOf(id, a);
    ctx.beginPath(); ctx.arc(sx(a), sy(a), radius(id), 0, 7); ctx.fill();
  });
  ctx.globalAlpha = 1; ctx.textAlign = "center"; ctx.lineJoin = "round";
  const minDegree = 24 / Math.max(view.k / fitK, 1);
  g.forEachNode((id, a) => {
    const show = near ? near.has(id) : (id === "c0" || cur.hubs.has(id) || g.degree(id) >= minDegree);
    if (!show) return;
    ctx.font = (id === "c0" ? "600 14px" : id === focus ? "600 13px" : "12px") + " system-ui, sans-serif";
    const x = sx(a), y = sy(a) - radius(id) - 6;
    ctx.lineWidth = 3.5; ctx.strokeStyle = "rgba(17,19,23,0.9)"; ctx.strokeText(a.label, x, y);
    ctx.fillStyle = id === "c0" || id === focus ? "#f2efe8" : "#c3c6cd"; ctx.fillText(a.label, x, y);
  });
}

let fitK = 1;
function render(refit) {
  document.getElementById("busy").style.display = "grid";
  setTimeout(() => {
    cur = build(state.links);
    if (refit) { fit(); fitK = view.k; }
    document.getElementById("busy").style.display = "none";
    document.querySelectorAll(".seg").forEach(s => s.querySelectorAll("button")
      .forEach(b => b.classList.toggle("on", state[s.dataset.key] === b.dataset.v)));
    document.getElementById("colorHint").textContent = HINTS[state.color];
    document.getElementById("title").innerHTML = DATA.question + "<small>" + DATA.nodes.length +
      " concepts, " + DATA.maxDepth + " levels deep, " + cur.g.size + " links, " + cur.rank.length + " clusters</small>";
    draw();
    document.title = "settled";
  }, 20);
}

document.querySelectorAll(".seg").forEach(s => s.addEventListener("click", e => {
  const v = e.target.dataset.v; if (!v) return;
  const key = s.dataset.key, relayout = key === "links" && state.links !== v;
  state[key] = v; render(relayout);
}));
function nodeAt(mx, my) {
  let best = null, bestD = 64;
  cur.g.forEachNode((id, a) => { const d = (sx(a) - mx) ** 2 + (sy(a) - my) ** 2;
    if (d < bestD && d < (radius(id) + 5) ** 2) { best = id; bestD = d; } });
  return best;
}
function describe(id) {
  if (!id) return "Hover a concept to see what it connects to; click it for its papers. Scroll to zoom, drag to move.";
  const a = cur.g.getNodeAttributes(id);
  return "<b>" + esc(a.label) + "</b><br>" + NAMES[a.direction] + ", " + a.depth + " steps from your question, " +
    a.papers + " papers, " + cur.g.degree(id) + " links";
}
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const paperLink = id => DATA.papers[id] && DATA.papers[id].url ? DATA.papers[id].url
  : /^10\./.test(id) ? "https://doi.org/" + id : /^https?:/.test(id) ? id : "";
const NAMES = { root: "your question", up: "broader", sideways: "related", down: "narrower" };
function select(id) {
  selected = id; const box = document.getElementById("detail");
  if (!id) { box.style.display = "none"; draw(); return; }
  const a = cur.g.getNodeAttributes(id);
  const chain = []; for (let n = DATA.byId[id]; n; n = DATA.byId[n.parent]) chain.unshift(n);
  const go = n => '<span class="go" data-id="' + n + '">' + esc(DATA.byId[n].label) + "</span>";
  const crumbs = chain.map(n => n.id === id ? esc(n.label) : go(n.id)).join(" &rsaquo; ");
  const papers = a.paperIds.map(pid => {
    const p = DATA.papers[pid] || {}, url = paperLink(pid), title = esc(p.title || pid);
    const meta = [p.year, p.venue, p.cites != null ? p.cites + " citations" : ""].filter(Boolean).map(esc).join(" &middot; ");
    return "<li>" + (url ? '<a href="' + esc(url) + '" target="_blank" rel="noopener">' + title + "</a>" : title) +
      (meta ? '<div class="meta">' + meta + "</div>" : "") +
      (p.abstract ? "<details><summary>abstract</summary><p>" + esc(p.abstract) + "</p></details>" : "") + "</li>";
  }).join("");
  box.innerHTML = "<h3>" + esc(a.label) + '</h3><div class="meta">' + NAMES[a.direction] + ", " + a.depth +
    " steps from your question" + (a.query ? ", found by searching <i>" + esc(a.query) + "</i>" : "") + "</div>" +
    '<h4>Path from your question</h4><div class="crumbs">' + crumbs + "</div>" +
    "<h4>Linked concepts (" + cur.g.degree(id) + ')</h4><div class="crumbs">' + cur.g.neighbors(id).map(go).join(", ") + "</div>" +
    "<h4>Papers (" + a.paperIds.length + ")</h4><ol>" + papers + "</ol>";
  box.style.display = "block"; box.scrollIntoView({ block: "nearest" }); draw();
}
document.getElementById("detail").addEventListener("click", e => {
  const id = e.target.dataset && e.target.dataset.id; if (!id) return;
  const a = cur.g.getNodeAttributes(id);
  view.x = (W - 320) / 2 - a.x * view.k; view.y = H / 2 - a.y * view.k; select(id);
});
let drag = null;
canvas.addEventListener("mousedown", e => drag = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y, moved: false });
addEventListener("mouseup", e => {
  if (drag && !drag.moved && e.target === canvas) select(nodeAt(e.clientX, e.clientY));
  drag = null;
});
canvas.addEventListener("mousemove", e => {
  if (drag) { drag.moved = drag.moved || Math.abs(e.clientX - drag.x) + Math.abs(e.clientY - drag.y) > 4; view.x = drag.vx + e.clientX - drag.x; view.y = drag.vy + e.clientY - drag.y; draw(); return; }
  const id = nodeAt(e.clientX, e.clientY);
  if (id !== hover) { hover = id; document.getElementById("info").innerHTML = describe(id); draw(); }
});
canvas.addEventListener("wheel", e => {
  e.preventDefault();
  const f = Math.exp(-e.deltaY * 0.0015);
  view.x = e.clientX - (e.clientX - view.x) * f; view.y = e.clientY - (e.clientY - view.y) * f;
  view.k *= f; draw();
}, { passive: false });
document.getElementById("find").addEventListener("keydown", e => {
  if (e.key !== "Enter") return;
  const q = e.target.value.trim().toLowerCase();
  const id = cur.g.findNode((_, a) => a.label.toLowerCase().includes(q));
  if (!id) return;
  const a = cur.g.getNodeAttributes(id);
  view.k = fitK * 4; view.x = (W - 320) / 2 - a.x * view.k; view.y = H / 2 - a.y * view.k;
  select(id);
});
addEventListener("resize", () => { resize(); fit(); fitK = view.k; draw(); });
resize(); render(true);
</script></body></html>
"""


ABSTRACT_CHARS = 600
# Abstracts sometimes carry an author's address; the repo keeps no email addresses.
EMAIL = re.compile(r"\S+@\S+\.\w+")


def paper_details(research_map: dict, store: Path | None) -> dict:
    """Title, year, venue, citations, link and a short abstract for every paper a concept cites.

    The run file keeps full records only for its top papers; the local paper store
    (~/.cache/eonrise/corpus.jsonl) holds the rest.
    """
    wanted = {p for c in research_map["concepts"] for p in c.get("paper_ids", [])}
    records = {p["paper_id"]: p for p in research_map.get("papers", [])}
    if store and store.exists():
        with store.open(encoding="utf-8") as lines:
            for line in lines:
                paper = json.loads(line)
                if paper.get("paper_id") in wanted:
                    records.setdefault(paper["paper_id"], paper)
    details = {}
    for pid in wanted & records.keys():
        p = records[pid]
        abstract = EMAIL.sub("[email removed]", (p.get("abstract") or "")).strip()
        if len(abstract) > ABSTRACT_CHARS:
            abstract = abstract[:ABSTRACT_CHARS].rsplit(" ", 1)[0] + "..."
        details[pid] = {"title": p.get("title"), "year": p.get("year"), "venue": p.get("venue"),
                        "cites": p.get("cited_by_count"), "url": p.get("url"), "abstract": abstract}
    return details


def graph_data(research_map: dict, store: Path | None = None) -> dict:
    concepts = research_map["concepts"]
    ids = {c["node_id"] for c in concepts}
    nodes = [{"id": c["node_id"], "label": c["label"], "direction": c["direction"], "depth": c["depth"],
              "parent": c.get("parent_id"), "query": c.get("query"), "papers": len(c.get("paper_ids", [])),
              "paperIds": c.get("paper_ids", [])} for c in concepts]
    tree = [[c["parent_id"], c["node_id"]] for c in concepts if c.get("parent_id") in ids]
    backers = defaultdict(set)
    for c in concepts:
        for paper in c.get("paper_ids", []):
            backers[paper].add(c["node_id"])
    pairs = Counter()
    for group in backers.values():
        if len(group) <= MAX_PAPER_FANOUT:
            pairs.update(itertools.combinations(sorted(group), 2))
    in_tree = {tuple(sorted(link)) for link in tree}
    shared = [[a, b, n] for (a, b), n in sorted(pairs.items())
              if n >= MIN_SHARED_PAPERS and (a, b) not in in_tree]
    return {"question": research_map["question"], "maxDepth": max(c["depth"] for c in concepts),
            "nodes": nodes, "tree": tree, "shared": shared, "papers": paper_details(research_map, store)}


def find_chrome() -> str:
    for name in ("chrome", "google-chrome", "chromium", "msedge"):
        if shutil.which(name):
            return shutil.which(name)
    for path in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                 r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"):
        if os.path.exists(path):
            return path
    raise SystemExit("No Chrome, Chromium or Edge found for --png")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("map", type=Path, help="research_map.json from an Eonrise run")
    p.add_argument("--out", type=Path, default=Path("graph.html"))
    p.add_argument("--png", type=Path, help="also save a still image here")
    p.add_argument("--size", default="1600,1000", help="still image width,height")
    p.add_argument("--papers", type=Path, default=Path.home() / ".cache" / "eonrise" / "corpus.jsonl",
                   help="local paper store with titles and abstracts")
    args = p.parse_args()

    data = graph_data(json.loads(args.map.read_text(encoding="utf-8")), args.papers)
    page = PAGE.replace("__LIBS__", LIBS).replace("__DATA__", json.dumps(data, ensure_ascii=False))
    args.out.write_text(page, encoding="utf-8")
    print(f"{args.out}: {len(data['nodes'])} concepts, {len(data['tree'])} tree links, "
          f"{len(data['shared'])} shared-paper links, {len(data['papers'])} papers, depth {data['maxDepth']}")
    if args.png:
        args.png.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([find_chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        f"--window-size={args.size}", "--virtual-time-budget=60000",
                        f"--screenshot={args.png.resolve()}", args.out.resolve().as_uri() + "#still"], check=True)
        if not args.png.exists():
            raise SystemExit(f"Chrome ran but wrote no {args.png}")
        print(f"{args.png}: saved")


if __name__ == "__main__":
    main()
