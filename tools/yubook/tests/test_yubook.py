from __future__ import annotations

import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import yubook  # noqa: E402


class YuBookTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
