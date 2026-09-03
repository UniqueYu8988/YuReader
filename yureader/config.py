"""Configuration, directory paths, and global locks for YuReader."""

from __future__ import annotations

import os
from pathlib import Path
from threading import Lock

ROOT = Path(__file__).resolve().parents[1]
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

BOOK_ASSETS: dict[str, dict] = {}
