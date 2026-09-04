import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app
from yureader.oral_focus import oral_focus_due_items, oral_focus_due_session
from yureader.practice import create_mistakes_practice_session, practice_question, mistakes_overview

class UpgradesSuiteTests(unittest.TestCase):
    def test_oral_focus_due_items_structure(self):
        due = oral_focus_due_items(limit=10)
        self.assertIsInstance(due, dict)
        self.assertIn('total_due', due)
        self.assertIn('definitions_due', due)
        self.assertIn('essays_due', due)
        self.assertIn('by_subject', due)
        self.assertIn('items', due)
        self.assertIsInstance(due['items'], list)

    def test_oral_focus_due_session_structure(self):
        session = oral_focus_due_session(limit=10)
        self.assertIsInstance(session, dict)
        self.assertTrue(session.get('is_due_session'))
        self.assertIn('subject', session)
        self.assertIn('chapter', session)
        self.assertIn('items', session)

    def test_create_mistakes_practice_session(self):
        session = create_mistakes_practice_session()
        self.assertIsInstance(session, dict)
        self.assertTrue(session.get('is_mistakes_session'))
        self.assertIn('bank', session)
        self.assertIn('questions', session)
        self.assertIn('question_count', session)
        self.assertEqual(session['bank']['id'], 'mistakes-session')

    def test_practice_question_fallback(self):
        banks = app.question_bank_catalog()
        if banks:
            first_bank = banks[0]
            questions = app.load_bank_questions(first_bank['id'])
            if questions:
                first_qid = questions[0]['question_id']
                res = practice_question('mistakes-session', first_qid)
                self.assertIsInstance(res, dict)
                self.assertEqual(res['question']['question_id'], first_qid)

    def test_markdown_nested_list_renderer(self):
        import subprocess
        script = """
        const vm = require('vm');
        const fs = require('fs');
        const code = fs.readFileSync('static/markdown.js', 'utf8');
        const sandbox = { window: {}, DOMParser: class { parseFromString() { return { body: { querySelector() { return null; } } }; } } };
        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);
        const md = sandbox.window.YuReaderMarkdown.create((s) => s);
        const input = '* P1\\n  * C1\\n  * C2\\n* P2';
        const html = md.renderMarkdown(input);
        if (html !== '<ul><li>P1<ul><li>C1</li><li>C2</li></ul></li><li>P2</li></ul>') {
            console.error('Mismatch:', html);
            process.exit(1);
        }
        """
        res = subprocess.run(['node', '-e', script], cwd=str(ROOT), capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Node markdown test failed: {res.stderr}")

if __name__ == '__main__':
    unittest.main()

