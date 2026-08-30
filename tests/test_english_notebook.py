import tempfile
import unittest
from datetime import date
from pathlib import Path

import app


class EnglishNotebookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.originals = {name: getattr(app, name) for name in ("DATA_DIR", "ENGLISH_NOTEBOOK_DIR", "obsidian_vault")}
        app.DATA_DIR = self.root / "data"
        app.ENGLISH_NOTEBOOK_DIR = app.DATA_DIR / "english-weekly"
        app.obsidian_vault = lambda: None
        year, week, _ = date.today().isocalendar()
        self.week = f"{year}-W{week:02d}"

    def tearDown(self):
        for name, value in self.originals.items():
            setattr(app, name, value)
        self.temp.cleanup()

    def test_empty_payload_is_current_week_without_creating_a_file(self):
        payload = app.english_notebook_payload()
        self.assertEqual(payload["week"], self.week)
        self.assertEqual(payload["start"], app.week_bounds(self.week)[0].isoformat())
        self.assertEqual(payload["end"], app.week_bounds(self.week)[1].isoformat())
        self.assertEqual(payload["content"], "")
        self.assertEqual(payload["archives"], [])
        self.assertFalse(app.ENGLISH_NOTEBOOK_DIR.exists())

    def test_payload_reads_weekly_content_and_lists_archive(self):
        target = app.ENGLISH_NOTEBOOK_DIR / f"{self.week}.md"
        app.atomic_write(target, "## 周一\n\nword list")
        payload = app.english_notebook_payload(self.week)
        self.assertEqual(payload["content"], "## 周一\n\nword list\n")
        self.assertEqual(payload["character_count"], len("## 周一\n\nword list"))
        self.assertEqual([entry["week"] for entry in payload["archives"]], [self.week])
        self.assertTrue(payload["archives"][0]["current"])

    def test_week_value_is_validated_before_touching_files(self):
        with self.assertRaises(ValueError):
            app.english_notebook_target("../../escape")
        self.assertFalse(self.root.joinpath("escape.md").exists())

    def test_obsidian_target_is_separate_from_daily_logs(self):
        vault = self.root / "vault"
        (vault / ".obsidian").mkdir(parents=True)
        app.obsidian_vault = lambda: vault
        target, storage, uri = app.english_notebook_target(self.week)
        self.assertEqual(storage, "obsidian")
        self.assertTrue(target.is_relative_to(vault / "YuReader" / "英语周记"))
        self.assertIn("%E8%8B%B1%E8%AF%AD%E5%91%A8%E8%AE%B0", uri)
        self.assertNotIn("学习日志", target.parts)


if __name__ == "__main__":
    unittest.main()
