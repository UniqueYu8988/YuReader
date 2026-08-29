"""Apply YuReader's first-chapter content boundary to existing packages.

This is a conservative package migration: section text and source maps are
copied byte-for-byte, while only manifest membership/order and the reports are
updated.  Original source files and YuBuilder evidence are never touched.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import tempfile


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content"
FIRST_CHAPTER_TITLE = re.compile(
    r"^\s*(?:第[0-9０-９一二三四五六七八九十百千万零〇两]+章(?:\s|$)|"
    r"chapter\s*(?:1|one)\b)",
    re.IGNORECASE,
)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def first_chapter_index(toc: list[dict]) -> int:
    for index, chapter in enumerate(toc):
        if FIRST_CHAPTER_TITLE.search(str(chapter.get("title") or "").strip()):
            return index
    raise ValueError("manifest has no reliable first chapter title")


def package_plan(package: Path) -> dict:
    manifest_path = package / "manifest.json"
    manifest = read_json(manifest_path)
    toc = manifest.get("toc")
    sections = manifest.get("sections")
    source_chapters = manifest.get("source_chapters")
    if not isinstance(toc, list) or not isinstance(sections, list) or not isinstance(source_chapters, list):
        raise ValueError(f"{package.name}: manifest structure is incomplete")
    start = first_chapter_index(toc)
    if start == 0:
        return {"package": package, "manifest": manifest, "start": 0, "changed": False}

    kept_toc = toc[start:]
    kept_chapter_ids = {str(item.get("id")) for item in kept_toc}
    kept_sections = [
        item for item in sections if str(item.get("chapter_id")) in kept_chapter_ids
    ]
    kept_source_chapters = [
        item for item in source_chapters if str(item.get("id")) in kept_chapter_ids
    ]
    if len(kept_source_chapters) != len(kept_toc) or not kept_sections:
        raise ValueError(f"{package.name}: first-chapter slice has incomplete section coverage")
    return {
        "package": package,
        "manifest": manifest,
        "start": start,
        "changed": True,
        "toc": kept_toc,
        "sections": kept_sections,
        "source_chapters": kept_source_chapters,
    }


def _safe_copy(source_root: Path, target_root: Path, relative: str) -> None:
    source = (source_root / relative).resolve()
    if source_root.resolve() not in source.parents or not source.is_file():
        raise ValueError(f"referenced artifact is missing or escapes package: {relative}")
    target = target_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def migrate(plan: dict, *, apply: bool) -> dict:
    package = plan["package"]
    manifest = plan["manifest"]
    if not plan["changed"]:
        return {
            "book_id": str(manifest.get("book", {}).get("id") or package.name),
            "status": "already_first_chapter",
            "excluded_prefix_chapter_count": 0,
            "chapter_count": len(manifest.get("toc") or []),
            "section_count": len(manifest.get("sections") or []),
        }

    toc = plan["toc"]
    sections = plan["sections"]
    source_chapters = plan["source_chapters"]
    chapter_order = {str(item["id"]): order for order, item in enumerate(toc, start=1)}
    kept_artifacts = {
        str(item["artifact"])
        for item in (*sections, *source_chapters)
        if isinstance(item.get("artifact"), str)
    }
    page_sizes = []
    for item in sections:
        artifact = str(item["artifact"])
        path = package / artifact
        if not path.is_file():
            raise ValueError(f"{package.name}: missing section artifact {artifact}")
        page_sizes.append((artifact, len(path.read_text(encoding="utf-8-sig"))))

    next_manifest = json.loads(json.dumps(manifest, ensure_ascii=False))
    next_manifest["toc"] = []
    next_manifest["sections"] = []
    next_manifest["source_chapters"] = []
    for order, chapter in enumerate(toc, start=1):
        chapter_copy = dict(chapter)
        chapter_copy["order"] = order
        chapter_copy["section_ids"] = [
            str(item["id"])
            for item in sections
            if str(item.get("chapter_id")) == str(chapter["id"])
        ]
        next_manifest["toc"].append(chapter_copy)
    for order, chapter in enumerate(source_chapters, start=1):
        chapter_copy = dict(chapter)
        chapter_copy["order"] = order
        next_manifest["source_chapters"].append(chapter_copy)
    for order, section in enumerate(sections, start=1):
        section_copy = dict(section)
        section_copy["order"] = order
        section_copy["chapter_order"] = chapter_order[str(section["chapter_id"])]
        section_copy["section_order"] = 1 + sum(
            1
            for prior in sections[: order - 1]
            if str(prior.get("chapter_id")) == str(section["chapter_id"])
        )
        next_manifest["sections"].append(section_copy)

    first_title = str(toc[0].get("title") or "")
    boundary = {
        "schema_version": 1,
        "mode": "first_chapter",
        "book_id": str(manifest.get("book", {}).get("id") or package.name),
        "excluded_prefix_chapter_count": plan["start"],
        "first_chapter_title": first_title,
        "retained_chapter_count": len(toc),
        "retained_section_count": len(sections),
        "retained_page_characters": sum(size for _artifact, size in page_sizes),
        "source_package_before_migration": str(package),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    next_manifest.setdefault("provenance", {})["content_boundary"] = {
        "mode": boundary["mode"],
        "excluded_prefix_chapter_count": boundary["excluded_prefix_chapter_count"],
        "first_chapter_title": first_title,
        "report": "reports/content-boundary.json",
    }
    next_manifest.setdefault("artifacts", {})["content_boundary_report"] = "reports/content-boundary.json"
    reading_layout = next_manifest.setdefault("reading_layout", {})
    reading_layout.update(
        {
            "chapter_count": len(toc),
            "section_count": len(sections),
            "content_start": "first_chapter",
            "excluded_prefix_chapter_count": plan["start"],
            "first_chapter_title": first_title,
        }
    )
    next_manifest["content_boundary_applied_at"] = boundary["generated_at"]

    quality = next_manifest.get("quality") if isinstance(next_manifest.get("quality"), dict) else {}
    quality_report_path = package / str(quality.get("report") or "reports/quality.json")
    quality_report = read_json(quality_report_path) if quality_report_path.is_file() else {
        "status": "pass", "blockers": [], "warnings": [], "metrics": {}
    }
    kept_paths = kept_artifacts
    warnings = [
        item for item in (quality_report.get("warnings") or [])
        if not isinstance(item, dict)
        or not item.get("artifact")
        or str(item.get("artifact")) in kept_paths
    ]
    quality_report["warnings"] = warnings
    quality_report["status"] = "warning" if warnings else "pass"
    metrics = quality_report.setdefault("metrics", {})
    metrics["chapter_count"] = len(toc)
    metrics["published_chapter_characters"] = sum(
        len((package / str(item["artifact"])).read_text(encoding="utf-8-sig"))
        for item in source_chapters
    )
    metrics["page_count"] = len(sections)
    quality["status"] = quality_report["status"]
    quality["warning_count"] = len(warnings)
    quality["blocker_count"] = len(quality_report.get("blockers") or [])
    next_manifest["quality"] = quality
    next_manifest["reading_layout"]["oversized_page_count"] = sum(size > 8000 for _artifact, size in page_sizes)
    layout_report_path = package / str(reading_layout.get("report") or "reports/layout.json")
    layout_report = read_json(layout_report_path) if layout_report_path.is_file() else {
        "status": "pass", "blockers": [], "oversized_pages": [], "metrics": {}
    }
    layout_report["status"] = "warning" if any(size > 8000 for _artifact, size in page_sizes) else "pass"
    layout_report["content_start"] = "first_chapter"
    layout_report["excluded_prefix_chapter_count"] = plan["start"]
    layout_report["first_chapter_title"] = first_title
    layout_report["oversized_pages"] = [
        order for order, (_artifact, size) in enumerate(page_sizes, start=1) if size > 8000
    ]
    layout_metrics = layout_report.setdefault("metrics", {})
    layout_metrics.update(
        {
            "chapter_count": len(toc),
            "section_count": len(sections),
            "total_characters": sum(size for _artifact, size in page_sizes),
            "minimum_characters": min((size for _artifact, size in page_sizes), default=0),
            "maximum_characters": max((size for _artifact, size in page_sizes), default=0),
            "average_characters": round(sum(size for _artifact, size in page_sizes) / len(page_sizes))
            if page_sizes
            else 0,
        }
    )

    if not apply:
        return {
            "book_id": str(manifest.get("book", {}).get("id") or package.name),
            "status": "would_migrate",
            "excluded_prefix_chapter_count": plan["start"],
            "first_chapter_title": first_title,
            "chapter_count": len(toc),
            "section_count": len(sections),
        }

    parent = package.parent
    staging = Path(tempfile.mkdtemp(prefix=f".{package.name}-first-chapter-", dir=parent))
    try:
        # Preserve reports/other evidence, then prune only unreferenced chapter
        # and page Markdown files from the runtime copy.
        shutil.copytree(package, staging, dirs_exist_ok=True)
        for relative in ("cleaned/chapters", "cleaned/pages"):
            directory = staging / relative
            if not directory.is_dir():
                continue
            for path in directory.rglob("*.md"):
                if path.relative_to(staging).as_posix() not in kept_paths:
                    path.unlink()
        write_json(staging / "manifest.json", next_manifest)
        report_relative = str(quality.get("report") or "reports/quality.json")
        write_json(staging / report_relative, quality_report)
        write_json(staging / str(reading_layout.get("report") or "reports/layout.json"), layout_report)
        write_json(staging / "reports/content-boundary.json", boundary)
        backup = parent / f".{package.name}-before-first-chapter"
        if backup.exists():
            shutil.rmtree(backup)
        package.replace(backup)
        staging.replace(package)
        shutil.rmtree(backup)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "book_id": str(manifest.get("book", {}).get("id") or package.name),
        "status": "migrated",
        "excluded_prefix_chapter_count": plan["start"],
        "first_chapter_title": first_title,
        "chapter_count": len(toc),
        "section_count": len(sections),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=CONTENT_DIR)
    parser.add_argument("--apply", action="store_true", help="atomically replace packages")
    parser.add_argument("book_ids", nargs="*")
    args = parser.parse_args()
    root = args.root.resolve()
    candidates = [root / book_id for book_id in args.book_ids] if args.book_ids else sorted(root.iterdir())
    results = []
    for package in candidates:
        if not package.is_dir() or not (package / "manifest.json").is_file():
            continue
        plan = package_plan(package)
        results.append(migrate(plan, apply=args.apply))
    print(json.dumps({"root": str(root), "apply": args.apply, "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
