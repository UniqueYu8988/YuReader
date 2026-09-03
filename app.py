"""YuReader: a local, manifest-aware Markdown reader."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import date, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, quote, unquote, urlparse

from yureader.utils import (
    atomic_write,
    first_title,
    safe_domain,
    safe_note_component,
    safe_resource_type,
    stable_id,
    starts_at_first_chapter,
)


ROOT = Path(__file__).resolve().parent
CONTENT_DIR = Path(os.environ.get("YUREADER_CONTENT_DIR", ROOT / "content")).resolve()
QUESTION_BANK_DIR = Path(os.environ.get("YUREADER_QUESTION_BANK_DIR", ROOT / "question-banks")).resolve()
DATA_DIR = Path(os.environ.get("YUREADER_DATA_DIR", ROOT / "data")).resolve()
NOTES_DIR = DATA_DIR / "notes"
REVIEWS_DIR = DATA_DIR / "reviews"
REVIEW_WORKFLOW_DIR = DATA_DIR / "review-workflow"
LOGS_DIR = DATA_DIR / "logs"
WEEKLY_DIR = DATA_DIR / "weekly-reports"
ENGLISH_NOTEBOOK_DIR = DATA_DIR / "english-weekly"
SUBJECTIVE_DIR = DATA_DIR / "subjective"
ORAL_FOCUS_DIR = DATA_DIR / "oral-focus"
ORAL_FOCUS_CONTENT_PATH = ORAL_FOCUS_DIR / "content.json"
ORAL_FOCUS_PROGRESS_PATH = ORAL_FOCUS_DIR / "progress.json"
ACTIVITY_PATH = DATA_DIR / "activity.json"
ACTIVITY_SCHEMA_VERSION = 3
ACTIVITY_TYPES = {"read", "objective_practice", "subjective_practice", "notebook", "review"}
MIN_MEANINGFUL_ACTIVITY_SECONDS = 60
STATIC_DIR = ROOT / "static"
HOST = "127.0.0.1"
VERSION = "0.12.0"
REVIEW_PAGE_CHARACTERS = 5000
DOMAIN_LABELS = {"medicine": "医学", "politics": "政治", "english": "英语"}
VALID_DOMAINS = set(DOMAIN_LABELS)
RESOURCE_TYPE_LABELS = {"book": "教材", "lecture": "讲义", "question_bank": "题库", "reference": "参考资料"}
VALID_RESOURCE_TYPES = set(RESOURCE_TYPE_LABELS)
LEGACY_ROUTE_REDIRECTS = {
    "/home": "today",
    "/dashboard": "today",
    "/library": "library",
    "/books": "library",
    "/bookshelf": "library",
    "/shelf": "library",
    "/review": "review",
    "/reviews": "review",
    "/yesterday-review": "review",
    "/logs": "records",
    "/log": "records",
    "/records": "records",
    "/stats": "records/stats",
    "/statistics": "records/stats",
}
ACTIVITY_LOCK = Lock()
CATALOG_LOCK = Lock()
CATALOG_RECHECK_SECONDS = 2.0
CATALOG_CACHE: dict = {
    "checked_at": 0.0,
    "signature": None,
    "books": [],
    "sections": {},
}
QUESTION_BANK_LOCK = Lock()
QUESTION_BANK_CACHE: dict = {
    "checked_at": 0.0,
    "signature": None,
    "banks": [],
}
PRACTICE_LOCK = Lock()
ORAL_FOCUS_LOCK = Lock()
ORAL_FOCUS_CACHE: dict = {"mtime_ns": None, "payload": None, "items": {}}
# Read-only image assets are served per published book package.  BOOK_ASSETS
# records the manifest-declared asset names and SHA-256 file list for each
# book_id so the /api/book-assets endpoint can only expose files that a
# published package explicitly declares.  Keys are book ids.
BOOK_ASSETS: dict[str, dict] = {}


def public_question_bank_title(title: object, bank_id: str, subject: object = "", domain: object = "") -> str:
    """Return a stable reader-facing title for a published question bank.

    Candidate builders sometimes retain markers such as ``（候选）`` or
    ``客观题候选包`` in the source title. Once a package has passed the
    runtime validator and is published, those workflow markers should not be
    shown as if they were part of the exam name. Keep non-English and
    non-exam banks untouched so this remains a display normalization rather
    than a content rewrite.
    """
    value = str(title or bank_id).strip() or bank_id
    if safe_domain(domain) != "english":
        return value
    exam_id = re.fullmatch(r"english-(?:(\d{4})-e([12])|e([12])-(\d{4}))", str(bank_id))
    if exam_id:
        year = exam_id.group(1) or exam_id.group(4)
        track = exam_id.group(2) or exam_id.group(3)
        return f"{year} 年考研英语{'二' if track == '2' else '一'}真题"
    return re.sub(r"\s*(?:（候选）|\(候选\)|客观题候选包)\s*$", "", value).strip() or value


def sections_for(path: Path) -> list[dict]:
    relative = path.relative_to(CONTENT_DIR).as_posix()
    markdown = path.read_text(encoding="utf-8-sig")
    matches = list(re.finditer(r"^(#{1,6})\s+(.+?)\s*$", markdown, re.MULTILINE))
    selected = [match for match in matches if len(match.group(1)) >= 2]
    if not selected:
        selected = [None]

    result: list[dict] = []
    for index, match in enumerate(selected):
        start = match.start() if match else 0
        end = selected[index + 1].start() if index + 1 < len(selected) and selected[index + 1] else len(markdown)
        title = match.group(2).strip() if match else path.stem
        fragment = markdown[start:end].strip()
        result.append(
            {
                "id": stable_id(relative, start),
                "title": title,
                "level": len(match.group(1)) if match else 1,
                "book_title": first_title(markdown, path.stem),
                "path": relative,
                "markdown": fragment,
            }
        )
    return result


def package_path(package_dir: Path, relative: str) -> Path:
    candidate = (package_dir / relative).resolve()
    if candidate != package_dir and package_dir not in candidate.parents:
        raise ValueError("artifact escapes book package")
    return candidate


def manifest_book(manifest_path: Path) -> tuple[dict, dict[str, dict]] | None:
    """Load one validated published package without trusting external paths."""
    package_dir = manifest_path.parent.resolve()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        book_meta = manifest["book"]
        quality = manifest["quality"]
        if (
            manifest.get("schema_version") not in {1, 2}
            or book_meta.get("status") != "ready"
            or int(quality.get("blocker_count", 1)) != 0
        ):
            return None
        toc_entries = manifest.get("toc")
        if not isinstance(toc_entries, list) or not toc_entries:
            return None
        first_toc_title = toc_entries[0].get("title") if isinstance(toc_entries[0], dict) else ""
        if not starts_at_first_chapter(str(first_toc_title or "")):
            return None
        book_id = str(book_meta["id"])
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", book_id):
            return None

        # Register manifest-declared image assets so /api/book-assets can only
        # serve files the published package explicitly declares.  Legacy
        # packages without an assets contract register nothing.
        asset_names = [str(item) for item in manifest.get("assets") or []]
        asset_integrity = manifest.get("asset_integrity") if isinstance(manifest.get("asset_integrity"), dict) else {}
        if asset_names:
            integrity_files = asset_integrity.get("files")
            integrity_paths = {
                str(item.get("path")) for item in integrity_files if isinstance(item, dict) and isinstance(item.get("path"), str)
            } if isinstance(integrity_files, list) else set()
            BOOK_ASSETS[book_id] = {
                "package_dir": str(package_dir),
                "asset_root": str(manifest.get("assets_root") or "images"),
                "names": set(asset_names),
                "integrity_paths": integrity_paths,
            }

        knowledge_ids: list[str] = []
        page_knowledge_ids: dict[str, list[str]] = {}
        knowledge_map_path = package_dir / "knowledge-map.json"
        if knowledge_map_path.is_file():
            try:
                knowledge_payload = json.loads(knowledge_map_path.read_text(encoding="utf-8-sig"))
                km_entries = knowledge_payload.get("entries") if isinstance(knowledge_payload, dict) else None
                if isinstance(km_entries, list):
                    knowledge_ids = [
                        str(item.get("knowledge_id"))
                        for item in km_entries
                        if isinstance(item, dict) and isinstance(item.get("knowledge_id"), str)
                    ]
                    for item in km_entries:
                        if not isinstance(item, dict) or not isinstance(item.get("knowledge_id"), str):
                            continue
                        for page_id in item.get("page_ids") or []:
                            if isinstance(page_id, str):
                                page_knowledge_ids.setdefault(page_id, []).append(item["knowledge_id"])
            except (OSError, json.JSONDecodeError, ValueError):
                knowledge_ids = []

        book_title = str(book_meta["title"])
        book = {
            "asset_count": len(asset_names),
            "knowledge_ids": knowledge_ids,
            "id": book_id,
            "title": book_title,
            "edition": str(book_meta.get("edition") or ""),
            "domain": safe_domain(book_meta.get("domain")),
            "domain_label": DOMAIN_LABELS[safe_domain(book_meta.get("domain"))],
            "subject": str(book_meta.get("subject") or "").strip() or book_title,
            "resource_type": safe_resource_type(book_meta.get("resource_type")),
            "resource_type_label": RESOURCE_TYPE_LABELS[safe_resource_type(book_meta.get("resource_type"))],
            "sections": [],
            "toc": [],
            "source_files": 0,
            "material_kind": str(book_meta.get("default_material") or "cleaned"),
            "quality": {
                "status": str(quality.get("status") or "unknown"),
                "warning_count": int(quality.get("warning_count") or 0),
            },
            "reading_layout": manifest.get("reading_layout") or {},
        }
        loaded: dict[str, dict] = {}
        manifest_sections = manifest.get("sections") or manifest.get("chapters", [])
        for chapter in sorted(manifest_sections, key=lambda item: int(item["order"])):
            artifact = str(chapter["artifact"])
            source = package_path(package_dir, artifact)
            if not source.is_file():
                return None
            expected_hash = str(chapter.get("sha256") or "").lower()
            if expected_hash and hashlib.sha256(source.read_bytes()).hexdigest() != expected_hash:
                return None
            section_id = str(chapter["id"])
            if not re.fullmatch(r"[0-9a-f]{12}", section_id) or section_id in loaded:
                return None
            markdown = source.read_text(encoding="utf-8-sig").strip()
            if not markdown:
                return None
            entry = {
                "id": section_id,
                "book_id": book_id,
                "title": str(chapter["title"]),
                "level": int(chapter.get("level") or 1),
                "book_title": book["title"],
                "path": f"{book_id}/{artifact}",
                "markdown": markdown,
                "material_kind": str(chapter.get("material_kind") or "cleaned"),
                "source_map": chapter.get("source_map") or {},
                "quality": book["quality"],
                "chapter_id": str(chapter.get("chapter_id") or ""),
                "chapter_title": str(chapter.get("chapter_title") or ""),
                "chapter_order": int(chapter.get("chapter_order") or 0),
                "section_order": int(chapter.get("section_order") or chapter.get("order") or 0),
                "character_count": int(chapter.get("character_count") or len(markdown)),
                "knowledge_ids": page_knowledge_ids.get(str(chapter.get("key") or ""), []),
            }
            loaded[section_id] = entry
            book["sections"].append(
                {
                    "id": section_id,
                    "title": entry["title"],
                    "level": entry["level"],
                    "material_kind": entry["material_kind"],
                    "chapter_id": entry["chapter_id"],
                    "chapter_title": entry["chapter_title"],
                    "chapter_order": entry["chapter_order"],
                    "section_order": entry["section_order"],
                    "character_count": entry["character_count"],
                    "knowledge_ids": entry["knowledge_ids"],
                }
            )
        section_summaries = {item["id"]: item for item in book["sections"]}
        for toc_entry in sorted(toc_entries, key=lambda item: int(item["order"])):
            toc_sections = [
                section_summaries[section_id]
                for section_id in toc_entry.get("section_ids", [])
                if section_id in section_summaries
            ]
            if toc_sections:
                book["toc"].append(
                    {
                        "id": str(toc_entry["id"]),
                        "order": int(toc_entry["order"]),
                        "title": str(toc_entry["title"]),
                        "sections": toc_sections,
                    }
                )
        book["source_files"] = len(book["sections"])
        return (book, loaded) if loaded else None
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
        return None


def build_catalog() -> tuple[list[dict], dict[str, dict]]:
    BOOK_ASSETS.clear()
    books: dict[str, dict] = {}
    sections: dict[str, dict] = {}
    if not CONTENT_DIR.is_dir():
        return [], sections

    package_roots: set[Path] = set()
    for manifest_path in sorted(CONTENT_DIR.glob("*/manifest.json")):
        loaded = manifest_book(manifest_path)
        if not loaded:
            continue
        book, package_sections = loaded
        books[book["id"]] = book
        sections.update(package_sections)
        package_roots.add(manifest_path.parent.resolve())

    for path in sorted(CONTENT_DIR.rglob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        resolved = path.resolve()
        if any(root == resolved.parent or root in resolved.parents for root in package_roots):
            continue
        relative = path.relative_to(CONTENT_DIR)
        book_key = relative.parts[0] if len(relative.parts) > 1 else path.stem
        book = books.setdefault(
            book_key,
            {
                "id": book_key,
                "title": book_key,
                "domain": "medicine",
                "domain_label": DOMAIN_LABELS["medicine"],
                "subject": book_key,
                "resource_type": "book",
                "resource_type_label": RESOURCE_TYPE_LABELS["book"],
                "sections": [],
                "source_files": 0,
            },
        )
        book["source_files"] += 1
        entries = sections_for(path)
        if entries:
            book["title"] = entries[0]["book_title"] or book["title"]
        for entry in entries:
            sections[entry["id"]] = entry
            book["sections"].append(
                {"id": entry["id"], "title": entry["title"], "level": entry["level"]}
            )
    return list(books.values()), sections


def catalog_signature() -> tuple[tuple[str, int, int], ...]:
    """Track published content cheaply without rereading or hashing every section."""
    if not CONTENT_DIR.is_dir():
        return ()
    records: list[tuple[str, int, int]] = []
    for path in CONTENT_DIR.rglob("*"):
        if not path.is_file() or (path.name != "manifest.json" and path.suffix.lower() != ".md"):
            continue
        try:
            stat = path.stat()
            records.append((path.relative_to(CONTENT_DIR).as_posix(), stat.st_size, stat.st_mtime_ns))
        except OSError:
            continue
    return tuple(sorted(records))


def catalog() -> tuple[list[dict], dict[str, dict]]:
    """Reuse the validated catalog and invalidate it shortly after source changes."""
    now = time.monotonic()
    with CATALOG_LOCK:
        if CATALOG_CACHE["signature"] is not None and now - CATALOG_CACHE["checked_at"] < CATALOG_RECHECK_SECONDS:
            return CATALOG_CACHE["books"], CATALOG_CACHE["sections"]

        signature = catalog_signature()
        if signature == CATALOG_CACHE["signature"]:
            CATALOG_CACHE["checked_at"] = now
            return CATALOG_CACHE["books"], CATALOG_CACHE["sections"]

        books, sections = build_catalog()
        CATALOG_CACHE.update(
            checked_at=time.monotonic(),
            signature=signature,
            books=books,
            sections=sections,
        )
        return books, sections


def question_bank_signature() -> tuple[tuple[str, int, int], ...]:
    """Track published question-bank content cheaply without hashing all questions."""
    if not QUESTION_BANK_DIR.is_dir():
        return ()
    records: list[tuple[str, int, int]] = []
    for path in QUESTION_BANK_DIR.rglob("*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
            records.append((path.relative_to(QUESTION_BANK_DIR).as_posix(), stat.st_size, stat.st_mtime_ns))
        except OSError:
            continue
    return tuple(sorted(records))


def build_question_bank_catalog() -> list[dict]:
    """Build a read-only runtime index of published question banks.

    Only manifest-declared, ready question banks are listed.  The index exposes
    real metadata (title, domain, subject, counts, knowledge_ids) so the app can
    distinguish ``lecture`` packages under content/ from ``question_bank``
    packages under the question-bank runtime root without fuzzy matching.
    Quarantined questions are never counted as formal questions here.
    """
    if not QUESTION_BANK_DIR.is_dir():
        return []
    banks: list[dict] = []
    for manifest_path in sorted(QUESTION_BANK_DIR.glob("*/manifest.json")):
        # Atomic question-bank replacement keeps hidden ``.backup-*`` and
        # ``.import-releases`` artifacts beside the live bank.  They are
        # recovery/provenance data, never runtime catalog entries.
        if manifest_path.parent.name.startswith("."):
            continue
        package_dir = manifest_path.parent.resolve()
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            bank = manifest.get("bank") if isinstance(manifest.get("bank"), dict) else {}
            bank_id = str(bank.get("id") or "")
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", bank_id):
                continue
            if manifest_path.parent.name != bank_id:
                continue
            if str(bank.get("status") or "") != "ready":
                continue
            if manifest.get("schema_version") != 1:
                continue
            quality = manifest.get("quality") if isinstance(manifest.get("quality"), dict) else {}
            question_count = int(manifest.get("question_count") or 0)
            quarantined_count = int(manifest.get("quarantined_count") or 0)
            type_counts = manifest.get("question_type_counts") if isinstance(manifest.get("question_type_counts"), dict) else {}
            difficulty_counts = manifest.get("difficulty_counts") if isinstance(manifest.get("difficulty_counts"), dict) else {}
            scope_counts = manifest.get("scope_counts") if isinstance(manifest.get("scope_counts"), dict) else {}
            questions_decl = manifest.get("questions") if isinstance(manifest.get("questions"), dict) else {}
            km_decl = manifest.get("knowledge_map") if isinstance(manifest.get("knowledge_map"), dict) else {}
            source_index_decl = manifest.get("source_index") if isinstance(manifest.get("source_index"), dict) else {}
            coverage = manifest.get("coverage") if isinstance(manifest.get("coverage"), dict) else {}
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue

        knowledge_ids: list[str] = []
        knowledge_map_entries = 0
        try:
            km_path = package_dir / str(km_decl.get("path") or "knowledge-map.json")
            km_payload = json.loads(km_path.read_text(encoding="utf-8-sig"))
            km_entries = km_payload.get("entries") if isinstance(km_payload, dict) else None
            if isinstance(km_entries, list):
                knowledge_map_entries = len(km_entries)
                knowledge_ids = [
                    str(item.get("knowledge_id"))
                    for item in km_entries
                    if isinstance(item, dict) and isinstance(item.get("knowledge_id"), str)
                ]
        except (OSError, json.JSONDecodeError, ValueError):
            pass

        source_blocks_total = 0
        try:
            si_path = package_dir / str(source_index_decl.get("path") or "source-index.json")
            si_payload = json.loads(si_path.read_text(encoding="utf-8-sig"))
            for source in (si_payload.get("sources") or []) if isinstance(si_payload, dict) else []:
                if isinstance(source, dict) and isinstance(source.get("blocks"), list):
                    source_blocks_total += len(source["blocks"])
        except (OSError, json.JSONDecodeError, ValueError):
            pass

        banks.append(
            {
                "id": bank_id,
                "title": public_question_bank_title(bank.get("title"), bank_id, bank.get("subject"), bank.get("domain")),
                "domain": safe_domain(bank.get("domain")),
                "domain_label": DOMAIN_LABELS[safe_domain(bank.get("domain"))],
                "subject": str(bank.get("subject") or bank_id),
                "resource_type": "question_bank",
                "resource_type_label": RESOURCE_TYPE_LABELS["question_bank"],
                "status": "ready",
                "question_count": question_count,
                "quarantined_count": quarantined_count,
                "question_type_counts": type_counts,
                "difficulty_counts": difficulty_counts,
                "scope_counts": scope_counts,
                "knowledge_map_entries": knowledge_map_entries,
                "source_blocks_total": source_blocks_total,
                "knowledge_ids": knowledge_ids,
                "sources": [str(item.get("source_id") or "") for item in (manifest.get("sources") or []) if isinstance(item, dict)],
                "questions_sha256": str(questions_decl.get("sha256") or ""),
                "knowledge_map_sha256": str(km_decl.get("sha256") or ""),
                "source_index_sha256": str(source_index_decl.get("sha256") or ""),
                "quality": {
                    "status": str(quality.get("status") or "unknown"),
                    "blocker_count": int(quality.get("blocker_count") or 0),
                    "warning_count": int(quality.get("warning_count") or 0),
                },
                "test_count": manifest.get("test_count") if isinstance(manifest.get("test_count"), int) else None,
                "generated_at": str(manifest.get("generated_at") or ""),
                "coverage": coverage,
                "path": manifest_path.parent.relative_to(QUESTION_BANK_DIR).as_posix(),
            }
        )
    return banks


def question_bank_catalog() -> list[dict]:
    """Reuse the validated question-bank index and invalidate it shortly after changes."""
    now = time.monotonic()
    with QUESTION_BANK_LOCK:
        if QUESTION_BANK_CACHE["signature"] is not None and now - QUESTION_BANK_CACHE["checked_at"] < CATALOG_RECHECK_SECONDS:
            return QUESTION_BANK_CACHE["banks"]
        signature = question_bank_signature()
        if signature == QUESTION_BANK_CACHE["signature"]:
            QUESTION_BANK_CACHE["checked_at"] = now
            return QUESTION_BANK_CACHE["banks"]
        banks = build_question_bank_catalog()
        QUESTION_BANK_CACHE.update(checked_at=now, signature=signature, banks=banks)
        return banks


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


def question_bank_by_id(bank_id: str) -> dict | None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", bank_id):
        return None
    return next((bank for bank in question_bank_catalog() if bank["id"] == bank_id), None)


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


def load_oral_focus() -> tuple[dict, dict[str, dict]]:
    """Load the ignored local focus dataset and index items without mutating it."""
    if not ORAL_FOCUS_CONTENT_PATH.is_file():
        return {"schema_version": 1, "summary": {}, "subjects": []}, {}
    mtime_ns = ORAL_FOCUS_CONTENT_PATH.stat().st_mtime_ns
    if ORAL_FOCUS_CACHE.get("mtime_ns") == mtime_ns and isinstance(ORAL_FOCUS_CACHE.get("payload"), dict):
        return ORAL_FOCUS_CACHE["payload"], ORAL_FOCUS_CACHE.get("items", {})
    payload = json.loads(ORAL_FOCUS_CONTENT_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or int(payload.get("schema_version") or 0) != 1 or not isinstance(payload.get("subjects"), list):
        raise ValueError("invalid oral focus dataset")
    items: dict[str, dict] = {}
    for subject in payload["subjects"]:
        if not isinstance(subject, dict):
            continue
        for chapter in subject.get("chapters") if isinstance(subject.get("chapters"), list) else []:
            if not isinstance(chapter, dict):
                continue
            for item in chapter.get("items") if isinstance(chapter.get("items"), list) else []:
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get("id") or "")
                if not re.fullmatch(r"oral-focus-[a-f0-9]{16}", item_id) or item_id in items:
                    raise ValueError("invalid oral focus item id")
                items[item_id] = {**item, "subject": subject, "chapter": chapter}
    ORAL_FOCUS_CACHE.update({"mtime_ns": mtime_ns, "payload": payload, "items": items})
    return payload, items


def load_oral_focus_progress() -> dict:
    if not ORAL_FOCUS_PROGRESS_PATH.is_file():
        return {"schema_version": 1, "items": {}}
    try:
        payload = json.loads(ORAL_FOCUS_PROGRESS_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "items": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), dict):
        return {"schema_version": 1, "items": {}}
    return payload


def oral_focus_index_payload() -> dict:
    dataset, _items = load_oral_focus()
    progress = load_oral_focus_progress().get("items", {})
    subjects: list[dict] = []
    for subject in dataset.get("subjects") or []:
        chapters: list[dict] = []
        for chapter in subject.get("chapters") or []:
            public_items = []
            for item in chapter.get("items") or []:
                state = progress.get(str(item.get("id") or ""), {})
                state = state if isinstance(state, dict) else {}
                completed = bool(
                    str(state.get("answer") or "").strip()
                    or str(state.get("memory_note") or "").strip()
                    or str(state.get("mastery") or "unseen") != "unseen"
                )
                public_items.append(
                    {
                        key: item.get(key)
                        for key in ("id", "order", "type", "type_label", "title", "star_level", "character_count", "has_table", "has_unreviewed_image")
                    }
                    | {"mastery": str(state.get("mastery") or "unseen"), "completed": completed}
                )
            chapters.append(
                {
                    key: chapter.get(key)
                    for key in ("id", "order", "title", "definition_count", "essay_count", "starred_count")
                }
                | {"items": public_items}
            )
        subject_progress = [progress.get(item["id"], {}) for chapter in chapters for item in chapter["items"]]
        subjects.append(
            {
                key: subject.get(key)
                for key in ("id", "short_title", "title", "book_id", "item_count", "chapter_count")
            }
            | {
                "studied_count": sum(
                    isinstance(item, dict)
                    and bool(
                        str(item.get("answer") or "").strip()
                        or str(item.get("memory_note") or "").strip()
                        or item.get("mastery") not in (None, "", "unseen")
                    )
                    for item in subject_progress
                ),
                "mastered_count": sum(isinstance(item, dict) and item.get("mastery") == "mastered" for item in subject_progress),
                "chapters": chapters,
            }
        )
    return {"available": bool(subjects), "summary": dataset.get("summary") or {}, "subjects": subjects}


def oral_focus_item_payload(item_id: str, *, reveal: bool = False) -> dict:
    if not re.fullmatch(r"oral-focus-[a-f0-9]{16}", str(item_id or "")):
        raise ValueError("invalid oral focus item id")
    _dataset, items = load_oral_focus()
    record = items.get(item_id)
    if not record:
        raise ValueError("oral focus item not found")
    subject = record["subject"]
    chapter = record["chapter"]
    progress = load_oral_focus_progress().get("items", {}).get(item_id, {})
    progress = progress if isinstance(progress, dict) else {}
    _note_target, note_storage, note_uri = oral_focus_notes_target(subject)
    public = {
        key: record.get(key)
        for key in ("id", "order", "type", "type_label", "title", "star_level", "character_count", "has_table", "has_unreviewed_image", "source_files", "source_paragraph")
    }
    public.update(
        {
            "subject": {key: subject.get(key) for key in ("id", "short_title", "title", "book_id")},
            "chapter": {key: chapter.get(key) for key in ("id", "order", "title")},
            "progress": {
                "answer": str(progress.get("answer") or ""),
                "memory_note": str(progress.get("memory_note") or ""),
                "mastery": str(progress.get("mastery") or "unseen"),
                "updated_at": str(progress.get("updated_at") or ""),
            },
            "reference_revealed": bool(reveal),
            "storage": note_storage,
            "obsidian_uri": note_uri,
        }
    )
    if reveal:
        public["answer_markdown"] = str(record.get("answer_markdown") or "")
    return public


def oral_focus_notes_target(subject: dict) -> tuple[Path, str, str]:
    subject_name = safe_note_component(subject.get("title") or subject.get("id"), "口腔重点")
    vault = obsidian_vault()
    if vault:
        root = (vault / "YuReader" / "医学" / subject_name).resolve()
        target = (root / "重点背诵.md").resolve()
        if target.parent != root:
            raise ValueError("oral focus note path escapes Obsidian vault")
        return target, "obsidian", f"obsidian://open?path={quote(str(target.relative_to(vault)).replace(os.sep, '/'))}"
    target = (ORAL_FOCUS_DIR / "notes" / f"{subject.get('id')}.md").resolve()
    if ORAL_FOCUS_DIR.resolve() not in target.parents:
        raise ValueError("oral focus note path escapes data directory")
    return target, "local", "obsidian://open"


def write_oral_focus_notes(subject_id: str, progress_payload: dict) -> tuple[Path, str, str]:
    dataset, items = load_oral_focus()
    subject = next((entry for entry in dataset.get("subjects") or [] if entry.get("id") == subject_id), None)
    if not subject:
        raise ValueError("oral focus subject not found")
    lines = [f"# {subject.get('title')} · 重点背诵", "", "> 保存从侧边栏整理的个人笔记；原始题目和参考答案仍留在本地重点数据中。"]
    progress_items = progress_payload.get("items") if isinstance(progress_payload.get("items"), dict) else {}
    for item_id, state in progress_items.items():
        record = items.get(str(item_id))
        if not record or record["subject"].get("id") != subject_id or not isinstance(state, dict):
            continue
        answer = str(state.get("answer") or "").strip()
        memory_note = str(state.get("memory_note") or "").strip()
        mastery = str(state.get("mastery") or "unseen")
        if not answer and not memory_note and mastery == "unseen":
            continue
        lines.extend(["", f"## {record.get('title')}", "", f"- 章节：{record['chapter'].get('title')}", f"- 题型：{record.get('type_label')}", f"- 掌握：{mastery}"])
        if answer:
            lines.extend(["", "### 我的作答", "", answer])
        if memory_note:
            lines.extend(["", "### 学习笔记", "", memory_note])
    target, storage, uri = oral_focus_notes_target(subject)
    atomic_write(target, "\n".join(lines).strip() + "\n")
    return target, storage, uri


def save_oral_focus_progress(item_id: str, answer: str, memory_note: str, mastery: str) -> dict:
    item = oral_focus_item_payload(item_id)
    if mastery not in {"unseen", "learning", "fuzzy", "mastered"}:
        raise ValueError("invalid oral focus mastery")
    answer = str(answer or "").replace("\r\n", "\n").strip()
    memory_note = str(memory_note or "").replace("\r\n", "\n").strip()
    if len(answer) > 50000 or len(memory_note) > 30000:
        raise ValueError("oral focus response is too long")
    with ORAL_FOCUS_LOCK:
        payload = load_oral_focus_progress()
        payload.setdefault("items", {})[item_id] = {
            "answer": answer,
            "memory_note": memory_note,
            "mastery": mastery,
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        atomic_write(ORAL_FOCUS_PROGRESS_PATH, json.dumps(payload, ensure_ascii=False, indent=2))
        target, storage, uri = write_oral_focus_notes(item["subject"]["id"], payload)
    return {"saved": bool(answer or memory_note or mastery != "unseen"), "progress": payload["items"][item_id], "path": str(target), "storage": storage, "obsidian_uri": uri}


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
    question = next((item for item in load_bank_questions(bank_id) if item["question_id"] == question_id), None)
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


def book_asset_path(book_id: str, asset_path: str) -> Path | None:
    """Resolve one package-declared image asset without allowing traversal.

    Only ``<asset_root>/<declared_name>`` is accepted, the name must be listed in
    the published manifest ``assets`` (and, when the package carries an integrity
    list, the exact ``<asset_root>/<name>`` path), and the resolved file must stay
    inside that book's published package directory.
    """
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", book_id):
        return None
    entry = BOOK_ASSETS.get(book_id)
    if not entry:
        return None
    asset_root = str(entry.get("asset_root") or "images")
    parts = asset_path.split("/")
    if len(parts) != 2 or parts[0] != asset_root or not parts[1]:
        return None
    name = parts[1]
    if name != Path(name).name or name in {".", "..", ""}:
        return None
    if name not in entry["names"]:
        return None
    integrity_paths = entry.get("integrity_paths")
    if integrity_paths and f"{asset_root}/{name}" not in integrity_paths:
        return None
    package_dir = Path(entry["package_dir"]).resolve()
    candidate = (package_dir / asset_path).resolve()
    try:
        candidate.relative_to(package_dir)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def note_path(section_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", section_id):
        raise ValueError("invalid section id")
    return NOTES_DIR / f"{section_id}.md"


def section_aliases_path() -> Path:
    """Return the metadata-only legacy section ID alias index location."""
    return DATA_DIR / "section-aliases.json"


def load_section_aliases() -> dict[str, dict]:
    """Load high-confidence legacy section aliases without touching source data."""
    try:
        payload = json.loads(section_aliases_path().read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        return {}
    raw_aliases = payload.get("section_aliases")
    if not isinstance(raw_aliases, dict):
        return {}
    aliases: dict[str, dict] = {}
    for legacy_id, entry in raw_aliases.items():
        if not isinstance(legacy_id, str) or not re.fullmatch(r"[0-9a-f]{12}", legacy_id):
            continue
        if not isinstance(entry, dict):
            continue
        current_id = entry.get("current_id")
        if not isinstance(current_id, str) or not re.fullmatch(r"[0-9a-f]{12}", current_id) or current_id == legacy_id:
            continue
        aliases[legacy_id] = {
            "current_id": current_id,
            "confidence": str(entry.get("confidence") or "").strip(),
            "reason": str(entry.get("reason") or "").strip(),
        }
    return aliases


def resolve_section_id(section_id: object, available_ids: object = None) -> str | None:
    """Resolve one current or legacy section ID, failing closed on bad aliases."""
    current = str(section_id or "")
    if not re.fullmatch(r"[0-9a-f]{12}", current):
        return None
    available = set(available_ids) if available_ids is not None else None
    aliases = load_section_aliases()
    visited: set[str] = set()
    while current in aliases:
        if current in visited:
            return None
        visited.add(current)
        current = aliases[current]["current_id"]
    if available is not None and current not in available:
        return None
    return current


def section_aliases_for(section_id: object, available_ids: object = None) -> list[str]:
    """Return the canonical ID followed by legacy IDs that resolve to it."""
    canonical = resolve_section_id(section_id, available_ids)
    if not canonical:
        return []
    aliases = [canonical]
    for legacy_id in load_section_aliases():
        if resolve_section_id(legacy_id, available_ids) == canonical:
            aliases.append(legacy_id)
    return [canonical, *sorted(set(aliases[1:]))]


def section_note_records(sections: dict[str, dict]) -> dict[str, tuple[Path, str]]:
    """Read active note bodies once, preferring a canonical file over its aliases."""
    records: dict[str, tuple[Path, str]] = {}
    if not NOTES_DIR.is_dir():
        return records
    known_ids = set(sections)
    for path in NOTES_DIR.glob("*.md"):
        canonical_id = resolve_section_id(path.stem, known_ids)
        if not canonical_id:
            continue
        try:
            markdown = path.read_text(encoding="utf-8-sig").strip()
        except OSError:
            continue
        if not markdown:
            continue
        existing = records.get(canonical_id)
        if existing is None or path.stem == canonical_id:
            records[canonical_id] = (path, markdown)
    return records


def section_note_source(section_id: object, sections: dict[str, dict]) -> tuple[str, Path] | None:
    """Find a canonical or legacy local note without moving or rewriting it."""
    canonical_id = resolve_section_id(section_id, set(sections))
    if not canonical_id:
        return None
    for candidate_id in section_aliases_for(canonical_id, set(sections)):
        candidate = note_path(candidate_id)
        if candidate.is_file():
            return canonical_id, candidate
    return canonical_id, note_path(canonical_id)


def _display_data_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def unarchived_learning_records(sections: dict[str, dict]) -> dict:
    """Return metadata-only unresolved notes and activity IDs for migration review."""
    known_ids = set(sections)
    notes: list[dict] = []
    if NOTES_DIR.is_dir():
        for path in sorted(NOTES_DIR.glob("*.md")):
            try:
                markdown = path.read_text(encoding="utf-8-sig").strip()
                stat = path.stat()
            except OSError:
                continue
            if not markdown or resolve_section_id(path.stem, known_ids):
                continue
            notes.append(
                {
                    "legacy_id": path.stem,
                    "path": _display_data_path(path),
                    "size_bytes": stat.st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "mapping_status": "unmapped",
                }
            )

    activity: list[dict] = []
    seen_activity: set[tuple[str, str, str]] = set()
    payload = load_activity()
    raw_days = payload.get("days") if isinstance(payload.get("days"), dict) else {}
    for day, value in raw_days.items():
        if not isinstance(value, dict):
            continue
        for field in ("sections", "notes"):
            raw_ids = value.get(field) if isinstance(value.get(field), list) else []
            for raw_id in raw_ids:
                section_id = str(raw_id)
                if resolve_section_id(section_id, known_ids):
                    continue
                key = (str(day), field, section_id)
                if key not in seen_activity:
                    seen_activity.add(key)
                    activity.append({"day": str(day), "field": field, "legacy_id": section_id, "mapping_status": "unmapped"})
        raw_seconds = value.get("section_reading_seconds") if isinstance(value.get("section_reading_seconds"), dict) else {}
        for raw_id in raw_seconds:
            section_id = str(raw_id)
            if resolve_section_id(section_id, known_ids):
                continue
            key = (str(day), "section_reading_seconds", section_id)
            if key not in seen_activity:
                seen_activity.add(key)
                activity.append({"day": str(day), "field": "section_reading_seconds", "legacy_id": section_id, "mapping_status": "unmapped"})
        for field in ("last_section_id",):
            section_id = str(value.get(field) or "")
            if not section_id or resolve_section_id(section_id, known_ids):
                continue
            key = (str(day), field, section_id)
            if key not in seen_activity:
                seen_activity.add(key)
                activity.append({"day": str(day), "field": field, "legacy_id": section_id, "mapping_status": "unmapped"})
    global_last = str(payload.get("last_section_id") or "")
    if global_last and not resolve_section_id(global_last, known_ids):
        activity.append({"day": "", "field": "last_section_id", "legacy_id": global_last, "mapping_status": "unmapped"})
    return {
        "schema_version": 1,
        "aliases": load_section_aliases(),
        "notes": notes,
        "activity": activity,
        "note_count": len(notes),
        "activity_count": len(activity),
    }


def section_note_target(book: dict, section: dict) -> tuple[Path, str, str]:
    """Map one stable reader section to a browsable Obsidian note location."""
    domain = safe_domain(book.get("domain"))
    subject = safe_note_component(book.get("subject"), "未分类学科")
    chapter = safe_note_component(section.get("chapter_title"), "未分章")
    section_title = safe_note_component(section.get("title"), section.get("id") or "小节")
    filename = f"{section_title}.md"
    local = note_path(section["id"])
    vault = obsidian_vault()
    if not vault:
        return local, "local", ""
    relative = Path("YuReader") / DOMAIN_LABELS[domain] / subject / chapter / filename
    target = (vault / relative).resolve()
    if vault != target and vault not in target.parents:
        raise ValueError("section note path escapes Obsidian vault")
    uri = f"obsidian://open?vault={quote(vault.name)}&file={quote(relative.as_posix())}"
    return target, "obsidian", uri


def section_note_markdown(book: dict, section: dict, content: str) -> str:
    """Keep the Obsidian copy navigable while local note bodies stay compatible."""
    chapter = str(section.get("chapter_title") or "未分章")
    lines = [
        "---",
        "yureader_note: true",
        f"book_id: {book['id']}",
        f"section_id: {section['id']}",
        f"domain: {safe_domain(book.get('domain'))}",
        "---",
        "",
        f"# {section['title']}",
        "",
        f"> {book['title']} / {chapter}",
    ]
    if content.strip():
        lines.extend(["", content.strip()])
    return "\n".join(lines)


def ensure_section_note_mirror(book: dict, section: dict, content: str) -> tuple[Path, str, str]:
    """Backfill an old local section note once, without overwriting vault edits."""
    target, storage, uri = section_note_target(book, section)
    if storage == "obsidian" and content.strip() and not target.exists():
        atomic_write(target, section_note_markdown(book, section, content))
    return target, storage, uri


def dated_note_path(directory: Path, day: str, section_id: str | None = None) -> Path:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("invalid date")
    if section_id is None:
        return directory / f"{day}.md"
    if not re.fullmatch(r"[0-9a-f]{12}", section_id):
        raise ValueError("invalid section id")
    return directory / day / f"{section_id}.md"


def load_activity() -> dict:
    try:
        payload = json.loads(ACTIVITY_PATH.read_text(encoding="utf-8-sig"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def activity_stable_id(*parts: object) -> str:
    return hashlib.sha256(":".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:16]


def _section_activity_context(section_id: object) -> dict | None:
    requested = str(section_id or "")
    books, sections = catalog()
    canonical_id = resolve_section_id(requested, set(sections))
    if not canonical_id:
        return None
    section = sections.get(canonical_id)
    book = next((item for item in books if any(entry.get("id") == canonical_id for entry in item.get("sections", []))), None)
    if not section or not book:
        return None
    subject_id = str(book.get("subject") or book.get("id") or "").strip()
    return {
        "domain": safe_domain(book.get("domain")),
        "subject_id": subject_id,
        "resource_id": str(book.get("id") or ""),
        "item_id": canonical_id,
        "resume_target": {"view": "reader", "resource_id": str(book.get("id") or ""), "item_id": canonical_id},
    }


def _activity_output_ref(kind: str, identifier: object, path: Path | str) -> dict:
    return {"kind": kind, "id": str(identifier or ""), "path": str(path)}


def _activity_day(value: object, fallback: Path | None = None) -> str:
    candidate = str(value or "")
    match = re.match(r"(\d{4}-\d{2}-\d{2})", candidate)
    if match:
        return match.group(1)
    if fallback:
        try:
            return date.fromtimestamp(fallback.stat().st_mtime).isoformat()
        except OSError:
            pass
    return date.today().isoformat()


def _question_activity_context(bank_id: object, question_id: object) -> dict | None:
    bank = question_bank_by_id(str(bank_id or ""))
    if not bank:
        return None
    question = next((item for item in load_bank_questions(bank["id"]) if item.get("question_id") == str(question_id or "")), None)
    subject_id = str((question or {}).get("subject_label") or bank.get("subject") or bank["id"]).strip()
    item_id = str(question_id or "").strip()
    if not item_id:
        return None
    return {
        "domain": safe_domain(bank.get("domain")),
        "subject_id": subject_id,
        "resource_id": str(bank["id"]),
        "item_id": item_id,
        "resume_target": {"view": "practice", "resource_id": str(bank["id"]), "item_id": item_id, "question_id": item_id},
    }


def _activity_record(payload: dict, day: str, *, activity_type: str, context: dict, activity_id: str, duration_seconds: int = 0, result_state: str = "in_progress", output_refs: list[dict] | None = None, idempotency_key: str = "", event_at: str = "") -> tuple[dict, bool]:
    if activity_type not in ACTIVITY_TYPES:
        raise ValueError("invalid activity type")
    days = payload.setdefault("days", {})
    daily = days.setdefault(day, {"section_opens": 0, "sections": [], "notes": [], "review_saved": False})
    activities = daily.setdefault("activities", [])
    if not isinstance(activities, list):
        activities = []
        daily["activities"] = activities
    existing = next((item for item in activities if isinstance(item, dict) and item.get("activity_id") == activity_id), None)
    if existing is None:
        now = event_at or datetime.now().astimezone().isoformat(timespec="seconds")
        existing = {
            "activity_id": activity_id,
            "activity_type": activity_type,
            "domain": str(context.get("domain") or ""),
            "subject_id": str(context.get("subject_id") or ""),
            "resource_id": str(context.get("resource_id") or ""),
            "item_id": str(context.get("item_id") or ""),
            "started_at": now,
            "last_active_at": now,
            "duration_seconds": 0,
            "resume_target": context.get("resume_target") if isinstance(context.get("resume_target"), dict) else {},
            "output_refs": [],
            "result_state": result_state,
            "idempotency_keys": [],
        }
        activities.append(existing)
    seen_keys = existing.setdefault("idempotency_keys", [])
    if not isinstance(seen_keys, list):
        seen_keys = []
        existing["idempotency_keys"] = seen_keys
    if idempotency_key and idempotency_key in seen_keys:
        return existing, False
    existing["duration_seconds"] = max(0, int(existing.get("duration_seconds") or 0)) + max(0, int(duration_seconds or 0))
    existing["last_active_at"] = event_at or datetime.now().astimezone().isoformat(timespec="seconds")
    if result_state == "has_output" or existing.get("result_state") in {"started", "in_progress"}:
        existing["result_state"] = result_state
    refs = existing.setdefault("output_refs", [])
    if not isinstance(refs, list):
        refs = []
        existing["output_refs"] = refs
    for ref in output_refs or []:
        if isinstance(ref, dict) and ref not in refs:
            refs.append(ref)
    if idempotency_key and idempotency_key not in seen_keys:
        seen_keys.append(idempotency_key)
        del seen_keys[:-256]
    return existing, True


def _migrate_legacy_activity_payload(payload: dict) -> dict:
    """Backfill schema-1 reading facts into deterministic schema-3 records."""
    migration = payload.get("migration") if isinstance(payload.get("migration"), dict) else {}
    if migration.get("legacy_activity_backfill") == "v2":
        return payload
    payload["schema_version"] = ACTIVITY_SCHEMA_VERSION
    raw_days = payload.get("days") if isinstance(payload.get("days"), dict) else {}
    for day, value in raw_days.items():
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(day)) or not isinstance(value, dict):
            continue
        raw_seconds = value.get("section_reading_seconds") if isinstance(value.get("section_reading_seconds"), dict) else {}
        canonical_seconds: dict[str, int] = {}
        for raw_id, seconds in raw_seconds.items():
            context = _section_activity_context(raw_id)
            if not context:
                continue
            item_id = context["item_id"]
            canonical_seconds[item_id] = canonical_seconds.get(item_id, 0) + max(0, int(seconds or 0))
        raw_ids = []
        for field in ("sections", "notes"):
            candidates = value.get(field) if isinstance(value.get(field), list) else []
            raw_ids.extend(str(item) for item in candidates if str(item))
        raw_ids.extend(str(item) for item in raw_seconds if str(item))
        if not canonical_seconds and int(value.get("reading_seconds") or 0) > 0:
            fallback = _section_activity_context(value.get("last_section_id"))
            if not fallback and raw_ids:
                fallback = _section_activity_context(raw_ids[-1])
            if fallback:
                canonical_seconds[fallback["item_id"]] = max(0, int(value.get("reading_seconds") or 0))
        known_contexts: dict[str, dict] = {}
        for raw_id in raw_ids:
            context = _section_activity_context(raw_id)
            if context:
                known_contexts[context["item_id"]] = context
        daily_last = str(value.get("last_reading_at") or "")
        for item_id, context in known_contexts.items():
            refs: list[dict] = []
            note_source = section_note_source(item_id, catalog()[1])
            if note_source:
                _canonical_id, note_path_value = note_source
                try:
                    if note_path_value.read_text(encoding="utf-8-sig").strip():
                        refs.append(_activity_output_ref("section_note", item_id, note_path_value))
                except OSError:
                    pass
            duration = canonical_seconds.get(item_id, 0)
            _activity_record(
                payload,
                str(day),
                activity_type="read",
                context=context,
                activity_id=activity_stable_id("legacy-read", day, item_id),
                duration_seconds=duration,
                result_state="has_output" if refs else ("in_progress" if duration or item_id in raw_ids else "started"),
                output_refs=refs,
                event_at=daily_last or f"{day}T00:00:00+08:00",
            )
        if value.get("review_saved") and known_contexts:
            context = next(iter(known_contexts.values())).copy()
            context["item_id"] = str(day)
            context["resume_target"] = {"view": "review", "resource_id": str(context.get("resource_id") or ""), "item_id": str(day)}
            _activity_record(
                payload,
                str(day),
                activity_type="review",
                context=context,
                activity_id=activity_stable_id("legacy-review", day),
                result_state="completed",
                event_at=daily_last or f"{day}T00:00:00+08:00",
            )
    # Existing sidecar stores keep their own bodies and answer data.  Backfill
    # only stable references into the unified index; never copy their content.
    attempts_path = practice_path("attempts")
    try:
        attempts_payload = json.loads(attempts_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        attempts_payload = {}
    attempts = attempts_payload.get("items") if isinstance(attempts_payload, dict) and isinstance(attempts_payload.get("items"), dict) else {}
    for question_id, attempt in attempts.items():
        if not isinstance(attempt, dict):
            continue
        context = _question_activity_context(attempt.get("bank_id"), question_id)
        if not context:
            continue
        day = _activity_day(attempt.get("answered_at"), attempts_path)
        _activity_record(
            payload,
            day,
            activity_type="objective_practice",
            context=context,
            activity_id=activity_stable_id("legacy-objective", day, context["resource_id"], question_id),
            result_state="has_output",
            output_refs=[_activity_output_ref("objective_attempt", question_id, attempts_path)],
            event_at=str(attempt.get("answered_at") or ""),
        )
    analyses_path = practice_path("analyses")
    try:
        analyses_payload = json.loads(analyses_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        analyses_payload = {}
    analyses = analyses_payload.get("items") if isinstance(analyses_payload, dict) and isinstance(analyses_payload.get("items"), dict) else {}
    for question_id, analysis in analyses.items():
        if not isinstance(analysis, dict) or not str(analysis.get("content") or "").strip():
            continue
        context = _question_activity_context(analysis.get("bank_id"), question_id)
        if not context:
            continue
        day = _activity_day(analysis.get("updated_at"), analyses_path)
        _activity_record(
            payload,
            day,
            activity_type="objective_practice",
            context=context,
            activity_id=activity_stable_id("legacy-objective", day, context["resource_id"], question_id),
            result_state="has_output",
            output_refs=[_activity_output_ref("personal_analysis", question_id, analyses_path)],
            event_at=str(analysis.get("updated_at") or ""),
        )
    subjective_dir = SUBJECTIVE_DIR
    if subjective_dir.is_dir():
        for response_path in sorted(subjective_dir.glob("*.json")):
            try:
                response = json.loads(response_path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(response, dict) or not (str(response.get("answer") or "").strip() or str(response.get("reflection") or "").strip()):
                continue
            context = _section_activity_context(response.get("section_id") or response_path.stem)
            if not context:
                continue
            day = _activity_day(response.get("updated_at"), response_path)
            _activity_record(
                payload,
                day,
                activity_type="subjective_practice",
                context={**context, "resume_target": {"view": "subjective_practice", "resource_id": context["resource_id"], "item_id": context["item_id"]}},
                activity_id=activity_stable_id("legacy-subjective", day, context["resource_id"], context["item_id"]),
                result_state="has_output",
                output_refs=[_activity_output_ref("subjective_response", context["item_id"], response_path)],
                event_at=str(response.get("updated_at") or ""),
            )
    for week, notebook_path in english_notebook_files().items():
        try:
            if not notebook_path.read_text(encoding="utf-8-sig").strip():
                continue
        except OSError:
            continue
        notebook_day = _activity_day("", notebook_path)
        context = {"domain": "english", "subject_id": "english-notebook", "resource_id": "english-notebook", "item_id": week, "resume_target": {"view": "english_notebook", "resource_id": "english-notebook", "item_id": week}}
        _activity_record(
            payload,
            notebook_day,
            activity_type="notebook",
            context=context,
            activity_id=activity_stable_id("legacy-notebook", notebook_day, week),
            result_state="has_output",
            output_refs=[_activity_output_ref("english_notebook", week, notebook_path)],
            event_at=f"{notebook_day}T00:00:00+08:00",
        )
    migration["legacy_activity_backfill"] = "v2"
    payload["migration"] = migration
    return payload


def migrate_activity_index() -> dict:
    """Upgrade activity.json once, retaining every legacy field verbatim."""
    with ACTIVITY_LOCK:
        payload = _migrate_legacy_activity_payload(load_activity())
        payload["schema_version"] = ACTIVITY_SCHEMA_VERSION
        atomic_write(ACTIVITY_PATH, json.dumps(payload, ensure_ascii=False, indent=2))
        return payload


def _record_activity(
    kind: str,
    section_id: str = "",
    character_count: int = 0,
    reading_seconds: int = 0,
    *,
    activity_type: str = "",
    context: dict | None = None,
    activity_id: str = "",
    output_refs: list[dict] | None = None,
    result_state: str = "in_progress",
    idempotency_key: str = "",
    event_at: str = "",
) -> bool:
    if kind not in {"section_open", "note_save", "review_save", "reading_time", "objective_practice", "subjective_practice", "notebook", "review"}:
        raise ValueError("invalid activity kind")
    if activity_type and activity_type not in ACTIVITY_TYPES:
        raise ValueError("invalid activity type")
    payload = _migrate_legacy_activity_payload(load_activity())
    payload["schema_version"] = ACTIVITY_SCHEMA_VERSION
    days = payload.setdefault("days", {})
    today = date.today().isoformat()
    daily = days.setdefault(today, {"section_opens": 0, "sections": [], "notes": [], "review_saved": False})
    existing_activities = daily.get("activities") if isinstance(daily.get("activities"), list) else []
    if idempotency_key and any(isinstance(item, dict) and idempotency_key in (item.get("idempotency_keys") or []) for item in existing_activities):
        return False
    if kind == "section_open":
        daily["section_opens"] = int(daily.get("section_opens") or 0) + 1
        if section_id and section_id not in daily.setdefault("sections", []):
            daily["sections"].append(section_id)
        if section_id:
            payload["last_section_id"] = section_id
    elif kind == "note_save":
        if section_id and section_id not in daily.setdefault("notes", []):
            daily["notes"].append(section_id)
        daily["note_characters"] = max(int(daily.get("note_characters") or 0), max(0, character_count))
    elif kind == "review_save":
        daily["review_saved"] = True
    elif kind == "reading_time":
        daily["reading_seconds"] = int(daily.get("reading_seconds") or 0) + max(0, reading_seconds)
        if section_id:
            section_seconds = daily.setdefault("section_reading_seconds", {})
            section_seconds[section_id] = int(section_seconds.get(section_id) or 0) + max(0, reading_seconds)
        daily["last_reading_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        if section_id:
            daily["last_section_id"] = section_id
            payload["last_section_id"] = section_id
    resolved_context = context or _section_activity_context(section_id)
    if not activity_type and kind in {"section_open", "note_save", "reading_time"}:
        activity_type = "read"
    if resolved_context and activity_type:
        canonical_id = str(resolved_context.get("item_id") or section_id)
        resolved_context = {**resolved_context, "item_id": canonical_id}
        if not activity_id:
            activity_id = activity_stable_id(today, activity_type, resolved_context.get("resource_id"), canonical_id)
        duration = max(0, reading_seconds)
        refs = output_refs or []
        state = result_state
        if kind == "note_save":
            if character_count > 0:
                refs = [*refs, _activity_output_ref("section_note", canonical_id, note_path(canonical_id))]
                state = "has_output"
            else:
                state = "in_progress"
        _activity_record(
            payload,
            today,
            activity_type=activity_type,
            context=resolved_context,
            activity_id=activity_id,
            duration_seconds=duration,
            result_state=state,
            output_refs=refs,
            idempotency_key=idempotency_key,
            event_at=event_at,
        )
    # This is the user's long-term learning history. Keep all dated records;
    # retention or archival must be an explicit, recoverable operation.
    atomic_write(ACTIVITY_PATH, json.dumps(payload, ensure_ascii=False, indent=2))
    return True


def record_activity(kind: str, section_id: str = "", character_count: int = 0, reading_seconds: int = 0, **kwargs: object) -> bool:
    with ACTIVITY_LOCK:
        return _record_activity(kind, section_id, character_count, reading_seconds, **kwargs)


def activity_records_payload(day: str = "", activity_type: str = "") -> dict:
    if day and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("invalid activity date")
    if activity_type and activity_type not in ACTIVITY_TYPES:
        raise ValueError("invalid activity type")
    payload = _migrate_legacy_activity_payload(load_activity())
    raw_days = payload.get("days") if isinstance(payload.get("days"), dict) else {}
    records: list[dict] = []
    for current_day, value in sorted(raw_days.items()):
        if day and current_day != day:
            continue
        items = value.get("activities") if isinstance(value, dict) and isinstance(value.get("activities"), list) else []
        for item in items:
            if not isinstance(item, dict) or (activity_type and item.get("activity_type") != activity_type):
                continue
            records.append({"date": str(current_day), **{key: value for key, value in item.items() if key != "idempotency_keys"}})
    by_type: dict[str, int] = {}
    by_domain: dict[str, int] = {}
    for item in records:
        kind = str(item.get("activity_type") or "")
        domain = str(item.get("domain") or "")
        seconds = max(0, int(item.get("duration_seconds") or 0))
        by_type[kind] = by_type.get(kind, 0) + seconds
        by_domain[domain] = by_domain.get(domain, 0) + seconds
    return {
        "schema_version": ACTIVITY_SCHEMA_VERSION,
        "date": day,
        "activities": records,
        "count": len(records),
        "duration_seconds": sum(max(0, int(item.get("duration_seconds") or 0)) for item in records),
        "by_activity_type": by_type,
        "by_domain": by_domain,
    }


def coalesce_activity_records(records: object) -> list[dict]:
    """Merge timer and durable-output rows for the same logical learning item.

    Workspace timers use a session activity ID while answer/note saves use a
    stable output activity ID. Both rows remain in the append-compatible local
    index, but user-facing summaries should show one question or notebook once.
    Durations are accumulated and the durable-output row supplies the more
    specific subject, result state, and resume target.
    """
    items = records if isinstance(records, list) else []
    merged: dict[tuple[str, ...], dict] = {}
    order: list[tuple[str, ...]] = []
    result_rank = {"in_progress": 0, "has_output": 1, "completed": 2}

    def preferred_rank(item: dict) -> int:
        state_rank = result_rank.get(str(item.get("result_state") or ""), 0)
        has_output = any(isinstance(ref, dict) for ref in (item.get("output_refs") or []))
        return max(state_rank, 1 if has_output else 0)

    for position, raw in enumerate(items):
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        activity_type = str(item.get("activity_type") or "")
        resource_id = str(item.get("resource_id") or "")
        item_id = str(item.get("item_id") or "")
        day = str(item.get("date") or "")
        if activity_type and resource_id and item_id:
            key = (day, activity_type, resource_id, item_id)
        else:
            key = ("activity", str(item.get("activity_id") or position))
        if key not in merged:
            item["duration_seconds"] = max(0, int(item.get("duration_seconds") or 0))
            item["output_refs"] = [dict(ref) for ref in (item.get("output_refs") or []) if isinstance(ref, dict)]
            item["_preferred_rank"] = preferred_rank(item)
            merged[key] = item
            order.append(key)
            continue

        current = merged[key]
        current["duration_seconds"] = max(0, int(current.get("duration_seconds") or 0)) + max(0, int(item.get("duration_seconds") or 0))
        existing_refs = {
            (str(ref.get("kind") or ""), str(ref.get("id") or ""), str(ref.get("path") or ""))
            for ref in current.get("output_refs") or []
            if isinstance(ref, dict)
        }
        for ref in item.get("output_refs") or []:
            if not isinstance(ref, dict):
                continue
            ref_key = (str(ref.get("kind") or ""), str(ref.get("id") or ""), str(ref.get("path") or ""))
            if ref_key not in existing_refs:
                current.setdefault("output_refs", []).append(dict(ref))
                existing_refs.add(ref_key)
        started = [str(value) for value in (current.get("started_at"), item.get("started_at")) if str(value or "")]
        active = [str(value) for value in (current.get("last_active_at"), item.get("last_active_at")) if str(value or "")]
        if started:
            current["started_at"] = min(started)
        if active:
            current["last_active_at"] = max(active)
        candidate_rank = preferred_rank(item)
        if candidate_rank > int(current.get("_preferred_rank") or 0):
            for field in ("activity_id", "domain", "subject_id", "result_state", "resume_target"):
                if item.get(field) not in (None, "", {}):
                    current[field] = item[field]
            current["_preferred_rank"] = candidate_rank

    result: list[dict] = []
    for key in order:
        item = merged[key]
        item.pop("_preferred_rank", None)
        result.append(item)
    return result


def meaningful_activity(item: object, *, include_review: bool = True) -> bool:
    """Return whether one indexed activity represents deliberate learning.

    Opening a workspace creates a resumable index immediately, but it should not
    manufacture an active day or a review task. A minute of tracked work or a
    durable user output is enough; explicit completed reviews still count as
    learning, while callers may exclude them when selecting a day to review.
    """
    if not isinstance(item, dict):
        return False
    if not include_review and item.get("activity_type") == "review":
        return False
    if max(0, int(item.get("duration_seconds") or 0)) >= MIN_MEANINGFUL_ACTIVITY_SECONDS:
        return True
    if str(item.get("result_state") or "") in {"has_output", "completed"}:
        return True
    return any(isinstance(ref, dict) for ref in (item.get("output_refs") or []))


def completed_review_activity(item: object) -> bool:
    """A timed visit is not a completed review until it has a durable result."""
    if not isinstance(item, dict) or item.get("activity_type") != "review":
        return False
    return str(item.get("result_state") or "") in {"has_output", "completed"} or any(
        isinstance(ref, dict) for ref in (item.get("output_refs") or [])
    )


def meaningful_learning_day(value: object, records: list[dict], *, include_review: bool = True) -> bool:
    """Apply the same effective-day rule to schema-3 and legacy facts."""
    daily = value if isinstance(value, dict) else {}
    if any(meaningful_activity(item, include_review=include_review) for item in records):
        return True
    if max(0, int(daily.get("reading_seconds") or 0)) >= MIN_MEANINGFUL_ACTIVITY_SECONDS:
        return True
    if max(0, int(daily.get("note_characters") or 0)) > 0:
        return True
    return include_review and bool(daily.get("review_saved"))


def effective_activity_payload(day: str = "", *, include_review: bool = True) -> dict:
    """Return the public activity aggregate after applying the effective rule."""
    raw = activity_records_payload(day)
    records = [item for item in coalesce_activity_records(raw.get("activities", [])) if meaningful_activity(item, include_review=include_review)]
    by_type: dict[str, int] = {}
    by_domain: dict[str, int] = {}
    for item in records:
        seconds = max(0, int(item.get("duration_seconds") or 0))
        activity_type = str(item.get("activity_type") or "")
        domain = str(item.get("domain") or "")
        by_type[activity_type] = by_type.get(activity_type, 0) + seconds
        by_domain[domain] = by_domain.get(domain, 0) + seconds
    return {
        "schema_version": ACTIVITY_SCHEMA_VERSION,
        "date": day,
        "activities": records,
        "count": len(records),
        "duration_seconds": sum(max(0, int(item.get("duration_seconds") or 0)) for item in records),
        "by_activity_type": by_type,
        "by_domain": by_domain,
    }


ACTIVITY_TYPE_LABELS = {
    "read": "阅读",
    "objective_practice": "客观题",
    "subjective_practice": "主观题",
    "notebook": "笔记",
    "review": "回顾",
}


def activity_resume_target(item: dict) -> dict:
    """Return a safe, actionable continuation target without exposing content."""
    target = dict(item.get("resume_target") or {}) if isinstance(item.get("resume_target"), dict) else {}
    if target.get("view") != "practice":
        return target
    bank_id = str(target.get("resource_id") or item.get("resource_id") or "")
    question_id = str(target.get("question_id") or target.get("item_id") or item.get("item_id") or "")
    if not bank_id or not question_id:
        return target
    try:
        question = next((entry for entry in load_bank_questions(bank_id) if entry.get("question_id") == question_id), None)
    except (OSError, ValueError, KeyError, TypeError):
        question = None
    if not question:
        return target
    knowledge_ids = [str(value) for value in question.get("knowledge_ids") or [] if str(value)]
    if knowledge_ids:
        knowledge_id = str(target.get("knowledge_id") or knowledge_ids[-1])
        match_level = str(target.get("match_level") or ("section" if len(knowledge_ids) > 1 else "comprehensive"))
        if match_level not in {"section", "chapter", "comprehensive"}:
            match_level = "section" if len(knowledge_ids) > 1 else "comprehensive"
        target.update({"knowledge_id": knowledge_id, "match_level": match_level})
        try:
            matched = matching_questions(bank_id, knowledge_id, match_level)
            target["start_index"] = next((index for index, entry in enumerate(matched) if entry.get("question_id") == question_id), 0)
        except (OSError, ValueError, KeyError, TypeError):
            target.setdefault("start_index", 0)
    target["question_id"] = question_id
    if question.get("local_number") is not None:
        target["question_number"] = question.get("local_number")
    target["resource_id"] = bank_id
    target["item_id"] = question_id
    return target


def activity_home_summary(item: dict, sections: dict[str, dict], section_to_book: dict[str, dict]) -> dict:
    """Build content-free metadata for Today and continuation surfaces."""
    activity_type = str(item.get("activity_type") or "")
    item_id = str(item.get("item_id") or "")
    target = activity_resume_target(item)
    title = item_id
    if activity_type in {"read", "subjective_practice"}:
        section = sections.get(item_id)
        title = str((section or {}).get("title") or item_id)
        if activity_type == "subjective_practice" and item_id.startswith("oral-focus-"):
            try:
                title = str(oral_focus_item_payload(item_id).get("title") or title)
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                pass
    elif activity_type == "objective_practice":
        question_number = target.get("question_number")
        title = f"第 {question_number} 题" if question_number else f"题目 {item_id}"
    elif activity_type == "notebook":
        title = f"{item_id} · 英语周记"
    elif activity_type == "review":
        title = f"{item_id} · 学习回顾"
    resource_id = str(item.get("resource_id") or target.get("resource_id") or "")
    book = section_to_book.get(item_id)
    if book:
        resource_id = str(book.get("id") or resource_id)
    resource_title = str((book or {}).get("title") or resource_id)
    if activity_type == "objective_practice":
        try:
            resource_title = str((question_bank_by_id(resource_id) or {}).get("title") or resource_title)
        except (OSError, ValueError, KeyError, TypeError):
            pass
    elif activity_type == "notebook":
        resource_title = "英语周记"
    elif activity_type == "review":
        resource_title = str(item.get("subject_id") or resource_title)
    elif activity_type == "subjective_practice" and item_id.startswith("oral-focus-"):
        resource_title = str(item.get("subject_id") or "口腔重点")
    return {
        "date": str(item.get("date") or ""),
        "activity_id": str(item.get("activity_id") or ""),
        "activity_type": activity_type,
        "activity_label": ACTIVITY_TYPE_LABELS.get(activity_type, activity_type),
        "domain": str(item.get("domain") or (book or {}).get("domain") or ""),
        "subject_id": str(item.get("subject_id") or (book or {}).get("subject") or ""),
        "resource_id": resource_id,
        "resource_title": resource_title,
        "item_id": item_id,
        "title": title,
        "started_at": str(item.get("started_at") or ""),
        "last_active_at": str(item.get("last_active_at") or ""),
        "duration_seconds": max(0, int(item.get("duration_seconds") or 0)),
        "result_state": str(item.get("result_state") or ""),
        "resume_target": target,
    }


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


def obsidian_vault() -> Path | None:
    configured = os.environ.get("YUREADER_OBSIDIAN_VAULT", "").strip()
    if configured:
        candidate = Path(configured).expanduser().resolve()
        return candidate if candidate.is_dir() else None
    app_data = os.environ.get("APPDATA", "").strip()
    if not app_data:
        return None
    config_path = Path(app_data) / "obsidian" / "obsidian.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        vaults = list((config.get("vaults") or {}).values())
        vaults.sort(key=lambda item: (not bool(item.get("open")), -int(item.get("ts") or 0)))
        for item in vaults:
            candidate = Path(str(item.get("path") or "")).expanduser().resolve()
            if candidate.is_dir() and (candidate / ".obsidian").is_dir():
                return candidate
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    return None


def daily_review_target(day: str) -> tuple[Path, str, str]:
    local_target = dated_note_path(REVIEWS_DIR, day)
    vault = obsidian_vault()
    if not vault:
        return local_target, "local", ""
    relative = Path("YuReader") / "每日复习" / f"{day}.md"
    target = (vault / relative).resolve()
    if vault != target and vault not in target.parents:
        raise ValueError("review path escapes Obsidian vault")
    uri = f"obsidian://open?vault={quote(vault.name)}&file={quote(relative.as_posix())}"
    return target, "obsidian", uri


def daily_learning_record_target(day: str) -> tuple[Path, str, str]:
    """Resolve the new compact daily-record mirror without touching old archives."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("invalid date")
    year, month = day[:4], day[5:7]
    local_target = DATA_DIR / "learning-records" / year / month / f"{day}.md"
    vault = obsidian_vault()
    if not vault:
        return local_target, "local", ""
    relative = Path("YuReader") / "学习记录" / year / month / f"{day}.md"
    target = (vault / relative).resolve()
    if vault != target and vault not in target.parents:
        raise ValueError("learning record path escapes Obsidian vault")
    uri = f"obsidian://open?vault={quote(vault.name)}&file={quote(relative.as_posix())}"
    return target, "obsidian", uri


def learning_record_files() -> dict[str, Path]:
    """List new daily records while keeping legacy logs as a separate source."""
    files: dict[str, Path] = {}
    local_root = DATA_DIR / "learning-records"
    if local_root.is_dir():
        files.update({path.stem: path for path in local_root.glob("????/??/*.md") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.stem)})
    vault = obsidian_vault()
    remote = vault / "YuReader" / "学习记录" if vault else None
    if remote and remote.is_dir():
        files.update({path.stem: path for path in remote.glob("????/??/*.md") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.stem)})
    return files


def weekly_learning_record_target(week: str) -> tuple[Path, str, str]:
    """Resolve the post-retirement weekly summary without touching old archives."""
    week_bounds(week)
    local_target = DATA_DIR / "learning-records" / "weekly" / f"{week}.md"
    vault = obsidian_vault()
    if not vault:
        return local_target, "local", ""
    relative = Path("YuReader") / "学习记录" / "周报" / f"{week}.md"
    target = (vault / relative).resolve()
    if vault != target and vault not in target.parents:
        raise ValueError("weekly learning record path escapes Obsidian vault")
    uri = f"obsidian://open?vault={quote(vault.name)}&file={quote(relative.as_posix())}"
    return target, "obsidian", uri


def weekly_learning_record_files() -> dict[str, Path]:
    files: dict[str, Path] = {}
    local = DATA_DIR / "learning-records" / "weekly"
    if local.is_dir():
        files.update({path.stem: path for path in local.glob("*.md") if re.fullmatch(r"\d{4}-W\d{2}", path.stem)})
    vault = obsidian_vault()
    remote = vault / "YuReader" / "学习记录" / "周报" if vault else None
    if remote and remote.is_dir():
        files.update({path.stem: path for path in remote.glob("*.md") if re.fullmatch(r"\d{4}-W\d{2}", path.stem)})
    return files


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


def archive_target(day: str, kind: str = "daily") -> tuple[Path, str, str]:
    """Resolve one user-facing Markdown archive without duplicating it across stores."""
    if kind == "daily":
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise ValueError("invalid date")
        local_target = LOGS_DIR / f"{day}.md"
        relative = Path("YuReader") / "学习日志" / f"{day}.md"
    elif kind == "weekly":
        if not re.fullmatch(r"\d{4}-W\d{2}", day):
            raise ValueError("invalid week")
        local_target = WEEKLY_DIR / f"{day}.md"
        relative = Path("YuReader") / "周报" / f"{day}.md"
    else:
        raise ValueError("invalid archive kind")
    vault = obsidian_vault()
    if not vault:
        return local_target, "local", ""
    target = (vault / relative).resolve()
    if vault != target and vault not in target.parents:
        raise ValueError("archive path escapes Obsidian vault")
    uri = f"obsidian://open?vault={quote(vault.name)}&file={quote(relative.as_posix())}"
    return target, "obsidian", uri


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


def archive_files(kind: str) -> dict[str, Path]:
    directory = LOGS_DIR if kind == "daily" else WEEKLY_DIR
    pattern = r"\d{4}-\d{2}-\d{2}" if kind == "daily" else r"\d{4}-W\d{2}"
    folder = "学习日志" if kind == "daily" else "周报"
    files = {path.stem: path for path in directory.glob("*.md") if re.fullmatch(pattern, path.stem)} if directory.is_dir() else {}
    vault = obsidian_vault()
    remote = vault / "YuReader" / folder if vault else None
    if remote and remote.is_dir():
        files.update({path.stem: path for path in remote.glob("*.md") if re.fullmatch(pattern, path.stem)})
    return files


def review_note_files() -> dict[str, Path]:
    files: dict[str, Path] = {}
    if REVIEWS_DIR.is_dir():
        files.update({path.stem: path for path in REVIEWS_DIR.glob("*.md") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.stem)})
    vault = obsidian_vault()
    obsidian_reviews = vault / "YuReader" / "每日复习" if vault else None
    if obsidian_reviews and obsidian_reviews.is_dir():
        files.update({path.stem: path for path in obsidian_reviews.glob("*.md") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.stem)})
    # 新版学习日志与旧版每日复习共同计入复习天数，迁移后不丢历史统计。
    files.update(archive_files("daily"))
    return files


def reading_time_payload(end_day: str = "", day_count: int = 1) -> dict:
    """Return content-free reading duration data for local companion apps."""
    try:
        end = date.fromisoformat(end_day) if end_day else date.today()
    except ValueError as error:
        raise ValueError("date must use YYYY-MM-DD") from error
    count = min(400, max(1, day_count))
    activity = load_activity()
    raw_days = activity.get("days") if isinstance(activity.get("days"), dict) else {}
    history = []
    for offset in range(count - 1, -1, -1):
        current = end - timedelta(days=offset)
        value = raw_days.get(current.isoformat()) if isinstance(raw_days.get(current.isoformat()), dict) else {}
        seconds = max(0, int(value.get("reading_seconds") or 0))
        history.append(
            {
                "date": current.isoformat(),
                "seconds": seconds,
                "minutes": round(seconds / 60, 1),
                "last_reading_at": str(value.get("last_reading_at") or ""),
            }
        )
    selected = history[-1]
    aggregates = activity_records_payload()
    return {
        "date": selected["date"],
        "seconds": selected["seconds"],
        "minutes": selected["minutes"],
        "last_reading_at": selected["last_reading_at"],
        "history": history,
        "source": "YuReader local active reading timer",
        "idle_timeout_seconds": 600,
        "activity_totals": aggregates["by_activity_type"],
        "domain_totals": aggregates["by_domain"],
    }


def learning_stats(books: list[dict], sections: dict[str, dict], weeks: int = 12) -> dict:
    activity = load_activity()
    raw_days = activity.get("days") if isinstance(activity.get("days"), dict) else {}
    unified_payload = activity_records_payload()
    raw_unified_activities = unified_payload.get("activities", [])
    coalesced_unified_activities = coalesce_activity_records(raw_unified_activities)
    unified_activities = [item for item in coalesced_unified_activities if meaningful_activity(item)]
    unified_by_day: dict[str, list[dict]] = {}
    for item in unified_activities:
        unified_by_day.setdefault(str(item.get("date") or ""), []).append(item)
    raw_unified_by_day: dict[str, list[dict]] = {}
    for item in raw_unified_activities:
        raw_unified_by_day.setdefault(str(item.get("date") or ""), []).append(item)
    known_section_ids = set(sections)

    def resolve_for_catalog(value: object) -> str | None:
        return resolve_section_id(value, known_section_ids)

    def resolved_ids(value: object) -> set[str]:
        raw_ids = value if isinstance(value, (list, tuple, set)) else []
        return {resolved for item in raw_ids if (resolved := resolve_for_catalog(item))}

    def resolved_seconds(value: object) -> dict[str, int]:
        raw_seconds = value if isinstance(value, dict) else {}
        result: dict[str, int] = {}
        for section_id, seconds in raw_seconds.items():
            resolved = resolve_for_catalog(section_id)
            if not resolved:
                continue
            result[resolved] = result.get(resolved, 0) + max(0, int(seconds or 0))
        return result

    def empty_day() -> dict:
        return {"section_opens": 0, "sections": set(), "notes": set(), "review_saved": False, "note_characters": 0, "reading_seconds": 0, "section_reading_seconds": {}}

    days: dict[str, dict] = {}
    for day, value in raw_days.items():
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(day)) or not isinstance(value, dict):
            continue
        raw_section_seconds = value.get("section_reading_seconds") if isinstance(value.get("section_reading_seconds"), dict) else {}
        days[str(day)] = {
            "section_opens": max(0, int(value.get("section_opens") or 0)),
            "sections": resolved_ids(value.get("sections")),
            "notes": resolved_ids(value.get("notes")),
            "review_saved": bool(value.get("review_saved")),
            "note_characters": max(0, int(value.get("note_characters") or 0)),
            "reading_seconds": max(0, int(value.get("reading_seconds") or 0)),
            "section_reading_seconds": resolved_seconds(raw_section_seconds),
        }

    note_files = section_note_records(sections)
    for section_id, (path, markdown) in note_files.items():
        day = date.fromtimestamp(path.stat().st_mtime).isoformat()
        daily = days.setdefault(day, empty_day())
        daily["notes"].add(section_id)
        daily["note_characters"] += len(markdown)

    reviewed_days: set[str] = set()
    for day, path in review_note_files().items():
        try:
            if not path.read_text(encoding="utf-8-sig").strip():
                continue
        except OSError:
            continue
        daily = days.setdefault(day, empty_day())
        daily["review_saved"] = True
        reviewed_days.add(day)

    def day_seconds(value: dict) -> int:
        return max(0, int(value.get("reading_seconds") or 0))

    def activity_seconds(day: str) -> int:
        return sum(max(0, int(item.get("duration_seconds") or 0)) for item in unified_by_day.get(day, []))

    def activity_type_seconds(day: str, activity_type: str) -> int:
        return sum(
            max(0, int(item.get("duration_seconds") or 0))
            for item in unified_by_day.get(day, [])
            if item.get("activity_type") == activity_type
        )

    def raw_activity_type_seconds(day: str, activity_type: str) -> int:
        return sum(
            max(0, int(item.get("duration_seconds") or 0))
            for item in raw_unified_by_day.get(day, [])
            if item.get("activity_type") == activity_type
        )

    def active_day(day: str, value: dict) -> bool:
        return meaningful_learning_day(value, unified_by_day.get(day, []))

    def active_day_seconds(day: str, value: dict) -> int:
        return max(day_seconds(value), activity_seconds(day))

    today = date.today()
    start = today - timedelta(days=today.weekday() + (weeks - 1) * 7)
    heatmap_days: list[dict] = []
    for offset in range(weeks * 7):
        current = start + timedelta(days=offset)
        value = days.get(current.isoformat(), empty_day())
        current_day = current.isoformat()
        primary_seconds = activity_seconds(current_day)
        unified_reading_seconds = activity_type_seconds(current_day, "read")
        heatmap_days.append(
            {
                "date": current_day,
                # The visual intensity follows the unified activity index.
                # Legacy reading remains available beside it for explainability.
                "count": primary_seconds,
                "active": active_day(current_day, value),
                "activity_count": sum(1 for item in unified_by_day.get(current_day, []) if meaningful_activity(item)),
                "reading_seconds": day_seconds(value),
                "unified_reading_seconds": unified_reading_seconds,
                "legacy_unmapped_reading_seconds": max(0, day_seconds(value) - unified_reading_seconds),
                "activity_seconds": primary_seconds,
                "reading_minutes": round(day_seconds(value) / 60, 1),
                "section_opens": int(value["section_opens"]),
                "section_count": len(value["sections"]),
                "note_count": len(value["notes"]),
                "review_saved": bool(value["review_saved"]),
                "future": current > today,
            }
        )

    streak_anchor = today
    if not active_day(today.isoformat(), days.get(today.isoformat(), {})):
        streak_anchor -= timedelta(days=1)
    streak = 0
    while active_day(streak_anchor.isoformat(), days.get(streak_anchor.isoformat(), {})):
        streak += 1
        streak_anchor -= timedelta(days=1)

    section_to_book = {section["id"]: book for book in books for section in book.get("sections", [])}
    activity_summaries = [activity_home_summary(item, sections, section_to_book) for item in coalesced_unified_activities if isinstance(item, dict)]
    activity_summaries.sort(key=lambda item: (item.get("last_active_at") or item.get("started_at") or item.get("date") or "", item.get("activity_id") or ""))
    for item in activity_summaries:
        if completed_review_activity(item) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(item.get("item_id") or "")):
            reviewed_days.add(str(item["item_id"]))
    today = date.today()
    today_iso = today.isoformat()
    today_activities = [item for item in activity_summaries if item.get("date") == today_iso and meaningful_activity(item)]
    continuation = next(
        (
            item
            for item in reversed(activity_summaries)
            if isinstance(item.get("resume_target"), dict)
            and item["resume_target"].get("view")
            and item["resume_target"].get("item_id")
            and not completed_review_activity(item)
        ),
        None,
    )
    valid_learning_days = {
        day
        for day in set(days) | set(unified_by_day)
        if day < today_iso and meaningful_learning_day(days.get(day, {}), unified_by_day.get(day, []), include_review=False)
    }
    pending_review_day = next((day for day in sorted(valid_learning_days, reverse=True) if day not in reviewed_days), "")
    pending_value = days.get(pending_review_day, {}) if pending_review_day else {}
    pending_activity_seconds = activity_seconds(pending_review_day) if pending_review_day else 0
    review_pending = {
        "date": pending_review_day,
        "activity_count": sum(1 for item in unified_by_day.get(pending_review_day, []) if meaningful_activity(item, include_review=False)) if pending_review_day else 0,
        "duration_seconds": max(day_seconds(pending_value), pending_activity_seconds) if pending_review_day else 0,
        "note_count": len(pending_value.get("notes", set())) if pending_review_day else 0,
    } if pending_review_day else None
    recent_resources: list[dict] = []
    seen_resources: set[tuple[str, str]] = set()
    for item in reversed(activity_summaries):
        # A review is a daily workflow, not a reusable learning resource.  Its
        # source resource_id only anchors provenance and must not become a
        # phantom book on the home page or in a subject workspace.
        if item.get("activity_type") == "review":
            continue
        key = (str(item.get("domain") or ""), str(item.get("resource_id") or ""))
        if not key[1] or key in seen_resources:
            continue
        seen_resources.add(key)
        recent_resources.append({
            "domain": item.get("domain", ""),
            "subject_id": item.get("subject_id", ""),
            "resource_id": item.get("resource_id", ""),
            "title": item.get("resource_title") or item.get("title", ""),
            "resume_target": item.get("resume_target", {}),
        })
        if len(recent_resources) >= 5:
            break
    book_note_counts: dict[str, int] = {}
    for section_id in note_files:
        book = section_to_book.get(section_id)
        if book:
            book_note_counts[book["id"]] = book_note_counts.get(book["id"], 0) + 1
    book_distribution = [
        {"book_id": book["id"], "title": book["title"], "note_count": book_note_counts.get(book["id"], 0), "section_count": len(book.get("sections", []))}
        for book in books
    ]
    book_distribution.sort(key=lambda item: (-item["note_count"], item["title"]))

    # The dashboard intentionally groups effort by learning area rather than
    # implying that a book is "complete". Reading time comes from the
    # section-level timer; notes and practice are counted independently.
    effort_domains = {
        domain: {"key": domain, "label": DOMAIN_LABELS[domain], "reading_seconds": 0, "section_ids": set(), "note_count": 0, "note_characters": 0}
        for domain in ("medicine", "politics", "english")
    }
    for value in days.values():
        for section_id, seconds in value.get("section_reading_seconds", {}).items():
            book = section_to_book.get(section_id)
            if not book:
                continue
            domain = safe_domain(book.get("domain"))
            effort_domains[domain]["reading_seconds"] += max(0, int(seconds or 0))
            effort_domains[domain]["section_ids"].add(section_id)
        for section_id in value.get("sections", set()):
            book = section_to_book.get(section_id)
            if book:
                effort_domains[safe_domain(book.get("domain"))]["section_ids"].add(section_id)
    for section_id, (_, markdown) in note_files.items():
        book = section_to_book.get(section_id)
        if not book:
            continue
        entry = effort_domains[safe_domain(book.get("domain"))]
        entry["note_count"] += 1
        entry["note_characters"] += len(markdown)

    attempts = load_practice_store("attempts").get("items", {})
    analyses = load_practice_store("analyses").get("items", {})
    practice_items = [item for item in attempts.values() if isinstance(item, dict)] if isinstance(attempts, dict) else []
    analysis_items = [item for item in analyses.values() if isinstance(item, dict) and str(item.get("content") or "").strip()] if isinstance(analyses, dict) else []
    practice_summary = {
        "answered_count": len(practice_items),
        "correct_count": sum(1 for item in practice_items if item.get("correct") is True),
        "analysis_count": len(analysis_items),
        "analysis_characters": sum(len(str(item.get("content") or "").strip()) for item in analysis_items),
    }
    notebook_summary = {"week_count": 0, "character_count": 0}
    for path in english_notebook_files().values():
        try:
            content = path.read_text(encoding="utf-8-sig").strip()
        except OSError:
            continue
        if content:
            notebook_summary["week_count"] += 1
            notebook_summary["character_count"] += len(content)
    effort_summary = {
        "reading_domains": [
            {
                "key": domain,
                "label": entry["label"],
                "reading_seconds": entry["reading_seconds"],
                "section_count": len(entry["section_ids"]),
                "note_count": entry["note_count"],
                "note_characters": entry["note_characters"],
            }
            for domain, entry in effort_domains.items()
        ],
        "practice": practice_summary,
        "notebook": notebook_summary,
    }

    last_section_id = resolve_for_catalog(activity.get("last_section_id")) or ""
    if not last_section_id and note_files:
        last_section_id = max(note_files, key=lambda item: note_files[item][0].stat().st_mtime)
    last_section = None
    if last_section_id in sections:
        section = sections[last_section_id]
        book = section_to_book.get(last_section_id, {})
        last_section = {
            "id": last_section_id,
            "title": section.get("title", ""),
            "chapter_title": section.get("chapter_title", ""),
            "book_id": book.get("id", ""),
            "book_title": section.get("book_title") or book.get("title", ""),
        }

    today_value = days.get(today.isoformat(), empty_day())
    all_activity_days = set(days) | set(unified_by_day)
    active_days = sum(1 for day in all_activity_days if active_day(day, days.get(day, {})))
    total_reading_seconds = sum(day_seconds(value) for value in days.values())
    activity_totals = {activity_type: 0 for activity_type in sorted(ACTIVITY_TYPES)}
    activity_counts = {activity_type: 0 for activity_type in sorted(ACTIVITY_TYPES)}
    raw_activity_totals = unified_payload.get("by_activity_type", {})
    for item in unified_activities:
        activity_type = str(item.get("activity_type") or "")
        if activity_type not in activity_totals:
            continue
        activity_totals[activity_type] += max(0, int(item.get("duration_seconds") or 0))
        activity_counts[activity_type] += 1
    raw_domain_totals = unified_payload.get("by_domain", {})
    activity_domain_totals = {domain: 0 for domain in DOMAIN_LABELS}
    activity_domain_totals["other"] = 0
    activity_domain_counts = {domain: 0 for domain in DOMAIN_LABELS}
    activity_domain_counts["other"] = 0
    for item in unified_activities:
        domain = str(item.get("domain") or "")
        domain_key = domain if domain in DOMAIN_LABELS else "other"
        activity_domain_totals[domain_key] += max(0, int(item.get("duration_seconds") or 0))
        activity_domain_counts[domain_key] += 1
    total_activity_seconds = sum(activity_totals.values())
    unified_reading_seconds = activity_totals["read"]
    raw_unified_reading_seconds = max(0, int(raw_activity_totals.get("read") or 0))
    legacy_unmapped_reading_seconds = max(0, total_reading_seconds - raw_unified_reading_seconds)
    total_note_characters = sum(len(markdown) for _, markdown in note_files.values())
    return {
        "today": today.isoformat(),
        "weeks": weeks,
        "days": heatmap_days,
        "max": max((item["count"] for item in heatmap_days if not item["future"]), default=0),
        "heatmap_total_seconds": sum(item["activity_seconds"] for item in heatmap_days if not item["future"]),
        "book_count": len(books),
        "section_count": len(sections),
        "noted_section_count": len(note_files),
        "note_character_count": total_note_characters,
        "note_coverage": round((len(note_files) / len(sections) * 100) if sections else 0, 1),
        "review_day_count": sum(1 for value in days.values() if value["review_saved"]),
        "active_day_count": active_days,
        "streak": streak,
        # Keep the old field as a compatibility reference. New consumers use
        # total_activity_seconds, whose type/domain totals explain the sum.
        "total_reading_seconds": total_reading_seconds,
        "unified_reading_seconds": unified_reading_seconds,
        "legacy_unmapped_reading_seconds": legacy_unmapped_reading_seconds,
        "activity_count": len(unified_activities),
        "activity_totals": activity_totals,
        "activity_counts": activity_counts,
        "activity_domain_totals": activity_domain_totals,
        "activity_domain_counts": activity_domain_counts,
        "activity_domain_totals_raw": raw_domain_totals,
        "activity_type_totals_raw": raw_activity_totals,
        "total_activity_seconds": total_activity_seconds,
        "total_learning_seconds": total_activity_seconds,
        "today_reading_seconds": day_seconds(today_value),
        "today_unified_reading_seconds": activity_type_seconds(today.isoformat(), "read"),
        "today_legacy_unmapped_reading_seconds": max(0, day_seconds(today_value) - raw_activity_type_seconds(today.isoformat(), "read")),
        "today_activity_seconds": activity_seconds(today.isoformat()),
        "today_activity_count": len(today_activities),
        "today_activities": today_activities[-8:],
        "continue_activity": continuation,
        "continue_target": continuation.get("resume_target") if continuation else (last_section and {"view": "reader", "resource_id": last_section.get("book_id", ""), "item_id": last_section.get("id", "")}),
        "review_pending": review_pending,
        "recent_resources": recent_resources,
        "today_section_opens": int(today_value["section_opens"]),
        "today_section_count": len(today_value["sections"]),
        "today_note_count": len(today_value["notes"]),
        "today_review_saved": bool(today_value["review_saved"]),
        "last_section": last_section,
        "book_distribution": book_distribution,
        "effort_summary": effort_summary,
    }


def book_learning_summary(book: dict, sections: dict[str, dict]) -> dict:
    """Per-resource learning facts derived only from local activity and notes.

    Reads stable section ids, activity.json and note filenames, never book content.
    """
    book_id = str(book.get("id") or "")
    section_ids = {str(item.get("id")) for item in book.get("sections", [])}
    known_section_ids = set(sections)

    def resolve_for_catalog(value: object) -> str | None:
        return resolve_section_id(value, known_section_ids)

    activity = load_activity()
    raw_days = activity.get("days") if isinstance(activity.get("days"), dict) else {}
    learned: set[str] = set()
    reading_seconds = 0
    last_day = ""
    last_day_time = ""
    last_section_id = ""
    for day, value in raw_days.items():
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(day)) or not isinstance(value, dict):
            continue
        day_sections = {
            resolved
            for item in (value.get("sections") if isinstance(value.get("sections"), list) else [])
            if (resolved := resolve_for_catalog(item)) in section_ids
        }
        day_notes = {
            resolved
            for item in (value.get("notes") if isinstance(value.get("notes"), list) else [])
            if (resolved := resolve_for_catalog(item)) in section_ids
        }
        learned |= day_sections | day_notes
        per_section = value.get("section_reading_seconds")
        if isinstance(per_section, dict):
            for section_id, seconds in per_section.items():
                resolved = resolve_for_catalog(section_id)
                if resolved in section_ids:
                    reading_seconds += max(0, int(seconds or 0))
        day_last = str(value.get("last_section_id") or "")
        resolved_day_last = resolve_for_catalog(day_last)
        day_last_time = str(value.get("last_reading_at") or "")
        if day_sections or day_notes or resolved_day_last in section_ids:
            if not last_day or day >= last_day:
                last_day = day
                last_day_time = day_last_time
                if resolved_day_last in section_ids:
                    last_section_id = resolved_day_last
    note_count = 0
    for section_id in section_note_records(sections):
        if section_id in section_ids:
            note_count += 1
            learned.add(section_id)
    if not last_section_id:
        global_last = resolve_for_catalog(activity.get("last_section_id"))
        if global_last in section_ids:
            last_section_id = global_last
    last_section = None
    if last_section_id and last_section_id in sections:
        section = sections[last_section_id]
        last_section = {
            "id": last_section_id,
            "title": str(section.get("title") or ""),
            "chapter_title": str(section.get("chapter_title") or ""),
            "chapter_order": int(section.get("chapter_order") or 0),
            "section_order": int(section.get("section_order") or 0),
        }
    section_count = len(book.get("sections", []))
    return {
        "book_id": book_id,
        "last_section": last_section,
        "last_studied_at": last_day_time,
        "last_studied_day": last_day,
        "learned_section_count": len(learned),
        "section_count": section_count,
        "note_count": note_count,
        "reading_seconds": reading_seconds,
        "progress": round(len(learned) / section_count * 100, 1) if section_count else 0.0,
    }


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
            if str(analysis.get("content") or "").strip():
                body_lines.extend(["", "#### 个人解析", "", str(analysis["content"]).strip()])
            add_source(
                source_type="objective_practice",
                domain=domain,
                subject_id=subject_id,
                resource_id=resource_id,
                item_id=item_id,
                title=f"第 {question_number} 题" if question_number else f"题目 {item_id}",
                markdown="\n".join(body_lines),
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
                if str(focus_progress.get("answer") or "").strip():
                    body_lines.extend(["#### 我的作答", "", str(focus_progress["answer"]).strip()])
                if str(focus_progress.get("memory_note") or "").strip():
                    body_lines.extend(["", "#### 漏点与记忆", "", str(focus_progress["memory_note"]).strip()])
                add_source(
                    source_type="subjective_practice",
                    domain="medicine",
                    subject_id=(focus.get("subject") or {}).get("title") or subject_id,
                    resource_id=resource_id,
                    item_id=item_id,
                    title=str(focus.get("title") or "口腔重点题"),
                    markdown="\n".join(body_lines) or "- 已进入口腔重点题，个人作答仍保留在重点学习记录中。",
                    duration_seconds=duration,
                    resume_target={"view": "oral_focus", "resource_id": resource_id, "item_id": item_id},
                )
                continue
            response = load_subjective_response(str(item_id))
            section = sections.get(str(item_id), {})
            body_lines: list[str] = []
            if str(response.get("answer") or "").strip():
                body_lines.extend(["#### 我的作答", "", str(response["answer"]).strip()])
            if str(response.get("reflection") or "").strip():
                body_lines.extend(["", "#### 反思", "", str(response["reflection"]).strip()])
            add_source(
                source_type="subjective_practice",
                domain=domain,
                subject_id=subject_id,
                resource_id=resource_id,
                item_id=item_id,
                title=str(section.get("title") or response.get("title") or "主观题"),
                markdown="\n".join(body_lines) or "- 已保存主观题活动，答案仍保留在原始作答文件。",
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
            add_source(
                source_type="notebook",
                domain="english",
                subject_id="英语笔记",
                resource_id="english-notebook",
                item_id=item_id,
                title=f"{item_id} · 英语周记",
                markdown=_review_snippet(_english_notebook_day_markdown(content, day)),
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
    result = {
        "review_date": day,
        "review_note_date": date.today().isoformat(),
        "note_count": sum(1 for source in sources if source.get("source_type") == "section_note"),
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
        has_summary = bool(str((unified_result or {}).get("summary") or "").strip()) or bool((unified_result or {}).get("no_text"))
        if not has_summary:
            has_summary = bool(str(legacy_state.get("summary") or "").strip())
        entries.append(
            {
                "date": day,
                "subject_count": max(activity_subject_count(day), sum(1 for value in results.values() if str(value).strip())),
                "character_count": len(content),
                "has_summary": has_summary,
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
        "duration_seconds": sum(item["duration_seconds"] for item in daily_records),
        "activity_by_type": weekly_type_totals,
        "activity_by_domain": weekly_domain_totals,
        "source_markdown": source,
        "report": report,
        "legacy_report": legacy_report if report_path else "",
        "legacy_report_path": str(archive_target(week, "weekly")[0]) if legacy_report and report_path else "",
        "storage": storage,
        "path": str(target),
        "obsidian_uri": uri,
    }


def english_notebook_target(week: str) -> tuple[Path, str, str]:
    """Resolve one weekly English notebook without touching book notes or logs."""
    week_bounds(week)  # validate before using the value in a filename
    local_target = ENGLISH_NOTEBOOK_DIR / f"{week}.md"
    relative = Path("YuReader") / "英语周记" / f"{week}.md"
    vault = obsidian_vault()
    if not vault:
        return local_target, "local", ""
    target = (vault / relative).resolve()
    if vault != target and vault not in target.parents:
        raise ValueError("English notebook path escapes Obsidian vault")
    uri = f"obsidian://open?vault={quote(vault.name)}&file={quote(relative.as_posix())}"
    return target, "obsidian", uri


def english_notebook_files() -> dict[str, Path]:
    """List weekly English notebooks, preferring the configured Obsidian copy."""
    files: dict[str, Path] = {}
    if ENGLISH_NOTEBOOK_DIR.is_dir():
        files.update({path.stem: path for path in ENGLISH_NOTEBOOK_DIR.glob("*.md") if re.fullmatch(r"\d{4}-W\d{2}", path.stem)})
    vault = obsidian_vault()
    remote = vault / "YuReader" / "英语周记" if vault else None
    if remote and remote.is_dir():
        files.update({path.stem: path for path in remote.glob("*.md") if re.fullmatch(r"\d{4}-W\d{2}", path.stem)})
    return files


def english_notebook_payload(week: str = "") -> dict:
    """Return the selected weekly notebook and its lightweight archive index."""
    if not week:
        year, number, _ = date.today().isocalendar()
        week = f"{year}-W{number:02d}"
    start, end = week_bounds(week)
    files = english_notebook_files()
    source = files.get(week)
    content = ""
    if source:
        try:
            content = source.read_text(encoding="utf-8-sig")
        except OSError:
            content = ""
    target, storage, uri = english_notebook_target(week)
    archives: list[dict] = []
    for archived_week, path in sorted(files.items(), reverse=True):
        try:
            archived_content = path.read_text(encoding="utf-8-sig").strip()
            updated_at = datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")
        except OSError:
            continue
        archived_start, archived_end = week_bounds(archived_week)
        archives.append(
            {
                "week": archived_week,
                "start": archived_start.isoformat(),
                "end": archived_end.isoformat(),
                "character_count": len(archived_content),
                "updated_at": updated_at,
                "current": archived_week == week,
            }
        )
    today = date.today()
    current_year, current_number, _ = today.isocalendar()
    current_week = f"{current_year}-W{current_number:02d}"
    return {
        "week": week,
        "current_week": current_week,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "today": today.isoformat(),
        "today_weekday": today.weekday(),
        "content": content,
        "character_count": len(content.strip()),
        "storage": storage,
        "path": str(target),
        "obsidian_uri": uri,
        "archives": archives,
    }


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
            self.send_json(
                {
                    **section,
                    "note": current_note,
                    "note_storage": note_storage,
                    "obsidian_uri": note_uri,
                    "requested_section_id": requested_section_id,
                    "resolved_from_alias": requested_section_id != section["id"],
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
            self.send_text(candidate.read_bytes(), content_type)
            return
        self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path not in {"/api/notes", "/api/review-summary", "/api/weekly-summary", "/api/english-notebook", "/api/oral-focus/progress", "/api/activity", "/api/activity/heartbeat", "/api/reading-time", "/api/practice/answer", "/api/practice/analysis", "/api/subjective/response"}:
            self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
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
                item = oral_focus_item_payload(item_id)
                saved = save_oral_focus_progress(item_id, answer, memory_note, mastery)
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
            if parsed.path == "/api/practice/answer":
                bank_id = str(body.get("bank_id") or "")
                question_id = str(body.get("question_id") or "")
                selected = body.get("selected_answers")
                if not isinstance(selected, list) or not selected:
                    raise ValueError("select at least one answer")
                question = next((item for item in load_bank_questions(bank_id) if item["question_id"] == question_id), None)
                if not question:
                    raise ValueError("question not found")
                labels = {str(option.get("label")) for option in question.get("options") or [] if isinstance(option, dict)}
                selected_answers = sorted({str(item).strip() for item in selected if str(item).strip()})
                if not selected_answers or any(item not in labels for item in selected_answers):
                    raise ValueError("invalid selected answer")
                correct_answers = sorted(str(item) for item in question.get("correct_answers") or [])
                with PRACTICE_LOCK:
                    payload = load_practice_store("attempts")
                    payload.setdefault("items", {})[question_id] = {"bank_id": bank_id, "selected_answers": selected_answers, "correct": selected_answers == correct_answers, "answered_at": datetime.now().astimezone().isoformat(timespec="seconds")}
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
                question = next((item for item in load_bank_questions(bank_id) if item["question_id"] == question_id), None)
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
