from __future__ import annotations

import hashlib, html, json, os, re, time
import urllib.error, urllib.parse, urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .models import Paper

class ProviderError(RuntimeError): pass
class ProviderUnavailable(ProviderError):
    """A provider told us to come back later. Retrying inside this run cannot help."""
    def __init__(self, message: str, retry_after: float = 0.0):
        super().__init__(message); self.retry_after = retry_after
class SearchProvider(Protocol):
    name: str
    def search(self, query: str, limit: int) -> list[Paper]: ...

@dataclass
class CachedHttpClient:
    cache_dir: Path
    user_agent: str = "eonrise/0.5"
    timeout: int = 12
    max_retries: int = 2
    min_interval: float = 0.15
    cache_ttl_seconds: int = 7 * 24 * 60 * 60
    # A Retry-After longer than this is a quota window, not a burst limit: waiting it out
    # inside one run is impossible, so the host is dropped for the rest of the run.
    cooldown_threshold: float = 120.0
    def __post_init__(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True); self._last_request = 0.0
        self._host_last: dict[str, float] = {}; self._host_cooldown: dict[str, str] = {}
    def get_json(self, url: str, headers: dict[str, str] | None = None) -> dict:
        key = hashlib.sha256(url.encode()).hexdigest(); cache_file = self.cache_dir / f"{key}.json"
        if cache_file.exists() and time.time() - cache_file.stat().st_mtime <= self.cache_ttl_seconds:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        host = urllib.parse.urlsplit(url).netloc
        if host in self._host_cooldown:
            # 16 doomed requests per run is how the previous build spent a rate limit.
            raise ProviderUnavailable(self._host_cooldown[host])
        merged = {"User-Agent": self.user_agent, "Accept": "application/json"}; merged.update(headers or {})
        last_error = None
        for attempt in range(self.max_retries):
            elapsed = time.monotonic() - self._host_last.get(host, 0.0)
            if elapsed < self.min_interval: time.sleep(self.min_interval - elapsed)
            try:
                self._last_request = self._host_last[host] = time.monotonic()
                with urllib.request.urlopen(urllib.request.Request(url, headers=merged), timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode()); cache_file.write_text(json.dumps(payload)); return payload
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code == 429:
                    wait = _retry_after_seconds(exc)
                    if wait >= self.cooldown_threshold:
                        message = f"{host} rate limited, retry in {int(wait)}s"
                        self._host_cooldown[host] = message
                        raise ProviderUnavailable(message, wait) from exc
                elif exc.code not in {500,502,503,504}: break
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc: last_error = exc
            time.sleep(2**attempt)
        raise ProviderError(f"Request failed: {url}: {last_error}")

def _retry_after_seconds(exc) -> float:
    raw = (getattr(exc, "headers", None) or {}).get("Retry-After", "")
    try: return float(str(raw).strip())
    except (TypeError, ValueError): return 0.0

def _strip_markup(value):
    if not value: return ""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()
def _first_title(raw): return str(raw[0]) if isinstance(raw, list) and raw else str(raw or "")
def _crossref_year(item):
    for key in ("published-print","published-online","issued","created"):
        parts = item.get(key, {}).get("date-parts", [])
        if parts and parts[0]:
            try: return int(parts[0][0])
            except (TypeError, ValueError): pass
    return None

class CrossrefProvider:
    name = "crossref"
    def __init__(self, http, email=""): self.http, self.email = http, email
    def search(self, query, limit=20):
        params = {"query.bibliographic": query, "rows": str(max(1,min(limit,100)))}
        if self.email: params["mailto"] = self.email
        payload = self.http.get_json("https://api.crossref.org/works?" + urllib.parse.urlencode(params))
        papers = []
        for item in payload.get("message", {}).get("items", []):
            doi = str(item.get("DOI", "")).strip(); title = _strip_markup(_first_title(item.get("title")))
            if not title: continue
            papers.append(Paper(doi or hashlib.sha1(title.lower().encode()).hexdigest(), title, _strip_markup(item.get("abstract")), str(item.get("URL", "")), doi, _crossref_year(item), int(item.get("is-referenced-by-count",0) or 0), self.name, [], [str(x).strip() for x in item.get("subject",[]) if str(x).strip()], [], _first_title(item.get("container-title")), [query]))
        return papers

def _restore_abstract(index):
    if not index: return ""
    positions = [(int(offset), word) for word, offsets in index.items() for offset in offsets]
    return " ".join(word for _, word in sorted(positions))
def _display_name(value): return str(value.get("display_name", "")) if isinstance(value, dict) else ""

class OpenAlexProvider:
    name = "openalex"
    def __init__(self, http, api_key=None, semantic=False, email=""):
        self.http = http
        self.api_key = api_key or os.getenv("OPENALEX_API_KEY", "")
        self.semantic = semantic
        self.email = email or os.getenv("CROSSREF_EMAIL", "")
    def search(self, query, limit=20):
        # OpenAlex answers without a key. A key only raises rate limits, and semantic
        # search needs one; keyless keyword search is the default because Crossref
        # carries no abstracts or topic hierarchy (measured: 16% / 0%).
        semantic = self.semantic and bool(self.api_key)
        params = {"search.semantic" if semantic else "search": query, "per_page": str(max(1,min(limit,100))), "select": "id,doi,title,abstract_inverted_index,publication_year,cited_by_count,primary_topic,topics,keywords"}
        if self.api_key: params["api_key"] = self.api_key
        elif self.email: params["mailto"] = self.email
        payload = self.http.get_json("https://api.openalex.org/works?" + urllib.parse.urlencode(params)); papers = []
        for item in payload.get("results", []):
            title = str(item.get("title", "")).strip()
            if not title: continue
            primary = item.get("primary_topic") or {}; # Only the subfield: domain and field are labels like "Physical Sciences" or
            # "Computer Science", which crowded out every real neighbour in live runs.
            hierarchy = [_display_name(primary.get("subfield"))] if _display_name(primary.get("subfield")) else []
            topic_name = _display_name(primary); keywords = [_display_name(x) for x in item.get("keywords",[]) if _display_name(x)] + [_display_name(x) for x in item.get("topics",[])[:5] if _display_name(x)]
            papers.append(Paper(str(item.get("id", "")) or str(item.get("doi", "")), title, _restore_abstract(item.get("abstract_inverted_index")), str(item.get("doi") or item.get("id") or ""), str(item.get("doi") or ""), item.get("publication_year"), int(item.get("cited_by_count",0) or 0), self.name, list(dict.fromkeys(keywords)), hierarchy, [topic_name] if topic_name else [], "", [query]))
        return papers

class EvidenceBundleProvider:
    name = "assistant_bundle"
    def __init__(self, path):
        self.path = Path(path); raw = json.loads(self.path.read_text(encoding="utf-8"))
        rows = raw if isinstance(raw, list) else raw.get("papers", []) if isinstance(raw, dict) else None
        if not isinstance(rows, list): raise ProviderError("Evidence bundle must contain a paper list")
        self.papers = [Paper.from_dict(x) for x in rows if isinstance(x, dict)]
    def search(self, query, limit=20):
        query_tokens = set(re.findall(r"[a-z0-9]+", query.lower())); ranked = []
        for paper in self.papers:
            text = " ".join([paper.title, paper.abstract, *paper.keywords, *paper.fields, *paper.topic_path]).lower(); tokens = set(re.findall(r"[a-z0-9]+", text))
            score = len(query_tokens & tokens) + min(paper.cited_by_count,100)/500
            if score > 0:
                clone = Paper.from_dict(paper.to_dict()); clone.provider = clone.provider or self.name; clone.found_by = list(dict.fromkeys([*clone.found_by, query])); ranked.append((score, clone))
        ranked.sort(key=lambda x: x[0], reverse=True); return [p for _, p in ranked[:limit]]

FixtureProvider = EvidenceBundleProvider
