# YuPractice

YuReader 内孵化的极轻量题库数据规范与候选包验证器。它只定义“正式发布内容包”的数据契约，并用标准库 Python 验证 Agent 已经生成的结构化包；**不是答题界面、不是导入工具、不做 PDF/OCR/模型调用**。

本项目从 YuQuiz 已验证的原则中提取了六条边界（见文末“借鉴自 YuQuiz 的原则”），但完全不依赖 YuQuiz 的 `study.db`、运行目录或业务代码。

## 这个工具解决什么

后续 Agent 会逐步产出基础题、拔高题及其解析。为了让这些候选人能统一验证、保证可追溯、且把问题隔离在发布包之外，YuPractice 只建设数据地基：

- 一份稳定的 **question-bank 包契约**（`schema/question-bank.schema.json`）；
- 一个标准库 **验证器**（`yupractice.py validate`）；
- 两套 **最小示例**：`examples/minimal-valid/`（可通过）与 `examples/invalid/`（必须失败）；
- 一组 **自动隔离规则**：重复 ID、重复“单元＋题型＋局部题号”键、knowledge 引用悬空、source 引用不可解析、隔离区题目泄漏到正式区等，全部作为 blocker。

## 边界（重要）

- 只处理**发布内容包**。`personal_analysis`、作答历史、用户笔记、Obsidian 内容一律不写入题库包。
- 不导入真实题目、不导入正式书架、不修改 `content/` 与用户 `data/`。
- 不修改 YuReader `app.py`、`static/index.html`、`static/app.js` 及现有 UI。
- 不复制 YuQuiz 完整业务，不依赖其 `study.db`。
- 不用正则解析原始教材；本工具只验证 Agent 已产出的结构化包。
- 不引入大型框架、数据库服务、前端、任务队列或模型 API；仅 Python 标准库。

## 包结构

一个题库包是一个目录，目录名即稳定 `bank.id`：

```text
<question-bank-id>/
  manifest.json          # 包声明：schema_version、bank、sources、数量、quality
  questions.jsonl        # 正式题目，每行一个 JSON 对象
  knowledge-map.json     # 稳定知识位置 → 章节/小节路径
  source-index.json      # 来源卷 → 块级可追溯索引（页码 + 行号 + block_id）
  reports/               # validate 生成的派生报告（不参与哈希）
    validation.json
    quality-report.json
  quarantine/            # 可选：不确定 OCR/歧义题隔离区，正式区不可见
    questions.jsonl
    reasons.json
```

`reports/` 由验证器写入；`quarantine/` 由 Agent 维护。manifest 中的哈希只覆盖 `questions.jsonl`、`knowledge-map.json`、`source-index.json`；报告与隔离区文件不进哈希，但隔离区数量会与 manifest 交叉核对。

## Schema 核心字段

### manifest.json（schema_version = 1）

| 字段 | 说明 |
| --- | --- |
| `schema_version` | 契约版本，必须为 `1` |
| `bank.id` / `title` / `domain` / `subject` / `resource_type` / `status` | 稳定题库 ID、标题、领域、学科、资料类型(`question_bank`)、发布状态(`ready` 才可发布) |
| `sources[]` | 组成该题库的来源卷：`source_id`、`filename`、`sha256`、`role`(`primary/auxiliary/reference`)；支持多册共同构成一个题库 |
| `question_count` | 必须等于 `questions.jsonl` 实际行数 |
| `quarantined_count` | 必须等于 `quarantine/questions.jsonl` 实际行数 |
| `question_type_counts` | 必须与实际题型计数一致 |
| `knowledge_map.path/sha256`、`questions.path/sha256`、`source_index.path/sha256` | 包内文件路径与 SHA-256，逐文件校验 |
| `quality.status/blocker_count/warning_count` | 生成器自检声明；必须与实测一致，否则 blocker |
| `generated_at`、`generator` | 生成时间与生成器标识 |

### questions.jsonl 每行（正式题目）

| 字段 | 说明 |
| --- | --- |
| `question_id` | 稳定 ID，小写 kebab-case，全包唯一 |
| `question_type` | `single_choice` / `multiple_choice` |
| `difficulty` | `basic` / `advanced`（基础/拔高） |
| `scope` | `chapter`（章节题库）/ `comprehensive`（综合测试） |
| `unit` / `unit_key` / `local_number` | 题集标签、稳定题集键、局部题号；三者合成为“单元＋题型＋局部题号”唯一键 |
| `stem_md` | 题干（Markdown），非空 |
| `options[]` | 有序选项，标签从 `A` 连续升序且唯一，每项含 `label`、`text_md` |
| `correct_answers[]` | 选项标签的非空子集；单选必须恰好 1 个 |
| `knowledge_ids[]` | 一个或多个知识位置（如 `politics.marxism.chapter-01.section-02`），必须存在于 `knowledge-map.json` |
| `source_refs[]` | `{source_id, block_id}`，必须能在 `source-index.json` 解析（页码+行号由 block 提供，块级追溯） |
| `source_analysis_md` | **原书解析**，不可变更的发布内容；个人解析绝不写在这里 |
| `distractor_analysis_md` | 可选：按选项标签映射的原书干扰项解析 |
| `status` | 正式题目必须为 `ready` |
| `transformations[]` | 自动修复记录：`type`(如 `ocr_fix`/`term_normalization`/`separator_fix`)、`reason`，可选的 `from/to/source_line/count/verified` |

### knowledge-map.json

```jsonc
{
  "map_version": 1,
  "bank_id": "...",
  "entries": [
    {
      "knowledge_id": "politics.marxism.chapter-01.section-02",
      "label": "第一章 第二节",
      "path": ["政治", "马克思主义基本原理", "第一章", "第二节"],
      "kind": "section",          // section | chapter | comprehensive | topic
      "source_ref": {...}         // 可选：位置出处（须能在 source-index 解析，否则 W014）
    }
  ]
}
```

### source-index.json

```jsonc
{
  "index_version": 1,
  "bank_id": "...",
  "sources": [
    {
      "source_id": "...",
      "filename": "...",
      "display_name": "...",
      "sha256": "...",             // 必须与 manifest.sources 中一致
      "role": "primary",
      "blocks": [
        { "block_id": "b-0012", "page": "P3", "start_line": 231, "end_line": 233, "label": "..." }
      ]
    }
  ]
}
```

### quarantine/

- `questions.jsonl`：隔离题目，`status` 必须为 `quarantined`；ID 不得出现在正式 `questions.jsonl`（否则 E029 blocker）。
- `reasons.json`：每条隔离题必须有对应 `reason` 记录（E032）；原因应写明保留/隔离理由与置信度。
- 有隔离题目但缺 `reasons.json` 是 E031 blocker。

### 跨文件身份一致性（发布门禁）

`manifest.bank.id` 是题库包的稳定身份，以下字段必须与之严格一致，否则为 blocker：

- `knowledge-map.json.bank_id`（E039）
- `source-index.json.bank_id`（E040）
- `quarantine/reasons.json.bank_id`（E041）
- 正式题目的 `bank_id`（若该记录包含该字段，E042）
- 隔离题目的 `bank_id`（若该记录包含该字段，E043）

### source-index 完整性（发布门禁）

验证器对 `source-index.json` 做完整结构校验，以下均为 blocker：

- `index_version` 必须为当前支持版本 `1`（E038）；`sources` 必须是数组（E044）。
- 每个 source：`source_id` 非空且全包唯一（E045/E046）；`filename`/`display_name`/`sha256`/`role` 结构合法（E047）；`blocks` 必须是数组（E048）。
- 每个 block：`block_id` 非空且同一 source 内唯一（E049/E050）；`start_line`/`end_line` 必须为正整数（E051）；`start_line` 不得大于 `end_line`（E052）；`page`/`page_label` 若存在类型必须合理（E053）。
- manifest.sources 声明与 source-index 的 filename/sha256/role 一致（E012）；未索引任何 block 的声明来源为 warning（W008）。
- 题目 `source_refs` 必须能解析到唯一的 source/block（E024）。

### knowledge-map 完整性（发布门禁）

- `map_version` 必须为当前支持版本 `1`（E054）；`entries` 必须是数组（E010）。
- `knowledge_id` 唯一且语法合法（E034/E035）；`source_ref` 若存在必须能解析（W014）。
- `kind`/`path`/`label` 非法时按契约给出 warning（W015/W017/W018），不阻断但需解释。

## Blocker 规则（任意一个存在 → 退出码非 0）

| 代码 | 规则 |
| --- | --- |
| E001 | 包目录或 `manifest.json` 缺失 |
| E002 | manifest 不是合法 JSON 对象 |
| E003 | `schema_version` 不是 1 |
| E004 | `bank` 字段缺失/非法，或 `status` 不是 `ready` |
| E005 | 声明的包内文件缺失（questions/knowledge-map/source-index 或其 path 声明） |
| E006 | `questions.jsonl` 某行 JSON 解析失败 |
| E007 | `question_count` 与实测不一致 |
| E008 | `question_type_counts` 与实测不一致 |
| E009 | 包内文件 SHA-256 与 manifest 声明不一致 |
| E010 | knowledge-map 缺失/非法 JSON/缺少 entries |
| E011 | source-index 缺失/非法 JSON |
| E012 | manifest.sources 与 source-index.json 的 source 不一致或不可解析 |
| E013 | `question_id` 缺失或格式非法 |
| E014 | 全包重复 `question_id` |
| E015 | `question_type` 非法 |
| E016 | `stem_md` 缺失或为空 |
| E017 | options 不是有序数组、标签非从 A 连续升序、或选项文本为空 |
| E018 | `correct_answers` 缺失或为空 |
| E019 | `correct_answers` 含非选项标签 |
| E020 | 单选正确答案数 ≠ 1 |
| E021 | `knowledge_ids` 语法非法 |
| E022 | `knowledge_id` 不存在于 knowledge-map |
| E023 | `source_refs` 为空（必须可追溯） |
| E024 | `source_ref` 在 source-index 中不可解析 |
| E025 | `source_analysis_md` 缺失或为空 |
| E026 | 正式题目 `status` 不是 `ready` |
| E027 | `transformations` 结构非法（缺 `type` 或 `reason`） |
| E028 | 重复的“单元(unit_key)＋题型＋局部题号”键 |
| E029 | 隔离区题目出现在正式 `questions.jsonl`（隔离泄漏） |
| E030 | 隔离题 `status` 不是 `quarantined` / 隔离区重复 ID / `quarantined_count` 不一致 |
| E031 | 有隔离题目但缺少 `reasons.json` |
| E032 | 隔离题缺少对应原因记录 |
| E033 | manifest.quality 声明与实测不一致（或自相矛盾） |
| E034 | knowledge-map 重复 `knowledge_id` |
| E035 | knowledge-map 中 `knowledge_id` 语法非法 |
| E037 | 题目 JSON 行不是对象 |
| E038 | source-index 的 `index_version` 不是当前支持版本（必须为 1） |
| E039 | knowledge-map 的 `bank_id` 与 manifest.bank.id 不一致（或缺失） |
| E040 | source-index 的 `bank_id` 与 manifest.bank.id 不一致（或缺失） |
| E041 | quarantine/reasons.json 的 `bank_id` 与 manifest.bank.id 不一致（或缺失） |
| E042 | 正式题目的 `bank_id`（若存在）与 manifest.bank.id 不一致 |
| E043 | 隔离题目的 `bank_id`（若存在）与 manifest.bank.id 不一致 |
| E044 | source-index 的 `sources` 不是数组 |
| E045 | source 不是对象 / 缺少 `source_id` 或为空 |
| E046 | 重复 `source_id` |
| E047 | source 的 `filename`/`display_name`/`sha256`/`role` 缺失或格式非法 |
| E048 | source 的 `blocks` 不是数组 |
| E049 | block 不是对象 / 缺少 `block_id` 或为空 |
| E050 | 同一 source 内重复 `block_id` |
| E051 | `start_line`/`end_line` 不是正整数 |
| E052 | `start_line` 大于 `end_line` |
| E053 | `page`/`page_label` 存在但类型非法 |
| E054 | knowledge-map 的 `map_version` 不是当前支持版本（必须为 1） |
| E055 | `local_number` 已提供但不是大于等于 1 的整数 |
| E056 | 正式题干、选项或解析中残留推广、二维码等非题目内容 |
| E057 | 正式题目含图片引用，但当前题库契约尚未声明和校验资产 |

## Warning 规则（warning 存在但无 blocker 时仍可通过，退出码 0）

| 代码 | 规则 |
| --- | --- |
| W001 | knowledge-map 存在未被任何正式题引用的孤立条目 |
| W002 | 题目未关联任何知识位置 |
| W003 | 多选题只有一个正确答案（可疑）/ 隔离题缺 `correct_answers` |
| W004 | 隔离题选项文本为空 |
| W005 | `distractor_analysis_md` 存在但不是“标签→文字”对象 |
| W007 | 隔离题缺少 `stem_md`/`source_refs`/`source_analysis_md` |
| W008 | 声明来源在 source-index 中没有索引块 |
| W009 | `correct_answers` 含重复标签 |
| W010 | `difficulty` 缺失或取值未登记 |
| W011 | `scope` 取值未登记 |
| W012 | reasons 指向不存在的隔离题 |
| W013 | 缺少 `local_number` |
| W014 | knowledge-map 条目的 `source_ref` 无法在 source-index 解析 |
| W015 | knowledge-map `kind` 未登记 |
| W016 | transformations 使用未登记类型 |
| W017 | knowledge-map 条目 `path` 缺失或非法 |
| W018 | knowledge-map 条目 `label` 缺失或为空 |
| W019 | 隔离题仍含推广或二维码残留 |
| W020 | 隔离题仍含当前契约无法发布的图片引用 |

## CLI 用法

```powershell
python tools\yupractice\yupractice.py validate <题库包目录>
python tools\yupractice\yupractice.py validate <题库包目录> --json   # 同时把机器可读 JSON 打印到 stdout
```

退出码：

- `0`：无 blocker（warning 存在也通过）
- `1`：用法/运行错误
- `2`：存在 blocker

每次 validate 都会把 `reports/validation.json`（完整结果）与 `reports/quality-report.json`（精简质量报告）写入包内 `reports/`。两者都是派生报告，不参与 manifest 哈希。

## 工作流

1. Agent 从已清洗的题库样本构建结构化包：先建 `knowledge-map.json` 与 `source-index.json`，再写 `questions.jsonl`。
2. 运行 `validate`。有 blocker 时修复（不靠放宽规则）。
3. warning 由 Agent 自行解释决定保留/修复/隔离；warning 不要求用户复核。
4. `quality` 达到 0 blocker 后才允许进入后续发布流程；本工具本身不发布。

## 与 YuQuiz 的关系

YuQuiz 保持只读参考。YuPractice 借鉴了其已验证的边界原则（不复制业务）：

1. **原题解析是不可变发布内容**：`source_analysis_md` 与 `distractor_analysis_md` 属于发布包；个人解析绝不覆盖。
2. **个人解析属于用户数据**：本工具明确不处理、不写回 personal analysis 与作答历史。
3. **题目稳定 ID**：`question_id` 全包唯一、格式稳定，用于未来连接作答记录与 Obsidian 笔记。
4. **题库内容与用户状态分离**：包只含发布内容；用户状态在包外。
5. **避免覆盖 Obsidian 较新内容**：由未来 Obsidian 同步逻辑负责（参考 YuQuiz `ObsidianNoteConflict` 模式），本工具不写用户文件。
6. **没有 Obsidian 时本地功能仍可用**：题库包完全自包含，不依赖 Obsidian 配置。

## 未实现（明确不做）

- 答题 UI、模拟考试、组卷、记忆曲线；
- 真实题库导入与发布（`import` 命令不存在）；
- PDF/OCR/MinerU 调用与清洗；
- 模型 API、任务队列、数据库服务；
- personal_analysis / 作答历史 / 用户笔记的读写；
- 自动修改正式书架或 `content/`、`data/`。

## 目录

```text
tools/yupractice/
  README.md
  AGENTS.md
  schema/question-bank.schema.json
  yupractice.py
  tests/test_yupractice.py
  examples/minimal-valid/
  examples/invalid/
```
