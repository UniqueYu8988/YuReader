import hashlib
import json
import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

import app


class SectionIdAliasTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.originals = {
            name: getattr(app, name)
            for name in ("DATA_DIR", "NOTES_DIR", "REVIEWS_DIR", "REVIEW_WORKFLOW_DIR", "LOGS_DIR", "WEEKLY_DIR", "ACTIVITY_PATH", "obsidian_vault")
        }
        app.DATA_DIR = self.root / "data"
        app.NOTES_DIR = app.DATA_DIR / "notes"
        app.REVIEWS_DIR = app.DATA_DIR / "reviews"
        app.REVIEW_WORKFLOW_DIR = app.DATA_DIR / "review-workflow"
        app.LOGS_DIR = app.DATA_DIR / "logs"
        app.WEEKLY_DIR = app.DATA_DIR / "weekly-reports"
        app.ACTIVITY_PATH = app.DATA_DIR / "activity.json"
        app.obsidian_vault = lambda: None
        self.current_id = "aaaaaaaaaaaa"
        self.legacy_id = "bbbbbbbbbbbb"
        self.sections = {
            self.current_id: {
                "id": self.current_id,
                "title": "现行小节",
                "book_title": "测试书",
                "chapter_title": "第一章",
                "chapter_order": 1,
                "section_order": 1,
            }
        }
        self.book = {"id": "book-x", "title": "测试书", "sections": [{"id": self.current_id}]}

    def tearDown(self):
        for name, value in self.originals.items():
            setattr(app, name, value)
        self.temp.cleanup()

    def write_aliases(self, aliases):
        app.atomic_write(
            app.section_aliases_path(),
            json.dumps({"schema_version": 1, "section_aliases": aliases}, ensure_ascii=False),
        )

    def test_loader_fails_closed_for_cycle_and_dangling_alias(self):
        self.write_aliases(
            {
                self.legacy_id: {"current_id": self.current_id, "confidence": "high"},
                "cccccccccccc": {"current_id": "dddddddddddd", "confidence": "high"},
                "eeeeeeeeeeee": {"current_id": "ffffffffffff", "confidence": "high"},
                "ffffffffffff": {"current_id": "eeeeeeeeeeee", "confidence": "high"},
            }
        )
        self.assertEqual(app.resolve_section_id(self.legacy_id, set(self.sections)), self.current_id)
        self.assertIsNone(app.resolve_section_id("cccccccccccc", set(self.sections)))
        self.assertIsNone(app.resolve_section_id("eeeeeeeeeeee", set(self.sections)))
        self.assertIsNone(app.resolve_section_id("not-an-id", set(self.sections)))

    def test_alias_note_and_activity_are_counted_without_moving_note(self):
        self.write_aliases({self.legacy_id: {"current_id": self.current_id, "confidence": "high"}})
        note = app.NOTES_DIR / f"{self.legacy_id}.md"
        app.atomic_write(note, "旧笔记正文")
        before_hash = hashlib.sha256(note.read_bytes()).hexdigest()
        timestamp = datetime(2026, 8, 28, 12, 0).timestamp()
        os.utime(note, (timestamp, timestamp))
        app.atomic_write(
            app.ACTIVITY_PATH,
            json.dumps(
                {
                    "schema_version": 1,
                    "days": {
                        "2026-08-28": {
                            "sections": [self.legacy_id],
                            "notes": [self.legacy_id],
                            "reading_seconds": 120,
                            "section_reading_seconds": {self.legacy_id: 120},
                            "last_section_id": self.legacy_id,
                        }
                    },
                    "last_section_id": self.legacy_id,
                },
                ensure_ascii=False,
            ),
        )

        summary = app.book_learning_summary(self.book, self.sections)
        stats = app.learning_stats([self.book], self.sections)
        self.assertEqual(summary["learned_section_count"], 1)
        self.assertEqual(summary["note_count"], 1)
        self.assertEqual(summary["reading_seconds"], 120)
        self.assertEqual(summary["last_section"]["id"], self.current_id)
        self.assertEqual(stats["noted_section_count"], 1)
        self.assertEqual(stats["total_reading_seconds"], 120)
        self.assertEqual(stats["last_section"]["id"], self.current_id)
        review = app.review_payload("2026-08-28", [self.book], self.sections)
        self.assertEqual(review["note_count"], 1)
        self.assertEqual(review["subjects"][0]["notes"][0]["section_id"], self.current_id)
        self.assertEqual(review["subjects"][0]["reading_seconds"], 120)
        self.assertEqual(hashlib.sha256(note.read_bytes()).hexdigest(), before_hash)
        self.assertFalse((app.NOTES_DIR / f"{self.current_id}.md").exists())

    def test_unarchived_report_is_metadata_only_and_lists_unresolved_note(self):
        unresolved = app.NOTES_DIR / "cccccccccccc.md"
        app.atomic_write(unresolved, "不可猜测的笔记正文")
        report = app.unarchived_learning_records(self.sections)
        self.assertEqual(report["note_count"], 1)
        self.assertEqual(report["notes"][0]["legacy_id"], "cccccccccccc")
        self.assertEqual(report["notes"][0]["mapping_status"], "unmapped")
        self.assertNotIn("不可猜测的笔记正文", json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
