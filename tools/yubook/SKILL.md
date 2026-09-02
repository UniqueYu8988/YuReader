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

When one source volume contains several subjects that users should enter independently, create one bounded workspace and one stable book ID per subject. Keep the source-series title in provenance rather than adding it as a visible navigation layer. Preserve topic and 考点 headings inside their natural section: YuReader generates the page-local guide at runtime, so do not inject a duplicate hand-written contents table into the derived Markdown.

For a multi-subject OCR archive, record the exact source line range and the
shared archive SHA in every subject workspace. A subject split is a navigation
and provenance operation, not permission to rewrite prose. If a repeated
standalone series title is demonstrably a page header (for example, the same
heading between body text and a page image), remove it only through the
auditable fixed-watermark mechanism; preserve the source occurrence and report
the transformation count.

When a question bank spans several books, any generated personal-analysis
aggregate must be grouped by the individual question's stable subject label
(or knowledge namespace), never by the first question in the bank. This keeps
Obsidian backups under the matching subject even when one runtime bank serves
the whole domain.

## 通用内容处理经验（持续沉淀）

- 目录是导航证据，不是正文的替代品。先从正文第一章开始建立稳定的章/节边界，再生成页面；书前版权、课程宣传、二维码和书末索引默认归入 `reference`，不让它们占用主阅读流。
- 清洗只做高置信度、可逐行解释的变更。优先修复重复页眉、明确的 OCR 专业词、标题断裂和编号后的排版空格；普通错字、语义不确定的 OCR 和疑似表格内容原样保留，交给侧边栏 AI 结合上下文理解。
- MinerU 将标题前的装饰箭头识别为 `->>`、`>>` 或单个 `>` 时，可只在 Markdown 标题行移除箭头，保留后面的标题文字；不要对正文中的 `>`、数学符号或引用块做全局替换。
- 同一来源行可能同时命中多个规则。替换记录以 `(source_line, old)` 去重，并在构建前模拟最终结果，确保规则组合后仍是预期标题；不能只检查 replacement 列表而忽略最终派生正文。
- 不用字符数阈值强行切页。一个物理来源行中合并的多节内容无法可靠定位时，保留完整内容并在质量报告中标记 long-page warning；绝不复制、猜写或制造缺失边界。
- 若同一物理来源行内存在明确、可复现的 HTML 表格起点，可在页面中声明绝对 `start_char`/`end_char`（end-exclusive）切页；字符区间必须连续覆盖来源，必要的 `<table>` 外壳只能作为显式 `char_prefix`/`char_suffix` 结构包装，并记录在 source_map，不能改变单词或题干。
- 页面只服务于阅读和侧边栏上下文：保留原文、表格、公式、图注和来源映射，不为“看起来完整”补造图片，也不把 AI 摘要混入原书正文。每次导入前都要用最后一个候选包的 manifest、质量报告和清单做回归。
- 发布后仍要复核 `provenance.original.external_path` 指向的文件哈希；若工作区路径被后续流程替换，必须从带有正确 `original/source.md` 的旧候选或新归档重新建包，不能只手改 manifest 中的哈希来掩盖来源漂移。
- 扫描到 Unicode replacement character（`U+FFFD`）时先按重复页眉/页脚或编码损坏分组审计；没有同源证据就保留原样并记录风险，禁止逐字符臆测替换。
- 英语试卷中若出现短的非中文乱码行，同时带有明确页脚页码形态（`.1.`–`.14.`、`� 14`、`1:vf`/`14:Vf` 或 `A-14`），可逐行移除并记录 provenance；书前 20 行和没有页码证据的乱码一律保留。
- 对英文资料，可按 Passage/题型等原生边界整理；若 OCR 将“第 N 段原文”拆成多行，可依据同一 Passage 内连续编号恢复标题，但不要凭空补写段落正文。宣传页和重复书名保留在 reference，避免污染学习页面。

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

## English PDF pilot notes

For English exam material, keep the four concerns separate: the original paper, a structured objective question bank, a same-year detailed-analysis source, and subjective translation/writing reading pages. Prefer native text extraction for selectable English PDF pages; use MinerU Pipeline OCR only for image-only analysis pages and keep a per-run receipt with page count, source hash, and output hash. A question may expose the shared paper passage through optional `context_md`, but must not include the answer or detailed analysis before submission. Part-B matching questions may have A–G/H options; the option labels must still be a continuous sequence from A in the package contract. Do not treat a detailed-analysis book as a method course merely because its title contains “写作”; resource selection should prefer exact grammar/vocabulary signals, then explicit exam companions.
