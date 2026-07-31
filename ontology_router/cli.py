from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .engine import run_router
from .providers import CachedHttpClient, CrossrefProvider, EvidenceBundleProvider, OpenAlexProvider
from .report import write_outputs


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Expand a research question into grounded search routes.")
    p.add_argument("question", help="Research question in plain language")
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
    result = run_router(
        args.question,
        providers,
        max_rounds=max(1, args.max_rounds),
        results_per_query=max(1, args.results),
    )
    result["mode"] = mode
    result["input_bundle"] = str(Path(bundle_path).resolve()) if bundle_path else ""
    write_outputs(result, args.out)
    print(json.dumps({
        "mode": mode,
        "status": result["status"],
        "stop_reason": result["stop_reason"],
        "papers": len(result["papers"]),
        "gaps": result["gaps"],
        "output": str(Path(args.out).resolve()),
    }, indent=2))


if __name__ == "__main__":
    main()
