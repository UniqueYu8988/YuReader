import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app
from yureader.catalog import build_catalog
from yureader.activity import learning_stats
from yureader.practice import practice_overview

class EnglishShelfTests(unittest.TestCase):
    def test_status_not_ready_never_enters_catalog(self):
        books, sections = app.catalog()
        ebbinghaus = [b for b in books if 'ebbinghaus' in b.get('id', '')]
        self.assertEqual(ebbinghaus, [], 'english-method-ebbinghaus must NEVER enter catalog')
        for b in books:
            if b.get('status'):
                self.assertEqual(b['status'], 'ready', f'{b["id"]} must have status ready')

    def test_five_canonical_books_present(self):
        books, sections = app.catalog()
        book_ids = {b['id'] for b in books if b.get('domain') == 'english'}
        expected_canonical = {
            'english-grammar-long-sentences',
            'english-58-basic-reading',
            'english-vocab-redbook',
            'english-method-wordbook',
            'english-method-88-sentences',
        }
        for expected in expected_canonical:
            self.assertIn(expected, book_ids, f'Missing canonical book: {expected}')

    def test_book_progress_in_learning_stats(self):
        books, sections = app.catalog()
        stats = learning_stats(books, sections)
        self.assertIn('book_progress', stats)
        bp = stats['book_progress']
        for b_id in ['english-grammar-long-sentences', 'english-58-basic-reading', 'english-vocab-redbook', 'english-method-wordbook', 'english-method-88-sentences']:
            self.assertIn(b_id, bp)
            self.assertIn('learned_sections', bp[b_id])
            self.assertIn('total_sections', bp[b_id])
            self.assertGreater(bp[b_id]['total_sections'], 0)

    def test_english_exam_overview_reading_groups(self):
        # 2024 English I
        overview = practice_overview('english-2024-e1')
        self.assertIn('bank', overview)
        groups = overview.get('groups', [])
        # Find the 4 reading texts (questions 21-25, 26-30, 31-35, 36-40)
        reading_groups = [g for g in groups if g.get('start_number', 0) >= 21 and g.get('end_number', 0) <= 40]
        self.assertEqual(len(reading_groups), 4, f'Expected 4 reading text groups, found {len(reading_groups)}')
        for i, rg in enumerate(reading_groups):
            self.assertEqual(rg['question_count'], 5)
            self.assertIn(f'Text {i+1}', rg['label'])

    def test_practice_mistakes_endpoint(self):
        class DummyHandler(app.ReaderHandler):
            def __init__(self, path):
                self.path = path
                self.headers = {}
                self.rfile = io.BytesIO(b'')
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

        for path in ['/api/practice/mistakes', '/api/practice/mistakes/']:
            handler = DummyHandler(path)
            handler.do_GET()
            self.assertEqual(handler.status, 200, f'GET {path} failed with {handler.status}')
            response_json = json.loads(handler.wfile.getvalue().decode('utf-8'))
            self.assertIn('items', response_json)

if __name__ == '__main__':
    unittest.main()
