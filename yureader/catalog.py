"""Catalog discovery, manifest loading, asset verification, and section aliases."""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from yureader.config import (
    ROOT,
    CONTENT_DIR,
    DATA_DIR,
    QUESTION_BANK_DIR,
    DOMAIN_LABELS,
    RESOURCE_TYPE_LABELS,
    BOOK_ASSETS,
    CATALOG_LOCK,
    CATALOG_CACHE,
    CATALOG_RECHECK_SECONDS,
    QUESTION_BANK_LOCK,
    QUESTION_BANK_CACHE,
)
from yureader.utils import (
    safe_domain,
    safe_resource_type,
    stable_id,
    first_title,
    starts_at_first_chapter,
)

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



def question_bank_by_id(bank_id: str) -> dict | None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", bank_id):
        return None
    return next((bank for bank in question_bank_catalog() if bank["id"] == bank_id), None)



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


