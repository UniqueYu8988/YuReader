"""Tests for the YuPractice question-bank package validator.

The helper ``build_package`` writes a deterministic correct package and lets
each test inject one defect through ``manifest_patch`` or by overriding an
individual question field, so every rule is exercised in isolation.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yupractice  # noqa: E402

SOURCES_DEFAULT = [
    {
        "source_id": "youtiku-basic",
        "filename": "优题库-基础题.md",
        "display_name": "优题库 基础题",
        "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "role": "primary",
        "blocks": [
            {
                "block_id": "b-0012",
                "page": "P3",
                "page_label": "第3页",
                "start_line": 231,
                "end_line": 233,
                "label": "第一章 单选",
            }
        ],
    }
]

MAP_DEFAULT = [
    {
        "knowledge_id": "politics.marxism.chapter-01.section-02",
        "label": "第一章 第二节",
        "path": ["政治", "马克思主义基本原理", "第一章", "第二节"],
        "kind": "section",
        "source_ref": {"source_id": "youtiku-basic", "block_id": "b-0012"},
    }
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def valid_question(question_id: str = "valid-q-001", **overrides) -> dict:
    question = {
        "question_id": question_id,
        "question_type": "single_choice",
        "difficulty": "basic",
        "scope": "chapter",
        "unit": "单元一",
        "unit_key": "u1",
        "local_number": 1,
        "stem_md": "这是一道格式正确的单选题。",
        "options": [
            {"label": "A", "text_md": "选项A"},
            {"label": "B", "text_md": "选项B"},
            {"label": "C", "text_md": "选项C"},
        ],
        "correct_answers": ["A"],
        "knowledge_ids": ["politics.marxism.chapter-01.section-02"],
        "source_refs": [{"source_id": "youtiku-basic", "block_id": "b-0012"}],
        "source_analysis_md": "【原书解析】选项A正确。",
        "status": "ready",
        "transformations": [],
    }
    question.update(overrides)
    return question


def build_package(
    root: Path,
    questions: list[dict],
    *,
    map_entries: list[dict] | None = None,
    sources: list[dict] | None = None,
    quarantine_questions: list[dict] | None = None,
    quarantine_reasons: dict | None = None,
    manifest_patch: dict | None = None,
    source_index_patch: dict | None = None,
    knowledge_map_patch: dict | None = None,
) -> Path:
    map_entries = MAP_DEFAULT if map_entries is None else map_entries
    sources = SOURCES_DEFAULT if sources is None else sources

    package_dir = root / "bank"
    package_dir.mkdir(parents=True, exist_ok=True)

    lines = "\n".join(json.dumps(q, ensure_ascii=False) for q in questions) + "\n"
    (package_dir / "questions.jsonl").write_text(lines, encoding="utf-8")
    knowledge_map = {"map_version": 1, "bank_id": "test-bank", "entries": map_entries}
    if knowledge_map_patch is not None:
        knowledge_map.update(knowledge_map_patch)
    (package_dir / "knowledge-map.json").write_text(
        json.dumps(knowledge_map, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    source_index = {"index_version": 1, "bank_id": "test-bank", "sources": sources}
    if source_index_patch is not None:
        source_index.update(source_index_patch)
    (package_dir / "source-index.json").write_text(
        json.dumps(source_index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    quarantine: list[dict] = []
    if quarantine_questions is not None:
        (package_dir / "quarantine").mkdir(exist_ok=True)
        quarantine_lines = "\n".join(json.dumps(q, ensure_ascii=False) for q in quarantine_questions) + "\n"
        (package_dir / "quarantine" / "questions.jsonl").write_text(quarantine_lines, encoding="utf-8")
        quarantine = quarantine_questions
        if quarantine_reasons is not None:
            (package_dir / "quarantine" / "reasons.json").write_text(
                json.dumps(quarantine_reasons, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    type_counts: dict[str, int] = {}
    for question in questions:
        qtype = question.get("question_type")
        if isinstance(qtype, str):
            type_counts[qtype] = type_counts.get(qtype, 0) + 1

    manifest = {
        "schema_version": 1,
        "bank": {
            "id": "test-bank",
            "title": "测试题库",
            "domain": "politics",
            "subject": "马克思主义基本原理",
            "resource_type": "question_bank",
            "status": "ready",
        },
        "sources": [
            {
                "source_id": source["source_id"],
                "filename": source["filename"],
                "sha256": source["sha256"],
                "role": source["role"],
            }
            for source in sources
        ],
        "question_count": len(questions),
        "quarantined_count": len(quarantine),
        "question_type_counts": type_counts,
        "knowledge_map": {
            "path": "knowledge-map.json",
            "sha256": sha256_bytes((package_dir / "knowledge-map.json").read_bytes()),
        },
        "questions": {
            "path": "questions.jsonl",
            "sha256": sha256_bytes((package_dir / "questions.jsonl").read_bytes()),
        },
        "source_index": {
            "path": "source-index.json",
            "sha256": sha256_bytes((package_dir / "source-index.json").read_bytes()),
        },
        "quality": {"status": "pass", "blocker_count": 0, "warning_count": 0},
        "generated_at": "2026-08-30T12:00:00",
        "generator": "yupractice/0.2.0",
    }
    if manifest_patch:
        manifest.update(manifest_patch)
    (package_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return package_dir


def validate(root_or_package: str | Path) -> dict:
    return yupractice.validate_package(Path(root_or_package))


class YuPracticeValidatorTests(unittest.TestCase):
    def test_valid_package_passes_with_zero_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(Path(tmp), [valid_question(), valid_question("valid-q-002", unit_key="u1", local_number=2)])
            result = validate(package)
            self.assertEqual(result["quality"]["status"], "pass")
            self.assertEqual(result["quality"]["blocker_count"], 0)
            self.assertEqual(result["quality"]["warning_count"], 0)
            self.assertEqual(result["summary"]["question_count"], 2)

    def test_manifest_question_count_mismatch_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(
                Path(tmp),
                [valid_question(), valid_question("valid-q-002", unit_key="u1", local_number=2)],
                manifest_patch={"question_count": 5},
            )
            result = validate(package)
            self.assertIn("E007", [blocker["code"] for blocker in result["blockers"]])

    def test_manifest_type_counts_mismatch_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(
                Path(tmp),
                [valid_question()],
                manifest_patch={"question_type_counts": {"single_choice": 2}},
            )
            result = validate(package)
            self.assertIn("E008", [blocker["code"] for blocker in result["blockers"]])

    def test_sha256_mismatch_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(Path(tmp), [valid_question()])
            (package / "questions.jsonl").write_text(
                (package / "questions.jsonl").read_text(encoding="utf-8") + "extra\n",
                encoding="utf-8",
            )
            result = validate(package)
            self.assertIn("E009", [blocker["code"] for blocker in result["blockers"]])

    def test_schema_version_mismatch_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(Path(tmp), [valid_question()], manifest_patch={"schema_version": 2})
            result = validate(package)
            self.assertIn("E003", [blocker["code"] for blocker in result["blockers"]])

    def test_duplicate_question_id_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(
                Path(tmp),
                [valid_question("dup-q-001"), valid_question("dup-q-001", stem_md="重复题干")],
            )
            result = validate(package)
            self.assertIn("E014", [blocker["code"] for blocker in result["blockers"]])

    def test_invalid_question_id_format_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(Path(tmp), [valid_question("Bad-ID-001")])
            result = validate(package)
            self.assertIn("E013", [blocker["code"] for blocker in result["blockers"]])

    def test_duplicate_composite_key_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(
                Path(tmp),
                [
                    valid_question("a-q-001", unit_key="u1", local_number=1),
                    valid_question("b-q-002", unit_key="u1", local_number=1),
                ],
            )
            result = validate(package)
            self.assertIn("E028", [blocker["code"] for blocker in result["blockers"]])

    def test_single_choice_with_two_answers_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(Path(tmp), [valid_question(correct_answers=["A", "B"])])
            result = validate(package)
            self.assertIn("E020", [blocker["code"] for blocker in result["blockers"]])

    def test_knowledge_id_not_in_map_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(
                Path(tmp),
                [valid_question(knowledge_ids=["politics.marxism.chapter-99"])],
            )
            result = validate(package)
            self.assertIn("E022", [blocker["code"] for blocker in result["blockers"]])

    def test_knowledge_id_syntax_invalid_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(
                Path(tmp),
                [valid_question(knowledge_ids=["Politics chapter 01"])],
            )
            result = validate(package)
            self.assertIn("E021", [blocker["code"] for blocker in result["blockers"]])

    def test_unresolvable_source_ref_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(
                Path(tmp),
                [valid_question(source_refs=[{"source_id": "youtiku-basic", "block_id": "b-9999"}])],
            )
            result = validate(package)
            self.assertIn("E024", [blocker["code"] for blocker in result["blockers"]])

    def test_missing_source_analysis_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(Path(tmp), [valid_question(source_analysis_md="")])
            result = validate(package)
            self.assertIn("E025", [blocker["code"] for blocker in result["blockers"]])

    def test_status_not_ready_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(Path(tmp), [valid_question(status="draft")])
            result = validate(package)
            self.assertIn("E026", [blocker["code"] for blocker in result["blockers"]])

    def test_invalid_transformations_structure_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(
                Path(tmp),
                [valid_question(transformations=[{"from": "旧", "to": "新", "reason": "缺少 type"}])],
            )
            result = validate(package)
            self.assertIn("E027", [blocker["code"] for blocker in result["blockers"]])

    def test_manifest_quality_declaration_mismatch_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(
                Path(tmp),
                [valid_question(status="draft")],
                manifest_patch={"quality": {"status": "pass", "blocker_count": 0, "warning_count": 0}},
            )
            result = validate(package)
            self.assertIn("E033", [blocker["code"] for blocker in result["blockers"]])

    def test_quarantine_leak_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            leaked = valid_question("leak-q-001")
            package = build_package(
                Path(tmp),
                [leaked],
                quarantine_questions=[
                    {
                        "question_id": "leak-q-001",
                        "question_type": "single_choice",
                        "status": "quarantined",
                        "stem_md": "隔离区与正式区重复的ID",
                        "options": leaked["options"],
                        "correct_answers": ["A"],
                        "knowledge_ids": [],
                        "source_refs": leaked["source_refs"],
                        "source_analysis_md": "保留原文",
                        "transformations": [],
                    }
                ],
                quarantine_reasons={"bank_id": "test-bank", "reasons": []},
            )
            result = validate(package)
            self.assertIn("E029", [blocker["code"] for blocker in result["blockers"]])

    def test_quarantine_without_reasons_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(
                Path(tmp),
                [valid_question()],
                quarantine_questions=[
                    {
                        "question_id": "quarantine-only-001",
                        "question_type": "single_choice",
                        "status": "quarantined",
                        "stem_md": "仅隔离区",
                        "options": valid_question()["options"],
                        "correct_answers": ["A"],
                        "knowledge_ids": [],
                        "source_refs": [],
                        "source_analysis_md": "",
                        "transformations": [],
                    }
                ],
            )
            result = validate(package)
            codes = [blocker["code"] for blocker in result["blockers"]]
            self.assertIn("E031", codes)
            self.assertIn("E032", codes)

    def test_valid_quarantine_with_reasons_passes_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(
                Path(tmp),
                [valid_question()],
                quarantine_questions=[
                    {
                        "question_id": "quarantined-ok-001",
                        "question_type": "single_choice",
                        "status": "quarantined",
                        "stem_md": "隔离区题目，ID不与正式区重复",
                        "options": valid_question()["options"],
                        "correct_answers": ["A"],
                        "knowledge_ids": [],
                        "source_refs": [{"source_id": "youtiku-basic", "block_id": "b-0012"}],
                        "source_analysis_md": "保留原文待复核",
                        "transformations": [],
                    }
                ],
                quarantine_reasons={
                    "bank_id": "test-bank",
                    "reasons": [
                        {
                            "question_id": "quarantined-ok-001",
                            "reason": "OCR置信度不足，保留原文待复核",
                            "confidence": "uncertain",
                        }
                    ],
                },
            )
            result = validate(package)
            codes = [blocker["code"] for blocker in result["blockers"]]
            self.assertNotIn("E029", codes)
            self.assertNotIn("E031", codes)
            self.assertNotIn("E032", codes)
            self.assertEqual(result["summary"]["quarantined_count"], 1)

    def test_orphan_knowledge_map_entry_is_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(
                Path(tmp),
                [valid_question()],
                map_entries=MAP_DEFAULT
                + [
                    {
                        "knowledge_id": "politics.marxism.chapter-02",
                        "label": "第二章（孤儿）",
                        "path": ["政治", "马克思主义基本原理", "第二章"],
                        "kind": "chapter",
                    }
                ],
                manifest_patch={"quality": {"status": "warning", "blocker_count": 0, "warning_count": 1}},
            )
            result = validate(package)
            self.assertEqual(result["quality"]["status"], "warning")
            self.assertEqual(result["quality"]["blocker_count"], 0)
            self.assertIn("W001", [warning["code"] for warning in result["warnings"]])

    def test_multiple_choice_with_two_answers_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            multiple = valid_question(
                "multi-q-001",
                question_type="multiple_choice",
                correct_answers=["A", "C"],
            )
            package = build_package(Path(tmp), [multiple])
            result = validate(package)
            self.assertEqual(result["quality"]["status"], "pass")

    def test_multiple_choice_with_single_answer_is_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            multiple = valid_question(
                "multi-q-001",
                question_type="multiple_choice",
                correct_answers=["A"],
            )
            package = build_package(
                Path(tmp),
                [multiple],
                manifest_patch={"quality": {"status": "warning", "blocker_count": 0, "warning_count": 1}},
            )
            result = validate(package)
            self.assertEqual(result["quality"]["status"], "warning")
            self.assertEqual(result["quality"]["blocker_count"], 0)
            self.assertIn("W003", [warning["code"] for warning in result["warnings"]])

    def test_empty_knowledge_ids_is_warning_not_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(
                Path(tmp),
                [valid_question(knowledge_ids=[])],
                map_entries=[],
                manifest_patch={"quality": {"status": "warning", "blocker_count": 0, "warning_count": 1}},
            )
            result = validate(package)
            self.assertEqual(result["quality"]["blocker_count"], 0)
            self.assertEqual(result["quality"]["warning_count"], 1)
            self.assertIn("W002", [warning["code"] for warning in result["warnings"]])

    def test_duplicate_correct_answer_labels_is_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            multiple = valid_question(
                "multi-q-001",
                question_type="multiple_choice",
                correct_answers=["A", "B", "A"],
            )
            package = build_package(
                Path(tmp),
                [multiple],
                manifest_patch={"quality": {"status": "warning", "blocker_count": 0, "warning_count": 1}},
            )
            result = validate(package)
            self.assertEqual(result["quality"]["blocker_count"], 0)
            self.assertIn("W009", [warning["code"] for warning in result["warnings"]])

    def test_non_consecutive_option_labels_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            question = valid_question(
                options=[
                    {"label": "A", "text_md": "选项A"},
                    {"label": "C", "text_md": "选项C"},
                    {"label": "D", "text_md": "选项D"},
                ]
            )
            package = build_package(Path(tmp), [question])
            result = validate(package)
            self.assertIn("E017", [blocker["code"] for blocker in result["blockers"]])

    def test_single_option_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(
                Path(tmp),
                [valid_question(options=[{"label": "A", "text_md": "唯一选项"}], correct_answers=["A"])],
            )
            result = validate(package)
            self.assertIn("E017", [blocker["code"] for blocker in result["blockers"]])

    def test_invalid_local_number_types_are_blockers_not_crashes(self) -> None:
        for invalid in ([], {}, "1", 0, True):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as tmp:
                package = build_package(Path(tmp), [valid_question(local_number=invalid)])
                result = validate(package)
                self.assertIn("E055", [blocker["code"] for blocker in result["blockers"]])

    def test_unhashable_correct_answer_is_blocker_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(Path(tmp), [valid_question(correct_answers=[{}])])
            result = validate(package)
            self.assertIn("E018", [blocker["code"] for blocker in result["blockers"]])

    def test_unhashable_transformation_type_is_blocker_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(
                Path(tmp),
                [valid_question(transformations=[{"type": [], "reason": "错误类型"}])],
            )
            result = validate(package)
            self.assertIn("E027", [blocker["code"] for blocker in result["blockers"]])

    def test_unhashable_manifest_status_is_blocker_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(
                Path(tmp),
                [valid_question()],
                manifest_patch={
                    "bank": {
                        "id": "test-bank",
                        "title": "测试题库",
                        "domain": "politics",
                        "subject": "马克思主义基本原理",
                        "resource_type": "question_bank",
                        "status": [],
                    }
                },
            )
            result = validate(package)
            self.assertIn("E004", [blocker["code"] for blocker in result["blockers"]])

    def test_promotional_residue_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(
                Path(tmp),
                [valid_question(options=[
                    {"label": "A", "text_md": "选项A"},
                    {"label": "B", "text_md": "选项B 扫描右侧二维码继续刷题"},
                ])],
            )
            result = validate(package)
            self.assertIn("E056", [blocker["code"] for blocker in result["blockers"]])

    def test_undeclared_question_image_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(
                Path(tmp),
                [valid_question(source_analysis_md="解析。![](images/promo.jpg)")],
            )
            result = validate(package)
            self.assertIn("E057", [blocker["code"] for blocker in result["blockers"]])

    def test_bank_status_not_ready_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(
                Path(tmp),
                [valid_question()],
                manifest_patch={
                    "bank": {
                        "id": "test-bank",
                        "title": "测试题库",
                        "domain": "politics",
                        "subject": "马克思主义基本原理",
                        "resource_type": "question_bank",
                        "status": "draft",
                    }
                },
            )
            result = validate(package)
            self.assertIn("E004", [blocker["code"] for blocker in result["blockers"]])

    def test_warning_only_package_has_nonzero_warnings_but_exit_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(
                Path(tmp),
                [valid_question()],
                map_entries=MAP_DEFAULT
                + [
                    {
                        "knowledge_id": "politics.marxism.chapter-02",
                        "label": "第二章（孤儿）",
                        "path": ["政治", "马克思主义基本原理", "第二章"],
                        "kind": "chapter",
                    }
                ],
                manifest_patch={"quality": {"status": "warning", "blocker_count": 0, "warning_count": 1}},
            )
            result = validate(package)
            self.assertEqual(result["quality"]["blocker_count"], 0)
            self.assertEqual(result["quality"]["warning_count"], 1)
            self.assertEqual(result["quality"]["status"], "warning")
            code = yupractice.cmd_validate(
                argparse_namespace(package, json_flag=False)
            )
            self.assertEqual(code, 0)

    # ---- new strict integrity rules ----

    def test_source_missing_source_id_is_blocker_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(
                Path(tmp),
                [valid_question()],
                # Old-style source-index: a source without source_id must not
                # raise KeyError in _build_source_lookup.
                source_index_patch={"sources": [{"id": "Q"}]},
            )
            result = validate(package)
            codes = [blocker["code"] for blocker in result["blockers"]]
            self.assertIn("E045", codes)  # missing source_id
            self.assertIn("E047", codes)  # missing filename/display_name/sha256/role
            self.assertIn("E048", codes)  # blocks not an array
            self.assertEqual(result["quality"]["status"], "blocked")

    def test_block_missing_block_id_is_blocker_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = {
                **SOURCES_DEFAULT[0],
                "blocks": [
                    {"id": "b-0012", "page": "P3", "start_line": 231, "end_line": 233}
                ],
            }
            package = build_package(Path(tmp), [valid_question()], sources=[source])
            result = validate(package)
            codes = [blocker["code"] for blocker in result["blockers"]]
            self.assertIn("E049", codes)  # missing block_id
            self.assertEqual(result["quality"]["status"], "blocked")

    def test_duplicate_source_id_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = {**SOURCES_DEFAULT[0]}
            second = {
                **SOURCES_DEFAULT[0],
                "blocks": [
                    {"block_id": "b-9999", "page": "P9", "start_line": 1, "end_line": 2}
                ],
            }
            package = build_package(
                Path(tmp), [valid_question()], sources=[first, second]
            )
            result = validate(package)
            self.assertIn("E046", [blocker["code"] for blocker in result["blockers"]])

    def test_duplicate_block_id_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = {
                **SOURCES_DEFAULT[0],
                "blocks": [
                    {"block_id": "b-0012", "page": "P3", "start_line": 231, "end_line": 233},
                    {"block_id": "b-0012", "page": "P4", "start_line": 300, "end_line": 302},
                ],
            }
            package = build_package(Path(tmp), [valid_question()], sources=[source])
            result = validate(package)
            self.assertIn("E050", [blocker["code"] for blocker in result["blockers"]])

    def test_start_line_greater_than_end_line_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = {
                **SOURCES_DEFAULT[0],
                "blocks": [
                    {"block_id": "b-0012", "page": "P3", "start_line": 300, "end_line": 100}
                ],
            }
            package = build_package(Path(tmp), [valid_question()], sources=[source])
            result = validate(package)
            self.assertIn("E052", [blocker["code"] for blocker in result["blockers"]])

    def test_knowledge_map_bank_id_mismatch_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(
                Path(tmp),
                [valid_question()],
                knowledge_map_patch={"bank_id": "other-bank"},
            )
            result = validate(package)
            self.assertIn("E039", [blocker["code"] for blocker in result["blockers"]])

    def test_source_index_bank_id_mismatch_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(
                Path(tmp),
                [valid_question()],
                source_index_patch={"bank_id": "other-bank"},
            )
            result = validate(package)
            self.assertIn("E040", [blocker["code"] for blocker in result["blockers"]])

    def test_reasons_bank_id_mismatch_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            quarantined = {
                "question_id": "quarantined-ok-001",
                "question_type": "single_choice",
                "status": "quarantined",
                "stem_md": "隔离区题目",
                "options": valid_question()["options"],
                "correct_answers": ["A"],
                "knowledge_ids": [],
                "source_refs": [{"source_id": "youtiku-basic", "block_id": "b-0012"}],
                "source_analysis_md": "保留原文待复核",
                "transformations": [],
            }
            package = build_package(
                Path(tmp),
                [valid_question()],
                quarantine_questions=[quarantined],
                quarantine_reasons={
                    "bank_id": "other-bank",
                    "reasons": [
                        {"question_id": "quarantined-ok-001", "reason": "OCR 不确定，保留原文"}
                    ],
                },
            )
            result = validate(package)
            self.assertIn("E041", [blocker["code"] for blocker in result["blockers"]])

    def test_question_bank_id_mismatch_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(
                Path(tmp),
                [valid_question(bank_id="other-bank")],
            )
            result = validate(package)
            self.assertIn("E042", [blocker["code"] for blocker in result["blockers"]])

    def test_quarantined_question_bank_id_mismatch_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            quarantined = {
                "question_id": "quarantined-bank-id-001",
                "question_type": "single_choice",
                "status": "quarantined",
                "bank_id": "other-bank",
                "stem_md": "隔离区题目",
                "options": valid_question()["options"],
                "correct_answers": ["A"],
                "knowledge_ids": [],
                "source_refs": [{"source_id": "youtiku-basic", "block_id": "b-0012"}],
                "source_analysis_md": "保留原文待复核",
                "transformations": [],
            }
            package = build_package(
                Path(tmp),
                [valid_question()],
                quarantine_questions=[quarantined],
                quarantine_reasons={
                    "bank_id": "test-bank",
                    "reasons": [
                        {"question_id": "quarantined-bank-id-001", "reason": "OCR 不确定，保留原文"}
                    ],
                },
            )
            result = validate(package)
            self.assertIn("E043", [blocker["code"] for blocker in result["blockers"]])

    def test_invalid_map_version_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(
                Path(tmp),
                [valid_question()],
                knowledge_map_patch={"map_version": 2},
            )
            result = validate(package)
            self.assertIn("E054", [blocker["code"] for blocker in result["blockers"]])

    def test_invalid_index_version_is_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(
                Path(tmp),
                [valid_question()],
                source_index_patch={"index_version": 2},
            )
            result = validate(package)
            self.assertIn("E038", [blocker["code"] for blocker in result["blockers"]])

    def test_example_minimal_valid_still_passes(self) -> None:
        examples = Path(yupractice.__file__).resolve().parent / "examples"
        result = validate(examples / "minimal-valid")
        self.assertEqual(result["quality"]["status"], "pass")
        self.assertEqual(result["quality"]["blocker_count"], 0)

    def test_example_invalid_still_fails(self) -> None:
        examples = Path(yupractice.__file__).resolve().parent / "examples"
        result = validate(examples / "invalid")
        self.assertEqual(result["quality"]["status"], "blocked")
        self.assertGreater(result["quality"]["blocker_count"], 0)


def argparse_namespace(package_dir, json_flag: bool):
    """Build a tiny argparse-like object for cmd_validate."""
    return types.SimpleNamespace(package_dir=package_dir, json=json_flag)


class YuPracticeCliTests(unittest.TestCase):
    def test_cli_exit_codes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid_package = build_package(root / "valid-tmp", [valid_question()])
            invalid_package = build_package(
                root / "invalid-tmp",
                [valid_question(status="draft")],
            )
            script = Path(yupractice.__file__).resolve()
            valid_run = subprocess.run(
                [sys.executable, str(script), "validate", str(valid_package)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(valid_run.returncode, 0)
            self.assertTrue((valid_package / "reports" / "validation.json").is_file())
            invalid_run = subprocess.run(
                [sys.executable, str(script), "validate", str(invalid_package)],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(invalid_run.returncode, 0)
            self.assertTrue((invalid_package / "reports" / "validation.json").is_file())

    def test_json_output_is_valid_utf8_and_reloadable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(Path(tmp), [valid_question()])
            script = Path(yupractice.__file__).resolve()
            run = subprocess.run(
                [sys.executable, str(script), "validate", str(package), "--json"],
                capture_output=True,
            )
            self.assertEqual(run.returncode, 0)
            # Raw bytes must be valid UTF-8 JSON on every platform/code page.
            payload = json.loads(run.stdout.decode("utf-8"))
            self.assertEqual(payload["quality"]["status"], "pass")
            self.assertEqual(payload["bank"]["id"], "test-bank")

    def test_windows_utf8_configuration_is_safe_and_idempotent(self) -> None:
        # Must be callable repeatedly without raising, in any environment.
        yupractice.configure_windows_utf8()
        yupractice.configure_windows_utf8()
        yupractice.configure_windows_utf8()
        self.assertIsNotNone(getattr(yupractice.sys, "stdout", None))

    def test_windows_utf8_configuration_only_reconfigures_interactive_console(self) -> None:
        if yupractice.sys.platform != "win32":
            self.skipTest("Windows-only console reconfiguration behavior")
        import io

        orig_stdout = yupractice.sys.stdout

        class FakeInteractiveStream:
            """Imitates a Windows console: legacy encoding + isatty True."""

            def __init__(self) -> None:
                self.encoding = "gbk"
                self.buffer = io.BytesIO()
                self.reconfigure_called = 0
                self.reconfigure_kwargs: list[dict] = []

            def isatty(self) -> bool:
                return True

            def reconfigure(self, *, encoding: str | None = None, **kwargs):
                self.reconfigure_called += 1
                self.reconfigure_kwargs.append(kwargs)
                if encoding:
                    self.encoding = encoding

            def write(self, text: str) -> int:
                return self.buffer.write(text.encode(self.encoding, errors="replace"))

            def flush(self) -> None:
                pass

        try:
            fake = FakeInteractiveStream()
            yupractice.sys.stdout = fake
            yupractice.configure_windows_utf8()
            self.assertEqual(fake.encoding, "utf-8")
            yupractice.configure_windows_utf8()  # second call must be a no-op
            self.assertEqual(fake.reconfigure_called, 1)
            fake.write("质量: pass  blocker=0")
            self.assertTrue(fake.buffer.getvalue().decode("utf-8").startswith("质量"))
        finally:
            yupractice.sys.stdout = orig_stdout

    def test_old_style_source_index_returns_blocker_not_keyerror(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = build_package(
                Path(tmp),
                [valid_question()],
                source_index_patch={"sources": [{"id": "Q"}]},
            )
            script = Path(yupractice.__file__).resolve()
            run = subprocess.run(
                [sys.executable, str(script), "validate", str(package)],
                capture_output=True,
            )
            self.assertEqual(run.returncode, 2)
            self.assertNotIn(b"KeyError", run.stderr)
            report = json.loads((package / "reports" / "validation.json").read_text(encoding="utf-8"))
            codes = [blocker["code"] for blocker in report["blockers"]]
            self.assertIn("E045", codes)


if __name__ == "__main__":
    unittest.main()
