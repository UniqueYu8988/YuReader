"""Build a local, source-preserving oral-medicine focus dataset from DOCX files."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path


SCHEMA_VERSION = 1
SUBJECT_SOURCES = [
    {
        "id": "oral-surgery",
        "short_title": "口外",
        "title": "口腔颌面外科学",
        "book_id": "oral-maxillofacial-surgery-8e",
        "files": {"definition": ["口外名解.docx"], "essay": ["口外论述1.docx", "口外论述2.docx"]},
    },
    {
        "id": "oral-pathology",
        "short_title": "口组",
        "title": "口腔组织病理学",
        "book_id": "oral-pathology-8e",
        "files": {"definition": ["口组名解.docx"], "essay": ["口组论述.docx"]},
    },
    {
        "id": "dental-pulp",
        "short_title": "牙体",
        "title": "牙体牙髓病学",
        "book_id": "dental-pulp-5e",
        "files": {"definition": ["牙体名解.docx"], "essay": ["牙体论述.docx"]},
    },
    {
        "id": "periodontology",
        "short_title": "牙周",
        "title": "牙周病学",
        "book_id": "periodontology-5e",
        "files": {"definition": ["牙周名解.docx"], "essay": ["牙周论述.docx"]},
    },
    {
        "id": "prosthodontics",
        "short_title": "修复",
        "title": "口腔修复学",
        "book_id": "prosthodontics-8e",
        "files": {"definition": ["修复名解.docx"], "essay": ["修复论述1.docx", "修复论述2.docx"]},
    },
]
TYPE_LABELS = {"definition": "名词解释", "essay": "简答论述"}
CHINESE_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
CHAPTER_RE = re.compile(r"^\s*([一二三四五六七八九十百〇零]+)\s*[、.．]\s*(.+?)\s*$")
QUESTION_RE = re.compile(r"^\s*(\d{1,3})\s*[.．、]\s*(.+?)\s*$")
PROMOTION_RE = re.compile(
    r"(?:微信搜索(?:公众号[：:]?)?\s*银河研旅(?:公众号)?(?:，|,)?\s*)?"
    r"(?:记乎\s*app\s*搜索(?:班级[：:]?)?\s*途中口腔医学考研(?:2班)?)",
    re.IGNORECASE,
)
PURCHASER_RE = re.compile(r"\s*购买者[^\n，。；]{0,40}(?:大学|学院)?\s*$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_id(*parts: object) -> str:
    raw = "\u241f".join(str(part or "").strip() for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def chinese_number(value: str) -> int:
    """Parse the chapter numerals used by these documents (1-99)."""
    value = str(value or "").strip()
    if not value:
        return 0
    if "十" in value:
        left, right = value.split("十", 1)
        tens = CHINESE_DIGITS.get(left, 1) if left else 1
        ones = CHINESE_DIGITS.get(right, 0) if right else 0
        return tens * 10 + ones
    return CHINESE_DIGITS.get(value, 0)


def clean_source_text(value: object) -> tuple[str, bool]:
    text = str(value or "").replace("\u00a0", " ").replace("\r\n", "\n").strip()
    cleaned = PROMOTION_RE.sub("", text)
    cleaned = PURCHASER_RE.sub("", cleaned)
    cleaned = re.sub(r"\s+([，。；：])", r"\1", cleaned).strip(" \t，,")
    return cleaned, cleaned != text


def clean_chapter_title(raw: str) -> str:
    title = str(raw or "").split("\t", 1)[0].strip()
    title = re.sub(r"\s*(?:组病)?(?:名词解释|名解|简答论述|论述)\s*$", "", title).strip()
    return title or "未分章"


def clean_question_title(raw: str) -> tuple[str, int]:
    stars = min(3, str(raw or "").count("★") + str(raw or "").count("＊"))
    title = re.sub(r"[★＊*]+", "", str(raw or ""))
    title, _ = clean_source_text(title)
    return re.sub(r"\s+", " ", title).strip(" ：:"), stars


def split_embedded_definition(title: str) -> tuple[str, str]:
    """Separate definitions that OCR kept on the same line as the term."""
    value = str(title or "").strip()
    if "。" in value:
        lead, remainder = value.split("。", 1)
        if remainder.strip():
            return lead.strip(), remainder.strip()
    if "：" in value:
        lead, remainder = value.split("：", 1)
        if len(remainder) >= 18 or re.search(r"(?:指|是|也称|利用|若|由|有|称为)", remainder):
            return lead.strip(), remainder.strip()
    return value, ""


def normalize_definition_title(title: str) -> tuple[str, str]:
    """Prefer the Chinese term in bilingual OCR headings and retain the English alias."""
    value = str(title or "").strip()
    match = re.match(r"^([A-Za-z][^：:]*?)\s*[：:]\s*(.*[\u3400-\u9fff].*)$", value)
    if not match:
        return value, ""
    english_alias = re.sub(r"\s+", " ", match.group(1)).strip()
    chinese_title = re.sub(r"\s+", " ", match.group(2)).strip(" ：:")
    return chinese_title or value, english_alias


def table_markdown(table: object) -> str:
    rows: list[list[str]] = []
    for row in getattr(table, "rows", []):
        values = []
        for cell in row.cells:
            value, _ = clean_source_text(cell.text)
            values.append(value.replace("|", "\\|").replace("\n", "<br>"))
        if any(values):
            rows.append(values)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    return "\n".join(
        ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
        + ["| " + " | ".join(row) + " |" for row in rows[1:]]
    )


def iter_doc_blocks(document: object):
    """Yield paragraphs and tables in document order without rewriting OOXML."""
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P

    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield "paragraph", Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield "table", Table(child, document)


def build_dataset(source_dir: Path | str) -> dict:
    """Read the known OCR DOCX set and return one deterministic learning dataset."""
    from docx import Document

    root = Path(source_dir).resolve()
    if not root.is_dir():
        raise ValueError("source directory not found")
    subjects: list[dict] = []
    source_files: list[dict] = []
    warnings: list[dict] = []
    excluded_promotions = 0
    image_markers = 0
    normalized_definition_titles = 0

    for subject_config in SUBJECT_SOURCES:
        chapter_map: dict[int, dict] = {}
        chapter_order: list[int] = []
        subject_item_count = 0
        for item_type in ("definition", "essay"):
            current_chapter: dict | None = None
            current_item: dict | None = None
            expected_question = 1
            duplicate_titles: dict[tuple[int, str], int] = {}

            def finish_item() -> None:
                nonlocal current_item, subject_item_count
                if not current_item:
                    return
                answer = "\n\n".join(block for block in current_item.pop("_blocks", []) if block.strip()).strip()
                current_item["answer_markdown"] = answer or "暂无可识别的参考答案。"
                current_item["character_count"] = len(answer)
                current_item["has_table"] = bool(current_item.pop("_has_table", False))
                current_item["has_unreviewed_image"] = bool(current_item.pop("_has_image", False))
                current_item["source_files"] = list(dict.fromkeys(current_item.get("source_files") or []))
                current_item["order"] = len(current_chapter["items"]) + 1
                current_chapter["items"].append(current_item)
                subject_item_count += 1
                if current_item["character_count"] > 5000:
                    warnings.append({"kind": "oversized_item", "item_id": current_item["id"], "characters": current_item["character_count"]})
                current_item = None

            for filename in subject_config["files"][item_type]:
                source = (root / filename).resolve()
                if source.parent != root or not source.is_file():
                    raise ValueError(f"required source missing: {filename}")
                document = Document(source)
                file_sha = _sha256(source)
                source_files.append(
                    {
                        "name": filename,
                        "sha256": file_sha,
                        "bytes": source.stat().st_size,
                        "paragraphs": len(document.paragraphs),
                        "tables": len(document.tables),
                        "inline_shapes": len(document.inline_shapes),
                    }
                )
                paragraph_number = 0
                for block_kind, block in iter_doc_blocks(document):
                    if block_kind == "paragraph":
                        paragraph_number += 1
                        text, removed = clean_source_text(block.text)
                        excluded_promotions += int(removed)
                        chapter_match = CHAPTER_RE.match(text)
                        if chapter_match:
                            finish_item()
                            number = chinese_number(chapter_match.group(1)) or (len(chapter_order) + 1)
                            if number not in chapter_map:
                                chapter_order.append(number)
                                chapter_map[number] = {
                                    "id": f"{subject_config['id']}-ch{number:02d}",
                                    "order": number,
                                    "title": clean_chapter_title(text),
                                    "items": [],
                                }
                            current_chapter = chapter_map[number]
                            expected_question = 1
                            continue
                        question_match = QUESTION_RE.match(text)
                        question_number = int(question_match.group(1)) if question_match else 0
                        question_tail = question_match.group(2).strip() if question_match else ""
                        if question_match and question_number == expected_question and not re.match(r"^\d", question_tail):
                            finish_item()
                            if current_chapter is None:
                                number = 0
                                if number not in chapter_map:
                                    chapter_order.insert(0, number)
                                    chapter_map[number] = {"id": f"{subject_config['id']}-ch00", "order": 0, "title": "未分章", "items": []}
                                current_chapter = chapter_map[number]
                            title, stars = clean_question_title(question_match.group(2))
                            embedded_answer = ""
                            source_title = title
                            english_alias = ""
                            if item_type == "definition":
                                title, embedded_answer = split_embedded_definition(title)
                                source_title = title
                                title, english_alias = normalize_definition_title(title)
                                normalized_definition_titles += int(bool(english_alias))
                            duplicate_key = (int(current_chapter["order"]), source_title)
                            duplicate_titles[duplicate_key] = duplicate_titles.get(duplicate_key, 0) + 1
                            item_id = "oral-focus-" + _stable_id(subject_config["id"], item_type, current_chapter["id"], source_title, duplicate_titles[duplicate_key])
                            current_item = {
                                "id": item_id,
                                "type": item_type,
                                "type_label": TYPE_LABELS[item_type],
                                "title": title or f"第 {question_match.group(1)} 题",
                                "source_number": question_number,
                                "star_level": stars,
                                "source_files": [filename],
                                "source_paragraph": paragraph_number,
                                "source_sha256": file_sha,
                                "_blocks": [embedded_answer] if embedded_answer else [],
                                "_has_table": False,
                                "_has_image": False,
                            }
                            if english_alias:
                                current_item["aliases"] = [english_alias]
                                current_item["source_title"] = source_title
                            expected_question += 1
                            continue
                        if current_item and text:
                            current_item["_blocks"].append(text)
                            current_item["source_files"].append(filename)
                        if current_item and block._p.xpath(".//a:blip"):
                            current_item["_blocks"].append("> 原始文档此处包含图片，尚待人工确认后发布。")
                            current_item["_has_image"] = True
                            image_markers += 1
                    elif current_item:
                        markdown = table_markdown(block)
                        if markdown:
                            current_item["_blocks"].append(markdown)
                            current_item["_has_table"] = True
            finish_item()

        chapters = [chapter_map[number] for number in sorted(chapter_order) if chapter_map[number]["items"]]
        for chapter in chapters:
            chapter["definition_count"] = sum(item["type"] == "definition" for item in chapter["items"])
            chapter["essay_count"] = sum(item["type"] == "essay" for item in chapter["items"])
            chapter["starred_count"] = sum(item["star_level"] > 0 for item in chapter["items"])
        subjects.append(
            {
                **{key: subject_config[key] for key in ("id", "short_title", "title", "book_id")},
                "item_count": subject_item_count,
                "chapter_count": len(chapters),
                "chapters": chapters,
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": {"external_path": str(root), "files": source_files},
        "summary": {
            "subject_count": len(subjects),
            "chapter_count": sum(subject["chapter_count"] for subject in subjects),
            "item_count": sum(subject["item_count"] for subject in subjects),
            "definition_count": sum(item["type"] == "definition" for subject in subjects for chapter in subject["chapters"] for item in chapter["items"]),
            "essay_count": sum(item["type"] == "essay" for subject in subjects for chapter in subject["chapters"] for item in chapter["items"]),
            "table_item_count": sum(item["has_table"] for subject in subjects for chapter in subject["chapters"] for item in chapter["items"]),
            "unreviewed_image_item_count": sum(item["has_unreviewed_image"] for subject in subjects for chapter in subject["chapters"] for item in chapter["items"]),
            "excluded_promotion_blocks": excluded_promotions,
            "image_markers": image_markers,
            "normalized_definition_title_count": normalized_definition_titles,
        },
        "warnings": warnings,
        "subjects": subjects,
    }


def write_dataset(source_dir: Path | str, output_path: Path | str) -> dict:
    payload = build_dataset(source_dir)
    target = Path(output_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return payload
