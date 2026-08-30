#!/usr/bin/env python3
"""Split the immutable 2027 politics core OCR into four YuBook lecture packages.

The source is one MinerU Markdown file containing five political subjects.  This
small, explicit splitter keeps the source byte-for-byte unchanged and only
materializes subject-specific outlines, section pages, provenance and image
assets.  It deliberately does not rewrite prose: the source line ranges remain
the audit boundary and YuReader receives the original OCR text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "tools" / "yubook" / "workspace" / "politics-core-marxism" / "source" / "original.md"
IMAGE_SOURCE = Path(r"C:\Users\Yu\Documents\YuBook-Staging\politics-2026\core-kao-an\27《核心考案》\ocr\images")
WORKSPACE = ROOT / "tools" / "yubook" / "workspace"
SECTION_RE = re.compile(r"^#{1,6}\s+(第[一二三四五六七八九十百]+节)(.*)$")
IMAGE_RE = re.compile(r"images/([^\s)\"'<>]+)")


SUBJECTS = [
    {
        "id": "politics-mao",
        "title": "毛泽东思想和中国特色社会主义理论体系概论",
        "namespace": "politics.mao",
        "title_evidence": (100, "毛泽东思想和中国特色社会主义理论体系概论"),
        "start": 2468,
        "end": 3540,
        "chapters": [
            (1, "毛泽东思想及其历史地位", 2468, None, None),
            (2, "新民主主义革命理论", 2572, None, None),
            (3, "社会主义改造理论", 2782, None, None),
            (4, "社会主义建设道路初步探索的重要理论成果", 2935, 107, "正文缺失章标题，依据书内目录恢复"),
            (5, "中国特色社会主义理论体系的形成发展", 3100, None, None),
            (6, "邓小平理论", 3230, 110, "正文缺失章标题，依据书内目录恢复"),
            (7, "“三个代表”重要思想", 3448, None, None),
            (8, "科学发展观", 3494, None, None),
        ],
    },
    {
        "id": "politics-xi",
        "title": "习近平新时代中国特色社会主义思想概论",
        "namespace": "politics.xi",
        "title_evidence": (114, "习近平新时代中国特色社会主义思想概论"),
        "start": 3714,
        "end": 6627,
        "chapters": [
            (1, "新时代坚持和发展中国特色社会主义", 3714, None, None),
            (2, "以中国式现代化全面推进中华民族伟大复兴", 3869, 119, "目录与正文互证，修复正文章标题中的 OCR‘夏兴’"),
            (3, "坚持党的全面领导", 4069, None, None),
            (4, "坚持以人民为中心", 4165, None, None),
            (5, "全面深化改革开放", 4271, None, None),
            (6, "推动高质量发展", 4491, None, None),
            (7, "社会主义现代化建设的教育、科技、人才战略", 4819, None, None),
            (8, "发展全过程人民民主", 5033, 126, "正文缺失章标题，依据书内目录恢复"),
            (9, "全面依法治国", 5273, None, None),
            (10, "建设社会主义文化强国", 5405, None, None),
            (11, "以保障和改善民生为重点加强社会建设", 5593, None, None),
            (12, "建设社会主义生态文明", 5761, 130, "正文缺失章标题，依据书内目录恢复"),
            (13, "维护和塑造国家安全", 5933, None, None),
            (14, "建设巩固国防和强大人民军队", 6059, None, None),
            (15, "坚持“一国两制”和推进祖国完全统一", 6155, None, None),
            (16, "中国特色大国外交和推动构建人类命运共同体", 6289, None, None),
            (17, "全面从严治党", 6470, 136, "正文标题为‘日逻辑框架’，依据目录恢复章标题"),
        ],
    },
    {
        "id": "politics-modern-history",
        "title": "中国近现代史纲要",
        "namespace": "politics.modern-history",
        "title_evidence": (138, "中国近现代史纲要"),
        "start": 6649,
        "end": 8933,
        "chapters": [
            (1, "进入近代后中华民族的磨难与抗争", 6649, None, None),
            (2, "不同社会力量对国家出路的早期探索", 6870, 142, "正文缺失章标题，依据书内目录恢复"),
            (3, "辛亥革命与君主专制制度的终结", 7104, None, None),
            (4, "中国共产党成立和中国革命新局面", 7286, None, None),
            (5, "中国革命的新道路", 7625, 146, "正文缺失章标题，依据书内目录恢复"),
            (6, "中华民族的抗日战争", 7821, 147, "正文缺失章标题，依据书内目录恢复"),
            (7, "为建立新中国而奋斗", 8143, None, None),
            (8, "中华人民共和国的成立与中国社会主义建设道路的探索", 8339, None, None),
            (9, "改革开放与中国特色社会主义的开创和发展", 8653, None, None),
            (10, "中国特色社会主义进入新时代", 8821, 152, "正文缺失章标题，依据书内目录恢复"),
        ],
    },
    {
        "id": "politics-ethics-law",
        "title": "思想道德与法治",
        "namespace": "politics.ethics-law",
        "title_evidence": (154, "思想道德与法治"),
        "start": 9013,
        "end": 10503,
        "chapters": [
            (1, "领悟人生真谛 把握人生方向", 9013, None, None),
            (2, "追求远大理想 坚定崇高信念", 9221, 160, "正文缺失章标题，依据书内目录恢复"),
            (3, "继承优良传统 弘扬中国精神", 9385, None, None),
            (4, "明确价值要求 践行价值准则", 9598, None, None),
            (5, "遵守道德规范 锤炼道德品格", 9756, None, None),
            (6, "学习法治思想 提升法治素养", 10150, None, None),
        ],
    },
]

# Two OCR chapter blocks lost their first ``第一节`` marker.  The section
# names are recovered from the chapter topics and the book's contents page;
# their source line is the chapter's logic-framework marker, so no prose is
# invented or moved.
INFERRED_SECTIONS = {
    ("politics-xi", 2): ("第一节 实现中华民族伟大复兴的中国梦", 3871),
    ("politics-ethics-law", 6): ("第一节 社会主义法律的本质特征", 10152),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def heading_title(line: str) -> str:
    return re.sub(r"^#{1,6}\s*", "", line.strip())


def normalize_nav_title(raw: str) -> str:
    """Normalize only the visible navigation prefix, never the page prose."""
    title = raw.strip()
    title = re.sub(r"^(第[一二三四五六七八九十百]+[章节])\s*[:：]?\s*", r"\1 ", title)
    return title


def raw_line(lines: list[str], line_number: int) -> str:
    return heading_title(lines[line_number - 1])


def normalized_node(raw_title: str, title: str, source_line: int, evidence_lines: list[int], reason: str | None) -> dict:
    node = {"title": title, "source_line": source_line}
    if raw_title != title:
        node["source_title"] = raw_title
        node["title_normalization"] = {
            "reason": reason or "导航标题统一编号后的半角空格；正文原文未改动。",
            "evidence_lines": evidence_lines,
        }
    return node


def subject_end(lines: list[str], subject: dict) -> int:
    end = int(subject["end"])
    homework = [i for i, line in enumerate(lines, 1) if subject["start"] <= i <= end and heading_title(line) == "课后作业"]
    if not homework or homework[-1] != end:
        raise ValueError(f"subject {subject['id']} does not end at its final 课后作业: {end}")
    return end


def make_outline(subject: dict, lines: list[str], source_hash: str) -> tuple[dict, dict, list[str], list[str]]:
    end = subject_end(lines, subject)
    chapters = subject["chapters"]
    nodes: list[dict] = []
    pages: list[dict] = []
    chapter_info: list[dict] = []
    page_order = 1

    for idx, (number, desired_title, chapter_start, evidence_line, normalization_reason) in enumerate(chapters):
        chapter_end = (chapters[idx + 1][2] - 1) if idx + 1 < len(chapters) else end
        if chapter_start < subject["start"] or chapter_end > end or chapter_start > chapter_end:
            raise ValueError(f"invalid chapter range {number}: {chapter_start}-{chapter_end}")
        raw_chapter = raw_line(lines, chapter_start)
        if evidence_line is None:
            evidence = [chapter_start]
        else:
            evidence = [evidence_line, chapter_start]
        chapter = {"id": f"ch{number:02d}", "parent_id": None, "order": number, "kind": "chapter"}
        chapter.update(normalized_node(raw_chapter, f"第{number_to_cn(number)}章 {desired_title}", chapter_start, evidence, normalization_reason))
        nodes.append(chapter)

        section_matches: list[tuple[int, str]] = []
        for line_number in range(chapter_start, chapter_end + 1):
            match = SECTION_RE.match(lines[line_number - 1].strip())
            if match:
                section_matches.append((line_number, heading_title(lines[line_number - 1])))
        if not section_matches:
            raise ValueError(f"chapter {number} has no section heading")
        inferred_section = INFERRED_SECTIONS.get((subject["id"], number))
        if inferred_section and not any(title.startswith("第一节") for _, title in section_matches):
            section_matches.insert(0, (inferred_section[1], inferred_section[0]))
        homework_lines = [line_number for line_number in range(chapter_start, chapter_end + 1) if heading_title(lines[line_number - 1]) == "课后作业"]
        homework_line = homework_lines[-1] if homework_lines else None
        if homework_line is not None:
            section_matches = [(line_number, title) for line_number, title in section_matches if line_number < homework_line]
        if not section_matches:
            raise ValueError(f"chapter {number} has no section before homework")

        section_pages: list[str] = []
        for section_index, (section_line, raw_section) in enumerate(section_matches, 1):
            next_section = section_matches[section_index][0] if section_index < len(section_matches) else (homework_line or chapter_end + 1)
            section_end = next_section - 1
            section_id = f"ch{number:02d}-s{section_index:02d}"
            inferred_this = bool(inferred_section and section_line == inferred_section[1])
            if inferred_this:
                raw_section = heading_title(lines[section_line - 1])
                section_title = inferred_section[0]
            else:
                section_title = normalize_nav_title(raw_section)
            node = {"id": section_id, "parent_id": f"ch{number:02d}", "order": section_index, "kind": "section"}
            node.update(normalized_node(raw_section, section_title, section_line, [section_line], "正文缺失该节标题，依据本章考点顺序恢复导航标题" if inferred_this else None))
            nodes.append(node)
            page_start = chapter_start if section_index == 1 else section_line
            pages.append({"id": section_id, "node_id": section_id, "order": page_order, "role": "reading", "title": section_title, "start_line": page_start, "end_line": section_end})
            page_order += 1
            section_pages.append(section_id)

        if homework_line is not None:
            homework_id = f"ch{number:02d}-hw"
            homework_title = f"第{number_to_cn(number)}章 {desired_title} 课后作业"
            nodes.append({"id": homework_id, "parent_id": f"ch{number:02d}", "order": len(section_matches) + 1, "kind": "supporting", "title": homework_title, "source_line": homework_line})
            pages.append({"id": homework_id, "node_id": homework_id, "order": page_order, "role": "reference", "title": homework_title, "start_line": homework_line, "end_line": chapter_end})
            page_order += 1

        chapter_info.append({"number": number, "id": f"ch{number:02d}", "title": chapter["title"], "start": chapter_start, "end": chapter_end, "section_ids": section_pages})

    outline = {
        "schema_version": 1,
        "book": {
            "id": subject["id"],
            "title": subject["title"],
            "edition": "2027考研版（2026年1月第1版）",
            "identity_evidence": [{"field": "title", "line": subject["title_evidence"][0], "quote": subject["title_evidence"][1]}, {"field": "edition", "line": 49, "quote": "第1 版"}],
        },
        "source": {"artifact": "source/original.md", "sha256": source_hash, "line_count": len(lines)},
        "content": {"start_line": subject["start"], "end_line": end},
        "cleaning": {"text_replacements": []},
        "nodes": nodes,
        "pages": pages,
        "issues": [],
    }

    entries: list[dict] = []
    positions: list[dict] = []
    for chapter in chapter_info:
        chapter_pages = [page for page in pages if page["node_id"] in chapter["section_ids"]]
        chapter_id = f"{subject['namespace']}.ch{chapter['number']:02d}"
        entries.append({"knowledge_id": chapter_id, "label": chapter["title"], "kind": "chapter", "path": ["政治", subject["title"], chapter["title"]], "chapter_id": chapter["id"], "section_ids": chapter["section_ids"], "page_ids": chapter["section_ids"], "source_range": [chapter["start"], chapter_pages[-1]["end_line"]]})
        for section_id in chapter["section_ids"]:
            page = next(page for page in chapter_pages if page["id"] == section_id)
            node = next(node for node in nodes if node["id"] == section_id)
            knowledge_id = f"{chapter_id}.{section_id.rsplit('-', 1)[-1]}"
            entries.append({"knowledge_id": knowledge_id, "label": node["title"], "kind": "section", "path": ["政治", subject["title"], chapter["title"], node["title"]], "chapter_id": chapter["id"], "section_id": section_id, "page_ids": [section_id], "source_range": [page["start_line"], page["end_line"]]})
            positions.append({"knowledge_id": knowledge_id, "pages": [{"page_key": section_id, "role": "reading", "title": page["title"], "md_range": [page["start_line"], page["end_line"]], "chars": len("".join(lines[page["start_line"] - 1:page["end_line"]]).strip()), "lines": page["end_line"] - page["start_line"] + 1}]})

    knowledge_map = {
        "schema_version": 1,
        "book_id": subject["id"],
        "title": subject["title"],
        "namespace": subject["namespace"],
        "content_range": [subject["start"], end],
        "input_sha256": source_hash,
        "excluded_pre_content": {"range": [1, subject["start"] - 1], "reason": "核心考案书前资料与本学科前置材料仅作为来源归档，不进入正式阅读目录"},
        "knowledge_positions": positions,
        "pages": [{"page_key": page["id"], "role": page["role"], "title": page["title"], "source_range": [page["start_line"], page["end_line"]]} for page in pages],
        "chapters": [{"knowledge_id": f"{subject['namespace']}.ch{chapter['number']:02d}", "chapter_id": chapter["id"], "title": chapter["title"], "section_ids": chapter["section_ids"]} for chapter in chapter_info],
        "entries": entries,
    }
    refs = sorted({match.group(1) for line in lines[subject["start"] - 1:end] for match in IMAGE_RE.finditer(line)})
    return outline, knowledge_map, refs, [f"content lines {subject['start']}-{end}", f"chapters {len(chapter_info)}", f"reading pages {sum(page['role'] == 'reading' for page in pages)}", f"reference pages {sum(page['role'] == 'reference' for page in pages)}"]


def number_to_cn(number: int) -> str:
    values = "零一二三四五六七八九"
    if number < 10:
        return values[number]
    if number < 20:
        return "十" if number == 10 else "十" + values[number - 10]
    if number < 100:
        return values[number // 10] + "十" + (values[number % 10] if number % 10 else "")
    raise ValueError(number)


def run_init(project_id: str, title: str, rebuild: bool = False) -> Path:
    project = WORKSPACE / project_id
    if project.exists() and any(project.iterdir()):
        if not rebuild or not (project / "source" / "IMAGE-REGISTRATION.md").is_file():
            raise RuntimeError(f"refusing to overwrite non-empty workspace: {project}")
        shutil.rmtree(project)
    cmd = [sys.executable, str(ROOT / "tools" / "yubook" / "scripts" / "yubook.py"), "init", "--source", str(SOURCE), "--book-id", project_id, "--title", title, "--edition", "2027考研版（2026年1月第1版）", "--workspace", str(WORKSPACE)]
    subprocess.run(cmd, cwd=ROOT, check=True)
    return project


def materialize(subject: dict, rebuild: bool = False) -> dict:
    lines = SOURCE.read_text(encoding="utf-8").splitlines(keepends=True)
    source_hash = sha256_file(SOURCE)
    project = run_init(subject["id"], subject["title"], rebuild=rebuild)
    outline, knowledge_map, refs, metrics = make_outline(subject, lines, source_hash)
    book = json.loads((project / "book.json").read_text(encoding="utf-8"))
    book.update({"domain": "politics", "subject": subject["title"], "resource_type": "lecture"})
    (project / "book.json").write_text(json.dumps(book, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_json(project / "outline.json", outline)
    write_json(project / "knowledge-map.json", knowledge_map)
    image_dir = project / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    missing: list[str] = []
    for name in refs:
        source_image = IMAGE_SOURCE / name
        if source_image.is_file():
            shutil.copy2(source_image, image_dir / name)
        else:
            missing.append(name)
    registration = [
        "# Image registration",
        "",
        "Images are copied from the immutable MinerU staging artifact for the same source Markdown.",
        f"- source_markdown_sha256: `{source_hash}`",
        f"- image_source: `{IMAGE_SOURCE}`",
        f"- referenced_assets: {len(refs)}",
        f"- copied_assets: {len(refs) - len(missing)}",
        f"- missing_assets: {len(missing)}",
    ]
    if missing:
        registration.extend(["", "Missing names:", *[f"- `{item}`" for item in missing]])
    (project / "source" / "IMAGE-REGISTRATION.md").write_text("\n".join(registration) + "\n", encoding="utf-8")
    return {"book_id": subject["id"], "project": str(project), "refs": len(refs), "missing_images": missing, "metrics": metrics}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject", choices=[item["id"] for item in SUBJECTS] + ["all"], default="all")
    parser.add_argument("--rebuild", action="store_true", help="仅允许重建本脚本先前生成且带有 IMAGE-REGISTRATION 标记的工作区")
    args = parser.parse_args()
    selected = SUBJECTS if args.subject == "all" else [item for item in SUBJECTS if item["id"] == args.subject]
    results = [materialize(subject, rebuild=args.rebuild) for subject in selected]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
