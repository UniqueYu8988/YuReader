from __future__ import annotations

import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

import yubook  # noqa: E402


class YuBookTests(unittest.TestCase):
    def test_political_series_header_is_removed_as_a_fixed_watermark(self) -> None:
        lines = ["# 第一章 例子\n", "## 考研政治核心考案\n", "正文\n"]
        derived, transformations = yubook.derive_clean_lines(
            lines,
            {"content": {"start_line": 1, "end_line": 3}},
        )
        self.assertEqual(derived[1], "\n")
        self.assertEqual(transformations[0]["kind"], "remove_fixed_watermark_line")
        self.assertEqual(transformations[0]["line"], 2)

    def make_project(self, root: Path) -> Path:
        source = root / "sample.md"
        source.write_text(
            "示例教材\n"
            "第1版\n"
            "目录\n"
            "第一章 绪论\n"
            "第一节 学科概况\n"
            "第二节 学习方法\n"
            "第二章 基础知识\n"
            "第一节 基本概念\n"
            "# 第一章 绪论\n"
            "本章导言。\n"
            "# 本资料仅用于学习交流使用，禁止用于商业用途第一章绪论\n"
            "## 第一节 学科概况\n"
            + "学科正文。" * 80
            + "\n术语：增加酷垫。\n"
            + "本资料仅用于学习交流使用，禁止用于商业用途\n"
            + "\n## 第二节 学习方法\n"
            + "方法正文。" * 80
            + "\n# 第二章 基础知识\n"
            "## 第一节 基本概念\n"
            + "基础正文。" * 80
            + "\n参考文献\n参考资料。\n",
            encoding="utf-8",
        )
        result = yubook.command_init(
            Namespace(
                source=str(source),
                book_id="sample-book",
                title="示例教材",
                edition="第1版",
                workspace=str(root / "workspace"),
            )
        )
        project = Path(result["project"])
        lines = yubook.source_lines(project / "source" / "original.md")

        def line_of(text: str) -> int:
            return next(index for index, line in enumerate(lines, start=1) if line.strip() == text)

        ch1 = line_of("# 第一章 绪论")
        s1 = line_of("## 第一节 学科概况")
        s2 = line_of("## 第二节 学习方法")
        ch2 = line_of("# 第二章 基础知识")
        ch2s1 = line_of("## 第一节 基本概念")
        reference = line_of("参考文献")
        outline = yubook.load_json(project / "outline.json")
        outline["book"]["identity_evidence"] = [
            {"field": "title", "line": 1, "quote": "示例教材"},
            {"field": "edition", "line": 2, "quote": "第1版"},
        ]
        outline["cleaning"] = {
            "text_replacements": [
                {
                    "line": line_of("术语：增加酷垫。"),
                    "old": "增加酷垫",
                    "new": "增加𬌗垫",
                    "count": 1,
                    "reason": "测试完整专业词组替换",
                }
            ]
        }
        outline["content"] = {"start_line": ch1, "end_line": len(lines)}
        outline["nodes"] = [
            {"id": "ch01", "parent_id": None, "order": 1, "kind": "chapter", "title": "第一章 绪论", "source_line": ch1},
            {"id": "ch01-s01", "parent_id": "ch01", "order": 1, "kind": "section", "title": "第一节 学科概况", "source_line": s1},
            {"id": "ch01-s02", "parent_id": "ch01", "order": 2, "kind": "section", "title": "第二节 学习方法", "source_line": s2},
            {"id": "ch02", "parent_id": None, "order": 2, "kind": "chapter", "title": "第二章 基础知识", "source_line": ch2},
            {"id": "ch02-s01", "parent_id": "ch02", "order": 1, "kind": "section", "title": "第一节 基本概念", "source_line": ch2s1},
            {"id": "refs", "parent_id": None, "order": 3, "kind": "supporting", "title": "参考文献", "source_line": reference},
        ]
        outline["pages"] = [
            {"id": "ch01-s01", "node_id": "ch01-s01", "order": 1, "role": "reading", "title": "第一节 学科概况", "start_line": ch1, "end_line": s2 - 1},
            {"id": "ch01-s02", "node_id": "ch01-s02", "order": 2, "role": "reading", "title": "第二节 学习方法", "start_line": s2, "end_line": ch2 - 1},
            {"id": "ch02-s01", "node_id": "ch02-s01", "order": 3, "role": "reading", "title": "第一节 基本概念", "start_line": ch2, "end_line": reference - 1},
            {"id": "refs", "node_id": "refs", "order": 4, "role": "reference", "title": "参考文献", "start_line": reference, "end_line": len(lines)},
        ]
        yubook.write_json(project / "outline.json", outline)
        return project

    def test_valid_outline_builds_traceable_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = self.make_project(Path(temp))
            report, _outline, _lines = yubook.validate_project(project)
            self.assertFalse(report["blockers"])
            result = yubook.command_build(Namespace(project=str(project)))
            package = Path(result["package"])
            audit = yubook.validate_package(package)
            self.assertEqual("pass", audit["status"])
            manifest = audit["manifest"]
            self.assertEqual(2, len(manifest["toc"]))
            self.assertEqual(3, len(manifest["sections"]))
            self.assertEqual(1, len(manifest["references"]))
            self.assertEqual([1, 2, 3], [item["order"] for item in manifest["sections"]])
            self.assertEqual(3, manifest["provenance"]["cleaned_candidate"]["transformation_count"])
            self.assertEqual(
                yubook.DERIVED_TEXT_HASH_ALGORITHM,
                manifest["provenance"]["cleaned_candidate"]["hash_algorithm"],
            )
            self.assertEqual(
                manifest["provenance"]["original"]["sha256"],
                manifest["provenance"]["cleaned_candidate"]["source_sha256"],
            )
            self.assertNotEqual(
                manifest["provenance"]["original"]["sha256"],
                manifest["provenance"]["cleaned_candidate"]["sha256"],
            )
            self.assertEqual(
                4,
                manifest["provenance"]["cleaned_candidate"]["artifact_count"],
            )
            self.assertTrue((package / "reports" / "transformations.json").is_file())
            self.assertNotIn("本资料仅用于", "".join((package / item["artifact"]).read_text(encoding="utf-8") for item in manifest["sections"]))
            self.assertIn("增加𬌗垫", "".join((package / item["artifact"]).read_text(encoding="utf-8") for item in manifest["sections"]))
            source_bytes = "".join(
                yubook.source_lines(project / "source" / "original.md")[
                    yubook.load_json(project / "outline.json")["content"]["start_line"] - 1 :
                ]
            ).encode("utf-8")
            materialized = b"".join(
                (package / item["artifact"]).read_bytes()
                for item in sorted(manifest["sections"] + manifest["references"], key=lambda item: item["source_map"]["original_line_start"])
            )
            self.assertNotEqual(source_bytes, materialized)
            content_root = Path(temp) / "content"
            imported = yubook.command_import(Namespace(package=str(package), content_root=str(content_root)))
            target = Path(imported["target"])
            self.assertTrue((target / "manifest.json").is_file())
            self.assertFalse((target / "original").exists())

    def test_fragment_title_and_number_gap_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = self.make_project(Path(temp))
            outline = yubook.load_json(project / "outline.json")
            outline["nodes"][1]["title"] = "第二节 学科概况"
            outline["pages"][0]["title"] = "防治方法如下："
            yubook.write_json(project / "outline.json", outline)
            report, _outline, _lines = yubook.validate_project(project)
            codes = {item["code"] for item in report["blockers"]}
            self.assertIn("section_number_gap", codes)
            self.assertIn("navigation_fragment", codes)

    def test_navigation_number_requires_separator_space(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = self.make_project(Path(temp))
            outline = yubook.load_json(project / "outline.json")
            outline["nodes"][1]["title"] = "第一节学科概况"
            outline["pages"][0]["title"] = "第一节学科概况"
            yubook.write_json(project / "outline.json", outline)
            report, _outline, _lines = yubook.validate_project(project)
            self.assertIn("navigation_title_spacing", {item["code"] for item in report["blockers"]})

    def test_topic_page_gets_runtime_breadcrumb_without_changing_canonical_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = self.make_project(Path(temp))
            outline = yubook.load_json(project / "outline.json")
            section = outline["nodes"][1]
            outline["nodes"].append(
                {
                    "id": "ch01-s01-t01",
                    "parent_id": section["id"],
                    "order": 1,
                    "kind": "topic",
                    "title": "一、学科范围",
                    "source_line": section["source_line"],
                }
            )
            outline["pages"][0]["node_id"] = "ch01-s01-t01"
            outline["pages"][0]["title"] = "一、学科范围"
            yubook.write_json(project / "outline.json", outline)
            result = yubook.command_build(Namespace(project=str(project)))
            manifest = yubook.load_json(Path(result["package"]) / "manifest.json")
            page = manifest["sections"][0]
            self.assertEqual("第一节 学科概况 · 一、学科范围", page["title"])
            self.assertEqual("一、学科范围", page["canonical_title"])
            self.assertEqual(["第一章 绪论", "第一节 学科概况", "一、学科范围"], page["breadcrumb"])

    def test_deterministic_occlusion_residual_blocks_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = self.make_project(Path(temp))
            outline = yubook.load_json(project / "outline.json")
            outline["cleaning"]["text_replacements"] = []
            yubook.write_json(project / "outline.json", outline)
            report, _outline, _lines = yubook.validate_project(project)
            self.assertIn("occlusion_alias_residual", {item["code"] for item in report["blockers"]})

    def test_protected_word_inside_multichar_alias_is_not_a_blocker(self) -> None:
        audit = yubook.audit_derived_occlusion(
            ["牙胚产生整体验向移动和偏中心的移动。\n", "随后沿验向萌出。\n"],
            1,
            2,
        )
        aliases = {item["found"]: item["count"] for item in audit["aliases"]}
        self.assertNotIn("体验向", aliases)
        self.assertEqual(1, aliases["验向"])

    def test_english_backed_missing_occlusion_terms_are_detected(self) -> None:
        lines = [
            "## 四、全口义齿的平衡\n",
            "正中平衡（centric balanced occlusion）与侧方平衡 lateral balanced occlusion。\n",
            "舌向集中(lingualized occlusion）和平面（monoplane occlusion）。\n",
            "并发症如关系紊乱、牙松动、牙移位。\n",
        ]
        audit = yubook.audit_derived_occlusion(lines, 1, len(lines))
        rules = {item["rule"] for item in audit["automatic_missing"]}
        self.assertTrue(
            {
                "complete_denture_balanced_occlusion",
                "centric_balanced_occlusion_english",
                "lateral_balanced_occlusion_english",
                "lingualized_occlusion_english",
                "monoplane_occlusion_english",
                "occlusion_relation_disorder_complication",
            }.issubset(rules)
        )

    def test_supporting_material_requires_explicit_reason_to_be_reading(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = self.make_project(Path(temp))
            outline = yubook.load_json(project / "outline.json")
            outline["pages"][-1]["role"] = "reading"
            yubook.write_json(project / "outline.json", outline)
            report, _outline, _lines = yubook.validate_project(project)
            self.assertIn("supporting_reading_role", {item["code"] for item in report["blockers"]})

    def test_reference_hash_is_part_of_package_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = self.make_project(Path(temp))
            result = yubook.command_build(Namespace(project=str(project)))
            package = Path(result["package"])
            manifest = yubook.load_json(package / "manifest.json")
            reference = package / manifest["references"][0]["artifact"]
            reference.write_text(reference.read_text(encoding="utf-8") + "tampered", encoding="utf-8")
            audit = yubook.validate_package(package)
            self.assertIn("section_hash", {item["code"] for item in audit["blockers"]})

    def test_derived_text_hash_is_part_of_package_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = self.make_project(Path(temp))
            result = yubook.command_build(Namespace(project=str(project)))
            package = Path(result["package"])
            manifest_path = package / "manifest.json"
            manifest = yubook.load_json(manifest_path)
            manifest["provenance"]["cleaned_candidate"]["sha256"] = "0" * 64
            yubook.write_json(manifest_path, manifest)
            audit = yubook.validate_package(package)
            self.assertIn("derived_hash", {item["code"] for item in audit["blockers"]})

    # ---- 政治讲义资源元数据（YuBook 0.4.0） ----

    def make_politics_project(self, root: Path) -> Path:
        """在样本工程上叠加 politics 讲义元数据与 knowledge-map.json。"""
        project = self.make_project(root)
        book = yubook.load_json(project / "book.json")
        book["domain"] = "politics"
        book["subject"] = "马克思主义基本原理"
        book["resource_type"] = "lecture"
        yubook.write_json(project / "book.json", book)
        knowledge_map = {
            "schema_version": 1,
            "book_id": "sample-book",
            "namespace": "politics.marxism",
            "entries": [
                {
                    "knowledge_id": "politics.marxism.ch01",
                    "label": "第一章 绪论",
                    "kind": "chapter",
                    "path": ["政治", "马克思主义基本原理", "第一章 绪论"],
                    "chapter_id": "ch01",
                    "page_ids": ["ch01-s01", "ch01-s02"],
                },
                {
                    "knowledge_id": "politics.marxism.ch01.s01",
                    "label": "第一节 学科概况",
                    "kind": "section",
                    "path": ["政治", "马克思主义基本原理", "第一章 绪论", "第一节 学科概况"],
                    "chapter_id": "ch01",
                    "section_id": "ch01-s01",
                    "page_ids": ["ch01-s01"],
                },
                {
                    "knowledge_id": "politics.marxism.ch01.s02",
                    "label": "第二节 学习方法",
                    "kind": "section",
                    "path": ["政治", "马克思主义基本原理", "第一章 绪论", "第二节 学习方法"],
                    "chapter_id": "ch01",
                    "section_id": "ch01-s02",
                    "page_ids": ["ch01-s02"],
                },
                {
                    "knowledge_id": "politics.marxism.ch02",
                    "label": "第二章 基础知识",
                    "kind": "chapter",
                    "path": ["政治", "马克思主义基本原理", "第二章 基础知识"],
                    "chapter_id": "ch02",
                    "page_ids": ["ch02-s01"],
                },
                {
                    "knowledge_id": "politics.marxism.intro",
                    "label": "导论（学科前置内容）",
                    "kind": "excluded",
                    "path": ["政治", "马克思主义基本原理", "导论（学科前置，仅归档）"],
                    "chapter_id": None,
                    "section_id": None,
                    "page_ids": [],
                    "source_range": [1, 10],
                },
            ],
        }
        yubook.write_json(project / "knowledge-map.json", knowledge_map)
        return project

    def test_politics_lecture_metadata_reaches_final_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = self.make_politics_project(Path(temp))
            result = yubook.command_build(Namespace(project=str(project)))
            package = Path(result["package"])
            audit = yubook.validate_package(package)
            self.assertEqual("pass", audit["status"])
            book = audit["manifest"]["book"]
            self.assertEqual("politics", book["domain"])
            self.assertEqual("马克思主义基本原理", book["subject"])
            self.assertEqual("lecture", book["resource_type"])

    def test_old_book_without_metadata_still_builds(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = self.make_project(Path(temp))
            report, _outline, _lines = yubook.validate_project(project)
            self.assertFalse(report["blockers"])
            result = yubook.command_build(Namespace(project=str(project)))
            audit = yubook.validate_package(Path(result["package"]))
            self.assertEqual("pass", audit["status"])
            self.assertNotIn("domain", audit["manifest"]["book"])
            self.assertNotIn("knowledge_map", audit["manifest"])

    def test_invalid_domain_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = self.make_project(Path(temp))
            book = yubook.load_json(project / "book.json")
            book["domain"] = "history"
            yubook.write_json(project / "book.json", book)
            report, _outline, _lines = yubook.validate_project(project)
            self.assertIn("book_domain_invalid", {item["code"] for item in report["blockers"]})

    def test_invalid_resource_type_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = self.make_project(Path(temp))
            book = yubook.load_json(project / "book.json")
            book["resource_type"] = "magazine"
            yubook.write_json(project / "book.json", book)
            report, _outline, _lines = yubook.validate_project(project)
            self.assertIn("book_resource_type_invalid", {item["code"] for item in report["blockers"]})

    def test_knowledge_map_copied_into_dist_with_declaration(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = self.make_politics_project(Path(temp))
            result = yubook.command_build(Namespace(project=str(project)))
            package = Path(result["package"])
            self.assertTrue((package / "knowledge-map.json").is_file())
            manifest = yubook.load_json(package / "manifest.json")
            declared = manifest["knowledge_map"]
            self.assertEqual("knowledge-map.json", declared["path"])
            self.assertEqual(5, declared["entry_count"])
            self.assertEqual(yubook.sha256_file(package / "knowledge-map.json"), declared["sha256"])

    def test_knowledge_map_hash_tampering_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = self.make_politics_project(Path(temp))
            result = yubook.command_build(Namespace(project=str(project)))
            package = Path(result["package"])
            km_path = package / "knowledge-map.json"
            km_path.write_text(km_path.read_text(encoding="utf-8") + "\ntampered", encoding="utf-8")
            audit = yubook.validate_package(package)
            self.assertIn("knowledge_map_hash", {item["code"] for item in audit["blockers"]})

    def test_knowledge_map_duplicate_id_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = self.make_politics_project(Path(temp))
            knowledge_map = yubook.load_json(project / "knowledge-map.json")
            knowledge_map["entries"].append(dict(knowledge_map["entries"][0]))
            yubook.write_json(project / "knowledge-map.json", knowledge_map)
            report, _outline, _lines = yubook.validate_project(project)
            self.assertIn("knowledge_map_duplicate", {item["code"] for item in report["blockers"]})

    def test_knowledge_map_book_id_mismatch_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = self.make_politics_project(Path(temp))
            knowledge_map = yubook.load_json(project / "knowledge-map.json")
            knowledge_map["book_id"] = "another-book"
            yubook.write_json(project / "knowledge-map.json", knowledge_map)
            report, _outline, _lines = yubook.validate_project(project)
            self.assertIn("knowledge_map_book_id", {item["code"] for item in report["blockers"]})

    def test_knowledge_map_unknown_page_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = self.make_politics_project(Path(temp))
            knowledge_map = yubook.load_json(project / "knowledge-map.json")
            knowledge_map["entries"][0]["page_ids"].append("missing-page")
            yubook.write_json(project / "knowledge-map.json", knowledge_map)
            report, _outline, _lines = yubook.validate_project(project)
            self.assertIn("knowledge_map_page_ids", {item["code"] for item in report["blockers"]})

    def test_knowledge_map_change_creates_new_immutable_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = self.make_politics_project(Path(temp))
            first = Path(yubook.command_build(Namespace(project=str(project)))["package"])
            knowledge_map = yubook.load_json(project / "knowledge-map.json")
            knowledge_map["title"] = "更新后的知识映射"
            yubook.write_json(project / "knowledge-map.json", knowledge_map)
            second = Path(yubook.command_build(Namespace(project=str(project)))["package"])
            self.assertNotEqual(first, second)
            self.assertEqual("更新后的知识映射", yubook.load_json(second / "knowledge-map.json")["title"])

    def test_book_metadata_change_creates_new_immutable_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = self.make_politics_project(Path(temp))
            first = Path(yubook.command_build(Namespace(project=str(project)))["package"])
            book = yubook.load_json(project / "book.json")
            book["subject"] = "政治理论"
            yubook.write_json(project / "book.json", book)
            second = Path(yubook.command_build(Namespace(project=str(project)))["package"])
            self.assertNotEqual(first, second)
            self.assertEqual("政治理论", yubook.load_json(second / "manifest.json")["book"]["subject"])

    def test_asset_hash_tampering_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = self.make_project(Path(temp))
            image_dir = project / "pages" / "images"
            image_dir.mkdir(parents=True)
            (image_dir / "figure.png").write_bytes(b"original-image")
            package = Path(yubook.command_build(Namespace(project=str(project)))["package"])
            (package / "images" / "figure.png").write_bytes(b"tampered")
            audit = yubook.validate_package(package)
            self.assertIn("asset_hash", {item["code"] for item in audit["blockers"]})

    def test_project_without_knowledge_map_still_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = self.make_project(Path(temp))
            report, _outline, _lines = yubook.validate_project(project)
            self.assertFalse(report["blockers"])
            result = yubook.command_build(Namespace(project=str(project)))
            audit = yubook.validate_package(Path(result["package"]))
            self.assertEqual("pass", audit["status"])

    def test_temporary_import_manifest_book_returns_politics_lecture(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = self.make_politics_project(Path(temp))
            result = yubook.command_build(Namespace(project=str(project)))
            package = Path(result["package"])
            content_root = Path(temp) / "content"
            imported = yubook.command_import(Namespace(package=str(package), content_root=str(content_root)))
            import app  # noqa: E402  （只读复用 YuReader 现有 manifest_book）
            loaded = app.manifest_book(Path(imported["target"]) / "manifest.json")
            self.assertIsNotNone(loaded, "临时导入包必须被 YuReader manifest_book 读取")
            book, _sections = loaded
            self.assertEqual("politics", book["domain"])
            self.assertEqual("lecture", book["resource_type"])
            self.assertEqual("马克思主义基本原理", book["subject"])
            self.assertEqual("政治", book["domain_label"])
            self.assertEqual(3, len(book["sections"]))
            self.assertTrue((Path(imported["target"]) / "knowledge-map.json").is_file())


if __name__ == "__main__":
    unittest.main()
