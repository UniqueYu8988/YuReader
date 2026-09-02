import hashlib
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import app


class LearningCenterFrontendContractTests(unittest.TestCase):
    """The learning center keeps three domain-specific paths without reviving weekly UI."""

    @classmethod
    def setUpClass(cls):
        static = Path(__file__).resolve().parents[1] / "static"
        cls.html = (static / "index.html").read_text(encoding="utf-8")
        cls.javascript = (static / "app.js").read_text(encoding="utf-8")

    def test_center_exposes_three_domains_and_no_search_or_weekly_editor(self):
        for label in ("医学", "政治", "英语"):
            self.assertIn(f"<strong>{label}</strong>", self.html)
        for removed_id in ("librarySearch", "englishNotebook", "englishNotebookEditor"):
            self.assertNotIn(f'id="{removed_id}"', self.html)

    def test_center_keeps_real_section_boundaries(self):
        for title in ("名词解释", "优题库基础篇", "优题库拔高篇", "真题训练", "翻译与写作"):
            self.assertIn(title, self.javascript)
        self.assertIn('start >= 21 && start <= 40 : start >= 41', self.javascript)
        self.assertIn('openOralFocusIndex(subjectId = "", type = "")', self.javascript)


class DomainFallbackTests(unittest.TestCase):
    """Runtime must safely fall back when existing packages have no domain fields."""

    def make_package(self, root: Path, book_meta: dict) -> Path:
        section_id = "abcd1234abcd"
        artifact_path = root / "pages" / "001.md"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text("# 第一节 起点\n正文内容", encoding="utf-8")
        manifest = {
            "schema_version": 2,
            "book": {**{"id": "test-book", "title": "测试资料", "status": "ready", "default_material": "cleaned"}, **book_meta},
            "quality": {"status": "warning", "blocker_count": 0, "warning_count": 0},
            "toc": [{"id": "tc1", "order": 1, "title": "第一章 起点", "section_ids": [section_id]}],
            "sections": [
                {
                    "id": section_id,
                    "order": 1,
                    "title": "第一节 起点",
                    "artifact": "pages/001.md",
                    "sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
                    "chapter_id": "tc1",
                    "chapter_order": 1,
                    "chapter_title": "第一章 起点",
                    "section_order": 1,
                    "level": 2,
                    "material_kind": "cleaned",
                }
            ],
        }
        target = root / "manifest.json"
        target.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        return target

    def test_legacy_book_falls_back_to_medicine_book(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = self.make_package(Path(tmp), {})
            loaded = app.manifest_book(manifest_path)
            self.assertIsNotNone(loaded)
            book, sections = loaded
            self.assertEqual(book["domain"], "medicine")
            self.assertEqual(book["domain_label"], "医学")
            self.assertEqual(book["resource_type"], "book")
            self.assertEqual(book["resource_type_label"], "教材")
            self.assertEqual(book["subject"], "测试资料")
            self.assertIn("abcd1234abcd", sections)

    def test_new_book_can_declare_politics_lecture(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = self.make_package(
                Path(tmp),
                {"domain": "politics", "subject": "马克思主义基本原理", "resource_type": "question_bank"},
            )
            book, _ = app.manifest_book(manifest_path)
            self.assertEqual(book["domain"], "politics")
            self.assertEqual(book["domain_label"], "政治")
            self.assertEqual(book["resource_type"], "question_bank")
            self.assertEqual(book["subject"], "马克思主义基本原理")

    def test_invalid_domain_values_safely_fall_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = self.make_package(Path(tmp), {"domain": "unknown", "resource_type": "game"})
            book, _ = app.manifest_book(manifest_path)
            self.assertEqual(book["domain"], "medicine")
            self.assertEqual(book["resource_type"], "book")

    def test_safe_helpers_are_idempotent(self):
        self.assertEqual(app.safe_domain(None), "medicine")
        self.assertEqual(app.safe_domain("Medicine "), "medicine")
        self.assertEqual(app.safe_domain("xx"), "medicine")
        self.assertEqual(app.safe_resource_type("Reference"), "reference")
        self.assertEqual(app.safe_resource_type("wrong"), "book")


class BookLearningSummaryTests(unittest.TestCase):
    """Summary only reads local activity + note filenames, never book content."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.originals = {
            name: getattr(app, name)
            for name in ("DATA_DIR", "NOTES_DIR", "ACTIVITY_PATH", "obsidian_vault")
        }
        app.DATA_DIR = self.root
        app.NOTES_DIR = self.root / "notes"
        app.ACTIVITY_PATH = self.root / "activity.json"
        app.obsidian_vault = lambda: None
        self.book = {
            "id": "book-x",
            "title": "测试书",
            "sections": [
                {"id": "aaaaaaaaaaaa", "title": "一节"},
                {"id": "bbbbbbbbbbbb", "title": "二节"},
                {"id": "cccccccccccc", "title": "三节"},
                {"id": "dddddddddddd", "title": "四节"},
            ],
        }
        self.sections = {
            "aaaaaaaaaaaa": {"id": "aaaaaaaaaaaa", "title": "一节", "chapter_title": "一章", "chapter_order": 1, "section_order": 1},
            "bbbbbbbbbbbb": {"id": "bbbbbbbbbbbb", "title": "二节", "chapter_title": "一章", "chapter_order": 1, "section_order": 2},
            "cccccccccccc": {"id": "cccccccccccc", "title": "三节", "chapter_title": "二章", "chapter_order": 2, "section_order": 1},
            "dddddddddddd": {"id": "dddddddddddd", "title": "四节", "chapter_title": "二章", "chapter_order": 2, "section_order": 2},
        }

    def tearDown(self):
        for name, value in self.originals.items():
            setattr(app, name, value)
        self.temp.cleanup()

    def test_summary_uses_real_activity_and_notes_only(self):
        app.atomic_write(
            app.ACTIVITY_PATH,
            json.dumps(
                {
                    "schema_version": 1,
                    "days": {
                        "2026-08-28": {
                            "sections": ["aaaaaaaaaaaa", "bbbbbbbbbbbb", "eeeeeeeeeeee"],
                            "reading_seconds": 120,
                            "section_reading_seconds": {"aaaaaaaaaaaa": 40, "bbbbbbbbbbbb": 60, "eeeeeeeeeeee": 20},
                            "last_section_id": "bbbbbbbbbbbb",
                            "last_reading_at": "2026-08-28T22:00:00+08:00",
                        },
                        "2026-08-29": {
                            "sections": ["cccccccccccc"],
                            "reading_seconds": 50,
                            "section_reading_seconds": {"cccccccccccc": 50},
                            "last_section_id": "cccccccccccc",
                            "last_reading_at": "2026-08-29T08:00:00+08:00",
                        },
                    },
                    "last_section_id": "cccccccccccc",
                },
                ensure_ascii=False,
            ),
        )
        note_path = app.NOTES_DIR / "dddddddddddd.md"
        app.atomic_write(note_path, "一篇非空笔记")
        summary = app.book_learning_summary(self.book, self.sections)
        # opened: a, b, c + note on d -> 4 learned; foreign section e ignored.
        self.assertEqual(summary["learned_section_count"], 4)
        self.assertEqual(summary["note_count"], 1)
        self.assertEqual(summary["reading_seconds"], 150)  # 120 + 50 minus the 20 of e
        self.assertEqual(summary["progress"], 100.0)
        self.assertEqual(summary["last_section"]["id"], "cccccccccccc")
        self.assertEqual(summary["last_studied_day"], "2026-08-29")

    def test_empty_book_has_zero_facts(self):
        summary = app.book_learning_summary({"id": "x", "sections": []}, {})
        self.assertEqual(summary["learned_section_count"], 0)
        self.assertEqual(summary["progress"], 0.0)
        self.assertIsNone(summary["last_section"])


class ObsidianSectionNoteTests(unittest.TestCase):
    """Section notes keep stable local IDs and gain a browsable vault tree."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.originals = {name: getattr(app, name) for name in ("DATA_DIR", "NOTES_DIR", "obsidian_vault")}
        app.DATA_DIR = self.root / "data"
        app.NOTES_DIR = app.DATA_DIR / "notes"
        self.vault = self.root / "vault"
        (self.vault / ".obsidian").mkdir(parents=True)
        app.obsidian_vault = lambda: self.vault
        self.book = {"id": "politics-core", "title": "核心考案", "domain": "politics", "subject": "马克思主义基本原理"}
        self.section = {"id": "abcdefabcdef", "title": "第一节 哲学/基本问题", "chapter_title": "第一章 辩证唯物论"}

    def tearDown(self):
        for name, value in self.originals.items():
            setattr(app, name, value)
        self.temp.cleanup()

    def test_vault_note_has_browsable_hierarchy_and_stable_identity(self):
        target, storage, uri = app.section_note_target(self.book, self.section)
        self.assertEqual(storage, "obsidian")
        self.assertTrue(target.is_relative_to(self.vault / "YuReader" / "政治" / "马克思主义基本原理" / "第一章 辩证唯物论"))
        self.assertNotIn("/", target.name)
        self.assertNotIn("abcdefabcdef", target.name)
        self.assertIn("section_id: abcdefabcdef", app.section_note_markdown(self.book, self.section, "我的笔记"))
        self.assertIn("obsidian://open", uri)


if __name__ == "__main__":
    unittest.main()
