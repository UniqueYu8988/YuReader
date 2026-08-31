#!/usr/bin/env python3
"""Assemble contiguous MinerU page chunks without losing PDF provenance.

MinerU may exhaust an 8 GB GPU when an image-only book is submitted in one
large processing window.  This helper joins successful page-range outputs in
source order, copies their hash-named assets, and writes a machine-readable
receipt.  It does not clean or reorganize the extracted prose.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path


RANGE_RE = re.compile(r"^pages-(\d+)-(\d+)$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def find_chunk_outputs(root: Path) -> list[tuple[int, int, Path, Path | None]]:
    outputs: list[tuple[int, int, Path, Path | None]] = []
    for directory in root.iterdir():
        match = RANGE_RE.fullmatch(directory.name)
        if not directory.is_dir() or not match:
            continue
        markdown = sorted(directory.rglob("*.md"))
        if len(markdown) != 1:
            raise ValueError(f"{directory}: expected exactly one MinerU Markdown, found {len(markdown)}")
        image_dirs = sorted({path.parent for path in directory.rglob("images/*") if path.is_file()})
        if len(image_dirs) > 1:
            raise ValueError(f"{directory}: found more than one images directory")
        outputs.append((int(match.group(1)), int(match.group(2)), markdown[0], image_dirs[0] if image_dirs else None))
    return sorted(outputs)


def validate_ranges(chunks: list[tuple[int, int, Path, Path | None]], expected_pages: int) -> None:
    if not chunks:
        raise ValueError("no pages-NNN-NNN chunk directories found")
    expected_start = 0
    for start, end, *_ in chunks:
        if start != expected_start or end < start:
            raise ValueError(f"non-contiguous page ranges: expected {expected_start}, found {start}-{end}")
        expected_start = end + 1
    if expected_pages and expected_start != expected_pages:
        raise ValueError(f"page coverage contains {expected_start} pages; expected {expected_pages}")


def copy_assets(chunks: list[tuple[int, int, Path, Path | None]], output: Path) -> list[dict]:
    output.mkdir(parents=True, exist_ok=True)
    assets: dict[str, dict] = {}
    for start, end, _, image_dir in chunks:
        if not image_dir:
            continue
        for source in sorted(image_dir.iterdir()):
            if not source.is_file():
                continue
            digest = sha256(source)
            target = output / source.name
            if target.exists() and sha256(target) != digest:
                raise ValueError(f"asset name collision with different content: {source.name}")
            if not target.exists():
                shutil.copy2(source, target)
            assets[source.name] = {"sha256": digest, "source_pages": [start, end]}
    return [{"path": f"images/{name}", **details} for name, details in sorted(assets.items())]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunks-root", required=True, type=Path)
    parser.add_argument("--output-md", required=True, type=Path)
    parser.add_argument("--output-images", required=True, type=Path)
    parser.add_argument("--source-pdf", required=True, type=Path)
    parser.add_argument("--expected-pages", required=True, type=int)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()

    chunks = find_chunk_outputs(args.chunks_root.resolve())
    validate_ranges(chunks, args.expected_pages)
    parts: list[str] = []
    chunk_receipts: list[dict] = []
    for start, end, markdown, _ in chunks:
        text = markdown.read_text(encoding="utf-8-sig").replace("\r\n", "\n").strip()
        parts.append(f"<!-- source-pdf-pages: {start + 1}-{end + 1} -->\n\n{text}")
        chunk_receipts.append(
            {
                "start_page_zero_based": start,
                "end_page_zero_based": end,
                "markdown": str(markdown),
                "markdown_sha256": sha256(markdown),
            }
        )

    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text("\n\n".join(parts).rstrip() + "\n", encoding="utf-8", newline="\n")
    assets = copy_assets(chunks, args.output_images)
    receipt = {
        "schema_version": 1,
        "source_pdf": str(args.source_pdf.resolve()),
        "source_pdf_sha256": sha256(args.source_pdf.resolve()),
        "page_count": args.expected_pages,
        "chunks": chunk_receipts,
        "assembled_markdown": str(args.output_md.resolve()),
        "assembled_markdown_sha256": sha256(args.output_md),
        "assets": assets,
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"pages": args.expected_pages, "chunks": len(chunks), "assets": len(assets), "markdown_sha256": receipt["assembled_markdown_sha256"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
