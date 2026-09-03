"""Obsidian vault integration, section note mirroring, and markdown targets."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from yureader.config import (
    ROOT,
    DATA_DIR,
    NOTES_DIR,
    REVIEWS_DIR,
    WEEKLY_DIR,
    LOGS_DIR,
    ENGLISH_NOTEBOOK_DIR,
    DOMAIN_LABELS,
)
from yureader.utils import (
    safe_domain,
    safe_note_component,
    atomic_write,
)
from yureader.catalog import (
    resolve_section_id,
    section_aliases_for,
    load_section_aliases,
)

def _get_week_bounds(week: str):
    from yureader.review import week_bounds
    return week_bounds(week)

def _get_load_activity():
    from yureader.activity import load_activity
    return load_activity()

def note_path(section_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", section_id):
        raise ValueError("invalid section id")
    return NOTES_DIR / f"{section_id}.md"



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
    payload = _get_load_activity()
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
    _get_week_bounds(week)
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



# English notebook routines
def english_notebook_target(week: str) -> tuple[Path, str, str]:
    """Resolve one weekly English notebook without touching book notes or logs."""
    _get_week_bounds(week)  # validate before using the value in a filename
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
    start, end = _get_week_bounds(week)
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
        archived_start, archived_end = _get_week_bounds(archived_week)
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


