from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .corpus import CorpusStore
from .engine import canonical_root, run_agent
from .memory import MemoryStore
from .models import AgentPolicy, Paper
from .providers import (CachedHttpClient, CoreProvider, CrossrefProvider, DoajProvider,
                         EuropePMCProvider, EvidenceBundleProvider, OpenAlexProvider,
                         SemanticScholarProvider)
from .report import write_outputs
from .scheduling import ProviderStates


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Expand one topic into a grounded up/down/sideways map.")
    p.add_argument("question", help="Research question or topic in plain language")
    p.add_argument("--out", default="eonrise-output", help="Output directory")
    p.add_argument("--email", default=os.getenv("CROSSREF_EMAIL", ""), help="Email for Crossref polite pool")
    p.add_argument("--openalex-key", default=os.getenv("OPENALEX_API_KEY", ""), help="OpenAlex API key (optional: raises rate limits, enables --semantic)")
    p.add_argument("--semantic", action="store_true", help="Use OpenAlex semantic search")
    p.add_argument("--mode", choices=("live", "assistant"), default="live", help="live: search scholarly APIs; assistant: use an offline evidence bundle")
    p.add_argument("--bundle", help="JSON evidence bundle for assistant mode")
    p.add_argument("--fixture", help=argparse.SUPPRESS)
    p.add_argument("--crossref-only", action="store_true", help="Crossref alone (no abstracts or topics; expect neighbor_field to stay empty)")
    p.add_argument("--providers", default="", help="Comma-separated subset of: crossref,openalex,europepmc,doaj,semanticscholar,core")
    p.add_argument("--s2-key", default=os.getenv("S2_API_KEY", ""), help="Semantic Scholar key (free; the keyless pool answers 429 under load)")
    p.add_argument("--core-key", default=os.getenv("CORE_API_KEY", ""), help="CORE key (free; keyless requests 429 after a few calls)")
    p.add_argument("--max-rounds", type=int, default=6)
    p.add_argument("--results", type=int, default=20, help="Results per query/provider")
    p.add_argument("--http-timeout", type=int, default=12, help="Seconds per live API request")
    p.add_argument("--http-retries", type=int, default=2, help="Attempts per live API request")
    # Single-root agent policy: the agent decides depth and direction.
    p.add_argument("--agent-name", default="default")
    p.add_argument("--max-nodes", type=int, default=120, help="Agent concept budget (unbounded if large)")
    p.add_argument("--max-depth", type=int, default=4, help="How deep one agent may recurse")
    p.add_argument("--up-weight", type=float, default=0.5)
    p.add_argument("--down-weight", type=float, default=1.0)
    p.add_argument("--sideways-weight", type=float, default=1.0)
    p.add_argument("--support-threshold", type=int, default=2, help="Papers needed to expand past round 1")
    p.add_argument("--no-memory", action="store_true", help="Skip appending to local memory store")
    p.add_argument("--corpus", default="", help="Paper store to read and grow (default: <cache>/corpus.jsonl)")
    p.add_argument("--no-corpus", action="store_true", help="Do not read or write the local paper store")
    return p


def main() -> None:
    args = parser().parse_args()
    cache = Path.home() / ".cache" / "eonrise"
    http = CachedHttpClient(cache, timeout=max(1, args.http_timeout), max_retries=max(1, args.http_retries))
    corpus = None if args.no_corpus else CorpusStore(args.corpus or (cache / "corpus.jsonl"))
    bundle_path = args.bundle or args.fixture
    if args.mode == "assistant" or bundle_path:
        if not bundle_path:
            raise SystemExit("assistant mode requires --bundle PATH")
        providers = [EvidenceBundleProvider(bundle_path)]
        mode = "assistant"
    else:
        # Measured on one query, 20 results each: Europe PMC returned 20/20 abstracts and
        # 18/20 keyword lists, DOAJ 8/8 abstracts with an LCC subject each, Crossref 16%
        # abstracts and no subjects. Keyless sources run by default; the two that need a
        # free key join only when one is supplied.
        available = {
            "crossref": lambda: CrossrefProvider(http, args.email),
            "openalex": lambda: OpenAlexProvider(http, args.openalex_key, args.semantic, args.email),
            "europepmc": lambda: EuropePMCProvider(http, args.email),
            "doaj": lambda: DoajProvider(http, args.email),
            "semanticscholar": lambda: SemanticScholarProvider(http, args.s2_key),
            "core": lambda: CoreProvider(http, args.core_key),
        }
        if args.providers:
            chosen = [n.strip().lower() for n in args.providers.split(",") if n.strip()]
            unknown = [n for n in chosen if n not in available]
            if unknown:
                raise SystemExit(f"unknown provider(s): {', '.join(unknown)}")
        elif args.crossref_only:
            chosen = ["crossref"]
        else:
            chosen = ["crossref", "openalex", "europepmc", "doaj"]
            if args.s2_key: chosen.append("semanticscholar")
            if args.core_key: chosen.append("core")
        providers = [available[name]() for name in dict.fromkeys(chosen)]
        # The store answers first and costs nothing: a paper already held needs no API
        # credit, and OpenAlex now charges them.
        if corpus is not None:
            providers.insert(0, corpus)
        mode = "live"
    policy = AgentPolicy(
        name=args.agent_name,
        max_nodes=max(1, args.max_nodes),
        max_depth=max(1, args.max_depth),
        max_rounds=max(1, args.max_rounds),
        up_weight=args.up_weight,
        down_weight=args.down_weight,
        sideways_weight=args.sideways_weight,
        support_threshold=max(1, args.support_threshold),
    )
    store = MemoryStore(cache / "memory.jsonl")
    try:
        background = store.background_labels(canonical_root(args.question))
    except OSError:
        background = set()
    # Availability lives longer than one process: a source rate limited for eight hours
    # should not be re-discovered by tomorrow's run.
    states = ProviderStates(cache / "providers.json")
    result = run_agent(args.question, providers, policy, results_per_query=max(1, args.results),
                       background=background, states=states)
    try:
        states.save()
    except OSError:
        pass
    result["background_terms_penalised"] = len(background)
    result["mode"] = mode
    result["input_bundle"] = str(Path(bundle_path).resolve()) if bundle_path else ""
    if not args.no_memory:
        try:
            store.append_run(result)
        except OSError:
            pass
    if corpus is not None:
        try:
            result["corpus_added"] = corpus.add([Paper.from_dict(p) for p in result["papers"]])
            result["corpus_size"] = corpus.stats()["papers"]
        except OSError:
            pass
    write_outputs(result, args.out)
    print(json.dumps({
        "mode": mode,
        "status": result["status"],
        "stop_reason": result["stop_reason"],
        "root_topic": result.get("root_topic", ""),
        "agent": policy.name,
        "concepts": len(result.get("concepts", [])),
        "papers": len(result["papers"]),
        "corpus": result.get("corpus_size", 0),
        "gaps": result["gaps"],
        "output": str(Path(args.out).resolve()),
    }, indent=2))


if __name__ == "__main__":
    main()
