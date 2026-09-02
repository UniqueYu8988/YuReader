from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


TOOL_VERSION = "0.4.1"
DERIVED_TEXT_HASH_ALGORITHM = "canonical-json-page-set-v1"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE = ROOT / "workspace"
DEFAULT_CONTENT_ROOT = Path(__file__).resolve().parents[3] / "content"
OCCLUSION_TERMS_PATH = ROOT.parent / "occlusion_terms.json"

NODE_KINDS = {"chapter", "section", "topic", "supporting"}
PAGE_ROLES = {"reading", "reference"}
VALID_DOMAINS = {"medicine", "politics", "english"}
VALID_RESOURCE_TYPES = {"book", "lecture", "question_bank", "reference"}
LONG_READING_WARNING = 30_000
WATERMARK_HEADING_PREFIXES = (
    "本资料仅用",
    "关注微信公众号：医考侠",
    "关注微信公众号:医考侠",
    # The political Core Exam Guide OCR repeats its series title as a page
    # header.  It is not a subject heading and must not appear in reading
    # pages; the immutable source still retains every occurrence.
    "考研政治核心考案",
)

MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s*(.+?)\s*$")
BARE_HEADING = re.compile(
    r"^(?:第[〇零一二三四五六七八九十百两0-9]+[章节篇部卷]\s*.+|附录.*|实习教程.*|中英文名词对照索引.*)$"
)
CHAPTER_MARKER = re.compile(r"^第([〇零一二三四五六七八九十百两0-9]+)章")
SECTION_MARKER = re.compile(r"^第([〇零一二三四五六七八九十百两0-9]+)节")
TOPIC_MARKER = re.compile(r"^([〇零一二三四五六七八九十百两]+)、")
PAREN_CN_MARKER = re.compile(r"^[（(]([〇零一二三四五六七八九十百两]+)[）)]")
PAREN_DIGIT_MARKER = re.compile(r"^[（(](\d+)[）)]")
NAVIGATION_SPACING_PREFIX = re.compile(
    r"^(?:第[〇零一二三四五六七八九十百两0-9]+[章节]|实验[〇零一二三四五六七八九十百两0-9]+)(?=\S)"
)
SUSPICIOUS_NAVIGATION = (
    re.compile(r"^[A-Z]$"),
    re.compile(r"^【.+】$"),
    re.compile(r"(?:如下|包括)[:：]?$"),
    re.compile(r"^[（(]\d+[）)](?:制作技术|局部因素|充填)?$"),
)


class YuBookError(RuntimeError):
    pass


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(encoded)


def derived_text_hash(items: list[dict]) -> str:
    """Hash the ordered reading/reference artifact set without duplicating text."""
    page_set = []
    for item in sorted(
        items,
        key=lambda item: (
            item["source_map"].get("original_char_start", item["source_map"]["original_line_start"]),
            item["source_map"].get("original_char_end", item["source_map"]["original_line_end"]),
            item["artifact"],
        ),
    ):
        source_map = item["source_map"]
        entry = {
            "artifact": item["artifact"],
            "sha256": item["sha256"],
            "original_line_start": source_map["original_line_start"],
            "original_line_end": source_map["original_line_end"],
        }
        if "original_char_start" in source_map or "original_char_end" in source_map:
            entry["original_char_start"] = source_map.get("original_char_start")
            entry["original_char_end"] = source_map.get("original_char_end")
        page_set.append(entry)
    return canonical_hash(page_set)


def stable_id(*parts: object) -> str:
    return sha256_bytes(":".join(str(part) for part in parts).encode("utf-8"))[:12]


def load_section_aliases(content_root: Path) -> dict[str, str]:
    """Load only the stable-ID alias edges used by replacement validation."""
    alias_path = content_root.parent / "data" / "section-aliases.json"
    try:
        payload = json.loads(read_text(alias_path))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        return {}
    raw_aliases = payload.get("section_aliases")
    if not isinstance(raw_aliases, dict):
        return {}
    aliases: dict[str, str] = {}
    for legacy_id, entry in raw_aliases.items():
        current_id = entry.get("current_id") if isinstance(entry, dict) else None
        if (
            isinstance(legacy_id, str)
            and re.fullmatch(r"[0-9a-f]{12}", legacy_id)
            and isinstance(current_id, str)
            and re.fullmatch(r"[0-9a-f]{12}", current_id)
            and legacy_id != current_id
        ):
            aliases[legacy_id] = current_id
    return aliases


def resolve_section_alias(section_id: object, aliases: dict[str, str]) -> str | None:
    """Resolve an alias edge safely, returning None for cycles or invalid IDs."""
    current = str(section_id or "")
    if not re.fullmatch(r"[0-9a-f]{12}", current):
        return None
    visited: set[str] = set()
    while current in aliases:
        if current in visited:
            return None
        visited.add(current)
        current = aliases[current]
        if not re.fullmatch(r"[0-9a-f]{12}", current):
            return None
    return current


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> dict:
    try:
        payload = json.loads(read_text(path))
    except (OSError, json.JSONDecodeError) as exc:
        raise YuBookError(f"无法读取 JSON：{path}：{exc}") from exc
    if not isinstance(payload, dict):
        raise YuBookError(f"JSON 顶层必须是对象：{path}")
    return payload


def build_occlusion_aliases(profile: dict) -> tuple[tuple[str, str], ...]:
    """Build complete-term aliases without ever treating a bare glyph as safe."""
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
    aliases: dict[str, str] = {}
    for canonical in canonical_terms:
        for confusion in confusions:
            alias = canonical.replace("𬌗", str(confusion))
            if alias != canonical:
                aliases[alias] = canonical
    for item in profile.get("explicit_aliases", []):
        aliases[str(item["from"])] = str(item["to"])
    return tuple(sorted(aliases.items(), key=lambda pair: (-len(pair[0]), pair[0])))


def count_unprotected_alias(text: str, alias: str, profile: dict) -> int:
    """Count a complete OCR alias while ignoring overlaps with legitimate words."""
    single = tuple(str(item) for item in profile.get("confusions", {}).get("single_character_substitutions", []))
    protected = tuple(str(item) for item in profile.get("confusions", {}).get("preserve_as_written", []))
    # Multi-character OCR aliases can themselves contain an ordinary protected
    # word (for example, 𬌗向 -> 体验向 inside “整体验向移动”).  Preserve the
    # surrounding legitimate word just as we do for single-character aliases;
    # ambiguous overlaps must not become deterministic blockers.
    protect_overlap = any(char in alias for char in single) or any(word in alias for word in protected)
    count = 0
    cursor = 0
    while (index := text.find(alias, cursor)) >= 0:
        end = index + len(alias)
        overlaps = False
        if protect_overlap:
            for word in protected:
                search_start = max(0, index - len(word) + 1)
                word_start = text.find(word, search_start)
                while 0 <= word_start < end:
                    if word_start + len(word) > index:
                        overlaps = True
                        break
                    word_start = text.find(word, word_start + 1)
                if overlaps:
                    break
        if not overlaps:
            count += 1
        cursor = end
    return count


def audit_derived_occlusion(lines: list[str], start: int, end: int) -> dict:
    """Find deterministic 𬌗 defects in the text that would actually be published."""
    profile = load_json(OCCLUSION_TERMS_PATH)
    text = "".join(lines[start - 1 : end])
    aliases = [
        {"found": alias, "canonical": canonical, "count": count}
        for alias, canonical in build_occlusion_aliases(profile)
        if (count := count_unprotected_alias(text, alias, profile))
    ]
    automatic_missing = []
    for rule in profile.get("missing_character_patterns", []):
        if rule.get("action") != "automatic":
            continue
        count = len(re.findall(str(rule["pattern"]), text))
        if count:
            automatic_missing.append(
                {
                    "rule": rule.get("id"),
                    "replacement": rule.get("replacement"),
                    "count": count,
                }
            )
    return {"aliases": aliases, "automatic_missing": automatic_missing}


def source_lines(path: Path) -> list[str]:
    # Path.read_text() uses universal-newline translation.  Keep the source's
    # actual CRLF/LF bytes so a page range can be reconstructed byte-for-byte.
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return handle.read().splitlines(keepends=True)


def source_line_offsets(lines: list[str]) -> list[int]:
    """Return absolute character offsets for the start of each source line."""
    offsets: list[int] = []
    cursor = 0
    for line in lines:
        offsets.append(cursor)
        cursor += len(line)
    return offsets


def page_source_text(lines: list[str], page: dict, *, cleaned_lines: list[str] | None = None) -> str:
    """Materialize one page, optionally using an auditable character span.

    Normal pages continue to use inclusive source line ranges.  A page may
    additionally declare ``start_char``/``end_char`` (absolute, end-exclusive)
    when several independent tables share one physical source line.  The
    character-span form is deliberately line-preserving: callers must provide
    the same-length cleaned lines, so deterministic replacements cannot shift
    an offset silently.
    """
    source = "".join(cleaned_lines if cleaned_lines is not None else lines)
    start_char = page.get("start_char")
    end_char = page.get("end_char")
    if start_char is not None or end_char is not None:
        if not isinstance(start_char, int) or not isinstance(end_char, int):
            raise YuBookError("字符切页必须同时提供整数 start_char/end_char")
        if start_char < 0 or end_char <= start_char or end_char > len(source):
            raise YuBookError("字符切页范围无效")
        text = source[start_char:end_char]
    else:
        start_line, end_line = page["start_line"], page["end_line"]
        text = "".join((cleaned_lines if cleaned_lines is not None else lines)[start_line - 1 : end_line])
    prefix = page.get("char_prefix", "")
    suffix = page.get("char_suffix", "")
    if not isinstance(prefix, str) or not isinstance(suffix, str):
        raise YuBookError("字符切页的 char_prefix/char_suffix 必须是字符串")
    return f"{prefix}{text}{suffix}"


def line_ending(value: str) -> str:
    match = re.search(r"(\r\n|\n|\r)$", value)
    return match.group(1) if match else ""


def is_fixed_watermark_line(value: str) -> bool:
    stripped = value.strip()
    heading = MARKDOWN_HEADING.match(stripped)
    candidate = heading.group(2).strip() if heading else stripped
    return candidate.startswith(WATERMARK_HEADING_PREFIXES)


def derive_clean_lines(lines: list[str], outline: dict) -> tuple[list[str], list[dict]]:
    """Apply only auditable, line-preserving derivations to a source copy."""
    result = list(lines)
    transformations: list[dict] = []
    content = outline.get("content") if isinstance(outline.get("content"), dict) else {}
    content_start = content.get("start_line") if isinstance(content.get("start_line"), int) else 1
    content_end = content.get("end_line") if isinstance(content.get("end_line"), int) else len(lines)
    for number, value in enumerate(lines, start=1):
        if content_start <= number <= content_end and is_fixed_watermark_line(value):
            result[number - 1] = line_ending(value)
            transformations.append(
                {
                    "kind": "remove_fixed_watermark_line",
                    "line": number,
                    "before": value.rstrip("\r\n"),
                    "after": "",
                    "reason": "确定性扫描水印或公众号页眉，不属于原书正文",
                }
            )

    cleaning = outline.get("cleaning") if isinstance(outline.get("cleaning"), dict) else {}
    replacements = cleaning.get("text_replacements") if isinstance(cleaning.get("text_replacements"), list) else []
    for replacement in replacements:
        number = replacement["line"]
        old = replacement["old"]
        new = replacement["new"]
        before = result[number - 1]
        count = before.count(old)
        result[number - 1] = before.replace(old, new)
        transformations.append(
            {
                "kind": "high_confidence_text_replacement",
                "line": number,
                "before": old,
                "after": new,
                "count": count,
                "reason": replacement["reason"],
            }
        )
    return result, transformations


def inspect_markdown(path: Path) -> dict:
    text = read_text(path)
    lines = text.splitlines()
    headings: list[dict] = []
    in_fence = False
    fence_char = None
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            if not in_fence:
                in_fence = True
                fence_char = marker
            elif marker == fence_char:
                in_fence = False
                fence_char = None
            continue
        if in_fence or not stripped:
            continue
        match = MARKDOWN_HEADING.match(stripped)
        if match:
            title = match.group(2).strip()
            headings.append({"line": number, "level": len(match.group(1)), "title": title, "source": "markdown"})
        elif BARE_HEADING.match(stripped) and len(stripped) <= 100:
            headings.append({"line": number, "level": None, "title": stripped, "source": "bare_candidate"})

    first_chapters = [item for item in headings if CHAPTER_MARKER.match(item["title"]) and cn_number(CHAPTER_MARKER.match(item["title"]).group(1)) == 1]
    chapter_candidates = [item for item in headings if CHAPTER_MARKER.match(item["title"])]
    return {
        "schema_version": 1,
        "tool_version": TOOL_VERSION,
        "source": str(path.resolve()),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "line_count": len(lines),
        "character_count": len(text),
        "heading_count": len(headings),
        "chapter_candidate_count": len(chapter_candidates),
        "first_chapter_candidates": first_chapters,
        "headings": headings,
    }


def cn_number(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    units = {"十": 10, "百": 100}
    total = 0
    current = 0
    for char in value:
        if char in digits:
            current = digits[char]
        elif char in units:
            unit = units[char]
            total += (current or 1) * unit
            current = 0
        else:
            return None
    return total + current


def marker_number(title: str, pattern: re.Pattern[str]) -> int | None:
    match = pattern.match(title.strip())
    return cn_number(match.group(1)) if match else None


def resolve_project(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise YuBookError(f"工程目录不存在：{path}")
    return path


def project_source(project: Path, outline: dict | None = None) -> Path:
    artifact = "source/original.md"
    if outline:
        artifact = str(outline.get("source", {}).get("artifact") or artifact)
    path = (project / artifact).resolve()
    try:
        path.relative_to(project.resolve())
    except ValueError as exc:
        raise YuBookError("source.artifact 不能越出工程目录") from exc
    if not path.is_file():
        raise YuBookError(f"归档源文件不存在：{path}")
    return path


def command_init(args: argparse.Namespace) -> dict:
    source = Path(args.source).expanduser().resolve()
    if not source.is_file():
        raise YuBookError(f"输入文件不存在：{source}")
    if source.is_symlink():
        raise YuBookError("输入文件不能是符号链接")
    if source.suffix.lower() not in {".md", ".markdown"}:
        raise YuBookError("YuBook 0.1 只接受 Markdown")
    try:
        read_text(source)
    except UnicodeError as exc:
        raise YuBookError("输入文件不是可读的 UTF-8 Markdown") from exc

    workspace = Path(args.workspace).expanduser().resolve() if args.workspace else DEFAULT_WORKSPACE
    project = workspace / args.book_id
    if project.exists() and any(project.iterdir()):
        raise YuBookError(f"工程已存在且非空，不会覆盖：{project}")
    project.mkdir(parents=True, exist_ok=True)
    archived = project / "source" / "original.md"
    archived.parent.mkdir(parents=True, exist_ok=True)
    before = sha256_file(source)
    shutil.copy2(source, archived)
    after = sha256_file(archived)
    if before != after:
        raise YuBookError("归档副本哈希不一致")

    inspection = inspect_markdown(archived)
    book = {
        "schema_version": 1,
        "id": args.book_id,
        "title": args.title,
        "edition": args.edition or "",
        "created_at": utc_now(),
        "external_source": str(source),
        "source_sha256": before,
    }
    outline = {
        "schema_version": 1,
        "book": {"id": args.book_id, "title": args.title, "edition": args.edition or ""},
        "source": {
            "artifact": "source/original.md",
            "sha256": before,
            "line_count": inspection["line_count"],
        },
        "content": {"start_line": None, "end_line": inspection["line_count"]},
        "nodes": [],
        "pages": [],
        "issues": [],
    }
    write_json(project / "book.json", book)
    write_json(project / "inspection.json", inspection)
    write_json(project / "outline.json", outline)
    return {"status": "initialized", "project": str(project), "source_sha256": before, "next": "重建 outline.json"}


def command_inspect(args: argparse.Namespace) -> dict:
    if args.project:
        project = resolve_project(args.project)
        outline_path = project / "outline.json"
        outline = load_json(outline_path) if outline_path.is_file() else None
        source = project_source(project, outline)
    else:
        source = Path(args.source).expanduser().resolve()
        if not source.is_file():
            raise YuBookError(f"输入文件不存在：{source}")
    return inspect_markdown(source)


def add_problem(target: list[dict], code: str, message: str, **details: object) -> None:
    item = {"code": code, "message": message}
    item.update({key: value for key, value in details.items() if value is not None})
    target.append(item)


def book_metadata_errors(book_meta: dict) -> list[dict]:
    """校验可选的 domain / subject / resource_type 元数据。

    - 旧工作区、旧书包没有这些字段时返回空列表，保持完全兼容；
    - 非法 domain / resource_type 必须阻断，不能静默写入候选包；
    - subject 缺失时旧书可安全回退为 title；只有 domain=politics 才要求明确填写；
    - 显式提供的 subject 必须为字符串（非字符串视为非法）。
    """
    problems: list[dict] = []
    domain = book_meta.get("domain")
    if domain is not None:
        if not isinstance(domain, str) or domain.strip().lower() not in VALID_DOMAINS:
            add_problem(
                problems,
                "book_domain_invalid",
                "book.domain 必须是 medicine / politics / english 之一",
                domain=domain,
            )
    resource_type = book_meta.get("resource_type")
    if resource_type is not None:
        if not isinstance(resource_type, str) or resource_type.strip().lower() not in VALID_RESOURCE_TYPES:
            add_problem(
                problems,
                "book_resource_type_invalid",
                "book.resource_type 必须是 book / lecture / question_bank / reference 之一",
                resource_type=resource_type,
            )
    subject = book_meta.get("subject")
    if subject is not None and not isinstance(subject, str):
        add_problem(problems, "book_subject_invalid", "book.subject 必须是字符串", subject=subject)
    if isinstance(domain, str) and domain.strip().lower() == "politics" and (not isinstance(subject, str) or not subject.strip()):
        add_problem(problems, "book_subject_required", "政治领域（domain=politics）必须明确填写非空 book.subject", subject=subject)
    return problems


def validate_number_sequence(items: list[tuple[int, str]], code: str, blockers: list[dict], parent_id: str | None) -> None:
    if not items:
        return
    values = [number for number, _title in items]
    expected = list(range(1, len(values) + 1))
    if values != expected:
        add_problem(blockers, code, "编号不连续", parent_id=parent_id, actual=values, expected=expected, titles=[title for _number, title in items])


def validate_project(project: Path) -> tuple[dict, dict, list[str]]:
    outline = load_json(project / "outline.json")
    source = project_source(project, outline)
    lines = source_lines(source)
    source_text = "".join(lines)
    line_offsets = source_line_offsets(lines)
    blockers: list[dict] = []
    warnings: list[dict] = []

    if outline.get("schema_version") != 1:
        add_problem(blockers, "schema_version", "outline.schema_version 必须为 1")
    book = outline.get("book") if isinstance(outline.get("book"), dict) else {}
    project_book = load_json(project / "book.json")
    for field in ("id", "title", "edition"):
        if project_book.get(field, "") != book.get(field, ""):
            add_problem(
                blockers,
                "book_identity_mismatch",
                "book.json 与 outline.book 身份不一致",
                field=field,
                book_json=project_book.get(field, ""),
                outline=book.get(field, ""),
            )
    blockers.extend(book_metadata_errors(project_book))
    source_meta = outline.get("source") if isinstance(outline.get("source"), dict) else {}
    content = outline.get("content") if isinstance(outline.get("content"), dict) else {}
    actual_hash = sha256_file(source)
    if source_meta.get("sha256") != actual_hash:
        add_problem(blockers, "source_hash", "归档源文件与 outline 记录不一致", actual=actual_hash, expected=source_meta.get("sha256"))
    if source_meta.get("line_count") != len(lines):
        add_problem(blockers, "source_line_count", "源文件行数与 outline 记录不一致", actual=len(lines), expected=source_meta.get("line_count"))

    identity_evidence = book.get("identity_evidence") if isinstance(book.get("identity_evidence"), list) else []
    evidence_fields: set[str] = set()
    for index, evidence in enumerate(identity_evidence):
        if not isinstance(evidence, dict):
            add_problem(blockers, "identity_evidence_shape", "书籍身份依据必须是对象", index=index)
            continue
        field = evidence.get("field")
        line_number = evidence.get("line")
        quote = evidence.get("quote")
        if field not in {"title", "edition"} or not isinstance(line_number, int) or not isinstance(quote, str) or not quote:
            add_problem(blockers, "identity_evidence_shape", "身份依据需包含 field、line、quote", index=index)
            continue
        if line_number < 1 or line_number > len(lines) or quote not in lines[line_number - 1]:
            add_problem(blockers, "identity_evidence_missing", "身份依据未在指定原文行找到", field=field, line=line_number, quote=quote)
            continue
        evidence_fields.add(field)
    for required_field in ("title", "edition"):
        if book.get(required_field) and required_field not in evidence_fields:
            add_problem(blockers, "identity_evidence_required", "书名与版次必须由书内原文证据确认，不能只信文件名", field=required_field)

    current_id = book.get("id")
    current_title = book.get("title")
    if current_id and current_title and DEFAULT_CONTENT_ROOT.is_dir():
        for manifest_path in DEFAULT_CONTENT_ROOT.glob("*/manifest.json"):
            try:
                existing_manifest = load_json(manifest_path)
                existing = existing_manifest.get("book", {})
            except YuBookError:
                continue
            if existing.get("title") == current_title and existing.get("id") != current_id:
                add_problem(
                    blockers,
                    "existing_book_id_mismatch",
                    "同名书已在 YuReader 中使用其他稳定 ID；升级时必须复用原 ID",
                    title=current_title,
                    planned_id=current_id,
                    existing_id=existing.get("id"),
                )
                break
            if existing.get("id") != current_id:
                continue
            raw_pages = outline.get("pages") if isinstance(outline.get("pages"), list) else []
            planned_section_ids = {
                stable_id(current_id, "page", page.get("id"))
                for page in raw_pages
                if isinstance(page, dict) and page.get("role") == "reading" and isinstance(page.get("id"), str) and page.get("id")
            }
            existing_section_ids = {
                str(section.get("id"))
                for section in (existing_manifest.get("sections") if isinstance(existing_manifest.get("sections"), list) else [])
                if isinstance(section, dict) and isinstance(section.get("id"), str)
            }
            missing_ids = existing_section_ids - planned_section_ids
            if missing_ids:
                aliases = load_section_aliases(DEFAULT_CONTENT_ROOT)
                unresolved_ids = sorted(
                    section_id
                    for section_id in missing_ids
                    if resolve_section_alias(section_id, aliases) not in planned_section_ids
                )
                if unresolved_ids:
                    add_problem(
                        blockers,
                        "section_id_drift",
                        "替换书包会使现有小节稳定 ID 失联；必须保留原 ID 或先登记高置信别名",
                        book_id=current_id,
                        existing_ids=unresolved_ids,
                    )
                break

    start = content.get("start_line")
    end = content.get("end_line")
    if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start or end > len(lines):
        add_problem(blockers, "content_range", "content.start_line/end_line 无效", start_line=start, end_line=end, source_lines=len(lines))

    cleaning = outline.get("cleaning")
    if cleaning is not None and not isinstance(cleaning, dict):
        add_problem(blockers, "cleaning_shape", "outline.cleaning 必须是对象")
        cleaning = {}
    cleaning = cleaning or {}
    replacements = cleaning.get("text_replacements", [])
    if not isinstance(replacements, list):
        add_problem(blockers, "replacement_shape", "cleaning.text_replacements 必须是数组")
        replacements = []
    seen_replacements: set[tuple[int, str]] = set()
    for index, replacement in enumerate(replacements):
        if not isinstance(replacement, dict):
            add_problem(blockers, "replacement_shape", "文本替换必须是对象", index=index)
            continue
        line_number = replacement.get("line")
        old = replacement.get("old")
        new = replacement.get("new")
        reason = replacement.get("reason")
        expected_count = replacement.get("count", 1)
        if (
            not isinstance(line_number, int)
            or not isinstance(old, str)
            or len(old) < 2
            or not isinstance(new, str)
            or old == new
            or not isinstance(reason, str)
            or not reason.strip()
            or not isinstance(expected_count, int)
            or expected_count < 1
        ):
            add_problem(blockers, "replacement_shape", "替换需包含有效 line、完整 old/new、count 与 reason", index=index)
            continue
        key = (line_number, old)
        if key in seen_replacements:
            add_problem(blockers, "replacement_duplicate", "同一来源行和词组不能重复替换", line=line_number, old=old)
            continue
        seen_replacements.add(key)
        if not isinstance(start, int) or not isinstance(end, int) or line_number < start or line_number > end:
            add_problem(blockers, "replacement_line", "替换行必须位于正式内容范围", line=line_number, old=old)
        elif lines[line_number - 1].count(old) != expected_count:
            add_problem(
                blockers,
                "replacement_evidence",
                "来源行中的旧词组数量与声明不一致",
                line=line_number,
                old=old,
                actual=lines[line_number - 1].count(old),
                expected=expected_count,
            )

    occlusion_audit = {"aliases": [], "automatic_missing": []}
    replacement_blocker_codes = {
        "content_range",
        "cleaning_shape",
        "replacement_shape",
        "replacement_duplicate",
        "replacement_line",
        "replacement_evidence",
    }
    if not any(item["code"] in replacement_blocker_codes for item in blockers):
        derived_lines, _transformations = derive_clean_lines(lines, outline)
        occlusion_audit = audit_derived_occlusion(derived_lines, start, end)
        if occlusion_audit["aliases"]:
            add_problem(
                blockers,
                "occlusion_alias_residual",
                "派生正文仍含可确定归一化的𬌗完整术语，不能报告为已清零",
                candidates=occlusion_audit["aliases"],
            )
        if occlusion_audit["automatic_missing"]:
            add_problem(
                blockers,
                "occlusion_missing_residual",
                "派生正文仍含可自动补回的𬌗缺字词组",
                candidates=occlusion_audit["automatic_missing"],
            )

    raw_nodes = outline.get("nodes")
    nodes = raw_nodes if isinstance(raw_nodes, list) else []
    if not nodes:
        add_problem(blockers, "nodes_empty", "必须先建立权威目录树")
    node_map: dict[str, dict] = {}
    children: dict[str | None, list[dict]] = defaultdict(list)
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            add_problem(blockers, "node_shape", "目录节点必须是对象", index=index)
            continue
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id:
            add_problem(blockers, "node_id", "目录节点缺少稳定 id", index=index)
            continue
        if node_id in node_map:
            add_problem(blockers, "node_duplicate", "目录节点 id 重复", node_id=node_id)
            continue
        node_map[node_id] = node
        children[node.get("parent_id")].append(node)
        if node.get("kind") not in NODE_KINDS:
            add_problem(blockers, "node_kind", "目录节点 kind 无效", node_id=node_id, kind=node.get("kind"))
        if not isinstance(node.get("title"), str) or not node["title"].strip():
            add_problem(blockers, "node_title", "目录节点缺少标题", node_id=node_id)
        elif NAVIGATION_SPACING_PREFIX.search(node["title"].strip()):
            add_problem(
                blockers,
                "navigation_title_spacing",
                "章、节或实验编号后必须保留一个空格，避免正式目录出现粘连标题",
                node_id=node_id,
                title=node["title"],
            )
        if not isinstance(node.get("order"), int) or node["order"] < 1:
            add_problem(blockers, "node_order", "目录节点 order 必须为正整数", node_id=node_id)
        line = node.get("source_line")
        if isinstance(start, int) and isinstance(end, int) and (not isinstance(line, int) or line < start or line > end):
            add_problem(blockers, "node_source_line", "目录节点来源行无效", node_id=node_id, source_line=line)
        source_title = node.get("source_title")
        normalization = node.get("title_normalization")
        if source_title is not None or normalization is not None:
            if not isinstance(source_title, str) or not source_title or not isinstance(normalization, dict):
                add_problem(blockers, "title_normalization_shape", "规范化标题必须同时记录 source_title 与 title_normalization", node_id=node_id)
            elif isinstance(line, int) and 1 <= line <= len(lines):
                raw_heading = re.sub(r"^#{1,6}\s*", "", lines[line - 1].strip())
                if raw_heading != source_title:
                    add_problem(blockers, "title_normalization_source", "source_title 与来源行标题不一致", node_id=node_id, actual=raw_heading, expected=source_title)
                reason = normalization.get("reason")
                evidence_lines = normalization.get("evidence_lines")
                if not isinstance(reason, str) or not reason.strip() or not isinstance(evidence_lines, list) or not evidence_lines:
                    add_problem(blockers, "title_normalization_evidence", "标题修复必须记录原因与证据行", node_id=node_id)
                elif any(not isinstance(value, int) or value < 1 or value > len(lines) for value in evidence_lines):
                    add_problem(blockers, "title_normalization_evidence", "标题修复证据行无效", node_id=node_id, evidence_lines=evidence_lines)

    for node_id, node in node_map.items():
        parent = node.get("parent_id")
        if parent is not None and parent not in node_map:
            add_problem(blockers, "node_parent_missing", "目录节点父节点不存在", node_id=node_id, parent_id=parent)
        seen = {node_id}
        cursor = parent
        while cursor is not None and cursor in node_map:
            if cursor in seen:
                add_problem(blockers, "node_cycle", "目录树存在循环", node_id=node_id)
                break
            seen.add(cursor)
            cursor = node_map[cursor].get("parent_id")

    for parent, siblings in children.items():
        orders = [node.get("order") for node in siblings if isinstance(node.get("order"), int)]
        if len(orders) != len(set(orders)):
            add_problem(blockers, "sibling_order_duplicate", "同一父节点下 order 重复", parent_id=parent, orders=orders)
        sorted_siblings = sorted(siblings, key=lambda node: node.get("order", 10**9))
        section_numbers = [(marker_number(node.get("title", ""), SECTION_MARKER), node.get("title", "")) for node in sorted_siblings]
        section_numbers = [(number, title) for number, title in section_numbers if number is not None]
        validate_number_sequence(section_numbers, "section_number_gap", blockers, parent)
        for pattern, code in ((TOPIC_MARKER, "topic_number_gap"), (PAREN_CN_MARKER, "subtopic_number_gap"), (PAREN_DIGIT_MARKER, "digit_number_gap")):
            numbered = [(marker_number(node.get("title", ""), pattern), node.get("title", "")) for node in sorted_siblings]
            numbered = [(number, title) for number, title in numbered if number is not None]
            validate_number_sequence(numbered, code, blockers, parent)

    chapters = sorted(
        [node for node in children.get(None, []) if node.get("kind") == "chapter"],
        key=lambda node: node.get("order", 10**9),
    )
    chapter_numbers = [(marker_number(node.get("title", ""), CHAPTER_MARKER), node.get("title", "")) for node in chapters]
    chapter_numbers = [(number, title) for number, title in chapter_numbers if number is not None]
    validate_number_sequence(chapter_numbers, "chapter_number_gap", blockers, None)
    if not chapters or marker_number(chapters[0].get("title", ""), CHAPTER_MARKER) != 1:
        add_problem(blockers, "first_chapter", "正式目录必须从第一章开始")
    elif isinstance(start, int) and chapters[0].get("source_line") != start:
        add_problem(blockers, "first_chapter_boundary", "正文起点必须是第一章来源行", chapter_line=chapters[0].get("source_line"), content_start=start)

    raw_pages = outline.get("pages")
    pages = raw_pages if isinstance(raw_pages, list) else []
    if not pages:
        add_problem(blockers, "pages_empty", "必须建立阅读页面计划")
    page_ids: set[str] = set()
    page_orders: list[int] = []
    valid_pages: list[dict] = []
    node_to_pages: dict[str, list[dict]] = defaultdict(list)
    for index, page in enumerate(pages):
        if not isinstance(page, dict):
            add_problem(blockers, "page_shape", "页面必须是对象", index=index)
            continue
        page_id = page.get("id")
        if not isinstance(page_id, str) or not page_id:
            add_problem(blockers, "page_id", "页面缺少稳定 id", index=index)
            continue
        if page_id in page_ids:
            add_problem(blockers, "page_duplicate", "页面 id 重复", page_id=page_id)
        page_ids.add(page_id)
        if page.get("node_id") not in node_map:
            add_problem(blockers, "page_node_missing", "页面关联的目录节点不存在", page_id=page_id, node_id=page.get("node_id"))
        else:
            node_to_pages[page["node_id"]].append(page)
            node = node_map[page["node_id"]]
            if node.get("kind") == "supporting" and page.get("role") == "reading" and not str(page.get("reading_reason", "")).strip():
                add_problem(
                    blockers,
                    "supporting_reading_role",
                    "supporting 材料默认应作为 reference；确需进入主阅读时必须记录 reading_reason",
                    page_id=page_id,
                    title=page.get("title"),
                )
        if page.get("role") not in PAGE_ROLES:
            add_problem(blockers, "page_role", "页面 role 无效", page_id=page_id, role=page.get("role"))
        if not isinstance(page.get("title"), str) or not page["title"].strip():
            add_problem(blockers, "page_title", "页面缺少标题", page_id=page_id)
        elif NAVIGATION_SPACING_PREFIX.search(page["title"].strip()):
            add_problem(
                blockers,
                "navigation_title_spacing",
                "章、节或实验编号后必须保留一个空格，避免阅读页标题出现粘连",
                page_id=page_id,
                title=page["title"],
            )
        order = page.get("order")
        if not isinstance(order, int) or order < 1:
            add_problem(blockers, "page_order", "页面 order 必须为正整数", page_id=page_id)
        else:
            page_orders.append(order)
        p_start, p_end = page.get("start_line"), page.get("end_line")
        if not isinstance(p_start, int) or not isinstance(p_end, int) or p_start < 1 or p_end < p_start or p_end > len(lines):
            add_problem(blockers, "page_range", "页面来源范围无效", page_id=page_id, start_line=p_start, end_line=p_end)
            continue
        start_char, end_char = page.get("start_char"), page.get("end_char")
        has_char_span = start_char is not None or end_char is not None
        if has_char_span:
            if not isinstance(start_char, int) or not isinstance(end_char, int):
                add_problem(blockers, "page_char_range", "字符切页必须同时提供整数 start_char/end_char", page_id=page_id)
                continue
            line_start_offset = line_offsets[p_start - 1]
            line_end_offset = line_offsets[p_end - 1] + len(lines[p_end - 1])
            if start_char < line_start_offset or end_char > line_end_offset or end_char <= start_char:
                add_problem(
                    blockers,
                    "page_char_range",
                    "字符切页必须位于声明的来源行范围内且 end_char 大于 start_char",
                    page_id=page_id,
                    start_char=start_char,
                    end_char=end_char,
                    line_start_offset=line_start_offset,
                    line_end_offset=line_end_offset,
                )
                continue
            prefix, suffix = page.get("char_prefix", ""), page.get("char_suffix", "")
            if not isinstance(prefix, str) or not isinstance(suffix, str):
                add_problem(blockers, "page_char_wrapper", "字符切页的 char_prefix/char_suffix 必须是字符串", page_id=page_id)
                continue
            # A character offset points into the immutable source.  If a
            # line-level transformation changes that span, offsets would no
            # longer identify the same bytes; reject the page instead of
            # silently shifting its provenance.
            derived_lines, _ = derive_clean_lines(lines, outline)
            if any(derived_lines[index] != lines[index] for index in range(p_start - 1, p_end)):
                add_problem(
                    blockers,
                    "page_char_transform_conflict",
                    "字符切页所在来源行包含会改变长度的行级清洗，无法安全映射",
                    page_id=page_id,
                )
                continue
        try:
            page_text = page_source_text(lines, page)
        except YuBookError as exc:
            add_problem(blockers, "page_char_range", str(exc), page_id=page_id)
            continue
        valid_pages.append(page)
        char_count = len(page_text.strip())
        if page.get("role") == "reading" and char_count < 300:
            add_problem(warnings, "short_page", "页面偏短，需要确认是否应并入相邻自然小节", page_id=page_id, characters=char_count)
        if page.get("role") == "reading" and char_count > LONG_READING_WARNING:
            add_problem(warnings, "long_page", "自然小节超过30000字，需要检查是否存在可靠语义边界", page_id=page_id, characters=char_count)
        title = page.get("title", "").strip()
        if page.get("role") == "reading" and any(pattern.search(title) for pattern in SUSPICIOUS_NAVIGATION):
            add_problem(blockers, "navigation_fragment", "疑似正文标签、提示句或索引字母，不能作为学习页面标题", page_id=page_id, title=title)

    if page_orders and sorted(page_orders) != list(range(1, len(page_orders) + 1)):
        add_problem(blockers, "page_order_gap", "页面全书顺序必须从 1 连续递增", actual=sorted(page_orders))

    # English teaching booklets often place a course cover, category legend,
    # QR promotion, or other front matter in the same source range as the
    # first passage.  Keep the source range auditable, but surface the issue
    # so a builder can make that prefix a reference artifact or an explicit
    # derived transformation instead of showing it in the reading page.
    if str(project_book.get("domain") or "").strip().lower() == "english":
        reading_pages = [page for page in valid_pages if page.get("role") == "reading"]
        if reading_pages:
            first_page = min(reading_pages, key=lambda page: page.get("order", 10**9))
            first_text = "".join(lines[first_page["start_line"] - 1 : first_page["end_line"]])
            passage_match = re.search(r"(?m)^#{1,6}\s*Passage\s+0*1\b", first_text, re.IGNORECASE)
            if passage_match and passage_match.start() > 0:
                prefix = first_text[: passage_match.start()]
                if re.search(r"(?:二维码|赠送|免费获取|扫码|课程|社会生活类|商业经济类|科学技术类)", prefix):
                    add_problem(
                        warnings,
                        "front_matter_prefix",
                        "首个阅读页在 Passage 01 前含疑似课程/宣传前置信息；应归档或记录显式派生清理",
                        page_id=first_page.get("id"),
                        prefix_characters=len(prefix.strip()),
                    )

    def page_interval(page: dict) -> tuple[int, int]:
        if isinstance(page.get("start_char"), int) and isinstance(page.get("end_char"), int):
            return page["start_char"], page["end_char"]
        return line_offsets[page["start_line"] - 1], line_offsets[page["end_line"] - 1] + len(lines[page["end_line"] - 1])

    ordered_pages = sorted(valid_pages, key=page_interval)
    if ordered_pages and isinstance(start, int) and isinstance(end, int):
        cursor = line_offsets[start - 1]
        expected_end = line_offsets[end - 1] + len(lines[end - 1])
        for page in ordered_pages:
            interval_start, interval_end = page_interval(page)
            if interval_start != cursor:
                code = "source_gap" if interval_start > cursor else "source_overlap"
                add_problem(
                    blockers,
                    code,
                    "页面范围必须无缺口、无重叠覆盖正文",
                    expected_start=cursor,
                    page_id=page.get("id"),
                    actual_start=interval_start,
                )
            cursor = max(cursor, interval_end)
        if cursor != expected_end:
            add_problem(blockers, "source_tail", "页面没有覆盖到正文末尾", expected_end=expected_end, covered_end=cursor)

    reading_chapters: set[str] = set()
    for page in pages:
        if page.get("role") != "reading" or page.get("node_id") not in node_map:
            continue
        cursor = page["node_id"]
        while cursor in node_map:
            node = node_map[cursor]
            if node.get("kind") == "chapter":
                reading_chapters.add(cursor)
                break
            cursor = node.get("parent_id")
    for chapter in chapters:
        if chapter.get("id") not in reading_chapters:
            add_problem(blockers, "chapter_without_page", "正式章没有阅读页面", chapter_id=chapter.get("id"), title=chapter.get("title"))

    for issue in outline.get("issues", []) if isinstance(outline.get("issues"), list) else []:
        if isinstance(issue, dict) and issue.get("status", "open") != "resolved":
            add_problem(blockers, "open_issue", "outline 仍有未解决问题", issue=issue)

    knowledge_map_path = project / "knowledge-map.json"
    if knowledge_map_path.is_file():
        try:
            km_payload = load_json(knowledge_map_path)
        except YuBookError as exc:
            add_problem(blockers, "knowledge_map_shape", "knowledge-map.json 无法解析，必须为合法 JSON 对象", error=str(exc))
            km_payload = None
        if not isinstance(km_payload, dict):
            add_problem(blockers, "knowledge_map_shape", "knowledge-map.json 顶层必须为对象")
        else:
            if km_payload.get("schema_version") != 1:
                add_problem(blockers, "knowledge_map_schema", "knowledge-map.schema_version 必须为 1")
            if km_payload.get("book_id") != project_book.get("id"):
                add_problem(
                    blockers,
                    "knowledge_map_book_id",
                    "knowledge-map.book_id 与 book.json 不一致",
                    actual=km_payload.get("book_id"),
                    expected=project_book.get("id"),
                )
            if km_payload.get("input_sha256") is not None and km_payload.get("input_sha256") != actual_hash:
                add_problem(blockers, "knowledge_map_source_hash", "knowledge-map.input_sha256 与归档源文件不一致")
            entries = km_payload.get("entries")
            if entries is not None and not isinstance(entries, list):
                add_problem(blockers, "knowledge_map_shape", "knowledge-map.json 的 entries 必须是数组")
            elif isinstance(entries, list):
                seen_km: set[str] = set()
                for index, entry in enumerate(entries):
                    if not isinstance(entry, dict):
                        add_problem(blockers, "knowledge_map_entry_shape", "knowledge entry 必须是对象", index=index)
                        continue
                    knowledge_id = entry.get("knowledge_id")
                    if not isinstance(knowledge_id, str) or not knowledge_id.strip():
                        add_problem(blockers, "knowledge_map_entry_shape", "knowledge entry 缺少非空 knowledge_id", index=index)
                        continue
                    if knowledge_id in seen_km:
                        add_problem(blockers, "knowledge_map_duplicate", "knowledge-map 存在重复 knowledge_id", knowledge_id=knowledge_id)
                    seen_km.add(knowledge_id)
                    page_ids = entry.get("page_ids")
                    if page_ids is not None:
                        if not isinstance(page_ids, list) or any(not isinstance(page_id, str) for page_id in page_ids):
                            add_problem(blockers, "knowledge_map_page_ids", "knowledge entry.page_ids 必须是字符串数组", knowledge_id=knowledge_id)
                        else:
                            known_page_ids = {page.get("id") for page in outline.get("pages", []) if isinstance(page, dict)}
                            missing_page_ids = sorted(set(page_ids) - known_page_ids)
                            if missing_page_ids:
                                add_problem(
                                    blockers,
                                    "knowledge_map_page_ids",
                                    "knowledge entry 引用了不存在的阅读页",
                                    knowledge_id=knowledge_id,
                                    page_ids=missing_page_ids,
                                )

    sibling_titles: dict[tuple[str | None, str], list[str]] = defaultdict(list)
    for node in node_map.values():
        sibling_titles[(node.get("parent_id"), node.get("title", "").strip())].append(node.get("id"))
    for (parent, title), ids in sibling_titles.items():
        if title and len(ids) > 1:
            add_problem(warnings, "duplicate_sibling_title", "同一父节点下标题重复", parent_id=parent, title=title, node_ids=ids)

    report = {
        "schema_version": 1,
        "tool_version": TOOL_VERSION,
        "status": "blocked" if blockers else ("warning" if warnings else "pass"),
        "book_id": book.get("id"),
        "source_sha256": actual_hash,
        "metrics": {
            "source_lines": len(lines),
            "node_count": len(node_map),
            "chapter_count": len(chapters),
            "page_count": len(pages),
            "reading_page_count": sum(page.get("role") == "reading" for page in pages if isinstance(page, dict)),
            "reference_page_count": sum(page.get("role") == "reference" for page in pages if isinstance(page, dict)),
            "fixed_watermark_line_count": sum(
                is_fixed_watermark_line(line)
                for line in lines[(start - 1 if isinstance(start, int) else 0) : (end if isinstance(end, int) else len(lines))]
            ),
            "declared_text_replacement_count": sum(item.get("count", 1) for item in replacements if isinstance(item, dict)),
            "residual_occlusion_alias_count": sum(item["count"] for item in occlusion_audit["aliases"]),
            "automatic_missing_occlusion_count": sum(item["count"] for item in occlusion_audit["automatic_missing"]),
        },
        "blockers": blockers,
        "warnings": warnings,
    }
    return report, outline, lines


def command_validate(args: argparse.Namespace) -> dict:
    project = resolve_project(args.project)
    report, _outline, _lines = validate_project(project)
    return report


def ancestor_chapter(node_id: str, node_map: dict[str, dict]) -> dict | None:
    cursor = node_id
    while cursor in node_map:
        node = node_map[cursor]
        if node.get("kind") == "chapter":
            return node
        cursor = node.get("parent_id")
    return None


def node_breadcrumb(node_id: str, node_map: dict[str, dict]) -> list[dict]:
    result: list[dict] = []
    cursor: str | None = node_id
    seen: set[str] = set()
    while cursor in node_map and cursor not in seen:
        seen.add(cursor)
        node = node_map[cursor]
        result.append(node)
        cursor = node.get("parent_id")
    return list(reversed(result))


def command_build(args: argparse.Namespace) -> dict:
    project = resolve_project(args.project)
    report, outline, lines = validate_project(project)
    if report["blockers"]:
        raise YuBookError(f"目录或页面计划仍有 {len(report['blockers'])} 个 blocker；先运行 validate 查看")
    clean_lines, transformations = derive_clean_lines(lines, outline)
    book = outline["book"]
    book_id = book["id"]
    outline_hash = canonical_hash(outline)
    source = project_source(project, outline)
    project_book_meta = load_json(project / "book.json")
    knowledge_map_path = project / "knowledge-map.json"
    knowledge_map_input_hash = sha256_file(knowledge_map_path) if knowledge_map_path.is_file() else None
    images_source = project / "pages" / "images"
    if not images_source.is_dir():
        images_source = project / "images"
    asset_inputs = [
        {"name": path.name, "sha256": sha256_file(path)}
        for path in sorted(images_source.iterdir())
        if images_source.is_dir() and path.is_file()
    ] if images_source.is_dir() else []
    dist_root = project / "dist"
    build_hash = canonical_hash(
        {
            "outline_sha256": outline_hash,
            "source_sha256": sha256_file(source),
            "book_json_sha256": canonical_hash(project_book_meta),
            "knowledge_map_sha256": knowledge_map_input_hash,
            "assets": asset_inputs,
            "builder_version": TOOL_VERSION,
            "derived_text_hash_algorithm": DERIVED_TEXT_HASH_ALGORITHM,
        }
    )
    package = dist_root / f"{book_id}-{build_hash[:8]}"
    if package.exists():
        return {"status": "already_built", "package": str(package), "outline_sha256": outline_hash}
    dist_root.mkdir(parents=True, exist_ok=True)
    staging = dist_root / f".tmp-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        (staging / "original").mkdir()
        shutil.copy2(source, staging / "original" / "source.md")
        write_json(staging / "reports" / "outline.json", outline)

        knowledge_map_decl: dict | None = None
        if knowledge_map_path.is_file():
            km_payload = load_json(knowledge_map_path)
            shutil.copy2(knowledge_map_path, staging / "knowledge-map.json")
            knowledge_map_decl = {"path": "knowledge-map.json", "sha256": sha256_file(staging / "knowledge-map.json")}
            if isinstance(km_payload, dict):
                entries = km_payload.get("entries")
                if isinstance(entries, list):
                    knowledge_map_decl["entry_count"] = len(entries)
                knowledge_positions = km_payload.get("knowledge_positions")
                if isinstance(knowledge_positions, list):
                    knowledge_map_decl["knowledge_position_count"] = len(knowledge_positions)

        asset_names: list[str] = []
        asset_integrity_files: list[dict] = []
        if images_source.is_dir():
            images_target = staging / "images"
            images_target.mkdir(parents=True, exist_ok=True)
            for image_path in sorted(images_source.iterdir()):
                if image_path.is_file():
                    shutil.copy2(image_path, images_target / image_path.name)
                    asset_names.append(image_path.name)
                    asset_integrity_files.append(
                        {
                            "path": f"images/{image_path.name}",
                            "sha256": sha256_file(images_target / image_path.name),
                        }
                    )

        nodes = outline["nodes"]
        node_map = {node["id"]: node for node in nodes}
        chapters = sorted(
            [node for node in nodes if node.get("kind") == "chapter" and node.get("parent_id") is None],
            key=lambda node: node["order"],
        )
        chapter_order = {chapter["id"]: index for index, chapter in enumerate(chapters, start=1)}
        reading_sections: list[dict] = []
        references: list[dict] = []
        chapter_page_texts: dict[str, list[str]] = defaultdict(list)
        chapter_page_ids: dict[str, list[str]] = defaultdict(list)

        pages = sorted(outline["pages"], key=lambda page: page["order"])
        for page in pages:
            text = page_source_text(clean_lines, page)
            public_id = stable_id(book_id, "page", page["id"])
            role = page["role"]
            folder = staging / ("cleaned/pages" if role == "reading" else "reference/pages")
            folder.mkdir(parents=True, exist_ok=True)
            relative = Path("cleaned/pages" if role == "reading" else "reference/pages") / f"{page['order']:03d}-{page['id']}.md"
            output_path = staging / relative
            output_path.write_bytes(text.encode("utf-8"))
            chapter = ancestor_chapter(page["node_id"], node_map)
            breadcrumb_nodes = node_breadcrumb(page["node_id"], node_map)
            breadcrumb = [node["title"] for node in breadcrumb_nodes]
            node = node_map[page["node_id"]]
            canonical_title = page["title"]
            if page.get("display_title"):
                runtime_title = page["display_title"]
            elif node.get("kind") == "topic":
                runtime_title = " · ".join(item["title"] for item in breadcrumb_nodes if item.get("kind") != "chapter")
            else:
                runtime_title = canonical_title
            item = {
                "id": public_id,
                "key": page["id"],
                "order": page["order"],
                "title": runtime_title,
                "canonical_title": canonical_title,
                "breadcrumb": breadcrumb,
                "role": role,
                "node_id": page["node_id"],
                "artifact": relative.as_posix(),
                "character_count": len(text.strip()),
                "line_count": page["end_line"] - page["start_line"] + 1,
                "sha256": sha256_bytes(text.encode("utf-8")),
                "source_map": {
                    "original_artifact": "original/source.md",
                    "original_line_start": page["start_line"],
                    "original_line_end": page["end_line"],
                },
            }
            if isinstance(page.get("start_char"), int) and isinstance(page.get("end_char"), int):
                item["source_map"].update(
                    {
                        "original_char_start": page["start_char"],
                        "original_char_end": page["end_char"],
                    }
                )
                if page.get("char_prefix") or page.get("char_suffix"):
                    item["source_map"]["derived_prefix"] = page.get("char_prefix", "")
                    item["source_map"]["derived_suffix"] = page.get("char_suffix", "")
            if chapter:
                item.update(
                    {
                        "chapter_id": stable_id(book_id, "chapter", chapter["id"]),
                        "chapter_key": chapter["id"],
                        "chapter_order": chapter_order[chapter["id"]],
                        "chapter_title": chapter["title"],
                    }
                )
            if role == "reading" and chapter:
                item["source_order"] = item["order"]
                item["order"] = len(reading_sections) + 1
                item["section_order"] = len(chapter_page_ids[chapter["id"]]) + 1
                item["level"] = 2
                item["material_kind"] = "cleaned"
                reading_sections.append(item)
                chapter_page_ids[chapter["id"]].append(public_id)
                chapter_page_texts[chapter["id"]].append(text)
            else:
                references.append(item)

        toc: list[dict] = []
        source_chapters: list[dict] = []
        chapter_dir = staging / "cleaned" / "chapters"
        chapter_dir.mkdir(parents=True, exist_ok=True)
        for chapter in chapters:
            if not chapter_page_ids[chapter["id"]]:
                continue
            order = chapter_order[chapter["id"]]
            chapter_text = "".join(chapter_page_texts[chapter["id"]])
            relative = Path("cleaned/chapters") / f"{order:03d}.md"
            (staging / relative).write_bytes(chapter_text.encode("utf-8"))
            chapter_public_id = stable_id(book_id, "chapter", chapter["id"])
            toc.append({"id": chapter_public_id, "key": chapter["id"], "order": order, "title": chapter["title"], "section_ids": chapter_page_ids[chapter["id"]]})
            chapter_pages = [page for page in pages if page["role"] == "reading" and (ancestor_chapter(page["node_id"], node_map) or {}).get("id") == chapter["id"]]
            source_chapters.append(
                {
                    "id": chapter_public_id,
                    "key": chapter["id"],
                    "order": order,
                    "title": chapter["title"],
                    "level": 1,
                    "artifact": relative.as_posix(),
                    "character_count": len(chapter_text.strip()),
                    "line_count": sum(page["end_line"] - page["start_line"] + 1 for page in chapter_pages),
                    "sha256": sha256_bytes(chapter_text.encode("utf-8")),
                    "material_kind": "cleaned",
                    "source_map": {
                        "original_artifact": "original/source.md",
                        "original_line_start": min(page["start_line"] for page in chapter_pages),
                        "original_line_end": max(page["end_line"] for page in chapter_pages),
                    },
                }
            )

        quality = dict(report)
        quality["status"] = "warning" if report["warnings"] else "pass"
        write_json(staging / "reports" / "quality.json", quality)
        write_json(
            staging / "reports" / "transformations.json",
            {
                "schema_version": 1,
                "source_sha256": sha256_file(source),
                "transformation_count": len(transformations),
                "items": transformations,
            },
        )
        write_json(
            staging / "reports" / "layout.json",
            {
                "schema_version": 1,
                "status": quality["status"],
                "outline_sha256": outline_hash,
                "metrics": report["metrics"],
                "warnings": report["warnings"],
            },
        )
        source_hash = sha256_file(source)
        derived_items = [*reading_sections, *references]
        cleaned_hash = derived_text_hash(derived_items)
        manifest_book = {
            "id": book_id,
            "title": book["title"],
            "edition": book.get("edition", ""),
            "status": "ready",
            "default_material": "cleaned",
        }
        for metadata_key in ("domain", "subject", "resource_type"):
            metadata_value = project_book_meta.get(metadata_key)
            if metadata_value is not None:
                manifest_book[metadata_key] = metadata_value
        manifest = {
            "schema_version": 2,
            "book": manifest_book,
            "created_at": utc_now(),
            "builder": {"name": "YuBook", "version": TOOL_VERSION, "outline_sha256": outline_hash},
            "provenance": {
                "original": {
                    "external_path": load_json(project / "book.json").get("external_source"),
                    "artifact": "original/source.md",
                    "sha256": source_hash,
                    "bytes": source.stat().st_size,
                },
                "cleaned_candidate": {
                    "mode": "line_preserving_derived_text",
                    "source_artifact": "original/source.md",
                    "source_sha256": source_hash,
                    "sha256": cleaned_hash,
                    "hash_algorithm": DERIVED_TEXT_HASH_ALGORITHM,
                    "artifact_count": len(derived_items),
                    "transformation_count": len(transformations),
                    "transformation_report": "reports/transformations.json",
                    "navigation_normalization_count": sum(bool(node.get("title_normalization")) for node in nodes),
                },
            },
            "artifacts": {"original": "original/source.md", "cleaned_chapters": "cleaned/chapters", "slices": "cleaned/pages", "quality_report": "reports/quality.json", "transformations": "reports/transformations.json", "outline": "reports/outline.json"},
            "quality": {"status": quality["status"], "blocker_count": 0, "warning_count": len(report["warnings"]), "report": "reports/quality.json"},
            "reading_layout": {
                "mode": "authoritative_outline",
                "chapter_count": len(toc),
                "section_count": len(reading_sections),
                "reference_page_count": len(references),
                "oversized_page_count": sum(item["character_count"] > LONG_READING_WARNING for item in reading_sections),
                "report": "reports/layout.json",
                "content_start": "first_chapter",
                "first_chapter_title": toc[0]["title"] if toc else None,
            },
            "outline_nodes": nodes,
            "toc": toc,
            "source_chapters": source_chapters,
            "sections": reading_sections,
            "references": references,
            "assets": asset_names,
        }
        if asset_names:
            manifest["assets_root"] = "images"
            manifest["asset_integrity"] = {
                "algorithm": "sha256-file-list-v1",
                "count": len(asset_integrity_files),
                "files": asset_integrity_files,
            }
        if knowledge_map_decl is not None:
            manifest["knowledge_map"] = knowledge_map_decl
        write_json(staging / "manifest.json", manifest)
        staging.rename(package)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return {
        "status": "built",
        "package": str(package),
        "outline_sha256": outline_hash,
        "chapters": len(toc),
        "reading_pages": len(reading_sections),
        "reference_pages": len(references),
        "warnings": len(report["warnings"]),
    }


def validate_package(package: Path) -> dict:
    manifest = load_json(package / "manifest.json")
    blockers: list[dict] = []
    if manifest.get("schema_version") != 2 or manifest.get("book", {}).get("status") != "ready":
        add_problem(blockers, "manifest", "manifest 不是可发布的 YuReader schema 2 包")
    blockers.extend(book_metadata_errors(manifest.get("book") or {}))
    quality_meta = manifest.get("quality") if isinstance(manifest.get("quality"), dict) else {}
    quality_path = package / quality_meta.get("report", "")
    if not quality_path.is_file():
        add_problem(blockers, "quality_report_missing", "候选包缺少质量报告", artifact=quality_meta.get("report"))
    else:
        quality = load_json(quality_path)
        if quality.get("blockers") or quality_meta.get("blocker_count"):
            add_problem(blockers, "quality_blocked", "质量报告仍包含 blocker，不能导入")
    for artifact_key in ("transformations", "outline"):
        relative = manifest.get("artifacts", {}).get(artifact_key)
        if not relative or not (package / relative).is_file():
            add_problem(blockers, "package_artifact_missing", "候选包缺少可追溯报告", artifact_key=artifact_key, artifact=relative)
    repair_meta = manifest.get("repair") if isinstance(manifest.get("repair"), dict) else None
    if repair_meta is not None:
        receipt = repair_meta.get("receipt")
        if not isinstance(receipt, str) or not receipt or not (package / receipt).is_file():
            add_problem(blockers, "repair_receipt_missing", "派生修复包缺少 repair receipt", receipt=receipt)
    derived_items = [*manifest.get("sections", []), *manifest.get("references", [])]
    for section in derived_items:
        artifact = package / section.get("artifact", "")
        if not artifact.is_file():
            add_problem(blockers, "section_missing", "页面文件不存在", section_id=section.get("id"), artifact=section.get("artifact"))
        elif sha256_file(artifact) != section.get("sha256"):
            add_problem(blockers, "section_hash", "页面哈希不一致", section_id=section.get("id"))
    assets = manifest.get("assets")
    if isinstance(assets, list) and assets:
        integrity = manifest.get("asset_integrity") if isinstance(manifest.get("asset_integrity"), dict) else {}
        integrity_files = integrity.get("files") if isinstance(integrity.get("files"), list) else []
        if integrity.get("algorithm") != "sha256-file-list-v1" or integrity.get("count") != len(assets):
            add_problem(blockers, "asset_integrity", "图片资产缺少完整的 SHA-256 契约")
        declared_assets: set[str] = set()
        for index, item in enumerate(integrity_files):
            if not isinstance(item, dict):
                add_problem(blockers, "asset_integrity", "图片资产声明必须是对象", index=index)
                continue
            relative = item.get("path")
            expected_hash = item.get("sha256")
            if not isinstance(relative, str) or not relative.startswith("images/") or Path(relative).is_absolute() or ".." in Path(relative).parts:
                add_problem(blockers, "asset_integrity", "图片资产路径非法", index=index, path=relative)
                continue
            asset_file = package / relative
            declared_assets.add(Path(relative).name)
            if not asset_file.is_file():
                add_problem(blockers, "asset_missing", "图片资产不存在", path=relative)
            elif not isinstance(expected_hash, str) or sha256_file(asset_file) != expected_hash:
                add_problem(blockers, "asset_hash", "图片资产 SHA-256 不一致", path=relative)
        if declared_assets != set(assets):
            add_problem(
                blockers,
                "asset_integrity",
                "manifest.assets 与 asset_integrity.files 不一致",
                assets=sorted(str(item) for item in assets),
                declared=sorted(declared_assets),
            )
    provenance = manifest.get("provenance") if isinstance(manifest.get("provenance"), dict) else {}
    original = provenance.get("original") if isinstance(provenance.get("original"), dict) else {}
    cleaned = provenance.get("cleaned_candidate") if isinstance(provenance.get("cleaned_candidate"), dict) else {}
    if cleaned.get("mode") == "line_preserving_derived_text":
        if cleaned.get("source_sha256") != original.get("sha256"):
            add_problem(blockers, "derived_source_hash", "派生正文记录的源哈希与原始归档不一致")
        if cleaned.get("hash_algorithm") != DERIVED_TEXT_HASH_ALGORITHM:
            add_problem(blockers, "derived_hash_contract", "派生正文缺少受支持的独立哈希契约")
        elif cleaned.get("sha256") != derived_text_hash(derived_items):
            add_problem(blockers, "derived_hash", "派生正文聚合哈希不一致")
        if cleaned.get("artifact_count") != len(derived_items):
            add_problem(
                blockers,
                "derived_artifact_count",
                "派生正文记录的页面数量不一致",
                actual=len(derived_items),
                expected=cleaned.get("artifact_count"),
            )

    knowledge_map_decl = manifest.get("knowledge_map") if isinstance(manifest.get("knowledge_map"), dict) else {}
    if knowledge_map_decl:
        km_path_value = knowledge_map_decl.get("path")
        km_file = package / str(km_path_value or "")
        if not isinstance(km_path_value, str) or not km_path_value or not km_file.is_file() or km_file.parent != package:
            add_problem(blockers, "knowledge_map_missing", "候选包缺少知识映射文件", path=km_path_value)
        else:
            if sha256_file(km_file) != knowledge_map_decl.get("sha256"):
                add_problem(blockers, "knowledge_map_hash", "知识映射 SHA-256 与 manifest 声明不一致", path=km_path_value)
            try:
                km_payload = load_json(km_file)
            except YuBookError as exc:
                add_problem(blockers, "knowledge_map_shape", "包内 knowledge-map.json 无法解析", path=km_path_value, error=str(exc))
                km_payload = None
            if not isinstance(km_payload, dict):
                add_problem(blockers, "knowledge_map_shape", "包内 knowledge-map.json 顶层必须为对象")
            else:
                if km_payload.get("schema_version") != 1:
                    add_problem(blockers, "knowledge_map_schema", "包内 knowledge-map.schema_version 必须为 1")
                manifest_book_id = (manifest.get("book") or {}).get("id") if isinstance(manifest.get("book"), dict) else None
                if km_payload.get("book_id") != manifest_book_id:
                    add_problem(
                        blockers,
                        "knowledge_map_book_id",
                        "包内 knowledge-map.book_id 与 manifest.book.id 不一致",
                    )
                if km_payload.get("input_sha256") is not None and km_payload.get("input_sha256") != original.get("sha256"):
                    add_problem(blockers, "knowledge_map_source_hash", "包内 knowledge-map.input_sha256 与原始归档哈希不一致")
                entries = km_payload.get("entries")
                if isinstance(entries, list):
                    declared_entry_count = knowledge_map_decl.get("entry_count")
                    if isinstance(declared_entry_count, int) and declared_entry_count != len(entries):
                        add_problem(
                            blockers,
                            "knowledge_map_entry_count",
                            "manifest 声明的 entry_count 与包内实际不一致",
                            declared=declared_entry_count,
                            actual=len(entries),
                        )
                    seen_km: set[str] = set()
                    for index, entry in enumerate(entries):
                        if not isinstance(entry, dict):
                            add_problem(blockers, "knowledge_map_entry_shape", "知识映射 entry 必须是对象", index=index)
                            continue
                        knowledge_id = entry.get("knowledge_id")
                        if not isinstance(knowledge_id, str) or not knowledge_id.strip():
                            add_problem(blockers, "knowledge_map_entry_shape", "knowledge entry 缺少非空 knowledge_id", index=index)
                            continue
                        if knowledge_id in seen_km:
                            add_problem(blockers, "knowledge_map_duplicate", "知识映射存在重复 knowledge_id", knowledge_id=knowledge_id)
                        seen_km.add(knowledge_id)
                        page_ids = entry.get("page_ids")
                        if page_ids is not None:
                            if not isinstance(page_ids, list) or any(not isinstance(page_id, str) for page_id in page_ids):
                                add_problem(blockers, "knowledge_map_page_ids", "knowledge entry.page_ids 必须是字符串数组", knowledge_id=knowledge_id)
                            else:
                                available_page_ids = {
                                    value
                                    for section in manifest.get("sections", [])
                                    if isinstance(section, dict)
                                    for value in (section.get("key"), section.get("node_id"))
                                    if isinstance(value, str)
                                }
                                missing_page_ids = sorted(set(page_ids) - available_page_ids)
                                if missing_page_ids:
                                    add_problem(
                                        blockers,
                                        "knowledge_map_page_ids",
                                        "knowledge entry 引用了包内不存在的阅读页",
                                        knowledge_id=knowledge_id,
                                        page_ids=missing_page_ids,
                                    )
                knowledge_positions = km_payload.get("knowledge_positions")
                if isinstance(knowledge_positions, list):
                    declared_position_count = knowledge_map_decl.get("knowledge_position_count")
                    if isinstance(declared_position_count, int) and declared_position_count != len(knowledge_positions):
                        add_problem(
                            blockers,
                            "knowledge_map_position_count",
                            "manifest 声明的 knowledge_position_count 与包内实际不一致",
                            declared=declared_position_count,
                            actual=len(knowledge_positions),
                        )
    return {"status": "blocked" if blockers else "pass", "blockers": blockers, "manifest": manifest}


def command_import(args: argparse.Namespace) -> dict:
    package = Path(args.package).expanduser().resolve()
    if not package.is_dir():
        raise YuBookError(f"数据包不存在：{package}")
    audit = validate_package(package)
    if audit["blockers"]:
        raise YuBookError(f"数据包存在 {len(audit['blockers'])} 个 blocker")
    manifest = audit["manifest"]
    book_id = manifest["book"]["id"]
    content_root = Path(args.content_root).expanduser().resolve() if args.content_root else DEFAULT_CONTENT_ROOT.resolve()
    content_root.mkdir(parents=True, exist_ok=True)
    target = (content_root / book_id).resolve()
    try:
        target.relative_to(content_root)
    except ValueError as exc:
        raise YuBookError("导入目标越出 YuReader content 根目录") from exc
    staging = content_root / f".yubook-import-{book_id}-{uuid.uuid4().hex}"
    backup = content_root / f".yubook-backup-{book_id}-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        shutil.copy2(package / "manifest.json", staging / "manifest.json")
        for name in ("cleaned", "reference", "reports", "images"):
            source_dir = package / name
            if source_dir.is_dir():
                shutil.copytree(source_dir, staging / name)
        if (package / "knowledge-map.json").is_file():
            shutil.copy2(package / "knowledge-map.json", staging / "knowledge-map.json")
        staged_audit = validate_package(staging)
        if staged_audit["blockers"]:
            raise YuBookError("暂存包复核失败")
        if target.exists():
            target.rename(backup)
        try:
            staging.rename(target)
        except Exception:
            if backup.exists() and not target.exists():
                backup.rename(target)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return {"status": "imported", "book_id": book_id, "target": str(target), "package": str(package)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yubook", description="轻量、Agent 驱动的 YuReader 制书工具")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="只读归档 Markdown 并创建最小工程")
    init.add_argument("--source", required=True)
    init.add_argument("--book-id", required=True)
    init.add_argument("--title", required=True)
    init.add_argument("--edition", default="")
    init.add_argument("--workspace")
    init.set_defaults(handler=command_init)

    inspect = sub.add_parser("inspect", help="只读列出标题候选")
    source_group = inspect.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--source")
    source_group.add_argument("--project")
    inspect.set_defaults(handler=command_inspect)

    validate = sub.add_parser("validate", help="检查权威目录树、编号和正文覆盖")
    validate.add_argument("--project", required=True)
    validate.set_defaults(handler=command_validate)

    build = sub.add_parser("build", help="生成不可变、来源可追溯的候选包")
    build.add_argument("--project", required=True)
    build.set_defaults(handler=command_build)

    import_command = sub.add_parser("import", help="复核并原子导入 YuReader content")
    import_command.add_argument("--package", required=True)
    import_command.add_argument("--content-root")
    import_command.set_defaults(handler=command_import)
    return parser


def main() -> int:
    # Windows may expose a legacy console encoding while Codex and downstream
    # consumers decode CLI JSON as UTF-8. Keep machine-readable Chinese output
    # stable without changing library behavior for imported callers.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = args.handler(args)
    except YuBookError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
