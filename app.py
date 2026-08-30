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


ROOT = Path(__file__).resolve().parent
CONTENT_DIR = Path(os.environ.get("YUREADER_CONTENT_DIR", ROOT / "content")).resolve()
QUESTION_BANK_DIR = Path(os.environ.get("YUREADER_QUESTION_BANK_DIR", ROOT / "question-banks")).resolve()
DATA_DIR = Path(os.environ.get("YUREADER_DATA_DIR", ROOT / "data")).resolve()
NOTES_DIR = DATA_DIR / "notes"
REVIEWS_DIR = DATA_DIR / "reviews"
REVIEW_WORKFLOW_DIR = DATA_DIR / "review-workflow"
LOGS_DIR = DATA_DIR / "logs"
WEEKLY_DIR = DATA_DIR / "weekly-reports"
ACTIVITY_PATH = DATA_DIR / "activity.json"
STATIC_DIR = ROOT / "static"
HOST = "127.0.0.1"
VERSION = "0.10.0"
REVIEW_PAGE_CHARACTERS = 5000
DOMAIN_LABELS = {"medicine": "医学", "politics": "政治", "english": "英语"}
VALID_DOMAINS = set(DOMAIN_LABELS)
RESOURCE_TYPE_LABELS = {"book": "教材", "lecture": "讲义", "question_bank": "题库", "reference": "参考资料"}
VALID_RESOURCE_TYPES = set(RESOURCE_TYPE_LABELS)
FIRST_CHAPTER_TITLE = re.compile(
    r"^\s*(?:第[0-9０-９一二三四五六七八九十百千万零〇两]+章(?:\s|$)|"
    r"chapter\s*(?:1|one)\b)",
    re.IGNORECASE,
)
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
# Read-only image assets are served per published book package.  BOOK_ASSETS
# records the manifest-declared asset names and SHA-256 file list for each
# book_id so the /api/book-assets endpoint can only expose files that a
# published package explicitly declares.  Keys are book ids.
BOOK_ASSETS: dict[str, dict] = {}


def safe_domain(value: object) -> str:
    domain = str(value or "medicine").strip().lower()
    return domain if domain in VALID_DOMAINS else "medicine"


def safe_resource_type(value: object) -> str:
    resource_type = str(value or "book").strip().lower()
    return resource_type if resource_type in VALID_RESOURCE_TYPES else "book"


def stable_id(relative_path: str, offset: int) -> str:
    value = f"{relative_path}\0{offset}".encode("utf-8")
    return hashlib.sha1(value).hexdigest()[:12]


def first_title(markdown: str, fallback: str) -> str:
    match = re.search(r"^#\s+(.+?)\s*$", markdown, re.MULTILINE)
    return match.group(1).strip() if match else fallback


def starts_at_first_chapter(title: str) -> bool:
    """Reject packages that expose preface material as formal book content."""
    return bool(FIRST_CHAPTER_TITLE.search(str(title or "").strip()))


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
                "title": str(bank.get("title") or bank_id),
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
        "scope": question.get("scope"), "unit": question.get("unit"), "unit_label": question.get("unit_label"),
        "local_number": question.get("local_number"), "stem_md": question.get("stem_md") or "",
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
        items.append({"question_id": question["question_id"], "local_number": question.get("local_number"), "question_type": question.get("question_type"), "answered": bool(attempt), "correct": attempt.get("correct") if isinstance(attempt, dict) else None})
    return {"bank": {key: bank[key] for key in ("id", "title", "subject", "domain")}, "knowledge_id": knowledge_id, "match_level": match_level, "questions": items, "answered_count": sum(1 for item in items if item["answered"]), "question_count": len(items)}


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


def safe_note_component(value: object, fallback: str) -> str:
    """Produce a human-readable, Windows-safe folder/file component."""
    cleaned = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "-", str(value or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-")
    return (cleaned[:80].rstrip(" .-") or fallback)


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


def atomic_write(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(content + ("\n" if content else ""), encoding="utf-8")
    temporary.replace(target)


def load_activity() -> dict:
    try:
        payload = json.loads(ACTIVITY_PATH.read_text(encoding="utf-8-sig"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _record_activity(kind: str, section_id: str = "", character_count: int = 0, reading_seconds: int = 0) -> None:
    if kind not in {"section_open", "note_save", "review_save", "reading_time"}:
        raise ValueError("invalid activity kind")
    payload = load_activity()
    payload["schema_version"] = 1
    days = payload.setdefault("days", {})
    today = date.today().isoformat()
    daily = days.setdefault(today, {"section_opens": 0, "sections": [], "notes": [], "review_saved": False})
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
    cutoff = (date.today() - timedelta(days=400)).isoformat()
    payload["days"] = {day: value for day, value in days.items() if day >= cutoff}
    atomic_write(ACTIVITY_PATH, json.dumps(payload, ensure_ascii=False, indent=2))


def record_activity(kind: str, section_id: str = "", character_count: int = 0, reading_seconds: int = 0) -> None:
    with ACTIVITY_LOCK:
        _record_activity(kind, section_id, character_count, reading_seconds)


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


def save_workflow_state(day: str, payload: dict) -> None:
    payload["schema_version"] = 1
    payload["learning_date"] = day
    payload["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    atomic_write(workflow_state_path(day), json.dumps(payload, ensure_ascii=False, indent=2))


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


def write_daily_log(day: str, subjects: list[dict], summary: str) -> tuple[Path, str, str, str]:
    content = daily_log_markdown(day, subjects, summary)
    target, storage, uri = archive_target(day, "daily")
    atomic_write(target, content)
    return target, storage, uri, content


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
    return {
        "date": selected["date"],
        "seconds": selected["seconds"],
        "minutes": selected["minutes"],
        "last_reading_at": selected["last_reading_at"],
        "history": history,
        "source": "YuReader local active reading timer",
        "idle_timeout_seconds": 600,
    }


def learning_stats(books: list[dict], sections: dict[str, dict], weeks: int = 12) -> dict:
    activity = load_activity()
    raw_days = activity.get("days") if isinstance(activity.get("days"), dict) else {}
    days: dict[str, dict] = {}
    for day, value in raw_days.items():
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(day)) or not isinstance(value, dict):
            continue
        days[str(day)] = {
            "section_opens": max(0, int(value.get("section_opens") or 0)),
            "sections": set(str(item) for item in value.get("sections", []) if str(item) in sections),
            "notes": set(str(item) for item in value.get("notes", []) if str(item) in sections),
            "review_saved": bool(value.get("review_saved")),
            "note_characters": max(0, int(value.get("note_characters") or 0)),
            "reading_seconds": max(0, int(value.get("reading_seconds") or 0)),
        }

    note_files: dict[str, tuple[Path, str]] = {}
    if NOTES_DIR.is_dir():
        for path in NOTES_DIR.glob("*.md"):
            if path.stem not in sections:
                continue
            try:
                markdown = path.read_text(encoding="utf-8-sig").strip()
            except OSError:
                continue
            if not markdown:
                continue
            note_files[path.stem] = (path, markdown)
            day = date.fromtimestamp(path.stat().st_mtime).isoformat()
            daily = days.setdefault(day, {"section_opens": 0, "sections": set(), "notes": set(), "review_saved": False, "note_characters": 0, "reading_seconds": 0})
            daily["notes"].add(path.stem)
            daily["note_characters"] += len(markdown)

    for day, path in review_note_files().items():
        try:
            if not path.read_text(encoding="utf-8-sig").strip():
                continue
        except OSError:
            continue
        daily = days.setdefault(day, {"section_opens": 0, "sections": set(), "notes": set(), "review_saved": False, "note_characters": 0, "reading_seconds": 0})
        daily["review_saved"] = True

    def day_seconds(value: dict) -> int:
        return max(0, int(value.get("reading_seconds") or 0))

    today = date.today()
    start = today - timedelta(days=today.weekday() + (weeks - 1) * 7)
    heatmap_days: list[dict] = []
    for offset in range(weeks * 7):
        current = start + timedelta(days=offset)
        value = days.get(current.isoformat(), {"section_opens": 0, "sections": set(), "notes": set(), "review_saved": False, "note_characters": 0, "reading_seconds": 0})
        heatmap_days.append(
            {
                "date": current.isoformat(),
                "count": day_seconds(value),
                "reading_seconds": day_seconds(value),
                "reading_minutes": round(day_seconds(value) / 60, 1),
                "section_opens": int(value["section_opens"]),
                "section_count": len(value["sections"]),
                "note_count": len(value["notes"]),
                "review_saved": bool(value["review_saved"]),
                "future": current > today,
            }
        )

    streak_anchor = today
    if day_seconds(days.get(today.isoformat(), {})) == 0:
        streak_anchor -= timedelta(days=1)
    streak = 0
    while day_seconds(days.get(streak_anchor.isoformat(), {})) > 0:
        streak += 1
        streak_anchor -= timedelta(days=1)

    section_to_book = {section["id"]: book for book in books for section in book.get("sections", [])}
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

    last_section_id = str(activity.get("last_section_id") or "")
    if last_section_id not in sections and note_files:
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

    today_value = days.get(today.isoformat(), {"section_opens": 0, "sections": set(), "notes": set(), "review_saved": False, "note_characters": 0, "reading_seconds": 0})
    active_days = sum(1 for value in days.values() if day_seconds(value) > 0)
    total_reading_seconds = sum(day_seconds(value) for value in days.values())
    total_note_characters = sum(len(markdown) for _, markdown in note_files.values())
    return {
        "today": today.isoformat(),
        "weeks": weeks,
        "days": heatmap_days,
        "max": max((item["count"] for item in heatmap_days if not item["future"]), default=0),
        "heatmap_total_seconds": sum(item["reading_seconds"] for item in heatmap_days if not item["future"]),
        "book_count": len(books),
        "section_count": len(sections),
        "noted_section_count": len(note_files),
        "note_character_count": total_note_characters,
        "note_coverage": round((len(note_files) / len(sections) * 100) if sections else 0, 1),
        "review_day_count": sum(1 for value in days.values() if value["review_saved"]),
        "active_day_count": active_days,
        "streak": streak,
        "total_reading_seconds": total_reading_seconds,
        "today_reading_seconds": day_seconds(today_value),
        "today_section_opens": int(today_value["section_opens"]),
        "today_section_count": len(today_value["sections"]),
        "today_note_count": len(today_value["notes"]),
        "today_review_saved": bool(today_value["review_saved"]),
        "last_section": last_section,
        "book_distribution": book_distribution,
    }


def book_learning_summary(book: dict, sections: dict[str, dict]) -> dict:
    """Per-resource learning facts derived only from local activity and notes.

    Reads stable section ids, activity.json and note filenames, never book content.
    """
    book_id = str(book.get("id") or "")
    section_ids = {str(item.get("id")) for item in book.get("sections", [])}
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
        day_sections = {str(item) for item in value.get("sections", []) if str(item) in section_ids}
        day_notes = {str(item) for item in value.get("notes", []) if str(item) in section_ids}
        learned |= day_sections | day_notes
        per_section = value.get("section_reading_seconds")
        if isinstance(per_section, dict):
            for section_id, seconds in per_section.items():
                if str(section_id) in section_ids:
                    reading_seconds += max(0, int(seconds or 0))
        day_last = str(value.get("last_section_id") or "")
        day_last_time = str(value.get("last_reading_at") or "")
        if day_sections or day_notes or day_last in section_ids:
            if not last_day or day >= last_day:
                last_day = day
                last_day_time = day_last_time
                if day_last in section_ids:
                    last_section_id = day_last
    note_count = 0
    if NOTES_DIR.is_dir():
        for path in NOTES_DIR.glob("*.md"):
            if path.stem not in section_ids:
                continue
            try:
                markdown = path.read_text(encoding="utf-8-sig").strip()
            except OSError:
                continue
            if markdown:
                note_count += 1
                learned.add(path.stem)
    if not last_section_id:
        global_last = str(activity.get("last_section_id") or "")
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


def review_payload(day: str, books: list[dict], sections: dict[str, dict]) -> dict:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("invalid date")
    target_day = date.fromisoformat(day)
    note_sources: dict[str, Path] = {}
    if NOTES_DIR.is_dir():
        for path in NOTES_DIR.glob("*.md"):
            if date.fromtimestamp(path.stat().st_mtime) == target_day:
                note_sources[path.stem] = path

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
    section_seconds = day_activity.get("section_reading_seconds") if isinstance(day_activity.get("section_reading_seconds"), dict) else {}
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


def logs_payload(selected_day: str = "") -> dict:
    daily_files = archive_files("daily")
    entries: list[dict] = []
    for day, path in sorted(daily_files.items(), reverse=True):
        try:
            content = path.read_text(encoding="utf-8-sig").strip()
        except OSError:
            continue
        state = load_workflow_state(day)
        results = state.get("subjects") if isinstance(state.get("subjects"), dict) else {}
        entries.append(
            {
                "date": day,
                "subject_count": sum(1 for value in results.values() if str(value).strip()),
                "character_count": len(content),
                "has_summary": bool(str(state.get("summary") or "").strip()),
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
            }
        )
    detail = None
    if selected_day:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", selected_day):
            raise ValueError("invalid date")
        path = daily_files.get(selected_day)
        if path:
            target, storage, uri = archive_target(selected_day, "daily")
            detail = {
                "date": selected_day,
                "content": path.read_text(encoding="utf-8-sig"),
                "storage": storage,
                "path": str(target),
                "obsidian_uri": uri,
            }
    weekly_entries = []
    for week, path in sorted(archive_files("weekly").items(), reverse=True):
        try:
            content = path.read_text(encoding="utf-8-sig").strip()
        except OSError:
            continue
        weekly_entries.append(
            {
                "week": week,
                "character_count": len(content),
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
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


def weekly_payload(week: str = "") -> dict:
    if not week:
        # 周一等边界日期优先打开最近一个真正有日报总结的周期，避免空白周报。
        summarized_days = [
            day for day in archive_files("daily")
            if str(load_workflow_state(day).get("summary") or "").strip()
        ]
        anchor = date.fromisoformat(max(summarized_days)) if summarized_days else date.today()
        year, number, _ = anchor.isocalendar()
        week = f"{year}-W{number:02d}"
    start, end = week_bounds(week)
    summaries = []
    for offset in range(7):
        day = (start + timedelta(days=offset)).isoformat()
        summary = str(load_workflow_state(day).get("summary") or "").strip()
        if summary:
            summaries.append({"date": day, "summary": summary})
    state_path = REVIEW_WORKFLOW_DIR / f"{week}.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        state = {}
    report = str(state.get("summary") or "")
    source_lines = [f"# {week} 每日总结汇编"]
    for item in summaries:
        source_lines.extend(["", f"## {item['date']}", "", item["summary"]])
    source = "\n".join(source_lines)
    target, storage, uri = archive_target(week, "weekly")
    return {
        "week": week,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "day_count": len(summaries),
        "summaries": summaries,
        "source_markdown": source,
        "report": report,
        "storage": storage,
        "path": str(target),
        "obsidian_uri": uri,
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
        books, sections = catalog()
        question_banks = question_bank_catalog()
        if path == "/api/bootstrap":
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
            self.send_json({"banks": question_banks, "count": len(question_banks)})
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
        if path == "/api/practice/question":
            try:
                query = parse_qs(parsed.query)
                self.send_json(practice_question(query.get("bank_id", [""])[0], query.get("question_id", [""])[0]))
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
        if path == "/api/reviews":
            try:
                requested = parse_qs(parsed.query).get("date", [""])[0]
                review_day = requested or (date.today() - timedelta(days=1)).isoformat()
                self.send_json(review_payload(review_day, books, sections))
            except (ValueError, OSError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/api/sections/"):
            section = sections.get(path.rsplit("/", 1)[-1])
            if not section:
                self.send_json({"error": "section not found"}, HTTPStatus.NOT_FOUND)
                return
            current_note = ""
            try:
                note = note_path(section["id"])
                if note.is_file():
                    current_note = note.read_text(encoding="utf-8-sig")
            except ValueError:
                pass
            book = next((item for item in books if any(entry["id"] == section["id"] for entry in item.get("sections", []))), None)
            note_storage, note_uri = "local", ""
            if book:
                _, note_storage, note_uri = ensure_section_note_mirror(book, section, current_note)
            self.send_json({**section, "note": current_note, "note_storage": note_storage, "obsidian_uri": note_uri})
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
        if parsed.path not in {"/api/notes", "/api/review-notes", "/api/review-subject", "/api/review-summary", "/api/weekly-summary", "/api/activity", "/api/reading-time", "/api/practice/answer", "/api/practice/analysis"}:
            self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
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
                self.send_json({"ok": True, "saved": bool(content), "path": str(target), "storage": storage, "obsidian_uri": uri})
                return
            if parsed.path in {"/api/review-subject", "/api/review-summary"}:
                review_day = str(body.get("date") or "")
                books, sections = catalog()
                review = review_payload(review_day, books, sections)
                state = load_workflow_state(review_day)
                state_subjects = state.setdefault("subjects", {})
                if parsed.path == "/api/review-subject":
                    book_id = str(body.get("book_id") or "")
                    allowed = {subject["book_id"] for subject in review["subjects"]}
                    if book_id not in allowed:
                        raise ValueError("review subject not found")
                    state_subjects[book_id] = str(body.get("content") or "").replace("\r\n", "\n").strip()
                else:
                    if not review["all_complete"]:
                        raise ValueError("complete every subject before writing the daily summary")
                    state["summary"] = str(body.get("content") or "").replace("\r\n", "\n").strip()
                save_workflow_state(review_day, state)
                refreshed = review_payload(review_day, books, sections)
                target, storage, uri, content = write_daily_log(review_day, refreshed["subjects"], refreshed["daily_summary"])
                if content.strip():
                    record_activity("review_save")
                self.send_json({"ok": True, "review": refreshed, "storage": storage, "path": str(target), "obsidian_uri": uri})
                return
            if parsed.path == "/api/weekly-summary":
                week = str(body.get("week") or "")
                content = str(body.get("content") or "").replace("\r\n", "\n").strip()
                payload = weekly_payload(week)
                state_path = REVIEW_WORKFLOW_DIR / f"{week}.json"
                atomic_write(state_path, json.dumps({"schema_version": 1, "week": week, "summary": content, "updated_at": datetime.now().astimezone().isoformat(timespec="seconds")}, ensure_ascii=False, indent=2))
                target, storage, uri = archive_target(week, "weekly")
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
            if parsed.path == "/api/reading-time":
                section_id = str(body.get("section_id") or "").strip()
                seconds = int(body.get("seconds") or 0)
                if not section_id or len(section_id) > 160 or not re.fullmatch(r"[\w.-]+", section_id):
                    raise ValueError("invalid section_id")
                if seconds < 1 or seconds > 600:
                    raise ValueError("seconds must be between 1 and 600")
                record_activity("reading_time", section_id, reading_seconds=seconds)
                self.send_json({"ok": True, "seconds": seconds, "today": reading_time_payload()})
                return
            if parsed.path == "/api/activity":
                section_id = str(body.get("section_id") or "")
                _, sections = catalog()
                if section_id not in sections:
                    raise ValueError("section not found")
                record_activity("section_open", section_id)
                self.send_json({"ok": True, "section_id": section_id})
                return
            if parsed.path == "/api/review-notes":
                review_day = str(body.get("date") or date.today().isoformat())
                if review_day != date.today().isoformat():
                    raise ValueError("review note date must be today")
                content = str(body.get("content") or "").replace("\r\n", "\n").strip()
                review_target, review_storage, obsidian_uri = daily_review_target(review_day)
                atomic_write(review_target, content)
                if content:
                    record_activity("review_save")
                self.send_json(
                    {
                        "ok": True,
                        "saved": bool(content),
                        "date": review_day,
                        "storage": review_storage,
                        "path": str(review_target),
                        "obsidian_uri": obsidian_uri,
                    }
                )
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
