import hashlib
import io
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import app


class ReviewHandlerHarness(app.ReaderHandler):
    """Small in-memory HTTP harness for the unified review save route."""

    def __init__(self, path: str, payload: dict):
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.path = path
        self.headers = {"Content-Length": str(len(encoded))}
        self.rfile = io.BytesIO(encoded)
        self.wfile = io.BytesIO()
        self.status = None
        self.headers_out = {}

    def send_response(self, code: int, message: str | None = None) -> None:
        self.status = code

    def send_header(self, key: str, value: str) -> None:
        self.headers_out[key] = value

    def end_headers(self) -> None:
        pass

    def log_message(self, format: str, *args: object) -> None:
        return


class UnifiedActivityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.originals = {
            name: getattr(app, name)
            for name in ("DATA_DIR", "NOTES_DIR", "ACTIVITY_PATH", "REVIEWS_DIR", "REVIEW_WORKFLOW_DIR", "LOGS_DIR", "WEEKLY_DIR", "ENGLISH_NOTEBOOK_DIR", "SUBJECTIVE_DIR", "catalog", "obsidian_vault")
        }
        app.DATA_DIR = self.root / "data"
        app.NOTES_DIR = app.DATA_DIR / "notes"
        app.ACTIVITY_PATH = app.DATA_DIR / "activity.json"
        app.REVIEWS_DIR = app.DATA_DIR / "reviews"
        app.REVIEW_WORKFLOW_DIR = app.DATA_DIR / "review-workflow"
        app.LOGS_DIR = app.DATA_DIR / "logs"
        app.WEEKLY_DIR = app.DATA_DIR / "weekly-reports"
        app.ENGLISH_NOTEBOOK_DIR = app.DATA_DIR / "english-weekly"
        app.SUBJECTIVE_DIR = app.DATA_DIR / "subjective"
        app.obsidian_vault = lambda: None
        self.section_id = "aaaaaaaaaaaa"
        self.books = [{"id": "book-x", "title": "测试书", "domain": "medicine", "subject": "口腔医学", "sections": [{"id": self.section_id}]}]
        self.sections = {self.section_id: {"id": self.section_id, "title": "第一节", "book_title": "测试书", "chapter_title": "第一章"}}
        app.catalog = lambda: (self.books, self.sections)

    def tearDown(self):
        for name, value in self.originals.items():
            setattr(app, name, value)
        self.temp.cleanup()

    def write_legacy_workflow(self, day, payload):
        app.atomic_write(app.workflow_state_path(day), json.dumps(payload, ensure_ascii=False))

    def test_legacy_activity_migration_is_lossless_and_idempotent(self):
        app.atomic_write(
            app.ACTIVITY_PATH,
            json.dumps(
                {
                    "schema_version": 1,
                    "days": {
                        "2026-09-01": {
                            "sections": [self.section_id],
                            "reading_seconds": 42,
                            "section_reading_seconds": {self.section_id: 42},
                            "last_section_id": self.section_id,
                        }
                    },
                    "last_section_id": self.section_id,
                },
                ensure_ascii=False,
            ),
        )
        first = app.migrate_activity_index()
        first_bytes = app.ACTIVITY_PATH.read_bytes()
        second = app.migrate_activity_index()
        second_bytes = app.ACTIVITY_PATH.read_bytes()
        self.assertEqual(first["schema_version"], 3)
        self.assertEqual(second["days"]["2026-09-01"]["reading_seconds"], 42)
        self.assertEqual(len(first["days"]["2026-09-01"]["activities"]), 1)
        self.assertEqual(first["days"]["2026-09-01"]["activities"][0]["duration_seconds"], 42)
        self.assertEqual(first_bytes, second_bytes)
        self.assertEqual(hashlib.sha256(first_bytes).hexdigest(), hashlib.sha256(second_bytes).hexdigest())

    def test_legacy_list_sections_backfill_and_read_query_are_non_mutating(self):
        legacy = {
            "schema_version": 1,
            "days": {
                "2026-09-01": {
                    "sections": [self.section_id],
                    "reading_seconds": 42,
                    "section_reading_seconds": {self.section_id: 42},
                    "last_section_id": self.section_id,
                }
            },
        }
        app.atomic_write(app.ACTIVITY_PATH, json.dumps(legacy, ensure_ascii=False))
        before = app.ACTIVITY_PATH.read_bytes()
        payload = app.activity_records_payload()
        self.assertEqual(payload["activities"][0]["activity_type"], "read")
        self.assertEqual(payload["activities"][0]["duration_seconds"], 42)
        self.assertEqual(app.ACTIVITY_PATH.read_bytes(), before)
        migrated = app.migrate_activity_index()
        self.assertEqual(migrated["migration"]["legacy_activity_backfill"], "v2")
        self.assertEqual(len(migrated["days"]["2026-09-01"]["activities"]), 1)

    def test_five_activity_types_share_fields_and_resume_targets(self):
        app.record_activity("section_open", self.section_id)
        app.record_activity("reading_time", self.section_id, reading_seconds=20, idempotency_key="read-heartbeat-1")
        self.assertFalse(app.record_activity("reading_time", self.section_id, reading_seconds=20, idempotency_key="read-heartbeat-1"))
        contexts = [
            ("objective_practice", "english-2025-e1", "q-001", "英语", "practice"),
            ("subjective_practice", "english-exam-2025-e1-subjective", "cccccccccccc", "考研英语一", "subjective_practice"),
            ("notebook", "english-notebook", "2026-W36", "英语笔记", "english_notebook"),
            ("review", "book-x", "2026-09-01", "口腔医学", "review"),
        ]
        for activity_type, resource_id, item_id, subject_id, view in contexts:
            app.record_activity(
                activity_type,
                reading_seconds=7,
                activity_type=activity_type,
                context={
                    "domain": "english" if activity_type != "review" else "medicine",
                    "subject_id": subject_id,
                    "resource_id": resource_id,
                    "item_id": item_id,
                    "resume_target": {"view": view, "resource_id": resource_id, "item_id": item_id},
                },
                activity_id=app.activity_stable_id("test", activity_type),
                result_state="has_output",
            )
        payload = app.activity_records_payload()
        self.assertEqual({item["activity_type"] for item in payload["activities"]}, {"read", "objective_practice", "subjective_practice", "notebook", "review"})
        for item in payload["activities"]:
            for field in ("activity_id", "activity_type", "domain", "subject_id", "resource_id", "item_id", "started_at", "last_active_at", "duration_seconds", "resume_target", "output_refs", "result_state"):
                self.assertIn(field, item)
            self.assertTrue(item["resume_target"].get("item_id"))
        self.assertEqual(payload["by_activity_type"]["read"], 20)
        self.assertEqual(payload["by_activity_type"]["objective_practice"], 7)

    def test_reading_time_response_keeps_legacy_fields_and_adds_aggregates(self):
        app.record_activity(
            "objective_practice",
            reading_seconds=9,
            activity_type="objective_practice",
            context={"domain": "english", "subject_id": "英语一", "resource_id": "bank", "item_id": "q", "resume_target": {"view": "practice", "resource_id": "bank", "item_id": "q"}},
            activity_id="objective-test",
        )
        payload = app.reading_time_payload(day_count=1)
        self.assertIn("seconds", payload)
        self.assertIn("history", payload)
        self.assertEqual(payload["activity_totals"]["objective_practice"], 9)
        self.assertEqual(payload["domain_totals"]["english"], 9)

    def test_today_aggregate_exposes_continue_and_pending_review(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        app.atomic_write(
            app.ACTIVITY_PATH,
            json.dumps(
                {
                    "schema_version": 1,
                    "days": {
                        yesterday: {
                            "sections": [self.section_id],
                            "reading_seconds": 60,
                            "section_reading_seconds": {self.section_id: 60},
                            "last_section_id": self.section_id,
                            "last_reading_at": f"{yesterday}T20:00:00+08:00",
                        }
                    },
                },
                ensure_ascii=False,
            ),
        )
        app.record_activity(
            "objective_practice",
            activity_type="objective_practice",
            context={
                "domain": "english",
                "subject_id": "英语一",
                "resource_id": "bank",
                "item_id": "question-1",
                "resume_target": {"view": "practice", "resource_id": "bank", "item_id": "question-1"},
            },
            activity_id="today-objective",
            result_state="has_output",
            output_refs=[{"kind": "objective_attempt", "id": "question-1", "path": "attempts.json"}],
        )
        stats = app.learning_stats(self.books, self.sections, weeks=1)
        self.assertEqual(stats["review_pending"]["date"], yesterday)
        self.assertEqual(stats["today_activity_count"], 1)
        self.assertEqual(stats["continue_target"]["view"], "practice")
        self.assertEqual(stats["continue_target"]["item_id"], "question-1")

    def test_stats_use_deduped_activity_time_and_keep_legacy_compatibility(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        earlier = (date.today() - timedelta(days=2)).isoformat()

        def activity(activity_id, activity_type, domain, seconds, item_id, result_state="in_progress"):
            return {
                "activity_id": activity_id,
                "activity_type": activity_type,
                "domain": domain,
                "subject_id": domain,
                "resource_id": "book-x",
                "item_id": item_id,
                "started_at": f"{yesterday}T10:00:00+08:00",
                "last_active_at": f"{yesterday}T10:01:00+08:00",
                "duration_seconds": seconds,
                "resume_target": {"view": "reader", "resource_id": "book-x", "item_id": item_id},
                "output_refs": [],
                "result_state": result_state,
            }

        app.atomic_write(
            app.ACTIVITY_PATH,
            json.dumps(
                {
                    "schema_version": 3,
                    "migration": {"legacy_activity_backfill": "v2"},
                    "days": {
                        yesterday: {
                            "reading_seconds": 80,
                            "activities": [
                                activity("read-stats", "read", "medicine", 60, self.section_id),
                                activity("objective-stats", "objective_practice", "english", 12, "question-1", "has_output"),
                            ],
                        },
                        earlier: {
                            "activities": [activity("review-stats", "review", "politics", 0, earlier, "completed")],
                        },
                    },
                },
                ensure_ascii=False,
            ),
        )
        stats = app.learning_stats(self.books, self.sections, weeks=1)
        self.assertEqual(stats["total_activity_seconds"], 72)
        self.assertEqual(sum(stats["activity_totals"].values()), 72)
        self.assertEqual(sum(stats["activity_domain_totals"].values()), 72)
        self.assertEqual(stats["total_reading_seconds"], 80)
        self.assertEqual(stats["unified_reading_seconds"], 60)
        self.assertEqual(stats["legacy_unmapped_reading_seconds"], 20)
        self.assertEqual(stats["active_day_count"], 2)
        self.assertEqual(stats["streak"], 2)
        yesterday_cell = next(item for item in stats["days"] if item["date"] == yesterday)
        earlier_cell = next(item for item in stats["days"] if item["date"] == earlier)
        self.assertEqual(yesterday_cell["activity_seconds"], 72)
        self.assertEqual(yesterday_cell["legacy_unmapped_reading_seconds"], 20)
        self.assertTrue(earlier_cell["active"])
        self.assertEqual(earlier_cell["activity_seconds"], 0)
        self.assertEqual(stats["heatmap_total_seconds"], 72)

    def test_short_open_is_resumable_but_not_active_or_reviewable(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        short_open = {
            "activity_id": "short-open",
            "activity_type": "read",
            "domain": "medicine",
            "subject_id": "口腔医学",
            "resource_id": "book-x",
            "item_id": self.section_id,
            "started_at": f"{yesterday}T10:00:00+08:00",
            "last_active_at": f"{yesterday}T10:00:07+08:00",
            "duration_seconds": 7,
            "resume_target": {"view": "reader", "resource_id": "book-x", "item_id": self.section_id},
            "output_refs": [],
            "result_state": "in_progress",
        }
        app.atomic_write(app.ACTIVITY_PATH, json.dumps({"schema_version": 3, "migration": {"legacy_activity_backfill": "v2"}, "days": {yesterday: {"activities": [short_open]}}}, ensure_ascii=False))
        stats = app.learning_stats(self.books, self.sections, weeks=1)
        self.assertEqual(stats["active_day_count"], 0)
        self.assertIsNone(stats["review_pending"])
        self.assertEqual(stats["continue_target"]["item_id"], self.section_id)
        self.assertEqual(app.reviewable_learning_days()[0], [])

    def test_activity_history_is_not_silently_pruned(self):
        old_day = "2020-01-01"
        app.atomic_write(
            app.ACTIVITY_PATH,
            json.dumps({"schema_version": 3, "migration": {"legacy_activity_backfill": "v2"}, "days": {old_day: {"reading_seconds": 60}}}, ensure_ascii=False),
        )
        app.record_activity(
            "objective_practice",
            activity_type="objective_practice",
            context={"domain": "english", "subject_id": "英语一", "resource_id": "bank", "item_id": "q", "resume_target": {"view": "practice", "resource_id": "bank", "item_id": "q"}},
            activity_id="new-output",
            result_state="has_output",
            output_refs=[{"kind": "objective_attempt", "id": "q", "path": "attempts.json"}],
        )
        self.assertIn(old_day, app.load_activity()["days"])

    def test_objective_review_includes_compact_question_context(self):
        day = (date.today() - timedelta(days=1)).isoformat()
        activity = {
            "activity_id": "objective-review-context",
            "activity_type": "objective_practice",
            "domain": "english",
            "subject_id": "英语一",
            "resource_id": "bank",
            "item_id": "q-1",
            "started_at": f"{day}T10:00:00+08:00",
            "last_active_at": f"{day}T10:01:00+08:00",
            "duration_seconds": 0,
            "resume_target": {"view": "practice", "resource_id": "bank", "item_id": "q-1"},
            "output_refs": [{"kind": "objective_attempt", "id": "q-1", "path": "attempts.json"}],
            "result_state": "has_output",
        }
        app.atomic_write(app.ACTIVITY_PATH, json.dumps({"schema_version": 3, "migration": {"legacy_activity_backfill": "v2"}, "days": {day: {"activities": [activity]}}}, ensure_ascii=False))
        question = {"question_id": "q-1", "local_number": 1, "stem_md": "Which answer is correct?", "options": [{"label": "A", "text_md": "Alpha"}, {"label": "B", "text_md": "Beta"}], "correct_answers": ["B"]}

        def practice_store(kind):
            if kind == "attempts":
                return {"items": {"q-1": {"selected_answers": ["A"], "correct": False}}}
            return {"items": {"q-1": {"content": "混淆了两个概念。"}}}

        with patch.object(app, "load_bank_questions", return_value=[question]), patch.object(app, "load_practice_store", side_effect=practice_store):
            source = app.review_source_records(day, self.books, self.sections)[0]
        self.assertIn("Which answer is correct?", source["markdown"])
        self.assertIn("**B** Beta", source["markdown"])
        self.assertIn("正确答案：B", source["markdown"])
        self.assertIn("混淆了两个概念", source["markdown"])

    def test_objective_timer_and_output_are_one_review_source(self):
        day = (date.today() - timedelta(days=1)).isoformat()
        question_id = "politics-question-1"
        timer_activity = {
            "activity_id": "objective-session-timer",
            "activity_type": "objective_practice",
            "domain": "politics",
            "subject_id": "考研政治（思想政治理论）",
            "resource_id": "politics-bank",
            "item_id": question_id,
            "started_at": f"{day}T10:00:00+08:00",
            "last_active_at": f"{day}T10:01:15+08:00",
            "duration_seconds": 75,
            "resume_target": {"view": "practice", "resource_id": "politics-bank", "item_id": question_id},
            "output_refs": [],
            "result_state": "in_progress",
        }
        output_activity = {
            "activity_id": "objective-answer-output",
            "activity_type": "objective_practice",
            "domain": "politics",
            "subject_id": "马克思主义基本原理",
            "resource_id": "politics-bank",
            "item_id": question_id,
            "started_at": f"{day}T10:01:00+08:00",
            "last_active_at": f"{day}T10:01:00+08:00",
            "duration_seconds": 0,
            "resume_target": {"view": "practice", "resource_id": "politics-bank", "item_id": question_id, "question_id": question_id},
            "output_refs": [{"kind": "objective_attempt", "id": question_id, "path": "attempts.json"}],
            "result_state": "has_output",
        }
        app.atomic_write(
            app.ACTIVITY_PATH,
            json.dumps({"schema_version": 3, "migration": {"legacy_activity_backfill": "v2"}, "days": {day: {"activities": [timer_activity, output_activity]}}}, ensure_ascii=False),
        )
        question = {"question_id": question_id, "local_number": 1, "stem_md": "哲学的基本问题是？", "options": [], "correct_answers": ["C"]}

        def practice_store(kind):
            if kind == "attempts":
                return {"items": {question_id: {"selected_answers": ["C"], "correct": True}}}
            return {"items": {}}

        with patch.object(app, "load_bank_questions", return_value=[question]), patch.object(app, "load_practice_store", side_effect=practice_store):
            effective = app.effective_activity_payload(day, include_review=False)
            review = app.review_payload(day, self.books, self.sections)

        self.assertEqual(effective["count"], 1)
        self.assertEqual(effective["duration_seconds"], 75)
        self.assertEqual(effective["activities"][0]["subject_id"], "马克思主义基本原理")
        self.assertEqual(review["activity_count"], 1)
        self.assertEqual(review["source_count"], 1)
        self.assertEqual(review["subject_count"], 1)
        self.assertEqual(review["sources"][0]["subject_key"], "politics:马克思主义基本原理")
        self.assertEqual(review["sources"][0]["duration_seconds"], 75)
        entry = next(item for item in app.logs_payload()["entries"] if item["date"] == day)
        self.assertEqual(entry["subject_count"], 1)

    def test_weekly_notebook_review_extracts_only_requested_day(self):
        markdown = "## 周二 · 9/1\n\nTuesday note\n\n## 周三 · 9/2\n\nWednesday note"
        extracted = app._english_notebook_day_markdown(markdown, "2026-09-01")
        self.assertIn("Tuesday note", extracted)
        self.assertNotIn("Wednesday note", extracted)

    def test_automatic_record_entry_reports_real_subject_count(self):
        day = (date.today() - timedelta(days=1)).isoformat()
        activity = {
            "activity_id": "logs-read",
            "activity_type": "read",
            "domain": "medicine",
            "subject_id": "口腔医学",
            "resource_id": "book-x",
            "item_id": self.section_id,
            "started_at": f"{day}T10:00:00+08:00",
            "last_active_at": f"{day}T10:01:00+08:00",
            "duration_seconds": 60,
            "resume_target": {"view": "reader", "resource_id": "book-x", "item_id": self.section_id},
            "output_refs": [],
            "result_state": "in_progress",
        }
        app.atomic_write(app.ACTIVITY_PATH, json.dumps({"schema_version": 3, "migration": {"legacy_activity_backfill": "v2"}, "days": {day: {"activities": [activity]}}}, ensure_ascii=False))
        entry = next(item for item in app.logs_payload()["entries"] if item["date"] == day)
        self.assertEqual(entry["subject_count"], 1)

    def test_weekly_view_derives_selected_daily_records_from_activity_index(self):
        day = (date.today() - timedelta(days=1)).isoformat()
        activity = {
            "activity_id": "weekly-read",
            "activity_type": "read",
            "domain": "medicine",
            "subject_id": "口腔医学",
            "resource_id": "book-x",
            "item_id": self.section_id,
            "started_at": f"{day}T10:00:00+08:00",
            "last_active_at": f"{day}T10:01:00+08:00",
            "duration_seconds": 60,
            "resume_target": {"view": "reader", "resource_id": "book-x", "item_id": self.section_id},
            "output_refs": [],
            "result_state": "in_progress",
        }
        app.atomic_write(
            app.ACTIVITY_PATH,
            json.dumps({"schema_version": 3, "migration": {"legacy_activity_backfill": "v2"}, "days": {day: {"activities": [activity]}}}, ensure_ascii=False),
        )
        year, week, _ = date.fromisoformat(day).isocalendar()
        payload = app.weekly_payload(f"{year}-W{week:02d}")
        self.assertEqual(payload["record_count"], 1)
        self.assertEqual(payload["duration_seconds"], 60)
        self.assertEqual(payload["activity_by_type"]["read"], 60)
        self.assertEqual(payload["daily_records"][0]["activity_count"], 1)
        self.assertIn("有效时长", payload["source_markdown"])

    def test_review_aggregates_activity_types_by_domain_and_subject(self):
        day = (date.today() - timedelta(days=1)).isoformat()
        activities = []
        for activity_type, domain, subject_id, resource_id, item_id, view, seconds in (
            ("read", "medicine", "口腔医学", "book-x", self.section_id, "reader", 30),
            ("objective_practice", "english", "英语一", "english-bank", "question-1", "practice", 12),
            ("subjective_practice", "english", "考研英语一", "english-subjective", "cccccccccccc", "subjective_practice", 18),
            ("notebook", "english", "英语笔记", "english-notebook", "2026-W36", "english_notebook", 5),
        ):
            activities.append(
                {
                    "activity_id": f"{activity_type}-review",
                    "activity_type": activity_type,
                    "domain": domain,
                    "subject_id": subject_id,
                    "resource_id": resource_id,
                    "item_id": item_id,
                    "started_at": f"{day}T10:00:00+08:00",
                    "last_active_at": f"{day}T10:01:00+08:00",
                    "duration_seconds": seconds,
                    "resume_target": {"view": view, "resource_id": resource_id, "item_id": item_id},
                    "output_refs": [],
                    "result_state": "has_output",
                }
            )
        app.atomic_write(app.ACTIVITY_PATH, json.dumps({"schema_version": 3, "migration": {"legacy_activity_backfill": "v2"}, "days": {day: {"activities": activities}}}, ensure_ascii=False))
        payload = app.review_payload(day, self.books, self.sections)
        self.assertEqual(payload["activity_count"], 4)
        self.assertEqual({item["source_type"] for item in payload["sources"]}, {"read", "objective_practice", "subjective_practice", "notebook"})
        self.assertEqual({item["subject_key"] for item in payload["sources"]}, {"medicine:口腔医学", "english:英语一", "english:考研英语一", "english:英语笔记"})
        self.assertEqual(payload["activity_by_type"]["objective_practice"], 12)

    def test_default_review_day_skips_latest_reviewed_learning_day(self):
        latest = (date.today() - timedelta(days=1)).isoformat()
        earlier = (date.today() - timedelta(days=2)).isoformat()
        app.atomic_write(
            app.ACTIVITY_PATH,
            json.dumps(
                {
                    "schema_version": 3,
                    "migration": {"legacy_activity_backfill": "v2"},
                    "days": {
                        latest: {"reading_seconds": 60, "review_saved": True},
                        earlier: {"reading_seconds": 60},
                    },
                },
                ensure_ascii=False,
            ),
        )
        self.assertEqual(app.next_review_day(), earlier)

    def test_timed_review_visit_does_not_mark_source_day_complete(self):
        source_day = (date.today() - timedelta(days=1)).isoformat()
        today = date.today().isoformat()
        source = {
            "activity_id": "source-read",
            "activity_type": "read",
            "domain": "medicine",
            "subject_id": "口腔医学",
            "resource_id": "book-x",
            "item_id": self.section_id,
            "duration_seconds": 60,
            "resume_target": {"view": "reader", "resource_id": "book-x", "item_id": self.section_id},
            "output_refs": [],
            "result_state": "in_progress",
        }
        visit = {
            "activity_id": "review-visit",
            "activity_type": "review",
            "domain": "medicine",
            "subject_id": "daily-review",
            "resource_id": "book-x",
            "item_id": source_day,
            "duration_seconds": 75,
            "resume_target": {"view": "review", "resource_id": "book-x", "item_id": source_day},
            "output_refs": [],
            "result_state": "in_progress",
        }
        app.atomic_write(app.ACTIVITY_PATH, json.dumps({"schema_version": 3, "migration": {"legacy_activity_backfill": "v2"}, "days": {source_day: {"activities": [source]}, today: {"activities": [visit]}}}, ensure_ascii=False))
        self.assertEqual(app.next_review_day(), source_day)
        stats = app.learning_stats(self.books, self.sections, weeks=1)
        self.assertEqual(stats["review_pending"]["date"], source_day)
        self.assertTrue(next(item for item in stats["days"] if item["date"] == today)["active"])

    def test_review_anchor_does_not_appear_as_recent_learning_resource(self):
        today = date.today().isoformat()
        activities = [
            {
                "activity_id": "read-resource",
                "activity_type": "read",
                "domain": "medicine",
                "subject_id": "口腔医学",
                "resource_id": "book-x",
                "item_id": self.section_id,
                "duration_seconds": 60,
                "last_active_at": f"{today}T10:00:00+08:00",
                "resume_target": {"view": "reader", "resource_id": "book-x", "item_id": self.section_id},
                "output_refs": [],
                "result_state": "in_progress",
            },
            {
                "activity_id": "review-anchor",
                "activity_type": "review",
                "domain": "medicine",
                "subject_id": "daily-review",
                "resource_id": "book-x",
                "item_id": (date.today() - timedelta(days=1)).isoformat(),
                "duration_seconds": 60,
                "last_active_at": f"{today}T11:00:00+08:00",
                "resume_target": {"view": "review", "resource_id": "book-x", "item_id": (date.today() - timedelta(days=1)).isoformat()},
                "output_refs": [],
                "result_state": "has_output",
            },
        ]
        app.atomic_write(app.ACTIVITY_PATH, json.dumps({"schema_version": 3, "migration": {"legacy_activity_backfill": "v2"}, "days": {today: {"activities": activities}}}, ensure_ascii=False))
        recent = app.learning_stats(self.books, self.sections, weeks=1)["recent_resources"]
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["resume_target"]["view"], "reader")
        self.assertEqual(recent[0]["title"], "测试书")

    def test_completed_review_does_not_override_learning_continuation(self):
        today = date.today().isoformat()
        source_day = (date.today() - timedelta(days=1)).isoformat()
        activities = [
            {
                "activity_id": "read-before-review",
                "activity_type": "read",
                "domain": "medicine",
                "subject_id": "口腔医学",
                "resource_id": "book-x",
                "item_id": self.section_id,
                "duration_seconds": 60,
                "last_active_at": f"{today}T10:00:00+08:00",
                "resume_target": {"view": "reader", "resource_id": "book-x", "item_id": self.section_id},
                "output_refs": [],
                "result_state": "in_progress",
            },
            {
                "activity_id": "completed-review",
                "activity_type": "review",
                "domain": "medicine",
                "subject_id": "daily-review",
                "resource_id": "book-x",
                "item_id": source_day,
                "duration_seconds": 60,
                "last_active_at": f"{today}T11:00:00+08:00",
                "resume_target": {"view": "review", "resource_id": "book-x", "item_id": source_day},
                "output_refs": [{"kind": "review_note", "id": source_day, "path": "review.md"}],
                "result_state": "has_output",
            },
        ]
        app.atomic_write(app.ACTIVITY_PATH, json.dumps({"schema_version": 3, "migration": {"legacy_activity_backfill": "v2"}, "days": {today: {"activities": activities}}}, ensure_ascii=False))
        stats = app.learning_stats(self.books, self.sections, weeks=1)
        self.assertEqual(stats["continue_target"]["view"], "reader")
        self.assertEqual(stats["continue_target"]["item_id"], self.section_id)
        self.assertEqual(len(stats["today_activities"]), 2)
        self.assertTrue(any(item["activity_type"] == "review" for item in stats["today_activities"]))

    def test_daily_learning_record_is_local_without_obsidian(self):
        day = (date.today() - timedelta(days=1)).isoformat()
        app.atomic_write(
            app.ACTIVITY_PATH,
            json.dumps(
                {
                    "schema_version": 3,
                    "migration": {"legacy_activity_backfill": "v2"},
                    "days": {
                        day: {
                            "activities": [
                                {
                                    "activity_id": "read-record",
                                    "activity_type": "read",
                                    "domain": "medicine",
                                    "subject_id": "口腔医学",
                                    "resource_id": "book-x",
                                    "item_id": self.section_id,
                                    "started_at": f"{day}T10:00:00+08:00",
                                    "last_active_at": f"{day}T10:00:00+08:00",
                                    "duration_seconds": 60,
                                    "resume_target": {"view": "reader", "resource_id": "book-x", "item_id": self.section_id},
                                    "output_refs": [],
                                    "result_state": "in_progress",
                                }
                            ]
                        }
                    },
                },
                ensure_ascii=False,
            ),
        )
        self.write_legacy_workflow(day, {"summary": "一次统一回顾", "summary_no_text": False})
        review = app.review_payload(day, self.books, self.sections)
        target, storage, _, content = app.write_daily_learning_record(review)
        self.assertEqual(storage, "local")
        self.assertTrue(target.is_file())
        self.assertIn("一次统一回顾", content)
        logs = app.logs_payload()
        self.assertTrue(any(item["date"] == day and item["source"] == "learning_record" for item in logs["entries"]))
        detail = app.logs_payload(day)["detail"]
        self.assertFalse(detail.get("automatic", False))
        self.assertIn("一次统一回顾", detail["content"])

    def test_no_text_review_is_a_completed_explicit_state(self):
        day = (date.today() - timedelta(days=1)).isoformat()
        app.atomic_write(app.ACTIVITY_PATH, json.dumps({"schema_version": 3, "migration": {"legacy_activity_backfill": "v2"}, "days": {day: {"reading_seconds": 1}}}, ensure_ascii=False))
        self.write_legacy_workflow(day, {"summary": "", "summary_no_text": True})
        review = app.review_payload(day, self.books, self.sections)
        self.assertTrue(review["review_done"])
        self.assertTrue(review["review_no_text"])
        _, _, _, content = app.write_daily_learning_record(review)
        self.assertIn("已标记为无文本回顾", content)

    def test_review_summary_http_save_writes_only_new_record(self):
        day = (date.today() - timedelta(days=1)).isoformat()
        app.atomic_write(
            app.ACTIVITY_PATH,
            json.dumps(
                {
                    "schema_version": 3,
                    "migration": {"legacy_activity_backfill": "v2"},
                    "days": {
                        day: {
                            "activities": [
                                {
                                    "activity_id": "read-save",
                                    "activity_type": "read",
                                    "domain": "medicine",
                                    "subject_id": "口腔医学",
                                    "resource_id": "book-x",
                                    "item_id": self.section_id,
                                    "started_at": f"{day}T10:00:00+08:00",
                                    "last_active_at": f"{day}T10:01:00+08:00",
                                    "duration_seconds": 60,
                                    "resume_target": {"view": "reader", "resource_id": "book-x", "item_id": self.section_id},
                                    "output_refs": [],
                                    "result_state": "in_progress",
                                }
                            ]
                        }
                    },
                },
                ensure_ascii=False,
            ),
        )
        handler = ReviewHandlerHarness("/api/review-summary", {"date": day, "content": "一次统一回顾"})
        handler.do_POST()
        self.assertEqual(handler.status, 200)
        response = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertTrue(response["review"]["review_done"])
        record_path = Path(response["path"])
        self.assertTrue(record_path.is_file())
        self.assertEqual(response["storage"], "local")
        self.assertIn("一次统一回顾", record_path.read_text(encoding="utf-8"))
        self.assertFalse(app.REVIEW_WORKFLOW_DIR.exists())
        self.assertFalse(app.LOGS_DIR.exists())
        review_activities = [item for item in app.activity_records_payload().get("activities", []) if item.get("activity_type") == "review"]
        self.assertTrue(review_activities)

    def test_retired_review_write_routes_are_not_available(self):
        for path in ("/api/review-subject", "/api/review-notes"):
            handler = ReviewHandlerHarness(path, {"date": (date.today() - timedelta(days=1)).isoformat(), "content": "旧入口"})
            handler.do_POST()
            self.assertEqual(handler.status, 404)

    def test_new_record_and_legacy_log_are_merged_in_history(self):
        day = (date.today() - timedelta(days=1)).isoformat()
        self.write_legacy_workflow(day, {"summary": "旧总结"})
        app.atomic_write(app.LOGS_DIR / f"{day}.md", "旧日志正文")
        app.atomic_write(
            app.DATA_DIR / "learning-records" / day[:4] / day[5:7] / f"{day}.md",
            f"# {day} 学习记录\n\n## 本次回顾\n\n新总结",
        )
        logs = app.logs_payload(day)
        self.assertEqual(logs["entries"][0]["source"], "learning_record")
        self.assertTrue(logs["entries"][0]["legacy_available"])
        self.assertIn("新总结", logs["detail"]["content"])
        self.assertIn("旧日志正文", logs["detail"]["legacy_content"])

    def test_weekly_summary_http_save_uses_new_record_path(self):
        day = (date.today() - timedelta(days=1)).isoformat()
        year, week, _ = date.fromisoformat(day).isocalendar()
        requested_week = f"{year}-W{week:02d}"
        handler = ReviewHandlerHarness("/api/weekly-summary", {"week": requested_week, "content": "新阶段总结"})
        handler.do_POST()
        self.assertEqual(handler.status, 200)
        response = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(response["path"], str(app.DATA_DIR / "learning-records" / "weekly" / f"{requested_week}.md"))
        self.assertTrue(Path(response["path"]).is_file())
        self.assertFalse(app.REVIEW_WORKFLOW_DIR.exists())
        self.assertFalse(app.WEEKLY_DIR.exists())

    def test_legacy_navigation_paths_redirect_to_unified_concepts(self):
        for path, location in {
            "/bookshelf": "/#library",
            "/yesterday-review": "/#review",
            "/logs": "/#records",
            "/statistics": "/#records/stats",
        }.items():
            handler = ReviewHandlerHarness(path, {})
            handler.do_GET()
            self.assertEqual(handler.status, 303)
            self.assertEqual(handler.headers_out["Location"], location)


if __name__ == "__main__":
    unittest.main()
