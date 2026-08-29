"""Build and atomically publish a traceable YuReader Markdown book package."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_DIR = ROOT / "workspace"
CONTENT_DIR = ROOT / "content"
SCHEMA_VERSION = 2
MIN_CHAPTER_CHARS = 200
OVERSIZED_PAGE_CHARS = 8000
OCCLUSION_TERMS_PATH = ROOT / "tools" / "occlusion_terms.json"

# YuReader pages deliberately begin at the first real chapter.  Front matter
# (copyright pages, prefaces, tables of contents, etc.) remains in the source
# archive and candidate evidence, but is never exposed as formal reading
# content.  Keep this matcher narrow enough that a section such as “第一节”
# cannot become the book boundary by accident.
FIRST_CHAPTER_TITLE = re.compile(
    r"^\s*(?:第[0-9０-９一二三四五六七八九十百千万零〇两]+章(?:\s|$)|"
    r"chapter\s*(?:1|one)\b)",
    re.IGNORECASE,
)


def load_occlusion_profile() -> dict:
    profile = json.loads(OCCLUSION_TERMS_PATH.read_text(encoding="utf-8"))
    if profile.get("schema_version") != 1 or profile.get("character") != "𬌗":
        raise ValueError("invalid occlusion terminology profile")
    return profile


def build_occlusion_replacements(profile: dict) -> tuple[tuple[str, str], ...]:
    """Derive complete-term OCR aliases without ever replacing a bare glyph."""
    canonical_terms = {
        str(term)
        for group in profile.get("canonical_groups", [])
        for term in group.get("terms", [])
        if "𬌗" in str(term) and len(str(term)) > 1
    }
    confusions = [
        *profile.get("confusions", {}).get("single_character_substitutions", []),
        *profile.get("confusions", {}).get("multi_character_substitutions", []),
    ]
    replacements: dict[str, str] = {}
    for canonical in canonical_terms:
        for confusion in confusions:
            alias = canonical.replace("𬌗", str(confusion))
            if alias != canonical:
                replacements[alias] = canonical
    for alias in profile.get("explicit_aliases", []):
        replacements[str(alias["from"])] = str(alias["to"])
    return tuple(sorted(replacements.items(), key=lambda pair: (-len(pair[0]), pair[0])))


OCCLUSION_PROFILE = load_occlusion_profile()
SAFE_OCCLUSION_REPLACEMENTS = build_occlusion_replacements(OCCLUSION_PROFILE)
OCCLUSION_SINGLE_CONFUSIONS = tuple(
    str(item)
    for item in OCCLUSION_PROFILE.get("confusions", {}).get(
        "single_character_substitutions", []
    )
)
OCCLUSION_MULTI_CONFUSIONS = tuple(
    str(item)
    for item in OCCLUSION_PROFILE.get("confusions", {}).get(
        "multi_character_substitutions", []
    )
)
OCCLUSION_PROTECTED_WORDS = tuple(
    str(item)
    for item in OCCLUSION_PROFILE.get("confusions", {}).get("preserve_as_written", [])
)
SAFE_OCCLUSION_MISSING_PATTERNS = tuple(
    item
    for item in OCCLUSION_PROFILE.get("missing_character_patterns", [])
    if item.get("action") == "automatic"
)


def replace_occlusion_alias(line: str, before: str, after: str) -> tuple[str, int]:
    """Replace a complete alias unless it overlaps a protected legitimate word."""
    if before not in line:
        return line, 0
    protect_overlap = any(char in before for char in OCCLUSION_SINGLE_CONFUSIONS) and not any(
        phrase in before for phrase in OCCLUSION_MULTI_CONFUSIONS
    )

    parts: list[str] = []
    cursor = 0
    count = 0
    while (index := line.find(before, cursor)) >= 0:
        end = index + len(before)
        overlaps = False
        if protect_overlap:
            for word in OCCLUSION_PROTECTED_WORDS:
                search_start = max(0, index - len(word) + 1)
                word_start = line.find(word, search_start)
                while 0 <= word_start < end:
                    if word_start + len(word) > index:
                        overlaps = True
                        break
                    word_start = line.find(word, word_start + 1)
                if overlaps:
                    break
        parts.append(line[cursor:index])
        if overlaps:
            parts.append(before)
        else:
            parts.append(after)
            count += 1
        cursor = end
    if not count:
        return line, 0
    parts.append(line[cursor:])
    return "".join(parts), count


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def stable_chapter_id(book_id: str, order: int) -> str:
    return hashlib.sha1(f"{book_id}\0chapter:{order}".encode("utf-8")).hexdigest()[:12]


def stable_section_id(book_id: str, chapter_order: int, section_order: int) -> str:
    value = f"{book_id}\0section:{chapter_order}:{section_order}"
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def first_heading(markdown: str, fallback: str) -> str:
    match = re.search(r"^#\s+(.+?)\s*$", markdown, re.MULTILINE)
    return match.group(1).strip() if match else fallback


def chapter_title(path: Path, markdown: str) -> str:
    if path.name.startswith("00-"):
        return path.stem.split("-", 1)[1]
    return first_heading(markdown, path.stem)


def first_chapter_index(chapters: list[dict]) -> int:
    """Return the first formal chapter, rejecting layouts without one."""
    for index, chapter in enumerate(chapters):
        title = str(chapter.get("title") or "").strip()
        if FIRST_CHAPTER_TITLE.search(title):
            return index
    raise ValueError(
        "the reading layout must contain a first chapter; "
        "front matter alone cannot be published as YuReader content"
    )


def content_chapters(chapters: list[dict]) -> tuple[list[dict], dict]:
    """Exclude every layout unit before the first chapter.

    The returned chapter dictionaries keep their original source order in the
    private ``source_order`` field so a rebuild does not unnecessarily change
    stable chapter/section IDs.  Display order is assigned later when the
    manifest is materialized.
    """
    start = first_chapter_index(chapters)
    selected = []
    for source_order, chapter in enumerate(chapters[start:], start=start + 1):
        selected.append({**chapter, "source_order": source_order})
    first = selected[0]
    return selected, {
        "mode": "first_chapter",
        "excluded_prefix_chapter_count": start,
        "first_chapter_title": str(first.get("title") or ""),
        "first_chapter_source_order": int(first["source_order"]),
    }


def chapter_sort_key(path: Path) -> tuple[int, int, str]:
    match = re.match(r"^(\d+)-", path.name)
    if match:
        number = int(match.group(1))
        # 00-书目信息 should precede 00-目录 deterministically.
        zero_rank = 0 if "书目信息" in path.stem else 1
        return number, zero_rank, path.name
    return 10_000, 0, path.name


def line_count(text: str) -> int:
    return text.count("\n") + (1 if text else 0)


def original_heading_candidates(original: str, title: str) -> list[int]:
    chapter = re.match(r"^(第[^\s]+章)", title)
    needle = chapter.group(1) if chapter else ("附录" if title.startswith("附录") else title)
    return [
        index
        for index, line in enumerate(original.splitlines(), start=1)
        if needle and needle in line
    ][:20]


def heading_warnings(relative: str, markdown: str) -> list[dict]:
    warnings: list[dict] = []
    suspicious_text = re.compile(
        r"本资料|资料仅用(?:于|干)?学习交流|仅用于学习交流|禁止用于商业用途|公众号|医考侠|_part\d+|�|□"
    )
    minor_as_heading = re.compile(r"^(?:\(?\d+[.．、）)]|[（(]\d+[）)])")
    fragment_start = re.compile(r"^[、，,:：;；]|^(?:图|表)\s*\d")
    for number, line in enumerate(markdown.splitlines(), start=1):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if not match:
            continue
        title = match.group(2).strip()
        reasons: list[str] = []
        if len(title) > 80:
            reasons.append("标题超过 80 字")
        if suspicious_text.search(title):
            reasons.append("标题含水印或 OCR 占位符")
        if len(match.group(1)) == 2 and minor_as_heading.search(title):
            reasons.append("数字条目疑似误升为二级标题")
        if len(match.group(1)) == 2 and fragment_start.search(title):
            reasons.append("标题疑似正文残片或图表题")
        if title.count("(") != title.count(")") or title.count("（") != title.count("）"):
            reasons.append("标题括号不配对")
        if reasons:
            warnings.append(
                {"artifact": relative, "line": number, "title": title, "reasons": reasons}
            )
    return warnings


def count_noise(markdown: str) -> dict[str, int]:
    patterns = {
        "replacement_character": r"�",
        "square_placeholder": r"□",
        "watermark_text": (
            r"本资料|资料仅用(?:于|干)?学习交流|仅用于学习交流|禁止用于商业用途|公众号|医考侠"
        ),
        "part_marker": r"_part\d+",
        "latex_fragment": r"\$[^\n$]+\$",
        "suspected_xray_ocr": r"×线",
        "occlusion_character": r"𬌗",
        "suspected_occlusion_ocr": "|".join(
            re.escape(before) for before, _after in SAFE_OCCLUSION_REPLACEMENTS
        ),
        "possible_missing_occlusion": "|".join(
            f"(?:{item['pattern']})"
            for item in OCCLUSION_PROFILE.get("missing_character_patterns", [])
            if item.get("action") == "detect_only"
        ),
        "html_table": r"<table\b",
        "markdown_table_separator": r"(?m)^\s*\|?\s*:?-{3,}",
    }
    return {name: len(re.findall(pattern, markdown, re.IGNORECASE)) for name, pattern in patterns.items()}


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare_source_only_candidate(original: str, layout: dict) -> tuple[str, list[dict]]:
    """Blank reviewed scan-only heading lines while preserving every original line number."""
    lines = original.splitlines()
    transformations: list[dict] = []
    noise = re.compile(
        r"本资料|资料仅用(?:于|干)?学习交流|仅用于学习交流|禁止用于商业用途|公众号|医考侠|_part\d+",
        re.IGNORECASE,
    )
    chapters = layout.get("chapters", [])
    chapter_starts = [int(chapter["source_line_start"]) for chapter in chapters]
    repeated_chapter_lines: set[int] = set()
    for index, chapter in enumerate(chapters):
        prefix_match = re.match(r"^(第[^\s]+章)", str(chapter["title"]))
        if not prefix_match:
            continue
        prefix = prefix_match.group(1)
        start = chapter_starts[index]
        end = chapter_starts[index + 1] - 1 if index + 1 < len(chapter_starts) else len(lines)
        for line_number in range(start + 1, end + 1):
            match = re.match(r"^#{1,6}\s+(.+?)\s*$", lines[line_number - 1])
            if match and match.group(1).strip().startswith(prefix):
                repeated_chapter_lines.add(line_number)
    for index, line in enumerate(lines):
        if not noise.search(line) and index + 1 not in repeated_chapter_lines:
            continue
        lines[index] = ""
        transformations.append(
            {
                "line": index + 1,
                "kind": (
                    "remove_repeated_chapter_header"
                    if index + 1 in repeated_chapter_lines and not noise.search(line)
                    else "remove_scan_metadata_line"
                ),
                "before": line,
                "after": lines[index],
            }
        )
    for before_text, after_text in SAFE_OCCLUSION_REPLACEMENTS:
        for index, line in enumerate(lines):
            if before_text not in line:
                continue
            updated, count = replace_occlusion_alias(line, before_text, after_text)
            if not count:
                continue
            lines[index] = updated
            transformations.append(
                {
                    "line": index + 1,
                    "kind": "normalize_occlusion_term",
                    "before": line,
                    "after": updated,
                    "reason": "𬌗字的确定性完整词组归一化；不执行单字符全局替换",
                    "occurrences": count,
                }
            )
    for repair in SAFE_OCCLUSION_MISSING_PATTERNS:
        pattern = re.compile(str(repair["pattern"]))
        replacement = str(repair["replacement"])
        for index, line in enumerate(lines):
            updated, count = pattern.subn(replacement, line)
            if not count:
                continue
            lines[index] = updated
            transformations.append(
                {
                    "line": index + 1,
                    "kind": "restore_missing_occlusion_character",
                    "before": line,
                    "after": updated,
                    "reason": str(repair["reason"]),
                    "rule": str(repair["id"]),
                }
            )
    for replacement in layout.get("reviewed_replacements", []):
        before_text = str(replacement.get("from") or "")
        after_text = str(replacement.get("to") or "")
        if not before_text or before_text == after_text:
            raise ValueError("reviewed replacement must contain distinct non-empty text")
        for index, line in enumerate(lines):
            if before_text not in line:
                continue
            updated = line.replace(before_text, after_text)
            lines[index] = updated
            transformations.append(
                {
                    "line": index + 1,
                    "kind": "reviewed_phrase_replacement",
                    "before": line,
                    "after": updated,
                    "reason": str(replacement.get("reason") or "人工复核的完整词组修复"),
                }
            )
    suffix = "\n" if original.endswith("\n") else ""
    return "\n".join(lines) + suffix, transformations


def source_only_chapter_inputs(
    original: str, candidate: str, layout: dict
) -> list[dict]:
    original_lines = original.splitlines()
    candidate_lines = candidate.splitlines()
    all_chapters = layout.get("chapters", [])
    chapters, _content_policy = content_chapters(all_chapters)
    starts = [int(chapter.get("source_line_start", 0)) for chapter in chapters]
    if not starts or any(start < 1 or start > len(original_lines) for start in starts):
        raise ValueError("source-only layout chapter line is missing or outside the source")
    if starts != sorted(set(starts)):
        raise ValueError("source-only layout chapter lines must be unique and increasing")

    inputs: list[dict] = []
    first_index = first_chapter_index(all_chapters)
    for index, chapter in enumerate(chapters):
        start = starts[index]
        expected_heading = str(chapter.get("source_heading") or "").strip()
        actual = original_lines[start - 1]
        match = re.match(r"^#{1,6}\s+(.+?)\s*$", actual)
        if not match or match.group(1).strip() != expected_heading:
            raise ValueError(
                f"source heading mismatch at line {start}: expected {expected_heading!r}, got {actual!r}"
            )
        end = starts[index + 1] - 1 if index + 1 < len(starts) else len(candidate_lines)
        text = "\n".join(candidate_lines[start - 1 : end]).strip() + "\n"
        inputs.append(
            {
                "name": str(chapter["artifact"]),
                "title": str(chapter["title"]),
                "text": text,
                "external": None,
                "source_line_start": start,
                "source_order": first_index + index + 1,
            }
        )
    return inputs


def build_quality_report(
    original: str,
    candidate: str,
    chapters: list[dict],
    combined_published: str,
) -> dict:
    blockers: list[dict] = []
    warnings: list[dict] = []
    numeric_orders: list[int] = []

    for chapter in chapters:
        if chapter["character_count"] < MIN_CHAPTER_CHARS:
            blockers.append(
                {
                    "code": "empty_or_too_short_chapter",
                    "chapter_id": chapter["id"],
                    "artifact": chapter["artifact"],
                    "characters": chapter["character_count"],
                }
            )
        match = re.match(r"^(\d+)-", Path(chapter["artifact"]).name)
        if match and int(match.group(1)) > 0:
            numeric_orders.append(int(match.group(1)))
        warnings.extend(chapter.pop("heading_warnings"))

    expected = list(range(1, max(numeric_orders, default=0) + 1))
    if numeric_orders != expected:
        blockers.append(
            {"code": "chapter_order_gap_or_duplicate", "actual": numeric_orders, "expected": expected}
        )

    original_chars = len(original)
    candidate_chars = len(candidate)
    published_chars = len(combined_published)
    candidate_ratio = candidate_chars / original_chars if original_chars else 0
    published_ratio = published_chars / candidate_chars if candidate_chars else 0
    if candidate_ratio < 0.85:
        blockers.append(
            {"code": "candidate_abnormally_short", "ratio": round(candidate_ratio, 4)}
        )
    if published_ratio < 0.85:
        blockers.append(
            {"code": "published_chapters_abnormally_short", "ratio": round(published_ratio, 4)}
        )

    noise = count_noise(combined_published)
    for key in ("replacement_character", "square_placeholder", "watermark_text", "part_marker"):
        if noise[key]:
            warnings.append({"code": "ocr_noise", "kind": key, "count": noise[key]})
    if noise["latex_fragment"]:
        warnings.append({"code": "latex_fragments_need_review", "count": noise["latex_fragment"]})
    if noise["suspected_xray_ocr"]:
        warnings.append({"code": "suspected_xray_ocr", "count": noise["suspected_xray_ocr"]})
    if noise["possible_missing_occlusion"]:
        warnings.append(
            {
                "code": "possible_missing_occlusion",
                "count": noise["possible_missing_occlusion"],
                "handling": "detect_only",
            }
        )

    return {
        "status": "blocked" if blockers else ("warning" if warnings else "pass"),
        "blockers": blockers,
        "warnings": warnings,
        "metrics": {
            "original_characters": original_chars,
            "candidate_characters": candidate_chars,
            "published_chapter_characters": published_chars,
            "candidate_to_original_ratio": round(candidate_ratio, 4),
            "published_to_candidate_ratio": round(published_ratio, 4),
            "chapter_count": len(chapters),
            "noise": noise,
        },
    }


def quality_markdown(report: dict) -> str:
    metrics = report["metrics"]
    lines = [
        "# YuReader 导入质量报告",
        "",
        f"- 结论：**{report['status']}**",
        f"- 章节文件：{metrics['chapter_count']}",
        f"- 原始字符数：{metrics['original_characters']}",
        f"- 候选清洗字符数：{metrics['candidate_characters']}",
        f"- 发布章节字符数：{metrics['published_chapter_characters']}",
        f"- 候选/原始比例：{metrics['candidate_to_original_ratio']:.2%}",
        f"- 发布章节/候选比例：{metrics['published_to_candidate_ratio']:.2%}",
        "",
        "## 阻断问题",
        "",
    ]
    if report["blockers"]:
        lines.extend(f"- `{item['code']}`：`{json.dumps(item, ensure_ascii=False)}`" for item in report["blockers"])
    else:
        lines.append("- 无。允许进入正式书架。")
    lines.extend(
        [
            "",
            "## 自动观察项",
            "",
            "以下项目用于后续规则改进，不要求用户逐条人工复核，也不阻断阅读。",
            "",
        ]
    )
    if report["warnings"]:
        for item in report["warnings"]:
            if "artifact" in item:
                reasons = "；".join(item["reasons"])
                lines.append(f"- `{item['artifact']}:{item['line']}` {item['title']} — {reasons}")
            else:
                lines.append(f"- `{item['code']}`：`{json.dumps(item, ensure_ascii=False)}`")
    else:
        lines.append("- 无。")
    lines.extend(["", "## 噪声计数", ""])
    lines.extend(f"- `{name}`：{count}" for name, count in metrics["noise"].items())
    lines.append("")
    return "\n".join(lines)


def build_reading_layout(
    staging: Path,
    layout_path: Path,
    book_id: str,
    original_text: str,
    candidate_artifact: str,
    candidate_chapters_external: bool,
) -> tuple[list[dict], list[dict], dict]:
    """Split cleaned chapters only at explicit, reviewed table-of-contents headings."""
    layout = json.loads(read_text(layout_path))
    if layout.get("schema_version") != 1 or layout.get("book_id") != book_id:
        raise ValueError("layout schema or book id does not match the import")

    pages_dir = staging / "cleaned" / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    toc: list[dict] = []
    pages: list[dict] = []
    blockers: list[dict] = []

    layout_chapters, _content_policy = content_chapters(layout.get("chapters", []))
    for chapter_order, chapter in enumerate(layout_chapters, start=1):
        source_order = int(chapter.get("source_order") or chapter_order)
        source_relative = f"cleaned/chapters/{chapter['artifact']}"
        source_path = staging / source_relative
        if not source_path.is_file():
            blockers.append({"code": "layout_chapter_missing", "artifact": source_relative})
            continue
        source_text = read_text(source_path).strip() + "\n"
        source_lines = source_text.splitlines()
        markers: list[int] = []
        for section in chapter.get("sections", []):
            anchor = section.get("anchor")
            heading = section.get("heading")
            if anchor is not None:
                needle = str(anchor)
                matches = [index for index, line in enumerate(source_lines) if needle in line]
                if len(matches) != 1:
                    blockers.append(
                        {
                            "code": "layout_anchor_not_unique",
                            "artifact": source_relative,
                            "anchor": needle,
                            "matches": len(matches),
                        }
                    )
                    markers.append(-1)
                else:
                    markers.append(matches[0])
            elif heading is None:
                markers.append(0)
                continue
            else:
                pattern = re.compile(rf"^#{{1,6}}\s+{re.escape(str(heading))}\s*$")
                matches = [index for index, line in enumerate(source_lines) if pattern.match(line)]
                if len(matches) != 1:
                    blockers.append(
                        {
                            "code": "layout_heading_not_unique",
                            "artifact": source_relative,
                            "heading": heading,
                            "matches": len(matches),
                        }
                    )
                    markers.append(-1)
                else:
                    markers.append(matches[0])
        if any(marker < 0 for marker in markers) or markers != sorted(markers):
            continue

        # Use the source order as the ID seed so removing front matter does
        # not invalidate notes already attached to the first real chapter.
        chapter_id = stable_chapter_id(book_id, source_order)
        section_ids: list[str] = []
        for section_order, (section, marker) in enumerate(zip(chapter["sections"], markers), start=1):
            start = 0 if section_order == 1 else marker
            end = markers[section_order] if section_order < len(markers) else len(source_lines)
            page_text = "\n".join(source_lines[start:end]).strip() + "\n"
            page_id = stable_section_id(book_id, source_order, section_order)
            destination = pages_dir / f"{chapter_order:02d}-{section_order:02d}.md"
            destination.write_text(page_text, encoding="utf-8")
            artifact = destination.relative_to(staging).as_posix()
            entry = {
                "id": page_id,
                "order": len(pages) + 1,
                "chapter_id": chapter_id,
                "chapter_order": chapter_order,
                "chapter_title": str(chapter["title"]),
                "section_order": section_order,
                "title": str(section["title"]),
                "level": 2,
                "artifact": artifact,
                "material_kind": "cleaned",
                "character_count": len(page_text),
                "line_count": line_count(page_text),
                "sha256": sha256_file(destination),
                "source_map": {
                    "cleaned_chapter": source_relative,
                    "cleaned_line_start": start + 1,
                    "cleaned_line_end": end,
                    "original_line_start": int(chapter.get("source_line_start", 0)) + start,
                    "original_line_end": int(chapter.get("source_line_start", 0)) + end - 1,
                    "candidate_artifact": candidate_artifact,
                    "candidate_chapter_external": (
                        f"chapters/{chapter['artifact']}" if candidate_chapters_external else None
                    ),
                    "original_artifact": "original/source.md",
                    "original_heading_line_candidates": original_heading_candidates(
                        original_text, str(chapter["title"])
                    ),
                },
            }
            pages.append(entry)
            section_ids.append(page_id)
        toc.append(
            {
                "id": chapter_id,
                "order": chapter_order,
                "title": str(chapter["title"]),
                "section_ids": section_ids,
            }
        )

    sizes = [page["character_count"] for page in pages]
    oversized = [
        {
            "section_id": page["id"],
            "chapter": page["chapter_title"],
            "title": page["title"],
            "characters": page["character_count"],
        }
        for page in pages
        if page["character_count"] > OVERSIZED_PAGE_CHARS
    ]
    report = {
        "status": "blocked" if blockers else ("warning" if oversized else "pass"),
        "blockers": blockers,
        "oversized_pages": oversized,
        "content_start": _content_policy["mode"],
        "excluded_prefix_chapter_count": _content_policy["excluded_prefix_chapter_count"],
        "first_chapter_title": _content_policy["first_chapter_title"],
        "metrics": {
            "chapter_count": len(toc),
            "section_count": len(pages),
            "total_characters": sum(sizes),
            "minimum_characters": min(sizes, default=0),
            "maximum_characters": max(sizes, default=0),
            "average_characters": round(sum(sizes) / len(sizes)) if sizes else 0,
            "oversized_threshold": OVERSIZED_PAGE_CHARS,
        },
    }
    write_json(staging / "reports" / "layout.json", report)
    return toc, pages, report


def build_package(args: argparse.Namespace) -> tuple[Path, dict]:
    source = args.source.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"required input missing: {source}")
    source_hash = sha256_file(source)
    original_text = read_text(source)
    layout_payload = json.loads(read_text(args.layout.resolve())) if args.layout else None
    transformations: list[dict] = []
    if args.candidate_run:
        run_dir = args.candidate_run.resolve()
        candidate = run_dir / args.candidate_file
        chapter_dir = run_dir / "chapters"
        process_result = run_dir / "_process_result.json"
        for required in (candidate, chapter_dir, process_result):
            if not required.exists():
                raise FileNotFoundError(f"required input missing: {required}")
        prior = json.loads(read_text(process_result))
        if str(prior.get("sha256", "")).lower() != source_hash:
            raise ValueError("candidate run does not declare the same source SHA-256")
        chapter_files = sorted(chapter_dir.glob("*.md"), key=chapter_sort_key)
        if not chapter_files:
            raise ValueError("candidate run contains no chapter Markdown files")
        candidate_text = read_text(candidate)
        chapter_inputs = [
            {
                "name": path.name,
                "title": chapter_title(path, read_text(path)),
                "text": read_text(path),
                "external": f"chapters/{path.name}",
                "source_order": index,
            }
            for index, path in enumerate(chapter_files, start=1)
        ]
        chapter_inputs, content_policy = content_chapters(chapter_inputs)
        candidate_artifact = "raw/agent-cleaned-candidate.md"
        process_artifact = "raw/agent-process-result.json"
        candidate_external_run = str(run_dir)
        candidate_chapters_external = True
    else:
        if not layout_payload:
            raise ValueError("source-only import requires --layout")
        candidate_text, transformations = prepare_source_only_candidate(original_text, layout_payload)
        chapter_inputs = source_only_chapter_inputs(original_text, candidate_text, layout_payload)
        _layout_chapters, content_policy = content_chapters(layout_payload.get("chapters", []))
        candidate_artifact = "raw/source-import-candidate.md"
        process_artifact = "raw/import-process-result.json"
        candidate_external_run = None
        candidate_chapters_external = False

    final_workspace = WORKSPACE_DIR / args.book_id
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{args.book_id}-", dir=WORKSPACE_DIR))
    try:
        for name in ("original", "raw", "cleaned/chapters", "slices", "reports"):
            (staging / name).mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, staging / "original" / "source.md")
        (staging / candidate_artifact).write_text(candidate_text, encoding="utf-8")
        if args.candidate_run:
            shutil.copy2(process_result, staging / process_artifact)
        else:
            write_json(
                staging / process_artifact,
                {
                    "mode": "source_only_reviewed_layout",
                    "sha256": source_hash,
                    "transformations": transformations,
                },
            )

        chapter_entries: list[dict] = []
        combined: list[str] = []
        for order, chapter_input in enumerate(chapter_inputs, start=1):
            text = str(chapter_input["text"]).strip() + "\n"
            destination = staging / "cleaned" / "chapters" / str(chapter_input["name"])
            destination.write_text(text, encoding="utf-8")
            relative = destination.relative_to(staging).as_posix()
            title = str(chapter_input["title"] or chapter_title(destination, text))
            chapter_entries.append(
                {
                    "id": stable_chapter_id(
                        args.book_id, int(chapter_input.get("source_order") or order)
                    ),
                    "order": order,
                    "title": title,
                    "level": 1,
                    "artifact": relative,
                    "material_kind": "cleaned",
                    "character_count": len(text),
                    "line_count": line_count(text),
                    "sha256": sha256_file(destination),
                "source_map": {
                    "candidate_artifact": candidate_artifact,
                    "candidate_chapter_external": chapter_input["external"],
                    "original_artifact": "original/source.md",
                    "original_source_line_start": chapter_input.get("source_line_start"),
                    "original_heading_line_candidates": original_heading_candidates(original_text, title),
                },
                    "heading_warnings": heading_warnings(relative, text),
                }
            )
            combined.append(text)

        report = build_quality_report(original_text, candidate_text, chapter_entries, "\n".join(combined))
        toc: list[dict] = []
        reading_sections = chapter_entries
        layout_report = None
        if args.layout:
            toc, reading_sections, layout_report = build_reading_layout(
                staging,
                args.layout.resolve(),
                args.book_id,
                original_text,
                candidate_artifact,
                candidate_chapters_external,
            )
            report["blockers"].extend(layout_report["blockers"])
            report["status"] = "blocked" if report["blockers"] else report["status"]
        write_json(staging / "reports" / "quality.json", report)
        (staging / "reports" / "quality.md").write_text(quality_markdown(report), encoding="utf-8")
        (staging / "slices" / "README.md").write_text(
            "# 语义切片\n\n本目录预留给以后供侧边栏 AI 阅读的语义切片。当前导入只发布清洗正文，不生成或伪造切片。\n",
            encoding="utf-8",
        )

        created_at = datetime.now().astimezone().isoformat(timespec="seconds")
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "book": {
                "id": args.book_id,
                "title": args.title,
                "edition": args.edition,
                "status": "ready" if not report["blockers"] else "blocked",
                "default_material": "cleaned",
            },
            "created_at": created_at,
            "provenance": {
                "original": {
                    "external_path": str(source),
                    "artifact": "original/source.md",
                    "sha256": source_hash,
                    "bytes": source.stat().st_size,
                },
                "cleaned_candidate": {
                    "mode": "external_agent_run" if args.candidate_run else "source_only_reviewed_layout",
                    "external_run": candidate_external_run,
                    "artifact": candidate_artifact,
                    "sha256": sha256_file(staging / candidate_artifact),
                    "process_result": process_artifact,
                    "transformation_count": len(transformations),
                },
            },
            "artifacts": {
                "original": "original/source.md",
                "cleaned_chapters": "cleaned/chapters",
                "slices": "slices",
                "quality_report": "reports/quality.json",
            },
            "quality": {
                "status": report["status"],
                "blocker_count": len(report["blockers"]),
                "warning_count": len(report["warnings"]),
                "report": "reports/quality.json",
            },
            "reading_layout": {
                "mode": "table_of_contents" if args.layout else "chapter_files",
                "chapter_count": len(toc) if toc else len(chapter_entries),
                "section_count": len(reading_sections),
                "oversized_page_count": len(layout_report["oversized_pages"]) if layout_report else 0,
                "report": "reports/layout.json" if layout_report else None,
                "content_start": content_policy["mode"],
                "excluded_prefix_chapter_count": content_policy["excluded_prefix_chapter_count"],
                "first_chapter_title": content_policy["first_chapter_title"],
            },
            "toc": toc,
            "sections": reading_sections,
            "source_chapters": chapter_entries,
        }
        write_json(staging / "manifest.json", manifest)

        if final_workspace.exists():
            backup = WORKSPACE_DIR / f".{args.book_id}-previous"
            if backup.exists():
                shutil.rmtree(backup)
            final_workspace.replace(backup)
            staging.replace(final_workspace)
            shutil.rmtree(backup)
        else:
            staging.replace(final_workspace)
        return final_workspace, manifest
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def publish_package(workspace: Path, manifest: dict) -> Path:
    if manifest["quality"]["blocker_count"]:
        raise ValueError("quality blockers prevent publication")
    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    target = CONTENT_DIR / manifest["book"]["id"]
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=CONTENT_DIR))
    try:
        shutil.copy2(workspace / "manifest.json", staging / "manifest.json")
        shutil.copytree(workspace / "cleaned", staging / "cleaned", dirs_exist_ok=True)
        shutil.copytree(workspace / "reports", staging / "reports", dirs_exist_ok=True)
        if target.exists():
            backup = CONTENT_DIR / f".{target.name}-previous"
            if backup.exists():
                shutil.rmtree(backup)
            target.replace(backup)
            staging.replace(target)
            shutil.rmtree(backup)
        else:
            staging.replace(target)
        return target
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--candidate-run", type=Path)
    parser.add_argument("--candidate-file", default="「正畸」第7版_整理版.md")
    parser.add_argument("--book-id", required=True, choices=None)
    parser.add_argument("--title", required=True)
    parser.add_argument("--edition", default="")
    parser.add_argument("--layout", type=Path)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", args.book_id):
        parser.error("--book-id must be 3-64 lowercase ASCII letters, digits, or hyphens")
    return args


def main() -> None:
    args = parse_args()
    workspace, manifest = build_package(args)
    output = {"workspace": str(workspace), "quality": manifest["quality"], "published": None}
    if args.publish:
        output["published"] = str(publish_package(workspace, manifest))
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
