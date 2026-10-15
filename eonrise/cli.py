from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from . import __version__
from .paper_store import PaperStore
from .engine import canonical_root, run_search
from .equivalence import ConceptEquivalenceStore
from .question_log import QuestionLog
from .models import SearchSettings, Paper
from .providers import (CachedHttpClient, CoreProvider, CrossrefProvider, DoajProvider,
                         EuropePMCProvider, EvidenceBundleProvider, OpenAlexProvider,
                         ProviderError, SemanticScholarProvider)
from .report import write_outputs
from . import angles
from .scheduling import ProviderStates


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Expand one topic into a grounded up/down/sideways map.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--demo", action="store_true", help="Offline run on a sample bundle shipped with Eonrise; writes only to --out")
    p.add_argument("--angles", default="", help="File of questions, one per line: run each into <out>/angle-N, then merge into angles.md")
    _provider_arguments(p)
    _run_arguments(p)
    _map_arguments(p)
    _memory_arguments(p)
    return p


def _provider_arguments(p):
    p.add_argument("question", nargs="?", help="Research question or topic in plain language")
    p.add_argument("--out", default="eonrise-output", help="Output directory")
    p.add_argument("--email", default=os.getenv("CROSSREF_EMAIL", ""), help="Email for Crossref polite pool")
    p.add_argument("--openalex-key", default=os.getenv("OPENALEX_API_KEY", ""), help="OpenAlex API key (optional: raises rate limits, enables --semantic)")
    p.add_argument("--semantic", action="store_true", help="Use OpenAlex semantic search")
    p.add_argument("--mode", choices=("live", "assistant"), default="live", help="live: search scholarly APIs; assistant: use an offline evidence bundle")
    p.add_argument("--bundle", action="append", help="JSON evidence bundle for assistant mode: a file or a folder of *.json; repeat to merge several")
    p.add_argument("--fixture", help=argparse.SUPPRESS)
    p.add_argument("--crossref-only", action="store_true", help="Crossref alone (no abstracts or topics; expect neighbor_field to stay empty)")
    p.add_argument("--providers", default="", help="Comma-separated subset of: crossref,openalex,europepmc,doaj,semanticscholar,core")
    p.add_argument("--s2-key", default=os.getenv("S2_API_KEY", ""), help="Semantic Scholar key (free; the keyless pool answers 429 under load)")
    p.add_argument("--core-key", default=os.getenv("CORE_API_KEY", ""), help="CORE key (free; keyless requests 429 after a few calls)")


def _run_arguments(p):
    p.add_argument("--max-rounds", type=int, default=6)
    p.add_argument("--results", type=int, default=20, help="Results per query/provider")
    p.add_argument("--http-timeout", type=int, default=12, help="Seconds per live API request")
    p.add_argument("--http-retries", type=int, default=2, help="Attempts per live API request")


def _map_arguments(p):
    # One root topic; these settings bound how far the search grows from it.
    p.add_argument("--max-nodes", type=int, default=400, help="Most concepts the map may hold")
    p.add_argument("--max-depth", type=int, default=4, help="How many steps a concept may sit from the root")
    p.add_argument("--up-weight", type=float, default=0.5)
    p.add_argument("--down-weight", type=float, default=1.0)
    p.add_argument("--sideways-weight", type=float, default=1.0)
    p.add_argument("--support-threshold", type=int, default=2, help="Papers needed to expand past round 1")


def _memory_arguments(p):
    p.add_argument("--no-memory", action="store_true", help="Skip appending to local memory store")
    p.add_argument("--cache-dir", default="", help="Folder for every store and cached response "
                   "(default: $EONRISE_CACHE_DIR, else ~/.cache/eonrise). Use .eonrise to keep a run inside the project")
    p.add_argument("--corpus", default="", help="Paper store to read and grow (default: <cache>/corpus.jsonl)")
    p.add_argument("--no-corpus", action="store_true", help="Do not read or write the local paper store")
    p.add_argument("--equivalence", default="", help="Concept-equivalence store to read and grow (default: <cache>/equivalence.jsonl)")
    p.add_argument("--no-equivalence", action="store_true", help="Do not read or write concept equivalences")
    p.add_argument("--query-expansion-slots", type=int, default=1, help="Per-run alternate-query slots supplied by learned equivalences")


def _bundle_providers(args: argparse.Namespace) -> list:
    bundle_path = _bundle_path(args)
    if not bundle_path:
        raise SystemExit("assistant mode requires --bundle PATH")
    try:
        return [EvidenceBundleProvider(bundle_path)]
    except ProviderError as exc:
        raise SystemExit(str(exc))


def _provider_names(args: argparse.Namespace, available: dict) -> list[str]:
    if args.providers:
        return _chosen_providers(args.providers, available)
    if args.crossref_only:
        return ["crossref"]
    keyed = [name for name, key in (("semanticscholar", args.s2_key), ("core", args.core_key)) if key]
    return ["crossref", "openalex", "europepmc", "doaj", *keyed]


def _chosen_providers(raw, available):
    chosen = [n.strip().lower() for n in raw.split(",") if n.strip()]
    _check_providers(chosen, available)
    return chosen


def _check_providers(chosen, available):
    unknown = [n for n in chosen if n not in available]
    if unknown:
        raise SystemExit(f"unknown provider(s): {', '.join(unknown)}")


def _live_providers(args: argparse.Namespace, http: CachedHttpClient, corpus: PaperStore | None) -> list:
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
    providers = [available[name]() for name in dict.fromkeys(_provider_names(args, available))]
    # The store answers first and costs nothing: a paper already held needs no API
    # credit, and OpenAlex now charges them.
    return ([corpus] if corpus is not None else []) + providers


def _settings(args: argparse.Namespace) -> SearchSettings:
    return SearchSettings(
        max_nodes=max(1, args.max_nodes),
        max_depth=max(1, args.max_depth),
        max_rounds=max(1, args.max_rounds),
        up_weight=args.up_weight,
        down_weight=args.down_weight,
        sideways_weight=args.sideways_weight,
        support_threshold=max(1, args.support_threshold),
    )


def _background(store: QuestionLog, question: str) -> set[str]:
    try:
        return store.background_labels(canonical_root(question))
    except OSError:
        return set()


def _equivalence_store(args: argparse.Namespace, cache: Path) -> tuple:
    """The store and the graph it holds, or (None, None) when off or unreadable."""
    if args.no_equivalence:
        return None, None
    try:
        store = ConceptEquivalenceStore(args.equivalence or (cache / "equivalence.jsonl"))
        return store, store.load()
    except OSError:
        return None, None


def _learn_equivalences(store: ConceptEquivalenceStore, question: str, result: dict) -> None:
    papers = []
    for row in result.get("corpus_papers") or result.get("papers", []):
        try:
            papers.append(Paper.from_dict(row))
        except (AttributeError, TypeError, ValueError):
            continue
    try:
        learned = store.observe_run(question, result.get("terms", []), papers,
                                    set(result.get("on_topic_paper_ids", [])))
        result["equivalence_store"] = str(store.path)
        result["equivalence_observations"] = len(learned)
        result["equivalence_edges"] = len(store.load().edges())
    except OSError:
        pass


def _grow_corpus(corpus: PaperStore, result: dict) -> None:
    try:
        stored = result.pop("corpus_papers", None) or result["papers"]
        result["corpus_added"] = corpus.add([Paper.from_dict(p) for p in stored])
        result["corpus_size"] = corpus.stats()["papers"]
    except OSError:
        pass


def _summary(result: dict, out: str) -> dict:
    return {
        "mode": result["mode"],
        "status": result["status"],
        "stop_reason": result["stop_reason"],
        "root_topic": result.get("root_topic", ""),
        "concepts": len(result.get("concepts", [])),
        "papers": len(result["papers"]),
        "corpus": result.get("corpus_size", 0),
        "gaps": result["gaps"],
        "providers_down": result.get("providers_down", []),
        "provider_errors": result.get("provider_errors", [])[:5],
        "output": str(Path(out).resolve()),
    }


def _search(args: argparse.Namespace, cache: Path, providers: list) -> dict:
    store = QuestionLog(cache / "memory.jsonl")
    background = _background(store, args.question)
    # Availability lives longer than one process: a source rate limited for eight hours
    # should not be re-discovered by tomorrow's run.
    states = ProviderStates(cache / "providers.json")
    equivalence, graph = _equivalence_store(args, cache)
    result = run_search(args.question, providers, _settings(args), results_per_query=max(1, args.results),
                        background=background, states=states, equivalence=graph,
                        query_expansion_slots=max(0, args.query_expansion_slots) if graph is not None else 0)
    _save_states(states)
    if equivalence is not None:
        _learn_equivalences(equivalence, args.question, result)
    result["background_terms_penalised"] = len(background)
    if not args.no_memory:
        _save_run(store, result)
    return result


def _save_states(states):
    try:
        states.save()
    except OSError:
        pass


def _save_run(store, result):
    try:
        store.append_run(result)
    except OSError:
        pass


def _args() -> argparse.Namespace:
    p = parser()
    args = p.parse_args()
    if args.demo:
        _use_demo(args)
    elif args.angles:
        args.question = args.question or "angles"
    elif not args.question:
        p.error("the following arguments are required: question (or --demo)")
    return args


def _use_demo(args):
    """The sample bundle's own question, offline, with every store left untouched."""
    bundle = Path(__file__).parent / "data" / "demo_bundle.json"
    args.question = args.question or json.loads(bundle.read_text(encoding="utf-8"))["question"]
    args.mode, args.bundle = "assistant", [str(bundle)]
    args.no_memory = args.no_corpus = args.no_equivalence = True


def main() -> None:
    args = _args()
    if args.angles:
        return _run_angles(args, Path(args.cache_dir or os.getenv("EONRISE_CACHE_DIR") or Path.home() / ".cache" / "eonrise"))
    if not args.demo:
        return _run(args, Path(args.cache_dir or os.getenv("EONRISE_CACHE_DIR") or Path.home() / ".cache" / "eonrise"))
    with tempfile.TemporaryDirectory() as cache:
        _run(args, Path(cache))


def _run(args, cache):
    http = _http(args, cache)
    corpus = _corpus(args, cache)
    bundle_path = _bundle_path(args)
    assistant = args.mode == "assistant" or bool(bundle_path)
    providers = _bundle_providers(args) if assistant else _live_providers(args, http, corpus)
    result = _search(args, cache, providers)
    result["mode"] = "assistant" if assistant else "live"
    _record_inputs(result, bundle_path)
    if corpus is not None:
        _grow_corpus(corpus, result)
    _finish_run(result, args)


def _run_angles(args, cache):
    """Runs each question in turn (stores are append-only files, so never in parallel) and merges them."""
    out = Path(args.out)
    folders = []
    for i, question in enumerate(angles.read_questions(args.angles), 1):
        folder = out / f"angle-{i}"
        try:
            _run(argparse.Namespace(**{**vars(args), "question": question, "out": str(folder)}), cache)
        except SystemExit:
            pass  # a failed angle is reported in its own folder; the others still count
        folders.append(folder)
    merged = angles.write_merge(out, folders)
    print(json.dumps({"angles": len(merged["angles"]), "papers": merged["papers"],
                      "fields": len(merged["fields"]), "output": str(out.resolve())}, indent=2))


def _finish_run(result, args):
    result.pop("corpus_papers", None)  # the store's copy, never the artifact's
    write_outputs(result, args.out)
    print(json.dumps(_summary(result, args.out), indent=2))
    # A run that retrieved nothing exited 0 and printed a brief that read like a thin
    # literature. A socket timeout against one provider is not a research finding, and a
    # caller scripting Eonrise has no other signal: `failed` is now a failed process.
    if result["status"] == "failed":
        raise SystemExit(2)


def _http(args, cache):
    return CachedHttpClient(cache, timeout=max(1, args.http_timeout), max_retries=max(1, args.http_retries))


def _corpus(args, cache):
    return None if args.no_corpus else PaperStore(args.corpus or (cache / "corpus.jsonl"))


def _bundle_path(args):
    return args.bundle or ([args.fixture] if args.fixture else None)


def _record_inputs(result, bundle_path):
    result["input_bundle"] = str(Path(bundle_path[0]).resolve()) if bundle_path else ""
    result["input_bundles"] = [str(Path(b).resolve()) for b in bundle_path or []]


if __name__ == "__main__":
    main()
