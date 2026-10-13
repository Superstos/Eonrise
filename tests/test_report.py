from __future__ import annotations

import unittest

from eonrise import report


class DegradedProviderReportTests(unittest.TestCase):
    BASE = {"question": "q", "root_topic": "q", "status": "partial", "stop_reason": "x",
            "papers": [], "retrieved_papers": 0, "on_topic_papers": 0, "concepts": [],
            "coverage": {"mechanism": []}, "gaps": ["mechanism"],
            "recommended_queries": [], "limitations": []}

    def test_brief_names_a_provider_that_answered_nothing(self):
        text = report.render_compact_markdown({**self.BASE, "providers_down": ["openalex"]})
        self.assertIn("**Degraded:** openalex", text)

    def test_brief_stays_quiet_when_every_provider_answered(self):
        self.assertNotIn("Degraded", report.render_compact_markdown({**self.BASE, "providers_down": []}))


if __name__ == "__main__":
    unittest.main()
