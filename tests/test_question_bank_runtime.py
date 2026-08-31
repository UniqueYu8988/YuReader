"""Runtime question-bank index, read-only image assets, and atomic import tests.

These tests cover the YuReader-layer deliverables of the politics data
foundation: the read-only question-bank runtime index (distinct from lecture
books under content/), the manifest-constrained read-only image asset access
(path-traversal safe), and the atomic question-bank publisher.

The authoritative YuPractice validator stays untouched as a contract/validator
tool; ``tools.import_question_bank.py`` only orchestrates validation + atomic
publish + post-verify on top of it.
"""

import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app  # noqa: E402
from tools import import_question_bank  # noqa: E402


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_lecture_package(root: Path, book_id: str, images: tuple[str, ...] = ("figure-a.jpg",)) -> Path:
    """Build a YuBook schema-2 package with declared image assets."""
    package = root / book_id
    pages = package / "cleaned" / "pages"
    images_dir = package / "images"
    pages.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)

    section_ids: list[str] = []
    artifacts: list[dict] = []
    toc_section_ids: list[str] = []
    for order, title in ((1, "第一节 起点"), (2, "第二节 图片页")):
        section_id = hashlib.sha1(f"{book_id}\0{order}".encode("utf-8")).hexdigest()[:12]
        artifact = f"cleaned/pages/{order:03d}.md"
        content = f"# {title}\n正文内容…\n" + (f"\n![](images/{images[0]})\n" if order == 2 else "")
        (package / artifact).write_text(content, encoding="utf-8")
        artifacts.append(
            {
                "id": section_id,
                "order": order,
                "title": title,
                "artifact": artifact,
                "sha256": sha256_bytes((package / artifact).read_bytes()),
                "chapter_id": "tc1",
                "chapter_order": 1,
                "chapter_title": "第一章 起点",
                "section_order": order,
                "level": 2,
                "material_kind": "cleaned",
            }
        )
        section_ids.append(section_id)
        toc_section_ids.append(section_id)

    image_bytes = b"\xff\xd8\xff\xe0fake-image-content"
    (images_dir / images[0]).write_bytes(image_bytes)
    asset_files = [
        {"path": f"images/{images[0]}", "sha256": sha256_bytes(image_bytes)}
    ]

    manifest = {
        "schema_version": 2,
        "book": {
            "id": book_id,
            "title": "政治讲义",
            "edition": "2027年版",
            "status": "ready",
            "default_material": "cleaned",
            "domain": "politics",
            "subject": "马克思主义基本原理",
            "resource_type": "lecture",
        },
        "quality": {"status": "pass", "blocker_count": 0, "warning_count": 0},
        "toc": [{"id": "tc1", "order": 1, "title": "第一章 起点", "section_ids": toc_section_ids}],
        "sections": artifacts,
        "references": [],
        "assets": [str(i) for i in images],
        "assets_root": "images",
        "asset_integrity": {"algorithm": "sha256-file-list-v1", "count": len(asset_files), "files": asset_files},
        "knowledge_map": {"path": "knowledge-map.json", "entry_count": 2},
    }
    (package / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    knowledge_map = {
        "schema_version": 1,
        "book_id": book_id,
        "entries": [
            {"knowledge_id": "politics.marxism.ch01", "label": "第一章 起点", "path": ["政治", "马克思主义基本原理", "第一章 起点"], "kind": "chapter"},
            {"knowledge_id": "politics.marxism.ch01.s01", "label": "第一节 起点", "kind": "section"},
        ],
    }
    (package / "knowledge-map.json").write_text(json.dumps(knowledge_map, ensure_ascii=False), encoding="utf-8")
    return package


def copy_tree(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for path in source.rglob("*"):
        if path.is_file():
            relative = path.relative_to(source)
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(path.read_bytes())


class FakeHandler(app.ReaderHandler):
    """Minimal handler harness to exercise the HTTP routing surface."""

    def __init__(self, path: str, command: str = "GET"):
        self.path = path
        self.command = command
        self.request_version = "HTTP/1.1"
        self.headers = {}
        self.wfile = io.BytesIO()
        self.rfile = io.BytesIO(b"{}")
        self.status: int | None = None
        self.headers_out: dict[str, str] = {}

    def send_response(self, code: int, message: str | None = None) -> None:
        self.status = code

    def send_header(self, key: str, value: str) -> None:
        self.headers_out[key] = value

    def end_headers(self) -> None:
        pass

    def log_message(self, format: str, *args: object) -> None:
        return


class AtomicImportTests(unittest.TestCase):
    """tools/import_question_bank.py: validate, publish, backup, refuse."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "workspace"
        self.root = Path(self.temp.name) / "question-banks"
        candidate = self.workspace / "candidate"
        example = ROOT / "tools" / "yupractice" / "examples" / "minimal-valid"
        copy_tree(example, candidate)
        self.candidate = candidate

    def tearDown(self):
        self.temp.cleanup()

    def test_publish_only_canonical_runtime_set(self):
        result = import_question_bank.command_import(self.candidate, self.root)
        self.assertEqual(result["status"], "published")
        target = Path(result["target"])
        self.assertTrue((target / "manifest.json").is_file())
        self.assertTrue((target / "questions.jsonl").is_file())
        self.assertTrue((target / "knowledge-map.json").is_file())
        self.assertTrue((target / "source-index.json").is_file())
        self.assertTrue((target / "quarantine" / "questions.jsonl").is_file())
        self.assertTrue((target / "reports" / "validation.json").is_file())
        # Workspace scratch must never enter the runtime package.
        self.assertEqual(import_question_bank.find_scratch_files(target), [])
        for scratch in ("outline.json", "notes", "build_bank.py", "bank-manifest.json", "test-outline.json"):
            self.assertFalse((target / scratch).exists())
        self.assertTrue(result["verified"]["verified"])

    def test_replacement_keeps_backup_and_release_record(self):
        import_question_bank.command_import(self.candidate, self.root)
        second = import_question_bank.command_import(self.candidate, self.root)
        self.assertTrue(second["publish"]["replaced"])
        self.assertIsNotNone(second["publish"]["backup"])
        backup = self.root / second["publish"]["backup"]
        self.assertTrue(backup.is_dir())
        release_path = self.root / ".import-releases" / "politics-basic-bank.json"
        self.assertTrue(release_path.is_file())
        history = json.loads(release_path.read_text(encoding="utf-8"))
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["backup"], second["publish"]["backup"])

    def test_blocker_refuses_and_leaves_runtime_untouched(self):
        import_question_bank.command_import(self.candidate, self.root)
        # Break the formal questions so the re-validation finds a blocker.
        broken = self.workspace / "broken"
        copy_tree(ROOT / "tools" / "yupractice" / "examples" / "minimal-valid", broken)
        output = broken / "questions.jsonl"
        output.write_text('{"question_id":"bad","question_type":"single_choice","difficulty":"basic","scope":"chapter","unit_key":"x","local_number":1,"stem_md":"","options":[]}\n', encoding="utf-8")
        with self.assertRaises(import_question_bank.ImportError_) as caught:
            import_question_bank.command_import(broken, self.root)
        self.assertEqual(caught.exception.code, "blocked")
        target = self.root / "politics-basic-bank"
        self.assertTrue((target / "manifest.json").is_file())
        runtime_manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(runtime_manifest["question_count"], 4)

    def test_hash_mismatch_refuses(self):
        import_question_bank.command_import(self.candidate, self.root)
        tampered = self.workspace / "tampered"
        copy_tree(ROOT / "tools" / "yupractice" / "examples" / "minimal-valid", tampered)
        manifest = json.loads((tampered / "manifest.json").read_text(encoding="utf-8"))
        manifest["questions"]["sha256"] = "0" * 64
        (tampered / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(import_question_bank.ImportError_) as caught:
            import_question_bank.command_import(tampered, self.root)
        # The authoritative YuPractice validator reports the SHA-256 mismatch as
        # E009 (a blocker), so publication is refused before any publish step.
        self.assertEqual(caught.exception.code, "blocked")
        # The first-published bank remains intact; nothing was replaced.
        runtime_manifest = json.loads((self.root / "politics-basic-bank" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(runtime_manifest["question_count"], 4)


class QuestionBankRuntimeIndexTests(unittest.TestCase):
    """app.py read-only runtime index distinguishes lecture vs question_bank."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.content_root = Path(self.temp.name) / "content"
        self.qb_root = Path(self.temp.name) / "question-banks"
        self.content_root.mkdir(parents=True, exist_ok=True)
        self.qb_root.mkdir(parents=True, exist_ok=True)
        self.lecture = make_lecture_package(self.content_root, "lecture-x")
        copy_tree(ROOT / "tools" / "yupractice" / "examples" / "minimal-valid", self.qb_root / "politics-basic-bank")
        self.original_globals = {
            name: getattr(app, name)
            for name in ("CONTENT_DIR", "QUESTION_BANK_DIR", "DATA_DIR", "BOOK_ASSETS", "CATALOG_CACHE", "QUESTION_BANK_CACHE", "obsidian_vault")
        }
        app.CONTENT_DIR = self.content_root
        app.QUESTION_BANK_DIR = self.qb_root
        app.DATA_DIR = Path(self.temp.name) / "data"
        app.BOOK_ASSETS = {}
        app.CATALOG_CACHE = {"checked_at": 0.0, "signature": None, "books": [], "sections": {}}
        app.QUESTION_BANK_CACHE = {"checked_at": 0.0, "signature": None, "banks": []}
        app.obsidian_vault = lambda: None

    def tearDown(self):
        for name, value in self.original_globals.items():
            setattr(app, name, value)
        self.temp.cleanup()

    def test_lecture_book_loaded_as_politics_lecture(self):
        books, sections = app.build_catalog()
        self.assertEqual(len(books), 1)
        lecture = books[0]
        self.assertEqual(lecture["resource_type"], "lecture")
        self.assertEqual(lecture["domain"], "politics")
        self.assertEqual(lecture["asset_count"], 1)
        self.assertIn("politics.marxism.ch01", lecture["knowledge_ids"])
        self.assertEqual(len(sections), 2)

    def test_question_bank_index_is_separate_and_real(self):
        banks = app.build_question_bank_catalog()
        self.assertEqual(len(banks), 1)
        bank = banks[0]
        self.assertEqual(bank["id"], "politics-basic-bank")
        self.assertEqual(bank["resource_type"], "question_bank")
        self.assertEqual(bank["resource_type_label"], "题库")
        self.assertEqual(bank["question_count"], 4)
        self.assertEqual(bank["quarantined_count"], 1)
        self.assertEqual(bank["question_type_counts"], {"single_choice": 3, "multiple_choice": 1})
        self.assertIn("politics.marxism.chapter-01.section-02", bank["knowledge_ids"])
        # The lecture catalog must NOT include the question bank.
        books, _ = app.build_catalog()
        self.assertEqual([item["id"] for item in books], ["lecture-x"])

    def test_public_question_preserves_optional_reading_context(self):
        question = {
            "question_id": "english-2025-e1-q-21",
            "unit": "完形填空",
            "context_md": "Shared reading passage.",
            "stem_md": "What is the answer?",
            "options": [{"label": "A", "text_md": "A"}, {"label": "B", "text_md": "B"}],
            "correct_answers": ["B"],
        }
        public = app.public_question(question)
        self.assertEqual(public["context_md"], "Shared reading passage.")
        self.assertEqual(public["unit_label"], "完形填空")
        self.assertNotIn("correct_answers", public)

    def test_hidden_import_backup_is_not_catalogued(self):
        # Atomic replacement deliberately keeps a hidden recovery copy beside
        # the live bank.  Runtime discovery must expose one stable bank ID,
        # never a duplicate entry from that backup.
        copy_tree(self.qb_root / "politics-basic-bank", self.qb_root / ".backup-politics-basic-bank-20260830")
        banks = app.build_question_bank_catalog()
        self.assertEqual([item["id"] for item in banks], ["politics-basic-bank"])

    def test_question_bank_in_content_is_not_misread_as_book(self):
        # A YuPractice bank manifest (schema 1) under content/ must be ignored by
        # the bookshelf scanner; it is not a Markdown book package.
        copy_tree(ROOT / "tools" / "yupractice" / "examples" / "minimal-valid", self.content_root / "politics-basic-bank")
        books, _ = app.build_catalog()
        ids = [item["id"] for item in books]
        self.assertNotIn("politics-basic-bank", ids)

    def test_legacy_medicine_book_safe_fallback(self):
        package = self.content_root / "legacy-med"
        package.mkdir(parents=True, exist_ok=True)
        section_id = "abcdefabcdef"
        artifact = "cleaned/pages/001.md"
        (package / artifact).parent.mkdir(parents=True, exist_ok=True)
        content = "# 第一章 起点\n内容"
        (package / artifact).write_text(content, encoding="utf-8")
        manifest = {
            "schema_version": 2,
            "book": {"id": "legacy-med", "title": "旧医学书", "status": "ready", "default_material": "cleaned"},
            "quality": {"status": "pass", "blocker_count": 0, "warning_count": 0},
            "toc": [{"id": "tc1", "order": 1, "title": "第一章 起点", "section_ids": [section_id]}],
            "sections": [{"id": section_id, "order": 1, "title": "第一节 起点", "artifact": artifact, "sha256": sha256_bytes((package / artifact).read_bytes()), "level": 2, "material_kind": "cleaned"}],
        }
        (package / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        books, _ = app.build_catalog()
        legacy = next(item for item in books if item["id"] == "legacy-med")
        self.assertEqual(legacy["domain"], "medicine")
        self.assertEqual(legacy["resource_type"], "book")
        self.assertEqual(legacy["subject"], "旧医学书")
        self.assertEqual(legacy["asset_count"], 0)

    def test_practice_does_not_reveal_answers_until_submission(self):
        question_id = "politics-basic-marxism-ch01-s02-single-001"
        # The published minimal bank contains stable section positions and a
        # formal question; quarantine remains out of every practice read path.
        session = app.practice_session("politics-basic-bank", "politics.marxism.chapter-01.section-02", "section")
        self.assertEqual(session["question_count"], 1)
        question_id = session["questions"][0]["question_id"]
        before = app.practice_question("politics-basic-bank", question_id)
        self.assertNotIn("correct_answers", before["question"])

        handler = FakeHandler("/api/practice/answer", command="POST")
        handler.headers = {"Content-Length": ""}
        options = before["question"]["options"]
        encoded = json.dumps({"bank_id": "politics-basic-bank", "question_id": question_id, "selected_answers": [options[0]["label"]]}, ensure_ascii=False).encode("utf-8")
        handler.headers["Content-Length"] = str(len(encoded))
        handler.rfile = io.BytesIO(encoded)
        handler.do_POST()
        self.assertEqual(handler.status, 200)
        answer = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertIn("correct_answers", answer["question"])

        analysis = FakeHandler("/api/practice/analysis", command="POST")
        encoded = json.dumps({"bank_id": "politics-basic-bank", "question_id": question_id, "content": "我的判断过程。"}, ensure_ascii=False).encode("utf-8")
        analysis.headers = {"Content-Length": str(len(encoded))}
        analysis.rfile = io.BytesIO(encoded)
        analysis.do_POST()
        self.assertEqual(analysis.status, 200)
        saved = json.loads(analysis.wfile.getvalue().decode("utf-8"))
        self.assertTrue(Path(saved["path"]).is_file())
        self.assertIn("我的判断过程", Path(saved["path"]).read_text(encoding="utf-8"))

    def test_practice_overview_groups_questions_without_revealing_answers(self):
        overview = app.practice_overview("politics-basic-bank")
        self.assertEqual(overview["question_count"], 4)
        self.assertEqual([item["question_count"] for item in overview["groups"]], [2, 1, 1])
        self.assertEqual(overview["groups"][0]["start_index"], 0)
        self.assertEqual(overview["groups"][1]["start_index"], 2)
        self.assertNotIn("correct_answers", overview)
        self.assertNotIn("questions", overview)

    def test_practice_note_joins_the_subject_root_in_obsidian(self):
        vault = Path(self.temp.name) / "vault"
        (vault / ".obsidian").mkdir(parents=True)
        app.obsidian_vault = lambda: vault
        bank = app.question_bank_by_id("politics-basic-bank")
        target, storage, uri = app.practice_notes_target(bank)
        self.assertEqual(storage, "obsidian")
        self.assertTrue(target.is_relative_to(vault / "YuReader" / "政治" / "马克思主义基本原理"))
        self.assertEqual(target.name, "练习解析.md")
        self.assertIn("obsidian://open", uri)

    def test_practice_notes_split_one_cross_subject_bank_by_question_subject(self):
        """A shared politics bank must never put one subject's analysis in another."""
        original_load = app.load_bank_questions
        original_bank = app.question_bank_by_id
        questions = [
            {"question_id": "q-mao", "subject_label": "毛泽东思想和中国特色社会主义理论体系概论", "stem_md": "毛题", "correct_answers": ["A"]},
            {"question_id": "q-xi", "subject_label": "习近平新时代中国特色社会主义思想概论", "stem_md": "习题", "correct_answers": ["B"]},
        ]
        app.load_bank_questions = lambda _bank_id: questions
        app.question_bank_by_id = lambda _bank_id: {"id": "politics-basic-bank", "domain": "politics"}
        try:
            app.save_practice_store("analyses", {"items": {
                "q-mao": {"content": "毛解析"},
                "q-xi": {"content": "习解析"},
            }})
            target, storage, _ = app.write_practice_notes("politics-basic-bank", questions[0]["subject_label"])
            self.assertEqual(storage, "local")
            mao = app.DATA_DIR / "practice-notes" / "politics" / "毛泽东思想和中国特色社会主义理论体系概论.md"
            xi = app.DATA_DIR / "practice-notes" / "politics" / "习近平新时代中国特色社会主义思想概论.md"
            self.assertEqual(target, mao)
            self.assertIn("毛解析", mao.read_text(encoding="utf-8"))
            self.assertNotIn("q-xi", mao.read_text(encoding="utf-8"))
            self.assertIn("习解析", xi.read_text(encoding="utf-8"))
        finally:
            app.load_bank_questions = original_load
            app.question_bank_by_id = original_bank


class ImageAssetAccessTests(unittest.TestCase):
    """Read-only, manifest-constrained asset access without path traversal."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.content_root = Path(self.temp.name) / "content"
        self.qb_root = Path(self.temp.name) / "question-banks"
        self.content_root.mkdir(parents=True, exist_ok=True)
        self.qb_root.mkdir(parents=True, exist_ok=True)
        make_lecture_package(self.content_root, "lecture-x")
        copy_tree(ROOT / "tools" / "yupractice" / "examples" / "minimal-valid", self.qb_root / "politics-basic-bank")
        self.original = {
            name: getattr(app, name)
            for name in ("CONTENT_DIR", "QUESTION_BANK_DIR", "BOOK_ASSETS", "CATALOG_CACHE", "QUESTION_BANK_CACHE")
        }
        app.CONTENT_DIR = self.content_root
        app.QUESTION_BANK_DIR = self.qb_root
        app.BOOK_ASSETS = {}
        app.CATALOG_CACHE = {"checked_at": 0.0, "signature": None, "books": [], "sections": {}}
        app.QUESTION_BANK_CACHE = {"checked_at": 0.0, "signature": None, "banks": []}
        app.build_catalog()

    def tearDown(self):
        for name, value in self.original.items():
            setattr(app, name, value)
        self.temp.cleanup()

    def test_declared_image_resolves_inside_package(self):
        resolved = app.book_asset_path("lecture-x", "images/figure-a.jpg")
        self.assertIsNotNone(resolved)
        self.assertTrue(resolved.is_file())
        self.assertTrue(resolved.is_relative_to(self.content_root / "lecture-x"))

    def test_path_traversal_is_blocked(self):
        for hostile in (
            "images/../figure-a.jpg",
            "images/../../secret",
            "../lecture-x/images/figure-a.jpg",
            "images/figure-a.jpg/../../etc",
            "images/",
            "images",
            "other/figure-a.jpg",
            "images/secret.jpg",  # not declared in manifest
            "images/.hidden",
        ):
            self.assertIsNone(app.book_asset_path("lecture-x", hostile), hostile)

    def test_unknown_book_and_hostile_book_id_rejected(self):
        self.assertIsNone(app.book_asset_path("lecture-y", "images/figure-a.jpg"))
        self.assertIsNone(app.book_asset_path("../../etc", "images/figure-a.jpg"))
        self.assertIsNone(app.book_asset_path("lecture-x", "images/%2e%2e/figure-a.jpg"))

    def test_http_image_and_question_bank_endpoints(self):
        handler = FakeHandler(f"/api/book-assets/lecture-x/images/figure-a.jpg")
        handler.do_GET()
        self.assertEqual(handler.status, 200)
        self.assertEqual(handler.headers_out["Content-Type"], "image/jpeg")
        self.assertEqual(handler.wfile.getvalue(), b"\xff\xd8\xff\xe0fake-image-content")

        handler = FakeHandler("/api/book-assets/lecture-x/images/..%2fsecret")
        handler.do_GET()
        self.assertIn(handler.status, (400, 404))

        handler = FakeHandler("/api/question-banks")
        handler.do_GET()
        self.assertEqual(handler.status, 200)
        payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["banks"][0]["resource_type"], "question_bank")

        handler = FakeHandler("/api/practice/overview?bank_id=politics-basic-bank")
        handler.do_GET()
        self.assertEqual(handler.status, 200)
        payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(payload["question_count"], 4)
        self.assertEqual(payload["groups"][0]["label"], "第一单元 马克思主义基本原理")

        handler = FakeHandler("/api/bootstrap")
        handler.do_GET()
        payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(payload["question_bank_count"], 1)
        self.assertEqual([item["id"] for item in payload["books"]], ["lecture-x"])


if __name__ == "__main__":
    unittest.main()
