from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .engine import run_agent
from .memory import MemoryStore
from .models import AgentPolicy
from .providers import CachedHttpClient, CrossrefProvider, EvidenceBundleProvider, OpenAlexProvider
from .report import write_outputs


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Expand one topic into a grounded up/down/sideways map.")
    p.add_argument("question", help="Research question or topic in plain language")
    p.add_argument("--out", default="eonrise-output", help="Output directory")
    p.add_argument("--email", default=os.getenv("CROSSREF_EMAIL", ""), help="Email for Crossref polite pool")
    p.add_argument("--openalex-key", default=os.getenv("OPENALEX_API_KEY", ""), help="OpenAlex API key")
    p.add_argument("--semantic", action="store_true", help="Use OpenAlex semantic search")
    p.add_argument("--mode", choices=("live", "assistant"), default="live", help="live: search scholarly APIs; assistant: use an offline evidence bundle")
    p.add_argument("--bundle", help="JSON evidence bundle for assistant mode")
    p.add_argument("--fixture", help=argparse.SUPPRESS)
    p.add_argument("--crossref-only", action="store_true", help="Skip OpenAlex even when a key exists")
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
    return p


def main() -> None:
    args = parser().parse_args()
    cache = Path.home() / ".cache" / "eonrise"
    http = CachedHttpClient(cache, timeout=max(1, args.http_timeout), max_retries=max(1, args.http_retries))
    bundle_path = args.bundle or args.fixture
    if args.mode == "assistant" or bundle_path:
        if not bundle_path:
            raise SystemExit("assistant mode requires --bundle PATH")
        providers = [EvidenceBundleProvider(bundle_path)]
        mode = "assistant"
    else:
        providers = [CrossrefProvider(http, args.email)]
        if args.openalex_key and not args.crossref_only:
            providers.append(OpenAlexProvider(http, args.openalex_key, args.semantic))
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
    result = run_agent(args.question, providers, policy, results_per_query=max(1, args.results))
    result["mode"] = mode
    result["input_bundle"] = str(Path(bundle_path).resolve()) if bundle_path else ""
    if not args.no_memory:
        try:
            MemoryStore(cache / "memory.jsonl").append_run(result)
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
        "gaps": result["gaps"],
        "output": str(Path(args.out).resolve()),
    }, indent=2))


if __name__ == "__main__":
    main()
