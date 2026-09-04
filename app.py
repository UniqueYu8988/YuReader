"""YuReader application server and router."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, quote, unquote, urlparse
from types import ModuleType

from yureader.config import (
    ROOT,
    CONTENT_DIR,
    QUESTION_BANK_DIR,
    DATA_DIR,
    NOTES_DIR,
    REVIEWS_DIR,
    REVIEW_WORKFLOW_DIR,
    LOGS_DIR,
    WEEKLY_DIR,
    ENGLISH_NOTEBOOK_DIR,
    SUBJECTIVE_DIR,
    ORAL_FOCUS_DIR,
    ORAL_FOCUS_CONTENT_PATH,
    ORAL_FOCUS_PROGRESS_PATH,
    ACTIVITY_PATH,
    ACTIVITY_SCHEMA_VERSION,
    ACTIVITY_TYPES,
    MIN_MEANINGFUL_ACTIVITY_SECONDS,
    STATIC_DIR,
    HOST,
    VERSION,
    REVIEW_PAGE_CHARACTERS,
    DOMAIN_LABELS,
    VALID_DOMAINS,
    RESOURCE_TYPE_LABELS,
    VALID_RESOURCE_TYPES,
    LEGACY_ROUTE_REDIRECTS,
    ACTIVITY_LOCK,
    CATALOG_LOCK,
    CATALOG_RECHECK_SECONDS,
    CATALOG_CACHE,
    QUESTION_BANK_LOCK,
    QUESTION_BANK_CACHE,
    PRACTICE_LOCK,
    ORAL_FOCUS_LOCK,
    ORAL_FOCUS_CACHE,
    BOOK_ASSETS,
)

from yureader.utils import (
    safe_domain,
    safe_resource_type,
    stable_id,
    first_title,
    starts_at_first_chapter,
    safe_note_component,
    atomic_write,
)

from yureader.catalog import (
    public_question_bank_title,
    sections_for,
    package_path,
    manifest_book,
    build_catalog,
    catalog_signature,
    catalog,
    question_bank_signature,
    build_question_bank_catalog,
    question_bank_catalog,
    question_bank_by_id,
    book_asset_path,
    section_aliases_path,
    load_section_aliases,
    resolve_section_id,
    section_aliases_for,
)

from yureader.obsidian import (
    obsidian_vault,
    note_path,
    dated_note_path,
    section_note_records,
    section_note_source,
    _display_data_path,
    unarchived_learning_records,
    section_note_target,
    section_note_markdown,
    ensure_section_note_mirror,
    daily_review_target,
    daily_learning_record_target,
    learning_record_files,
    weekly_learning_record_target,
    weekly_learning_record_files,
    archive_target,
    archive_files,
    review_note_files,
    english_notebook_target,
    english_notebook_files,
    english_notebook_payload,
)

from yureader.practice import (
    practice_path,
    load_practice_store,
    save_practice_store,
    load_bank_questions,
    public_question,
    matching_questions,
    chapter_knowledge_id,
    knowledge_namespace,
    practice_availability,
    practice_session,
    practice_unit_metadata,
    _english_exam_track_and_year,
    _english_subjective_specs,
    english_subjective_companion,
    _subjective_record,
    subjective_mode,
    subjective_response_path,
    load_subjective_response,
    subjective_response_target,
    subjective_response_markdown,
    subjective_practice,
    practice_overview,
    practice_question,
    practice_subject_label,
    practice_notes_target,
    write_practice_notes,
    mistakes_overview,
    resolve_mistake,
    create_mistakes_practice_session,
)

from yureader.search import global_search

from yureader.activity import (
    load_activity,
    activity_stable_id,
    _section_activity_context,
    _activity_output_ref,
    _activity_day,
    _question_activity_context,
    _activity_record,
    _migrate_legacy_activity_payload,
    migrate_activity_index,
    _record_activity,
    record_activity,
    activity_records_payload,
    coalesce_activity_records,
    meaningful_activity,
    completed_review_activity,
    meaningful_learning_day,
    effective_activity_payload,
    activity_resume_target,
    activity_home_summary,
    reading_time_payload,
    learning_stats,
    book_learning_summary,
)

from yureader.review import (
    record_review_activities,
    unified_review_result,
    read_weekly_summary,
    reviewable_learning_days,
    next_review_day,
    workflow_state_path,
    load_workflow_state,
    daily_log_markdown,
    split_review_markdown,
    _legacy_review_payload,
    _review_subject_key,
    _review_snippet,
    _english_notebook_day_markdown,
    review_source_records,
    daily_learning_record_markdown,
    format_duration_text,
    write_daily_learning_record,
    review_payload,
    logs_payload,
    week_bounds,
    _weekly_daily_record,
    weekly_payload,
)

from yureader.oral_focus import (
    load_oral_focus,
    load_oral_focus_progress,
    oral_focus_index_payload,
    _oral_focus_public_record,
    oral_focus_item_payload,
    oral_focus_chapter_payload,
    oral_focus_notes_target,
    write_oral_focus_notes,
    save_oral_focus_progress,
    oral_focus_due_items,
    oral_focus_due_session,
)

from yureader.goals import (
    load_goals,
    save_goals,
    daily_goals_payload,
)

from yureader.chapter_questions import get_chapter_questions

class ReaderHandler(BaseHTTPRequestHandler):
    server_version = f"YuReader/{VERSION}"

    def log_message(self, format: str, *args: object) -> None:
        return

    def send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def send_text(self, body: bytes, content_type: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        legacy_route = LEGACY_ROUTE_REDIRECTS.get(path)
        if legacy_route:
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", f"/#{legacy_route}")
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        if path == "/api/health":
            self.send_json({"ok": True, "name": "YuReader", "version": VERSION})
            return
        if path == "/api/daily-goals":
            try:
                day = str(parse_qs(parsed.query).get("day", [""])[0]).strip()
                self.send_json(daily_goals_payload(day))
            except ValueError as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/reading-time":
            try:
                query = parse_qs(parsed.query)
                requested_day = query.get("date", [""])[0]
                requested_days = int(query.get("days", ["1"])[0])
                self.send_json(reading_time_payload(requested_day, requested_days))
            except (ValueError, TypeError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/logs":
            try:
                requested = parse_qs(parsed.query).get("date", [""])[0]
                self.send_json(logs_payload(requested))
            except (ValueError, OSError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/weekly-report":
            try:
                requested = parse_qs(parsed.query).get("week", [""])[0]
                self.send_json(weekly_payload(requested))
            except (ValueError, OSError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/english-notebook":
            try:
                requested = parse_qs(parsed.query).get("week", [""])[0]
                self.send_json(english_notebook_payload(requested))
            except (ValueError, OSError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/oral-focus":
            try:
                self.send_json(oral_focus_index_payload())
            except (ValueError, OSError, json.JSONDecodeError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/oral-focus/item":
            try:
                query = parse_qs(parsed.query)
                reveal = query.get("reveal", ["0"])[0] in {"1", "true", "yes"}
                self.send_json(oral_focus_item_payload(query.get("item_id", [""])[0], reveal=reveal))
            except (ValueError, OSError, json.JSONDecodeError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/oral-focus/chapter":
            try:
                query = parse_qs(parsed.query)
                reveal = query.get("reveal", ["0"])[0] in {"1", "true", "yes"}
                self.send_json(
                    oral_focus_chapter_payload(
                        query.get("subject_id", [""])[0],
                        query.get("chapter_id", [""])[0],
                        query.get("type", [""])[0],
                        reveal=reveal,
                    )
                )
            except (ValueError, OSError, json.JSONDecodeError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/oral-focus/due":
            try:
                query = parse_qs(parsed.query)
                limit = int(query.get("limit", ["100"])[0])
                self.send_json(oral_focus_due_items(limit=limit))
            except (ValueError, OSError, json.JSONDecodeError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/oral-focus/due-session":
            try:
                query = parse_qs(parsed.query)
                limit = int(query.get("limit", ["50"])[0])
                self.send_json(oral_focus_due_session(limit=limit))
            except (ValueError, OSError, json.JSONDecodeError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        books, sections = catalog()
        if path == "/api/bootstrap":
            question_banks = question_bank_catalog()
            self.send_json(
                {
                    "books": books,
                    "question_banks": question_banks,
                    "question_bank_count": len(question_banks),
                    "section_count": len(sections),
                    "content_dir": str(CONTENT_DIR),
                }
            )
            return
        if path == "/api/question-banks":
            question_banks = question_bank_catalog()
            self.send_json({"banks": question_banks, "count": len(question_banks)})
            return
        if path == "/api/activities":
            try:
                query = parse_qs(parsed.query)
                requested_day = query.get("date", [""])[0]
                requested_type = query.get("activity_type", [""])[0]
                self.send_json(activity_records_payload(requested_day, requested_type))
            except (ValueError, OSError, json.JSONDecodeError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/practice/availability":
            try:
                query = parse_qs(parsed.query)
                self.send_json(practice_availability(query.get("book_id", [""])[0], query.get("section_id", [""])[0]))
            except (ValueError, OSError, json.JSONDecodeError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/practice/session":
            try:
                query = parse_qs(parsed.query)
                self.send_json(practice_session(query.get("bank_id", [""])[0], query.get("knowledge_id", [""])[0], query.get("match_level", [""])[0]))
            except (ValueError, OSError, json.JSONDecodeError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/practice/overview":
            try:
                query = parse_qs(parsed.query)
                self.send_json(practice_overview(query.get("bank_id", [""])[0]))
            except (ValueError, OSError, json.JSONDecodeError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/practice/question":
            try:
                query = parse_qs(parsed.query)
                self.send_json(practice_question(query.get("bank_id", [""])[0], query.get("question_id", [""])[0]))
            except (ValueError, OSError, json.JSONDecodeError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/subjective/practice":
            try:
                query = parse_qs(parsed.query)
                self.send_json(subjective_practice(query.get("section_id", [""])[0]))
            except (ValueError, OSError, json.JSONDecodeError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if path.rstrip("/") == "/api/practice/mistakes":
            try:
                query = parse_qs(parsed.query)
                domain = query.get("domain", [""])[0]
                self.send_json(mistakes_overview(domain))
            except (ValueError, OSError, json.JSONDecodeError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/practice/mistakes/session":
            try:
                query = parse_qs(parsed.query)
                domain = query.get("domain", [""])[0]
                self.send_json(create_mistakes_practice_session(domain))
            except (ValueError, OSError, json.JSONDecodeError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/search":
            try:
                query = parse_qs(parsed.query)
                q = query.get("q", [""])[0]
                category = query.get("category", [""])[0]
                self.send_json(global_search(q, category))
            except (ValueError, OSError, json.JSONDecodeError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/resource/"):
            resource_id = path.rsplit("/", 1)[-1]
            book = next((item for item in books if item["id"] == resource_id), None)
            if not book:
                self.send_json({"error": "resource not found"}, HTTPStatus.NOT_FOUND)
                return
            self.send_json({"book": book, "summary": book_learning_summary(book, sections)})
            return
        if path == "/api/stats":
            self.send_json(learning_stats(books, sections))
            return
        if path == "/api/unarchived":
            self.send_json(unarchived_learning_records(sections))
            return
        if path == "/api/reviews":
            try:
                requested = parse_qs(parsed.query).get("date", [""])[0]
                review_day = next_review_day(requested)
                self.send_json(review_payload(review_day, books, sections))
            except (ValueError, OSError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/sections/"):
            requested_section_id = path.rsplit("/", 1)[-1]
            section_id = resolve_section_id(requested_section_id, set(sections))
            section = sections.get(section_id or "")
            if not section:
                self.send_json({"error": "section not found"}, HTTPStatus.NOT_FOUND)
                return
            current_note = ""
            try:
                note_source = section_note_source(section["id"], sections)
                if note_source:
                    _canonical_id, note = note_source
                    if note.is_file():
                        current_note = note.read_text(encoding="utf-8-sig")
            except ValueError:
                pass
            book = next((item for item in books if any(entry["id"] == section["id"] for entry in item.get("sections", []))), None)
            note_storage, note_uri = "local", ""
            if book:
                _, note_storage, note_uri = ensure_section_note_mirror(book, section, current_note)
            book_id = section.get("book_id", "") or (book["id"] if book else "")
            chapter_title = section.get("chapter_title", "")
            chapter_questions = get_chapter_questions(book_id, chapter_title)
            self.send_json(
                {
                    **section,
                    "note": current_note,
                    "note_storage": note_storage,
                    "obsidian_uri": note_uri,
                    "requested_section_id": requested_section_id,
                    "resolved_from_alias": requested_section_id != section["id"],
                    "chapter_questions": chapter_questions,
                }
            )
            return
        if path.startswith("/api/book-assets/"):
            remaining = path[len("/api/book-assets/"):]
            parts = remaining.split("/", 1)
            if len(parts) != 2:
                self.send_json({"error": "invalid asset path"}, HTTPStatus.BAD_REQUEST)
                return
            book_id, asset_path = parts
            asset_file = book_asset_path(book_id, asset_path)
            if not asset_file:
                self.send_json({"error": "asset not found"}, HTTPStatus.NOT_FOUND)
                return
            content_type = "application/octet-stream"
            suffix = asset_file.suffix.lower()
            if suffix in {".jpg", ".jpeg"}:
                content_type = "image/jpeg"
            elif suffix == ".png":
                content_type = "image/png"
            elif suffix == ".webp":
                content_type = "image/webp"
            elif suffix == ".gif":
                content_type = "image/gif"
            elif suffix == ".svg":
                content_type = "image/svg+xml"
            try:
                self.send_text(asset_file.read_bytes(), content_type)
            except OSError:
                self.send_json({"error": "asset unreadable"}, HTTPStatus.NOT_FOUND)
            return
        if path == "/" or path == "/index.html":
            self.send_text((STATIC_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
            return
        relative = path.lstrip("/")
        candidate = (STATIC_DIR / relative).resolve()
        if STATIC_DIR in candidate.parents and candidate.is_file():
            content_type = "text/plain; charset=utf-8"
            if candidate.suffix == ".css":
                content_type = "text/css; charset=utf-8"
            elif candidate.suffix == ".js":
                content_type = "text/javascript; charset=utf-8"
            elif candidate.suffix == ".svg":
                content_type = "image/svg+xml"
            elif candidate.suffix == ".png":
                content_type = "image/png"
            elif candidate.suffix in {".jpg", ".jpeg"}:
                content_type = "image/jpeg"
            elif candidate.suffix == ".webp":
                content_type = "image/webp"
            self.send_text(candidate.read_bytes(), content_type)
            return
        self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path not in {"/api/notes", "/api/review-summary", "/api/weekly-summary", "/api/english-notebook", "/api/oral-focus/progress", "/api/activity", "/api/activity/heartbeat", "/api/reading-time", "/api/practice/answer", "/api/practice/analysis", "/api/practice/mistakes/resolve", "/api/subjective/response", "/api/daily-goals"}:
            self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            if parsed.path == "/api/daily-goals":
                self.send_json(save_goals(body))
                return
            if parsed.path == "/api/activity/heartbeat":
                activity_type = str(body.get("activity_type") or "").strip()
                if activity_type not in ACTIVITY_TYPES:
                    raise ValueError("invalid activity type")
                domain = str(body.get("domain") or "").strip().lower()
                if domain not in VALID_DOMAINS:
                    raise ValueError("invalid activity domain")
                subject_id = str(body.get("subject_id") or "").strip()
                resource_id = str(body.get("resource_id") or "").strip()
                item_id = str(body.get("item_id") or "").strip()
                if not subject_id or not resource_id or not item_id or len(subject_id) > 160 or len(resource_id) > 160 or len(item_id) > 160:
                    raise ValueError("activity context is incomplete")
                seconds = int(body.get("seconds") or 0)
                if seconds < 1 or seconds > 600:
                    raise ValueError("seconds must be between 1 and 600")
                idempotency_key = str(body.get("idempotency_key") or "").strip()
                if idempotency_key and (len(idempotency_key) > 160 or not re.fullmatch(r"[\w.-]+", idempotency_key)):
                    raise ValueError("invalid idempotency_key")
                resume_target = body.get("resume_target") if isinstance(body.get("resume_target"), dict) else {}
                context = {
                    "domain": domain,
                    "subject_id": subject_id,
                    "resource_id": resource_id,
                    "item_id": item_id,
                    "resume_target": resume_target,
                }
                activity_id = str(body.get("activity_id") or "").strip()
                if activity_id and (len(activity_id) > 160 or not re.fullmatch(r"[\w.-]+", activity_id)):
                    raise ValueError("invalid activity_id")
                recorded = record_activity(
                    activity_type,
                    reading_seconds=seconds,
                    activity_type=activity_type,
                    context=context,
                    activity_id=activity_id or activity_stable_id(date.today().isoformat(), activity_type, resource_id, item_id),
                    idempotency_key=idempotency_key,
                )
                self.send_json({"ok": True, "recorded": recorded, "activities": activity_records_payload(date.today().isoformat(), activity_type)["activities"]})
                return
            if parsed.path == "/api/oral-focus/progress":
                item_id = str(body.get("item_id") or "").strip()
                answer = str(body.get("answer") or "")
                memory_note = str(body.get("memory_note") or "")
                mastery = str(body.get("mastery") or "unseen").strip()
                eb_interval = int(body.get("eb_interval_days") or 1)
                item = oral_focus_item_payload(item_id)
                saved = save_oral_focus_progress(item_id, answer, memory_note, mastery, eb_interval)
                subject = item.get("subject") if isinstance(item.get("subject"), dict) else {}
                resource_id = f"oral-focus:{subject.get('id')}"
                has_output = bool(answer.strip() or memory_note.strip() or mastery != "unseen")
                record_activity(
                    "subjective_practice",
                    activity_type="subjective_practice",
                    context={
                        "domain": "medicine",
                        "subject_id": str(subject.get("title") or subject.get("id") or "口腔重点"),
                        "resource_id": resource_id,
                        "item_id": item_id,
                        "resume_target": {"view": "oral_focus", "resource_id": resource_id, "item_id": item_id},
                    },
                    activity_id=activity_stable_id(date.today().isoformat(), "subjective_practice", resource_id, item_id),
                    result_state="has_output" if has_output else "in_progress",
                    output_refs=[
                        _activity_output_ref("oral_focus_progress", item_id, ORAL_FOCUS_PROGRESS_PATH),
                        _activity_output_ref("oral_focus_note", item_id, saved["path"]),
                    ] if has_output else [],
                )
                self.send_json({"ok": True, **saved, "item": oral_focus_item_payload(item_id)})
                return
            if parsed.path == "/api/practice/mistakes/resolve":
                question_id = str(body.get("question_id") or "")
                resolved = bool(body.get("resolved", True))
                self.send_json(resolve_mistake(question_id, resolved))
                return
            if parsed.path == "/api/practice/answer":
                bank_id = str(body.get("bank_id") or "")
                question_id = str(body.get("question_id") or "")
                selected = body.get("selected_answers")
                if not isinstance(selected, list) or not selected:
                    raise ValueError("select at least one answer")
                question = None
                if bank_id and bank_id != "mistakes-session":
                    try:
                        question = next((item for item in load_bank_questions(bank_id) if item["question_id"] == question_id), None)
                    except Exception:
                        question = None
                if not question:
                    for candidate_bank in question_bank_catalog():
                        try:
                            found = next((item for item in load_bank_questions(candidate_bank["id"]) if item["question_id"] == question_id), None)
                            if found:
                                question = found
                                bank_id = candidate_bank["id"]
                                break
                        except Exception:
                            continue
                if not question:
                    raise ValueError("question not found")
                labels = {str(option.get("label")) for option in question.get("options") or [] if isinstance(option, dict)}
                selected_answers = sorted({str(item).strip() for item in selected if str(item).strip()})
                if not selected_answers or any(item not in labels for item in selected_answers):
                    raise ValueError("invalid selected answer")
                correct_answers = sorted(str(item) for item in question.get("correct_answers") or [])
                with PRACTICE_LOCK:
                    payload = load_practice_store("attempts")
                    items = payload.setdefault("items", {})
                    old_attempt = items.get(question_id, {})
                    is_correct = (selected_answers == correct_answers)
                    was_wrong = (old_attempt.get("correct") is False or bool(old_attempt.get("previously_wrong")))
                    items[question_id] = {
                        "bank_id": bank_id,
                        "selected_answers": selected_answers,
                        "correct": is_correct,
                        "previously_wrong": was_wrong,
                        "resolved": is_correct if was_wrong else bool(old_attempt.get("resolved")),
                        "answered_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    }
                    if is_correct and was_wrong:
                        items[question_id]["resolved_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
                    save_practice_store("attempts", payload)
                bank = question_bank_by_id(bank_id) or {}
                record_activity(
                    "objective_practice",
                    activity_type="objective_practice",
                    context={
                        "domain": safe_domain(bank.get("domain")),
                        "subject_id": str(question.get("subject_label") or bank.get("subject") or bank_id),
                        "resource_id": bank_id,
                        "item_id": question_id,
                        "resume_target": {"view": "practice", "resource_id": bank_id, "item_id": question_id, "question_id": question_id},
                    },
                    activity_id=activity_stable_id(date.today().isoformat(), "objective_practice", bank_id, question_id),
                    result_state="has_output",
                    output_refs=[_activity_output_ref("objective_attempt", question_id, practice_path("attempts"))],
                )
                self.send_json({"ok": True, "question": public_question(question, reveal=True), "attempt": load_practice_store("attempts")["items"][question_id]})
                return
            if parsed.path == "/api/practice/analysis":
                bank_id = str(body.get("bank_id") or "")
                question_id = str(body.get("question_id") or "")
                content = str(body.get("content") or "").replace("\r\n", "\n").strip()
                question = None
                if bank_id and bank_id != "mistakes-session":
                    try:
                        question = next((item for item in load_bank_questions(bank_id) if item["question_id"] == question_id), None)
                    except Exception:
                        question = None
                if not question:
                    for candidate_bank in question_bank_catalog():
                        try:
                            found = next((item for item in load_bank_questions(candidate_bank["id"]) if item["question_id"] == question_id), None)
                            if found:
                                question = found
                                bank_id = candidate_bank["id"]
                                break
                        except Exception:
                            continue
                if not question:
                    raise ValueError("question not found")
                with PRACTICE_LOCK:
                    payload = load_practice_store("analyses")
                    payload.setdefault("items", {})[question_id] = {"bank_id": bank_id, "content": content, "updated_at": datetime.now().astimezone().isoformat(timespec="seconds")}
                    save_practice_store("analyses", payload)
                    target, storage, uri = write_practice_notes(bank_id, str(question.get("subject_label") or ""))
                    bank = question_bank_by_id(bank_id) or {}
                    record_activity(
                        "objective_practice",
                        activity_type="objective_practice",
                        context={
                            "domain": safe_domain(bank.get("domain")),
                            "subject_id": str(question.get("subject_label") or bank.get("subject") or bank_id),
                            "resource_id": bank_id,
                            "item_id": question_id,
                            "resume_target": {"view": "practice", "resource_id": bank_id, "item_id": question_id, "question_id": question_id},
                        },
                        activity_id=activity_stable_id(date.today().isoformat(), "objective_practice", bank_id, question_id),
                        result_state="has_output" if content else "in_progress",
                        output_refs=[_activity_output_ref("personal_analysis", question_id, target)],
                    )
                self.send_json({"ok": True, "saved": bool(content), "path": str(target), "storage": storage, "obsidian_uri": uri})
                return
            if parsed.path == "/api/subjective/response":
                section_id = str(body.get("section_id") or "").strip()
                book, section, prompt_meta, _, _ = _subjective_record(section_id)
                answer = str(body.get("answer") or "").replace("\r\n", "\n").strip()
                reflection = str(body.get("reflection") or "").replace("\r\n", "\n").strip()
                if len(answer) > 120000 or len(reflection) > 50000:
                    raise ValueError("subjective response is too long")
                mode = subjective_mode(prompt_meta, section)
                payload = {
                    "schema_version": 1,
                    "section_id": section_id,
                    "book_id": book["id"],
                    "mode": mode,
                    "answer": answer,
                    "reflection": reflection,
                    "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                }
                with PRACTICE_LOCK:
                    atomic_write(subjective_response_path(section_id), json.dumps(payload, ensure_ascii=False, indent=2))
                    target, storage, uri = subjective_response_target(book, section)
                    atomic_write(target, subjective_response_markdown(book, section, mode, answer, reflection))
                    record_activity(
                        "subjective_practice",
                        activity_type="subjective_practice",
                        context={
                            "domain": safe_domain(book.get("domain")),
                            "subject_id": str(book.get("subject") or book.get("id") or ""),
                            "resource_id": str(book.get("id") or ""),
                            "item_id": section_id,
                            "resume_target": {"view": "subjective_practice", "resource_id": str(book.get("id") or ""), "item_id": section_id},
                        },
                        activity_id=activity_stable_id(date.today().isoformat(), "subjective_practice", book.get("id"), section_id),
                        result_state="has_output" if answer or reflection else "in_progress",
                        output_refs=[
                            _activity_output_ref("subjective_response", section_id, subjective_response_path(section_id)),
                            _activity_output_ref("subjective_note", section_id, target),
                        ] if answer or reflection else [],
                    )
                self.send_json({"ok": True, "saved": bool(answer or reflection), "response": payload, "path": str(target), "storage": storage, "obsidian_uri": uri})
                return
            if parsed.path == "/api/review-summary":
                review_day = str(body.get("date") or "")
                books, sections = catalog()
                review = review_payload(review_day, books, sections)
                content = str(body.get("content") or "").replace("\r\n", "\n").strip()
                draft = {**review, "review_result": content, "daily_summary": content, "review_no_text": bool(body.get("no_text")) and not content}
                target, storage, uri, _record_content = write_daily_learning_record(draft)
                refreshed = review_payload(review_day, books, sections)
                if refreshed["review_done"]:
                    record_review_activities(refreshed, target)
                self.send_json({"ok": True, "review": refreshed, "storage": storage, "path": str(target), "obsidian_uri": uri})
                return
            if parsed.path == "/api/weekly-summary":
                requested_week = str(body.get("week") or "")
                content = str(body.get("content") or "").replace("\r\n", "\n").strip()
                payload = weekly_payload(requested_week)
                week = payload["week"]
                target, storage, uri = weekly_learning_record_target(week)
                lines = [f"# {week} 周报"]
                if content:
                    lines.extend(["", "## 阶段总结", "", content])
                if payload["summaries"]:
                    lines.extend(["", "## 每日总结"])
                    for item in payload["summaries"]:
                        lines.extend(["", f"### {item['date']}", "", item["summary"]])
                atomic_write(target, "\n".join(lines))
                self.send_json({"ok": True, "week": week, "saved": bool(content), "storage": storage, "path": str(target), "obsidian_uri": uri})
                return
            if parsed.path == "/api/english-notebook":
                week = str(body.get("week") or "")
                if not week:
                    current_year, current_number, _ = date.today().isocalendar()
                    week = f"{current_year}-W{current_number:02d}"
                content = str(body.get("content") or "").replace("\r\n", "\n").strip()
                target, storage, uri = english_notebook_target(week)
                atomic_write(target, content)
                payload = english_notebook_payload(week)
                record_activity(
                    "notebook",
                    activity_type="notebook",
                    context={
                        "domain": "english",
                        "subject_id": "english-notebook",
                        "resource_id": "english-notebook",
                        "item_id": week,
                        "resume_target": {"view": "english_notebook", "resource_id": "english-notebook", "item_id": week},
                    },
                    activity_id=activity_stable_id(date.today().isoformat(), "notebook", week),
                    result_state="has_output" if content else "in_progress",
                    output_refs=[_activity_output_ref("english_notebook", week, target)] if content else [],
                )
                self.send_json({"ok": True, "saved": bool(content), **payload})
                return
            if parsed.path == "/api/reading-time":
                section_id = str(body.get("section_id") or "").strip()
                seconds = int(body.get("seconds") or 0)
                if not section_id or len(section_id) > 160 or not re.fullmatch(r"[\w.-]+", section_id):
                    raise ValueError("invalid section_id")
                if seconds < 1 or seconds > 600:
                    raise ValueError("seconds must be between 1 and 600")
                idempotency_key = str(body.get("idempotency_key") or "").strip()
                if idempotency_key and (len(idempotency_key) > 160 or not re.fullmatch(r"[\w.-]+", idempotency_key)):
                    raise ValueError("invalid idempotency_key")
                recorded = record_activity("reading_time", section_id, reading_seconds=seconds, idempotency_key=idempotency_key)
                self.send_json({"ok": True, "recorded": recorded, "seconds": seconds, "today": reading_time_payload()})
                return
            if parsed.path == "/api/activity":
                section_id = str(body.get("section_id") or "")
                _, sections = catalog()
                if section_id not in sections:
                    raise ValueError("section not found")
                record_activity("section_open", section_id)
                self.send_json({"ok": True, "section_id": section_id})
                return
            section_id = str(body.get("section_id") or "")
            content = str(body.get("content") or "").replace("\r\n", "\n").strip()
            books, sections = catalog()
            if section_id not in sections:
                raise ValueError("section not found")
            section = sections[section_id]
            book = next((item for item in books if any(entry["id"] == section_id for entry in item.get("sections", []))), None)
            if not book:
                raise ValueError("book not found")
            atomic_write(note_path(section_id), content)
            target, storage, uri = section_note_target(book, section)
            if storage == "obsidian":
                atomic_write(target, section_note_markdown(book, section, content))
            record_activity("note_save", section_id, len(content))
            self.send_json({"ok": True, "saved": bool(content), "section_id": section_id, "storage": storage, "path": str(target), "obsidian_uri": uri})
        except (ValueError, json.JSONDecodeError, OSError) as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)


def main() -> None:
    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, int(os.environ.get("YUREADER_PORT", "8775"))), ReaderHandler)
    url = f"http://{HOST}:{server.server_port}"
    print(f"YuReader is running at {url}")
    server.serve_forever()


if __name__ == "__main__":
    main()

class _AppModule(ModuleType):
    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        for mod_name in (
            "yureader.config",
            "yureader.catalog",
            "yureader.obsidian",
            "yureader.practice",
            "yureader.activity",
            "yureader.review",
            "yureader.oral_focus",
            "yureader.goals",
        ):
            mod = sys.modules.get(mod_name)
            if mod is not None and hasattr(mod, name):
                setattr(mod, name, value)

sys.modules[__name__].__class__ = _AppModule
