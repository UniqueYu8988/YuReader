#!/usr/bin/env python3
"""Create safer, derived English candidates from completed YuPractice packages.

This is deliberately conservative. It never edits the input package or any
source PDF/Markdown. It only repairs deterministic display defects (cloze
markers and page-footers), removes clearly leaked Part-B labels, and hides an
analysis excerpt when its boundary/OCR quality is demonstrably unsafe. An
unsafe explanation must not be shown as if it were the answer key.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


FOOTER_RE = re.compile(
    r"\s*(?:20\d{2}年[^\n]{0,60}试题|英语\s*[（(]?[一二12][）)]?\s*试题)[^\n]{0,80}"
    r"(?:第\s*\d+\s*页|共\s*\d+\s*页)[^\n]*$",
    re.IGNORECASE,
)
PAGE_TAIL_RE = re.compile(r"\s*20\d{2}-\d+\s*<!--\s*PAGE\s*\d+\s*-->\s*$")
INLINE_PAGE_COMMENT_RE = re.compile(r"\s*<!--\s*page\s+\d+\s*-->\s*", re.IGNORECASE)
TRUNCATED_PAGE_COMMENT_RE = re.compile(r"\s*<!--\s*page\s+\d+\b.*$", re.IGNORECASE | re.MULTILINE)
QUESTION_NAME_TAIL_RE = re.compile(
    r"\s+(?:41|42|43|44|45)\.\s+[A-Z][A-Za-z .'-]{1,80}\s*$"
)
PROMO_LINE_RE = re.compile(
    r"(?:认准淘宝店铺|赠送配套课程|免费获取最新|扫码兑换|关注公众号|资料同步\s*VX|免费分享\s*PDF|涛涛提示)",
    re.IGNORECASE,
)


# A source-level OCR disagreement may be promoted only when it has been
# independently resolved and the resolution is recorded in the repair receipt.
# Keep this allow-list deliberately tiny: it is not a general-purpose answer
# guessing rule.
RESOLVED_QUARANTINE = {
    "english-e2-2025-q-16": {
        "bank_id": "english-e2-2025",
        "option_label": "A",
        "source_value": "read",
        "resolved_value": "recall",
        "reason": (
            "试卷 OCR 将选项 A 识别为 read；同年速查答案与详细解析均为 recall，"
            "并经独立公开真题页面交叉核对后恢复为 recall。原始 exam-paper OCR 不覆盖。"
        ),
        "external_sources": [
            "https://www.youlu.com/kaoyan/article/CA20241222010000000021",
            "https://english-exam.lazynote.cn/kaoyan/sections/2025-english-two/section1/",
        ],
    }
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean_visible_text(value: str) -> str:
    """Remove only unmistakable page furniture from user-visible text."""
    value = INLINE_PAGE_COMMENT_RE.sub(" ", str(value or ""))
    value = TRUNCATED_PAGE_COMMENT_RE.sub(" ", value)
    lines: list[str] = []
    for raw in str(value or "").splitlines():
        line = raw.strip()
        if line.startswith("<!--") and line.endswith("-->"):
            continue
        if PROMO_LINE_RE.search(line):
            continue
        line = PAGE_TAIL_RE.sub("", line)
        line = FOOTER_RE.sub("", line)
        if line.strip():
            lines.append(line.rstrip())
        elif lines and lines[-1] != "":
            lines.append("")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def replace_first_after(text: str, needle: str, replacement: str, start: int) -> tuple[str, bool]:
    position = text.find(needle, start)
    if position < 0:
        return text, False
    return text[:position] + replacement + text[position + len(needle) :], True


def normalize_broken_marker(text: str, number: int) -> tuple[str, bool]:
    """Collapse OCR-separated digits such as ``�1�7�`` to ``17``."""
    digits = str(number)
    if len(digits) != 2:
        return text, False
    exact = re.search(rf"(?<!\d){re.escape(digits)}(?!\d)", text)
    if exact:
        return text, False
    first, second = digits
    pattern = re.compile(rf"(?<!\d){first}[^0-9A-Za-z\n]{{1,6}}{second}(?!\d)")
    match = pattern.search(text)
    if not match:
        return text, False
    return text[: match.start()] + digits + text[match.end() :], True


def normalize_cloze_context(context: str, package_id: str) -> tuple[str, list[str]]:
    text = clean_visible_text(context)
    changes: list[str] = []

    # These are deterministic layout repairs observed in the source OCR. They
    # do not invent prose; they restore the numbered blanks already represented
    # by the surrounding sentence and answer set.
    if package_id == "english-e2-2014":
        replacements = [
            ("have\n\nthat", "have 1 that", "inserted missing blank 1"),
            ("schools.\n\nNegative", "schools. 17 Negative", "inserted missing blank 17"),
            ("obesity,\n\nin health concerns", "obesity, 18 in health concerns", "inserted missing blank 18"),
        ]
        for old, new, reason in replacements:
            if old in text:
                text = text.replace(old, new, 1)
                changes.append(reason)
    if package_id == "english-2021-e1":
        old = "higher measures of abdominal fat\nmeasures of fluid intelligence as the years 11\n10 worse on"
        new = "higher measures of abdominal fat 10 scored worse on measures of fluid intelligence as the years 11 went by"
        if old in text:
            text = text.replace(old, new, 1)
            changes.append("restored OCR column order around blanks 10–11")
    if package_id == "english-2018-e1":
        old = "__ l--'-6 _ the\ncontainer was empty"
        if old in text:
            text = text.replace(old, "16 the\ncontainer was empty", 1)
            changes.append("restored missing blank 16 marker")
    if package_id == "english-e2-2022":
        old_match = re.search(r"write\s+H\s*they listen", text)
        if old_match:
            text = text[: old_match.start()] + "write 11 they listen" + text[old_match.end() :]
            changes.append("restored OCR blank 11 marker")

    for number in range(2, 21):
        text, changed = normalize_broken_marker(text, number)
        if changed:
            changes.append(f"collapsed OCR-separated blank {number}")

    # A few scans lose the first blank as a lone bracket. Restrict this to the
    # passage body and only when no real marker 1 exists before marker 2.
    directions_end = max(text.lower().find("answer sheet"), text.lower().find("directions"))
    body_start = max(0, directions_end)
    first_one = re.search(r"(?<!\d)1(?!\d)", text[body_start:])
    first_two = re.search(r"(?<!\d)2(?!\d)", text[body_start:])
    if not first_one or (first_two and first_one.start() > first_two.start()):
        before_two = body_start + (first_two.start() if first_two else len(text) - body_start)
        bracket = re.search(r"[\]】]", text[body_start:before_two])
        if bracket:
            position = body_start + bracket.start()
            text = text[:position] + "1" + text[position + 1 :]
            changes.append("restored missing first cloze marker")
    return text, changes


def analysis_is_unsafe(question: dict, duplicate_ids: set[str]) -> str | None:
    text = str(question.get("source_analysis_md") or "")
    qid = str(question.get("question_id") or "")
    if qid in duplicate_ids:
        return "exact duplicate analysis block shared by multiple questions"
    if len(text) > 20000:
        return f"analysis excerpt is {len(text)} characters and crosses a likely section boundary"
    if "[无文本层" in text or text.count("配套") >= 8 or text.count("音频") >= 8:
        return "OCR analysis contains repeated low-information noise"
    if text.count("\ufffd") >= 3:
        return "analysis contains repeated replacement characters"
    if qid == "english-e2-2024-q-02" and "digital technologies" in text:
        return "analysis is visibly attached to another question"
    return None


def promote_resolved_quarantine(
    destination: Path, questions: list[dict], changes: list[dict]
) -> list[dict]:
    """Promote only explicitly resolved quarantine records.

    This is intentionally an allow-list operation.  A quarantined question is
    never inferred from context or an answer key by this function; it must have
    a matching entry in ``RESOLVED_QUARANTINE`` and the expected source value.
    The old quarantine record is retained in the repair receipt so the
    source/OCR disagreement remains auditable.
    """
    quarantine_path = destination / "quarantine" / "questions.jsonl"
    if not quarantine_path.is_file():
        return []
    raw_records = [
        json.loads(line)
        for line in quarantine_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    remaining: list[dict] = []
    promoted: list[dict] = []
    for record in raw_records:
        qid = str(record.get("question_id") or "")
        resolution = RESOLVED_QUARANTINE.get(qid)
        if not resolution or str(record.get("bank_id") or "") != resolution["bank_id"]:
            remaining.append(record)
            continue
        options = record.get("options")
        target = next(
            (
                option
                for option in options
                if isinstance(option, dict)
                and option.get("label") == resolution["option_label"]
            ),
            None,
        ) if isinstance(options, list) else None
        if not isinstance(target, dict) or str(target.get("text_md") or "") != resolution["source_value"]:
            # Refuse a silent promotion if the candidate changed underneath
            # this explicit resolution record.
            remaining.append(record)
            continue
        target["text_md"] = resolution["resolved_value"]
        record["status"] = "ready"
        record.setdefault("transformations", []).append(
            {
                "type": "ocr_fix",
                "reason": resolution["reason"],
                "verified": True,
            }
        )
        promoted.append(record)
        changes.append(
            {
                "question_id": qid,
                "kind": "quarantine_promotion",
                "details": [
                    f"option {resolution['option_label']}: {resolution['source_value']} -> {resolution['resolved_value']}",
                    "resolved against answer/analysis and independent public references",
                ],
                "external_sources": resolution["external_sources"],
            }
        )

    if promoted:
        # Preserve the question order within a unit so q16 appears between q15
        # and q17, rather than being appended after the whole bank.
        for record in promoted:
            unit_key = str(record.get("unit_key") or "")
            local_number = int(record.get("local_number") or 0)
            insert_at = next(
                (
                    index
                    for index, existing in enumerate(questions)
                    if str(existing.get("unit_key") or "") == unit_key
                    and int(existing.get("local_number") or 0) > local_number
                ),
                len(questions),
            )
            questions.insert(insert_at, record)

    quarantine_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) for record in remaining)
        + ("\n" if remaining else ""),
        encoding="utf-8",
    )
    reasons_path = destination / "quarantine" / "reasons.json"
    if reasons_path.is_file():
        reasons = json.loads(reasons_path.read_text(encoding="utf-8"))
        if isinstance(reasons, dict):
            reasons["reasons"] = [
                item
                for item in reasons.get("reasons", [])
                if str(item.get("question_id") or "") not in {record.get("question_id") for record in promoted}
            ]
            reasons_path.write_text(
                json.dumps(reasons, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    return promoted


def repair_package(source: Path, destination: Path) -> dict:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    questions_path = destination / "questions.jsonl"
    questions = [json.loads(line) for line in questions_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    analysis_counts = Counter(str(q.get("source_analysis_md") or "") for q in questions)
    duplicate_ids = {
        q["question_id"]
        for q in questions
        if analysis_counts[str(q.get("source_analysis_md") or "")] > 1
    }
    changes: list[dict] = []
    promoted = promote_resolved_quarantine(destination, questions, changes)
    for question in questions:
        qid = question["question_id"]
        package_id = str(question.get("bank_id") or source.name)
        question["stem_md"] = clean_visible_text(str(question.get("stem_md") or ""))
        if question.get("unit_key") == "use-of-english":
            context, context_changes = normalize_cloze_context(str(question.get("context_md") or ""), package_id)
            question["context_md"] = context
            if context_changes:
                changes.append({"question_id": qid, "kind": "cloze_context", "details": context_changes})
        else:
            question["context_md"] = clean_visible_text(str(question.get("context_md") or ""))
        for option in question.get("options", []):
            value = clean_visible_text(str(option.get("text_md") or ""))
            if question.get("unit_key") == "reading.part-b":
                value = QUESTION_NAME_TAIL_RE.sub("", value)
            option["text_md"] = value
        raw_analysis = str(question.get("source_analysis_md") or "")
        cleaned_analysis = clean_visible_text(raw_analysis)
        # A few OCR pages contain nothing but a shop/QR promotion in the
        # analysis span.  Do not turn that into a structurally missing field;
        # keep an explicit, traceable guard instead.
        if raw_analysis.strip() and not cleaned_analysis.strip():
            question["source_analysis_md"] = (
                "【原书解析未可靠转录】原解析片段仅含版面推广噪声，已隐藏，"
                "未将其作为答案依据。请结合题干、选项和来源解析页阅读。"
            )
            transforms = question.setdefault("transformations", [])
            transforms.append(
                {
                    "type": "other",
                    "reason": "content_quality_guard: analysis span contained only promotional noise",
                    "verified": True,
                }
            )
            changes.append({"question_id": qid, "kind": "analysis_guard", "details": ["analysis span contained only promotional noise"]})
        else:
            question["source_analysis_md"] = cleaned_analysis
        unsafe = analysis_is_unsafe(question, duplicate_ids)
        if unsafe:
            refs = ", ".join(str(ref.get("block_id")) for ref in question.get("source_refs", []) if ref.get("source_id") == "analysis-paper")
            question["source_analysis_md"] = (
                "【原书解析未可靠转录】该题的解析边界或 OCR 质量未通过自动校验，"
                "未将不确定内容作为答案依据。请结合题干、选项和来源解析页阅读。"
                f" 来源块：{refs or '未标注'}"
            )
            transforms = question.setdefault("transformations", [])
            transforms.append({"type": "other", "reason": f"content_quality_guard: {unsafe}", "verified": True})
            changes.append({"question_id": qid, "kind": "analysis_guard", "details": [unsafe]})

    questions_path.write_text(
        "\n".join(json.dumps(q, ensure_ascii=False, separators=(",", ":")) for q in questions) + "\n",
        encoding="utf-8",
    )
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["question_count"] = len(questions)
    manifest["quarantined_count"] = len(
        [line for line in (destination / "quarantine" / "questions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    ) if (destination / "quarantine" / "questions.jsonl").is_file() else 0
    manifest["question_type_counts"] = dict(Counter(str(q.get("question_type") or "") for q in questions))
    manifest["conflicts"] = [
        conflict
        for conflict in manifest.get("conflicts", [])
        if str(conflict.get("question_id") or "") not in {record.get("question_id") for record in promoted}
    ]
    if promoted:
        manifest["resolved_conflicts"] = [
            {
                "question_id": record.get("question_id"),
                "resolution": "正式题选项 A 恢复为 recall；原始 exam-paper OCR 的 read 仅作为冲突证据保留。",
                "basis": "同年 answer-paper/analysis-paper 与独立公开真题页面一致",
                "external_sources": RESOLVED_QUARANTINE[str(record.get("question_id"))]["external_sources"],
            }
            for record in promoted
        ]
    manifest["questions"]["sha256"] = sha256(questions_path)
    manifest["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest["repair"] = {
        "source_package": str(source),
        "source_manifest_sha256": sha256(source / "manifest.json"),
        "receipt": "reports/repair-receipt.json",
        "change_count": len(changes),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_package": str(source),
        "output_package": str(destination),
        "input_questions_sha256": sha256(source / "questions.jsonl"),
        "output_questions_sha256": sha256(questions_path),
        "changes": changes,
    }
    (destination / "reports" / "repair-receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", action="append", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    for source in args.source:
        destination = args.output_root / source.name
        receipt = repair_package(source, destination)
        print(f"{source.name}: {len(receipt['changes'])} change records -> {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
