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
  :root { --bg: #111317; --panel: #171a20; --raise: #262a33; --line: #2a2f38; --text: #e1e3e8;
    --dim: #9aa0aa; --accent: #c2a878; --link: #a9bdd8; }
  html, body { margin: 0; height: 100%; background: var(--bg); color: var(--text);
    font: 13px/1.45 system-ui, sans-serif; overflow: hidden; }
  canvas { display: block; cursor: grab; }
  #title { position: fixed; left: 20px; top: 16px; max-width: 55%; font-size: 15px; }
  #title small { display: block; color: var(--dim); font-size: 12px; margin-top: 3px; }
  #panel { position: fixed; right: 16px; top: 16px; bottom: 16px; width: 340px; display: flex;
    flex-direction: column; background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
    overflow: hidden; }
  #panel .top { padding: 12px 12px 0; }
  .search { position: relative; }
  .search input { width: 100%; box-sizing: border-box; background: var(--bg); color: var(--text);
    border: 1px solid var(--line); border-radius: 7px; padding: 8px 10px 8px 30px; font: inherit; }
  .search input::placeholder { color: var(--dim); }
  .search input:focus { outline: none; border-color: var(--accent); }
  .search svg { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); color: var(--dim); }
  .tabs { display: flex; gap: 4px; margin: 12px 0 0; border-bottom: 1px solid var(--line); }
  .tabs button { background: none; border: 0; border-bottom: 2px solid transparent; color: var(--dim);
    padding: 7px 10px 8px; font: inherit; font-weight: 500; cursor: pointer; margin-bottom: -1px; }
  .tabs button:hover { color: var(--text); }
  .tabs button.on { color: var(--text); border-bottom-color: var(--accent); }
  .body { flex: 1; overflow-y: auto; padding: 14px 14px 18px; }
  .body[hidden] { display: none; }
  .label { font-size: 12px; font-weight: 600; color: var(--dim); margin: 16px 0 6px; }
  .label:first-child { margin-top: 0; }
  .seg { display: flex; background: var(--bg); border: 1px solid var(--line); border-radius: 7px; padding: 2px; }
  .seg button { flex: 1; background: none; border: 0; border-radius: 5px; color: var(--dim); padding: 5px 0;
    font: inherit; cursor: pointer; transition: background .15s, color .15s; }
  .seg button:hover { color: var(--text); }
  .seg button.on { background: var(--raise); color: var(--text); }
  .hint { color: var(--dim); font-size: 12px; margin-top: 6px; }
  .legend { display: grid; gap: 2px; margin-top: 8px; }
  .legend button { display: flex; align-items: center; gap: 8px; background: none; border: 0; color: var(--text);
    padding: 4px 6px; border-radius: 5px; font: inherit; text-align: left; cursor: pointer; }
  .legend button:hover { background: var(--raise); }
  .legend .n { margin-left: auto; color: var(--dim); font-variant-numeric: tabular-nums; }
  .dot { width: 9px; height: 9px; border-radius: 50%; flex: none; background: var(--c); }
  .ramp { height: 8px; border-radius: 4px; margin-top: 8px;
    background: linear-gradient(90deg, rgb(222,214,196), rgb(70,82,102)); }
  .ramp + .ends { display: flex; justify-content: space-between; color: var(--dim); font-size: 12px; margin-top: 3px; }
  .empty { color: var(--dim); padding: 24px 4px; text-align: center; }
  .bar { display: flex; gap: 4px; margin-bottom: 12px; }
  .bar button { background: var(--bg); border: 1px solid var(--line); color: var(--text); border-radius: 6px;
    padding: 3px 9px; font: inherit; font-size: 12px; cursor: pointer; }
  .bar button:hover:not(:disabled) { border-color: var(--dim); }
  .bar button:disabled { color: #4a4f59; cursor: default; }
  .bar .grow { flex: 1; }
  .head { display: flex; align-items: flex-start; gap: 10px; }
  .head .dot { width: 12px; height: 12px; margin-top: 5px; }
  .head h3 { margin: 0; font-size: 17px; font-weight: 600; line-height: 1.3; text-wrap: balance; }
  .chips { display: flex; flex-wrap: wrap; gap: 5px; margin: 10px 0 0; }
  .chip { --c: var(--dim); display: inline-flex; align-items: center; gap: 5px; padding: 2px 8px;
    border-radius: 999px; font-size: 12px; color: color-mix(in oklab, var(--c) 75%, white);
    background: color-mix(in oklab, var(--c) 16%, transparent);
    border: 1px solid color-mix(in oklab, var(--c) 32%, transparent); }
  button.chip { font: inherit; font-size: 12px; cursor: pointer; }
  button.chip:hover { background: color-mix(in oklab, var(--c) 28%, transparent); }
  .found { margin-top: 10px; color: var(--dim); font-size: 12px; }
  .found q { color: var(--text); }
  details.sec { border-top: 1px solid var(--line); margin-top: 14px; padding-top: 10px; }
  details.sec > summary { list-style: none; display: flex; align-items: center; gap: 8px; cursor: pointer;
    font-weight: 600; }
  details.sec > summary::-webkit-details-marker { display: none; }
  details.sec > summary::before { content: ""; width: 6px; height: 6px; border: solid var(--dim);
    border-width: 0 1.5px 1.5px 0; transform: rotate(-45deg); transition: transform .15s; }
  details.sec[open] > summary::before { transform: rotate(45deg); }
  details.sec > summary .n { color: var(--dim); font-weight: 400; }
  details.sec > summary .seg { margin-left: auto; font-weight: 400; font-size: 12px; }
  details.sec > summary .seg button { padding: 2px 8px; }
  .papers { list-style: none; margin: 8px 0 0; padding: 0; display: grid; gap: 12px; }
  .papers a { color: var(--text); text-decoration: none; font-weight: 500; }
  .papers a:hover { color: var(--link); text-decoration: underline; }
  .pmeta { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 4px; color: var(--dim); font-size: 12px; }
  .year { color: var(--link); font-variant-numeric: tabular-nums; }
  .cites { color: #c2a878; }
  .papers details summary { color: var(--dim); font-size: 12px; cursor: pointer; margin-top: 4px; width: max-content; }
  .papers details p { margin: 5px 0 0; font-size: 12px; line-height: 1.5; color: #b3b8c2; }
  .links { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 8px; }
  .more { background: none; border: 0; color: var(--link); font: inherit; font-size: 12px; cursor: pointer; padding: 2px 4px; }
  .trail { list-style: none; margin: 8px 0 0; padding: 0; }
  .trail li { position: relative; padding: 0 0 8px 20px; }
  .trail li::before { content: ""; position: absolute; left: 4px; top: 6px; bottom: -6px; width: 1px; background: var(--line); }
  .trail li:last-child::before { display: none; }
  .trail .dot { position: absolute; left: 0; top: 5px; }
  .trail button { background: none; border: 0; padding: 0; color: var(--text); font: inherit; text-align: left; cursor: pointer; }
  .trail button:hover { color: var(--link); }
  .trail .here { font-weight: 600; }
  .trail .gap { color: var(--dim); }
  .trail small { color: var(--dim); margin-left: 4px; }
  #info { position: fixed; left: 20px; bottom: 16px; max-width: 420px; color: var(--dim); }
  #info b { color: var(--text); font-weight: 600; }
  #busy { position: fixed; inset: 0; display: grid; place-items: center; color: var(--dim);
    pointer-events: none; }
  body.still #panel, body.still #info { display: none; }
</style>
__LIBS__</head>
<body><div id="title"></div><canvas id="map"></canvas><div id="busy">Laying out...</div>
<aside id="panel">
  <div class="top">
    <label class="search"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
      <input id="find" placeholder="Find a concept" aria-label="Find a concept" list="names"></label>
    <datalist id="names"></datalist>
    <nav class="tabs"><button data-tab="concept">Concept</button><button data-tab="view">View</button></nav>
  </div>
  <div class="body" id="tab-concept"><div class="empty">Click a concept on the map, or find one by name.</div></div>
  <div class="body" id="tab-view" hidden>
    <div class="label">Links</div>
    <div class="seg" data-key="links"><button data-v="tree">Tree</button><button data-v="shared">Shared papers</button><button data-v="both">Both</button></div>
    <div class="hint">Tree links each concept to the one it grew from. Shared papers links two concepts the same papers support.</div>
    <div class="label">Colour</div>
    <div class="seg" data-key="color"><button data-v="cluster">Cluster</button><button data-v="direction">Direction</button><button data-v="depth">Depth</button></div>
    <div class="hint" id="colorHint"></div>
    <div id="legend"></div>
  </div>
</aside>
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
  cluster: "Groups the links pull together. A colour is a neighbourhood, not a field. Click one to open its hub.",
  direction: "How each concept relates to the one it grew from.",
  depth: "Steps from your question to each concept."
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
  const right = still ? 40 : 380;
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
    legend();
    if (selected) select(selected, false);
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
const history = [], at = { i: -1 };
let paperSort = "cites", showAllLinks = false;
const dotFor = id => '<span class="dot" style="--c:' + colorOf(id, cur.g.getNodeAttributes(id)) + '"></span>';
const chipFor = id => '<button class="chip" data-id="' + id + '" style="--c:' + colorOf(id, cur.g.getNodeAttributes(id)) + '">' +
  esc(DATA.byId[id].label) + "</button>";

function tab(name) {
  document.querySelectorAll(".tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === name));
  document.getElementById("tab-concept").hidden = name !== "concept";
  document.getElementById("tab-view").hidden = name !== "view";
}
function legend() {
  const box = document.getElementById("legend");
  if (state.color === "depth") {
    box.innerHTML = '<div class="ramp"></div><div class="ends"><span>your question</span><span>' + DATA.maxDepth + " steps</span></div>";
    return;
  }
  if (state.color === "direction") {
    const count = {}; DATA.nodes.forEach(n => count[n.direction] = (count[n.direction] || 0) + 1);
    box.innerHTML = '<div class="legend">' + ["up", "sideways", "down"].map(d =>
      '<button disabled><span class="dot" style="--c:' + DIRECTION[d] + '"></span>' + NAMES[d] +
      '<span class="n">' + count[d] + "</span></button>").join("") + "</div>";
    return;
  }
  const size = {}; Object.values(cur.community).forEach(c => size[c] = (size[c] || 0) + 1);
  const hubOf = {}; cur.hubs.forEach(id => hubOf[cur.community[id]] = id);
  box.innerHTML = '<div class="legend">' + cur.rank.slice(0, 12).filter(c => hubOf[c]).map(c =>
    '<button data-id="' + hubOf[c] + '"><span class="dot" style="--c:' + colorOf(hubOf[c], cur.g.getNodeAttributes(hubOf[c])) + '"></span>' +
    esc(DATA.byId[hubOf[c]].label) + '<span class="n">' + size[c] + "</span></button>").join("") + "</div>";
}

function papersHtml(ids) {
  const rows = ids.map(pid => ({ pid, p: DATA.papers[pid] || {} }));
  rows.sort(paperSort === "cites" ? (a, b) => (b.p.cites || 0) - (a.p.cites || 0) : (a, b) => (b.p.year || 0) - (a.p.year || 0));
  return '<ol class="papers">' + rows.map(({ pid, p }) => {
    const url = paperLink(pid), title = esc(p.title || pid);
    return "<li>" + (url ? '<a href="' + esc(url) + '" target="_blank" rel="noopener">' + title + "</a>" : title) +
      '<div class="pmeta">' + (p.year ? '<span class="year">' + p.year + "</span>" : "") +
      (p.venue ? "<span>" + esc(p.venue) + "</span>" : "") +
      (p.cites != null ? '<span class="cites">' + p.cites + " cited</span>" : "") + "</div>" +
      (p.abstract ? "<details><summary>Abstract</summary><p>" + esc(p.abstract) + "</p></details>" : "") + "</li>";
  }).join("") + "</ol>";
}
function trailHtml(id) {
  const chain = []; for (let n = DATA.byId[id]; n; n = DATA.byId[n.parent]) chain.unshift(n);
  const step = (n, i) => "<li>" + '<span class="dot" style="--c:' + (DIRECTION[n.direction] || DIRECTION.sideways) + '"></span>' +
    (n.id === id ? '<span class="here">' + esc(n.label) + "</span>" : '<button data-id="' + n.id + '">' + esc(n.label) + "</button>") +
    (i ? "<small>" + NAMES[n.direction] + "</small>" : "") + "</li>";
  if (chain.length <= 7) return '<ol class="trail">' + chain.map(step).join("") + "</ol>";
  return '<ol class="trail">' + chain.slice(0, 2).map(step).join("") +
    '<li><button class="gap" data-expand="1">' + (chain.length - 5) + " more steps</button></li>" +
    chain.slice(-3).map((n, i) => step(n, chain.length - 3 + i)).join("") + "</ol>";
}
function select(id, push = true) {
  selected = id; draw();
  const box = document.getElementById("tab-concept");
  if (!id) { box.innerHTML = '<div class="empty">Click a concept on the map, or find one by name.</div>'; return; }
  if (push && history[at.i] !== id) { history.splice(at.i + 1); history.push(id); at.i = history.length - 1; showAllLinks = false; }
  const a = cur.g.getNodeAttributes(id), color = colorOf(id, a);
  const links = cur.g.neighbors(id).sort((x, y) => cur.g.degree(y) - cur.g.degree(x));
  const shown = showAllLinks ? links : links.slice(0, 14);
  box.innerHTML =
    '<div class="bar"><button data-nav="-1"' + (at.i > 0 ? "" : " disabled") + ' aria-label="Back">&#8249; Back</button>' +
    '<button data-nav="1"' + (at.i < history.length - 1 ? "" : " disabled") + ' aria-label="Forward">Forward &#8250;</button>' +
    '<span class="grow"></span><button data-centre="1">Centre on map</button></div>' +
    '<div class="head"><span class="dot" style="--c:' + color + '"></span><h3>' + esc(a.label) + "</h3></div>" +
    '<div class="chips"><span class="chip" style="--c:' + (DIRECTION[a.direction] || DIRECTION.sideways) + '">' + NAMES[a.direction] + "</span>" +
    '<span class="chip">' + a.depth + " steps deep</span>" +
    '<span class="chip">' + a.paperIds.length + " papers</span>" +
    '<span class="chip">' + links.length + " links</span></div>" +
    (a.query ? '<div class="found">Found by searching <q>' + esc(a.query) + "</q></div>" : "") +
    '<details class="sec" open><summary>Path from your question <span class="n">' + a.depth + " steps</span></summary>" +
    trailHtml(id) + "</details>" +
    '<details class="sec" open><summary>Linked concepts <span class="n">' + links.length + "</span></summary>" +
    '<div class="links">' + shown.map(chipFor).join("") +
    (links.length > shown.length ? '<button class="more" data-all="1">Show all ' + links.length + "</button>" : "") + "</div></details>" +
    '<details class="sec" open><summary>Papers <span class="n">' + a.paperIds.length + "</span>" +
    '<span class="seg" data-sort="1"><button data-v="cites"' + (paperSort === "cites" ? ' class="on"' : "") + '>Most cited</button>' +
    '<button data-v="year"' + (paperSort === "year" ? ' class="on"' : "") + ">Newest</button></span></summary>" +
    papersHtml(a.paperIds) + "</details>";
  if (push) tab("concept");
}
function centre(id) {
  const a = cur.g.getNodeAttributes(id);
  if (view.k < fitK * 2.5) view.k = fitK * 2.5;
  view.x = (W - 380) / 2 - a.x * view.k; view.y = H / 2 - a.y * view.k; draw();
}
document.querySelector(".tabs").addEventListener("click", e => { if (e.target.dataset.tab) tab(e.target.dataset.tab); });
document.getElementById("legend").addEventListener("click", e => {
  const b = e.target.closest("[data-id]"); if (b) { centre(b.dataset.id); select(b.dataset.id); }
});
document.getElementById("tab-concept").addEventListener("click", e => {
  const el = e.target.closest("button, summary"); if (!el) return;
  const d = el.dataset;
  if (el.parentElement && el.parentElement.dataset.sort) { e.preventDefault(); paperSort = d.v; select(selected, false); return; }
  if (d.nav) { at.i += Number(d.nav); centre(history[at.i]); select(history[at.i], false); return; }
  if (d.centre) { centre(selected); return; }
  if (d.all) { showAllLinks = true; select(selected, false); return; }
  if (d.expand) { el.closest(".trail").outerHTML = trailHtml(selected).replace(/<li><button class="gap"[^]*?<\/li>/, ""); expandTrail(); return; }
  if (d.id) { centre(d.id); select(d.id); }
});
function expandTrail() {
  const chain = []; for (let n = DATA.byId[selected]; n; n = DATA.byId[n.parent]) chain.unshift(n);
  const box = document.querySelector("#tab-concept .trail");
  box.innerHTML = chain.map((n, i) => "<li>" + '<span class="dot" style="--c:' + (DIRECTION[n.direction] || DIRECTION.sideways) + '"></span>' +
    (n.id === selected ? '<span class="here">' + esc(n.label) + "</span>" : '<button data-id="' + n.id + '">' + esc(n.label) + "</button>") +
    (i ? "<small>" + NAMES[n.direction] + "</small>" : "") + "</li>").join("");
}
addEventListener("keydown", e => {
  if (e.target.tagName === "INPUT") return;
  if (e.key === "Escape") select(null);
  if (e.altKey && e.key === "ArrowLeft" && at.i > 0) { at.i--; centre(history[at.i]); select(history[at.i], false); }
  if (e.altKey && e.key === "ArrowRight" && at.i < history.length - 1) { at.i++; centre(history[at.i]); select(history[at.i], false); }
});
document.getElementById("names").innerHTML = DATA.nodes.map(n => '<option value="' + esc(n.label) + '">').join("");
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
