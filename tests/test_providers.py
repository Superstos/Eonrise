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


if __name__ == "__main__":
    unittest.main()
