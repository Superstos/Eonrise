import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("graph_view", Path(__file__).parent.parent / "tools" / "graph_view.py")
graph_view = importlib.util.module_from_spec(spec)
spec.loader.exec_module(graph_view)


class GraphViewTest(unittest.TestCase):
    def test_tree_and_shared_paper_links(self):
        research_map = {"question": "q", "concepts": [
            {"node_id": "c0", "label": "root", "direction": "root", "depth": 0, "parent_id": None, "paper_ids": ["p1"]},
            {"node_id": "c1", "label": "up", "direction": "up", "depth": 1, "parent_id": "c0", "paper_ids": ["p2", "p3"]},
            {"node_id": "c2", "label": "down", "direction": "down", "depth": 2, "parent_id": "c1", "paper_ids": ["p2"]},
            {"node_id": "c3", "label": "side", "direction": "sideways", "depth": 1, "parent_id": "c0", "paper_ids": ["p2", "p3"]},
        ]}
        data = graph_view.graph_data(research_map)
        self.assertEqual(data["tree"], [["c0", "c1"], ["c1", "c2"], ["c0", "c3"]])
        # c1 and c3 share two papers; c1-c2 shares one and is a tree link already.
        self.assertEqual(data["shared"], [["c1", "c3", 2]])
        self.assertEqual(data["maxDepth"], 2)


    def test_paper_details_drop_email_addresses(self):
        research_map = {"question": "q", "concepts": [
            {"node_id": "c0", "label": "root", "direction": "root", "depth": 0, "paper_ids": ["p1"]}],
            "papers": [{"paper_id": "p1", "title": "T", "abstract": "Contact a.b@example.org for data."}]}
        details = graph_view.paper_details(research_map, None)
        self.assertEqual(details["p1"]["abstract"], "Contact [email removed] for data.")


if __name__ == "__main__":
    unittest.main()
