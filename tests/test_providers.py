from __future__ import annotations

import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from eonrise import providers
from eonrise.providers import CachedHttpClient, OpenAlexProvider


class SubfieldOnlyTests(unittest.TestCase):
    """OpenAlex domain and field labels are shelf names; only the subfield is a neighbour."""

    def test_only_the_subfield_is_kept(self):
        http = OpenAlexKeylessTests._FakeHttp()
        papers = OpenAlexProvider(http).search("q", 5)
        self.assertEqual(papers[0].fields, ["Information Systems"])
        self.assertNotIn("Computer Science", papers[0].fields)
        self.assertNotIn("Physical Sciences", papers[0].fields)
        self.assertIn("Ontology engineering", papers[0].topic_path)


class OpenAlexKeylessTests(unittest.TestCase):
    """OpenAlex answers without a key; the old code refused to call it."""

    class _FakeHttp:
        def __init__(self):
            self.urls = []

        def get_json(self, url, headers=None):
            self.urls.append(url)
            return {"results": [{"id": "W1", "title": "Keyless result",
                                 "abstract_inverted_index": {"Mapping": [0], "quality": [1]},
                                 "publication_year": 2024,
                                 "primary_topic": {"display_name": "Ontology engineering",
                                                   "domain": {"display_name": "Physical Sciences"},
                                                   "field": {"display_name": "Computer Science"},
                                                   "subfield": {"display_name": "Information Systems"}},
                                 "keywords": [{"display_name": "ontology mapping"}]}]}

    def test_search_without_key_returns_papers(self):
        http = self._FakeHttp()
        papers = OpenAlexProvider(http).search("ontology mapping quality", 5)
        self.assertEqual(len(papers), 1)
        self.assertTrue(papers[0].abstract)
        self.assertTrue(papers[0].topic_path or papers[0].fields)
        self.assertNotIn("api_key", http.urls[0])

    def test_key_is_still_used_when_present(self):
        http = self._FakeHttp()
        OpenAlexProvider(http, api_key="secret").search("q", 5)
        self.assertIn("api_key=secret", http.urls[0])

    def test_email_becomes_mailto_when_keyless(self):
        http = self._FakeHttp()
        OpenAlexProvider(http, email="a@b.c").search("q", 5)
        self.assertIn("mailto=a%40b.c", http.urls[0])


def _raiser(error, calls):
    def fake(request, timeout=0):
        calls.append(getattr(request, "full_url", request))
        raise error
    return fake


class ProviderCooldownTests(unittest.TestCase):
    """A long Retry-After is a quota window: one run cannot wait it out."""

    def test_long_retry_after_stops_further_calls_to_that_host(self):
        err = urllib.error.HTTPError("https://api.openalex.org/works?q=1", 429, "Too Many Requests",
                                     {"Retry-After": "30746"}, None)
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            client = CachedHttpClient(cache_dir=Path(tmp), min_interval=0.0, max_retries=2)
            with mock.patch("urllib.request.urlopen", side_effect=_raiser(err, calls)), mock.patch("time.sleep"):
                with self.assertRaises(providers.ProviderUnavailable):
                    client.get_json("https://api.openalex.org/works?q=1")
                with self.assertRaises(providers.ProviderUnavailable):
                    client.get_json("https://api.openalex.org/works?q=2")
        self.assertEqual(len(calls), 1, "second call must fail fast without touching the network")

    def test_short_retry_after_still_retries(self):
        err = urllib.error.HTTPError("https://api.crossref.org/works?q=1", 429, "Too Many Requests",
                                     {"Retry-After": "1"}, None)
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            client = CachedHttpClient(cache_dir=Path(tmp), min_interval=0.0, max_retries=2)
            with mock.patch("urllib.request.urlopen", side_effect=_raiser(err, calls)), mock.patch("time.sleep"):
                with self.assertRaises(providers.ProviderError) as ctx:
                    client.get_json("https://api.crossref.org/works?q=1")
        self.assertNotIsInstance(ctx.exception, providers.ProviderUnavailable)
        self.assertEqual(len(calls), 2, "a burst limit is worth retrying inside the run")

    def test_failed_request_error_keeps_keys_and_email_out(self):
        url = "https://api.openalex.org/works?search=q&api_key=SECRETKEY&mailto=a%40b.c"
        err = urllib.error.URLError("timed out")
        with tempfile.TemporaryDirectory() as tmp:
            client = CachedHttpClient(cache_dir=Path(tmp), min_interval=0.0, max_retries=1)
            with mock.patch("urllib.request.urlopen", side_effect=_raiser(err, [])), mock.patch("time.sleep"):
                with self.assertRaises(providers.ProviderError) as ctx:
                    client.get_json(url)
        message = str(ctx.exception)
        self.assertIn("https://api.openalex.org/works", message)
        self.assertNotIn("SECRETKEY", message)
        self.assertNotIn("a%40b.c", message)


class _Response:
    def __init__(self, body): self.body = body
    def read(self): return self.body
    def __enter__(self): return self
    def __exit__(self, *exc): return False


def _replay(bodies, calls):
    def fake(request, timeout=0):
        calls.append(getattr(request, "full_url", request))
        return _Response(bodies.pop(0))
    return fake


class XmlClientTests(unittest.TestCase):
    """get_xml shares get_json's cache, retry and cooldown; these pin what XML adds."""

    def _client(self, tmp, **kw):
        return CachedHttpClient(cache_dir=Path(tmp), min_interval=0.0, **kw)

    def test_declared_encoding_is_honoured_live_and_from_cache(self):
        body = b'<?xml version="1.0" encoding="ISO-8859-1"?><r>caf\xe9</r>'
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(tmp)
            with mock.patch("urllib.request.urlopen", side_effect=_replay([body], calls)):
                first = client.get_xml("https://export.arxiv.org/api/query?q=1")
                second = client.get_xml("https://export.arxiv.org/api/query?q=1")
        self.assertEqual((first.text, second.text, len(calls)), ("café", "café", 1))

    def test_malformed_xml_is_retried_and_never_cached(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(tmp, max_retries=2)
            with mock.patch("urllib.request.urlopen", side_effect=_replay([b"<r>", b"<r>ok</r>"], calls)),                     mock.patch("time.sleep"):
                self.assertEqual(client.get_xml("https://export.arxiv.org/api/query?q=2").text, "ok")
            self.assertEqual([f.read_bytes() for f in Path(tmp).iterdir()], [b"<r>ok</r>"])
        self.assertEqual(len(calls), 2)

    def test_a_dtd_is_refused_so_entity_bombs_cannot_expand(self):
        bomb = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "x">]><r>&a;</r>'
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(tmp, max_retries=1)
            with mock.patch("urllib.request.urlopen", side_effect=_replay([bomb], [])), mock.patch("time.sleep"):
                with self.assertRaises(providers.ProviderError):
                    client.get_xml("https://export.arxiv.org/api/query?q=3")
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_a_dtd_is_refused_in_utf16_too(self):
        for encoding in ("utf-16", "utf-16-le", "utf-16-be"):
            bomb = '<?xml version="1.0" encoding="%s"?><!DOCTYPE r [<!ENTITY a "x">]><r>&a;</r>' % encoding
            body = bomb.encode(encoding)
            with self.subTest(encoding=encoding), tempfile.TemporaryDirectory() as tmp:
                client = self._client(tmp, max_retries=1)
                with mock.patch("urllib.request.urlopen", side_effect=_replay([body], [])), mock.patch("time.sleep"):
                    with self.assertRaises(providers.ProviderError):
                        client.get_xml("https://export.arxiv.org/api/query?q=6")

    def test_an_unknown_declared_encoding_is_retried_not_raised_raw(self):
        calls = []
        bodies = [b'<?xml version="1.0" encoding="xxx"?><r/>', b"<r>ok</r>"]
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(tmp, max_retries=2)
            with mock.patch("urllib.request.urlopen", side_effect=_replay(bodies, calls)), mock.patch("time.sleep"):
                self.assertEqual(client.get_xml("https://export.arxiv.org/api/query?q=7").text, "ok")
        self.assertEqual(len(calls), 2)

    def test_arxiv_requests_are_spaced_three_seconds_apart(self):
        sleeps = []
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(tmp)
            with mock.patch("urllib.request.urlopen", side_effect=_replay([b"<r/>", b"<r/>"], [])),                     mock.patch("time.sleep", side_effect=sleeps.append):
                client.get_xml("https://export.arxiv.org/api/query?q=4")
                client.get_xml("https://export.arxiv.org/api/query?q=5")
        self.assertTrue(sleeps and sleeps[-1] > 2.5, sleeps)

    def test_json_cache_written_by_older_versions_still_reads(self):
        url = "https://api.crossref.org/works?q=old"
        with tempfile.TemporaryDirectory() as tmp:
            import hashlib
            Path(tmp, hashlib.sha256(url.encode()).hexdigest() + ".json").write_text('{"a": "é"}', encoding="utf-8")
            with mock.patch("urllib.request.urlopen") as net:
                self.assertEqual(self._client(tmp).get_json(url), {"a": "é"})
            net.assert_not_called()


if __name__ == "__main__":
    unittest.main()
