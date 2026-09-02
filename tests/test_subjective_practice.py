import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app  # noqa: E402


class SubjectiveHandler(app.ReaderHandler):
    def __init__(self, payload):
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.path = "/api/subjective/response"
        self.headers = {"Content-Length": str(len(encoded))}
        self.rfile = io.BytesIO(encoded)
        self.wfile = io.BytesIO()
        self.status = None

    def send_response(self, code, message=None):
        self.status = code

    def send_header(self, key, value):
        pass

    def end_headers(self):
        pass

    def log_message(self, format, *args):
        pass


class SubjectivePracticeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.content_root = Path(self.temp.name) / "content"
        self.data_root = Path(self.temp.name) / "data"
        package = self.content_root / "english-exam-2099-e1-subjective"
        prompt = package / "cleaned" / "pages" / "001-translation.md"
        reference = package / "reference" / "pages" / "002-translation-analysis.md"
        prompt.parent.mkdir(parents=True, exist_ok=True)
        reference.parent.mkdir(parents=True, exist_ok=True)
        prompt.write_text("# 2099 年考研英语一主观题\n## 翻译\n(46) Translate this sentence.", encoding="utf-8")
        reference.write_text("## 翻译原书解析\n参考译文。", encoding="utf-8")
        section_id = "abcdef123456"
        prompt_meta = {
            "id": section_id,
            "key": "ch01-translation",
            "order": 1,
            "title": "第一节 翻译 Part C",
            "artifact": "cleaned/pages/001-translation.md",
            "sha256": hashlib.sha256(prompt.read_bytes()).hexdigest(),
            "source_map": {"original_line_start": 1, "original_line_end": 3},
            "chapter_id": "ch01",
            "chapter_order": 1,
            "chapter_title": "第一章 2099 年考研英语一主观题",
            "section_order": 1,
            "level": 2,
            "material_kind": "cleaned",
        }
        reference_meta = {
            "id": "123456abcdef",
            "key": "ch01-translation-analysis",
            "order": 2,
            "title": "第二节 翻译原书解析",
            "artifact": "reference/pages/002-translation-analysis.md",
            "sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
            "source_map": {"original_line_start": 4, "original_line_end": 6},
        }
        manifest = {
            "schema_version": 2,
            "book": {
                "id": package.name,
                "title": "2099 年考研英语一主观题",
                "status": "ready",
                "domain": "english",
                "subject": "考研英语一",
                "resource_type": "reference",
            },
            "quality": {"status": "pass", "blocker_count": 0, "warning_count": 0},
            "toc": [{"id": "ch01", "order": 1, "title": "第一章 2099 年考研英语一主观题", "section_ids": [section_id]}],
            "sections": [prompt_meta],
            "references": [reference_meta],
        }
        (package / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        self.original = {name: getattr(app, name) for name in ("CONTENT_DIR", "DATA_DIR", "ACTIVITY_PATH", "SUBJECTIVE_DIR", "BOOK_ASSETS", "CATALOG_CACHE", "obsidian_vault")}
        app.CONTENT_DIR = self.content_root
        app.DATA_DIR = self.data_root
        app.ACTIVITY_PATH = self.data_root / "activity.json"
        app.SUBJECTIVE_DIR = self.data_root / "subjective"
        app.BOOK_ASSETS = {}
        app.CATALOG_CACHE = {"checked_at": 0.0, "signature": None, "books": [], "sections": {}}
        app.obsidian_vault = lambda: None
        self.section_id = section_id

    def tearDown(self):
        for name, value in self.original.items():
            setattr(app, name, value)
        self.temp.cleanup()

    def test_prompt_pairs_only_its_explicit_reference(self):
        payload = app.subjective_practice(self.section_id)
        self.assertEqual(payload["mode"], "translation")
        self.assertTrue(payload["reference_available"])
        self.assertIn("参考译文", payload["reference_markdown"])
        self.assertEqual(payload["prompt_source_map"]["original_line_start"], 1)
        self.assertEqual(payload["reference_source_map"]["original_line_start"], 4)
        self.assertEqual(payload["storage"], "local")

    def test_response_is_saved_separately_and_never_changes_prompt(self):
        handler = SubjectiveHandler({"section_id": self.section_id, "answer": "我的译文", "reflection": "侧边栏批改"})
        handler.do_POST()
        self.assertEqual(handler.status, 200)
        response = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertTrue(response["saved"])
        self.assertTrue(Path(response["path"]).is_file())
        state = json.loads((app.SUBJECTIVE_DIR / f"{self.section_id}.json").read_text(encoding="utf-8"))
        self.assertEqual(state["answer"], "我的译文")
        self.assertIn("## 侧边栏 / 个人解析", Path(response["path"]).read_text(encoding="utf-8"))
        self.assertIn("Translate this sentence", app.subjective_practice(self.section_id)["prompt_markdown"])

    def test_invalid_id_is_rejected(self):
        with self.assertRaises(ValueError):
            app.subjective_practice("../escape")
        with self.assertRaises(ValueError):
            app.subjective_response_path("../escape")


if __name__ == "__main__":
    unittest.main()
