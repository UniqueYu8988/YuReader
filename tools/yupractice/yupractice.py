#!/usr/bin/env python3
"""YuPractice: validate a structured question-bank package for YuReader.

This tool only validates Agent-produced structured packages. It never
parses raw textbooks/OCR with regexes, never calls a model, never imports
anything into the formal bookshelf, and never writes user data.

Command:
    python tools\\yupractice\\yupractice.py validate <package-dir> [--json]

Exit codes:
    0  - no blockers (warnings may exist)
    1  - usage / runtime error (package unreadable etc.)
    2  - one or more blockers found

Outputs:
    - human-readable summary on stdout (UTF-8)
    - reports/validation.json and reports/quality-report.json written into
      the package (both are derived reports, not part of the hashed content)
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path

SCHEMA_VERSION = 1
SUPPORTED_MAP_VERSION = 1
SUPPORTED_INDEX_VERSION = 1
GENERATOR_NAME = "yupractice"
GENERATOR_VERSION = "0.2.0"

QUESTION_TYPES = {"single_choice", "multiple_choice"}
DIFFICULTIES = {"basic", "advanced"}
SCOPES = {"chapter", "comprehensive"}
SOURCE_ROLES = {"primary", "auxiliary", "reference"}
BANK_STATUS_VALUES = {"ready", "draft", "archived"}
QUALITY_STATUS_VALUES = {"pass", "warning", "blocked"}
TRANSFORMATION_TYPES = {
    "ocr_fix",
    "separator_fix",
    "term_normalization",
    "answer_confirmation",
    "quote_fix",
    "structure_fix",
    "deduplication",
    "other",
}
KNOWLEDGE_KINDS = {"section", "chapter", "comprehensive", "topic"}

QUESTION_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_SK = r"[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?"
KNOWLEDGE_ID_RE = re.compile(rf"^{_SK}(?:\.{_SK})+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
OPTION_LABEL_RE = re.compile(r"^[A-Z]$")
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
PROMOTIONAL_TEXT_RE = re.compile(
    r"(?:扫描右侧二维码|扫码兑换|关注公众号|QQ群|资料同步\s*VX|免费分享\s*PDF|认准淘宝店铺|赠送配套课程|涛涛提示)"
)
CLOZE_MARKER_RE = re.compile(r"(?<!\d)(\d{1,2})(?!\d)")
ANALYSIS_GUARD_PREFIX = "【原书解析未可靠转录】"


class Findings:
    """Collect blockers and warnings with stable codes."""

    def __init__(self) -> None:
        self.blockers: list[dict] = []
        self.warnings: list[dict] = []

    def block(self, code: str, message: str, where: str = "") -> None:
        entry = {"code": code, "message": message}
        if where:
            entry["where"] = where
        self.blockers.append(entry)

    def warn(self, code: str, message: str, where: str = "") -> None:
        entry = {"code": code, "message": message}
        if where:
            entry["where"] = where
        self.warnings.append(entry)

    @property
    def blocker_count(self) -> int:
        return len(self.blockers)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    @property
    def status(self) -> str:
        if self.blockers:
            return "blocked"
        if self.warnings:
            return "warning"
        return "pass"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_json(path: Path, findings: Findings, code: str, label: str):
    """Load a JSON file, reporting missing/invalid as a blocker."""
    if not path.is_file():
        findings.block(code, f"{label} 缺失: {path.name}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as error:
        findings.block(code, f"{label}无法解析: {error}")
        return None


def configure_windows_utf8() -> None:
    """Reconfigure Windows interactive console stdout/stderr to UTF-8.

    Safely and idempotently makes human-readable Chinese output readable in
    PowerShell / Windows Terminal, without touching redirected output, pipes
    or non-Windows environments. Machine-readable ``--json`` output is emitted
    as raw UTF-8 bytes regardless, so it stays valid JSON everywhere.
    """
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            if not stream.isatty():
                continue
            current = (getattr(stream, "encoding", "") or "").lower()
            if current in ("utf-8", "utf_8"):
                continue
            reconfigure(encoding="utf-8")
        except Exception:
            # Console reconfiguration must never crash the validator.
            continue


def _emit_utf8_json(payload: dict) -> None:
    """Emit machine-readable JSON as valid UTF-8 bytes on every platform.

    ``--json`` is consumed by downstream tools and must be re-loadable with
    ``json.loads`` regardless of locale/console code page, so it is written
    straight to the binary layer as UTF-8. Falls back to the text layer for
    unusual streams without a binary buffer.
    """
    out = sys.stdout
    if out is None:
        return
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    buffer = getattr(out, "buffer", None)
    if buffer is not None:
        buffer.write(text.encode("utf-8"))
        buffer.flush()
    else:
        try:
            out.write(text)
            out.flush()
        except Exception:
            return


def _build_source_lookup(source_index):
    """Build ``{source_id: {block_id: block}}`` without assuming any field
    exists. Structural defects are reported separately by
    ``_validate_source_index``; this function never raises on them."""
    lookup: dict[str, dict[str, dict]] = {}
    if not isinstance(source_index, dict):
        return lookup
    for source in source_index.get("sources", []):
        if not isinstance(source, dict):
            continue
        source_id = source.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            continue  # missing source_id -> E045, reported in _validate_source_index
        blocks = source.get("blocks")
        if not isinstance(blocks, list):
            continue  # blocks not a list -> E048
        source_blocks: dict[str, dict] = {}
        for block in blocks:
            if not isinstance(block, dict):
                continue
            block_id = block.get("block_id")
            if not isinstance(block_id, str) or not block_id:
                continue  # missing block_id -> E049
            source_blocks[block_id] = block
        lookup[source_id] = source_blocks
    return lookup


def _validate_source_index(payload, manifest, findings: Findings) -> dict:
    """Full structural validation of source-index.json.

    Checks index_version, bank_id, sources array shape, per-source fields,
    block_id uniqueness, line-range sanity and page label types. Returns the
    (possibly partial) lookup so callers keep collecting findings."""
    lookup = _build_source_lookup(payload)
    if not isinstance(payload, dict):
        return lookup

    index_version = payload.get("index_version")
    if index_version != SUPPORTED_INDEX_VERSION:
        findings.block(
            "E038",
            f"source-index.index_version 必须为 {SUPPORTED_INDEX_VERSION}，实际 {index_version!r}",
        )

    bank_id = payload.get("bank_id")
    if not isinstance(bank_id, str) or not bank_id.strip():
        findings.block("E040", "source-index.json 缺少 bank_id")
    elif isinstance(manifest, dict) and isinstance(manifest.get("bank"), dict):
        manifest_bank_id = manifest["bank"].get("id")
        if bank_id != manifest_bank_id:
            findings.block(
                "E040",
                f"source-index.json.bank_id={bank_id!r} 与 manifest.bank.id={manifest_bank_id!r} 不一致",
            )

    sources = payload.get("sources")
    if not isinstance(sources, list):
        findings.block("E044", "source-index.json.sources 必须是数组")
        return lookup

    seen_source_ids: set[str] = set()
    for source_index, source in enumerate(sources):
        where = f"source-index.json:sources[{source_index}]"
        if not isinstance(source, dict):
            findings.block("E045", f"{where} 不是对象", where)
            continue
        source_id = source.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            findings.block(
                "E045", f"{where} 缺少 source_id 或 source_id 为空", where
            )
        else:
            if source_id in seen_source_ids:
                findings.block(
                    "E046", f"{where} 重复的 source_id: {source_id}", where
                )
            seen_source_ids.add(source_id)
        for field in ("filename", "display_name", "sha256", "role"):
            value = source.get(field)
            if not isinstance(value, str) or not value.strip():
                findings.block(
                    "E047", f"{where} 缺少 {field} 或为空", where
                )
        sha_value = source.get("sha256")
        if isinstance(sha_value, str) and not SHA256_RE.match(sha_value):
            findings.block("E047", f"{where} sha256 格式非法", where)
        role = source.get("role")
        if isinstance(role, str) and role not in SOURCE_ROLES:
            findings.block("E047", f"{where} role 未登记: {role!r}", where)

        blocks = source.get("blocks")
        if not isinstance(blocks, list):
            findings.block("E048", f"{where} blocks 必须是数组", where)
            continue
        seen_block_ids: set[str] = set()
        for block_index, block in enumerate(blocks):
            block_where = f"{where}.blocks[{block_index}]"
            if not isinstance(block, dict):
                findings.block("E049", f"{block_where} 不是对象", block_where)
                continue
            block_id = block.get("block_id")
            if not isinstance(block_id, str) or not block_id:
                findings.block(
                    "E049", f"{block_where} 缺少 block_id 或 block_id 为空", block_where
                )
            else:
                if block_id in seen_block_ids:
                    findings.block(
                        "E050",
                        f"{block_where} 同一 source 内重复 block_id: {block_id}",
                        block_where,
                    )
                seen_block_ids.add(block_id)
            for field in ("start_line", "end_line"):
                value = block.get(field)
                if (
                    not isinstance(value, int)
                    or isinstance(value, bool)
                    or value < 1
                ):
                    findings.block(
                        "E051",
                        f"{block_where} {field} 必须是正整数，实际 {value!r}",
                        block_where,
                    )
            start_line = block.get("start_line")
            end_line = block.get("end_line")
            if (
                isinstance(start_line, int)
                and not isinstance(start_line, bool)
                and isinstance(end_line, int)
                and not isinstance(end_line, bool)
                and start_line > end_line
            ):
                findings.block(
                    "E052",
                    f"{block_where} start_line 大于 end_line ({start_line} > {end_line})",
                    block_where,
                )
            for field in ("page", "page_label"):
                value = block.get(field)
                if value is not None and not isinstance(value, str):
                    findings.block(
                        "E053",
                        f"{block_where} {field} 类型非法（应为字符串或缺失），实际 {value!r}",
                        block_where,
                    )
    return lookup


def validate_question_record(
    record: object,
    findings: Findings,
    *,
    knowledge_map_ids: set[str],
    source_lookup: dict[str, dict[str, dict]],
    where: str,
    expected_status: str,
    quarantine_mode: bool = False,
    expected_bank_id: str = "",
    bank_mismatch_code: str = "E042",
) -> None:
    """Validate one JSONL question record (formal or quarantine)."""
    if not isinstance(record, dict):
        findings.block("E037", "题目记录不是 JSON 对象", where)
        return

    bank_id = record.get("bank_id")
    if bank_id is not None:
        where_label = "隔离题目" if quarantine_mode else "正式题目"
        if not isinstance(bank_id, str) or not bank_id.strip():
            findings.block(
                bank_mismatch_code, f"{where_label} bank_id 缺失或为空", where
            )
        elif bank_id != expected_bank_id:
            findings.block(
                bank_mismatch_code,
                f"bank_id={bank_id!r} 与 manifest.bank.id={expected_bank_id!r} 不一致",
                where,
            )

    question_id = record.get("question_id")
    if not isinstance(question_id, str) or not QUESTION_ID_RE.match(question_id):
        findings.block("E013", "question_id 缺失或不符合稳定格式（小写 kebab-case）", where)
    elif len(question_id) < 3:
        findings.block("E013", f"question_id 过短: {question_id!r}", where)

    question_type = record.get("question_type")
    if not isinstance(question_type, str) or question_type not in QUESTION_TYPES:
        findings.block("E015", f"question_type 非法: {question_type!r}", where)

    stem_md = record.get("stem_md")
    if not isinstance(stem_md, str) or not stem_md.strip():
        if quarantine_mode:
            findings.warn("W007", "隔离题目缺少 stem_md（保留原文建议仍应给出题干）", where)
        else:
            findings.block("E016", "stem_md 缺失或为空", where)

    options = record.get("options")
    if not isinstance(options, list) or len(options) < 2:
        findings.block("E017", "options 必须是包含至少两个选项的有序数组", where)
        labels: list[str] = []
    else:
        labels = []
        for index, option in enumerate(options):
            if not isinstance(option, dict):
                findings.block("E017", f"选项 {index + 1} 不是对象", where)
                continue
            label = option.get("label")
            text = option.get("text_md")
            labels.append(str(label))
            if not isinstance(label, str) or not OPTION_LABEL_RE.match(label):
                findings.block("E017", f"选项 {index + 1} 的 label 非法: {label!r}", where)
            if not isinstance(text, str) or not text.strip():
                if quarantine_mode:
                    findings.warn("W004", f"选项 {label} 的 text_md 为空", where)
                else:
                    findings.block("E017", f"选项 {label} 的 text_md 为空", where)
        expected = [chr(ord("A") + index) for index in range(len(options))]
        if labels and labels != expected:
            findings.block(
                "E017",
                f"options 标签必须是从 A 开始连续的升序字母，实际为 {labels}",
                where,
            )
        if len(set(labels)) != len(labels):
            findings.block("E017", "options 标签必须唯一", where)

    correct_answers = record.get("correct_answers")
    if not isinstance(correct_answers, list) or not correct_answers:
        if quarantine_mode:
            findings.warn("W003", "隔离题目缺少 correct_answers", where)
        else:
            findings.block("E018", "correct_answers 缺失或为空", where)
    else:
        labels_set = set(labels)
        valid_answers: list[str] = []
        for answer in correct_answers:
            if not isinstance(answer, str):
                findings.block("E018", f"correct_answers 只能包含字符串标签: {answer!r}", where)
                continue
            valid_answers.append(answer)
            if answer not in labels_set:
                findings.block(
                    "E019", f"correct_answers 含非选项标签: {answer!r}", where
                )
        if len(set(valid_answers)) != len(valid_answers):
            findings.warn("W009", "correct_answers 含重复标签", where)
        if question_type == "single_choice" and len(correct_answers) != 1:
            findings.block(
                "E020",
                f"单选题必须只有一个正确答案，实际 {len(correct_answers)} 个",
                where,
            )
        if question_type == "multiple_choice" and len(correct_answers) == 1:
            findings.warn("W003", "多选题只有一个正确答案，可能标注错误", where)

    knowledge_ids = record.get("knowledge_ids")
    if isinstance(knowledge_ids, list):
        if not knowledge_ids:
            findings.warn("W002", "题目未关联任何知识位置", where)
        for knowledge_id in knowledge_ids:
            if not isinstance(knowledge_id, str) or not KNOWLEDGE_ID_RE.match(knowledge_id):
                findings.block(
                    "E021",
                    f"knowledge_ids 语法非法: {knowledge_id!r}",
                    where,
                )
                continue
            if knowledge_id not in knowledge_map_ids:
                findings.block(
                    "E022",
                    f"knowledge_id 不存在于 knowledge-map: {knowledge_id}",
                    where,
                )
    else:
        findings.block("E021", "knowledge_ids 必须是数组", where)

    source_refs = record.get("source_refs")
    if not isinstance(source_refs, list):
        findings.block("E024", "source_refs 必须是数组", where)
        source_refs = []
    if not source_refs:
        if quarantine_mode:
            findings.warn("W007", "隔离题目缺少 source_refs（建议保留来源）", where)
        else:
            findings.block("E023", "source_refs 为空（必须可追溯）", where)
    for source_ref in source_refs:
        if not isinstance(source_ref, dict):
            findings.block("E024", "source_ref 不是对象", where)
            continue
        source_id = source_ref.get("source_id")
        block_id = source_ref.get("block_id")
        if not isinstance(source_id, str) or not source_id:
            findings.block("E024", "source_ref 缺少 source_id", where)
            continue
        if not isinstance(block_id, str) or not block_id:
            findings.block("E024", "source_ref 缺少 block_id", where)
            continue
        source_blocks = source_lookup.get(source_id)
        if source_blocks is None:
            findings.block(
                "E024", f"source_id 无法在 source-index 解析: {source_id}", where
            )
            continue
        if block_id not in source_blocks:
            findings.block(
                "E024", f"block_id 无法在 source-index 解析: {source_id}/{block_id}", where
            )

    source_analysis_md = record.get("source_analysis_md")
    if not isinstance(source_analysis_md, str) or not source_analysis_md.strip():
        if quarantine_mode:
            findings.warn("W007", "隔离题目缺少 source_analysis_md", where)
        else:
            findings.block("E025", "source_analysis_md 缺失或为空（原书解析不可缺）", where)

    context_md = record.get("context_md")
    if context_md is not None and not isinstance(context_md, str):
        findings.block("E058", "context_md 如提供必须为字符串", where)
    content_fields: list[tuple[str, object]] = [
        ("context_md", context_md),
        ("stem_md", stem_md),
        ("source_analysis_md", source_analysis_md),
    ]
    if isinstance(options, list):
        for index, option in enumerate(options):
            if isinstance(option, dict):
                content_fields.append((f"options[{index}].text_md", option.get("text_md")))
    distractor_value = record.get("distractor_analysis_md")
    if isinstance(distractor_value, dict):
        for label, value in distractor_value.items():
            content_fields.append((f"distractor_analysis_md.{label}", value))
    for field_name, value in content_fields:
        if not isinstance(value, str):
            continue
        if PROMOTIONAL_TEXT_RE.search(value):
            if quarantine_mode:
                findings.warn("W019", f"{field_name} 含推广/二维码残留", where)
            else:
                findings.block("E056", f"{field_name} 含推广/二维码残留", where)
        if MARKDOWN_IMAGE_RE.search(value):
            if quarantine_mode:
                findings.warn("W020", f"{field_name} 含尚无题库资产契约的图片引用", where)
            else:
                findings.block("E057", f"{field_name} 含尚无题库资产契约的图片引用", where)

    distractor = record.get("distractor_analysis_md")
    if distractor is not None and not isinstance(distractor, dict):
        findings.warn(
            "W005",
            "distractor_analysis_md 应为按选项标签映射的原书干扰项解析对象",
            where,
        )

    status = record.get("status")
    if status != expected_status:
        if quarantine_mode:
            findings.block(
                "E030",
                f"隔离题目 status 必须为 quarantined，实际 {status!r}",
                where,
            )
        else:
            findings.block("E026", f"正式题目 status 必须为 ready，实际 {status!r}", where)

    transformations = record.get("transformations")
    if not isinstance(transformations, list):
        findings.block("E027", "transformations 必须是数组", where)
        transformations = []
    for index, transformation in enumerate(transformations):
        if not isinstance(transformation, dict):
            findings.block("E027", f"transformations[{index}] 不是对象", where)
            continue
        ttype = transformation.get("type")
        reason = transformation.get("reason")
        if not isinstance(ttype, str) or not ttype:
            findings.block("E027", f"transformations[{index}] 缺少 type", where)
        if not isinstance(reason, str) or not reason:
            findings.block("E027", f"transformations[{index}] 缺少 reason", where)
        if isinstance(ttype, str) and ttype not in TRANSFORMATION_TYPES:
            findings.warn(
                "W016",
                f"transformations[{index}] 使用未登记类型 {ttype!r}",
                where,
            )


def _cloze_marker_numbers(context: str) -> set[int]:
    """Return likely numbered blanks from the passage body.

    The directions contain an unrelated ``10 points`` token, so begin after
    the answer-sheet instruction when it is present.  This check is a quality
    warning rather than a rewrite rule: OCR may use underscores or punctuation
    around a number, but a missing blank is still important enough to surface.
    """
    text = str(context or "")
    starts = [text.lower().find("answer sheet"), text.lower().find("answer\u00a0sheet")]
    start = max(starts)
    body = text[start + len("answer sheet") :] if start >= 0 else text
    return {
        int(match.group(1))
        for match in CLOZE_MARKER_RE.finditer(body)
        if 1 <= int(match.group(1)) <= 20
    }


def _analysis_is_guarded(question: dict) -> bool:
    text = str(question.get("source_analysis_md") or "").lstrip()
    if text.startswith(ANALYSIS_GUARD_PREFIX):
        return True
    transformations = question.get("transformations")
    return isinstance(transformations, list) and any(
        isinstance(item, dict)
        and "content_quality_guard:" in str(item.get("reason") or "")
        for item in transformations
    )


def _analysis_noise_reason(question: dict, duplicate_counts: dict[str, int]) -> str | None:
    """Detect only high-confidence analysis corruption, never infer a repair."""
    text = str(question.get("source_analysis_md") or "")
    if not text.strip() or _analysis_is_guarded(question):
        return None
    if len(text) > 20_000:
        return f"解析长度 {len(text)} 字，疑似跨题串接"
    if "[无文本层" in text or text.count("配套") >= 8 or text.count("音频") >= 8:
        return "解析含重复低信息 OCR 噪声"
    if text.count("\ufffd") >= 3:
        return "解析含多个替换字符"
    if str(question.get("question_id") or "") == "english-e2-2024-q-02" and "digital technologies" in text:
        return "解析内容与题号明显错配"
    if duplicate_counts.get(text, 0) > 1 and len(text) >= 200:
        return "多个题目共用完全相同的长解析，疑似边界串题"
    return None


def _validate_content_quality(formal_questions: list[dict], findings: Findings) -> None:
    """Add conservative content-level gates after structural validation."""
    duplicate_counts: dict[str, int] = {}
    for question in formal_questions:
        text = str(question.get("source_analysis_md") or "")
        if text.strip():
            duplicate_counts[text] = duplicate_counts.get(text, 0) + 1

    checked_cloze_contexts: set[str] = set()
    for question in formal_questions:
        where = f"questions.jsonl:{question.get('question_id', '<unknown>')}"
        if question.get("unit_key") == "use-of-english":
            context = str(question.get("context_md") or "")
            if context not in checked_cloze_contexts:
                checked_cloze_contexts.add(context)
                missing = sorted(set(range(1, 21)) - _cloze_marker_numbers(context))
                if missing:
                    findings.warn(
                        "W021",
                        f"完形上下文疑似缺少空位标记: {', '.join(str(item) for item in missing)}",
                        where,
                    )
        reason = _analysis_noise_reason(question, duplicate_counts)
        if reason:
            findings.warn("W022", reason, where)


def validate_package(package_dir: Path) -> dict:
    findings = Findings()
    package = {
        "package_dir": str(package_dir),
        "schema_version": SCHEMA_VERSION,
        "validated_at": datetime.datetime.now().replace(microsecond=0).isoformat(),
    }

    if not package_dir.is_dir():
        findings.block("E001", f"题库包目录不存在: {package_dir}")
        package.update(
            {
                "quality": {"status": findings.status, "blocker_count": findings.blocker_count, "warning_count": findings.warning_count},
                "summary": {},
                "blockers": findings.blockers,
                "warnings": findings.warnings,
            }
        )
        return package

    manifest_path = package_dir / "manifest.json"
    manifest = load_json(manifest_path, findings, "E001/E002", "manifest.json")

    formal_questions: list[dict] = []

    bank_meta: dict = {}
    expected_bank_id = ""
    if manifest is not None and isinstance(manifest, dict):
        _validate_manifest(manifest, package_dir, findings)
        if isinstance(manifest.get("bank"), dict):
            bank_meta = {
                key: manifest["bank"].get(key)
                for key in ("id", "title", "domain", "subject")
            }
            bank_id_value = manifest["bank"].get("id")
            if isinstance(bank_id_value, str):
                expected_bank_id = bank_id_value
    elif manifest is not None:
        findings.block("E002", "manifest.json 根节点不是对象")

    # source-index and knowledge-map are validated even when questions.jsonl
    # is missing/empty, so the report stays complete and crash-free.
    source_index_payload = load_json(
        package_dir / "source-index.json", findings, "E011", "source-index.json"
    )
    source_lookup = _validate_source_index(source_index_payload, manifest, findings)
    knowledge_payload = load_json(
        package_dir / "knowledge-map.json", findings, "E010", "knowledge-map.json"
    )
    knowledge_map_ids = _load_knowledge_map(
        knowledge_payload, manifest, source_lookup, findings
    )

    # ---- questions.jsonl ----
    known_ids: set[str] = set()
    composite_keys: set[tuple] = set()
    type_counts: dict[str, int] = {}
    difficulty_counts: dict[str, int] = {}
    scope_counts: dict[str, int] = {}
    transformation_total = 0

    questions_path = package_dir / "questions.jsonl"
    if not questions_path.is_file():
        findings.block("E005", "questions.jsonl 缺失")
    else:
        declared_sha = ""
        if isinstance(manifest, dict):
            question_node = manifest.get("questions")
            if isinstance(question_node, dict):
                declared_sha = str(question_node.get("sha256") or "")
        if declared_sha and sha256_file(questions_path) != declared_sha:
            findings.block(
                "E009",
                "questions.jsonl SHA-256 与 manifest 声明不一致",
            )
        for line_number, raw_line in enumerate(questions_path.read_text(encoding="utf-8").splitlines(), start=1):
            raw = raw_line
            if not raw.strip():
                continue
            where = f"questions.jsonl:行{line_number}"
            try:
                record = json.loads(raw)
            except ValueError as error:
                findings.block("E006", f"{where} JSON 解析失败: {error}", where)
                continue
            if not isinstance(record, dict):
                findings.block("E037", f"{where} 不是 JSON 对象", where)
                continue
            question_id = record.get("question_id")
            if isinstance(question_id, str) and question_id in known_ids:
                findings.block("E014", f"重复的 question_id: {question_id}", where)
            if isinstance(question_id, str):
                known_ids.add(question_id)
            local_number = record.get("local_number")
            if local_number is None:
                findings.warn("W013", "缺少 local_number", where)
            elif isinstance(local_number, bool) or not isinstance(local_number, int) or local_number < 1:
                findings.block("E055", f"local_number 必须是大于等于 1 的整数: {local_number!r}", where)
            else:
                key = (
                    str(record.get("unit_key") or ""),
                    str(record.get("question_type") or ""),
                    local_number,
                )
                if key in composite_keys:
                    findings.block(
                        "E028",
                        f"重复的“单元＋题型＋局部题号”键: unit_key={key[0]!r} type={key[1]!r} number={key[2]!r}",
                        where,
                    )
                composite_keys.add(key)
            qtype = record.get("question_type")
            if isinstance(qtype, str):
                type_counts[qtype] = type_counts.get(qtype, 0) + 1
            difficulty = record.get("difficulty")
            if isinstance(difficulty, str):
                difficulty_counts[difficulty] = difficulty_counts.get(difficulty, 0) + 1
                if difficulty not in DIFFICULTIES:
                    findings.warn("W010", f"difficulty 取值未登记: {difficulty!r}", where)
            else:
                findings.warn("W010", "缺少 difficulty 字段", where)
            scope = record.get("scope")
            if isinstance(scope, str):
                scope_counts[scope] = scope_counts.get(scope, 0) + 1
                if scope not in SCOPES:
                    findings.warn("W011", f"scope 取值未登记: {scope!r}", where)
            validate_question_record(
                record,
                findings,
                knowledge_map_ids=knowledge_map_ids,
                source_lookup=source_lookup,
                where=where,
                expected_status="ready",
                quarantine_mode=False,
                expected_bank_id=expected_bank_id,
                bank_mismatch_code="E042",
            )
            transformations = record.get("transformations")
            if isinstance(transformations, list):
                transformation_total += len(transformations)
            formal_questions.append(record)

        question_count_declared = (
            manifest.get("question_count") if isinstance(manifest, dict) else None
        )
        if isinstance(question_count_declared, int):
            if question_count_declared != len(formal_questions):
                findings.block(
                    "E007",
                    f"manifest.question_count={question_count_declared} 与 questions.jsonl 实际 {len(formal_questions)} 不一致",
                )
        else:
            findings.block("E007", "manifest.question_count 不是整数")

        referenced_ids: set[str] = set()
        for record in formal_questions:
            knowledge_values = record.get("knowledge_ids")
            if isinstance(knowledge_values, list):
                referenced_ids.update(
                    value for value in knowledge_values if isinstance(value, str)
                )
        for orphan in sorted(knowledge_map_ids - referenced_ids):
            findings.warn(
                "W001",
                f"知识映射存在孤立条目（没有被任何正式题目引用）: {orphan}",
            )

        declared_type_counts = (
            manifest.get("question_type_counts") if isinstance(manifest, dict) else None
        )
        if isinstance(declared_type_counts, dict):
            if declared_type_counts != type_counts:
                findings.block(
                    "E008",
                    f"manifest.question_type_counts={declared_type_counts} 与实际 {type_counts} 不一致",
                )
        else:
            findings.block("E008", "manifest.question_type_counts 缺失或不是对象")

        # Structural fields above cannot tell whether OCR has dropped a
        # cloze blank or spliced one question's explanation into another.
        # Run the conservative content gate only after the complete formal
        # question set is available, so one shared passage produces one clear
        # finding instead of twenty duplicates.
        _validate_content_quality(formal_questions, findings)

    # ---- quarantine ----
    quarantine_dir = package_dir / "quarantine"
    quarantine_questions = _load_quarantine(
        quarantine_dir,
        manifest,
        findings,
        knowledge_map_ids,
        source_lookup,
        formal_ids=known_ids,
        expected_bank_id=expected_bank_id,
    )

    if isinstance(manifest, dict) and manifest.get("quarantined_count") is not None:
        declared_q = manifest.get("quarantined_count")
        if not isinstance(declared_q, int):
            findings.block("E030", "manifest.quarantined_count 不是整数")
        elif declared_q != len(quarantine_questions):
            findings.block(
                "E030",
                f"manifest.quarantined_count={declared_q} 与 quarantine/questions.jsonl 实际 {len(quarantine_questions)} 不一致",
            )

    # ---- source-index declared-source consistency ----
    _check_manifest_sources_consistency(manifest, source_index_payload, findings)

    # ---- manifest quality consistency ----
    if isinstance(manifest, dict) and isinstance(manifest.get("quality"), dict):
        declared_quality = manifest["quality"]
        computed_status = findings.status
        computed_blockers = findings.blocker_count
        computed_warnings = findings.warning_count
        d_status = declared_quality.get("status")
        d_blockers = declared_quality.get("blocker_count")
        d_warnings = declared_quality.get("warning_count")
        if not isinstance(d_status, str) or d_status not in QUALITY_STATUS_VALUES or not isinstance(d_blockers, int) or not isinstance(d_warnings, int):
            findings.block("E033", "manifest.quality 字段非法")
        else:
            expected_status_from_counts = (
                "blocked" if d_blockers else ("warning" if d_warnings else "pass")
            )
            if d_status != expected_status_from_counts:
                findings.block(
                    "E033",
                    f"manifest.quality.status={d_status!r} 与自身 blocker_count/warning_count 矛盾（应为 {expected_status_from_counts}）",
                )
            if d_blockers != computed_blockers or d_warnings != computed_warnings:
                findings.block(
                    "E033",
                    f"manifest.quality 声明 (blockers={d_blockers}, warnings={d_warnings}) 与实测 ({computed_blockers}, {computed_warnings}) 不一致",
                )
    elif isinstance(manifest, dict):
        findings.block("E033", "manifest.quality 缺失")

    summary = {
        "question_count": len(formal_questions),
        "quarantined_count": len(quarantine_questions),
        "question_type_counts": type_counts,
        "difficulty_counts": difficulty_counts,
        "scope_counts": scope_counts,
        "transformations_total": transformation_total,
        "knowledge_map_entries": len(knowledge_map_ids),
        "source_blocks_total": _count_source_blocks(source_index_payload),
        "known_question_ids": len(known_ids),
    }

    package.update(
        {
            "bank": bank_meta,
            "quality": {
                "status": findings.status,
                "blocker_count": findings.blocker_count,
                "warning_count": findings.warning_count,
            },
            "summary": summary,
            "blockers": findings.blockers,
            "warnings": findings.warnings,
        }
    )
    return package


def _validate_manifest(manifest: dict, package_dir: Path, findings: Findings) -> None:
    if manifest.get("schema_version") != SCHEMA_VERSION:
        findings.block(
            "E003",
            f"schema_version 必须为 {SCHEMA_VERSION}，实际 {manifest.get('schema_version')!r}",
        )

    bank = manifest.get("bank")
    if not isinstance(bank, dict):
        findings.block("E004", "manifest.bank 缺失")
        return
    for required_field in ("id", "title", "domain", "subject", "resource_type", "status"):
        if not isinstance(bank.get(required_field), str) or not bank[required_field].strip():
            findings.block("E004", f"manifest.bank.{required_field} 缺失或为空")
    bank_status = bank.get("status")
    if not isinstance(bank_status, str) or bank_status not in BANK_STATUS_VALUES:
        findings.block("E004", f"manifest.bank.status 非法: {bank_status!r}")
    elif bank_status != "ready":
        findings.block("E004", f"manifest.bank.status 必须为 ready 才可发布，实际 {bank_status!r}")

    for declared in ("knowledge_map", "questions", "source_index"):
        node = manifest.get(declared)
        if not isinstance(node, dict):
            findings.block("E005", f"manifest.{declared} 缺失")
            continue
        path_value = node.get("path")
        sha_value = node.get("sha256")
        if not isinstance(path_value, str) or not path_value:
            findings.block("E005", f"manifest.{declared}.path 缺失")
            continue
        if not isinstance(sha_value, str) or not SHA256_RE.match(sha_value):
            findings.block("E005", f"manifest.{declared}.sha256 缺失或格式非法")
            continue
        file_path = package_dir / path_value
        if not file_path.is_file():
            findings.block("E005", f"{path_value} 文件缺失")
            continue
        actual_sha = sha256_file(file_path)
        if actual_sha != sha_value:
            findings.block(
                "E009",
                f"{path_value} SHA-256 与 manifest.{declared}.sha256 不一致",
            )


def _load_knowledge_map(
    payload,
    manifest,
    source_lookup: dict[str, dict[str, dict]],
    findings: Findings,
) -> set[str]:
    """Validate knowledge-map.json identity and per-entry structure.

    Returns the set of valid knowledge_ids so question knowledge refs can be
    checked. A single bad entry never aborts the whole validation."""
    ids: set[str] = set()
    if not isinstance(payload, dict):
        return ids

    map_version = payload.get("map_version")
    if map_version != SUPPORTED_MAP_VERSION:
        findings.block(
            "E054",
            f"knowledge-map.map_version 必须为 {SUPPORTED_MAP_VERSION}，实际 {map_version!r}",
        )

    bank_id = payload.get("bank_id")
    if not isinstance(bank_id, str) or not bank_id.strip():
        findings.block("E039", "knowledge-map.json 缺少 bank_id")
    elif isinstance(manifest, dict) and isinstance(manifest.get("bank"), dict):
        manifest_bank_id = manifest["bank"].get("id")
        if bank_id != manifest_bank_id:
            findings.block(
                "E039",
                f"knowledge-map.json.bank_id={bank_id!r} 与 manifest.bank.id={manifest_bank_id!r} 不一致",
            )

    entries = payload.get("entries")
    if not isinstance(entries, list):
        findings.block("E010", "knowledge-map.json 缺少 entries 数组")
        return ids

    for index, entry in enumerate(entries):
        where = f"knowledge-map.json:entries[{index}]"
        if not isinstance(entry, dict):
            findings.block("E010", f"{where} 不是对象", where)
            continue
        knowledge_id = entry.get("knowledge_id")
        if not isinstance(knowledge_id, str) or not KNOWLEDGE_ID_RE.match(knowledge_id):
            findings.block("E035", f"{where} knowledge_id 语法非法: {knowledge_id!r}", where)
            continue
        if knowledge_id in ids:
            findings.block("E034", f"knowledge-map 重复的 knowledge_id: {knowledge_id}", where)
        ids.add(knowledge_id)
        kind = entry.get("kind")
        if not isinstance(kind, str) or kind not in KNOWLEDGE_KINDS:
            findings.warn("W015", f"{where} kind 未登记: {kind!r}", where)
        label = entry.get("label")
        if not isinstance(label, str) or not label.strip():
            findings.warn("W018", f"{where} label 缺失或为空", where)
        entry_path = entry.get("path")
        if (
            not isinstance(entry_path, list)
            or not entry_path
            or any(not isinstance(part, str) or not part for part in entry_path)
        ):
            findings.warn("W017", f"{where} path 必须是非空字符串数组", where)
        source_ref = entry.get("source_ref")
        if isinstance(source_ref, dict):
            sid = source_ref.get("source_id")
            bid = source_ref.get("block_id")
            if not isinstance(sid, str) or not sid:
                findings.warn("W014", f"{where} source_ref 缺少 source_id", where)
            elif not isinstance(bid, str) or not bid:
                findings.warn("W014", f"{where} source_ref 缺少 block_id", where)
            else:
                source_blocks = source_lookup.get(sid)
                if source_blocks is None or bid not in source_blocks:
                    findings.warn(
                        "W014",
                        f"{where} source_ref 无法在 source-index 解析: {sid}/{bid}",
                        where,
                    )
        elif source_ref is not None:
            findings.warn("W014", f"{where} source_ref 不是对象", where)
    return ids


def _load_quarantine(
    quarantine_dir: Path,
    manifest,
    findings: Findings,
    knowledge_map_ids: set[str],
    source_lookup: dict[str, dict[str, dict]],
    formal_ids: set[str],
    expected_bank_id: str,
) -> list[dict]:
    questions_path = quarantine_dir / "questions.jsonl"
    reasons_path = quarantine_dir / "reasons.json"
    entries: list[dict] = []

    if not questions_path.is_file():
        return entries

    quarantine_ids: set[str] = set()
    for line_number, raw in enumerate(questions_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        where = f"quarantine/questions.jsonl:行{line_number}"
        try:
            record = json.loads(raw)
        except ValueError as error:
            findings.block("E030", f"{where} JSON 解析失败: {error}", where)
            continue
        if not isinstance(record, dict):
            findings.block("E030", f"{where} 不是对象", where)
            continue
        question_id = record.get("question_id")
        if isinstance(question_id, str):
            if question_id in quarantine_ids:
                findings.block("E030", f"隔离区重复 question_id: {question_id}", where)
            quarantine_ids.add(question_id)
            if question_id in formal_ids:
                findings.block(
                    "E029",
                    f"隔离题目出现在正式 questions.jsonl: {question_id}",
                    where,
                )
        validate_question_record(
            record,
            findings,
            knowledge_map_ids=knowledge_map_ids,
            source_lookup=source_lookup,
            where=where,
            expected_status="quarantined",
            quarantine_mode=True,
            expected_bank_id=expected_bank_id,
            bank_mismatch_code="E043",
        )
        entries.append(record)

    if not entries:
        return entries

    reasons = load_json(reasons_path, findings, "E031", "quarantine/reasons.json")
    reason_ids: set[str] = set()
    if isinstance(reasons, dict):
        reasons_bank_id = reasons.get("bank_id")
        if not isinstance(reasons_bank_id, str) or not reasons_bank_id.strip():
            findings.block("E041", "quarantine/reasons.json 缺少 bank_id")
        elif expected_bank_id and reasons_bank_id != expected_bank_id:
            findings.block(
                "E041",
                f"quarantine/reasons.json.bank_id={reasons_bank_id!r} 与 manifest.bank.id={expected_bank_id!r} 不一致",
            )
        reason_list = reasons.get("reasons")
        if not isinstance(reason_list, list):
            findings.block("E032", "quarantine/reasons.json.reasons 必须是数组")
            reason_list = []
        for index, reason_entry in enumerate(reason_list):
            where = f"quarantine/reasons.json:reasons[{index}]"
            if not isinstance(reason_entry, dict):
                findings.block("E032", f"{where} 不是对象", where)
                continue
            question_id = reason_entry.get("question_id")
            reason_text = reason_entry.get("reason")
            if not isinstance(question_id, str) or not question_id:
                findings.block("E032", f"{where} 缺少 question_id", where)
                continue
            if question_id not in quarantine_ids:
                findings.warn(
                    "W012",
                    f"隔离原因对应不存在的隔离题 {question_id!r}",
                    where,
                )
            reason_ids.add(question_id)
            if not isinstance(reason_text, str) or not reason_text.strip():
                findings.block("E032", f"{where} 缺少非空 reason", where)
    elif reasons is not None:
        findings.block("E031", "quarantine/reasons.json 根节点不是对象")
    # reasons is None only when load_json already recorded E031 (missing/unreadable),
    # so no second blocker is emitted here; the per-question E032 loop below still
    # reports every quarantine entry that lacks a reason record.

    for question_id in sorted(quarantine_ids - reason_ids):
        findings.block(
            "E032",
            f"隔离题目缺少隔离原因记录: {question_id}",
        )
    return entries


def _check_manifest_sources_consistency(manifest, source_index, findings: Findings) -> None:
    if not isinstance(manifest, dict) or not isinstance(source_index, dict):
        return
    manifest_sources = manifest.get("sources")
    if not isinstance(manifest_sources, list):
        findings.block("E012", "manifest.sources 缺失或不是数组")
        return
    indexed = {}
    for source in source_index.get("sources", []):
        if not isinstance(source, dict):
            continue
        source_id = source.get("source_id")
        if isinstance(source_id, str):
            indexed[source_id] = source
    for index, source in enumerate(manifest_sources):
        where = f"manifest.sources[{index}]"
        if not isinstance(source, dict):
            findings.block("E012", f"{where} 不是对象", where)
            continue
        source_id = source.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            findings.block("E012", f"{where} 缺少 source_id", where)
            continue
        for field in ("filename", "sha256", "role"):
            value = source.get(field)
            if not isinstance(value, str) or not value:
                findings.block("E012", f"{where} 缺少 {field}", where)
        sha_value = source.get("sha256")
        if isinstance(sha_value, str) and not SHA256_RE.match(sha_value):
            findings.block("E012", f"{where} sha256 格式非法", where)
        role = source.get("role")
        if isinstance(role, str) and role not in SOURCE_ROLES:
            findings.block("E012", f"{where} role 未登记: {role!r}", where)
        match = indexed.get(source_id)
        if match is None:
            findings.block(
                "E012",
                f"manifest.sources 声明 {source_id} 但 source-index.json 中没有对应 source",
                where,
            )
            continue
        if (
            match.get("filename") != source.get("filename")
            or match.get("sha256") != source.get("sha256")
            or match.get("role") != source.get("role")
        ):
            findings.block(
                "E012",
                f"manifest.sources 与 source-index.json 对 {source_id} 的 filename/sha256/role 不一致",
                where,
            )

    # orphan warning: declared source without any indexed block
    for index, source in enumerate(manifest_sources):
        if not isinstance(source, dict):
            continue
        source_id = source.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            continue
        match = indexed.get(source_id)
        if match is None:
            continue
        if not isinstance(match.get("blocks"), list) or not match["blocks"]:
            findings.warn(
                "W008",
                f"声明来源 {source_id} 在 source-index 中没有索引块",
            )


def _count_source_blocks(source_index) -> int:
    if not isinstance(source_index, dict):
        return 0
    return sum(
        len(source.get("blocks", []))
        for source in source_index.get("sources", [])
        if isinstance(source, dict) and isinstance(source.get("blocks"), list)
    )


def _write_reports(package_dir: Path, result: dict) -> None:
    reports_dir = package_dir / "reports"
    try:
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / "validation.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        quality_report = {
            "bank_id": str(result.get("bank", {}).get("id") or ""),
            "bank_title": str(result.get("bank", {}).get("title") or ""),
            "quality": result["quality"],
            "summary": result["summary"],
            "blocker_codes": [item["code"] for item in result["blockers"]],
            "warning_codes": [item["code"] for item in result["warnings"]],
            "recommendation": (
                "不发布：存在 blocker"
                if result["quality"]["blocker_count"]
                else "可发布（含 warning，需 Agent 自行解释）"
                if result["quality"]["warning_count"]
                else "可发布：0 blocker、0 warning"
            ),
        }
        (reports_dir / "quality-report.json").write_text(
            json.dumps(quality_report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as error:
        print(f"[yupractice] 警告: 无法写入 reports/: {error}", file=sys.stderr)


def human_summary(result: dict) -> str:
    quality = result["quality"]
    summary = result["summary"]
    bank = result.get("bank", {})
    lines = [
        f"YuPractice validate  {result['package_dir']}",
        f"题库: {bank.get('id', '')}  {bank.get('title', '')}",
        f"质量: {quality['status']}  blocker={quality['blocker_count']}  warning={quality['warning_count']}",
        f"题目数: {summary.get('question_count', 0)}  隔离数: {summary.get('quarantined_count', 0)}  来源块: {summary.get('source_blocks_total', 0)}",
        f"题型: {summary.get('question_type_counts', {})}",
        f"难度: {summary.get('difficulty_counts', {})}  范围: {summary.get('scope_counts', {})}",
        f"知识位置: {summary.get('knowledge_map_entries', 0)}  修复记录: {summary.get('transformations_total', 0)}",
    ]
    if result["blockers"]:
        lines.append("")
        lines.append("BLOCKERS:")
        for item in result["blockers"]:
            where = item.get("where", "")
            lines.append(f"  [{item['code']}] {item['message']}" + (f"  ({where})" if where else ""))
    if result["warnings"]:
        lines.append("")
        lines.append("WARNINGS:")
        for item in result["warnings"]:
            where = item.get("where", "")
            lines.append(f"  [{item['code']}] {item['message']}" + (f"  ({where})" if where else ""))
    return "\n".join(lines)


def cmd_validate(args) -> int:
    package_dir = Path(args.package_dir).resolve()
    result = validate_package(package_dir)
    _write_reports(package_dir, result)
    if args.json:
        _emit_utf8_json(result)
    else:
        # Human summary uses the normal text layer: on an interactive Windows
        # console it is UTF-8 (configure_windows_utf8), while redirected output
        # and non-Windows environments keep their usual locale encoding.
        print(human_summary(result))
    return 2 if result["quality"]["blocker_count"] else 0


def main(argv: list[str] | None = None) -> int:
    configure_windows_utf8()
    parser = argparse.ArgumentParser(
        prog="yupractice.py",
        description="YuPractice question-bank package validator.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate", help="validate a question-bank package directory")
    validate_parser.add_argument("package_dir", help="path to the question-bank package directory")
    validate_parser.add_argument("--json", action="store_true", help="print the machine-readable JSON report to stdout")
    args = parser.parse_args(argv)
    if args.command == "validate":
        return cmd_validate(args)
    parser.error(f"unknown command: {args.command}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
