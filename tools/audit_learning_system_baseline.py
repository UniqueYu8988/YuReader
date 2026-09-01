"""Generate a metadata-only baseline for the unified learning-system migration.

The audit reads the current repository and local runtime data, but never writes
to content, question banks, user data, or an Obsidian vault.  The generated
report intentionally contains filenames, counts, timestamps, and SHA-256
digests only; it does not contain book, question, note, or review text.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPORT_SCHEMA_VERSION = 1
INVENTORY_DIRS = {
    "practice": "practice",
    "subjective": "subjective",
    "english_weekly": "english-weekly",
    "reviews": "reviews",
    "review_workflow": "review-workflow",
    "logs": "logs",
    "weekly_reports": "weekly-reports",
}
API_PATHS = ("/api/health", "/api/bootstrap", "/api/stats", "/api/reviews")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def file_metadata(path: Path, root: Path, *, include_non_empty: bool = False) -> dict[str, Any]:
    stat = path.stat()
    entry: dict[str, Any] = {
        "path": relative_path(path, root),
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": sha256_file(path),
    }
    if include_non_empty:
        # This boolean is derived from the bytes but the bytes themselves are
        # never placed in the report.
        entry["non_empty"] = bool(path.read_bytes().strip())
    return entry


def json_object(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return None, str(error)
    if not isinstance(value, dict):
        return None, "top-level JSON value is not an object"
    return value, None


def git_baseline(root: Path) -> dict[str, Any]:
    def run(*args: str) -> str:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as error:
            return f"git unavailable: {error}"
        if result.returncode != 0:
            return result.stderr.strip() or f"git exited {result.returncode}"
        return result.stdout.strip()

    status_lines = run("status", "--short").splitlines()
    return {
        "head": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "status": status_lines,
        "dirty": bool(status_lines),
    }


def content_inventory(root: Path) -> dict[str, Any]:
    content_root = root / "content"
    books: list[dict[str, Any]] = []
    if content_root.is_dir():
        for book_dir in sorted(path for path in content_root.iterdir() if path.is_dir()):
            manifest_path = book_dir / "manifest.json"
            entry: dict[str, Any] = {
                "path": relative_path(book_dir, root),
                "manifest": manifest_path.is_file(),
            }
            if manifest_path.is_file():
                manifest, error = json_object(manifest_path)
                entry["manifest_sha256"] = sha256_file(manifest_path)
                if error:
                    entry["manifest_error"] = error
                else:
                    assert manifest is not None
                    book = manifest.get("book") if isinstance(manifest.get("book"), dict) else {}
                    sections = manifest.get("sections")
                    if not isinstance(sections, list):
                        sections = manifest.get("chapters") if isinstance(manifest.get("chapters"), list) else []
                    quality = manifest.get("quality") if isinstance(manifest.get("quality"), dict) else {}
                    entry.update(
                        {
                            "id": str(book.get("id") or ""),
                            "title": str(book.get("title") or ""),
                            "status": str(book.get("status") or ""),
                            "schema_version": manifest.get("schema_version"),
                            "section_count": len(sections),
                            "quality_status": str(quality.get("status") or ""),
                            "blocker_count": int(quality.get("blocker_count") or 0),
                            "warning_count": int(quality.get("warning_count") or 0),
                        }
                    )
            else:
                markdown_files = sorted(path for path in book_dir.rglob("*.md") if path.is_file())
                entry.update({"id": book_dir.name, "markdown_file_count": len(markdown_files), "section_count": len(markdown_files)})
            books.append(entry)
    return {
        "root": str(content_root),
        "book_count": len(books),
        "manifest_book_count": sum(1 for item in books if item.get("manifest")),
        "section_count": sum(int(item.get("section_count") or 0) for item in books),
        "books": books,
    }


def load_yupractice_validator(root: Path) -> Any | None:
    validator_path = root / "tools" / "yupractice" / "yupractice.py"
    if not validator_path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("yureader_yupractice_baseline", validator_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return None
    return module


def question_bank_inventory(root: Path) -> dict[str, Any]:
    bank_root = root / "question-banks"
    banks: list[dict[str, Any]] = []
    if not bank_root.is_dir():
        return {"root": str(bank_root), "active_count": 0, "directory_count": 0, "banks": banks}
    validator = load_yupractice_validator(root)
    for bank_dir in sorted(path for path in bank_root.iterdir() if path.is_dir()):
        manifest_path = bank_dir / "manifest.json"
        entry: dict[str, Any] = {"path": relative_path(bank_dir, root), "hidden": bank_dir.name.startswith(".")}
        if not manifest_path.is_file():
            entry["status"] = "no-manifest"
            banks.append(entry)
            continue
        entry["manifest_sha256"] = sha256_file(manifest_path)
        manifest, error = json_object(manifest_path)
        if error:
            entry["status"] = "invalid-manifest"
            entry["manifest_error"] = error
            banks.append(entry)
            continue
        assert manifest is not None
        bank = manifest.get("bank") if isinstance(manifest.get("bank"), dict) else {}
        entry.update(
            {
                "id": str(bank.get("id") or ""),
                "title": str(bank.get("title") or ""),
                "schema_version": manifest.get("schema_version"),
                "declared_status": str(bank.get("status") or ""),
                "question_count": int(manifest.get("question_count") or 0),
                "quarantined_count": int(manifest.get("quarantined_count") or 0),
                "quality_status": str((manifest.get("quality") or {}).get("status") or "") if isinstance(manifest.get("quality"), dict) else "",
                "ready_runtime_entry": (
                    not bank_dir.name.startswith(".")
                    and bank_dir.name == str(bank.get("id") or "")
                    and manifest.get("schema_version") == 1
                    and bank.get("status") == "ready"
                ),
            }
        )
        if entry["ready_runtime_entry"] and validator is not None:
            try:
                result = validator.validate_package(bank_dir.resolve())
                quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
                summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
                entry["validation"] = {
                    "status": str(quality.get("status") or ""),
                    "blocker_count": int(quality.get("blocker_count") or 0),
                    "warning_count": int(quality.get("warning_count") or 0),
                    "question_count": int(summary.get("question_count") or 0),
                    "quarantined_count": int(summary.get("quarantined_count") or 0),
                }
            except Exception as exc:  # pragma: no cover - defensive for real packages
                entry["validation"] = {"status": "error", "error_type": type(exc).__name__}
        banks.append(entry)
    active = [item for item in banks if item.get("ready_runtime_entry")]
    return {
        "root": str(bank_root),
        "directory_count": len(banks),
        "active_count": len(active),
        "active_question_count": sum(int(item.get("question_count") or 0) for item in active),
        "active_quarantined_count": sum(int(item.get("quarantined_count") or 0) for item in active),
        "banks": banks,
    }


def section_ids_from_content(root: Path) -> set[str]:
    ids: set[str] = set()
    content_root = root / "content"
    if not content_root.is_dir():
        return ids
    for manifest_path in content_root.glob("*/manifest.json"):
        manifest, error = json_object(manifest_path)
        if error or manifest is None:
            continue
        book = manifest.get("book") if isinstance(manifest.get("book"), dict) else {}
        quality = manifest.get("quality") if isinstance(manifest.get("quality"), dict) else {}
        if book.get("status") != "ready" or int(quality.get("blocker_count") or 0) != 0:
            continue
        items = manifest.get("sections")
        if not isinstance(items, list):
            items = manifest.get("chapters") if isinstance(manifest.get("chapters"), list) else []
        ids.update(str(item.get("id")) for item in items if isinstance(item, dict) and item.get("id"))
    return ids


def activity_inventory(root: Path, section_ids: set[str]) -> dict[str, Any]:
    path = root / "data" / "activity.json"
    result: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
    if not path.is_file():
        return result
    result["sha256"] = sha256_file(path)
    payload, error = json_object(path)
    if error:
        result["parse_error"] = error
        return result
    assert payload is not None
    days = payload.get("days") if isinstance(payload.get("days"), dict) else {}
    day_summaries: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    total_reading_seconds = 0
    total_section_seconds = 0
    for day, value in sorted(days.items()):
        if not isinstance(value, dict):
            day_summaries.append({"date": str(day), "invalid": True})
            continue
        sections = [str(item) for item in value.get("sections", []) if str(item)] if isinstance(value.get("sections"), list) else []
        notes = [str(item) for item in value.get("notes", []) if str(item)] if isinstance(value.get("notes"), list) else []
        section_seconds = value.get("section_reading_seconds") if isinstance(value.get("section_reading_seconds"), dict) else {}
        unknown_ids = sorted((set(sections) | set(notes) | {str(item) for item in section_seconds}) - section_ids)
        if unknown_ids:
            unknown.append({"date": str(day), "ids": unknown_ids})
        reading_seconds = max(0, int(value.get("reading_seconds") or 0))
        total_reading_seconds += reading_seconds
        total_section_seconds += sum(max(0, int(seconds or 0)) for seconds in section_seconds.values())
        day_summaries.append(
            {
                "date": str(day),
                "keys": sorted(str(key) for key in value),
                "section_count": len(sections),
                "note_count": len(notes),
                "section_reading_seconds_count": len(section_seconds),
                "reading_seconds": reading_seconds,
                "review_saved": bool(value.get("review_saved")),
            }
        )
    last_section = str(payload.get("last_section_id") or "")
    result.update(
        {
            "schema_version": payload.get("schema_version"),
            "day_count": len(days),
            "dates": [item["date"] for item in day_summaries if "date" in item],
            "total_reading_seconds": total_reading_seconds,
            "total_section_reading_seconds": total_section_seconds,
            "last_section_id": last_section,
            "last_section_mapped": bool(last_section) and last_section in section_ids,
            "days": day_summaries,
            "unmapped_activity_ids": unknown,
        }
    )
    return result


def data_inventory(root: Path, section_ids: set[str]) -> dict[str, Any]:
    data_root = root / "data"
    result: dict[str, Any] = {"root": str(data_root), "directories": {}}
    for label, name in INVENTORY_DIRS.items():
        directory = data_root / name
        files = [path for path in directory.rglob("*") if path.is_file()] if directory.is_dir() else []
        result["directories"][label] = {
            "path": str(directory),
            "exists": directory.is_dir(),
            "file_count": len(files),
            "files": [file_metadata(path, root, include_non_empty=False) for path in sorted(files)],
        }

    notes_dir = data_root / "notes"
    note_files = [path for path in notes_dir.rglob("*") if path.is_file()] if notes_dir.is_dir() else []
    notes: list[dict[str, Any]] = []
    for path in sorted(note_files):
        entry = file_metadata(path, root, include_non_empty=True)
        stem = path.stem
        entry.update(
            {
                "section_id": stem,
                "mapping_status": "mapped" if stem in section_ids else "unmapped",
            }
        )
        notes.append(entry)
    result["notes"] = {
        "path": str(notes_dir),
        "file_count": len(notes),
        "non_empty_count": sum(1 for item in notes if item["non_empty"]),
        "mapped_non_empty_count": sum(1 for item in notes if item["non_empty"] and item["mapping_status"] == "mapped"),
        "unmapped_non_empty_count": sum(1 for item in notes if item["non_empty"] and item["mapping_status"] == "unmapped"),
        "files": notes,
    }
    return result


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
        vaults = list((config.get("vaults") or {}).values()) if isinstance(config, dict) else []
        vaults.sort(key=lambda item: (not bool(item.get("open")), -int(item.get("ts") or 0)))
        for item in vaults:
            if not isinstance(item, dict):
                continue
            candidate = Path(str(item.get("path") or "")).expanduser().resolve()
            if candidate.is_dir() and (candidate / ".obsidian").is_dir():
                return candidate
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    return None


def obsidian_inventory(root: Path) -> dict[str, Any]:
    vault = obsidian_vault()
    result: dict[str, Any] = {"detected": bool(vault), "vault_path": str(vault) if vault else ""}
    if not vault:
        return result
    yu_reader = vault / "YuReader"
    files = [path for path in yu_reader.rglob("*") if path.is_file()] if yu_reader.is_dir() else []
    entries: list[dict[str, Any]] = []
    for path in sorted(files):
        entry: dict[str, Any] = {"path": path.relative_to(vault).as_posix(), "size_bytes": path.stat().st_size}
        if path.suffix.lower() == ".md":
            entry["sha256"] = sha256_file(path)
        entries.append(entry)
    result.update({"yu_reader_exists": yu_reader.is_dir(), "file_count": len(entries), "files": entries})
    return result


def shape_summary(value: Any, depth: int = 0) -> dict[str, Any]:
    """Summarize an API payload without retaining any strings from its body."""
    if depth > 2:
        return {"type": type(value).__name__}
    if isinstance(value, dict):
        return {
            "type": "object",
            "keys": sorted(str(key) for key in value),
            "children": {str(key): shape_summary(item, depth + 1) for key, item in sorted(value.items(), key=lambda pair: str(pair[0])) if depth < 2},
        }
    if isinstance(value, list):
        return {"type": "array", "length": len(value), "item_types": sorted({type(item).__name__ for item in value})}
    if value is None:
        return {"type": "null"}
    return {"type": type(value).__name__}


def api_summary(path: str, payload: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {"payload": shape_summary(payload)}
    if not isinstance(payload, dict):
        return summary
    if path == "/api/health":
        summary.update({"ok": bool(payload.get("ok")), "version": str(payload.get("version") or "")})
    elif path == "/api/bootstrap":
        books = payload.get("books") if isinstance(payload.get("books"), list) else []
        banks = payload.get("question_banks") if isinstance(payload.get("question_banks"), list) else []
        summary.update(
            {
                "book_count": len(books),
                "section_count": int(payload.get("section_count") or 0),
                "question_bank_count": int(payload.get("question_bank_count") or len(banks)),
                "domain_counts": dict(Counter(str(book.get("domain") or "") for book in books if isinstance(book, dict))),
            }
        )
    elif path == "/api/stats":
        scalar_keys = {
            key
            for key, value in payload.items()
            if isinstance(value, (bool, int, float)) and (str(key).endswith(("_count", "_seconds", "_opens")) or key in {"weeks", "max", "streak", "note_coverage"})
        }
        summary["scalar_metrics"] = {key: payload[key] for key in sorted(scalar_keys)}
    elif path == "/api/reviews":
        safe_keys = {"review_date", "review_note_date", "note_count", "subject_count", "page_count", "review_note_characters", "completed_count", "all_complete"}
        summary["safe_metrics"] = {key: payload[key] for key in sorted(safe_keys) if key in payload and isinstance(payload[key], (bool, int, float, str))}
    return summary


def api_inventory(api_base: str, timeout: float) -> dict[str, Any]:
    result: dict[str, Any] = {"base": api_base, "endpoints": {}}
    for path in API_PATHS:
        endpoint: dict[str, Any] = {"url": api_base.rstrip("/") + path}
        try:
            request = urllib.request.Request(endpoint["url"], headers={"Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                endpoint.update({"available": True, "http_status": int(response.status), **api_summary(path, payload)})
        except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            endpoint.update({"available": False, "error_type": type(error).__name__})
        result["endpoints"][path] = endpoint
    return result


def build_report(root: Path, *, api_base: str = "http://127.0.0.1:8775", api_timeout: float = 2.0) -> dict[str, Any]:
    root = root.resolve()
    content = content_inventory(root)
    section_ids = section_ids_from_content(root)
    data = data_inventory(root, section_ids)
    activity = activity_inventory(root, section_ids)
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "repository_root": str(root),
        "git": git_baseline(root),
        "content": content,
        "question_banks": question_bank_inventory(root),
        "activity": activity,
        "data": data,
        "obsidian": obsidian_inventory(root),
        "api": api_inventory(api_base, api_timeout),
        "mapping": {
            "known_section_id_count": len(section_ids),
            "unmapped_non_empty_note_paths": [
                item["path"] for item in data["notes"]["files"] if item["non_empty"] and item["mapping_status"] == "unmapped"
            ],
            "unmapped_activity_ids": activity.get("unmapped_activity_ids", []),
        },
    }
    return report


def write_report(report: dict[str, Any], output: Path) -> None:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a metadata-only YuReader migration baseline")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, help="write the report to this path; stdout is used when omitted")
    parser.add_argument("--api-base", default="http://127.0.0.1:8775")
    parser.add_argument("--api-timeout", type=float, default=2.0)
    args = parser.parse_args(argv)
    report = build_report(args.root, api_base=args.api_base, api_timeout=max(0.1, args.api_timeout))
    if args.output:
        write_report(report, args.output)
        print(str(args.output.resolve()))
    else:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
