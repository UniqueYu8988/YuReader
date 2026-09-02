import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

import app


class ReviewWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.originals = {name: getattr(app, name) for name in ("DATA_DIR", "NOTES_DIR", "REVIEWS_DIR", "REVIEW_WORKFLOW_DIR", "LOGS_DIR", "WEEKLY_DIR", "ACTIVITY_PATH", "obsidian_vault")}
        app.DATA_DIR = self.root
        app.NOTES_DIR = self.root / "notes"
        app.REVIEWS_DIR = self.root / "reviews"
        app.REVIEW_WORKFLOW_DIR = self.root / "review-workflow"
        app.LOGS_DIR = self.root / "logs"
        app.WEEKLY_DIR = self.root / "weekly-reports"
        app.ACTIVITY_PATH = self.root / "activity.json"
        app.obsidian_vault = lambda: None
        self.day = (date.today() - timedelta(days=1)).isoformat()
        self.books = [
            {"id": "book-a", "title": "学科甲", "sections": [{"id": "aaaaaaaaaaaa"}]},
            {"id": "book-b", "title": "学科乙", "sections": [{"id": "bbbbbbbbbbbb"}]},
        ]
        self.sections = {
            "aaaaaaaaaaaa": {"id": "aaaaaaaaaaaa", "title": "甲节", "book_title": "学科甲", "chapter_title": "甲章"},
            "bbbbbbbbbbbb": {"id": "bbbbbbbbbbbb", "title": "乙节", "book_title": "学科乙", "chapter_title": "乙章"},
        }
        timestamp = datetime.combine(date.fromisoformat(self.day), datetime.min.time()).timestamp() + 3600
        for section_id, content in (("aaaaaaaaaaaa", "甲笔记"), ("bbbbbbbbbbbb", "乙笔记内容")):
            target = app.NOTES_DIR / f"{section_id}.md"
            app.atomic_write(target, content)
            os.utime(target, (timestamp, timestamp))
        app.atomic_write(app.ACTIVITY_PATH, json.dumps({"schema_version": 1, "days": {self.day: {"reading_seconds": 90, "section_reading_seconds": {"aaaaaaaaaaaa": 30, "bbbbbbbbbbbb": 60}}}}, ensure_ascii=False))

    def tearDown(self):
        for name, value in self.originals.items():
            setattr(app, name, value)
        self.temp.cleanup()

    def write_legacy_workflow(self, day, payload):
        app.atomic_write(app.workflow_state_path(day), json.dumps(payload, ensure_ascii=False))

    def test_subject_tasks_use_real_note_and_time_totals(self):
        payload = app.review_payload(self.day, self.books, self.sections)
        self.assertEqual(payload["subject_count"], 2)
        self.assertEqual([item["reading_seconds"] for item in payload["subjects"]], [30, 60])
        self.assertFalse(payload["all_complete"])

    def test_legacy_daily_log_remains_readable_without_new_writes(self):
        self.write_legacy_workflow(self.day, {"subjects": {"book-a": "甲成果", "book-b": "乙成果"}, "summary": "昨日总述"})
        legacy_content = "# 旧学习日志\n\n## 昨日总结\n\n昨日总述\n\n## 分科复习\n\n### 学科甲\n\n甲成果\n\n### 学科乙\n\n乙成果"
        app.atomic_write(app.LOGS_DIR / f"{self.day}.md", legacy_content)
        payload = app.logs_payload(self.day)
        self.assertIn("昨日总述", payload["detail"]["content"])
        self.assertTrue(payload["detail"]["legacy"])
        self.assertEqual(payload["entries"][0]["source"], "legacy_log")

    def test_weekly_source_collects_daily_summaries_only(self):
        self.write_legacy_workflow(self.day, {"subjects": {"book-a": "详细成果"}, "summary": "每日总述"})
        year, week, _ = date.fromisoformat(self.day).isocalendar()
        payload = app.weekly_payload(f"{year}-W{week:02d}")
        self.assertIn("每日总述", payload["source_markdown"])
        self.assertNotIn("详细成果", payload["source_markdown"])

    def test_default_week_uses_latest_archived_summary_and_archives_are_listed(self):
        self.write_legacy_workflow(self.day, {"subjects": {"book-a": "甲成果", "book-b": "乙成果"}, "summary": "每日总述"})
        review = app.review_payload(self.day, self.books, self.sections)
        app.atomic_write(app.LOGS_DIR / f"{self.day}.md", "旧学习日志")
        year, week, _ = date.fromisoformat(self.day).isocalendar()
        weekly = app.weekly_payload()
        self.assertEqual(weekly["week"], f"{year}-W{week:02d}")
        app.atomic_write(app.WEEKLY_DIR / f"{weekly['week']}.md", "阶段总结")
        logs = app.logs_payload()
        self.assertEqual(logs["entries"][0]["date"], self.day)
        self.assertEqual(logs["weekly_entries"][0]["week"], weekly["week"])


if __name__ == "__main__":
    unittest.main()
