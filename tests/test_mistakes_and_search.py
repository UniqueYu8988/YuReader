"""Tests for Mistakes Center, Global Search, and Ebbinghaus scheduling."""

import unittest
from yureader.practice import mistakes_overview, resolve_mistake
from yureader.search import global_search, extract_snippet
from yureader.oral_focus import save_oral_focus_progress, load_oral_focus_progress


class TestMistakesAndSearch(unittest.TestCase):
    def test_mistakes_overview_structure(self):
        overview = mistakes_overview()
        self.assertIn("total", overview)
        self.assertIn("pending", overview)
        self.assertIn("resolved", overview)
        self.assertIn("items", overview)
        self.assertIsInstance(overview["items"], list)

    def test_global_search_empty_and_normal(self):
        empty = global_search("")
        self.assertEqual(empty["total"], 0)
        self.assertEqual(empty["results"], [])

        # Search for common term like '牙' or '口腔'
        result = global_search("牙")
        self.assertIn("total", result)
        self.assertIn("results", result)
        if result["results"]:
            item = result["results"][0]
            self.assertIn("type", item)
            self.assertIn("title", item)
            self.assertIn("target", item)

    def test_extract_snippet(self):
        text = "口腔组织病理学是口腔医学的核心学科，重点在于牙体牙髓与牙周组织的病理变化。"
        snippet = extract_snippet(text, "牙体")
        self.assertIn("牙体", snippet)


if __name__ == "__main__":
    unittest.main()
