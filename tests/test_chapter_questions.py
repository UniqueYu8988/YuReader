import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app  # noqa: E402
from yureader.chapter_questions import (  # noqa: E402
    normalize_chapter_title,
    get_chapter_questions,
    clear_chapter_questions_cache,
)
from yureader.catalog import catalog  # noqa: E402


class ChapterQuestionsTest(unittest.TestCase):
    def setUp(self):
        clear_chapter_questions_cache()

    def test_normalize_chapter_title(self):
        self.assertEqual(normalize_chapter_title("第一章 牙髓根尖周病"), "牙髓根尖周")
        self.assertEqual(normalize_chapter_title("1. 牙周组织解剖与生理"), "牙周组织解剖生理")
        self.assertEqual(normalize_chapter_title("第十章、牙源性肿瘤和瘤样病变"), "牙源性肿瘤瘤样")

    def test_get_chapter_questions_dental_pulp(self):
        questions = get_chapter_questions("dental-pulp-5e", "第一章 龋病学概论")
        self.assertGreater(len(questions), 0)
        first = questions[0]
        self.assertIn("id", first)
        self.assertIn(first["type"], ("definition", "essay"))
        self.assertIn(first["type_label"], ("名词解释", "简答论述"))
        self.assertTrue(bool(first["prompt"]))
        self.assertIn("answer_markdown", first)
        self.assertGreater(first["star_level"], 0)

    def test_get_chapter_questions_aliases(self):
        questions = get_chapter_questions("dental-pulp-5e", "牙髓根尖周病治疗的生物学基础")
        self.assertGreater(len(questions), 0)

    def test_get_chapter_questions_empty_and_unknown(self):
        self.assertEqual(get_chapter_questions("", "牙体硬组织非龋性疾病"), [])
        self.assertEqual(get_chapter_questions("dental-pulp-5e", ""), [])
        self.assertEqual(get_chapter_questions("non-existent-book", "牙体硬组织非龋性疾病"), [])
        self.assertEqual(get_chapter_questions("english-grammar-long-sentences", "第一章"), [])

    def test_section_endpoint_includes_chapter_questions(self):
        _books, sections = catalog()
        # Find a section belonging to dental pulp
        target_section_id = None
        for sec_id, sec in sections.items():
            if sec.get("book_id") == "dental-pulp-5e" and sec.get("chapter_title"):
                target_section_id = sec_id
                break

        if not target_section_id:
            self.skipTest("No dental pulp section found in catalog")

        class RequestHandler(app.ReaderHandler):
            def __init__(self, path):
                self.path = path
                self.wfile = io.BytesIO()
                self.rfile = io.BytesIO()
                self.headers = {}
                self.status = None

            def send_response(self, code, message=None):
                self.status = code

            def send_header(self, key, value):
                pass

            def end_headers(self):
                pass

            def log_message(self, format, *args):
                pass

        handler = RequestHandler(f"/api/sections/{target_section_id}")
        handler.do_GET()
        self.assertEqual(handler.status, 200)
        payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertIn("chapter_questions", payload)
        self.assertIsInstance(payload["chapter_questions"], list)


if __name__ == "__main__":
    unittest.main()
