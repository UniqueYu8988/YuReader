"""Practice engine, question matching, and subjective responses."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from yureader.config import (
    CONTENT_DIR,
    DATA_DIR,
    DOMAIN_LABELS,
    QUESTION_BANK_DIR,
    SUBJECTIVE_DIR,
    PRACTICE_LOCK,
)
from yureader.utils import (
    safe_domain,
    safe_note_component,
    atomic_write,
)
from yureader.catalog import (
    catalog,
    question_bank_catalog,
    question_bank_by_id,
    resolve_section_id,
    section_aliases_for,
    package_path,
)
from yureader.obsidian import obsidian_vault

def practice_path(name: str) -> Path:
    if name not in {"attempts", "analyses"}:
        raise ValueError("invalid practice store")
    return DATA_DIR / "practice" / f"{name}.json"


def load_practice_store(name: str) -> dict:
    try:
        payload = json.loads(practice_path(name).read_text(encoding="utf-8-sig"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_practice_store(name: str, payload: dict) -> None:
    payload["schema_version"] = 1
    atomic_write(practice_path(name), json.dumps(payload, ensure_ascii=False, indent=2))



def load_bank_questions(bank_id: str) -> list[dict]:
    """Read only formal questions from a published runtime package.

    Quarantine files are deliberately not opened; a malformed formal line makes
    the request fail rather than silently displaying an unverified question.
    """
    bank = question_bank_by_id(bank_id)
    if not bank:
        raise ValueError("question bank not found")
    target = (QUESTION_BANK_DIR / bank["path"] / "questions.jsonl").resolve()
    package = (QUESTION_BANK_DIR / bank["path"]).resolve()
    if package not in target.parents or not target.is_file():
        raise ValueError("question bank unavailable")
    questions: list[dict] = []
    for line in target.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if isinstance(item, dict) and item.get("status") == "ready" and isinstance(item.get("question_id"), str):
            questions.append(item)
    return questions


def public_question(question: dict, reveal: bool = False) -> dict:
    payload = {
        "question_id": question["question_id"], "bank_id": question.get("bank_id"),
        "question_type": question.get("question_type"), "difficulty": question.get("difficulty"),
        "scope": question.get("scope"), "unit": question.get("unit"),
        "unit_label": question.get("unit_label") or practice_unit_metadata(question.get("unit"))["label"],
        "local_number": question.get("local_number"), "context_md": question.get("context_md") or "",
        "stem_md": question.get("stem_md") or "",
        "options": question.get("options") or [], "knowledge_ids": question.get("knowledge_ids") or [],
    }
    if reveal:
        payload.update({"correct_answers": question.get("correct_answers") or [], "source_analysis_md": question.get("source_analysis_md") or ""})
    return payload


def matching_questions(bank_id: str, knowledge_id: str, match_level: str) -> list[dict]:
    if match_level not in {"section", "chapter", "comprehensive"}:
        raise ValueError("invalid practice match level")
    if not re.fullmatch(r"[a-z][a-z0-9.-]{2,120}", knowledge_id):
        raise ValueError("invalid knowledge id")
    questions = load_bank_questions(bank_id)
    if match_level == "comprehensive":
        return [item for item in questions if item.get("scope") == "comprehensive" and knowledge_id in (item.get("knowledge_ids") or [])]
    return [item for item in questions if knowledge_id in (item.get("knowledge_ids") or [])]


def chapter_knowledge_id(knowledge_id: str) -> str:
    match = re.match(r"^(.+\.ch\d{2})(?:\.|$)", knowledge_id)
    return match.group(1) if match else ""


def knowledge_namespace(knowledge_id: str) -> str:
    parts = knowledge_id.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else ""


def practice_availability(book_id: str, section_id: str = "") -> dict:
    books, sections = catalog()
    book = next((item for item in books if item["id"] == book_id), None)
    if not book:
        raise ValueError("book not found")
    section = sections.get(section_id) if section_id else None
    if section_id and (not section or section.get("book_id") != book_id):
        raise ValueError("section not found")
    exact_ids = list(section.get("knowledge_ids") or []) if section else []
    chapter_ids = sorted({chapter_knowledge_id(item) for item in exact_ids if chapter_knowledge_id(item)})
    namespaces = {knowledge_namespace(item) for item in book.get("knowledge_ids") or [] if knowledge_namespace(item)}
    entries: list[dict] = []
    for bank in question_bank_catalog():
        bank_namespaces = {knowledge_namespace(item) for item in bank.get("knowledge_ids") or [] if knowledge_namespace(item)}
        if bank["domain"] != book["domain"] or not namespaces.intersection(bank_namespaces):
            continue
        if section:
            section_specific_ids = sorted((item for item in exact_ids if ".s" in item), key=len, reverse=True)
            for knowledge_id in section_specific_ids:
                count = len(matching_questions(bank["id"], knowledge_id, "section"))
                if count:
                    entries.append({"bank_id": bank["id"], "bank_title": bank["title"], "knowledge_id": knowledge_id, "match_level": "section", "question_count": count})
                    break
            if not any(item["bank_id"] == bank["id"] for item in entries):
                for knowledge_id in chapter_ids:
                    count = len(matching_questions(bank["id"], knowledge_id, "chapter"))
                    if count:
                        entries.append({"bank_id": bank["id"], "bank_title": bank["title"], "knowledge_id": knowledge_id, "match_level": "chapter", "question_count": count})
        else:
            for knowledge_id in sorted(namespaces):
                count = len(matching_questions(bank["id"], knowledge_id, "comprehensive"))
                if count:
                    entries.append({"bank_id": bank["id"], "bank_title": bank["title"], "knowledge_id": knowledge_id, "match_level": "comprehensive", "question_count": count})
    return {"book_id": book_id, "section_id": section_id, "entries": entries}


def practice_session(bank_id: str, knowledge_id: str, match_level: str) -> dict:
    bank = question_bank_by_id(bank_id)
    if not bank:
        raise ValueError("question bank not found")
    questions = matching_questions(bank_id, knowledge_id, match_level)
    attempts = load_practice_store("attempts").get("items", {})
    items = []
    for question in questions:
        attempt = attempts.get(question["question_id"], {}) if isinstance(attempts, dict) else {}
        items.append({"question_id": question["question_id"], "local_number": question.get("local_number"), "question_type": question.get("question_type"), "unit": question.get("unit"), "unit_label": question.get("unit_label") or practice_unit_metadata(question.get("unit"))["label"], "answered": bool(attempt), "correct": attempt.get("correct") if isinstance(attempt, dict) else None})
    return {"bank": {key: bank[key] for key in ("id", "title", "subject", "domain")}, "knowledge_id": knowledge_id, "match_level": match_level, "questions": items, "answered_count": sum(1 for item in items if item["answered"]), "question_count": len(items)}


def practice_unit_metadata(unit: object) -> dict[str, str]:
    """Return a stable, reader-friendly label for one exam unit.

    English exam banks keep the source paper's unit labels (for example
    ``阅读理解 Text 1``).  The overview needs a little more structure without
    forcing those display labels into the question-bank contract, so this
    mapping stays at the YuReader runtime boundary and safely falls back for
    future banks.
    """
    value = re.sub(r"\s+", " ", str(unit or "").strip())
    if re.fullmatch(r"Section\s+I\s+完形填空", value, re.IGNORECASE):
        return {"part": "Section I", "label": "完形填空", "kind": "objective"}
    match = re.fullmatch(r"Section\s+II\s+Part\s+A\s+Text\s+(\d+)", value, re.IGNORECASE)
    if match:
        number = match.group(1)
        return {"part": "Section II · Part A", "label": f"阅读理解 · Text {number}", "kind": "objective"}
    if re.fullmatch(r"Section\s+II\s+Part\s+B\s+新题型", value, re.IGNORECASE):
        return {"part": "Section II · Part B", "label": "阅读理解 · Part B（新题型）", "kind": "objective"}
    if re.fullmatch(r"完形填空", value):
        return {"part": "Section I", "label": "完形填空", "kind": "objective"}
    match = re.fullmatch(r"阅读理解\s+Text\s+(\d+)", value, re.IGNORECASE)
    if match:
        number = match.group(1)
        return {"part": "Section II · Part A", "label": f"阅读理解 · Text {number}", "kind": "objective"}
    if re.fullmatch(r"阅读理解\s+Part\s+B", value, re.IGNORECASE):
        return {"part": "Section II · Part B", "label": "阅读理解 · Part B（新题型）", "kind": "objective"}
    return {"part": "试卷题目", "label": value or "未命名题型", "kind": "objective"}


def _english_exam_track_and_year(bank: dict) -> tuple[int, int] | None:
    """Return ``(year, paper)`` for one English past-paper bank.

    Question-bank ids have existed in two stable forms (``english-2024-e1``
    and ``english-e2-2024``).  Keep this parsing at the runtime boundary so
    subjective companions can be located without fuzzy title matching.
    """
    bank_id = str(bank.get("id") or "")
    match = re.fullmatch(r"english-(\d{4})-e([12])", bank_id)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.fullmatch(r"english-e([12])-(\d{4})", bank_id)
    if match:
        return int(match.group(2)), int(match.group(1))
    title_match = re.search(r"(?<!\d)(20\d{2})(?!\d)", str(bank.get("title") or ""))
    if not title_match:
        return None
    paper = 2 if re.search(r"英语\s*[（(]?二|英语二|e2", f"{bank.get('subject', '')} {bank_id}", re.IGNORECASE) else 1
    return int(title_match.group(1)), paper


def _english_subjective_specs(paper: int) -> list[dict[str, object]]:
    """Describe the non-objective sections without turning them into MCQs."""
    if paper == 2:
        return [
            {"key": "translation", "title": "翻译 · Part C", "range": "第 46 题", "count": 1},
            {"key": "writing-a", "title": "应用文写作 · Part A", "range": "第 47 题", "count": 1},
            {"key": "writing-b", "title": "图表作文 · Part B", "range": "第 48 题", "count": 1},
        ]
    return [
        {"key": "translation", "title": "翻译 · Part C", "range": "第 46–50 题", "count": 5},
        {"key": "writing-a", "title": "应用文写作 · Part A", "range": "第 51 题", "count": 1},
        {"key": "writing-b", "title": "图画/图表写作 · Part B", "range": "第 52 题", "count": 1},
    ]



def english_subjective_companion(bank: dict) -> dict:
    """Resolve the imported subjective material for one past-paper year.

    Older source processing grouped 2010–2017 into one book while later years
    use one book per year.  The returned object always exposes exactly three
    navigable reading sections, preserving that storage choice and keeping the
    top-level English shelf free of duplicate companion books.
    """
    parsed = _english_exam_track_and_year(bank)
    empty = {"available": False, "year": None, "paper": None, "question_count": 0, "range": "", "book_id": "", "title": "", "sections": []}
    if not parsed:
        return empty
    year, paper = parsed
    books, _ = catalog()
    candidates = [item for item in books if item.get("domain") == "english" and re.search(r"主观题|翻译与写作", f"{item.get('title', '')} {item.get('id', '')}", re.IGNORECASE)]
    exact_ids = (
        [f"english-e2-subjective-{year}", f"english-e2-subjective-{year}-ocr"]
        if paper == 2
        else [f"english-exam-{year}-e1-subjective"]
    )
    companion = next((item for item in candidates if item.get("id") in exact_ids), None)
    if companion is None and 2010 <= year <= 2017:
        aggregate_id = "english-e2-subjective-2010-2017" if paper == 2 else "english-e1-subjective-2010-2017"
        companion = next((item for item in candidates if item.get("id") == aggregate_id), None)
    if companion is None:
        return {**empty, "year": year, "paper": paper}

    # For an aggregate package select the chapter whose title identifies this
    # year; for a per-year package the first (and only) chapter is sufficient.
    chapters = sorted(companion.get("toc") or [], key=lambda item: int(item.get("order") or 0))
    chapter = next((item for item in chapters if re.search(rf"(?<!\d){year}(?!\d)", str(item.get("title") or ""))), None)
    if chapter is None and chapters:
        chapter = chapters[0]
    section_by_id = {str(item.get("id")): item for item in companion.get("sections") or [] if isinstance(item, dict)}
    chapter_section_ids = (chapter or {}).get("section_ids")
    if not isinstance(chapter_section_ids, list):
        chapter_section_ids = [item.get("id") for item in (chapter or {}).get("sections", []) if isinstance(item, dict)]
    selected = [section_by_id[str(section_id)] for section_id in chapter_section_ids if str(section_id) in section_by_id]
    # The 2010–2017 English-II candidate intentionally stores each year as
    # one combined reading section.  Do not fall through to the first three
    # sections of the whole package (which would point 2011–2017 at 2010).
    if paper == 2 and len(selected) == 1:
        section = selected[0]
        return {
            "available": True, "year": year, "paper": paper, "question_count": 3,
            "range": "46–48", "book_id": companion["id"], "title": companion.get("title") or "翻译与写作",
            "sections": [{
                "key": "subjective", "title": "翻译与写作 · Part C / IV", "range": "第 46–48 题", "question_count": 3,
                "book_id": companion["id"], "section_id": section["id"], "source_title": section.get("title") or "",
            }],
        }
    if len(selected) < 3:
        selected = sorted(section_by_id.values(), key=lambda item: (int(item.get("chapter_order") or 0), int(item.get("section_order") or item.get("order") or 0)))[:3]
    specs = _english_subjective_specs(paper)
    sections = []
    for index, spec in enumerate(specs):
        section = selected[index] if index < len(selected) else None
        if not section:
            continue
        sections.append({
            "key": spec["key"], "title": spec["title"], "range": spec["range"], "question_count": spec["count"],
            "book_id": companion["id"], "section_id": section["id"], "source_title": section.get("title") or "",
        })
    if not sections:
        return {**empty, "year": year, "paper": paper}
    return {
        "available": True, "year": year, "paper": paper, "question_count": sum(int(item["question_count"]) for item in sections),
        "range": "46–48" if paper == 2 else "46–52", "book_id": companion["id"], "title": companion.get("title") or "翻译与写作", "sections": sections,
    }


def _subjective_record(section_id: str) -> tuple[dict, dict, dict, dict | None, Path]:
    """Resolve one cleaned subjective page and its explicitly paired reference.

    Subjective packages intentionally keep prompts and explanations as separate
    artifacts.  The runtime only pairs ``<prompt key>-analysis`` (or the
    legacy ``ch01-s01`` / ``ch01-s02`` adjacency), never a generic paper
    reference that could contain unrelated objective questions.
    """
    if not re.fullmatch(r"[0-9a-f]{12}", str(section_id or "")):
        raise ValueError("invalid subjective section id")
    books, sections = catalog()
    section = sections.get(section_id)
    if not section:
        raise ValueError("subjective section not found")
    book = next((item for item in books if item.get("id") == section.get("book_id")), None)
    if not book or book.get("domain") != "english":
        raise ValueError("subjective section is not an English material")
    package_dir = (CONTENT_DIR / str(book["id"])).resolve()
    try:
        package_dir.relative_to(CONTENT_DIR)
    except ValueError as error:
        raise ValueError("invalid subjective package") from error
    manifest_path = package_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("subjective package unavailable") from error
    if not isinstance(manifest, dict) or str((manifest.get("book") or {}).get("id") or "") != book["id"]:
        raise ValueError("subjective package manifest mismatch")
    prompt_meta = next((item for item in (manifest.get("sections") or []) if isinstance(item, dict) and str(item.get("id") or "") == section_id), None)
    if not prompt_meta:
        raise ValueError("subjective prompt metadata missing")
    prompt_artifact = str(prompt_meta.get("artifact") or "")
    prompt_path = package_path(package_dir, prompt_artifact)
    if not prompt_path.is_file():
        raise ValueError("subjective prompt unavailable")
    expected_prompt_hash = str(prompt_meta.get("sha256") or "").lower()
    if expected_prompt_hash and hashlib.sha256(prompt_path.read_bytes()).hexdigest() != expected_prompt_hash:
        raise ValueError("subjective prompt integrity check failed")
    references = [item for item in (manifest.get("references") or []) if isinstance(item, dict)]
    prompt_key = str(prompt_meta.get("key") or "")
    reference_meta = next((item for item in references if str(item.get("key") or "") == f"{prompt_key}-analysis"), None)
    if reference_meta is None and prompt_key.endswith("-subjective"):
        # English-II 2010–2017 stores one combined prompt per year and names
        # its paired explanation ``chNN-analysis``.
        reference_meta = next((item for item in references if str(item.get("key") or "") == f"{prompt_key[:-len('-subjective')]}-analysis"), None)
    # Early aggregate packages used ch01-s01/ch01-s02 pairs rather than a
    # semantic key.  The same chapter and the next source order is safe here.
    if reference_meta is None:
        match = re.fullmatch(r"(ch\d+)-s(\d+)", prompt_key)
        if match:
            wanted = f"{match.group(1)}-s{int(match.group(2)) + 1:02d}"
            reference_meta = next((item for item in references if str(item.get("key") or "") == wanted), None)
    reference_markdown = ""
    reference_verified = False
    if reference_meta:
        reference_artifact = str(reference_meta.get("artifact") or "")
        reference_path = package_path(package_dir, reference_artifact)
        if reference_path.is_file():
            expected_reference_hash = str(reference_meta.get("sha256") or "").lower()
            if expected_reference_hash and hashlib.sha256(reference_path.read_bytes()).hexdigest() != expected_reference_hash:
                raise ValueError("subjective reference integrity check failed")
            reference_markdown = reference_path.read_text(encoding="utf-8-sig").strip()
            reference_verified = True
    return book, section, prompt_meta, ({**reference_meta, "verified": reference_verified} if reference_meta else None), package_dir


def subjective_mode(prompt_meta: dict, section: dict) -> str:
    value = f"{prompt_meta.get('key', '')} {prompt_meta.get('title', '')} {section.get('title', '')}".lower()
    if "translation" in value or "翻译" in value:
        return "translation"
    if "writing-a" in value or "应用文" in value:
        return "writing-a"
    if "writing-b" in value or "图表" in value or "图画" in value:
        return "writing-b"
    return "combined"



def subjective_response_path(section_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", str(section_id or "")):
        raise ValueError("invalid subjective section id")
    return SUBJECTIVE_DIR / f"{section_id}.json"


def load_subjective_response(section_id: str) -> dict:
    try:
        payload = json.loads(subjective_response_path(section_id).read_text(encoding="utf-8-sig"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def subjective_response_target(book: dict, section: dict) -> tuple[Path, str, str]:
    subject = safe_note_component(book.get("subject"), "英语")
    chapter = safe_note_component(section.get("chapter_title"), "主观题")
    title = safe_note_component(section.get("title"), section.get("id") or "主观题")
    vault = obsidian_vault()
    if not vault:
        return DATA_DIR / "subjective-notes" / f"{section['id']}.md", "local", ""
    relative = Path("YuReader") / "英语" / subject / "主观题" / chapter / f"{title}·练习.md"
    target = (vault / relative).resolve()
    if vault != target and vault not in target.parents:
        raise ValueError("subjective note path escapes Obsidian vault")
    uri = f"obsidian://open?vault={quote(vault.name)}&file={quote(relative.as_posix())}"
    return target, "obsidian", uri


def subjective_response_markdown(book: dict, section: dict, mode: str, answer: str, reflection: str) -> str:
    lines = [
        "---",
        "yureader_subjective: true",
        f"book_id: {book['id']}",
        f"section_id: {section['id']}",
        f"mode: {mode}",
        "---",
        "",
        f"# {section['title']} · 我的练习",
        "",
        f"> {book['title']} / {section.get('chapter_title') or '主观题'}",
        "",
        "## 我的作答",
        "",
        answer.strip() or "（尚未作答）",
        "",
        "## 侧边栏 / 个人解析",
        "",
        reflection.strip() or "（尚未添加解析）",
    ]
    return "\n".join(lines)


def subjective_practice(section_id: str) -> dict:
    book, section, prompt_meta, reference_meta, _ = _subjective_record(section_id)
    prompt_path = package_path((CONTENT_DIR / book["id"]).resolve(), str(prompt_meta.get("artifact") or ""))
    prompt_markdown = prompt_path.read_text(encoding="utf-8-sig").strip()
    mode = subjective_mode(prompt_meta, section)
    reference_markdown = ""
    if reference_meta and reference_meta.get("verified"):
        reference_path = package_path((CONTENT_DIR / book["id"]).resolve(), str(reference_meta.get("artifact") or ""))
        reference_markdown = reference_path.read_text(encoding="utf-8-sig").strip()
    response = load_subjective_response(section_id)
    _, storage, uri = subjective_response_target(book, section)
    return {
        "section_id": section_id,
        "book_id": book["id"],
        "book_title": book["title"],
        "subject": book.get("subject") or book["title"],
        "title": section["title"],
        "chapter_title": section.get("chapter_title") or "主观题",
        "mode": mode,
        "prompt_markdown": prompt_markdown,
        "reference_markdown": reference_markdown,
        "reference_available": bool(reference_markdown),
        "prompt_source_map": prompt_meta.get("source_map") or section.get("source_map") or {},
        "reference_source_map": (reference_meta or {}).get("source_map") or {},
        "response": response if isinstance(response, dict) else {},
        "storage": storage,
        "path": str(subjective_response_target(book, section)[0]),
        "obsidian_uri": uri,
    }


def practice_overview(bank_id: str) -> dict:
    """Build a lightweight, answer-safe guide for one published paper.

    Questions remain the source of truth.  The response only exposes grouping,
    ranges and progress; answers and explanations are still gated by the
    existing per-question endpoint.
    """
    bank = question_bank_by_id(bank_id)
    if not bank:
        raise ValueError("question bank not found")
    questions = load_bank_questions(bank_id)
    attempts = load_practice_store("attempts").get("items", {})
    groups: list[dict] = []
    for index, question in enumerate(questions):
        metadata = practice_unit_metadata(question.get("unit"))
        key = str(question.get("unit_key") or question.get("unit") or f"group-{index + 1}")
        # Some older English-II banks number each passage locally (Text 1 is
        # 1–5, Text 2 is again 1–5).  The paper guide must show the original
        # exam's global numbering, while other domains retain their package's
        # local numbering semantics.
        display_number = index + 1 if bank.get("domain") == "english" else (question.get("local_number") or index + 1)
        if not groups or groups[-1]["key"] != key:
            knowledge_ids = [
                str(value)
                for value in (question.get("knowledge_ids") or [])
                if isinstance(value, str) and value.strip()
            ]
            groups.append(
                {
                    "key": key,
                    "part": metadata["part"],
                    "label": metadata["label"],
                    "kind": metadata["kind"],
                    # The most-specific knowledge position lets the overview
                    # open one exam unit without guessing a bank-wide ID.  It
                    # also supports banks whose section numbering is local
                    # (such as the current English-II package).
                    "knowledge_id": max(knowledge_ids, key=len, default=""),
                    "start_index": index,
                    "start_number": display_number,
                    "end_number": display_number,
                    "question_count": 0,
                    "answered_count": 0,
                    "correct_count": 0,
                    "paragraph_count": 0,
                    "context_characters": 0,
                }
            )
        group = groups[-1]
        group["question_count"] += 1
        group["end_number"] = display_number
        context = str(question.get("context_md") or "").strip()
        group["paragraph_count"] = max(group["paragraph_count"], len([item for item in re.split(r"\n\s*\n", context) if item.strip()]))
        group["context_characters"] = max(group["context_characters"], len(context))
        attempt = attempts.get(question.get("question_id"), {}) if isinstance(attempts, dict) else {}
        if isinstance(attempt, dict) and attempt:
            group["answered_count"] += 1
            if attempt.get("correct") is True:
                group["correct_count"] += 1

    public_bank = {key: bank[key] for key in ("id", "title", "subject", "domain", "coverage") if key in bank}
    return {
        "bank": public_bank,
        "question_count": len(questions),
        "answered_count": sum(group["answered_count"] for group in groups),
        "groups": groups,
        "subjective": english_subjective_companion(bank) if bank.get("domain") == "english" else {"available": False, "sections": [], "question_count": 0, "range": ""},
    }


def practice_question(bank_id: str, question_id: str) -> dict:
    if not re.fullmatch(r"[a-z0-9-]{3,160}", question_id):
        raise ValueError("invalid question id")
    question = None
    if bank_id and bank_id != "mistakes-session":
        try:
            question = next((item for item in load_bank_questions(bank_id) if item["question_id"] == question_id), None)
        except Exception:
            question = None
    if not question:
        for bank in question_bank_catalog():
            try:
                found = next((item for item in load_bank_questions(bank["id"]) if item["question_id"] == question_id), None)
                if found:
                    question = found
                    break
            except Exception:
                continue
    if not question:
        raise ValueError("question not found")
    attempts = load_practice_store("attempts").get("items", {})
    attempt = attempts.get(question_id, {}) if isinstance(attempts, dict) else {}
    revealed = isinstance(attempt, dict) and bool(attempt)
    analyses = load_practice_store("analyses").get("items", {})
    personal = analyses.get(question_id, {}) if isinstance(analyses, dict) else {}
    return {"question": public_question(question, reveal=revealed), "attempt": attempt if revealed else None, "personal_analysis": str(personal.get("content") or "") if isinstance(personal, dict) else ""}


def practice_subject_label(bank: dict, subject_label: str = "") -> str:
    """Prefer the stable learning subject over a source-series title.

    A published political bank spans several books.  Callers that are handling
    one question should pass that question's subject label; falling back to the
    first question is retained only for bank-level display and compatibility.
    """
    if subject_label.strip():
        return subject_label.strip()
    questions = load_bank_questions(bank["id"])
    for question in questions:
        label = str(question.get("subject_label") or "").strip()
        if label:
            return label
    return str(bank.get("subject") or bank["id"]).strip()


def practice_notes_target(bank: dict, subject_label: str = "") -> tuple[Path, str, str]:
    domain = safe_domain(bank.get("domain"))
    subject = safe_note_component(practice_subject_label(bank, subject_label), bank["id"])
    local = DATA_DIR / "practice-notes" / domain / f"{subject}.md"
    vault = obsidian_vault()
    if not vault:
        return local, "local", ""
    relative = Path("YuReader") / DOMAIN_LABELS[domain] / subject / "练习解析.md"
    target = (vault / relative).resolve()
    if vault != target and vault not in target.parents:
        raise ValueError("practice note path escapes Obsidian vault")
    return target, "obsidian", f"obsidian://open?vault={quote(vault.name)}&file={quote(relative.as_posix())}"


def write_practice_notes(bank_id: str, subject_label: str = "") -> tuple[Path, str, str]:
    bank = question_bank_by_id(bank_id)
    if not bank:
        raise ValueError("question bank not found")
    analyses = load_practice_store("analyses").get("items", {})
    attempts = load_practice_store("attempts").get("items", {})
    grouped: dict[str, list[tuple[dict, dict, dict]]] = {}
    for question in load_bank_questions(bank_id):
        analysis = analyses.get(question["question_id"], {}) if isinstance(analyses, dict) else {}
        if not isinstance(analysis, dict) or not str(analysis.get("content") or "").strip():
            continue
        attempt = attempts.get(question["question_id"], {}) if isinstance(attempts, dict) else {}
        label = practice_subject_label(bank, str(question.get("subject_label") or ""))
        grouped.setdefault(label, []).append((question, analysis, attempt if isinstance(attempt, dict) else {}))

    selected_label = practice_subject_label(bank, subject_label)
    selected: tuple[Path, str, str] | None = None
    for label, entries in grouped.items():
        lines = [f"# {label}练习解析", "", "本文件由 YuReader 根据已保存的个人解析原地重建。"]
        for question, analysis, attempt in entries:
            lines.extend(["", f"## {question['question_id']}", "", f"> {question.get('stem_md') or ''}", "", f"- 我的答案：{'、'.join(attempt.get('selected_answers') or []) or '未作答'}", f"- 正确答案：{'、'.join(question.get('correct_answers') or [])}", "", "### 我的解析", "", str(analysis["content"]).strip()])
        target, storage, uri = practice_notes_target(bank, label)
        atomic_write(target, "\n".join(lines))
        if label == selected_label:
            selected = (target, storage, uri)
    if selected:
        return selected
    return practice_notes_target(bank, selected_label)


def mistakes_overview(domain_filter: str = "") -> dict:
    attempts_data = load_practice_store("attempts").get("items", {})
    analyses_data = load_practice_store("analyses").get("items", {})
    all_banks = question_bank_catalog()
    bank_map = {bank["id"]: bank for bank in all_banks}

    bank_questions: dict[str, dict[str, dict]] = {}
    for bank in all_banks:
        try:
            questions = load_bank_questions(bank["id"])
            bank_questions[bank["id"]] = {q["question_id"]: q for q in questions}
        except Exception:
            continue

    mistakes: list[dict] = []
    resolved_count = 0
    pending_count = 0

    for qid, attempt in attempts_data.items():
        if not isinstance(attempt, dict):
            continue
        if attempt.get("correct") is not False and not attempt.get("previously_wrong"):
            continue

        bank_id = attempt.get("bank_id") or ""
        bank = bank_map.get(bank_id, {})
        domain = safe_domain(bank.get("domain") or "politics")
        if domain_filter and domain != domain_filter:
            continue

        q_dict = bank_questions.get(bank_id, {}).get(qid)
        if not q_dict:
            for b_id, b_qs in bank_questions.items():
                if qid in b_qs:
                    q_dict = b_qs[qid]
                    bank_id = b_id
                    bank = bank_map.get(bank_id, {})
                    domain = safe_domain(bank.get("domain") or "politics")
                    break

        if not q_dict:
            continue

        is_resolved = bool(attempt.get("resolved") or (attempt.get("correct") is True and attempt.get("previously_wrong")))
        if is_resolved:
            resolved_count += 1
        else:
            pending_count += 1

        personal_analysis = str((analyses_data.get(qid) or {}).get("content") or "").strip()

        mistakes.append({
            "question_id": qid,
            "bank_id": bank_id,
            "bank_title": bank.get("title") or bank_id,
            "domain": domain,
            "domain_label": DOMAIN_LABELS.get(domain, domain),
            "subject_label": practice_subject_label(bank, str(q_dict.get("subject_label") or "")),
            "stem_md": q_dict.get("stem_md") or "",
            "context_md": q_dict.get("context_md") or "",
            "options": q_dict.get("options") or [],
            "correct_answers": q_dict.get("correct_answers") or [],
            "selected_answers": attempt.get("selected_answers") or [],
            "source_analysis_md": q_dict.get("source_analysis_md") or "",
            "personal_analysis": personal_analysis,
            "answered_at": attempt.get("answered_at") or "",
            "resolved": is_resolved,
            "resolved_at": attempt.get("resolved_at") or "",
        })

    mistakes.sort(key=lambda x: (1 if x["resolved"] else 0, x["answered_at"] or ""), reverse=True)

    return {
        "total": len(mistakes),
        "pending": pending_count,
        "resolved": resolved_count,
        "items": mistakes,
    }


def resolve_mistake(question_id: str, resolved: bool = True) -> dict:
    if not re.fullmatch(r"[a-z0-9-]{3,160}", question_id):
        raise ValueError("invalid question id")
    with PRACTICE_LOCK:
        payload = load_practice_store("attempts")
        items = payload.setdefault("items", {})
        if question_id not in items:
            raise ValueError("question attempt not found")
        items[question_id]["resolved"] = bool(resolved)
        items[question_id]["resolved_at"] = datetime.now().astimezone().isoformat(timespec="seconds") if resolved else ""
        save_practice_store("attempts", payload)
    return {"ok": True, "question_id": question_id, "resolved": resolved}


def create_mistakes_practice_session(domain: str = "") -> dict:
    overview = mistakes_overview(domain_filter=domain)
    pending = [m for m in overview.get("items", []) if not m.get("resolved")]
    domain_label = DOMAIN_LABELS.get(domain, "全科") if domain else "全科"
    if not pending:
        return {
            "available": False,
            "bank": {
                "id": "mistakes-session",
                "title": f"错题攻坚专项集训 · {domain_label}",
                "subject": "二刷攻坚",
                "domain": domain or "politics",
            },
            "knowledge_id": "mistakes",
            "match_level": "mistakes",
            "is_mistakes_session": True,
            "questions": [],
            "question_count": 0,
            "answered_count": 0,
        }

    questions = []
    for idx, m in enumerate(pending):
        questions.append({
            "question_id": m["question_id"],
            "bank_id": m["bank_id"],
            "local_number": idx + 1,
            "question_type": "single_choice" if len(m.get("correct_answers") or []) <= 1 else "multiple_choice",
            "unit": m.get("bank_title") or "错题集训",
            "unit_label": m.get("domain_label") or "错题",
            "answered": False,
            "correct": None,
        })

    return {
        "available": True,
        "bank": {
            "id": "mistakes-session",
            "title": f"错题攻坚专项集训 · {domain_label}（共 {len(questions)} 题）",
            "subject": "二刷攻坚",
            "domain": domain or "politics",
        },
        "knowledge_id": "mistakes",
        "match_level": "mistakes",
        "is_mistakes_session": True,
        "questions": questions,
        "question_count": len(questions),
        "answered_count": 0,
    }


