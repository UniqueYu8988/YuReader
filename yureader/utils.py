"""Pure path and text helpers shared by the YuReader runtime."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


VALID_DOMAINS = frozenset({"medicine", "politics", "english"})
VALID_RESOURCE_TYPES = frozenset({"book", "lecture", "question_bank", "reference"})
FIRST_CHAPTER_TITLE = re.compile(
    r"^\s*(?:第[0-9０-９一二三四五六七八九十百千万零〇两]+章(?:\s|$)|"
    r"chapter\s*(?:1|one)\b)",
    re.IGNORECASE,
)


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


def safe_note_component(value: object, fallback: str) -> str:
    """Produce a human-readable, Windows-safe folder/file component."""
    cleaned = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "-", str(value or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-")
    return cleaned[:80].rstrip(" .-") or fallback


def atomic_write(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(content + ("\n" if content else ""), encoding="utf-8")
    temporary.replace(target)
