"""Activity tracking, reading duration, and learning statistics."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from yureader.config import (
    DATA_DIR,
    DOMAIN_LABELS,
    SUBJECTIVE_DIR,
    ACTIVITY_PATH,
    ACTIVITY_LOCK,
    ACTIVITY_SCHEMA_VERSION,
    ACTIVITY_TYPES,
    MIN_MEANINGFUL_ACTIVITY_SECONDS,
)
from yureader.utils import (
    safe_domain,
    atomic_write,
)
from yureader.catalog import (
    catalog,
    resolve_section_id,
    section_aliases_for,
)
from yureader.obsidian import (
    note_path,
    section_note_source,
    section_note_records,
    review_note_files,
    english_notebook_files,
)
from yureader.practice import (
    practice_path,
    load_practice_store,
    load_bank_questions,
    matching_questions,
    question_bank_by_id,
)
from yureader.oral_focus import oral_focus_item_payload

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

        day_items = unified_by_day.get(current_day, [])
        morning_seconds = 0
        afternoon_seconds = 0
        evening_seconds = 0
        for item in day_items:
            if not meaningful_activity(item):
                continue
            dur = max(0, int(item.get("duration_seconds") or 0))
            ts = str(item.get("started_at") or item.get("last_active_at") or "")
            hour = 14
            if ts:
                try:
                    hour = datetime.fromisoformat(ts).astimezone().hour
                except Exception:
                    if "T" in ts:
                        try:
                            hour = int(ts.split("T")[1].split(":")[0])
                        except Exception:
                            hour = 14
            if 5 <= hour < 12:
                morning_seconds += dur
            elif 12 <= hour < 18:
                afternoon_seconds += dur
            else:
                evening_seconds += dur

        if primary_seconds == 0 and day_seconds(value) > 0:
            ts_legacy = str(value.get("last_reading_at") or "")
            hour = 14
            if ts_legacy:
                try:
                    hour = datetime.fromisoformat(ts_legacy).astimezone().hour
                except Exception:
                    hour = 14
            if 5 <= hour < 12:
                morning_seconds = day_seconds(value)
            elif 12 <= hour < 18:
                afternoon_seconds = day_seconds(value)
            else:
                evening_seconds = day_seconds(value)

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
                "circadian": {
                    "morning_seconds": morning_seconds,
                    "afternoon_seconds": afternoon_seconds,
                    "evening_seconds": evening_seconds,
                },
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

    total_morning_seconds = sum(item.get("circadian", {}).get("morning_seconds", 0) for item in heatmap_days if not item["future"])
    total_afternoon_seconds = sum(item.get("circadian", {}).get("afternoon_seconds", 0) for item in heatmap_days if not item["future"])
    total_evening_seconds = sum(item.get("circadian", {}).get("evening_seconds", 0) for item in heatmap_days if not item["future"])
    circadian_totals = {
        "morning": total_morning_seconds,
        "afternoon": total_afternoon_seconds,
        "evening": total_evening_seconds,
    }
    slots_map = {"morning": "晨间 (05:00-12:00)", "afternoon": "午后 (12:00-18:00)", "evening": "晚间 (18:00-24:00+)"}
    golden_slot_key = max(circadian_totals, key=circadian_totals.get) if any(circadian_totals.values()) else "evening"
    golden_slot_label = slots_map[golden_slot_key]
    golden_slot_percent = round(circadian_totals[golden_slot_key] / max(1, sum(circadian_totals.values())) * 100) if any(circadian_totals.values()) else 0

    input_seconds = activity_totals.get("read", 0)
    output_seconds = (
        activity_totals.get("objective_practice", 0)
        + activity_totals.get("subjective_practice", 0)
        + activity_totals.get("notebook", 0)
        + activity_totals.get("review", 0)
    )
    total_in_out = max(1, input_seconds + output_seconds)
    input_ratio = round(input_seconds / total_in_out * 100)
    output_ratio = round(output_seconds / total_in_out * 100)

    try:
        from yureader.oral_focus import load_oral_focus_progress, load_oral_focus
        oral_progress = load_oral_focus_progress().get("items", {})
        oral_studied = sum(
            1 for item in oral_progress.values()
            if isinstance(item, dict) and (
                str(item.get("answer") or "").strip()
                or str(item.get("memory_note") or "").strip()
                or item.get("mastery") not in (None, "", "unseen")
            )
        )
        oral_mastered = sum(1 for item in oral_progress.values() if isinstance(item, dict) and item.get("mastery") == "mastered")
        _of_dataset, of_items = load_oral_focus()
        oral_total_items = len(of_items)
    except Exception:
        oral_studied = 0
        oral_mastered = 0
        oral_total_items = 0

    subject_assets = {
        "medicine": {
            "duration_seconds": activity_domain_totals.get("medicine", 0),
            "book_count": sum(1 for b in books if b.get("domain") == "medicine"),
            "note_count": sum(1 for sid in note_files if (sec := sections.get(sid)) and (bk := section_to_book.get(sid)) and bk.get("domain") == "medicine"),
            "oral_studied": oral_studied,
            "oral_mastered": oral_mastered,
            "oral_total_items": oral_total_items,
        },
        "politics": {
            "duration_seconds": activity_domain_totals.get("politics", 0),
            "answered_count": practice_summary.get("answered_count", 0),
            "correct_count": practice_summary.get("correct_count", 0),
            "accuracy": round(practice_summary["correct_count"] / practice_summary["answered_count"] * 100, 1) if practice_summary.get("answered_count") else 0,
        },
        "english": {
            "duration_seconds": activity_domain_totals.get("english", 0),
            "notebook_weeks": notebook_summary.get("week_count", 0),
            "notebook_characters": notebook_summary.get("character_count", 0),
        },
    }

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
        "circadian_totals": circadian_totals,
        "golden_slot": {
            "key": golden_slot_key,
            "label": golden_slot_label,
            "percent": golden_slot_percent,
        },
        "input_output_ratio": {
            "input_seconds": input_seconds,
            "output_seconds": output_seconds,
            "input_ratio": input_ratio,
            "output_ratio": output_ratio,
        },
        "subject_assets": subject_assets,
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


