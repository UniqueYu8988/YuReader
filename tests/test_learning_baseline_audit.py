import json
import tempfile
import unittest
from pathlib import Path

from tools.audit_learning_system_baseline import build_report


class LearningBaselineAuditTests(unittest.TestCase):
    def test_report_records_hashes_and_unmapped_data_without_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            content = root / "content" / "book-a"
            content.mkdir(parents=True)
            page = content / "page.md"
            page.write_text("# 不应进入审计报告的正文\n用户正文", encoding="utf-8")
            manifest = {
                "schema_version": 2,
                "book": {"id": "book-a", "title": "测试书", "status": "ready"},
                "quality": {"status": "pass", "blocker_count": 0, "warning_count": 0},
                "sections": [{"id": "aaaaaaaaaaaa", "artifact": "page.md"}],
            }
            (content / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            notes = root / "data" / "notes"
            notes.mkdir(parents=True)
            (notes / "aaaaaaaaaaaa.md").write_text("用户笔记不应进入报告", encoding="utf-8")
            (notes / "orphan.md").write_text("失联笔记不应进入报告", encoding="utf-8")
            (root / "data" / "activity.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "last_section_id": "orphan-section",
                        "days": {"2026-09-01": {"reading_seconds": 12, "sections": ["orphan-section"]}},
                    }
                ),
                encoding="utf-8",
            )

            report = build_report(root, api_base="http://127.0.0.1:1", api_timeout=0.1)

            self.assertEqual(report["content"]["book_count"], 1)
            self.assertEqual(report["content"]["section_count"], 1)
            self.assertEqual(report["activity"]["total_reading_seconds"], 12)
            self.assertEqual(report["data"]["notes"]["unmapped_non_empty_count"], 1)
            self.assertEqual(report["mapping"]["unmapped_non_empty_note_paths"], ["data/notes/orphan.md"])
            self.assertEqual(report["activity"]["unmapped_activity_ids"][0]["ids"], ["orphan-section"])
            serialized = json.dumps(report, ensure_ascii=False)
            self.assertNotIn("用户笔记不应进入报告", serialized)
            self.assertNotIn("失联笔记不应进入报告", serialized)
            self.assertIn("sha256", report["data"]["notes"]["files"][0])


if __name__ == "__main__":
    unittest.main()
