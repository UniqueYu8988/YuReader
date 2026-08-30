---
name: yubook
description: Reconstruct a Markdown book's authoritative table of contents, plan readable pages, validate source coverage, and build a traceable YuReader package. Use for preparing or repairing books for YuReader; do not use for ordinary Markdown preview or note editing.
---

# Build a YuReader book

Create a book that is pleasant to navigate and safe for sidebar-AI reading. Treat the source table of contents and body headings as evidence, not as automatically trusted structure.

## Workflow

1. Run `scripts/yubook.py init` once to archive the source, calculate its hash, and produce a bounded heading inspection.
2. Confirm the book title and edition from internal title/copyright-page evidence, not from the filename. Reuse the stable ID of an existing same-title YuReader book.
3. Read the source table of contents and representative body regions. Reconstruct the complete hierarchy in `outline.json` before changing text. Default to one natural section per reading page; do not split merely because it exceeds 8,000 characters.
4. Self-audit numbering, parentage, title completeness, chapter order, supporting material, and page size.
5. Run `scripts/yubook.py validate`. Validation audits the fully derived text, not only the source or declared replacement list. Resolve structural and deterministic OCR blockers by improving the outline; do not silence them by weakening validation.
6. Run `scripts/yubook.py build` to materialize a source-preserving candidate package.
7. Inspect the resulting directory and the titles as YuReader actually flattens them. Re-scan both reading and reference pages for book-specific deterministic terms. Write final counts only from the last built package's manifest and reports, then import only after the package is genuinely usable.

Built packages record two different integrity facts: `provenance.original.sha256` authenticates the archived input, while `provenance.cleaned_candidate.sha256` authenticates the ordered reading/reference artifact set using the declared `hash_algorithm`. Never reuse the source hash as the derived-text hash after transformations.

Immutable package identity must include every publishable input: outline, archived source, `book.json` metadata, optional `knowledge-map.json`, and copied image assets. A metadata, mapping, or asset change must create a new package instead of silently reusing an older directory. Knowledge-map page IDs must resolve to real reading page keys, and copied assets must carry per-file SHA-256 declarations.

If the task asks only for a candidate, an audit, or explicitly says not to import, stop after the immutable package and final report. A passing validator never overrides that boundary. Keep one-off probes and generated diagnostics under `notes/_scratch/`; do not leave dozens of temporary scripts or stale candidate paths in the book workspace root. Before reporting completion, remove disposable scratch artifacts or clearly isolate them from the authoritative `book.json`, `outline.json`, `source/`, `notes/`, and `dist/` outputs.

## Required references

- Read [references/outline.md](references/outline.md) while reconstructing hierarchy and writing `outline.json`.
- Read [references/acceptance.md](references/acceptance.md) before accepting or importing a build.

## Commands

```powershell
python scripts/yubook.py init --source "C:\path\book.md" --book-id example-book --title "书名" --edition "第1版"
python scripts/yubook.py validate --project workspace\example-book
python scripts/yubook.py build --project workspace\example-book
python scripts/yubook.py import --package "workspace\example-book\dist\example-book-xxxxxxxx"
```

The Agent may edit only the archived working copy, `outline.json`, and generated project notes. Never edit the external source. Do not import when validation reports blockers.

## Non-negotiable boundaries

- Keep original prose, tables, formulas, captions, and images intact unless a separately recorded high-confidence fix is required.
- Do not promote labels such as `【治疗】`, `防治方法如下：`, list items, index letters, or OCR fragments into navigation nodes.
- Do not flatten chapter, section, topic, and supporting material into one level.
- Do not make the user manually review ambiguous content. Preserve uncertainty and continue when source integrity remains safe.
- Do not add new infrastructure until a real book demonstrates the need.
- If a navigation title is repaired without changing body text, retain `source_title`, the reason, and evidence line numbers in the node.
- YuBook removes only known watermark headings automatically. Record any other high-confidence full-term correction in `cleaning.text_replacements` with its exact source line, old term, new term, count, and reason.
- Treat chapter questions, references, appendices, and indexes as `reference` by default. A `supporting` node may enter the reading sequence only with a concrete `reading_reason`.
