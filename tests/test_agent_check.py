import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("agent_check", Path(__file__).parent.parent / "tools" / "agent_check.py")
agent_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent_check)


class AgentCheckTest(unittest.TestCase):
    def test_counts_fields_an_answer_uses(self):
        s = agent_check.score("Jurors hear instructions once; nursing students debrief mistakes.")
        self.assertEqual(s["fields"], ["courts", "nursing"])
        self.assertFalse(s["dismissed"])

    def test_flags_an_answer_that_waves_results_away(self):
        s = agent_check.score("Most results came from unrelated fields, so this is noise.")
        self.assertEqual(s["fields"], [])
        self.assertTrue(s["dismissed"])

    def test_skill_goes_first_in_the_prompt(self):
        self.assertTrue(agent_check.prompt(True).startswith("---\nname: eonrise"))
        self.assertNotIn("name: eonrise", agent_check.prompt(False))
