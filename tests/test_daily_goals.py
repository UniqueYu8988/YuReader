import io
import json
import tempfile
import unittest
from pathlib import Path

import app
import yureader.goals as goals_mod


class GoalsHandlerHarness(app.ReaderHandler):
    def __init__(self, method: str, path: str, payload: dict | None = None):
        self.command = method
        self.path = path
        encoded = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8") if payload else b""
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


class DailyGoalsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data_dir = self.root / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.orig_goals_path = goals_mod.GOALS_PATH
        self.orig_vocab_path = goals_mod.VOCAB_PROGRESS_PATH
        goals_mod.GOALS_PATH = self.data_dir / "goals.json"
        goals_mod.VOCAB_PROGRESS_PATH = self.data_dir / "vocab_progress.json"

    def tearDown(self):
        goals_mod.GOALS_PATH = self.orig_goals_path
        goals_mod.VOCAB_PROGRESS_PATH = self.orig_vocab_path
        self.temp.cleanup()

    def test_default_goals_loading(self):
        goals = goals_mod.load_goals()
        self.assertEqual(goals["total_hours"], 10.0)
        self.assertEqual(goals["reading"]["medicine_hours"], 4.0)
        self.assertEqual(goals["reading"]["politics_hours"], 0.5)
        self.assertEqual(goals["practice"]["medicine_definition"], 20)
        self.assertEqual(goals["practice"]["english_vocab"], 100)

    def test_save_and_reload_goals(self):
        new_goals = {
            "total_hours": 6.5,
            "reading": {"medicine_hours": 3.0, "politics_hours": 1.0, "english_hours": 0.5},
            "practice": {"medicine_definition": 25, "medicine_essay": 15, "politics_units": 3, "english_reading": 4, "english_vocab": 150},
        }
        saved = goals_mod.save_goals(new_goals)
        self.assertEqual(saved["total_hours"], 6.5)
        self.assertEqual(saved["reading"]["medicine_hours"], 3.0)
        self.assertEqual(saved["practice"]["politics_units"], 3)
        self.assertEqual(saved["practice"]["english_vocab"], 150)

        reloaded = goals_mod.load_goals()
        self.assertEqual(reloaded["total_hours"], 6.5)
        self.assertEqual(reloaded["practice"]["medicine_definition"], 25)
        self.assertEqual(reloaded["practice"]["english_vocab"], 150)

    def test_http_get_and_post_goals(self):
        # 1. GET initial
        harness_get = GoalsHandlerHarness("GET", "/api/daily-goals")
        harness_get.do_GET()
        self.assertEqual(harness_get.status, 200)
        payload = json.loads(harness_get.wfile.getvalue().decode("utf-8"))
        self.assertIn("goals", payload)
        self.assertIn("progress", payload)

        # 2. POST update
        update_data = {
            "total_hours": 12.0,
            "reading": {"medicine_hours": 5.0, "politics_hours": 1.5, "english_hours": 1.0},
            "practice": {"medicine_definition": 30, "medicine_essay": 10, "politics_units": 5, "english_reading": 3},
        }
        harness_post = GoalsHandlerHarness("POST", "/api/daily-goals", update_data)
        harness_post.do_POST()
        self.assertEqual(harness_post.status, 200)
        saved_resp = json.loads(harness_post.wfile.getvalue().decode("utf-8"))
        self.assertEqual(saved_resp["total_hours"], 12.0)

    def test_oral_focus_progress_counts_in_daily_goals(self):
        item_types = goals_mod._load_oral_item_types()
        if not item_types:
            self.skipTest("Oral focus content dataset not present in environment")
        
        # Pick one definition and one essay item
        def_id = next((k for k, v in item_types.items() if v == "definition"), None)
        essay_id = next((k for k, v in item_types.items() if v == "essay"), None)
        self.assertIsNotNone(def_id)
        self.assertIsNotNone(essay_id)

        # Mock oral focus progress
        today_iso = goals_mod.date.today().isoformat()
        orig_prog_path = goals_mod.ORAL_FOCUS_PROGRESS_PATH
        mock_prog_path = self.data_dir / "oral_progress.json"
        mock_prog_path.write_text(
            json.dumps({
                "schema_version": 1,
                "items": {
                    def_id: {"updated_at": f"{today_iso}T10:00:00+08:00", "mastery": "learning", "memory_note": "Test note"},
                    essay_id: {"updated_at": f"{today_iso}T11:00:00+08:00", "mastery": "learning", "memory_note": "Essay note"},
                }
            }, ensure_ascii=False),
            encoding="utf-8"
        )
        try:
            goals_mod.ORAL_FOCUS_PROGRESS_PATH = mock_prog_path
            payload = goals_mod.daily_goals_payload(today_iso)
            practice = payload["progress"]["practice"]
            self.assertGreaterEqual(practice["medicine_definition"], 1)
            self.assertGreaterEqual(practice["medicine_essay"], 1)
        finally:
            goals_mod.ORAL_FOCUS_PROGRESS_PATH = orig_prog_path

    def test_vocab_progress_and_api(self):
        day = "2026-09-05"
        # 1. Direct save_vocab_progress
        saved = goals_mod.save_vocab_progress(85, day)
        self.assertEqual(saved["words_count"], 85)

        # 2. Check daily_goals_payload
        payload = goals_mod.daily_goals_payload(day)
        self.assertEqual(payload["progress"]["practice"]["english_vocab"], 85)

        # 3. GET /api/daily-vocab
        harness_get = GoalsHandlerHarness("GET", f"/api/daily-vocab?day={day}")
        harness_get.do_GET()
        self.assertEqual(harness_get.status, 200)
        res_get = json.loads(harness_get.wfile.getvalue().decode("utf-8"))
        self.assertTrue(res_get["ok"])
        self.assertEqual(res_get["vocab"]["words_count"], 85)

        # 4. POST /api/daily-vocab
        harness_post = GoalsHandlerHarness("POST", "/api/daily-vocab", {"day": day, "count": 120})
        harness_post.do_POST()
        self.assertEqual(harness_post.status, 200)
        res_post = json.loads(harness_post.wfile.getvalue().decode("utf-8"))
        self.assertTrue(res_post["ok"])
        self.assertEqual(res_post["result"]["words_count"], 120)
        self.assertEqual(res_post["goals"]["progress"]["practice"]["english_vocab"], 120)


if __name__ == "__main__":
    unittest.main()
