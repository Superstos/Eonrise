import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("graph_view", Path(__file__).parent.parent / "tools" / "graph_view.py")
graph_view = importlib.util.module_from_spec(spec)
spec.loader.exec_module(graph_view)


class GraphViewTest(unittest.TestCase):
    def test_links_follow_parent_ids(self):
        research_map = {"question": "q", "concepts": [
            {"node_id": "c0", "label": "root", "direction": "root", "depth": 0, "parent_id": None},
            {"node_id": "c1", "label": "up", "direction": "up", "depth": 1, "parent_id": "c0"},
            {"node_id": "c2", "label": "down", "direction": "down", "depth": 2, "parent_id": "c1"},
        ]}
        data = graph_view.graph_data(research_map)
        self.assertEqual(len(data["nodes"]), 3)
        self.assertEqual(data["links"], [{"source": "c0", "target": "c1"}, {"source": "c1", "target": "c2"}])
        self.assertEqual(data["maxDepth"], 2)


if __name__ == "__main__":
    unittest.main()
