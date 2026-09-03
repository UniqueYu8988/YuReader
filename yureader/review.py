"""Spaced repetition review, weekly reports, and study logs."""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from yureader.config import (
    DATA_DIR,
    ACTIVITY_TYPES,
    DOMAIN_LABELS,
    REVIEWS_DIR,
    VALID_DOMAINS,
    REVIEW_WORKFLOW_DIR,
    REVIEW_PAGE_CHARACTERS,
)
from yureader.utils import (
    safe_domain,
    atomic_write,
)
from yureader.catalog import (
    catalog,
    resolve_section_id,
)
from yureader.obsidian import (
    obsidian_vault,
    dated_note_path,
    section_note_records,
    section_note_source,
    archive_target,
    archive_files,
    review_note_files,
    daily_review_target,
    daily_learning_record_target,
    learning_record_files,
    weekly_learning_record_target,
    weekly_learning_record_files,
    english_notebook_files,
)
from yureader.activity import (
    load_activity,
    record_activity,
    activity_records_payload,
    meaningful_learning_day,
    effective_activity_payload,
    coalesce_activity_records,
    completed_review_activity,
    meaningful_activity,
    _activity_output_ref,
    activity_stable_id,
    activity_resume_target,
)
from yureader.practice import (
    load_bank_questions,
    load_practice_store,
    load_subjective_response,
)
from yureader.oral_focus import oral_focus_item_payload

def record_review_activities(review: dict, output_path: Path | str) -> None:
    """Index saved review outputs once per participating learning subject."""
    review_day = str(review.get("review_date") or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", review_day):
        return
    for subject in review.get("subjects") if isinstance(review.get("subjects"), list) else []:
        if not isinstance(subject, dict):
            continue
        resource_id = str(subject.get("resource_id") or subject.get("book_id") or subject.get("subject_key") or "")
        domain = str(subject.get("domain") or "").strip().lower()
        if domain not in VALID_DOMAINS:
            domain = "other"
        subject_id = str(subject.get("subject_id") or subject.get("title") or resource_id)
        if not resource_id or not subject_id:
            continue
        context = {
            "domain": domain,
            "subject_id": subject_id,
            "resource_id": resource_id,
            "item_id": review_day,
            "resume_target": {"view": "review", "resource_id": resource_id, "item_id": review_day},
        }
        record_activity(
            "review",
            activity_type="review",
            context=context,
            activity_id=activity_stable_id(date.today().isoformat(), "review", resource_id, review_day),
            result_state="completed" if subject.get("completed") else "has_output",
            output_refs=[_activity_output_ref("learning_record", review_day, output_path)] if subject.get("completed") else [],
        )



def unified_review_result(day: str) -> dict | None:
    """Read the result section from a new daily record, without duplicating it."""
    target, _storage, _uri = daily_learning_record_target(day)
    candidates = [target]
    local_target = DATA_DIR / "learning-records" / day[:4] / day[5:7] / f"{day}.md"
    if local_target not in candidates:
        candidates.append(local_target)
    for path in candidates:
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        marker = re.search(r"(?m)^## 本次回顾\s*$", content)
        if not marker:
            return {"summary": "", "no_text": False, "path": path}
        result = content[marker.end():].strip()
        if result == "（已标记为无文本回顾。）":
            return {"summary": "", "no_text": True, "path": path}
        return {"summary": result, "no_text": False, "path": path}
    return None


def read_weekly_summary(path: Path) -> str:
    try:
        content = path.read_text(encoding="utf-8-sig")
    except OSError:
        return ""
    marker = re.search(r"(?m)^## 阶段总结\s*$", content)
    return content[marker.end():].strip() if marker else ""


def reviewable_learning_days() -> tuple[list[str], set[str]]:
    """Return valid historical learning days and the days already reviewed."""
    activity = load_activity()
    raw_days = activity.get("days") if isinstance(activity.get("days"), dict) else {}
    records = activity_records_payload().get("activities", [])
    reviewed: set[str] = set()
    for day, value in raw_days.items():
        if isinstance(value, dict) and value.get("review_saved"):
            reviewed.add(str(day))
    reviewed.update(review_note_files())
    for item in records:
        if completed_review_activity(item):
            target = item.get("resume_target") if isinstance(item.get("resume_target"), dict) else {}
            source_day = str(target.get("item_id") or "")
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", source_day):
                reviewed.add(source_day)
    today = date.today().isoformat()
    records_by_day: dict[str, list[dict]] = {}
    for item in records:
        records_by_day.setdefault(str(item.get("date") or ""), []).append(item)
    valid = {
        str(day)
        for day, value in raw_days.items()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(day))
        and str(day) < today
        and meaningful_learning_day(value, records_by_day.get(str(day), []), include_review=False)
    }
    return sorted(valid, reverse=True), reviewed


def next_review_day(requested: str = "") -> str:
    if requested:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", requested):
            raise ValueError("invalid date")
        return requested
    valid_days, reviewed = reviewable_learning_days()
    for day in valid_days:
        if day not in reviewed:
            return day
    return (date.today() - timedelta(days=1)).isoformat()



def workflow_state_path(day: str) -> Path:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("invalid date")
    return REVIEW_WORKFLOW_DIR / f"{day}.json"


def load_workflow_state(day: str) -> dict:
    try:
        payload = json.loads(workflow_state_path(day).read_text(encoding="utf-8-sig"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def daily_log_markdown(day: str, subjects: list[dict], summary: str) -> str:
    target = date.fromisoformat(day)
    lines = [f"# {target.month}月{target.day}日学习日志"]
    if summary.strip():
        lines.extend(["", "## 昨日总结", "", summary.strip()])
    completed = [subject for subject in subjects if str(subject.get("result") or "").strip()]
    if completed:
        lines.extend(["", "## 分科复习"])
        for subject in completed:
            lines.extend(["", f"### {subject['title']}", "", str(subject["result"]).strip()])
    return "\n".join(lines).strip()



def split_review_markdown(markdown: str, limit: int = REVIEW_PAGE_CHARACTERS) -> list[str]:
    """Split a long note at Markdown paragraph boundaries where possible."""
    text = markdown.strip()
    if len(text) <= limit:
        return [text] if text else []
    blocks = re.split(r"\n\s*\n", text)
    chunks: list[str] = []
    current = ""
    for block in blocks:
        candidate = f"{current}\n\n{block}".strip() if current else block
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            if len(current) < limit // 3:
                remainder = f"{current}\n\n{block}"
            else:
                chunks.append(current)
                remainder = block
            current = ""
        else:
            remainder = block
        while len(remainder) > limit:
            boundary = max(
                remainder.rfind("\n", 0, limit),
                remainder.rfind("。", 0, limit),
                remainder.rfind("；", 0, limit),
            )
            if boundary < limit // 2:
                boundary = limit
            else:
                boundary += 1
            chunks.append(remainder[:boundary].strip())
            remainder = remainder[boundary:].strip()
        current = remainder
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk]


def _legacy_review_payload(day: str, books: list[dict], sections: dict[str, dict]) -> dict:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("invalid date")
    target_day = date.fromisoformat(day)
    note_sources = {
        section_id: path
        for section_id, (path, _markdown) in section_note_records(sections).items()
        if date.fromtimestamp(path.stat().st_mtime) == target_day
    }

    section_books = {
        section["id"]: book
        for book in books
        for section in book.get("sections", [])
    }
    notes: list[dict] = []
    for section_id, source in sorted(note_sources.items(), key=lambda item: item[1].stat().st_mtime):
        section = sections.get(section_id)
        if not section:
            continue
        markdown = source.read_text(encoding="utf-8-sig").strip()
        if not markdown:
            continue
        book = section_books.get(section_id, {})
        notes.append(
            {
                "section_id": section_id,
                "book_id": book.get("id", ""),
                "book_title": section.get("book_title") or book.get("title", ""),
                "chapter_title": section.get("chapter_title", ""),
                "section_title": section.get("title", ""),
                "markdown": markdown,
                "character_count": len(markdown),
            }
        )

    subjects: dict[str, list[dict]] = {}
    for note in notes:
        subjects.setdefault(note["book_title"] or "未分类", []).append(note)

    pages: list[dict] = []
    for subject, subject_notes in subjects.items():
        page_items: list[dict] = []
        page_length = 0
        for note in subject_notes:
            chunks = split_review_markdown(note["markdown"])
            for chunk_index, chunk in enumerate(chunks):
                item = {
                    **{key: value for key, value in note.items() if key != "markdown"},
                    "markdown": chunk,
                    "part": chunk_index + 1,
                    "part_count": len(chunks),
                }
                item_length = len(chunk) + len(note["section_title"]) + 80
                if page_items and page_length + item_length > REVIEW_PAGE_CHARACTERS:
                    pages.append(
                        {
                            "subject": subject,
                            "items": page_items,
                            "character_count": page_length,
                            "note_count": len({entry["section_id"] for entry in page_items}),
                        }
                    )
                    page_items, page_length = [], 0
                page_items.append(item)
                page_length += item_length
        if page_items:
            pages.append(
                {
                    "subject": subject,
                    "items": page_items,
                    "character_count": page_length,
                    "note_count": len({entry["section_id"] for entry in page_items}),
                }
            )
    for index, page in enumerate(pages):
        page["number"] = index + 1

    workflow = load_workflow_state(day)
    saved_results = workflow.get("subjects") if isinstance(workflow.get("subjects"), dict) else {}
    activity = load_activity()
    day_activity = (activity.get("days") or {}).get(day, {}) if isinstance(activity.get("days"), dict) else {}
    section_seconds: dict[str, int] = {}
    raw_section_seconds = day_activity.get("section_reading_seconds") if isinstance(day_activity.get("section_reading_seconds"), dict) else {}
    for section_id, seconds in raw_section_seconds.items():
        resolved = resolve_section_id(section_id, set(sections))
        if resolved:
            section_seconds[resolved] = section_seconds.get(resolved, 0) + max(0, int(seconds or 0))
    grouped_by_book: dict[str, list[dict]] = {}
    for note in notes:
        grouped_by_book.setdefault(note["book_id"] or note["book_title"], []).append(note)
    subject_tasks: list[dict] = []
    for book_key, subject_notes in grouped_by_book.items():
        result = str(saved_results.get(book_key) or "")
        subject_tasks.append(
            {
                "book_id": book_key,
                "title": subject_notes[0]["book_title"] or "未分类",
                "note_count": len(subject_notes),
                "character_count": sum(item["character_count"] for item in subject_notes),
                "reading_seconds": sum(max(0, int(section_seconds.get(item["section_id"]) or 0)) for item in subject_notes),
                "time_tracked": bool(section_seconds),
                "notes": subject_notes,
                "result": result,
                "completed": bool(result.strip()),
            }
        )
    completed_count = sum(1 for subject in subject_tasks if subject["completed"])
    summary = str(workflow.get("summary") or "")
    log_target, log_storage, log_uri = archive_target(day, "daily")
    combined_markdown = daily_log_markdown(day, subject_tasks, summary)

    today = date.today().isoformat()
    review_note_file, review_storage, obsidian_uri = daily_review_target(today)
    local_review_file = dated_note_path(REVIEWS_DIR, today)
    if review_note_file.is_file():
        review_note = review_note_file.read_text(encoding="utf-8-sig")
    elif local_review_file.is_file():
        review_note = local_review_file.read_text(encoding="utf-8-sig")
    else:
        review_note = ""
    return {
        "review_date": day,
        "review_note_date": today,
        "note_count": len(notes),
        "subject_count": len(subjects),
        "page_count": len(pages),
        "pages": pages,
        "review_note": review_note,
        "review_note_characters": len(review_note.strip()),
        "review_storage": review_storage,
        "review_path": str(review_note_file),
        "obsidian_uri": obsidian_uri,
        "subjects": subject_tasks,
        "completed_count": completed_count,
        "all_complete": bool(subject_tasks) and completed_count == len(subject_tasks),
        "daily_summary": summary,
        "combined_markdown": combined_markdown,
        "log_storage": log_storage,
        "log_path": str(log_target),
        "log_uri": log_uri,
    }


def _review_subject_key(domain: object, subject_id: object) -> str:
    return f"{safe_domain(domain)}:{str(subject_id or '未分类').strip() or '未分类'}"


def _review_snippet(markdown: str, limit: int = 5000) -> str:
    chunks = split_review_markdown(markdown, limit)
    if not chunks:
        return ""
    snippet = chunks[0]
    if len(chunks) > 1:
        snippet = f"{snippet}\n\n> 其余内容仍保留在英语周记原文件中。"
    return snippet


def _english_notebook_day_markdown(markdown: str, day: str) -> str:
    """Return only the requested dated H2 block from a weekly notebook."""
    if not markdown.strip() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        return ""
    target = date.fromisoformat(day)
    weekday = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")[target.weekday()]
    month, day_number = target.month, target.day
    date_tokens = {
        f"{month}/{day_number}",
        f"{month:02d}/{day_number:02d}",
        f"{month}月{day_number}日",
        target.isoformat(),
    }
    headings = list(re.finditer(r"(?m)^##\s+([^\n]+?)\s*$", markdown))
    for index, heading in enumerate(headings):
        label = heading.group(1).strip()
        if weekday not in label or not any(token in label for token in date_tokens):
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(markdown)
        return markdown[heading.start():end].strip()
    return ""


def review_source_records(day: str, books: list[dict], sections: dict[str, dict]) -> list[dict]:
    """Collect referenced user outputs for one learning day, without copying source bodies into storage."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("invalid date")
    target_day = date.fromisoformat(day)
    section_books = {
        section["id"]: book
        for book in books
        for section in book.get("sections", [])
    }
    note_files = section_note_records(sections)
    records = [item for item in coalesce_activity_records(activity_records_payload(day).get("activities", [])) if meaningful_activity(item, include_review=False)]
    raw_activity = load_activity()
    raw_day = (raw_activity.get("days") or {}).get(day, {}) if isinstance(raw_activity.get("days"), dict) else {}
    sources: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    def add_source(
        *,
        source_type: str,
        domain: object,
        subject_id: object,
        resource_id: object,
        item_id: object,
        title: object,
        markdown: str,
        duration_seconds: int = 0,
        resume_target: dict | None = None,
        note_text: str = "",
        section_id: str = "",
        book_id: str = "",
        book_title: str = "",
    ) -> None:
        clean_item = str(item_id or resource_id or "")
        subject = str(subject_id or resource_id or "未分类").strip() or "未分类"
        key = (source_type, _review_subject_key(domain, subject), clean_item)
        if key in seen:
            return
        seen.add(key)
        body = str(markdown or "").strip()
        sources.append(
            {
                "source_type": source_type,
                "source_label": {"section_note": "章节笔记", "objective_practice": "客观题", "subjective_practice": "主观题", "notebook": "英语周记", "read": "阅读轨迹"}.get(source_type, source_type),
                "domain": safe_domain(domain),
                "subject_id": subject,
                "subject_key": _review_subject_key(domain, subject),
                "resource_id": str(resource_id or ""),
                "item_id": clean_item,
                "title": str(title or clean_item),
                "markdown": body,
                "note_text": str(note_text or "").strip(),
                "character_count": len(body),
                "duration_seconds": max(0, int(duration_seconds or 0)),
                "resume_target": resume_target if isinstance(resume_target, dict) else {},
                "section_id": section_id,
                "book_id": book_id,
                "book_title": book_title,
            }
        )

    for item in records:
        activity_type = str(item.get("activity_type") or "")
        if activity_type == "review":
            continue
        domain = item.get("domain") or "medicine"
        subject_id = item.get("subject_id") or item.get("resource_id")
        resource_id = item.get("resource_id") or ""
        item_id = item.get("item_id") or ""
        target = activity_resume_target(item)
        duration = max(0, int(item.get("duration_seconds") or 0))
        if activity_type == "read":
            note_ref = next((ref for ref in item.get("output_refs") or [] if isinstance(ref, dict) and ref.get("kind") == "section_note"), None)
            canonical = resolve_section_id((note_ref or {}).get("id") if note_ref else item_id, set(sections))
            note_source = note_files.get(canonical) if canonical else None
            section = sections.get(canonical or item_id, {})
            book = section_books.get(canonical or item_id, {})
            body = ""
            if note_source:
                try:
                    body = note_source[1]
                except (IndexError, TypeError):
                    body = ""
            add_source(
                source_type="section_note" if body else "read",
                domain=(book or {}).get("domain") or domain,
                subject_id=(book or {}).get("subject") or subject_id,
                resource_id=(book or {}).get("id") or resource_id,
                item_id=canonical or item_id,
                title=(section or {}).get("title") or item_id,
                markdown=body,
                note_text=body if body else "",
                duration_seconds=duration,
                resume_target={"view": "reader", "resource_id": (book or {}).get("id") or resource_id, "item_id": canonical or item_id},
                section_id=canonical or "",
                book_id=str((book or {}).get("id") or ""),
                book_title=str((book or {}).get("title") or ""),
            )
            continue
        if activity_type == "objective_practice":
            attempt = load_practice_store("attempts").get("items", {}).get(str(item_id), {})
            analysis = load_practice_store("analyses").get("items", {}).get(str(item_id), {})
            attempt = attempt if isinstance(attempt, dict) else {}
            analysis = analysis if isinstance(analysis, dict) else {}
            question = None
            try:
                question = next((entry for entry in load_bank_questions(str(resource_id)) if entry.get("question_id") == str(item_id)), None)
            except (OSError, ValueError, KeyError, TypeError):
                pass
            question_number = (question or {}).get("local_number")
            body_lines: list[str] = []
            stem = str((question or {}).get("stem_md") or "").strip()
            if stem:
                body_lines.extend(["#### 题干", "", stem])
            options = [entry for entry in (question or {}).get("options") or [] if isinstance(entry, dict)]
            if options:
                body_lines.extend(["", "#### 选项", ""])
                body_lines.extend(f"- **{entry.get('label', '')}** {str(entry.get('text_md') or '').strip()}" for entry in options)
            body_lines.extend(["", "#### 作答记录", "", f"- 状态：{'错题' if attempt and attempt.get('correct') is False else '已作答' if attempt else '已进入题目'}"])
            if attempt.get("selected_answers"):
                body_lines.append(f"- 我的选择：{', '.join(str(value) for value in attempt['selected_answers'])}")
            correct_answers = [str(value) for value in (question or {}).get("correct_answers") or [] if str(value)]
            if correct_answers:
                body_lines.append(f"- 正确答案：{', '.join(correct_answers)}")
            personal_note = str(analysis.get("content") or "").strip()
            if personal_note:
                body_lines.extend(["", "#### 个人解析", "", personal_note])
            add_source(
                source_type="objective_practice",
                domain=domain,
                subject_id=subject_id,
                resource_id=resource_id,
                item_id=item_id,
                title=f"第 {question_number} 题" if question_number else f"题目 {item_id}",
                markdown="\n".join(body_lines),
                note_text=personal_note,
                duration_seconds=duration,
                resume_target=target,
            )
            continue
        if activity_type == "subjective_practice":
            if str(item_id).startswith("oral-focus-"):
                try:
                    focus = oral_focus_item_payload(str(item_id))
                except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                    focus = {}
                focus_progress = focus.get("progress") if isinstance(focus.get("progress"), dict) else {}
                body_lines: list[str] = []
                focus_notes: list[str] = []
                ans = str(focus_progress.get("answer") or "").strip()
                mem = str(focus_progress.get("memory_note") or "").strip()
                if ans:
                    body_lines.extend(["#### 我的作答", "", ans])
                    focus_notes.append(f"**我的作答**：\n{ans}")
                if mem:
                    body_lines.extend(["", "#### 漏点与记忆", "", mem])
                    focus_notes.append(f"**漏点与记忆**：\n{mem}")
                add_source(
                    source_type="subjective_practice",
                    domain="medicine",
                    subject_id=(focus.get("subject") or {}).get("title") or subject_id,
                    resource_id=resource_id,
                    item_id=item_id,
                    title=str(focus.get("title") or "口腔重点题"),
                    markdown="\n".join(body_lines) or "- 已进入口腔重点题，个人作答仍保留在重点学习记录中。",
                    note_text="\n\n".join(focus_notes),
                    duration_seconds=duration,
                    resume_target={"view": "oral_focus", "resource_id": resource_id, "item_id": item_id},
                )
                continue
            response = load_subjective_response(str(item_id))
            section = sections.get(str(item_id), {})
            body_lines: list[str] = []
            subj_notes: list[str] = []
            sub_ans = str(response.get("answer") or "").strip()
            sub_ref = str(response.get("reflection") or "").strip()
            if sub_ans:
                body_lines.extend(["#### 我的作答", "", sub_ans])
                subj_notes.append(f"**我的作答**：\n{sub_ans}")
            if sub_ref:
                body_lines.extend(["", "#### 反思", "", sub_ref])
                subj_notes.append(f"**反思解析**：\n{sub_ref}")
            add_source(
                source_type="subjective_practice",
                domain=domain,
                subject_id=subject_id,
                resource_id=resource_id,
                item_id=item_id,
                title=str(section.get("title") or response.get("title") or "主观题"),
                markdown="\n".join(body_lines) or "- 已保存主观题活动，答案仍保留在原始作答文件。",
                note_text="\n\n".join(subj_notes),
                duration_seconds=duration,
                resume_target=target,
            )
            continue
        if activity_type == "notebook":
            notebook_path = english_notebook_files().get(str(item_id))
            content = ""
            if notebook_path:
                try:
                    content = notebook_path.read_text(encoding="utf-8-sig")
                except OSError:
                    content = ""
            nb_body = _review_snippet(_english_notebook_day_markdown(content, day))
            add_source(
                source_type="notebook",
                domain="english",
                subject_id="英语笔记",
                resource_id="english-notebook",
                item_id=item_id,
                title=f"{item_id} · 英语周记",
                markdown=nb_body,
                note_text=nb_body,
                duration_seconds=duration,
                resume_target=target,
            )

    # Schema-1 reviews remain readable if the historical activity was created
    # before unified records existed.  This compatibility branch never writes
    # a new record and only maps IDs already accepted by the caller's catalog.
    if not records and isinstance(raw_day, dict):
        legacy_ids = []
        for field in ("sections", "notes"):
            values = raw_day.get(field) if isinstance(raw_day.get(field), list) else []
            legacy_ids.extend(str(value) for value in values if str(value))
        raw_seconds = raw_day.get("section_reading_seconds") if isinstance(raw_day.get("section_reading_seconds"), dict) else {}
        legacy_ids.extend(str(value) for value in raw_seconds if str(value))
        for raw_id in dict.fromkeys(legacy_ids):
            canonical = resolve_section_id(raw_id, set(sections))
            if not canonical:
                continue
            section = sections.get(canonical, {})
            book = section_books.get(canonical, {})
            note = note_files.get(canonical)
            body = note[1] if note else ""
            add_source(
                source_type="section_note" if body else "read",
                domain=(book or {}).get("domain") or "medicine",
                subject_id=(book or {}).get("subject") or (book or {}).get("title") or "未分类",
                resource_id=(book or {}).get("id") or "",
                item_id=canonical,
                title=(section or {}).get("title") or canonical,
                markdown=body,
                duration_seconds=max(0, int(raw_seconds.get(raw_id) or 0)),
                resume_target={"view": "reader", "resource_id": (book or {}).get("id") or "", "item_id": canonical},
                section_id=canonical,
                book_id=str((book or {}).get("id") or ""),
                book_title=str((book or {}).get("title") or ""),
            )
    return sources


def daily_learning_record_markdown(review: dict) -> str:
    lines = [f"# {review.get('review_date', '')} 学习记录", "", "## 当日概览", "", f"- 有效活动：{review.get('activity_count', 0)} 条", f"- 有效时长：{format_duration_text(review.get('duration_seconds', 0))}"]
    for domain, seconds in sorted((review.get("activity_by_domain") or {}).items()):
        lines.append(f"- {DOMAIN_LABELS.get(domain, domain)}：{format_duration_text(seconds)}")
    lines.extend(["", "## 学习位置"])
    for source in review.get("sources") or []:
        target = source.get("resume_target") if isinstance(source.get("resume_target"), dict) else {}
        location = target.get("item_id") or source.get("item_id") or ""
        lines.append(f"- {source.get('source_label', '学习')} · {source.get('subject_id', '')} · {source.get('title', location)}（{location}）")
    if review.get("review_no_text"):
        lines.extend(["", "## 本次回顾", "", "（已标记为无文本回顾。）"])
    elif str(review.get("review_result") or "").strip():
        lines.extend(["", "## 本次回顾", "", str(review["review_result"]).strip()])
    return "\n".join(lines).strip()


def format_duration_text(seconds: object) -> str:
    value = max(0, int(seconds or 0))
    if value < 60:
        return f"{value} 秒"
    return f"{value // 60} 分钟" if value % 60 == 0 else f"{value // 60} 分 {value % 60} 秒"


def write_daily_learning_record(review: dict) -> tuple[Path, str, str, str]:
    target, storage, uri = daily_learning_record_target(str(review.get("review_date") or ""))
    content = daily_learning_record_markdown(review)
    atomic_write(target, content)
    return target, storage, uri, content


def extract_domain_note_items(sources: list[dict]) -> dict[str, list[dict]]:
    notes_by_domain: dict[str, list[dict]] = {
        "medicine": [],
        "politics": [],
        "english": [],
    }
    for source in sources:
        note_text = str(source.get("note_text") or "").strip()
        if not note_text and source.get("source_type") == "section_note":
            note_text = str(source.get("markdown") or "").strip()
        if not note_text:
            continue
        domain = source.get("domain") or "medicine"
        if domain not in notes_by_domain:
            notes_by_domain[domain] = []

        tags: list[str] = []
        subject_name = str(source.get("book_title") or source.get("subject_id") or "").strip()
        if subject_name and subject_name != "未分类":
            tags.append(subject_name)
        item_title = str(source.get("title") or "").strip()
        if item_title and item_title not in tags:
            tags.append(item_title)
        source_label = str(source.get("source_label") or "").strip()
        if source_label and source_label not in tags:
            tags.append(source_label)

        notes_by_domain[domain].append({
            "id": str(source.get("item_id") or ""),
            "domain": domain,
            "domain_label": DOMAIN_LABELS.get(domain, domain),
            "source_type": source.get("source_type"),
            "source_label": source_label,
            "title": item_title or subject_name,
            "tags": tags,
            "markdown": note_text,
            "resume_target": source.get("resume_target") or {},
        })
    return notes_by_domain


def generate_review_ai_prompt(day: str, notes_by_domain: dict[str, list[dict]]) -> str:
    prompt_lines = [
        f"这是我在 {day} 学习中记录的核心笔记与思考（已按医学、政治、英语整理归类）：",
        "",
    ]
    has_any = False
    for dom_key in ("medicine", "politics", "english"):
        dom_notes = notes_by_domain.get(dom_key, [])
        if not dom_notes:
            continue
        has_any = True
        prompt_lines.append(f"## 【{DOMAIN_LABELS.get(dom_key, dom_key)}】（共 {len(dom_notes)} 条笔记）")
        for idx, note in enumerate(dom_notes, 1):
            tag_str = " · ".join(note.get("tags") or [])
            prompt_lines.append(f"### {idx}. {note.get('title')}（{tag_str}）")
            prompt_lines.append(note.get("markdown", "").strip())
            prompt_lines.append("")
    if not has_any:
        prompt_lines.append("昨日主要进行了教材阅读与题目练习，未记录较多独立文字笔记。")
        prompt_lines.append("")
    prompt_lines.extend([
        "---",
        "请作为我的考研复习督导与学科顾问，针对上述昨日笔记：",
        "1. 串联梳理今日笔记涉及的核心知识框架与逻辑脉络；",
        "2. 针对重点知识提炼出 3 个最核心或最易混淆的遗忘薄弱点，给出 3 道抽背检测题；",
        "3. 输出一段结构化精练的当日复盘总结（适合直接归档到 Obsidian）。",
    ])
    return "\n".join(prompt_lines).strip()


def review_payload(day: str, books: list[dict], sections: dict[str, dict]) -> dict:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("invalid date")
    sources = review_source_records(day, books, sections)
    groups: dict[str, list[dict]] = {}
    for source in sources:
        groups.setdefault(str(source["subject_key"]), []).append(source)
    workflow = load_workflow_state(day)
    saved_results = workflow.get("subjects") if isinstance(workflow.get("subjects"), dict) else {}
    unified_result = unified_review_result(day)
    if unified_result is not None:
        summary = str(unified_result.get("summary") or "").strip()
        review_no_text = bool(unified_result.get("no_text"))
    else:
        # Legacy workflow files are historical read-only input. New writes use
        # the daily learning record and never update this directory.
        summary = str(workflow.get("summary") or "").strip()
        review_no_text = bool(workflow.get("summary_no_text"))
    review_done = bool(summary) or review_no_text
    subjects: list[dict] = []
    for subject_key, subject_sources in groups.items():
        first = subject_sources[0]
        saved = saved_results.get(subject_key)
        if saved is None and first.get("book_id"):
            saved = saved_results.get(first["book_id"])
        if isinstance(saved, dict):
            result = str(saved.get("result") or "")
            no_text = bool(saved.get("no_text"))
        else:
            result = str(saved or "")
            no_text = False
        subject = {
            "book_id": str(first.get("book_id") or subject_key),
            "subject_key": subject_key,
            "domain": first.get("domain", ""),
            "subject_id": first.get("subject_id", ""),
            "title": first.get("subject_id") or first.get("book_title") or subject_key,
            "note_count": sum(1 for item in subject_sources if item.get("source_type") == "section_note"),
            "source_count": len(subject_sources),
            "character_count": sum(int(item.get("character_count") or 0) for item in subject_sources),
            "reading_seconds": sum(int(item.get("duration_seconds") or 0) for item in subject_sources if item.get("source_type") in {"read", "section_note"}),
            "activity_seconds": sum(int(item.get("duration_seconds") or 0) for item in subject_sources),
            "time_tracked": any(int(item.get("duration_seconds") or 0) > 0 for item in subject_sources),
            "notes": subject_sources,
            "sources": subject_sources,
            "result": result,
            "no_text": no_text,
            "completed": bool(result.strip()) or no_text or review_done,
        }
        subjects.append(subject)
    # Preserve the first-seen activity order so historical review pages remain
    # stable and callers can compare the displayed subjects with their source order.
    pages: list[dict] = []
    for subject in subjects:
        page_items: list[dict] = []
        page_length = 0
        for source in subject["sources"]:
            body = str(source.get("markdown") or "").strip() or f"- {source.get('source_label', '学习')}：仅记录活动轨迹，不复制正文。"
            for chunk_index, chunk in enumerate(split_review_markdown(body) or [body]):
                item = {**source, "markdown": chunk, "part": chunk_index + 1, "part_count": len(split_review_markdown(body) or [body])}
                item_length = len(chunk) + len(str(source.get("title") or "")) + 80
                if page_items and page_length + item_length > REVIEW_PAGE_CHARACTERS:
                    pages.append({"subject": subject["title"], "items": page_items, "character_count": page_length, "note_count": len({entry.get("section_id") for entry in page_items if entry.get("section_id")})})
                    page_items, page_length = [], 0
                page_items.append(item)
                page_length += item_length
        if page_items:
            pages.append({"subject": subject["title"], "items": page_items, "character_count": page_length, "note_count": len({entry.get("section_id") for entry in page_items if entry.get("section_id")})})
    for index, page in enumerate(pages):
        page["number"] = index + 1
    activity_day = effective_activity_payload(day, include_review=False)
    review_target, review_storage, review_uri = daily_review_target(date.today().isoformat())
    review_note = ""
    if review_target.is_file():
        try:
            review_note = review_target.read_text(encoding="utf-8-sig")
        except OSError:
            review_note = ""
    lines = [f"# {day} 学习回顾", "", "## 昨日概览", "", f"- 有效活动：{len(activity_day.get('activities', []))} 条", f"- 有效时长：{format_duration_text(activity_day.get('duration_seconds', 0))}"]
    for subject in subjects:
        lines.extend(["", f"## {DOMAIN_LABELS.get(subject['domain'], subject['domain'])} · {subject['title']}"])
        for source in subject["sources"]:
            lines.extend(["", f"### {source['source_label']} · {source['title']}", "", str(source.get("markdown") or "- 仅记录活动轨迹，不复制正文。")])
    if not subjects:
        lines.extend(["", "暂无可归档的学习产出；原始活动记录仍可从记录页查看。"])
    if summary:
        lines.extend(["", "## 本次回顾结果", "", summary])
    elif review_no_text:
        lines.extend(["", "## 本次回顾结果", "", "（已标记为无文本回顾。）"])
    record_target, record_storage, record_uri = daily_learning_record_target(day)
    domain_notes = extract_domain_note_items(sources)
    domain_stats = {
        "medicine": {
            "label": "医学",
            "duration_seconds": int((activity_day.get("by_domain") or {}).get("medicine") or 0),
            "note_count": len(domain_notes.get("medicine", [])),
        },
        "politics": {
            "label": "政治",
            "duration_seconds": int((activity_day.get("by_domain") or {}).get("politics") or 0),
            "note_count": len(domain_notes.get("politics", [])),
        },
        "english": {
            "label": "英语",
            "duration_seconds": int((activity_day.get("by_domain") or {}).get("english") or 0),
            "note_count": len(domain_notes.get("english", [])),
        },
    }
    ai_prompt = generate_review_ai_prompt(day, domain_notes)
    total_notes = sum(len(items) for items in domain_notes.values())
    result = {
        "review_date": day,
        "review_note_date": date.today().isoformat(),
        "note_count": sum(1 for source in sources if source.get("source_type") == "section_note"),
        "notes_by_domain": domain_notes,
        "domain_stats": domain_stats,
        "total_notes": total_notes,
        "ai_summary_prompt": ai_prompt,
        "source_count": len(sources),
        "subject_count": len(subjects),
        "page_count": len(pages),
        "pages": pages,
        "sources": sources,
        "subjects": subjects,
        "activity_count": len(activity_day.get("activities", [])),
        "duration_seconds": int(activity_day.get("duration_seconds") or 0),
        "activity_by_type": activity_day.get("by_activity_type", {}),
        "activity_by_domain": activity_day.get("by_domain", {}),
        "review_note": review_note,
        "review_note_characters": len(review_note.strip()),
        "review_storage": review_storage,
        "review_path": str(review_target),
        "obsidian_uri": review_uri,
        "completed_count": len(subjects) if review_done else sum(1 for subject in subjects if subject["completed"]),
        "all_complete": review_done or (bool(subjects) and all(subject["completed"] for subject in subjects)),
        "review_done": review_done,
        "review_no_text": review_no_text,
        "review_result": summary,
        "daily_summary": summary,
        "combined_markdown": "\n".join(lines).strip(),
        "log_storage": "local",
        "log_path": str(archive_target(day, "daily")[0]),
        "log_uri": archive_target(day, "daily")[2],
        "learning_record_storage": record_storage,
        "learning_record_path": str(record_target),
        "learning_record_uri": record_uri,
    }
    return result


def logs_payload(selected_day: str = "") -> dict:
    daily_files = archive_files("daily")
    learning_files = learning_record_files()
    all_days = set(daily_files) | set(learning_files)
    activity_payload = activity_records_payload()
    activity_records = coalesce_activity_records(activity_payload.get("activities", []))
    activity_by_day: dict[str, list[dict]] = {}
    for item in activity_records:
        if isinstance(item, dict):
            activity_by_day.setdefault(str(item.get("date") or ""), []).append(item)

    def activity_subject_count(day: str) -> int:
        return len(
            {
                _review_subject_key(item.get("domain"), item.get("subject_id") or item.get("resource_id"))
                for item in activity_by_day.get(day, [])
                if meaningful_activity(item)
            }
        )

    entries: list[dict] = []
    for day in sorted(all_days, reverse=True):
        path = learning_files.get(day) or daily_files.get(day)
        if not path:
            continue
        try:
            content = path.read_text(encoding="utf-8-sig").strip()
        except OSError:
            continue
        unified_result = unified_review_result(day) if day in learning_files else None
        legacy_state = load_workflow_state(day)
        results = legacy_state.get("subjects") if isinstance(legacy_state.get("subjects"), dict) else {}
        summary_text = str((unified_result or {}).get("summary") or "").strip() if unified_result is not None else str(legacy_state.get("summary") or "").strip()
        summary_preview = (summary_text[:100] + "…") if len(summary_text) > 100 else summary_text
        day_activities = activity_by_day.get(day, [])
        day_duration = sum(max(0, int(item.get("duration_seconds") or 0)) for item in day_activities if isinstance(item, dict))
        day_domains = {"medicine": 0, "politics": 0, "english": 0, "other": 0}
        for item in day_activities:
            if isinstance(item, dict):
                dom = str(item.get("domain") or "")
                dom_key = dom if dom in day_domains else "other"
                day_domains[dom_key] += max(0, int(item.get("duration_seconds") or 0))

        has_summary = bool(str((unified_result or {}).get("summary") or "").strip()) or bool((unified_result or {}).get("no_text"))
        if not has_summary:
            has_summary = bool(str(legacy_state.get("summary") or "").strip())

        entries.append(
            {
                "date": day,
                "subject_count": max(activity_subject_count(day), sum(1 for value in results.values() if str(value).strip())),
                "character_count": len(content),
                "duration_seconds": day_duration,
                "domain_totals": day_domains,
                "has_summary": has_summary,
                "summary_preview": summary_preview,
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
                "automatic": False,
                "legacy_available": day in daily_files,
                "source": "learning_record" if day in learning_files else "legacy_log",
                "unarchived": activity_subject_count(day) == 0 and bool(activity_by_day.get(day)),
            }
        )
    activity_days = {
        str(item.get("date"))
        for item in activity_records
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(item.get("date") or "")) and meaningful_activity(item)
    }
    raw_days = load_activity().get("days")
    if isinstance(raw_days, dict):
        activity_days.update(
            str(day)
            for day, value in raw_days.items()
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(day))
            and isinstance(value, dict)
            and meaningful_learning_day(value, activity_by_day.get(str(day), []))
        )
    for day in sorted(activity_days - all_days, reverse=True):
        entries.append(
            {
                "date": day,
                "subject_count": activity_subject_count(day),
                "character_count": 0,
                "has_summary": False,
                "updated_at": "",
                "automatic": True,
                "source": "activity_index",
                "unarchived": activity_subject_count(day) == 0,
            }
        )
    entries.sort(key=lambda item: str(item.get("date") or ""), reverse=True)
    detail = None
    if selected_day:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", selected_day):
            raise ValueError("invalid date")
        path = learning_files.get(selected_day)
        if path:
            target, storage, uri = daily_learning_record_target(selected_day)
            try:
                content = path.read_text(encoding="utf-8-sig")
            except OSError:
                content = ""
            legacy_path = daily_files.get(selected_day)
            legacy_content = ""
            if legacy_path:
                try:
                    legacy_content = legacy_path.read_text(encoding="utf-8-sig")
                except OSError:
                    legacy_content = ""
            detail = {
                "date": selected_day,
                "content": content,
                "storage": storage,
                "path": str(target),
                "obsidian_uri": uri,
                "legacy_available": bool(legacy_path),
                "legacy_path": str(archive_target(selected_day, "daily")[0]) if legacy_path else "",
                "legacy_content": legacy_content,
            }
        elif selected_day in daily_files:
            path = daily_files[selected_day]
            target, storage, uri = archive_target(selected_day, "daily")
            detail = {
                "date": selected_day,
                "content": path.read_text(encoding="utf-8-sig"),
                "storage": storage,
                "path": str(target),
                "obsidian_uri": uri,
                "legacy": True,
            }
        else:
            books, sections = catalog()
            review = review_payload(selected_day, books, sections)
            detail = {
                "date": selected_day,
                "content": daily_learning_record_markdown(review),
                "storage": review["learning_record_storage"],
                "path": review["learning_record_path"],
                "obsidian_uri": review["learning_record_uri"],
                "automatic": True,
                "legacy_available": False,
            }
    weekly_files = weekly_learning_record_files()
    legacy_weekly_files = archive_files("weekly")
    weekly_entries = []
    for week in sorted(set(weekly_files) | set(legacy_weekly_files), reverse=True):
        path = weekly_files.get(week) or legacy_weekly_files.get(week)
        try:
            content = path.read_text(encoding="utf-8-sig").strip()
        except OSError:
            continue
        weekly_entries.append(
            {
                "week": week,
                "character_count": len(content),
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
                "source": "learning_record" if week in weekly_files else "legacy_weekly_report",
                "legacy_available": week in legacy_weekly_files,
            }
        )
    return {"entries": entries, "weekly_entries": weekly_entries, "detail": detail}


def week_bounds(week: str) -> tuple[date, date]:
    match = re.fullmatch(r"(\d{4})-W(\d{2})", week)
    if not match:
        raise ValueError("invalid week")
    try:
        start = date.fromisocalendar(int(match.group(1)), int(match.group(2)), 1)
    except ValueError as error:
        raise ValueError("invalid week") from error
    return start, start + timedelta(days=6)


def _weekly_daily_record(day: str, activity_day: dict, summary: str) -> tuple[str, Path, str, str]:
    """Read or compose one compact daily record without exposing source bodies."""
    target, storage, uri = daily_learning_record_target(day)
    candidates = [target]
    local_target = DATA_DIR / "learning-records" / day[:4] / day[5:7] / f"{day}.md"
    if local_target not in candidates:
        candidates.append(local_target)
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            content = candidate.read_text(encoding="utf-8-sig").strip()
        except OSError:
            content = ""
        if content:
            return content, target, storage, uri

    # The weekly view is allowed to derive the selected seven days on demand.
    # This keeps the aggregate index authoritative while leaving all source
    # notes, answers, and old logs in their original files.
    try:
        books, sections = catalog()
        review = review_payload(day, books, sections)
        content = daily_learning_record_markdown(review)
    except (OSError, ValueError, KeyError, TypeError):
        content = ""
    if not content and (activity_day.get("activities") or summary):
        lines = [
            f"# {day} 学习记录",
            "",
            "## 当日概览",
            "",
            f"- 有效活动：{len(activity_day.get('activities') or [])} 条",
            f"- 有效时长：{format_duration_text(activity_day.get('duration_seconds', 0))}",
        ]
        if summary:
            lines.extend(["", "## 每日总述", "", summary])
        content = "\n".join(lines).strip()
    return content, target, storage, uri


def weekly_payload(week: str = "") -> dict:
    if not week:
        # Prefer the latest day with an activity, review, or legacy summary so
        # the weekly view remains useful before a physical daily log exists.
        candidate_days: set[str] = set()
        candidate_days.update(archive_files("daily"))
        candidate_days.update(learning_record_files())
        try:
            candidate_days.update(str(item.get("date") or "") for item in effective_activity_payload().get("activities", []))
        except (OSError, ValueError, KeyError, TypeError):
            pass
        raw_days = load_activity().get("days")
        if isinstance(raw_days, dict):
            candidate_days.update(str(day) for day, value in raw_days.items() if isinstance(value, dict))
        summarized_days = [
            day for day in candidate_days
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day)
            and (
                bool((unified_review_result(day) or {}).get("summary"))
                or bool((unified_review_result(day) or {}).get("no_text"))
                or bool(str(load_workflow_state(day).get("summary") or "").strip())
            )
        ]
        valid_candidates = [day for day in candidate_days if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day)]
        anchor_text = max(summarized_days or valid_candidates, default=date.today().isoformat())
        anchor = date.fromisoformat(anchor_text)
        year, number, _ = anchor.isocalendar()
        week = f"{year}-W{number:02d}"
    start, end = week_bounds(week)
    summaries = []
    daily_records = []
    weekly_type_totals = {activity_type: 0 for activity_type in sorted(ACTIVITY_TYPES)}
    weekly_domain_totals = {domain: 0 for domain in DOMAIN_LABELS}
    weekly_domain_totals["other"] = 0
    raw_days = load_activity().get("days")
    raw_days = raw_days if isinstance(raw_days, dict) else {}
    for offset in range(7):
        day = (start + timedelta(days=offset)).isoformat()
        unified_result = unified_review_result(day)
        workflow_summary = str(load_workflow_state(day).get("summary") or "").strip()
        daily_summary = str((unified_result or {}).get("summary") or "").strip() if unified_result is not None else workflow_summary
        if daily_summary:
            summaries.append({"date": day, "summary": daily_summary, "source": "learning_record" if unified_result is not None else "legacy_workflow"})
        activity_day = effective_activity_payload(day)
        raw_value = raw_days.get(day) if isinstance(raw_days.get(day), dict) else {}
        has_legacy_learning = meaningful_learning_day(raw_value, activity_day.get("activities", []))
        if not activity_day.get("activities") and not workflow_summary and not has_legacy_learning:
            continue
        content, record_path, record_storage, record_uri = _weekly_daily_record(day, activity_day, daily_summary)
        if not content:
            continue
        activity_items = activity_day.get("activities") if isinstance(activity_day.get("activities"), list) else []
        type_totals = {activity_type: 0 for activity_type in sorted(ACTIVITY_TYPES)}
        domain_totals = {domain: 0 for domain in DOMAIN_LABELS}
        domain_totals["other"] = 0
        for item in activity_items:
            if not isinstance(item, dict):
                continue
            seconds = max(0, int(item.get("duration_seconds") or 0))
            activity_type = str(item.get("activity_type") or "")
            if activity_type in type_totals:
                type_totals[activity_type] += seconds
                weekly_type_totals[activity_type] += seconds
            domain = str(item.get("domain") or "")
            domain_key = domain if domain in DOMAIN_LABELS else "other"
            domain_totals[domain_key] += seconds
            weekly_domain_totals[domain_key] += seconds
        read_seconds = type_totals["read"]
        daily_records.append(
            {
                "date": day,
                "content": content,
                "activity_count": len(activity_items),
                "duration_seconds": int(activity_day.get("duration_seconds") or 0),
                "activity_by_type": type_totals,
                "activity_by_domain": domain_totals,
                "legacy_unmapped_reading_seconds": max(0, int(raw_value.get("reading_seconds") or 0) - read_seconds),
                "record_path": str(record_path),
                "record_storage": record_storage,
                "record_uri": record_uri,
            }
        )
    state_path = REVIEW_WORKFLOW_DIR / f"{week}.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        state = {}
    legacy_report = str(state.get("summary") or "")
    weekly_files = weekly_learning_record_files()
    report_path = weekly_files.get(week)
    report = read_weekly_summary(report_path) if report_path else legacy_report
    source_lines = [f"# {week} 学习记录汇编"]
    for item in daily_records:
        source_lines.extend(["", f"## {item['date']}", "", item["content"] or "（当天仅保留活动索引。）"])
    source = "\n".join(source_lines)
    target, storage, uri = weekly_learning_record_target(week)

    total_duration_seconds = sum(item["duration_seconds"] for item in daily_records)
    total_hours = round(total_duration_seconds / 3600, 1)
    med_hours = round((weekly_domain_totals.get("medicine") or 0) / 3600, 1)
    pol_hours = round((weekly_domain_totals.get("politics") or 0) / 3600, 1)
    eng_hours = round((weekly_domain_totals.get("english") or 0) / 3600, 1)

    prompt_lines = [
        f"你是一位专业高效的考研深度学习顾问与知识架构师。以下是用户在【{week}】（{start.isoformat()} 至 {end.isoformat()}）的周期学习数据与各日复盘汇总：",
        "",
        f"- **总有效学时**：{total_hours} 小时（医学 {med_hours}h · 政治 {pol_hours}h · 英语 {eng_hours}h）",
        f"- **有效学习天数**：{len(daily_records)} 天 / 7 天",
        f"- **已完成复盘天数**：{len(summaries)} 天",
        "",
        "## 各日复盘与核心笔记沉淀："
    ]
    if summaries:
        for item in summaries:
            prompt_lines.extend([
                f"### 📅 {item['date']} 每日复盘：",
                str(item['summary']).strip(),
                ""
            ])
    else:
        prompt_lines.append("（本周主要进行了做题与通读，未保留独立日文字总结）")

    prompt_lines.extend([
        "",
        "---",
        "请根据上述全周学习轨迹与各日思考，为用户生成一份深刻、结构清晰且高度提炼的【周度知识织网与成长复盘周报】：",
        "1. **【本周全科知识脉络重构】**：提炼医学各系统、政治各专题、英语重难点的核心关联框架；",
        "2. **【薄弱盲点与高频遗忘项诊断】**：指出本周容易产生认知模糊、解题卡壳或需要重点回炉强化的环节；",
        "3. **【下周攻坚节奏与突破建议】**：给出具体到学科的下一阶段复习与做题侧重；",
        "请直接输出 Markdown 内容，语言干练犀利、富于学术洞见，适合直接沉淀为独立周报。"
    ])
    ai_weekly_prompt = "\n".join(prompt_lines)

    return {
        "week": week,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "day_count": len(daily_records),
        "summary_count": len(summaries),
        "summaries": summaries,
        "daily_records": [
            {key: value for key, value in item.items() if key != "content"}
            for item in daily_records
        ],
        "record_count": len(daily_records),
        "activity_count": sum(item["activity_count"] for item in daily_records),
        "duration_seconds": total_duration_seconds,
        "activity_by_type": weekly_type_totals,
        "activity_by_domain": weekly_domain_totals,
        "ai_weekly_prompt": ai_weekly_prompt,
        "source_markdown": source,
        "report": report,
        "legacy_report": legacy_report if report_path else "",
        "legacy_report_path": str(archive_target(week, "weekly")[0]) if legacy_report and report_path else "",
        "storage": storage,
        "path": str(target),
        "obsidian_uri": uri,
    }


