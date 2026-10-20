from __future__ import annotations

import hashlib
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from xml.etree import ElementTree
from xml.parsers import expat

from . import __version__
from .models import Paper

class ProviderError(RuntimeError):
    pass
class ProviderUnavailable(ProviderError):
    """A provider told us to come back later. Retrying inside this run cannot help."""
    def __init__(self, message: str, retry_after: float = 0.0):
        super().__init__(message)
        self.retry_after = retry_after
class SearchProvider(Protocol):
    name: str
    def search(self, query: str, limit: int) -> list[Paper]:
        ...

@dataclass
class CachedHttpClient:
    cache_dir: Path
    user_agent: str = f"eonrise/{__version__}"
    timeout: int = 12
    max_retries: int = 2
    min_interval: float = 0.15
    cache_ttl_seconds: int = 7 * 24 * 60 * 60
    # A Retry-After longer than this is a quota window, not a burst limit: waiting it out
    # inside one run is impossible, so the host is dropped for the rest of the run.
    cooldown_threshold: float = 120.0
    def __post_init__(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_request = 0.0
        self._host_last: dict[str, float] = {}
        self._host_cooldown: dict[str, str] = {}
    def get_json(self, url: str, headers: dict[str, str] | None = None) -> dict:
        return self._get(url, {"Accept": "application/json", **(headers or {})}, ".json", json.loads)

    def get_xml(self, url: str, headers: dict[str, str] | None = None) -> ElementTree.Element:
        """For sources that answer in XML, such as arXiv's Atom feed."""
        return self._get(url, headers or {}, ".xml", _parse_xml)

    def _get(self, url, headers, suffix, decode):
        key = hashlib.sha256(url.encode()).hexdigest()
        cache_file = self.cache_dir / f"{key}{suffix}"
        if self._cache_fresh(cache_file):
            return decode(cache_file.read_bytes())
        host = urllib.parse.urlsplit(url).netloc
        if host in self._host_cooldown:
            # 16 doomed requests per run is how the previous build spent a rate limit.
            raise ProviderUnavailable(self._host_cooldown[host])
        return self._fetch(url, {"User-Agent": self.user_agent, **headers}, cache_file, decode)

    def _cache_fresh(self, cache_file):
        return cache_file.exists() and time.time() - cache_file.stat().st_mtime <= self.cache_ttl_seconds

    def _fetch(self, url, headers, cache_file, decode):
        host = urllib.parse.urlsplit(url).netloc
        last_error = None
        for attempt in range(self.max_retries):
            self._wait_for_host(host)
            try:
                return self._request(url, headers, cache_file, decode)
            except urllib.error.HTTPError as exc:
                last_error = exc
                if not self._retry_http(exc, host):
                    break
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ElementTree.ParseError) as exc:
                last_error = exc
            time.sleep(2**attempt)
        self._request_failed(url, last_error)

    def _wait_for_host(self, host):
        interval = max(self.min_interval, _HOST_INTERVALS.get(host, 0.0))
        elapsed = time.monotonic() - self._host_last.get(host, 0.0)
        if elapsed < interval:
            time.sleep(interval - elapsed)

    def _request(self, url, headers, cache_file, decode):
        host = urllib.parse.urlsplit(url).netloc
        self._last_request = self._host_last[host] = time.monotonic()
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected -- every caller passes a fixed https API base plus urlencoded parameters
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=self.timeout) as response:
            # Bytes, not text: XML names its own encoding, and json.loads detects UTF-8/16/32.
            body = response.read()
            payload = decode(body)
            cache_file.write_bytes(body)
            return payload

    def _retry_http(self, exc, host):
        if exc.code == 429:
            wait = _retry_after_seconds(exc)
            if wait >= self.cooldown_threshold:
                message = f"{host} rate limited, retry in {int(wait)}s"
                self._host_cooldown[host] = message
                raise ProviderUnavailable(message, wait) from exc
        elif exc.code not in {500, 502, 503, 504}:
            return False
        return True

    def _request_failed(self, url, last_error):
        # The query string carries api_key and mailto, and this text lands in report.md.
        raise ProviderError(f"Request failed: {urllib.parse.urlsplit(url)._replace(query='').geturl()}: {last_error}")


# arXiv asks for one request every 3 seconds (info.arxiv.org/help/api/tou.html).
_HOST_INTERVALS = {"export.arxiv.org": 3.0}


def _parse_xml(body):
    # Expat caps entity expansion only from Python 3.8.12, and Eonrise supports 3.8.0. No API we
    # call sends a DTD, so a first pass refuses one at its opening tag, in any encoding, before
    # any entity is declared; ElementTree never fetches external entities.
    guard = expat.ParserCreate()
    guard.StartDoctypeDeclHandler = _refuse_dtd
    try:
        guard.Parse(body, True)
        return ElementTree.fromstring(body)  # nosemgrep: python.lang.security.use-defused-xml-parse.use-defused-xml-parse
    except (expat.ExpatError, LookupError, ValueError) as exc:
        # An unknown or unsupported declared encoding raises LookupError or ValueError.
        raise ElementTree.ParseError(str(exc)) from exc


def _refuse_dtd(*_):
    raise ValueError("XML with a DTD refused")


def _retry_after_seconds(exc) -> float:
    raw = (getattr(exc, "headers", None) or {}).get("Retry-After", "")
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return 0.0

def _strip_markup(value):
    if not value:
        return ""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()
def _first_title(raw):
    return str(raw[0]) if isinstance(raw, list) and raw else str(raw or "")
def _crossref_year(item):
    for key in ("published-print", "published-online", "issued", "created"):
        parts = item.get(key, {}).get("date-parts", [])
        if parts and parts[0]:
            try:
                return int(parts[0][0])
            except (TypeError, ValueError):
                pass
    return None

class CrossrefProvider:
    name = "crossref"
    def __init__(self, http, email=""):
        self.http, self.email = http, email
    def search(self, query, limit=20):
        params = {"query.bibliographic": query, "rows": str(max(1, min(limit, 100)))}
        if self.email:
            params["mailto"] = self.email
        payload = self.http.get_json("https://api.crossref.org/works?" + urllib.parse.urlencode(params))
        return _parsed(self._paper, payload.get("message", {}).get("items", []), query)

    def _paper(self, item, query):
        doi = str(item.get("DOI", "")).strip()
        title = _strip_markup(_first_title(item.get("title")))
        if not title or _crossref_retracted(item):
            return None
        # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1 -- a stable ID for papers without a DOI, not security; changing it would re-key stored papers
        paper_id = doi or hashlib.sha1(title.lower().encode(), usedforsecurity=False).hexdigest()
        return Paper(
            paper_id, title, _strip_markup(item.get("abstract")),
            str(item.get("URL", "")), doi, _crossref_year(item), int(item.get("is-referenced-by-count",0) or 0), self.name,
            [], _crossref_subjects(item), [], _first_title(item.get("container-title")), [query])

def _restore_abstract(index):
    if not index:
        return ""
    positions = [(int(offset), word) for word, offsets in index.items() for offset in offsets]
    return " ".join(word for _, word in sorted(positions))
def _display_name(value):
    return str(value.get("display_name", "")) if isinstance(value, dict) else ""

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
        params = {self._search_key(): query, "per_page": str(max(1,min(limit,100))),
                  "select": "id,doi,title,abstract_inverted_index,publication_year,cited_by_count,primary_topic,topics,keywords",
                  # A retracted paper must never reach a harvest; OpenAlex flags them from Retraction Watch.
                  "filter": "is_retracted:false"}
        self._identify(params)
        payload = self.http.get_json("https://api.openalex.org/works?" + urllib.parse.urlencode(params))
        return _parsed(self._paper, payload.get("results", []), query)

    def _search_key(self):
        semantic = self.semantic and bool(self.api_key)
        return "search.semantic" if semantic else "search"

    def _identify(self, params):
        if self.api_key:
            params["api_key"] = self.api_key
        elif self.email:
            params["mailto"] = self.email

    def _paper(self, item, query):
        title = str(item.get("title", "")).strip()
        if not title:
            return None
        primary = item.get("primary_topic") or {}
        # Only the subfield: domain and field are labels like "Physical Sciences" or
        # "Computer Science", which crowded out every real neighbour in live runs.
        hierarchy = _subfield_names(primary)
        topic_name = _display_name(primary)
        keywords = _display_names(item.get("keywords", [])) + _display_names(item.get("topics", [])[:5])
        return Paper(
            _openalex_id(item), title, _restore_abstract(item.get("abstract_inverted_index")),
            _openalex_url(item), _doi(item), item.get("publication_year"), _citation_count(item, "cited_by_count"), self.name,
            list(dict.fromkeys(keywords)), hierarchy, _topic_names(topic_name), "", [query])

class EvidenceBundleProvider:
    """One or more agent-gathered bundles. Evidence arrives from several searchers at once,
    so a path may be a file, a folder of `*.json` files, or a list of either. The same DOI
    or title from two bundles is merged on load, keeping the richer record."""
    name = "assistant_bundle"
    def __init__(self, path):
        from .evidence import _dedupe_papers
        self.paths = _bundle_files(path)
        merged = []
        if not self.paths:
            raise ProviderError(f"No evidence bundle found at {path}")
        for file in self.paths:
            merged, _ = _dedupe_papers(merged, _bundle_papers(file))
        self.path, self.papers = self.paths[0], merged
    def search(self, query, limit=20):
        query_tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
        ranked = []
        for paper in self.papers:
            score = _bundle_score(paper, query_tokens)
            if score > 0:
                ranked.append((score, self._clone(paper, query)))
        ranked.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in ranked[:limit]]

    def _clone(self, paper, query):
        clone = Paper.from_dict(paper.to_dict())
        clone.provider = clone.provider or self.name
        clone.found_by = list(dict.fromkeys([*clone.found_by, query]))
        return clone


def _bundle_files(path) -> list[Path]:
    items = path if isinstance(path, (list, tuple)) else [path]
    files = []
    for item in items:
        item = Path(item)
        files.extend(sorted(item.glob("*.json")) if item.is_dir() else [item] if item.exists() else [])
    return list(dict.fromkeys(files))

FixtureProvider = EvidenceBundleProvider

class EuropePMCProvider:
    """Keyless, no credit budget, and the richest free metadata measured: on a 20-paper
    probe it returned 20 abstracts, 18 keyword lists and 7 MeSH headings, where Crossref
    returned 16% abstracts and no subjects at all. Life-sciences weighted, so it pairs
    with a general provider rather than replacing one."""
    name = "europepmc"
    def __init__(self, http, email=""):
        self.http, self.email = http, email
    def search(self, query, limit=20):
        params = {"query": query, "format": "json", "resultType": "core",
                  "pageSize": str(max(1, min(limit, 100)))}
        if self.email:
            params["email"] = self.email
        payload = self.http.get_json("https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(params))
        return _parsed(self._paper, payload.get("resultList", {}).get("result", []), query)

    def _paper(self, item, query):
        title = _strip_markup(item.get("title"))
        if not title:
            return None
        doi = _doi(item).strip()
        keywords = _epmc_keywords(item)
        mesh = _epmc_mesh(item)
        journal = _epmc_journal(item)
        url = f"https://doi.org/{doi}" if doi else f"https://europepmc.org/article/{item.get('source','MED')}/{item.get('id','')}"
        year = _parse_year(item.get("pubYear"))
        return Paper(
            doi or f"epmc:{item.get('id','')}", title, _strip_markup(item.get("abstractText")),
            url, doi, year, _citation_count(item, "citedByCount"), self.name,
            list(dict.fromkeys(keywords)), [], list(dict.fromkeys(mesh))[:5], journal, [query])

class DoajProvider:
    """Keyless and small, but every article carries an abstract, author keywords and an
    LCC subject term — the subject label Crossref never supplies."""
    name = "doaj"
    def __init__(self, http, email=""):
        self.http = http
    def search(self, query, limit=20):
        url = ("https://doaj.org/api/search/articles/" + urllib.parse.quote(query) +
               "?" + urllib.parse.urlencode({"pageSize": str(max(1, min(limit, 100)))}))
        return _parsed(self._paper, self.http.get_json(url).get("results", []), query)

    def _paper(self, item, query):
        b = item.get("bibjson") or {}
        title = _strip_markup(b.get("title"))
        if not title:
            return None
        doi = _doaj_doi(b)
        subjects = _doaj_subjects(b)
        link = _doaj_link(b)
        year = _parse_year(b.get("year"))
        return Paper(
            doi or f"doaj:{item.get('id','')}", title, _strip_markup(b.get("abstract")),
            f"https://doi.org/{doi}" if doi else link, doi, year, 0, self.name,
            _doaj_keywords(b), list(dict.fromkeys(subjects)), [], _doaj_journal(b), [query])

class SemanticScholarProvider:
    """Broad coverage and its own field-of-study labels. The keyless pool is shared and
    answers 429 under any load, so a free key (S2_API_KEY) is what makes it usable."""
    name = "semanticscholar"
    FIELDS = "title,abstract,fieldsOfStudy,year,citationCount,externalIds,venue"
    def __init__(self, http, api_key=""):
        self.http, self.api_key = http, api_key or os.getenv("S2_API_KEY", "")
    def search(self, query, limit=20):
        url = "https://api.semanticscholar.org/graph/v1/paper/search?" + urllib.parse.urlencode(
            {"query": query, "limit": str(max(1, min(limit, 100))), "fields": self.FIELDS})
        payload = self.http.get_json(url, {"x-api-key": self.api_key} if self.api_key else None)
        return _parsed(self._paper, payload.get("data", []), query)

    def _paper(self, item, query):
        title = _strip_markup(item.get("title"))
        if not title:
            return None
        doi = _s2_doi(item)
        fields = _s2_fields(item)
        return Paper(
            doi or f"s2:{item.get('paperId','')}", title, _strip_markup(item.get("abstract")),
            f"https://doi.org/{doi}" if doi else f"https://www.semanticscholar.org/paper/{item.get('paperId','')}", doi, item.get("year"), _citation_count(item, "citationCount"), self.name,
            [], fields, [], _s2_venue(item), [query])

class CoreProvider:
    """Open-access full texts with abstracts on every hit. Keyless requests answer for a
    while and then 429, so treat CORE_API_KEY as required for a real run."""
    name = "core"
    def __init__(self, http, api_key=""):
        self.http, self.api_key = http, api_key or os.getenv("CORE_API_KEY", "")
    def search(self, query, limit=20):
        url = "https://api.core.ac.uk/v3/search/works?" + urllib.parse.urlencode(
            {"q": query, "limit": str(max(1, min(limit, 100)))})
        payload = self.http.get_json(url, {"Authorization": f"Bearer {self.api_key}"} if self.api_key else None)
        return _parsed(self._paper, payload.get("results", []), query)

    def _paper(self, item, query):
        title = _strip_markup(item.get("title"))
        if not title:
            return None
        doi = _doi(item)
        subjects = _core_subjects(item)
        return Paper(
            doi or f"core:{item.get('id','')}", title, _strip_markup(item.get("abstract")),
            f"https://doi.org/{doi}" if doi else _core_download(item), doi, item.get("yearPublished"), 0, self.name,
            [], list(dict.fromkeys(subjects))[:5], [], "", [query])


class OpenAireProvider:
    """Keyless EU open-access graph, deduplicated across repositories. Tested 2026-10-20:
    352 hits for a 3-word query with abstracts, keywords and open-access flags, no key."""
    name = "openaire"
    def __init__(self, http, email=""):
        self.http = http
    def search(self, query, limit=20):
        url = "https://api.openaire.eu/graph/v1/researchProducts?" + urllib.parse.urlencode(
            {"search": query, "type": "publication", "pageSize": str(max(1, min(limit, 100)))})
        return _parsed(self._paper, self.http.get_json(url).get("results") or [], query)

    def _paper(self, item, query):
        title = _strip_markup(item.get("mainTitle"))
        if not title:
            return None
        doi = _openaire_doi(item)
        return Paper(
            doi or f"openaire:{item.get('id','')}", title, _strip_markup(" ".join(str(x) for x in item.get("descriptions") or [] if x)),
            f"https://doi.org/{doi}" if doi else f"https://explore.openaire.eu/search/result?id={item.get('id','')}",
            doi, _parse_year(str(item.get("publicationDate") or "")[:4]), _openaire_citations(item), self.name,
            [], _openaire_subjects(item), [], (item.get("container") or {}).get("name") or "", [query])

class OpenReviewProvider:
    """Keyless conference papers (ICLR, NeurIPS workshops, Agents4Science). The venue keeps
    'Withdrawn' or 'Desk Rejected' visible as a quality signal."""
    name = "openreview"
    def __init__(self, http, email=""):
        self.http = http
    def search(self, query, limit=20):
        # source=forum returns submissions only; without it, reviews come back carrying their
        # own titles and dates in place of the paper's.
        url = "https://api2.openreview.net/notes/search?" + urllib.parse.urlencode(
            {"term": query, "source": "forum", "limit": str(max(1, min(limit, 100)))})
        return _parsed(self._paper, self.http.get_json(url).get("notes") or [], query)

    def _paper(self, item, query):
        content = item.get("content") or {}
        title = _strip_markup(_openreview_value(content, "title"))
        if not title or (item.get("forum") or item.get("id")) != item.get("id"):
            return None
        keywords = _openreview_value(content, "keywords")
        return Paper(
            f"openreview:{item.get('id', '')}", title, _strip_markup(_openreview_value(content, "abstract")),
            f"https://openreview.net/forum?id={item.get('id', '')}", "", _openreview_year(item), 0, self.name,
            keywords if isinstance(keywords, list) else [], [], [], _openreview_value(content, "venue") or "", [query])

class ArxivProvider:
    """Keyless preprints, mostly physics, maths, CS and AI, months before journals. Tested
    2026-10-20: 7 of 20 arXiv hits for one question were missing from OpenAIRE."""
    name = "arxiv"
    def __init__(self, http, email=""):
        self.http = http
    def search(self, query, limit=20):
        # Bare words are ORed, so 'group' and 'experiment' pulled particle physics; all words
        # ANDed returned 0 for 5-word queries. The first three in the abstract stayed on shape.
        words = re.findall(r"\w+", query)[:3]
        url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
            {"search_query": " AND ".join(f"abs:{w}" for w in words), "max_results": str(max(1, min(limit, 100))), "sortBy": "relevance"})
        entries = self.http.get_xml(url).findall(f"{_ATOM}entry")
        # A bad query comes back as a feed whose one entry is the error message.
        errors = [e for e in entries if "/api/errors" in (e.findtext(f"{_ATOM}id") or "")]
        if errors:
            raise ProviderError(f"arXiv: {(errors[0].findtext(f'{_ATOM}summary') or '').strip()}")
        return _parsed(self._paper, entries, query)

    def _paper(self, entry, query):
        title = _strip_markup(entry.findtext(f"{_ATOM}title"))
        arxiv_id = _arxiv_id(entry.findtext(f"{_ATOM}id", ""))
        if not title or not arxiv_id:
            return None
        doi = entry.findtext(f"{_ARXIV}doi", "").strip()
        fields = [_arxiv_field(c.get("term", "")) for c in entry.findall(f"{_ATOM}category")]
        return Paper(
            doi or f"arxiv:{arxiv_id}", title, _strip_markup(entry.findtext(f"{_ATOM}summary")),
            f"https://arxiv.org/abs/{arxiv_id}", doi, _parse_year(entry.findtext(f"{_ATOM}published", "")[:4]),
            0, self.name, [], list(dict.fromkeys(f for f in fields if f)), [],
            entry.findtext(f"{_ARXIV}journal_ref", "").strip() or "arXiv", [query])


def _arxiv_id(entry_id):
    """'http://arxiv.org/abs/2306.15804v2' -> '2306.15804'; anything else, such as an error entry, -> ''."""
    if "/abs/" not in entry_id:
        return ""
    return re.sub(r"v\d+$", "", entry_id.split("/abs/", 1)[1])


# arXiv subject codes (cs.CL, physics.soc-ph) by archive, named the way OpenAlex names fields.
_ARXIV_FIELDS = {
    "cs": "Computer Science", "math": "Mathematics", "stat": "Statistics", "econ": "Economics",
    "q-bio": "Biology", "q-fin": "Finance", "eess": "Electrical Engineering", "physics": "Physics",
    "astro-ph": "Astronomy", "cond-mat": "Physics", "gr-qc": "Physics", "hep-ex": "Physics",
    "hep-lat": "Physics", "hep-ph": "Physics", "hep-th": "Physics", "math-ph": "Physics",
    "nlin": "Physics", "nucl-ex": "Physics", "nucl-th": "Physics", "quant-ph": "Physics",
}


def _arxiv_field(code):
    """Unknown archives (cross-listed journal codes such as 'I.2.7') yield no field."""
    return _ARXIV_FIELDS.get(code.split(".", 1)[0], "")


_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"

def _openaire_doi(item):
    return next((x.get("value", "") for x in item.get("pids") or [] if x.get("scheme") == "doi"), "")


def _openaire_subjects(item):
    subjects = [((x.get("subject") or {}).get("value") or "").strip() for x in item.get("subjects") or []]
    return list(dict.fromkeys(s for s in subjects if s))[:8]


def _openaire_citations(item):
    return int(((item.get("indicators") or {}).get("citationImpact") or {}).get("citationCount") or 0)


def _openreview_year(item):
    return time.gmtime(item["cdate"] / 1000).tm_year if item.get("cdate") is not None else None


def _openreview_value(content, key):
    return (content.get(key) or {}).get("value")


def _parsed(parse, items, query):
    """Papers parsed from a provider's result items; items without a title are skipped."""
    return [paper for paper in (parse(item, query) for item in items) if paper is not None]


def _crossref_retracted(item):
    """A retracted or withdrawn paper (Retraction Watch data in `updated-by`), or the notice
    that retracts one (`update-to`): neither is evidence."""
    updates = (item.get("updated-by") or []) + (item.get("update-to") or [])
    return any(u.get("type") in {"retraction", "withdrawal"} for u in updates if isinstance(u, dict))


def _crossref_subjects(item):
    return [str(x).strip() for x in item.get("subject", []) if str(x).strip()]


def _display_names(items):
    return [_display_name(x) for x in items if _display_name(x)]


def _subfield_names(primary):
    return [_display_name(primary.get("subfield"))] if _display_name(primary.get("subfield")) else []


def _topic_names(topic_name):
    return [topic_name] if topic_name else []


def _openalex_id(item):
    return str(item.get("id", "")) or str(item.get("doi", ""))


def _openalex_url(item):
    return str(item.get("doi") or item.get("id") or "")


def _doi(item):
    return str(item.get("doi") or "")


def _citation_count(item, name):
    return int(item.get(name, 0) or 0)


def _bundle_rows(file):
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProviderError(f"Evidence bundle {file} is not valid JSON: {exc}") from exc
    if isinstance(raw, list):
        return raw
    return raw.get("papers", []) if isinstance(raw, dict) else None


def _bundle_papers(file):
    rows = _bundle_rows(file)
    if not isinstance(rows, list):
        raise ProviderError(f"Evidence bundle {file} must contain a paper list")
    return [Paper.from_dict(x) for x in rows if isinstance(x, dict) and x.get("title")]


def _bundle_score(paper, query_tokens):
    text = " ".join([paper.title, paper.abstract, *paper.keywords, *paper.fields, *paper.topic_path]).lower()
    tokens = set(re.findall(r"[a-z0-9]+", text))
    return len(query_tokens & tokens) + min(paper.cited_by_count, 100) / 500


def _epmc_keywords(item):
    return [k for k in ((item.get("keywordList") or {}).get("keyword") or []) if k]


def _epmc_mesh(item):
    return [m.get("descriptorName") for m in ((item.get("meshHeadingList") or {}).get("meshHeading") or [])
            if m.get("descriptorName")]


def _epmc_journal(item):
    return ((item.get("journalInfo") or {}).get("journal") or {}).get("title") or ""


def _parse_year(value):
    try:
        return int(value or 0) or None
    except (TypeError, ValueError):
        return None


def _doaj_doi(b):
    return next((i.get("id", "") for i in b.get("identifier", []) if i.get("type") == "doi"), "")


def _doaj_subjects(b):
    return [s.get("term") for s in b.get("subject", []) if s.get("term")]


def _doaj_link(b):
    return next((link.get("url", "") for link in b.get("link", []) if link.get("url")), "")


def _doaj_keywords(b):
    return list(dict.fromkeys(b.get("keywords") or []))


def _doaj_journal(b):
    return (b.get("journal") or {}).get("title", "")


def _s2_doi(item):
    return str((item.get("externalIds") or {}).get("DOI") or "")


def _s2_fields(item):
    return [f for f in (item.get("fieldsOfStudy") or []) if f]


def _s2_venue(item):
    return item.get("venue") or ""


def _core_subjects(item):
    return [s for s in (item.get("subjects") or []) if isinstance(s, str)]


def _core_download(item):
    return str(item.get("downloadUrl") or "")
