import unittest
from app import catalog
from yureader.activity import learning_stats


class StatsUpgradesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.books, cls.sections = catalog()

    def test_learning_stats_has_new_keys(self):
        stats = learning_stats(self.books, self.sections)
        self.assertIn("subject_balance", stats)
        self.assertIn("oral_funnel", stats)
        self.assertIn("mistake_analytics", stats)
        self.assertIn("last_7_days_trend", stats)
        self.assertIn("strategic_insights", stats)
        self.assertIn("subject_assets", stats)

    def test_subject_balance_structure_and_targets(self):
        stats = learning_stats(self.books, self.sections)
        balance = stats["subject_balance"]
        self.assertIn("medicine_seconds", balance)
        self.assertIn("politics_seconds", balance)
        self.assertIn("english_seconds", balance)
        self.assertIn("medicine_percent", balance)
        self.assertIn("politics_percent", balance)
        self.assertIn("english_percent", balance)
        self.assertIn("target_percents", balance)
        self.assertEqual(balance["target_percents"]["medicine"], 60)
        self.assertEqual(balance["target_percents"]["politics"], 20)
        self.assertEqual(balance["target_percents"]["english"], 20)
        self.assertIn("balance_score", balance)
        self.assertGreaterEqual(balance["balance_score"], 0)
        self.assertLessEqual(balance["balance_score"], 100)
        self.assertIn(balance["dominant_key"], {"medicine", "politics", "english"})
        self.assertTrue(bool(balance["dominant_label"]))

    def test_oral_funnel_structure(self):
        stats = learning_stats(self.books, self.sections)
        funnel = stats["oral_funnel"]
        for key in ("total_items", "unseen_count", "learning_count", "reviewing_count", "mastered_count", "mastery_rate", "due_today"):
            self.assertIn(key, funnel)
        self.assertEqual(
            funnel["total_items"],
            funnel["unseen_count"] + funnel["learning_count"] + funnel["reviewing_count"] + funnel["mastered_count"]
        )
        self.assertGreaterEqual(funnel["mastery_rate"], 0.0)
        self.assertLessEqual(funnel["mastery_rate"], 100.0)

    def test_mistake_analytics_structure(self):
        stats = learning_stats(self.books, self.sections)
        mistakes = stats["mistake_analytics"]
        for key in ("total", "resolved", "unresolved", "resolve_rate"):
            self.assertIn(key, mistakes)
        self.assertEqual(mistakes["total"], mistakes["resolved"] + mistakes["unresolved"])
        self.assertGreaterEqual(mistakes["resolve_rate"], 0.0)
        self.assertLessEqual(mistakes["resolve_rate"], 100.0)

    def test_last_7_days_trend(self):
        stats = learning_stats(self.books, self.sections)
        trend = stats["last_7_days_trend"]
        self.assertEqual(len(trend), 7)
        for d in trend:
            self.assertIn("date", d)
            self.assertIn("weekday", d)
            self.assertIn("short_date", d)
            self.assertIn("medicine_seconds", d)
            self.assertIn("politics_seconds", d)
            self.assertIn("english_seconds", d)
            self.assertIn("total_seconds", d)
            self.assertIn("output_events", d)
            self.assertGreaterEqual(d["medicine_seconds"], 0)
            self.assertGreaterEqual(d["politics_seconds"], 0)
            self.assertGreaterEqual(d["english_seconds"], 0)
            self.assertGreaterEqual(d["total_seconds"], 0)
            self.assertGreaterEqual(d["output_events"], 0)

    def test_strategic_insights(self):
        stats = learning_stats(self.books, self.sections)
        insights = stats["strategic_insights"]
        self.assertIsInstance(insights, list)
        self.assertGreaterEqual(len(insights), 1)
        valid_types = {"warning", "positive", "urgent", "action"}
        for item in insights:
            self.assertIn(item.get("type"), valid_types)
            self.assertTrue(bool(item.get("tag")))
            self.assertTrue(bool(item.get("content")))

    def test_subject_assets_extended_metrics(self):
        stats = learning_stats(self.books, self.sections)
        assets = stats["subject_assets"]
        # Medicine
        med = assets["medicine"]
        self.assertIn("coverage_percent", med)
        self.assertIn("learned_sections", med)
        self.assertIn("total_sections", med)
        self.assertIn("oral_studied", med)
        self.assertIn("oral_mastered", med)
        self.assertIn("oral_mastery_rate", med)
        # Politics
        pol = assets["politics"]
        self.assertIn("mistakes_total", pol)
        self.assertIn("mistakes_resolved", pol)
        self.assertIn("mistakes_unresolved", pol)
        self.assertIn("mistake_resolve_rate", pol)
        # English
        eng = assets["english"]
        self.assertIn("vocab_active_days", eng)
        self.assertIn("vocab_words", eng)


if __name__ == "__main__":
    unittest.main()
