"""Draw a run's concept map as a force-directed graph page, like Obsidian's graph view.

    python tools/graph_view.py output/research_map.json --out graph.html
    python tools/graph_view.py output/research_map.json --out graph.html --png docs/assets/graph.png

The page loads force-graph from a CDN; the package itself stays free of dependencies.
--png renders the page in headless Chrome and saves a screenshot.
"""

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

LIB = "https://cdn.jsdelivr.net/npm/force-graph@1.43.5/dist/force-graph.min.js"

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Eonrise concept map</title>
<style>
  html, body { margin: 0; height: 100%; background: #1e1e1e; overflow: hidden;
    font: 13px system-ui, sans-serif; color: #bbb; }
  #legend, #title { z-index: 2; }
  #legend { position: fixed; left: 16px; bottom: 14px; line-height: 1.7; }
  #legend b { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; }
  #title { position: fixed; left: 16px; top: 12px; max-width: 70%; color: #ddd; }
</style>
<script src="__LIB__"></script></head>
<body><div id="title"></div><div id="graph"></div><div id="legend"></div>
<script>
const DATA = __DATA__;
const COLOR = { root: "#a882ff", up: "#e0a458", sideways: "#7f8c9a", down: "#5fb38a" };
const NAMES = { root: "your question", up: "broader", sideways: "related", down: "narrower" };
document.getElementById("title").textContent = DATA.question + "  (" + DATA.nodes.length +
  " concepts, depth " + DATA.maxDepth + ")";
document.getElementById("legend").innerHTML = Object.keys(COLOR)
  .map(k => '<div><b style="background:' + COLOR[k] + '"></b>' + NAMES[k] + "</div>").join("");
const degree = {};
DATA.links.forEach(l => { degree[l.source] = (degree[l.source] || 0) + 1; degree[l.target] = (degree[l.target] || 0) + 1; });
const LABEL_DEGREE = DATA.nodes.length > 600 ? 20 : 5;
const radius = n => 2 + Math.sqrt(degree[n.id] || 1) * 1.6;
const graph = ForceGraph()(document.getElementById("graph"))
  .graphData(DATA)
  .backgroundColor("#1e1e1e")
  .nodeRelSize(1)
  .linkColor(() => "rgba(160,160,160,0.22)")
  .linkWidth(0.6)
  .cooldownTicks(400)
  .nodeCanvasObject((n, ctx, scale) => {
    // Sizes are in screen pixels, so a 2000-concept map stays readable when zoomed out.
    const r = Math.max(radius(n), 1.6 / scale) * (n.depth === 0 ? 2.5 : 1);
    ctx.beginPath(); ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
    ctx.fillStyle = COLOR[n.direction] || COLOR.sideways; ctx.fill();
    if (n.depth > 0 && (degree[n.id] || 0) < LABEL_DEGREE) return;
    ctx.font = (n.depth === 0 ? 15 : 11) / scale + "px system-ui"; ctx.fillStyle = "#d6d6d6";
    ctx.textAlign = "center"; ctx.fillText(n.label, n.x, n.y + r + 12 / scale);
  })
  .nodeLabel(n => n.label + " (" + NAMES[n.direction] + ", depth " + n.depth + ")")
  .onEngineStop(() => { graph.zoomToFit(0, 40); document.title = "settled"; });
graph.d3Force("charge").strength(-12);
graph.d3Force("link").distance(12);
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
    page = PAGE.replace("__LIB__", LIB).replace("__DATA__", json.dumps(data, ensure_ascii=False))
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
