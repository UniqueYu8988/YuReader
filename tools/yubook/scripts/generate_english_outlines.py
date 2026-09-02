"""Generate conservative, source-line auditable outlines for scanned English books.

This helper only creates outline metadata.  It never edits the MinerU Markdown
source.  The YuBook validator remains the authority for the resulting package.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def set_book_metadata(project: Path, *, subject: str, resource_type: str = "book") -> None:
    """Persist the reader-facing domain metadata alongside the outline.

    YuBook keeps source material and navigation separate from the runtime book
    metadata.  Explicitly marking these candidates as English prevents the
    application from falling back to its default Medicine shelf when a package
    is rebuilt later.
    """
    path = project / "book.json"
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    payload.update({"domain": "english", "subject": subject, "resource_type": resource_type})
    write(path, payload)


def source_lines(project: Path) -> list[str]:
    return (project / "source" / "original.md").read_text(encoding="utf-8-sig").splitlines()


def base(project: Path, book_id: str, title: str, lines: list[str], start: int, end: int) -> dict:
    return {
        "schema_version": 1,
        "book": {
            "id": book_id,
            "title": title,
            "edition": "",
            "identity_evidence": [],
        },
        "source": {
            "artifact": "source/original.md",
            "sha256": __import__("hashlib").sha256((project / "source" / "original.md").read_bytes()).hexdigest(),
            "line_count": len(lines),
        },
        "content": {"start_line": start, "end_line": end},
        "nodes": [],
        "pages": [],
        "issues": [],
    }


def title_evidence(outline: dict, field: str, line: int, quote: str) -> None:
    outline["book"]["identity_evidence"].append({"field": field, "line": line, "quote": quote})


def extract_exam(line: str) -> str:
    match = re.search(r"([（(][^）)]{0,100}[）)])\s*$", line.strip())
    return match.group(1).strip("（）() ") if match else ""


def build_88(project: Path) -> None:
    book_id = "english-method-88-sentences"
    set_book_metadata(project, subject="长难句方法", resource_type="book")
    lines = source_lines(project)
    starts: list[tuple[int, int, str]] = []
    recovered_markers: list[dict[str, object]] = []
    for line_no, line in enumerate(lines, 1):
        if line_no < 150:
            continue
        match = re.match(r"^(\d{1,2})(?:[.．、])\s*", line)
        number: int | None = int(match.group(1)) if match else None
        if number is None:
            # Two sentence markers were OCR'd as a leading full stop.  Their
            # position in the otherwise continuous 1–88 sequence is
            # unambiguous, so recover only the missing ordinal, not the
            # sentence wording (which remains source-preserving).
            expected = starts[-1][1] + 1 if starts else None
            if expected in {59, 85} and re.match(r"^\s*\.", line):
                number = expected
                recovered_markers.append(
                    {
                        "line": line_no,
                        "old": ".All" if line.lstrip().startswith(".All") else ". The",
                        "new": f"{number}. All" if line.lstrip().startswith(".All") else f"{number}. The",
                        "reason": "连续句号编号与该行来源题目互证，恢复丢失的句号编号",
                    }
                )
        if number is not None:
            # One source line has OCR'd the 79 marker as "9.".  Restore only
            # this unambiguous sequence label; the sentence body is untouched.
            if number == 9 and len(starts) >= 77:
                number = 79
            exam = extract_exam(line)
            label = f"第{number:02d}句"
            if exam:
                label += f" · {exam}"
            starts.append((line_no, number, label))
    if len(starts) != 88:
        raise SystemExit(f"88句可识别编号数量异常：{len(starts)}")
    outline = base(project, book_id, "88句终结长难句", lines, starts[0][0], len(lines))
    title_evidence(outline, "title", 7, "88句")
    if recovered_markers:
        outline["cleaning"] = {
            "text_replacements": [
                {
                    "line": item["line"],
                    "old": item["old"],
                    "new": item["new"],
                    "count": 1,
                    "reason": item["reason"],
                }
                for item in recovered_markers
            ]
        }
    chapter_id = "ch01"
    outline["nodes"].append({
        "id": chapter_id,
        "parent_id": None,
        "order": 1,
        "kind": "chapter",
        "title": "第一章 88句长难句训练",
        "source_line": starts[0][0],
    })
    for index, (line_no, number, label) in enumerate(starts, 1):
        node_id = f"ch01-s{number:03d}"
        outline["nodes"].append({
            "id": node_id,
            "parent_id": chapter_id,
            "order": index,
            "kind": "section",
            "title": label,
            "source_line": line_no,
        })
        end = starts[index][0] - 1 if index < len(starts) else len(lines)
        outline["pages"].append({
            "id": node_id,
            "node_id": node_id,
            "order": index,
            "role": "reading",
            "title": label,
            "start_line": line_no,
            "end_line": end,
        })
    # Publisher promotion after sentence 88 is source material, but not a
    # learning page. Keep it traceable as a reference page so it cannot enter
    # the reading flow while the source coverage remains complete.
    promotion_start = next(
        (line_no for line_no, line in enumerate(lines, 1) if line.strip() == "## 晓艳英语考研系列图书"),
        None,
    )
    if promotion_start is not None and outline["pages"][-1]["end_line"] >= promotion_start:
        outline["pages"][-1]["end_line"] = promotion_start - 2
        outline["nodes"].append(
            {
                "id": "publisher-material",
                "parent_id": None,
                "order": 2,
                "kind": "supporting",
                "title": "附录 资料信息（参考）",
                "source_line": promotion_start,
            }
        )
        outline["pages"].append(
            {
                "id": "publisher-material",
                "node_id": "publisher-material",
                "order": 89,
                "role": "reference",
                "title": "附录 资料信息（参考）",
                "start_line": promotion_start - 1,
                "end_line": len(lines),
            }
        )
    outline["issues"].append({
        "id": "missing-ocr-markers",
        "status": "resolved",
        "description": "原始 OCR 将第59、85句的编号识别为句号；根据连续编号和来源题目恢复标记，正文词句保持原样。",
        "recovered_markers": [59, 85],
    })
    write(project / "outline.json", outline)


def lesson_markers(lines: list[str], start: int) -> list[tuple[int, int, int]]:
    marker = re.compile(r"(?:Un(?:it|il|t))\s*(\d{1,2})\s+Lesson\s*(\d{1,2}|I)\b", re.IGNORECASE)
    result: list[tuple[int, int, int]] = []
    for line_no, line in enumerate(lines, 1):
        if line_no < start:
            continue
        for match in marker.finditer(line):
            lesson = 1 if match.group(2).upper() == "I" else int(match.group(2))
            result.append((line_no, int(match.group(1)), lesson))
    return result


def first_unique_markers(lines: list[str], start: int) -> list[tuple[int, int, int]]:
    seen: set[tuple[int, int]] = set()
    result: list[tuple[int, int, int]] = []
    for line_no, unit, lesson in lesson_markers(lines, start):
        key = (unit, lesson)
        if key not in seen:
            seen.add(key)
            result.append((line_no, unit, lesson))
    return result


def build_ebbinghaus(project: Path) -> None:
    book_id = "english-method-ebbinghaus"
    set_book_metadata(project, subject="考研英语词汇", resource_type="book")
    lines = source_lines(project)
    source_path = project / "source" / "original.md"
    with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
        source_text = handle.read()
    marker_pattern = re.compile(r"(?:Un(?:it|il|t))\s*(\d{1,2})\s+Lesson\s*(\d{1,2}|I)\b", re.IGNORECASE)
    source_line_starts: list[int] = []
    cursor = 0
    for source_line in source_text.splitlines(keepends=True):
        source_line_starts.append(cursor)
        cursor += len(source_line)
    if not source_line_starts:
        raise SystemExit("艾宾浩斯源文件为空")

    def line_for_offset(offset: int) -> int:
        import bisect

        if offset <= 0:
            return 1
        if offset >= len(source_text):
            return len(source_line_starts)
        return bisect.bisect_right(source_line_starts, offset)

    # Keep the first occurrence of each Lesson as the semantic boundary.  A
    # later occurrence of the same Lesson is usually a continued OCR table and
    # remains in that Lesson's span instead of becoming a duplicate page.
    markers: list[dict] = []
    seen: set[tuple[int, int]] = set()
    for match in marker_pattern.finditer(source_text):
        line_no = line_for_offset(match.start())
        if line_no < 132 or line_no > 332:
            continue
        lesson = 1 if match.group(2).upper() == "I" else int(match.group(2))
        key = (int(match.group(1)), lesson)
        if key in seen:
            continue
        seen.add(key)
        line_start = source_line_starts[line_no - 1]
        table_start = source_text.rfind("<table>", line_start, match.start() + 1)
        row_start = source_text.rfind("<tr>", table_start if table_start >= line_start else line_start, match.start() + 1)
        # The first row of a table belongs with its opening <table>; a later
        # row is an independent boundary and starts at its <tr> tag.
        if table_start >= line_start and row_start > table_start + len("<table>") + 1:
            start_char = row_start
        elif table_start >= line_start:
            start_char = table_start
        else:
            start_char = line_start
        markers.append({"line": line_no, "unit": int(match.group(1)), "lesson": lesson, "start_char": start_char})
    if len(markers) != 40:
        raise SystemExit(f"艾宾浩斯 Lesson 标记数量异常：{len(markers)}")

    content_end_char = source_line_starts[331] + len(source_text.splitlines(keepends=True)[331])
    groups: list[dict] = []
    for index, marker in enumerate(markers):
        end_char = markers[index + 1]["start_char"] if index + 1 < len(markers) else content_end_char
        groups.append(
            {
                "start_line": marker["line"],
                "end_line": line_for_offset(max(marker["start_char"], end_char - 1)),
                "lessons": [(marker["unit"], marker["lesson"])],
                "start_char": marker["start_char"],
                "end_char": end_char,
            }
        )
    # Add only structural table wrappers when a span starts/ends inside one
    # source table. The wrapped text itself remains an exact source slice.
    for group in groups:
        raw_span = source_text[group["start_char"] : group["end_char"]]
        prefix = "<table>" if raw_span.startswith("<tr>") else ""
        last_open = raw_span.rfind("<table>")
        last_close = raw_span.rfind("</table>")
        suffix = "</table>\n" if prefix or last_open > last_close else ""
        if suffix and last_open >= 0 and last_open < last_close:
            suffix = ""
        group["char_prefix"] = prefix
        group["char_suffix"] = suffix
    outline = base(project, book_id, "考研英语核心词·艾宾浩斯抗遗忘打卡", lines, 132, 332)
    title_evidence(outline, "title", 1, "考研英语核心词")
    title_evidence(outline, "title", 3, "艾宾浩斯抗遗忘打卡")
    unit_first_page: dict[int, str] = {}
    for unit in range(1, 11):
        chapter_id = f"ch{unit:02d}"
        first = next((item for item in groups if item["lessons"][0][0] == unit), None)
        if first is None:
            raise SystemExit(f"缺少 Unit {unit} 的来源行")
        unit_first_page[unit] = chapter_id
        lesson_span = first["lessons"][0][1]
        last_lesson = max(lesson for u, lesson in [m for g in groups if g["lessons"][0][0] == unit for m in g["lessons"]])
        outline["nodes"].append({
            "id": chapter_id,
            "parent_id": None,
            "order": unit,
            "kind": "chapter",
            "title": f"第{unit}章 Unit {unit} · Lesson {lesson_span}–{last_lesson}",
            "source_line": first["start_line"],
        })
    for index, group in enumerate(groups, 1):
        start_line = group["start_line"]
        end_line = group.get("end_line") or (groups[index]["start_line"] - 1 if index < len(groups) else 332)
        unit = group["lessons"][0][0]
        chapter_id = unit_first_page[unit]
        lesson_numbers = [lesson for _, lesson in group["lessons"]]
        units = [u for u, _ in group["lessons"]]
        if len(lesson_numbers) == 1:
            label = f"Unit {unit} · Lesson {lesson_numbers[0]}"
        elif len(set(units)) > 1:
            label = " + ".join(f"Unit {u} · Lesson {lesson}" for u, lesson in group["lessons"])
        else:
            label = f"Unit {unit} · Lessons {min(lesson_numbers)}–{max(lesson_numbers)}"
        node_id = f"{chapter_id}-s{index:02d}"
        outline["nodes"].append({
            "id": node_id,
            "parent_id": chapter_id,
            "order": len([n for n in outline["nodes"] if n.get("parent_id") == chapter_id]) + 1,
            "kind": "section",
            "title": label,
            "source_line": start_line,
        })
        page = {
            "id": node_id,
            "node_id": node_id,
            "order": index,
            "role": "reading",
            "title": label,
            "start_line": start_line,
            "end_line": end_line,
        }
        for key in ("start_char", "end_char", "char_prefix", "char_suffix"):
            if key in group:
                page[key] = group[key]
        outline["pages"].append(page)
    outline["issues"].append({
        "id": "ocr-table-line-merge",
        "status": "resolved",
        "description": "MinerU 将部分相邻 Lesson 表格写在同一物理行；对存在明确 HTML 行起点的各 Lesson 使用连续字符区间切页并补回必要的独立 table 外壳，未删除或改写单词内容。",
    })
    write(project / "outline.json", outline)


def build_wordbook(project: Path) -> None:
    book_id = "english-method-wordbook"
    set_book_metadata(project, subject="考研英语词汇", resource_type="book")
    lines = source_lines(project)
    unit_starts = [
        (1, 166, "第一单元（action~hasty）"),
        (2, 2068, "第二单元（agent~stare）"),
        (3, 4149, "第三单元（origin~principle）"),
        (4, 6278, "第四单元（incline~strap）"),
        (5, 8438, "第五单元（merit~cognitive）"),
        (6, 9912, "第六单元（extinguish~policy）"),
        (7, 11788, "第七单元（facility~instrument）"),
        (8, 13772, "第八单元（basis~recession）"),
        (9, 15613, "第九单元（bubble~subtle）"),
        (10, 17627, "第十单元（peak~otherwise）"),
    ]
    outline = base(project, book_id, "你还在背单词吗", lines, unit_starts[0][1], 19794)
    title_evidence(outline, "title", 49, "考研英语你还在背单词吗")
    section_pattern = re.compile(r"^#{1,3}\s*(\d{1,2})(?:[.．、]|[“\"（(]|[-—])")
    sections: list[tuple[int, int, str]] = []
    for line_no, line in enumerate(lines, 1):
        if line_no < unit_starts[0][1] or line_no > 19794:
            continue
        match = section_pattern.match(line.strip())
        if match:
            title = re.sub(r"^#{1,3}\s*", "", line.strip())
            sections.append((line_no, int(match.group(1)), title))
    if not sections:
        raise SystemExit("词汇书未找到编号主题标题")
    # Running unit headers are not section boundaries; only numbered topic
    # headings are retained.  The source title is used verbatim for traceability.
    chapter_ids: dict[int, str] = {}
    for unit, line_no, title in unit_starts:
        chapter_id = f"ch{unit:02d}"
        chapter_ids[unit] = chapter_id
        outline["nodes"].append({
            "id": chapter_id,
            "parent_id": None,
            "order": unit,
            "kind": "chapter",
            "title": f"第{unit}章 {title}",
            "source_line": line_no,
        })
    page_starts: list[int] = []
    section_units: list[int] = []
    for line_no, _number, _title in sections:
        section_units.append(max(unit for unit, start, _ in unit_starts if start <= line_no))
    for index, (line_no, _number, _title) in enumerate(sections):
        if index == 0 or section_units[index] != section_units[index - 1]:
            page_starts.append(next(start for unit, start, _ in unit_starts if unit == section_units[index]))
        else:
            page_starts.append(line_no)

    for index, (line_no, number, title) in enumerate(sections, 1):
        unit = max(unit for unit, start, _ in unit_starts if start <= line_no)
        chapter_id = chapter_ids[unit]
        node_id = f"{chapter_id}-s{index:03d}"
        sibling_order = len([n for n in outline["nodes"] if n.get("parent_id") == chapter_id]) + 1
        outline["nodes"].append({
            "id": node_id,
            "parent_id": chapter_id,
            "order": sibling_order,
            "kind": "section",
            "title": title,
            "source_line": line_no,
        })
        # Include each unit's opening motto/cover material in its first page.
        page_start = page_starts[index - 1]
        next_line = page_starts[index] - 1 if index < len(sections) else 19794
        outline["pages"].append({
            "id": node_id,
            "node_id": node_id,
            "order": index,
            "role": "reading",
            "title": title,
            "start_line": page_start,
            "end_line": next_line,
        })
    # The first Unit begins with a publisher motto and a cover image before
    # the first numbered word group. Keep those source lines as a reference
    # page instead of exposing the promotion as the opening reading content.
    first_reading_start = sections[0][0]
    intro_end = first_reading_start - 1
    if intro_end >= unit_starts[0][1]:
        outline["pages"][0]["start_line"] = first_reading_start
        for page in outline["pages"]:
            page["order"] += 1
        outline["nodes"].append(
            {
                "id": "publisher-intro",
                "parent_id": None,
                "order": len(unit_starts) + 1,
                "kind": "supporting",
                "title": "前置资料（参考）",
                "source_line": unit_starts[0][1],
            }
        )
        outline["pages"].insert(
            0,
            {
                "id": "publisher-intro",
                "node_id": "publisher-intro",
                "order": 1,
                "role": "reference",
                "title": "前置资料（参考）",
                "start_line": unit_starts[0][1],
                "end_line": intro_end,
            },
        )
    outline["issues"].append({
        "id": "running-unit-headers",
        "status": "resolved",
        "description": "正文中的重复单元页眉未作为新页面；按十个可验证 Unit 起点与编号主题分节。",
    })
    write(project / "outline.json", outline)


def build_58(project: Path) -> None:
    """Normalize OCR-split paragraph headings in the 58-passage reader.

    The source frequently emits ``## 第`` and ``## 段原文`` on adjacent
    lines, or loses the ordinal altogether.  Paragraph order is already
    explicit in each authoritative Passage page, so restoring only the
    heading label is deterministic and leaves every sentence untouched.
    """
    book_id = "english-58-basic-reading"
    set_book_metadata(project, subject="基础阅读", resource_type="lecture")
    outline_path = project / "outline.json"
    outline = json.loads(outline_path.read_text(encoding="utf-8-sig"))
    lines = source_lines(project)
    reading_pages = [page for page in outline.get("pages", []) if page.get("role") == "reading"]
    # The assembled file opens with a title/QR/publisher block before Passage
    # 01. Keep it traceable as a reference page instead of making it the first
    # visible reading page.
    if reading_pages:
        first_reading = min(reading_pages, key=lambda page: int(page["order"]))
        original_start = int(first_reading["start_line"])
        passage_start = next(
            (
                line_no
                for line_no in range(original_start, int(first_reading["end_line"]) + 1)
                if lines[line_no - 1].strip() == "## Passage 01"
            ),
        )
        if passage_start > original_start:
            front_end = passage_start - 1
            first_reading["start_line"] = passage_start
            for page in outline["pages"]:
                page["order"] = int(page["order"]) + 1
            outline["nodes"].append(
                {
                    "id": "front-matter",
                    "parent_id": None,
                    "order": max(int(node.get("order", 0)) for node in outline.get("nodes", [])) + 1,
                    "kind": "supporting",
                    "title": "前置资料（参考）",
                    "source_line": original_start,
                }
            )
            outline["pages"].insert(
                0,
                {
                    "id": "front-matter",
                    "node_id": "front-matter",
                    "order": 1,
                    "role": "reference",
                    "title": "前置资料（参考）",
                    "start_line": original_start,
                    "end_line": front_end,
                },
            )
    replacements: list[dict[str, object]] = []
    repaired = 0
    heading_re = re.compile(r"^##\s*(?:第\s*)?(\d+)?\s*段原文\s*$")
    for page in outline.get("pages", []):
        if page.get("role") != "reading":
            continue
        start = int(page["start_line"])
        end = int(page["end_line"])
        paragraph = 0
        line_no = start
        while line_no <= end:
            current = lines[line_no - 1].strip()
            if current == "## 第":
                next_line = line_no + 1
                while next_line <= end and not lines[next_line - 1].strip():
                    next_line += 1
                if next_line <= end and lines[next_line - 1].strip() == "## 段原文":
                    paragraph += 1
                    replacements.append(
                        {
                            "line": line_no,
                            "old": "## 第",
                            "new": f"## 第{paragraph}段原文",
                            "count": 1,
                            "reason": "OCR 将段落标题拆成两行；依据同一 Passage 内段落顺序恢复标题。",
                        }
                    )
                    replacements.append(
                        {
                            "line": next_line,
                            "old": "## 段原文",
                            "new": "",
                            "count": 1,
                            "reason": "与上一行合并为一个可导航的段落标题。",
                        }
                    )
                    repaired += 1
                    line_no = next_line + 1
                    continue
            match = heading_re.match(current)
            if match:
                paragraph += 1
                desired = f"## 第{paragraph}段原文"
                if current != desired:
                    replacements.append(
                        {
                            "line": line_no,
                            "old": current,
                            "new": desired,
                            "count": 1,
                            "reason": "OCR 丢失或分隔段落序号；依据同一 Passage 内段落顺序规范标题。",
                        }
                    )
                    repaired += 1
            line_no += 1
    cleaning = outline.get("cleaning") if isinstance(outline.get("cleaning"), dict) else {}
    cleaning["text_replacements"] = replacements
    outline["cleaning"] = cleaning
    outline.setdefault("issues", []).append(
        {
            "id": "split-paragraph-headings",
            "status": "resolved",
            "description": f"规范 58 篇阅读中 {repaired} 个 OCR 断裂或缺失序号的段落标题；正文内容未改写。",
            "replacement_count": len(replacements),
        }
    )
    write(outline_path, outline)


def build_grammar(project: Path) -> None:
    """Hide repeated running title lines in the grammar/long-sentence book."""
    book_id = "english-grammar-long-sentences"
    set_book_metadata(project, subject="语法与长难句", resource_type="book")
    outline_path = project / "outline.json"
    outline = json.loads(outline_path.read_text(encoding="utf-8-sig"))
    lines = source_lines(project)
    content = outline.get("content") if isinstance(outline.get("content"), dict) else {}
    start = int(content.get("start_line") or 1)
    end = int(content.get("end_line") or len(lines))
    old = "## 不就是语法和长难句吗"
    replacements = [
        {
            "line": line_no,
            "old": old,
            "new": "",
            "count": 1,
            "reason": "重复运行页眉，不属于当前语法正文标题。",
        }
        for line_no, value in enumerate(lines, 1)
        if start <= line_no <= end and value.strip() == old
    ]
    cleaning = outline.get("cleaning") if isinstance(outline.get("cleaning"), dict) else {}
    cleaning["text_replacements"] = replacements
    outline["cleaning"] = cleaning
    outline.setdefault("issues", []).append(
        {
            "id": "repeated-running-title",
            "status": "resolved",
            "description": f"移除 {len(replacements)} 个重复运行页眉；正文标题与例句内容未改写。",
            "replacement_count": len(replacements),
        }
    )
    write(outline_path, outline)


def repair_exact_terms(project: Path, terms: dict[str, str], *, issue_id: str, description: str) -> None:
    """Add line-auditable replacements for a tiny, unambiguous term allow-list."""
    outline_path = project / "outline.json"
    outline = json.loads(outline_path.read_text(encoding="utf-8-sig"))
    lines = source_lines(project)
    content = outline.get("content") if isinstance(outline.get("content"), dict) else {}
    start = int(content.get("start_line") or 1)
    end = int(content.get("end_line") or len(lines))
    cleaning = outline.get("cleaning") if isinstance(outline.get("cleaning"), dict) else {}
    replacements = list(cleaning.get("text_replacements") or [])
    existing = {(item.get("line"), item.get("old")) for item in replacements if isinstance(item, dict)}
    added = 0
    for line_no, value in enumerate(lines, 1):
        if not start <= line_no <= end:
            continue
        for old, new in terms.items():
            if old not in value or (line_no, old) in existing:
                continue
            replacements.append(
                {
                    "line": line_no,
                    "old": old,
                    "new": new,
                    "count": value.count(old),
                    "reason": description,
                }
            )
            existing.add((line_no, old))
            added += 1
    cleaning["text_replacements"] = replacements
    outline["cleaning"] = cleaning
    outline.setdefault("issues", []).append(
        {
            "id": issue_id,
            "status": "resolved",
            "description": description,
            "replacement_count": added,
            "terms": terms,
        }
    )
    write(outline_path, outline)


def normalize_arrow_headings(project: Path, *, issue_id: str = "ocr-arrow-heading") -> None:
    """Remove decorative OCR arrows from otherwise legible Markdown headings.

    MinerU occasionally turns a small arrow/bullet printed before labels such
    as “提要” or “导言” into ``->>``/``>>``.  The arrow is page furniture, not
    part of the heading text.  Record one exact source-line replacement per
    occurrence so the archived source remains authoritative and the derived
    page is readable.
    """
    outline_path = project / "outline.json"
    outline = json.loads(outline_path.read_text(encoding="utf-8-sig"))
    lines = source_lines(project)
    content = outline.get("content") if isinstance(outline.get("content"), dict) else {}
    start = int(content.get("start_line") or 1)
    end = int(content.get("end_line") or len(lines))
    # Match one or more OCR arrow glyphs directly after a Markdown heading.
    # Restrict the body to headings containing CJK characters and keep the
    # title itself untouched; this cannot rewrite prose or code examples.
    arrow_heading = re.compile(r"^(#{1,6}\s+)(?:[-]>|>)+(\s*)(.+?)\s*$")
    replacements: list[dict] = []
    cleaning = outline.get("cleaning") if isinstance(outline.get("cleaning"), dict) else {}
    existing = {
        (item.get("line"), item.get("old"))
        for item in (cleaning.get("text_replacements") or [])
        if isinstance(item, dict)
    }
    for line_no, value in enumerate(lines, 1):
        if not start <= line_no <= end:
            continue
        raw = value.rstrip("\r\n")
        match = arrow_heading.match(raw)
        if not match or not re.search(r"[\u3400-\u9fff]", match.group(3)):
            continue
        normalized = f"{match.group(1)}{match.group(3).strip()}"
        if normalized == raw or (line_no, raw) in existing:
            continue
        replacements.append(
            {
                "line": line_no,
                "old": raw,
                "new": normalized,
                "count": 1,
                "reason": "OCR 将标题前的装饰箭头识别为 ->>/>>；移除页眉装饰，不改动标题文字。",
            }
        )
        existing.add((line_no, raw))
    if replacements:
        cleaning["text_replacements"] = [*(cleaning.get("text_replacements") or []), *replacements]
        outline["cleaning"] = cleaning
        outline.setdefault("issues", []).append(
            {
                "id": issue_id,
                "status": "resolved",
                "description": "移除标题前重复出现的 OCR 装饰箭头，保留标题文本与来源映射。",
                "replacement_count": len(replacements),
            }
        )
    write(outline_path, outline)


def remove_garbled_exam_footers(project: Path, *, issue_id: str = "garbled-exam-footer") -> None:
    """Hide repeated OCR page-footer garbage in English subjective material.

    A few older OCR exports contain a short non-CJK footer with ``U+FFFD`` and
    a page marker such as ``.1.``–``.14.`` (or the OCR form ``� 14``) between
    the passage and the next analysis heading.  It is deterministic page
    furniture, not exam content; remove the complete source line while
    preserving its line number and provenance.  The first 20 source lines are
    always kept because they are front-matter evidence rather than page
    furniture.  Lines without both signals are never touched.
    """
    outline_path = project / "outline.json"
    outline = json.loads(outline_path.read_text(encoding="utf-8-sig"))
    lines = source_lines(project)
    content = outline.get("content") if isinstance(outline.get("content"), dict) else {}
    start = int(content.get("start_line") or 1)
    end = int(content.get("end_line") or len(lines))
    cleaning = outline.get("cleaning") if isinstance(outline.get("cleaning"), dict) else {}
    replacements = list(cleaning.get("text_replacements") or [])
    existing = {
        (item.get("line"), item.get("old"))
        for item in replacements
        if isinstance(item, dict)
    }
    # OCR exports use several page-number forms: ``.1.``–``.14.`` and
    # occasionally ``1:vf``/``14:Vf``, ``� 14`` or the stable ``A-14`` tail
    # marker. Restrict the number to 1–14 so ordinary prose containing a
    # decimal is never treated as page furniture.
    footer_marker = re.compile(
        r"(?:\.\s*(?:[1-9]|1[0-4])\s*\.|(?:[1-9]|1[0-4])\s*[:：]v[fF]|"
        r"(?:\ufffd\s*(?:[1-9]|1[0-4])\b|(?:[1-9]|1[0-4])\s+\ufffd)|A-14)"
    )
    added = 0
    for line_no, value in enumerate(lines, 1):
        if not start <= line_no <= end or line_no <= 20:
            continue
        raw = value.rstrip("\r\n")
        if "\ufffd" not in raw or len(raw) > 140 or not footer_marker.search(raw):
            continue
        # Footer OCR is non-CJK noise; do not match a real Chinese sentence
        # that happens to contain a replacement character.
        if re.search(r"[\u3400-\u9fff]", raw):
            continue
        if (line_no, raw) in existing:
            continue
        replacements.append(
            {
                "line": line_no,
                "old": raw,
                "new": "",
                "count": 1,
                "reason": "重复英语试卷页脚被 OCR 识别为含 U+FFFD 的乱码；移除整行页脚，不改动题干或解析。",
            }
        )
        existing.add((line_no, raw))
        added += 1
    if added:
        cleaning["text_replacements"] = replacements
        outline["cleaning"] = cleaning
        outline.setdefault("issues", []).append(
            {
                "id": issue_id,
                "status": "resolved",
                "description": "移除有明确页脚标记的 OCR 乱码行，保留原始来源与行映射。",
                "replacement_count": added,
            }
        )
    write(outline_path, outline)


def move_qr_placeholder_pages(project: Path, *, issue_id: str = "qr-placeholder-pages") -> None:
    """Keep tiny QR-only scan placeholders traceable but out of reading flow."""
    outline_path = project / "outline.json"
    outline = json.loads(outline_path.read_text(encoding="utf-8-sig"))
    lines = source_lines(project)
    moved: list[str] = []
    for page in outline.get("pages", []):
        if page.get("role") != "reading":
            continue
        start = int(page.get("start_line", 1))
        end = int(page.get("end_line", start))
        text = "".join(lines[start - 1 : end])
        compact = re.sub(r"\s+", "", text)
        if len(compact) <= 100 and re.search(r"(?:二维码|ER\d+-\d+)", text, re.IGNORECASE):
            page["role"] = "reference"
            moved.append(str(page.get("id")))
    if moved:
        outline.setdefault("issues", []).append(
            {
                "id": issue_id,
                "status": "resolved",
                "description": "将仅含二维码提示的扫描占位页保留为参考页，避免打断正文阅读；未删除来源内容。",
                "page_ids": moved,
            }
        )
    write(outline_path, outline)


def normalize_navigation_spacing(project: Path, *, issue_id: str = "navigation-title-spacing") -> None:
    """Restore a single space after Chinese chapter/section prefixes."""
    outline_path = project / "outline.json"
    outline = json.loads(outline_path.read_text(encoding="utf-8-sig"))
    lines = source_lines(project)
    prefix = re.compile(r"^(第[〇零一二三四五六七八九十百两0-9]+[章节篇])(?=\S)")
    heading_prefix = re.compile(r"^(#{1,6}\s*)(第[〇零一二三四五六七八九十百两0-9]+[章节篇])(?=\S)")
    changed_titles = 0
    for item in [*outline.get("nodes", []), *outline.get("pages", [])]:
        title = item.get("title")
        if isinstance(title, str):
            normalized = prefix.sub(r"\1 ", title.strip())
            if normalized != title:
                item["title"] = normalized
                changed_titles += 1
    cleaning = outline.get("cleaning") if isinstance(outline.get("cleaning"), dict) else {}
    replacements = list(cleaning.get("text_replacements") or [])
    existing = {(item.get("line"), item.get("old")) for item in replacements if isinstance(item, dict)}
    source_changes = 0
    content = outline.get("content") if isinstance(outline.get("content"), dict) else {}
    start = int(content.get("start_line") or 1)
    end = int(content.get("end_line") or len(lines))
    for line_no, value in enumerate(lines, 1):
        if not start <= line_no <= end:
            continue
        raw = value.rstrip("\r\n")
        normalized = heading_prefix.sub(r"\1\2 ", raw)
        if normalized != raw and (line_no, raw) not in existing:
            replacements.append(
                {
                    "line": line_no,
                    "old": raw,
                    "new": normalized,
                    "count": 1,
                    "reason": "OCR 省略章节/小节编号后的空格；恢复版式空格，不改动标题文字。",
                }
            )
            existing.add((line_no, raw))
            source_changes += 1
    cleaning["text_replacements"] = replacements
    outline["cleaning"] = cleaning
    outline.setdefault("issues", []).append(
        {
            "id": issue_id,
            "status": "resolved",
            "description": "恢复章节与小节编号后的版式空格，保持原始标题与来源证据不变。",
            "navigation_title_count": changed_titles,
            "source_line_count": source_changes,
        }
    )
    write(outline_path, outline)


def deduplicate_replacements(project: Path) -> None:
    """Remove duplicate (source line, old text) declarations before validation."""
    outline_path = project / "outline.json"
    outline = json.loads(outline_path.read_text(encoding="utf-8-sig"))
    cleaning = outline.get("cleaning") if isinstance(outline.get("cleaning"), dict) else {}
    replacements = list(cleaning.get("text_replacements") or [])
    unique: list[dict] = []
    seen: set[tuple[object, object]] = set()
    removed = 0
    for item in replacements:
        if not isinstance(item, dict):
            unique.append(item)
            continue
        key = (item.get("line"), item.get("old"))
        if key in seen:
            removed += 1
            continue
        seen.add(key)
        unique.append(item)
    cleaning["text_replacements"] = unique
    outline["cleaning"] = cleaning
    if removed:
        outline.setdefault("issues", []).append(
            {
                "id": "deduplicated-replacements",
                "status": "resolved",
                "description": f"合并 {removed} 条重复来源行替换声明，保留首次可追溯记录。",
                "removed_count": removed,
            }
        )
    write(outline_path, outline)


def reconcile_derived_heading_spacing(project: Path) -> None:
    """Make spacing fixes compose with older line-level OCR replacements."""
    outline_path = project / "outline.json"
    outline = json.loads(outline_path.read_text(encoding="utf-8-sig"))
    lines = source_lines(project)
    cleaning = outline.get("cleaning") if isinstance(outline.get("cleaning"), dict) else {}
    replacements = list(cleaning.get("text_replacements") or [])
    heading_prefix = re.compile(r"^(#{1,6}\s*)(第[〇零一二三四五六七八九十百两0-9]+[章节篇])(?=\S)")
    content = outline.get("content") if isinstance(outline.get("content"), dict) else {}
    start = int(content.get("start_line") or 1)
    end = int(content.get("end_line") or len(lines))
    by_line: dict[int, list[int]] = {}
    for index, item in enumerate(replacements):
        if isinstance(item, dict) and isinstance(item.get("line"), int):
            by_line.setdefault(item["line"], []).append(index)
    repaired = 0
    for line_no in range(start, end + 1):
        original = lines[line_no - 1].rstrip("\r\n")
        current = original
        effective: list[tuple[int, str, str, str]] = []
        for index in by_line.get(line_no, []):
            item = replacements[index]
            old, new = item.get("old"), item.get("new")
            if not isinstance(old, str) or not isinstance(new, str):
                continue
            before = current
            current = current.replace(old, new)
            if current != before:
                effective.append((index, before, old, new))
        normalized = heading_prefix.sub(r"\1\2 ", current)
        if normalized == current or not effective:
            continue
        # The last effective replacement owns the final heading text in the
        # normal case (older OCR fixes may have changed the same line first).
        index, before, old, _new = effective[-1]
        position = before.find(old)
        if position < 0:
            continue
        prefix, suffix = before[:position], before[position + len(old) :]
        if not (normalized.startswith(prefix) and normalized.endswith(suffix)):
            continue
        replacement_new = normalized[len(prefix) : len(normalized) - len(suffix) if suffix else None]
        if not replacement_new:
            continue
        replacements[index]["new"] = replacement_new
        repaired += 1
    cleaning["text_replacements"] = replacements
    outline["cleaning"] = cleaning
    if repaired:
        outline.setdefault("issues", []).append(
            {
                "id": "composed-heading-spacing",
                "status": "resolved",
                "description": "使章节/小节空格修复与同一来源行既有 OCR 修复正确组合，避免后续替换再次粘连标题。",
                "line_count": repaired,
            }
        )
    write(outline_path, outline)


def main() -> None:
    projects = {
        "english-method-88-sentences": build_88,
        "english-method-ebbinghaus": build_ebbinghaus,
        "english-method-wordbook": build_wordbook,
        "english-58-basic-reading": build_58,
        "english-method-grammar": build_grammar,
    }
    for name, builder in projects.items():
        project = ROOT / "workspace" / name / "project" / name
        builder(project)
        print(name, "outline written")


if __name__ == "__main__":
    main()
