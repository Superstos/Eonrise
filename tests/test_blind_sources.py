"""Blind acceptance tests for the OpenAIRE and OpenReview sources, written by GPT-6.1 Sol from the
source contracts alone, before it saw the code (2026-10-20). Edited only where the contract changed."""

import copy
import unittest
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote, unquote_plus, urlsplit

from eonrise import cli
from eonrise.models import Paper
from eonrise.providers import (
    OpenAireProvider,
    OpenReviewProvider,
)


class FakeHTTP:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get_json(self, url, headers=None):
        self.calls.append((url, copy.deepcopy(headers)))
        return copy.deepcopy(self.response)


class BlindSourceTests(unittest.TestCase):
    SOURCES = (
        (
            OpenAireProvider,
            "openaire",
            "api.openaire.eu",
            "/graph/v1/researchProducts",
            "search",
            "pageSize",
            100,
            {"results": []},
        ),
        (
            OpenReviewProvider,
            "openreview",
            "api2.openreview.net",
            "/notes/search",
            "term",
            "limit",
            100,
            {"notes": []},
        ),
    )

    def search(self, provider_class, response, query="agent research", limit=7):
        http = FakeHTTP(response)
        provider = provider_class(http)
        papers = provider.search(query, limit)

        self.assertIsInstance(papers, list)
        self.assertTrue(http.calls)
        for paper in papers:
            self.assertIsInstance(paper, Paper)
            self.assertEqual(paper.provider, provider.name)
            self.assertEqual(paper.found_by, [query])

        for url, headers in http.calls:
            parsed = urlsplit(url)
            self.assertIsNone(parsed.username)
            self.assertIsNone(parsed.password)
            self.assertIn(headers, (None, {}))

            decoded = unquote_plus(url).lower()
            for forbidden in ("api_key", "api-key", "apikey", "email", "mailto"):
                self.assertNotIn(forbidden, decoded)

            params = parse_qs(parsed.query, keep_blank_values=True)
            for name in params:
                normalized = name.lower().replace("-", "").replace("_", "")
                self.assertNotIn(normalized, {"key", "apikey", "email", "mailto"})

        return papers, http

    def assert_request(self, http, source, query, expected_limit):
        _, _, host, path, query_param, limit_param, _, _ = source
        for url, _ in http.calls:
            parsed = urlsplit(url)
            self.assertEqual(parsed.scheme, "https")
            self.assertEqual(parsed.netloc, host)
            self.assertEqual(parsed.path, path)
            params = parse_qs(parsed.query, keep_blank_values=True)
            self.assertEqual(params.get(query_param), [query])
            self.assertEqual(params.get(limit_param), [str(expected_limit)])

            if source[1] == "openaire":
                self.assertEqual(params.get("type"), ["publication"])

    def test_endpoints_query_encoding_and_keyless_requests(self):
        query = "agent systems & café 工具"
        for source in self.SOURCES:
            with self.subTest(provider=source[1]):
                papers, http = self.search(
                    source[0], source[7], query=query, limit=7
                )
                self.assertEqual(papers, [])
                self.assert_request(http, source, query, 7)

    def test_limit_clamping(self):
        for source in self.SOURCES:
            for requested, expected in ((0, 1), (500, source[6])):
                with self.subTest(provider=source[1], limit=requested):
                    papers, http = self.search(
                        source[0], source[7], query="agents", limit=requested
                    )
                    self.assertEqual(papers, [])
                    self.assert_request(http, source, "agents", expected)

    def test_empty_result_lists(self):
        for source in self.SOURCES:
            with self.subTest(provider=source[1]):
                papers, _ = self.search(source[0], source[7])
                self.assertEqual(papers, [])

    def test_openaire_happy_path(self):
        response = {
            "results": [
                {
                    "id": "doi_dedup___::10",
                    "mainTitle": "  <b>Clean</b>title &amp; agents\n",
                    "descriptions": [
                        "First<b>part</b> &amp; more.",
                        "\nSecond sentence.  ",
                    ],
                    "publicationDate": "2026-05-03",
                    "pids": [
                        {"scheme": "arXiv", "value": "2601.1"},
                        {"scheme": "doi", "value": "10.1/x"},
                        {"scheme": "doi", "value": "10.2/later"},
                    ],
                    "subjects": [
                        {"subject": {"scheme": "keyword", "value": "AI"}},
                        {"subject": {"scheme": "keyword", "value": "ML"}},
                        {"subject": {"scheme": "keyword", "value": "AI"}},
                        {"subject": {"scheme": "keyword", "value": ""}},
                    ],
                    "indicators": {"citationImpact": {"citationCount": 3.0}},
                    "container": {"name": "ICASSP"},
                }
            ]
        }
        papers, _ = self.search(OpenAireProvider, response)
        self.assertEqual(len(papers), 1)
        paper = papers[0]
        self.assertEqual(paper.provider, "openaire")
        self.assertEqual(paper.paper_id, "10.1/x")
        self.assertEqual(paper.doi, "10.1/x")
        self.assertEqual(paper.title, "Clean title & agents")
        self.assertEqual(paper.abstract, "First part & more. Second sentence.")
        self.assertEqual(paper.url, "https://doi.org/10.1/x")
        self.assertEqual(paper.year, 2026)
        self.assertEqual(paper.cited_by_count, 3)
        self.assertIsInstance(paper.cited_by_count, int)
        self.assertEqual(paper.fields, ["AI", "ML"])
        self.assertEqual(paper.keywords, [])
        self.assertEqual(paper.venue, "ICASSP")

    def test_openaire_missing_and_null_optional_fields(self):
        variants = [
            {},
            {
                "descriptions": None,
                "publicationDate": None,
                "pids": None,
                "subjects": None,
                "indicators": None,
                "container": None,
            },
            {
                "descriptions": [],
                "pids": [],
                "subjects": [],
                "indicators": {},
                "container": {},
            },
            {
                "indicators": {"citationImpact": None},
                "container": {"name": None},
            },
            {"indicators": {"citationImpact": {}}},
            {"indicators": {"citationImpact": {"citationCount": None}}},
        ]
        for optional in variants:
            with self.subTest(optional=optional):
                item = {"id": "local::42", "mainTitle": "A paper"}
                item.update(optional)
                papers, _ = self.search(OpenAireProvider, {"results": [item]})
                self.assertEqual(len(papers), 1)
                paper = papers[0]
                self.assertEqual(paper.paper_id, "openaire:local::42")
                self.assertEqual(paper.title, "A paper")
                self.assertEqual(paper.doi, "")
                self.assertEqual(paper.abstract, "")
                self.assertIsNone(paper.year)
                self.assertEqual(paper.cited_by_count, 0)
                self.assertEqual(paper.fields, [])
                self.assertEqual(paper.keywords, [])
                self.assertEqual(paper.venue, "")

                parsed = urlsplit(paper.url)
                self.assertEqual(parsed.scheme, "https")
                self.assertEqual(parsed.netloc, "explore.openaire.eu")
                self.assertEqual(parsed.path, "/search/result")
                self.assertEqual(
                    parse_qs(parsed.query).get("id"), ["local::42"]
                )

    def test_openaire_non_doi_pid_does_not_become_doi(self):
        papers, _ = self.search(
            OpenAireProvider,
            {
                "results": [
                    {
                        "id": "arxiv-record",
                        "mainTitle": "A preprint",
                        "pids": [{"scheme": "arXiv", "value": "2601.1"}],
                    }
                ]
            },
        )
        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].doi, "")
        self.assertEqual(papers[0].paper_id, "openaire:arxiv-record")
        self.assertEqual(
            parse_qs(urlsplit(papers[0].url).query).get("id"),
            ["arxiv-record"],
        )

    def test_openaire_fields_are_unique_ordered_and_capped(self):
        values = ["AI", "", "AI", "ML"] + [
            "Field {}".format(index) for index in range(12)
        ]
        papers, _ = self.search(
            OpenAireProvider,
            {
                "results": [
                    {
                        "id": "fields",
                        "mainTitle": "Fields",
                        "subjects": [
                            {"subject": {"scheme": "keyword", "value": value}}
                            for value in values
                        ],
                    }
                ]
            },
        )
        self.assertEqual(len(papers), 1)
        self.assertEqual(
            papers[0].fields,
            ["AI", "ML"] + ["Field {}".format(index) for index in range(6)],
        )

    def test_openaire_null_results(self):
        papers, _ = self.search(OpenAireProvider, {"results": None})
        self.assertEqual(papers, [])

    def test_openreview_paper_note(self):
        timestamp = int(
            datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000
        )
        papers, _ = self.search(
            OpenReviewProvider,
            {
                "notes": [
                    {
                        "id": "paper-1",
                        "forum": "paper-1",
                        "cdate": timestamp,
                        "content": {
                            "title": {
                                "value": "  <b>Clean</b>title &amp; agents "
                            },
                            "abstract": {
                                "value": "First<b>part</b> &amp; more."
                            },
                            "keywords": {"value": ["agents", "planning"]},
                            "venue": {"value": "ICLR 2026"},
                        },
                    }
                ]
            },
        )
        self.assertEqual(len(papers), 1)
        paper = papers[0]
        self.assertEqual(paper.provider, "openreview")
        self.assertEqual(paper.paper_id, "openreview:paper-1")
        self.assertEqual(paper.title, "Clean title & agents")
        self.assertEqual(paper.abstract, "First part & more.")
        self.assertEqual(paper.keywords, ["agents", "planning"])
        self.assertEqual(paper.venue, "ICLR 2026")
        self.assertEqual(paper.year, 2026)
        self.assertEqual(paper.url, "https://openreview.net/forum?id=paper-1")
        self.assertEqual(paper.doi, "")
        self.assertEqual(paper.cited_by_count, 0)


    def test_openreview_skips_replies_and_keeps_papers_in_order(self):
        # Contract changed after Sol's second review: search asks for submissions only
        # (source=forum), and any reply that still arrives is dropped, not folded.
        papers, _ = self.search(
            OpenReviewProvider,
            {
                "notes": [
                    {
                        "id": "comment-a",
                        "forum": "a",
                        "replyto": "a",
                        "forumContent": {
                            "title": {"value": "First A"},
                            "abstract": {"value": "First abstract"},
                        },
                    },
                    {
                        "id": "b",
                        "forum": "b",
                        "content": {"title": {"value": "First B"}},
                    },
                    {
                        "id": "a",
                        "forum": "a",
                        "content": {
                            "title": {"value": "Later A"},
                            "abstract": {"value": "Later abstract"},
                        },
                    },
                    {
                        "id": "comment-b",
                        "forum": "b",
                        "replyto": "b",
                        "forumContent": {
                            "title": {"value": "Later B"}
                        },
                    },
                ]
            },
        )
        self.assertEqual(
            [paper.paper_id for paper in papers],
            ["openreview:b", "openreview:a"],
        )
        self.assertEqual(
            [paper.title for paper in papers], ["First B", "Later A"]
        )
        self.assertEqual(papers[1].abstract, "Later abstract")

    def test_openreview_searches_submissions_only(self):
        _, http = self.search(OpenReviewProvider, {"notes": []})
        params = parse_qs(urlsplit(http.calls[0][0]).query)
        self.assertEqual(params.get("source"), ["forum"])

    def test_openreview_missing_and_null_optional_fields(self):
        variants = [
            {"id": "minimal", "content": {"title": {"value": "Minimal"}}},
            {
                "id": "minimal",
                "forum": None,
                "cdate": None,
                "content": {
                    "title": {"value": "Minimal"},
                    "abstract": {"value": None},
                    "keywords": {"value": None},
                    "venue": {"value": None},
                },
                "forumContent": None,
            },
        ]
        for note in variants:
            with self.subTest(note=note):
                papers, _ = self.search(
                    OpenReviewProvider, {"notes": [note]}
                )
                self.assertEqual(len(papers), 1)
                paper = papers[0]
                self.assertEqual(paper.paper_id, "openreview:minimal")
                self.assertEqual(paper.title, "Minimal")
                self.assertEqual(paper.abstract, "")
                self.assertEqual(paper.keywords, [])
                self.assertEqual(paper.venue, "")
                self.assertIsNone(paper.year)
                self.assertEqual(
                    paper.url, "https://openreview.net/forum?id=minimal"
                )
                self.assertEqual(paper.doi, "")
                self.assertEqual(paper.cited_by_count, 0)

    def test_openreview_keywords_must_be_a_list(self):
        for location in ("content", "forumContent"):
            for value in ("agents, planning", 17, {"agents": True}, None):
                with self.subTest(location=location, value=value):
                    note = {
                        "id": "keywords",
                        "content": {"title": {"value": "Keywords"}},
                    }
                    note.setdefault(location, {})["keywords"] = {"value": value}
                    papers, _ = self.search(
                        OpenReviewProvider, {"notes": [note]}
                    )
                    self.assertEqual(len(papers), 1)
                    self.assertEqual(papers[0].keywords, [])

    def test_openreview_utc_year_and_epoch_zero(self):
        cases = [
            (0, 1970),
            (
                int(
                    datetime(
                        2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc
                    ).timestamp()
                    * 1000
                ),
                2025,
            ),
            (
                int(
                    datetime(
                        2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc
                    ).timestamp()
                    * 1000
                ),
                2026,
            ),
        ]
        for timestamp, expected in cases:
            with self.subTest(timestamp=timestamp):
                papers, _ = self.search(
                    OpenReviewProvider,
                    {
                        "notes": [
                            {
                                "id": "dated",
                                "cdate": timestamp,
                                "content": {"title": {"value": "Dated"}},
                            }
                        ]
                    },
                )
                self.assertEqual(len(papers), 1)
                self.assertEqual(papers[0].year, expected)






    def test_missing_null_and_empty_titles_are_skipped(self):
        cases = [
            (
                OpenAireProvider,
                {
                    "results": [
                        {"id": "missing"},
                        {"id": "null", "mainTitle": None},
                        {"id": "empty", "mainTitle": ""},
                        {"id": "good", "mainTitle": "Kept"},
                    ]
                },
            ),
            (
                OpenReviewProvider,
                {
                    "notes": [
                        {"id": "missing", "content": {}},
                        {
                            "id": "null",
                            "content": {"title": {"value": None}},
                        },
                        {
                            "id": "empty",
                            "content": {"title": {"value": ""}},
                        },
                        {
                            "id": "good",
                            "content": {"title": {"value": "Kept"}},
                        },
                    ]
                },
            ),
        ]
        for provider_class, response in cases:
            with self.subTest(provider=provider_class.__name__):
                papers, _ = self.search(provider_class, response)
                self.assertEqual(len(papers), 1)
                self.assertEqual(papers[0].title, "Kept")

    def test_default_sources(self):
        args = cli.parser().parse_args(
            ["q", "--s2-key", "", "--core-key", ""]
        )
        names = cli._provider_names(args, {})
        self.assertIn("openaire", names)
        self.assertIn("openreview", names)

    def test_unknown_provider_is_rejected_when_building_providers(self):
        cli.parser().parse_args(["q", "--providers", "nope"])
        available = {
            name: provider_class(FakeHTTP(response))
            for provider_class, name, _, _, _, _, _, response in self.SOURCES
        }
        with self.assertRaises(SystemExit):
            cli._chosen_providers("nope", available)


if __name__ == "__main__":
    unittest.main()
