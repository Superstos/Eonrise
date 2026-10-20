from __future__ import annotations

import unittest

from eonrise.evidence import _dedupe_papers
from eonrise.providers import (CoreProvider, CrossrefProvider, DoajProvider,
                                       EuropePMCProvider, OpenAlexProvider,
                                       SemanticScholarProvider)


class FakeHttp:
    """Records the URL asked for and replays a canned payload, so a provider's parsing
    is tested without spending anyone's rate limit."""

    def __init__(self, payload): self.payload, self.urls, self.headers = payload, [], []

    def get_json(self, url, headers=None):
        self.urls.append(url); self.headers.append(headers or {}); return self.payload


EPMC = {"resultList": {"result": [{
    "id": "42540791", "doi": "10.7759/cureus.111895", "title": "Spaced retrieval in medical education",
    "abstractText": "We tested spaced retrieval against massed study.", "pubYear": "2026",
    "citedByCount": "4", "keywordList": {"keyword": ["Medical education", "Study Strategies"]},
    "meshHeadingList": {"meshHeading": [{"descriptorName": "Memory"}]},
    "journalInfo": {"journal": {"title": "Cureus"}}}]}}

DOAJ = {"results": [{"id": "abc", "bibjson": {
    "title": "Music as pedagogy", "abstract": "Rhythm supports retention.", "year": "2026",
    "keywords": ["rhythm and prosody", "spaced retrieval practice"],
    "subject": [{"term": "Education (General)", "scheme": "LCC"}],
    "identifier": [{"id": "2504-284X", "type": "eissn"}, {"id": "10.3389/feduc.2026.1731546", "type": "doi"}],
    "link": [{"url": "https://example.org/a"}], "journal": {"title": "Frontiers in Education"}}}]}

S2 = {"data": [{"paperId": "p1", "title": "Retrieval practice", "abstract": "A review.",
                "fieldsOfStudy": ["Psychology"], "year": 2024, "citationCount": 12,
                "externalIds": {"DOI": "10.1/abc"}, "venue": "Cognition"}]}

CORE = {"results": [{"id": 7, "title": "Open access retention study", "abstract": "Full text.",
                     "doi": "10.2/xyz", "yearPublished": 2023, "subjects": ["education", "memory"]}]}


class CrossProviderIdentityTests(unittest.TestCase):
    def test_bare_and_url_doi_merge_into_one_enriched_paper(self):
        crossref = CrossrefProvider(FakeHttp({"message": {"items": [{
            "DOI": "10.1234/example", "title": ["Memory retention study"]
        }]}})).search("memory retention")[0]
        openalex = OpenAlexProvider(FakeHttp({"results": [{
            "id": "W1", "doi": "https://doi.org/10.1234/example",
            "title": "Memory retention study",
            "abstract_inverted_index": {"Memory": [0], "retention": [1]}
        }]})).search("memory retention")[0]
        merged, added = _dedupe_papers([crossref], [openalex])
        self.assertEqual(len(merged), 1)
        self.assertEqual(added, 0)
        self.assertEqual(merged[0].abstract, "Memory retention")


class EuropePMCTests(unittest.TestCase):
    def test_reads_abstract_keywords_and_mesh(self):
        http = FakeHttp(EPMC)
        paper = EuropePMCProvider(http, "me@example.org").search("spaced repetition", 5)[0]
        self.assertEqual(paper.doi, "10.7759/cureus.111895")
        self.assertIn("massed study", paper.abstract)
        self.assertEqual(paper.keywords, ["Medical education", "Study Strategies"])
        self.assertEqual(paper.topic_path, ["Memory"])
        self.assertEqual(paper.year, 2026)
        self.assertEqual(paper.cited_by_count, 4)
        self.assertIn("email=me%40example.org", http.urls[0])

    def test_untitled_rows_are_dropped(self):
        http = FakeHttp({"resultList": {"result": [{"id": "1", "title": "   "}]}})
        self.assertEqual(EuropePMCProvider(http).search("q", 5), [])


class DoajTests(unittest.TestCase):
    def test_subject_term_becomes_a_field(self):
        paper = DoajProvider(FakeHttp(DOAJ)).search("music", 5)[0]
        self.assertEqual(paper.fields, ["Education (General)"])
        self.assertEqual(paper.doi, "10.3389/feduc.2026.1731546")
        self.assertIn("spaced retrieval practice", paper.keywords)

    def test_eissn_is_not_mistaken_for_a_doi(self):
        rows = {"results": [{"id": "x", "bibjson": {"title": "T", "abstract": "A",
                 "identifier": [{"id": "2504-284X", "type": "eissn"}], "link": [{"url": "https://e.org/x"}]}}]}
        paper = DoajProvider(FakeHttp(rows)).search("q", 5)[0]
        self.assertEqual(paper.doi, "")
        self.assertEqual(paper.url, "https://e.org/x")


class SemanticScholarTests(unittest.TestCase):
    def test_key_is_sent_as_a_header_when_present(self):
        http = FakeHttp(S2)
        paper = SemanticScholarProvider(http, "secret").search("retrieval", 5)[0]
        self.assertEqual(http.headers[0], {"x-api-key": "secret"})
        self.assertEqual(paper.fields, ["Psychology"])
        self.assertEqual(paper.doi, "10.1/abc")

    def test_no_key_sends_no_header(self):
        http = FakeHttp(S2)
        SemanticScholarProvider(http, "").search("retrieval", 5)
        self.assertEqual(http.headers[0], {})


class CoreTests(unittest.TestCase):
    def test_key_is_sent_as_a_bearer_token(self):
        http = FakeHttp(CORE)
        paper = CoreProvider(http, "k").search("open access", 5)[0]
        self.assertEqual(http.headers[0], {"Authorization": "Bearer k"})
        self.assertEqual(paper.fields, ["education", "memory"])
        self.assertEqual(paper.year, 2023)


if __name__ == "__main__":
    unittest.main()


OPENAIRE = {"results": [{"id": "doi_dedup___::10", "mainTitle": "FadeMem: forgetting for agent memory",
    "descriptions": ["Agents need selective forgetting."], "publicationDate": "2026-05-03",
    "pids": [{"scheme": "arXiv", "value": "2601.18642"}, {"scheme": "doi", "value": "10.1109/icassp.1"}],
    "subjects": [{"subject": {"scheme": "keyword", "value": "Artificial Intelligence"}}],
    "indicators": {"citationImpact": {"citationCount": 3.0}}, "container": {"name": "ICASSP 2026"}}]}

OPENREVIEW = {"notes": [
    {"id": "rev1", "forum": "paperA", "replyto": "paperA", "cdate": 1761965336565,
     "content": {"title": {"value": "Official Review of Submission 1"}, "summary": {"value": "A review."},
                 "abstract": {"value": "The reviewer's words."}, "venue": {"value": "wrong"}},
     "forumContent": {"title": {"value": "Evaluating memory in agents"}, "venue": {"value": "ICLR 2026 Poster"},
                      "abstract": {"value": "We benchmark memory agents."}, "keywords": {"value": ["memory"]}}},
    {"id": "rev2", "forum": "paperA", "replyto": "paperA", "cdate": 1761965336565,
     "content": {"title": {"value": "Comment"}}, "forumContent": {"title": {"value": "Evaluating memory in agents"}}},
    {"id": "rev3", "forum": "paperC", "replyto": "paperC", "content": {"title": {"value": "Official Review"}}},
    {"id": "paperB", "forum": "paperB", "cdate": 1761965336565,
     "content": {"title": {"value": "Drug discovery agents"}, "abstract": {"value": "Own abstract."},
                 "venue": {"value": "Agents4Science"}, "keywords": {"value": "not a list"}}}]}

class KeylessProvidersAddedTest(unittest.TestCase):
    def test_openaire_maps_doi_subjects_and_citations_without_a_key(self):
        from eonrise.providers import OpenAireProvider
        http = FakeHttp(OPENAIRE)
        [paper] = OpenAireProvider(http).search("agent memory", 5)
        self.assertEqual(paper.doi, "10.1109/icassp.1")
        self.assertEqual((paper.year, paper.cited_by_count, paper.venue), (2026, 3, "ICASSP 2026"))
        self.assertEqual(paper.fields, ["Artificial Intelligence"])
        self.assertNotIn("mailto", http.urls[0]); self.assertEqual(http.headers[0], {})

    def test_openreview_keeps_papers_drops_reviews_and_keeps_the_venue(self):
        from eonrise.providers import OpenReviewProvider
        papers = OpenReviewProvider(FakeHttp(OPENREVIEW)).search("agent memory", 5)
        self.assertEqual([p.paper_id for p in papers], ["openreview:paperB"])
        self.assertEqual((papers[0].abstract, papers[0].keywords, papers[0].venue), ("Own abstract.", [], "Agents4Science"))
        self.assertEqual(papers[0].year, 2025)

    def test_openaire_skips_null_descriptions(self):
        from eonrise.providers import OpenAireProvider
        item = dict(OPENAIRE["results"][0], descriptions=[None, "Kept."])
        [paper] = OpenAireProvider(FakeHttp({"results": [item]})).search("x", 5)
        self.assertEqual(paper.abstract, "Kept.")


    def test_both_keyless_sources_run_by_default(self):
        from eonrise import cli
        defaults = cli._provider_names(cli.parser().parse_args(["q", "--s2-key", "", "--core-key", ""]), {})
        self.assertIn("openaire", defaults); self.assertIn("openreview", defaults)


class RetractedPapersStayOutTest(unittest.TestCase):
    def test_crossref_drops_retracted_papers_and_retraction_notices(self):
        retraction = {"type": "retraction", "label": "Retraction", "source": "retraction-watch"}
        payload = {"message": {"items": [
            {"DOI": "10.1/kept", "title": ["Kept"], "updated-by": [{"type": "correction"}]},
            {"DOI": "10.1/gone", "title": ["Retracted study"], "updated-by": [retraction]},
            {"DOI": "10.1/notice", "title": ["Retraction: study"], "update-to": [retraction]},
            {"DOI": "10.1/withdrawn", "title": ["Withdrawn"], "updated-by": [{"type": "withdrawal"}]}]}}
        papers = CrossrefProvider(FakeHttp(payload)).search("study", 5)
        self.assertEqual([p.doi for p in papers], ["10.1/kept"])

    def test_openalex_asks_for_unretracted_works_only(self):
        import urllib.parse
        http = FakeHttp({"results": []})
        OpenAlexProvider(http).search("agent memory", 5)
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(http.urls[0]).query)
        self.assertEqual(params["filter"], ["is_retracted:false"])
