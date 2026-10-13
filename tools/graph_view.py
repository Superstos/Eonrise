"""Draw a run's concept map as a network picture: ForceAtlas2 layout, one colour per cluster.

    python tools/graph_view.py output/research_map.json --out graph.html
    python tools/graph_view.py output/research_map.json --out graph.html --png docs/assets/graph.png

The page loads graphology from a CDN; the package itself stays free of dependencies.
--png renders the page in headless Chrome and saves a screenshot.
"""

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

LIBS = "".join(f'<script src="https://cdn.jsdelivr.net/npm/{path}"></script>' for path in (
    "graphology@0.25.4/dist/graphology.umd.min.js",
    "graphology-library@0.8.0/dist/graphology-library.min.js",
))

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Eonrise concept map</title>
<style>
  html { background: #05060a; }
  html, body { margin: 0; height: 100%;
    background: radial-gradient(ellipse at center, #151826 0%, #05060a 75%) fixed; overflow: hidden; }
  canvas { display: block; }
  #title { position: fixed; left: 22px; top: 18px; max-width: 70%;
    font: 15px system-ui, sans-serif; color: #e8e8f0; letter-spacing: .2px; }
  #title small { display: block; margin-top: 4px; color: #7c8090; font-size: 12px; }
</style>
__LIBS__</head>
<body><div id="title"></div><canvas id="map"></canvas>
<script>
// ForceAtlas2 layout (Gephi's) plus Louvain clusters; each cluster gets one colour.
const DATA = __DATA__;
const lib = graphologyLibrary;
const g = new graphology.Graph();
DATA.nodes.forEach((n, i) => g.addNode(n.id, { ...n, x: Math.cos(i) * i, y: Math.sin(i) * i }));
DATA.links.forEach(l => g.mergeEdge(l.source, l.target));
lib.layoutForceAtlas2.assign(g, { iterations: 900, settings: {
  ...lib.layoutForceAtlas2.inferSettings(g), barnesHutOptimize: true, strongGravityMode: true,
  gravity: 0.6, scalingRatio: 6, adjustSizes: false } });
const community = lib.communitiesLouvain(g, { resolution: 1.2 });
const PALETTE = ["#ff6b9d", "#4cc9f0", "#ffd166", "#7bdff2", "#b388ff", "#06d6a0", "#ff9f1c",
  "#f15bb5", "#9bf6ff", "#caffbf", "#ffadad", "#a0c4ff"];
const sizes = {};
Object.values(community).forEach(c => sizes[c] = (sizes[c] || 0) + 1);
const rank = Object.keys(sizes).sort((a, b) => sizes[b] - sizes[a]);
const colorOf = id => g.getNodeAttribute(id, "depth") === 0 ? "#ffffff"
  : PALETTE[rank.indexOf(String(community[id])) % PALETTE.length];

const W = innerWidth, H = innerHeight, canvas = document.getElementById("map");
canvas.width = W; canvas.height = H; canvas.style.height = H + "px";
const ctx = canvas.getContext("2d");
const xs = g.mapNodes((_, a) => a.x), ys = g.mapNodes((_, a) => a.y);
const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
const pad = 70, k = Math.min((W - 2 * pad) / (x1 - x0), (H - 2 * pad - 40) / (y1 - y0));
const px = x => (x - (x0 + x1) / 2) * k + W / 2, py = y => (y - (y0 + y1) / 2) * k + H / 2 + 20;

ctx.globalCompositeOperation = "lighter";
g.forEachEdge((e, a, s, t, sa, ta) => {
  const [ax, ay, bx, by] = [px(sa.x), py(sa.y), px(ta.x), py(ta.y)];
  const mx = (ax + bx) / 2 + (by - ay) * 0.12, my = (ay + by) / 2 - (bx - ax) * 0.12;
  ctx.strokeStyle = colorOf(t) + "40"; ctx.lineWidth = 0.7;
  ctx.beginPath(); ctx.moveTo(ax, ay); ctx.quadraticCurveTo(mx, my, bx, by); ctx.stroke();
});
const radius = id => id === "c0" ? 9 : 1.3 + Math.sqrt(g.degree(id)) * 0.9;
g.forEachNode((id, a) => {
  const c = colorOf(id), r = radius(id), x = px(a.x), y = py(a.y);
  const glow = ctx.createRadialGradient(x, y, 0, x, y, r * 4);
  glow.addColorStop(0, c + "55"); glow.addColorStop(1, c + "00");
  ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(x, y, r * 4, 0, 7); ctx.fill();
  ctx.fillStyle = c; ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.fill();
});

ctx.globalCompositeOperation = "source-over";
const hubs = {};
g.forEachNode((id, a) => { const c = community[id];
  if (a.depth > 0 && (!hubs[c] || g.degree(id) > g.degree(hubs[c]))) hubs[c] = id; });
const labelled = rank.slice(0, 18).map(c => hubs[c]).filter(Boolean).concat(["c0"]);
ctx.textAlign = "center"; ctx.lineJoin = "round";
labelled.forEach(id => {
  const a = g.getNodeAttributes(id), x = px(a.x), y = py(a.y) - radius(id) - 8;
  ctx.font = (id === "c0" ? "600 16px" : "500 13px") + " system-ui, sans-serif";
  ctx.lineWidth = 4; ctx.strokeStyle = "rgba(5,6,10,.85)"; ctx.strokeText(a.label, x, y);
  ctx.fillStyle = id === "c0" ? "#ffffff" : colorOf(id); ctx.fillText(a.label, x, y);
});
document.getElementById("title").innerHTML = DATA.question +
  "<small>" + DATA.nodes.length + " concepts, " + DATA.maxDepth + " levels deep, " + rank.length + " clusters</small>";
document.title = "settled";
</script></body></html>
"""


def graph_data(research_map: dict) -> dict:
    concepts = research_map["concepts"]
    ids = {c["node_id"] for c in concepts}
    nodes = [{"id": c["node_id"], "label": c["label"], "direction": c["direction"], "depth": c["depth"]}
             for c in concepts]
    links = [{"source": c["parent_id"], "target": c["node_id"]}
             for c in concepts if c.get("parent_id") in ids]
    return {"question": research_map["question"], "maxDepth": max(c["depth"] for c in concepts),
            "nodes": nodes, "links": links}


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
    p.add_argument("--png", type=Path, help="also save a screenshot here")
    p.add_argument("--size", default="1600,1000", help="screenshot width,height")
    args = p.parse_args()

    data = graph_data(json.loads(args.map.read_text(encoding="utf-8")))
    page = PAGE.replace("__LIBS__", LIBS).replace("__DATA__", json.dumps(data, ensure_ascii=False))
    args.out.write_text(page, encoding="utf-8")
    print(f"{args.out}: {len(data['nodes'])} concepts, {len(data['links'])} links, depth {data['maxDepth']}")
    if args.png:
        args.png.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([find_chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        f"--window-size={args.size}", "--virtual-time-budget=30000",
                        f"--screenshot={args.png.resolve()}", args.out.resolve().as_uri()], check=True)
        if not args.png.exists():
            raise SystemExit(f"Chrome ran but wrote no {args.png}")
        print(f"{args.png}: saved")


if __name__ == "__main__":
    main()
