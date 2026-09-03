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
        goals_mod.GOALS_PATH = self.data_dir / "goals.json"

    def tearDown(self):
        goals_mod.GOALS_PATH = self.orig_goals_path
        self.temp.cleanup()

    def test_default_goals_loading(self):
        goals = goals_mod.load_goals()
        self.assertEqual(goals["total_hours"], 8.0)
        self.assertEqual(goals["reading"]["medicine_hours"], 2.0)
        self.assertEqual(goals["reading"]["politics_hours"], 0.5)
        self.assertEqual(goals["practice"]["medicine_definition"], 20)

    def test_save_and_reload_goals(self):
        new_goals = {
            "total_hours": 6.5,
            "reading": {"medicine_hours": 3.0, "politics_hours": 1.0, "english_hours": 0.5},
            "practice": {"medicine_definition": 25, "medicine_essay": 15, "politics_units": 3, "english_reading": 4},
        }
        saved = goals_mod.save_goals(new_goals)
        self.assertEqual(saved["total_hours"], 6.5)
        self.assertEqual(saved["reading"]["medicine_hours"], 3.0)
        self.assertEqual(saved["practice"]["politics_units"], 3)

        reloaded = goals_mod.load_goals()
        self.assertEqual(reloaded["total_hours"], 6.5)
        self.assertEqual(reloaded["practice"]["medicine_definition"], 25)

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
            "total_hours": 10.0,
            "reading": {"medicine_hours": 4.0, "politics_hours": 1.5, "english_hours": 1.0},
            "practice": {"medicine_definition": 30, "medicine_essay": 10, "politics_units": 5, "english_reading": 3},
        }
        harness_post = GoalsHandlerHarness("POST", "/api/daily-goals", update_data)
        harness_post.do_POST()
        self.assertEqual(harness_post.status, 200)
        saved_resp = json.loads(harness_post.wfile.getvalue().decode("utf-8"))
        self.assertEqual(saved_resp["total_hours"], 10.0)


if __name__ == "__main__":
    unittest.main()
