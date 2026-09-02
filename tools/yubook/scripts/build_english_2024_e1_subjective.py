"""Assemble the missing 2024 English-I subjective companion from local OCR sources.

This is a one-off, auditable assembly step: the source slices are copied without
rewriting, then YuBook's normal validator/build pipeline creates the candidate
package.  It intentionally does not touch the original PDFs or YuPractice bank.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PROJECT = ROOT / "tools" / "yubook" / "workspace" / "english-exam-2024-e1-subjective"
EXAM = ROOT / "tools" / "yupractice" / "workspace" / "english-2024-e1" / "source" / "exam.md"
ANALYSIS = next((path for path in (ROOT / "tools" / "yupractice" / "workspace" / "english-2024-e1" / "raw" / "analysis").rglob("*.md")), None)


def slice_lines(lines: list[str], start: int, end: int) -> list[str]:
    """Return an inclusive, 1-based source range."""
    return lines[start - 1 : end]


def marker(lines: list[str], text: str, start: int = 0) -> int:
    """Find a unique structural marker by its exact stripped text."""
    for index in range(start, len(lines)):
        if lines[index].strip() == text:
            return index
    raise ValueError(f"source marker not found: {text}")


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    if not EXAM.is_file() or ANALYSIS is None or not ANALYSIS.is_file():
        raise SystemExit("2024 English-I exam or analysis Markdown source is missing")
    exam_lines = EXAM.read_text(encoding="utf-8").splitlines()
    analysis_lines = ANALYSIS.read_text(encoding="utf-8").splitlines()
    parts: list[tuple[str, str, list[str], str]] = []

    translation_start = marker(exam_lines, "Part C", 450)
    translation_end = marker(exam_lines, "2024-14", translation_start)
    writing_start = marker(exam_lines, "Section III Writing", translation_end)
    writing_part_b = marker(exam_lines, "Part B", writing_start)
    # Stop before the printed page footer; the answer quick-reference page is
    # outside the subjective writing material and should not become reader
    # content.
    writing_end = marker(exam_lines, "2024-15", writing_start)
    analysis_part_c = marker(analysis_lines, "## Part C", 800)
    analysis_writing = marker(analysis_lines, "## Section Ⅲ Writing", analysis_part_c)
    analysis_part_b = marker(analysis_lines, "## Part B", analysis_writing)
    parts.append(("ch01-translation", "第一节 翻译 Part C", exam_lines[translation_start:translation_end], "reading"))
    parts.append(("ch01-translation-analysis", "第二节 翻译原书解析", analysis_lines[analysis_part_c + 1:analysis_writing], "reference"))
    parts.append(("ch01-writing-a", "第三节 应用文写作 Part A", exam_lines[writing_start:writing_part_b], "reading"))
    parts.append(("ch01-writing-a-analysis", "第四节 应用文原书解析", analysis_lines[analysis_writing + 1:analysis_part_b], "reference"))
    parts.append(("ch01-writing-b", "第五节 图画图表写作 Part B", exam_lines[writing_part_b:writing_end], "reading"))
    parts.append(("ch01-writing-b-analysis", "第六节 图画图表原书解析", analysis_lines[analysis_part_b + 1:], "reference"))

    book_title = "2024 年考研英语一翻译与写作"
    assembled: list[str] = ["# 2024 年考研英语一主观题"]
    ranges: dict[str, tuple[int, int]] = {}
    for part_id, title, content, role in parts:
        start = len(assembled) + 1
        assembled.append(f"## {title}")
        assembled.extend(content)
        end = len(assembled)
        ranges[part_id] = (start, end)
    source_text = "\n".join(assembled).rstrip() + "\n"

    source_dir = PROJECT / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    source_path = source_dir / "original.md"
    source_path.write_text(source_text, encoding="utf-8", newline="")
    images = ANALYSIS.parent / "images"
    if images.is_dir():
        # YuBook's immutable build step collects declared page assets from
        # ``pages/images`` and publishes them as the package's ``images``
        # root, matching the relative links emitted by MinerU Markdown.
        target_images = PROJECT / "pages" / "images"
        target_images.mkdir(parents=True, exist_ok=True)
        for image in images.iterdir():
            if image.is_file():
                shutil.copy2(image, target_images / image.name)

    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    line_count = len(source_path.read_text(encoding="utf-8").splitlines())
    book_id = "english-exam-2024-e1-subjective"
    title = "2024 年考研英语一翻译与写作"
    write_json(PROJECT / "book.json", {
        "schema_version": 1, "id": book_id, "title": title, "edition": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "external_source": str(EXAM), "source_sha256": source_sha,
        "domain": "english", "subject": "考研英语一", "resource_type": "reference",
        "namespace": "english.exam.2024.e1.subjective",
    })
    nodes = [{"id": "ch01", "parent_id": None, "order": 1, "kind": "chapter", "title": "第一章 2024 年考研英语一主观题", "source_line": 1}]
    pages = []
    for order, (part_id, title, content, role) in enumerate(parts, 1):
        start, end = ranges[part_id]
        kind = "supporting" if role == "reference" else "section"
        nodes.append({"id": part_id, "parent_id": "ch01", "order": order, "kind": kind, "title": title, "source_line": start})
        pages.append({"id": part_id, "node_id": part_id, "order": order, "role": role, "title": title, "start_line": start, "end_line": end})
    # The first reading page owns the book title line as in the other
    # subjective companion packages, so the page plan covers source line 1
    # without introducing a synthetic front-matter page.
    pages[0]["start_line"] = 1
    write_json(PROJECT / "outline.json", {
        "schema_version": 1,
        "book": {"id": book_id, "title": book_title, "edition": "", "identity_evidence": [{"field": "title", "line": 1, "quote": "2024 年考研英语一主观题"}]},
        "source": {"artifact": "source/original.md", "sha256": source_sha, "line_count": line_count},
        "content": {"start_line": 1, "end_line": line_count}, "nodes": nodes, "pages": pages, "issues": [],
    })
    result = subprocess.run(["python", str(ROOT / "tools" / "yubook" / "scripts" / "yubook.py"), "build", "--project", str(PROJECT)], cwd=ROOT, check=True, text=True)
    print(result)


if __name__ == "__main__":
    main()
