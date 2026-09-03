"""Daily study goals and progress calculation."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from yureader.config import (
    DATA_DIR,
    ORAL_FOCUS_CONTENT_PATH,
    ORAL_FOCUS_PROGRESS_PATH,
)
from yureader.utils import atomic_write
from yureader.activity import load_activity, activity_records_payload

GOALS_PATH = DATA_DIR / "goals.json"

DEFAULT_GOALS = {
    "total_hours": 8.0,
    "reading": {
        "medicine_hours": 2.0,
        "politics_hours": 0.5,
        "english_hours": 0.5,
    },
    "practice": {
        "medicine_definition": 20,
        "medicine_essay": 20,
        "politics_units": 2,
        "english_reading": 2,
    },
}


def load_goals() -> dict:
    """Load configured daily goals with robust fallbacks."""
    try:
        if GOALS_PATH.is_file():
            payload = json.loads(GOALS_PATH.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                merged = {
                    "total_hours": float(payload.get("total_hours", DEFAULT_GOALS["total_hours"])),
                    "reading": {
                        "medicine_hours": float((payload.get("reading") or {}).get("medicine_hours", DEFAULT_GOALS["reading"]["medicine_hours"])),
                        "politics_hours": float((payload.get("reading") or {}).get("politics_hours", DEFAULT_GOALS["reading"]["politics_hours"])),
                        "english_hours": float((payload.get("reading") or {}).get("english_hours", DEFAULT_GOALS["reading"]["english_hours"])),
                    },
                    "practice": {
                        "medicine_definition": int((payload.get("practice") or {}).get("medicine_definition", DEFAULT_GOALS["practice"]["medicine_definition"])),
                        "medicine_essay": int((payload.get("practice") or {}).get("medicine_essay", DEFAULT_GOALS["practice"]["medicine_essay"])),
                        "politics_units": int((payload.get("practice") or {}).get("politics_units", DEFAULT_GOALS["practice"]["politics_units"])),
                        "english_reading": int((payload.get("practice") or {}).get("english_reading", DEFAULT_GOALS["practice"]["english_reading"])),
                    },
                }
                return merged
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return {
        "total_hours": DEFAULT_GOALS["total_hours"],
        "reading": dict(DEFAULT_GOALS["reading"]),
        "practice": dict(DEFAULT_GOALS["practice"]),
    }


def save_goals(payload: dict) -> dict:
    """Validate and persist updated daily goals."""
    validated = {
        "total_hours": max(0.5, min(24.0, float(payload.get("total_hours", DEFAULT_GOALS["total_hours"])))),
        "reading": {
            "medicine_hours": max(0.0, min(12.0, float((payload.get("reading") or {}).get("medicine_hours", DEFAULT_GOALS["reading"]["medicine_hours"])))),
            "politics_hours": max(0.0, min(12.0, float((payload.get("reading") or {}).get("politics_hours", DEFAULT_GOALS["reading"]["politics_hours"])))),
            "english_hours": max(0.0, min(12.0, float((payload.get("reading") or {}).get("english_hours", DEFAULT_GOALS["reading"]["english_hours"])))),
        },
        "practice": {
            "medicine_definition": max(0, min(200, int((payload.get("practice") or {}).get("medicine_definition", DEFAULT_GOALS["practice"]["medicine_definition"])))),
            "medicine_essay": max(0, min(200, int((payload.get("practice") or {}).get("medicine_essay", DEFAULT_GOALS["practice"]["medicine_essay"])))),
            "politics_units": max(0, min(20, int((payload.get("practice") or {}).get("politics_units", DEFAULT_GOALS["practice"]["politics_units"])))),
            "english_reading": max(0, min(20, int((payload.get("practice") or {}).get("english_reading", DEFAULT_GOALS["practice"]["english_reading"])))),
        },
    }
    atomic_write(GOALS_PATH, json.dumps(validated, ensure_ascii=False, indent=2))
    return validated


def _load_oral_item_types() -> dict[str, str]:
    """Cache map of oral item id -> type (definition/essay)."""
    item_types: dict[str, str] = {}
    if ORAL_FOCUS_CONTENT_PATH.is_file():
        try:
            content = json.loads(ORAL_FOCUS_CONTENT_PATH.read_text(encoding="utf-8-sig"))
            for item in content.get("items", []):
                if isinstance(item, dict) and "id" in item and "type" in item:
                    item_types[item["id"]] = str(item["type"])
        except (OSError, json.JSONDecodeError):
            pass
    return item_types


def daily_goals_payload(day: str = "") -> dict:
    """Compute progress for the given day against configured goals."""
    if not day:
        day = date.today().isoformat()
    goals = load_goals()

    raw_activities = activity_records_payload(day).get("activities", [])
    item_types = _load_oral_item_types()

    total_activity_seconds = 0
    reading_seconds = {"medicine": 0, "politics": 0, "english": 0}

    medicine_definitions_seen: set[str] = set()
    medicine_essays_seen: set[str] = set()
    politics_units_seen: set[str] = set()
    english_reading_seen: set[str] = set()

    for act in raw_activities:
        if not isinstance(act, dict):
            continue
        duration = int(act.get("duration_seconds") or 0)
        total_activity_seconds += duration

        act_type = str(act.get("activity_type") or "")
        domain = str(act.get("domain") or "")
        resource_id = str(act.get("resource_id") or "")
        item_id = str(act.get("item_id") or "")

        # Reading progress
        if act_type == "read" and domain in reading_seconds:
            reading_seconds[domain] += duration

        # Oral focus practice
        if act_type == "subjective_practice" or "oral-focus" in resource_id:
            itype = item_types.get(item_id, "")
            if itype == "definition" or "名解" in str(act.get("title") or ""):
                medicine_definitions_seen.add(item_id or act.get("activity_id"))
            elif itype == "essay" or "论述" in str(act.get("title") or ""):
                medicine_essays_seen.add(item_id or act.get("activity_id"))

        # Politics practice
        if domain == "politics" and act_type == "objective_practice":
            unit = str(act.get("unit_id") or resource_id or item_id)
            politics_units_seen.add(unit)

        # English reading practice
        if domain == "english" and act_type in ("objective_practice", "read"):
            if "reading" in resource_id or "reading" in item_id or "阅读" in str(act.get("title") or ""):
                english_reading_seen.add(item_id or resource_id)

    # Also check oral focus progress for updates made today
    if ORAL_FOCUS_PROGRESS_PATH.is_file():
        try:
            pdata = json.loads(ORAL_FOCUS_PROGRESS_PATH.read_text(encoding="utf-8-sig"))
            for pid, pitem in (pdata.get("items") or {}).items():
                if isinstance(pitem, dict):
                    updated = str(pitem.get("updated_at") or "")
                    if updated.startswith(day):
                        itype = item_types.get(pid, "")
                        if itype == "definition":
                            medicine_definitions_seen.add(pid)
                        elif itype == "essay":
                            medicine_essays_seen.add(pid)
        except (OSError, json.JSONDecodeError):
            pass

    return {
        "day": day,
        "goals": goals,
        "progress": {
            "total_seconds": total_activity_seconds,
            "reading": {
                "medicine_seconds": reading_seconds["medicine"],
                "politics_seconds": reading_seconds["politics"],
                "english_seconds": reading_seconds["english"],
            },
            "practice": {
                "medicine_definition": len(medicine_definitions_seen),
                "medicine_essay": len(medicine_essays_seen),
                "politics_units": len(politics_units_seen),
                "english_reading": len(english_reading_seen),
            },
        },
    }
